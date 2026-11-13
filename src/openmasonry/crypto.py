"""Hashing, canonical encoding, Merkle roots and SSH signatures.

Signatures are OpenSSH signatures (`ssh-keygen -Y sign`, the same mechanism Git uses for SSH
commit signing). Every GitHub user already publishes their public keys at
https://github.com/<login>.keys, so identity needs no new infrastructure.

Two key types are accepted: `ssh-ed25519`, and `sk-ssh-ed25519@openssh.com`, the same Ed25519 key
held by a hardware token that signs only when it is touched (OpenSSH PROTOCOL.u2f).

Signing calls OpenSSH. Verifying does not: whether a signature is valid is decided by the code
in this file alone (`signature_valid`), so every platform reaches the same verdict and a
signature has exactly one accepted spelling.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from .canon import NAMESPACE


_MAX_SAFE_INT = 2**53 - 1


def _canonical_value(v) -> None:
    """Only what the protocol can carry may be encoded: objects with string keys, arrays, strings,
    booleans and integers within ±(2^53 − 1). A float or a null never reaches the hashed bytes."""
    t = type(v)
    if t is str or t is bool:
        return
    if t is int:
        if not -_MAX_SAFE_INT <= v <= _MAX_SAFE_INT:
            raise ValueError("canonical JSON: an integer is outside ±(2^53 − 1)")
    elif t is dict:
        for k, x in v.items():
            if type(k) is not str:
                raise TypeError("canonical JSON: an object key is not a string")
            _canonical_value(x)
    elif t is list:
        for x in v:
            _canonical_value(x)
    else:
        raise TypeError(f"canonical JSON: a value of type {t.__name__} cannot be encoded")


def canonical(obj) -> bytes:
    r"""The one byte string of a JSON value (SPEC §2.2): what is signed and what is hashed.

    * no whitespace: members separated by `,`, a key from its value by `:`;
    * the members of every object in ascending order of their keys, compared by Unicode code point;
    * arrays in their own order;
    * strings between `"`, escaping only `"` as `\"`, `\` as `\\`, the five short forms
      `\b \f \n \r \t` and any other character below U+0020 as `\u00XX` (lowercase hex); every other
      character is written as itself, in UTF-8;
    * integers in base 10 with no leading zero and a `-` when negative; booleans as `true` and `false`.

    The output depends on the value alone. Floats and null are refused here, and the strings of a ledger
    entry are ASCII (line feed and U+0020 to U+007E), so in an entry the only escapes that occur are
    `\"`, `\\` and `\n`, and the key order is the same by code point, by UTF-16 unit and by UTF-8 byte.
    """
    _canonical_value(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _mth(level: list[bytes], lo: int = 0, hi: int | None = None) -> bytes:
    hi = len(level) if hi is None else hi
    n = hi - lo
    if n == 1:
        return hashlib.sha256(b"\x00" + level[lo]).digest()
    k = 1 << ((n - 1).bit_length() - 1)          # largest power of two < n
    return hashlib.sha256(b"\x01" + _mth(level, lo, lo + k) + _mth(level, lo + k, hi)).digest()


def merkle_root(leaves: list[str]) -> str:
    """Merkle Tree Hash exactly as RFC 6962 §2.1 (no duplicated nodes, so no CVE-2012-2459 ambiguity)."""
    return merkle_root_bytes([bytes.fromhex(x) for x in leaves])


def merkle_root_bytes(leaves: list[bytes]) -> str:
    """`merkle_root` of leaves given as bytes rather than as hexadecimal text."""
    if not leaves:
        return sha256(b"")
    return _mth(leaves).hex()


def merkle_append(frontier: list[tuple[int, bytes]], leaf: bytes) -> None:
    """Add one leaf to the frontier of an RFC 6962 tree: the roots of its perfect subtrees, largest first,
    as `(size, hash)`, one for each 1 bit of the number of leaves. Amortized O(1) hashes per leaf."""
    node, size = hashlib.sha256(b"\x00" + leaf).digest(), 1
    while frontier and frontier[-1][0] == size:
        node, size = hashlib.sha256(b"\x01" + frontier.pop()[1] + node).digest(), size * 2
    frontier.append((size, node))


def merkle_frontier_root(frontier: list[tuple[int, bytes]]) -> str:
    """The Merkle Tree Hash of the leaves a frontier holds, in O(log n): RFC 6962 splits n leaves at the
    largest power of two below n, so its root folds the perfect subtrees from the smallest to the largest."""
    if not frontier:
        return sha256(b"")
    node = frontier[-1][1]
    for _, left in reversed(frontier[:-1]):
        node = hashlib.sha256(b"\x01" + left + node).digest()
    return node.hex()


class SigningError(RuntimeError):
    """OpenSSH could not sign (wrong passphrase, missing key, agent refused)."""


AGENT_TIMEOUT = 10        # seconds: an agent that does not answer by then is not readable (a dead forwarded socket)
SIGN_TIMEOUT = 300        # seconds to type a passphrase or touch a token: a signer that never finishes is stopped


def _agent_has(pub_line: str) -> bool:
    try:
        r = subprocess.run(["ssh-add", "-L"], capture_output=True, text=True, timeout=AGENT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False
    blob = pub_line.split()[1] if len(pub_line.split()) > 1 else ""
    return r.returncode == 0 and bool(blob) and blob in r.stdout


def sign(payload: bytes, private_key: Path) -> str:
    """Sign with OpenSSH. Prefers ssh-agent (no passphrase prompt, key never read by us).

    If the matching public key (<key>.pub) is loaded in ssh-agent, ssh-keygen signs through the
    agent. Otherwise it opens the private key file and asks for its passphrase on the terminal.
    For a hardware-backed key (`sk-ssh-ed25519@openssh.com`) the file is only a handle: ssh-keygen
    asks the token, and the token waits for a touch.
    """
    if shutil.which("ssh-keygen") is None:
        raise SigningError("ssh-keygen not found: install OpenSSH ≥ 8.1 to sign, 8.2 for a hardware key (verifying needs only Python)")
    private_key = Path(private_key).expanduser()
    pub = private_key.with_name(private_key.name + ".pub")
    use_agent = pub.exists() and _agent_has(pub.read_text())
    # A key file, a passphrase key (asked on the terminal) and a hardware handle need no agent, and ssh-keygen would
    # still ask one that SSH_AUTH_SOCK names: a silent one (a dead forwarded socket) would hold it forever.
    env = None if use_agent else {k: v for k, v in os.environ.items() if k != "SSH_AUTH_SOCK"}
    with tempfile.TemporaryDirectory() as d:
        msg = Path(d) / "msg"
        msg.write_bytes(payload)
        try:
            r = subprocess.run(
                ["ssh-keygen", "-q", "-Y", "sign", "-f", str(pub if use_agent else private_key), "-n", NAMESPACE, str(msg)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, timeout=SIGN_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise SigningError(f"ssh-keygen did not finish within {SIGN_TIMEOUT} seconds (a passphrase not typed, a "
                               "token not touched, or an ssh-agent that stopped answering): nothing was signed") from None
        if r.returncode != 0:
            hint = "" if use_agent else (f" Tip: load the key once with `ssh-add {private_key}` and sign through the agent.")
            raise SigningError(f"ssh-keygen could not sign: {r.stderr.strip() or 'exit ' + str(r.returncode)}.{hint}")
        armored = (Path(d) / "msg.sig").read_text()
    try:
        blob = base64.b64decode("".join(x for x in armored.splitlines() if not x.startswith("-----")), validate=True)
    except ValueError:
        blob = b""
    if not _canonical_blob(blob):
        raise SigningError("ssh-keygen wrote a signature this protocol does not accept: it must be made with the "
                           "sha512 hash by an ssh-ed25519 key, or by an sk-ssh-ed25519@openssh.com key of the "
                           "application ssh: with user presence (a touch)")
    return _armor(blob)


# ---------------------------------------------------------------- Ed25519 --
# RFC 8032 §5.1, verification only. A point is (X, Y, Z, T) with x = X/Z, y = Y/Z, x*y = T/Z on
# the curve -x^2 + y^2 = 1 + d*x^2*y^2 over GF(2^255 - 19) (extended coordinates).

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493        # order of the base point
_D = -121665 * pow(121666, -1, _P) % _P
_D2 = 2 * _D % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)
_ZERO = (0, 1, 1, 0)                                         # the identity


def _add(p: tuple, q: tuple) -> tuple:
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = _D2 * t1 * t2 % _P
    d = 2 * z1 * z2 % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _double(p: tuple) -> tuple:
    x1, y1, z1, _ = p
    a = x1 * x1 % _P
    b = y1 * y1 % _P
    h = a + b
    e = h - (x1 + y1) * (x1 + y1) % _P
    g = a - b
    f = 2 * z1 * z1 % _P + g
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _mul2(s: int, p: tuple, k: int, q: tuple) -> tuple:
    """[s]p + [k]q in one pass (one doubling per bit, at most one addition)."""
    table = (p, q, _add(p, q))
    acc = _ZERO
    for i in range(max(s.bit_length(), k.bit_length()) - 1, -1, -1):
        acc = _double(acc)
        pick = (s >> i & 1) | (k >> i & 1) << 1
        if pick:
            acc = _add(acc, table[pick - 1])
    return acc


def _mul(k: int, p: tuple) -> tuple:
    return _mul2(k, p, 0, _ZERO)


def _encode(p: tuple) -> bytes:
    """RFC 8032 §5.1.2: y in 255 bits, little-endian, then the low bit of x."""
    zi = pow(p[2], -1, _P)
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return (y | (x & 1) << 255).to_bytes(32, "little")


def _decode(b: bytes) -> tuple | None:
    """RFC 8032 §5.1.3, strict: a point only when `b` is the one canonical encoding of it."""
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, -1, _P) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P or (x == 0 and sign):
        return None
    if x & 1 != sign:
        x = _P - x
    return x, y, 1, x * y % _P


_B = _decode((4 * pow(5, -1, _P) % _P).to_bytes(32, "little"))          # the base point


_POINTS: dict[bytes, tuple] = {}    # the valid keys this process has met, each validated once


def _key_point(raw: bytes) -> tuple | None:
    """The point of a public key, only if it is canonically encoded and has order exactly L.

    Honest keys are [a]B, so they always pass. Refusing every other point (the identity, the
    seven other points of small order, and any point with such a component) removes the keys
    anyone can sign for, and the keys on which two correct verifiers could disagree.

    The check costs one scalar multiplication. A key that passed is remembered for the life of the
    process and never checked again, however many keys a ledger holds: there is no bound past which
    replay starts to validate every key anew. A key that failed is not remembered (replay stops at it).
    """
    a = _POINTS.get(raw)
    if a is None:
        a = _decode(raw)
        if a is None or a[:2] == (0, 1):
            return None
        x, y, z, _ = _mul(_L, a)
        if not (x == 0 and y == z):
            return None
        _POINTS[raw] = a
    return a


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7, the strict form without the cofactor: [S]B = R + [k]A, with S < L.

    The left side minus [k]A is encoded and compared with the 32 bytes of R, so R is accepted
    only as the canonical encoding of that exact point.
    """
    a = _key_point(public_key)
    if a is None or len(signature) != 64:
        return False
    r, s = signature[:32], int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(hashlib.sha512(r + public_key + message).digest(), "little") % _L
    minus_a = (-a[0] % _P, a[1], a[2], -a[3] % _P)
    return _encode(_mul2(s, _B, k, minus_a)) == r


# ----------------------------------------------------------------- SSHSIG --
# OpenSSH PROTOCOL.sshsig, narrowed to two key types, one namespace and one hash. A hardware-backed key
# (PROTOCOL.u2f) is the same Ed25519 point inside another key blob, and its signature carries two more
# fields, the flags and the counter of the token, which are signed.

HASH = "sha512"                     # what `ssh-keygen -Y sign` uses unless told otherwise
_BEGIN, _END = "-----BEGIN SSH SIGNATURE-----\n", "-----END SSH SIGNATURE-----\n"


def _string(b: bytes) -> bytes:
    return struct.pack(">I", len(b)) + b


PLAIN, SK = "ssh-ed25519", "sk-ssh-ed25519@openssh.com"      # the two key types
SK_APPLICATION = b"ssh:"            # the only application of a hardware-backed key this protocol accepts
SK_USER_PRESENT = 0x01              # the flag a token sets when it was touched for this signature
_KEY_HEAD = _string(PLAIN.encode()) + struct.pack(">I", 32)
_SK_HEAD = _string(SK.encode()) + struct.pack(">I", 32)
_SK_TAIL = _string(SK_APPLICATION)


def _key_blob(sk: bool, raw: bytes) -> bytes:
    """The OpenSSH public key blob of the 32 key bytes `raw`, plain (51 bytes) or hardware-backed (74)."""
    return _SK_HEAD + raw + _SK_TAIL if sk else _KEY_HEAD + raw


def _key_form(key: str) -> tuple[bool, bytes] | None:
    """(hardware-backed?, the 32 key bytes) of a bare `<type> <base64>` line in its one text form: the base64
    is the one canonical encoding of the exact blob of its type. The bytes are not checked to be a point."""
    if not isinstance(key, str):
        return None
    for sk, name in ((False, PLAIN), (True, SK)):
        if key.startswith(name + " "):
            b64 = key[len(name) + 1:]
            try:
                blob = base64.b64decode(b64, validate=True)
            except ValueError:
                return None
            raw = blob[len(_SK_HEAD):len(_SK_HEAD) + 32] if sk else blob[len(_KEY_HEAD):]
            if base64.b64encode(blob).decode() != b64 or len(raw) != 32 or blob != _key_blob(sk, raw):
                return None
            return sk, raw
    return None


def _parse_key(key: str) -> tuple[bool, bytes] | None:
    """`_key_form`, or None unless the key is valid: the bytes are also a point of order L."""
    form = _key_form(key)
    return form if form is not None and _key_point(form[1]) is not None else None


def key_bytes(key: str) -> bytes | None:
    """The 32 bytes a key line carries, decoded and not validated as a point. For a key that was validated
    when it entered a state (`valid_public_key`) these are the bytes of its point, at the cost of a base64
    decode; for any other string the result proves nothing."""
    form = _key_form(key)
    return form[1] if form is not None else None


def valid_public_key(key: str) -> bool:
    """A bare `ssh-ed25519 <base64>` or `sk-ssh-ed25519@openssh.com <base64>` line in its one text form, whose
    32 key bytes are a canonical point of order L (and, for the second type, whose application is `ssh:`)."""
    return _parse_key(key) is not None


def public_point(key: str) -> bytes | None:
    """The 32 bytes of the Ed25519 point of a valid key of either type; None for anything else. Two keys are
    the same key when their points are equal, whatever their types."""
    parsed = _parse_key(key)
    return parsed[1] if parsed is not None else None


def _armor(blob: bytes) -> str:
    """The one accepted text form: what `ssh-keygen -Y sign` writes (70 columns, LF, final LF)."""
    b64 = base64.b64encode(blob).decode()
    return _BEGIN + "".join(b64[i:i + 70] + "\n" for i in range(0, len(b64), 70)) + _END


def _dearmor(signature: str) -> bytes | None:
    """The blob of a canonically armored signature; None for any other spelling of it."""
    if not (isinstance(signature, str) and signature.startswith(_BEGIN) and signature.endswith(_END)):
        return None
    try:
        blob = base64.b64decode(signature[len(_BEGIN):-len(_END)].replace("\n", ""), validate=True)
    except ValueError:
        return None
    return blob if _armor(blob) == signature else None


def _sshsig(raw_key: bytes, sig: bytes) -> bytes:
    """The only blob that carries the Ed25519 signature `sig` by the plain key `raw_key` in this protocol."""
    return (b"SSHSIG" + struct.pack(">I", 1) + _string(_KEY_HEAD + raw_key) + _string(NAMESPACE.encode())
            + _string(b"") + _string(HASH.encode()) + _string(_string(PLAIN.encode()) + _string(sig)))


def _sshsig_sk(raw_key: bytes, sig: bytes, flags: bytes, counter: bytes) -> bytes:
    """The only blob that carries the signature `sig` of the hardware-backed key `raw_key`, made with these
    flags (one byte) and this counter (four bytes, big-endian), in this protocol."""
    return (b"SSHSIG" + struct.pack(">I", 1) + _string(_key_blob(True, raw_key)) + _string(NAMESPACE.encode())
            + _string(b"") + _string(HASH.encode())
            + _string(_string(SK.encode()) + _string(sig) + flags + counter))


def _sk_fields(blob: bytes) -> tuple[bytes, bytes, bytes]:
    """(signature, flags, counter) as the last 69 bytes of a hardware-key blob hold them."""
    return blob[-69:-5], blob[-5:-4], blob[-4:]


def _sk_signed(payload: bytes, flags: bytes, counter: bytes) -> bytes:
    """What a token signs (PROTOCOL.u2f): the application, its flags and counter, and the SSHSIG signed data."""
    return (hashlib.sha256(SK_APPLICATION).digest() + flags + counter
            + hashlib.sha256(_signed_data(payload)).digest())


def _canonical_blob(blob: bytes) -> bool:
    """`blob` is, for the key it names, a blob `signature_valid` could accept: the exact template of one of
    the two key types and, for a hardware-backed key, with the user-presence flag set."""
    if blob == _sshsig(blob[33:65], blob[-64:]):
        return True
    sig, flags, counter = _sk_fields(blob)
    return blob == _sshsig_sk(blob[48:80], sig, flags, counter) and bool(flags[0] & SK_USER_PRESENT)


def _signed_data(payload: bytes) -> bytes:
    """What the key actually signs: the namespace and the hash of the payload, never the payload itself."""
    return (b"SSHSIG" + _string(NAMESPACE.encode()) + _string(b"") + _string(HASH.encode())
            + _string(hashlib.new(HASH, payload).digest()))


def signature_valid(payload: bytes, signature: str, public_key: str) -> bool:
    """The protocol's whole definition of a valid signature. Pure: no files, no programs.

    `signature` must be byte for byte the canonical armor of the canonical blob for
    `public_key`, and the Ed25519 signature inside must verify strictly. A hardware-backed key signs
    with its flags and counter, and its signature counts only when the token reports user presence.
    """
    parsed, blob = _parse_key(public_key), _dearmor(signature)
    if parsed is None or blob is None:
        return False
    sk, raw = parsed
    if not sk:
        return blob == _sshsig(raw, blob[-64:]) and ed25519_verify(raw, _signed_data(payload), blob[-64:])
    sig, flags, counter = _sk_fields(blob)
    if blob != _sshsig_sk(raw, sig, flags, counter) or not flags[0] & SK_USER_PRESENT:
        return False
    return ed25519_verify(raw, _sk_signed(payload, flags, counter), sig)


_CACHE = Path(os.environ.get("OM_CACHE", Path.home() / ".cache" / "openmasonry" / "verified"))
_CACHE_KEY = Path(os.environ.get("OM_HOME", Path.home() / ".config" / "openmasonry")) / "cache.key"


def _private_ok(p: Path) -> bool:
    """Owned by us and not writable by group or others (else the cache is not trusted)."""
    try:
        st = p.stat()
    except OSError:
        return False
    return st.st_uid == os.getuid() and not (st.st_mode & 0o022)


def _cache_secret() -> bytes | None:
    try:
        if not _CACHE_KEY.exists():
            _CACHE_KEY.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(_CACHE_KEY.parent, 0o700)
            fd = os.open(_CACHE_KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(os.urandom(32))
        if not (_private_ok(_CACHE_KEY) and _private_ok(_CACHE_KEY.parent)):
            return None
        return _CACHE_KEY.read_bytes()
    except OSError:
        return None


def _cache_key(payload: bytes, signature: str, login: str, public_key: str) -> str:
    return hashlib.sha256(b"\0".join([payload, signature.encode(), login.encode(), public_key.encode()])).hexdigest()


def verify(payload: bytes, signature: str, login: str, public_key: str) -> bool:
    """`signature_valid`, memoized per machine for speed (`login` only names the cache entry).

    A cached success is a file holding HMAC(machine secret, check key): writing a bare file is not
    enough to make a forged entry verify. Directories must be owned by us and not group/world
    writable. The CI, witnesses and the Tyler officer run with OM_NO_CACHE=1 and verify everything.
    """
    if not (isinstance(signature, str) and signature.isascii()):
        return False
    secret = None if os.environ.get("OM_NO_CACHE") else _cache_secret()
    k = _cache_key(payload, signature, login, public_key)
    tag = hmac.new(secret, k.encode(), hashlib.sha256).hexdigest() if secret else ""
    marker = _CACHE / k[:2] / k
    if secret and marker.exists() and _private_ok(_CACHE):
        try:
            if hmac.compare_digest(marker.read_text().strip(), tag):
                return True
        except OSError:
            pass
    ok = signature_valid(payload, signature, public_key)
    if ok and secret:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(_CACHE, 0o700)
            os.chmod(marker.parent, 0o700)
            marker.write_text(tag)
        except OSError:
            pass
    return ok

