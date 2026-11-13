"""Signature tests: validity is decided by protocol code alone, and `sig` has one byte form.

The verifier is pure Python (openmasonry.crypto). OpenSSH is used here only as a signer and as
a reference to compare against; those tests are skipped when ssh-keygen is not installed.

Run: PYTHONPATH=src python3 -m unittest tests.test_signatures -v
"""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openmasonry import crypto, ledger
from openmasonry.ledger import Invalid, ed25519, entry_hash, replay, signed_payload

HAVE_SSH = shutil.which("ssh-keygen") is not None
NS = b"openmasonry"
SK = b"sk-ssh-ed25519@openssh.com"
APP = b"ssh:"
UP, UV = 0x01, 0x04                 # FIDO flags: user present, user verified
P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
IDENTITY = b"\x01" + bytes(31)
MESSAGES = [b"", b"a", b"hello", b"\x00\xff" * 40, "日本 ✓".encode(), b"x" * 10_000]


# ---------------------------------------------------------------- helpers --

def s(b: bytes) -> bytes:
    """An SSH `string`: 4-byte big-endian length, then the bytes."""
    return struct.pack(">I", len(b)) + b


def blob(pub: bytes, sig: bytes, namespace: bytes = NS, hashalg: bytes = b"sha512", version: int = 1,
         reserved: bytes = b"", keytype: bytes = b"ssh-ed25519", sigtype: bytes = b"ssh-ed25519",
         tail: bytes = b"") -> bytes:
    return (b"SSHSIG" + struct.pack(">I", version) + s(s(keytype) + s(pub)) + s(namespace) + s(reserved)
            + s(hashalg) + s(s(sigtype) + s(sig)) + tail)


def to_be_signed(msg: bytes, namespace: bytes = NS, hashalg: str = "sha512", reserved: bytes = b"") -> bytes:
    return b"SSHSIG" + s(namespace) + s(reserved) + s(hashalg.encode()) + s(hashlib.new(hashalg, msg).digest())


def armor(raw: bytes, width: int = 70, nl: str = "\n", end: str = "\n") -> str:
    b64 = base64.b64encode(raw).decode()
    lines = [b64[i:i + width] for i in range(0, len(b64), width)] if width else [b64]
    return nl.join(["-----BEGIN SSH SIGNATURE-----", *lines, "-----END SSH SIGNATURE-----"]) + end


def dearmor(sig: str) -> bytes:
    return base64.b64decode("".join(sig.split("\n")[1:-2]))


def keyline(pub: bytes) -> str:
    return "ssh-ed25519 " + base64.b64encode(s(b"ssh-ed25519") + s(pub)).decode()


def raw_key(line: str) -> bytes:
    return base64.b64decode(line.split()[1])[-32:]


def flip(b: bytes, i: int, bit: int = 0) -> bytes:
    return b[:i] + bytes([b[i] ^ (1 << bit)]) + b[i + 1:]


def keypair(seed: bytes) -> tuple[int, bytes, bytes]:
    """RFC 8032 §5.1.5: (secret scalar, prefix, public key)."""
    h = hashlib.sha512(seed).digest()
    a = (int.from_bytes(h[:32], "little") & ((1 << 254) - 8)) | (1 << 254)
    return a, h[32:], crypto._encode(crypto._mul(a, crypto._B))


def sign_raw(seed: bytes, msg: bytes) -> tuple[bytes, bytes]:
    """RFC 8032 §5.1.6, written here so the tests do not need OpenSSH: (public key, signature)."""
    a, prefix, pub = keypair(seed)
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % L
    big_r = crypto._encode(crypto._mul(r, crypto._B))
    k = int.from_bytes(hashlib.sha512(big_r + pub + msg).digest(), "little") % L
    return pub, big_r + ((r + k * a) % L).to_bytes(32, "little")


def sign_entry(seed: bytes, payload: bytes, **fields) -> tuple[str, str]:
    """(key line, armored SSHSIG) made without OpenSSH. `fields` bend the signed structure and the blob."""
    tbs = {k: v for k, v in fields.items() if k in ("namespace", "hashalg", "reserved")}
    if "hashalg" in tbs:
        tbs["hashalg"] = tbs["hashalg"].decode()
    pub, sig = sign_raw(seed, to_be_signed(payload, **tbs))
    return keyline(pub), armor(blob(pub, sig, **fields))


def mutations(payload: bytes, sig: str, key: str) -> list[tuple[str, bytes, str, str]]:
    """Every way we know to bend a valid (payload, sig, key) without the private key."""
    raw = dearmor(sig)
    pub, ed = raw_key(key), raw[-64:]
    r, sc = ed[:32], int.from_bytes(ed[32:], "little")
    b64 = base64.b64encode(raw).decode()
    body = sig.split("\n", 1)[1]
    out = [
        ("message: one bit flipped", flip(payload, 0) if payload else b"\x01", sig, key),
        ("message: one byte appended", payload + b"\n", sig, key),
        ("R: one bit flipped", payload, armor(raw[:-64] + flip(r, 3) + ed[32:]), key),
        ("S: one bit flipped", payload, armor(raw[:-32] + flip(ed[32:], 5)), key),
        ("S replaced by S + L", payload, armor(raw[:-32] + (sc + L).to_bytes(32, "little")), key),
        ("key in the blob: one bit flipped", payload, armor(blob(flip(pub, 7), ed)), key),
        ("expected key: one bit flipped", payload, sig, keyline(flip(pub, 7))),
        ("key flipped in the blob and expected", payload, armor(blob(flip(pub, 7), ed)), keyline(flip(pub, 7))),
        ("armor: base64 on one line", payload, armor(raw, width=0), key),
        ("armor: base64 wrapped at 10 columns", payload, armor(raw, width=10), key),
        ("armor: base64 wrapped at 76 columns", payload, armor(raw, width=76), key),
        ("armor: CRLF line endings", payload, armor(raw, nl="\r\n", end="\r\n"), key),
        ("armor: spaces inside the base64", payload, sig.replace(b64[:8], b64[:4] + " " + b64[4:8]), key),
        ("armor: trailing space on a line", payload, sig.replace(b64[:70] + "\n", b64[:70] + " \n"), key),
        ("armor: blank line after BEGIN", payload, sig.replace("-----\n", "-----\n\n", 1), key),
        ("armor: text after END", payload, sig + "extra\n", key),
        ("armor: text before BEGIN", payload, "extra\n" + sig, key),
        ("armor: blank line before BEGIN", payload, "\n" + sig, key),
        ("armor: no final newline", payload, sig[:-1], key),
        ("armor: two final newlines", payload, sig + "\n", key),
        ("armor: padding removed", payload, sig.replace("==\n", "\n"), key),
        ("armor: non-zero padding bits", payload, sig.replace(b64[-4:], b64[-4] + chr(ord(b64[-3]) + 1) + "=="), key),
        ("armor: lower-case BEGIN line", payload, "-----begin ssh signature-----\n" + body, key),
        ("blob: trailing bytes", payload, armor(raw + b"\x00"), key),
        ("blob: trailing bytes inside the signature field", payload, armor(raw[:-83] + s(raw[-79:] + b"\x00")), key),
        ("blob: hash label sha256", payload, armor(blob(pub, ed, hashalg=b"sha256")), key),
        ("blob: version 2", payload, armor(blob(pub, ed, version=2)), key),
        ("blob: reserved field not empty", payload, armor(blob(pub, ed, reserved=b"x")), key),
        ("blob: namespace file", payload, armor(blob(pub, ed, namespace=b"file")), key),
        ("blob: magic SSHSIH", payload, armor(b"SSHSIH" + raw[6:]), key),
        ("blob: empty", payload, armor(b""), key),
        ("sig: empty string", payload, "", key),
    ]
    assert all(m[1:] != (payload, sig, key) for m in out), "a mutation left the triple unchanged"
    return out


# -- hardware-backed keys (sk-ssh-ed25519@openssh.com), built from software keys: no token is needed --

def sk_keyblob(pub: bytes, app: bytes = APP, keytype: bytes = SK) -> bytes:
    return s(keytype) + s(pub) + s(app)


def sk_keyline(pub: bytes, app: bytes = APP) -> str:
    return SK.decode() + " " + base64.b64encode(sk_keyblob(pub, app)).decode()


def sk_raw_key(line: str) -> bytes:
    return base64.b64decode(line.split()[1])[34:66]


def sk_blob(pub: bytes, sig: bytes, flags: int = UP, counter: int = 0, app: bytes = APP, namespace: bytes = NS,
            hashalg: bytes = b"sha512", version: int = 1, reserved: bytes = b"", keytype: bytes = SK,
            sigtype: bytes = SK, trailer: bytes | None = None, inner_tail: bytes = b"", tail: bytes = b"") -> bytes:
    """PROTOCOL.u2f inside PROTOCOL.sshsig: the signature field is string type, string sig, byte flags, uint32
    counter. `trailer` replaces the five bytes of flags and counter."""
    field = (s(sigtype) + s(sig) + (bytes([flags]) + struct.pack(">I", counter) if trailer is None else trailer)
             + inner_tail)
    return (b"SSHSIG" + struct.pack(">I", version) + s(sk_keyblob(pub, app, keytype)) + s(namespace) + s(reserved)
            + s(hashalg) + s(field) + tail)


def sk_signed(msg: bytes, flags: int = UP, counter: int = 0, app: bytes = APP, **tbs) -> bytes:
    """What the token signs: SHA256(application) || flags || counter || SHA256(the SSHSIG signed data)."""
    return (hashlib.sha256(app).digest() + bytes([flags]) + struct.pack(">I", counter)
            + hashlib.sha256(to_be_signed(msg, **tbs)).digest())


def sk_sign_entry(seed: bytes, payload: bytes, flags: int = UP, counter: int = 0, app: bytes = APP,
                  **fields) -> tuple[str, str]:
    """(sk key line, armored SSHSIG) as a token holding `seed` would make them. `fields` bend the structure."""
    tbs = {k: v for k, v in fields.items() if k in ("namespace", "hashalg", "reserved")}
    if "hashalg" in tbs:
        tbs["hashalg"] = tbs["hashalg"].decode()
    pub, sig = sign_raw(seed, sk_signed(payload, flags, counter, app, **tbs))
    return sk_keyline(pub, app), armor(sk_blob(pub, sig, flags, counter, app, **fields))


def sk_mutations(payload: bytes, sig: str, key: str) -> list[tuple[str, bytes, str, str]]:
    """Every way we know to bend a valid hardware-key (payload, sig, key) without the private key."""
    raw = dearmor(sig)
    pub, ed, flags, counter = sk_raw_key(key), raw[-69:-5], raw[-5], int.from_bytes(raw[-4:], "big")
    sc = int.from_bytes(ed[32:], "little")
    b64 = base64.b64encode(raw).decode()
    again = lambda **kw: armor(sk_blob(pub, **{"sig": ed, "flags": flags, "counter": counter, **kw}))
    out = [
        ("message: one bit flipped", flip(payload, 0) if payload else b"\x01", sig, key),
        ("message: one byte appended", payload + b"\n", sig, key),
        ("R: one bit flipped", payload, again(sig=flip(ed, 3)), key),
        ("S: one bit flipped", payload, again(sig=flip(ed, 37)), key),
        ("S replaced by S + L", payload, again(sig=ed[:32] + (sc + L).to_bytes(32, "little")), key),
        ("counter: one more", payload, again(counter=(counter + 1) % 2**32), key),
        ("counter: zeroed", payload, again(counter=0 if counter else 1), key),
        ("flags: user presence cleared", payload, again(flags=flags & ~UP), key),
        ("flags: user verification toggled", payload, again(flags=flags ^ UV), key),
        ("flags: every bit set", payload, again(flags=0xff if flags != 0xff else 0x7f), key),
        ("key in the blob: one bit flipped", payload, armor(sk_blob(flip(pub, 7), ed, flags, counter)), key),
        ("expected key: one bit flipped", payload, sig, sk_keyline(flip(pub, 7))),
        ("key flipped in the blob and expected", payload, armor(sk_blob(flip(pub, 7), ed, flags, counter)),
         sk_keyline(flip(pub, 7))),
        ("application in the blob: ssh:x", payload, again(app=b"ssh:x"), key),
        ("application in the blob and expected: ssh:x", payload, again(app=b"ssh:x"), sk_keyline(pub, b"ssh:x")),
        ("application in the blob: empty", payload, again(app=b""), key),
        ("expected key: the same point as a plain ssh-ed25519 key", payload, sig, keyline(pub)),
        ("blob: the plain ssh-ed25519 template around the same signature", payload, armor(blob(pub, ed)), key),
        ("blob: key type ssh-ed25519", payload, again(keytype=b"ssh-ed25519"), key),
        ("blob: signature type ssh-ed25519", payload, again(sigtype=b"ssh-ed25519"), key),
        ("blob: flags and counter dropped", payload, again(trailer=b""), key),
        ("blob: a counter of three bytes", payload, again(trailer=bytes([flags]) + bytes(3)), key),
        ("blob: trailing bytes", payload, again(tail=b"\x00"), key),
        ("blob: trailing bytes after the counter", payload, again(inner_tail=b"\x00"), key),
        ("blob: trailing bytes inside the signature string", payload, again(sig=ed + b"\x00"), key),
        ("blob: hash label sha256", payload, again(hashalg=b"sha256"), key),
        ("blob: version 2", payload, again(version=2), key),
        ("blob: reserved field not empty", payload, again(reserved=b"x"), key),
        ("blob: namespace file", payload, again(namespace=b"file"), key),
        ("blob: magic SSHSIH", payload, armor(b"SSHSIH" + raw[6:]), key),
        ("armor: base64 on one line", payload, armor(raw, width=0), key),
        ("armor: base64 wrapped at 76 columns", payload, armor(raw, width=76), key),
        ("armor: CRLF line endings", payload, armor(raw, nl="\r\n", end="\r\n"), key),
        ("armor: trailing space on a line", payload, sig.replace(b64[:70] + "\n", b64[:70] + " \n"), key),
        ("armor: text after END", payload, sig + "extra\n", key),
        ("armor: no final newline", payload, sig[:-1], key),
        ("armor: two final newlines", payload, sig + "\n", key),
    ]
    assert all(m[1:] != (payload, sig, key) for m in out), "a mutation left the triple unchanged"
    return out


def openssh_knows_sk() -> bool:
    """Whether the installed OpenSSH knows the key type at all (it needs no token to verify)."""
    if not HAVE_SSH or shutil.which("ssh") is None:
        return False
    r = subprocess.run(["ssh", "-Q", "key"], capture_output=True, text=True)
    return r.returncode == 0 and SK.decode() in r.stdout.split()


def ssh_verify(payload: bytes, signature: str, key: str) -> bool:
    """What the installed OpenSSH says (the rule this project used to rely on)."""
    with tempfile.TemporaryDirectory() as d:
        signers = Path(d) / "allowed_signers"
        signers.write_text(f'x namespaces="openmasonry" {key}\n')
        sig = Path(d) / "sig"
        sig.write_bytes(signature.encode())
        r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", "x", "-n", "openmasonry",
                            "-s", str(sig)], input=payload, capture_output=True)
        return r.returncode == 0


def ssh_key(tmp: Path, name: str) -> tuple[Path, str]:
    path = tmp / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(path)], check=True)
    pub = path.with_suffix(".pub").read_text().split()
    return path, f"{pub[0]} {pub[1]}"


def ssh_sign(tmp: Path, key: Path, payload: bytes, *options: str, namespace: str = "openmasonry") -> str:
    msg = tmp / "msg"
    msg.write_bytes(payload)
    (tmp / "msg.sig").unlink(missing_ok=True)
    subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", namespace, *options, str(msg)],
                   check=True, capture_output=True)
    return (tmp / "msg.sig").read_bytes().decode()


def ssh_sign_sha256(tmp: Path, key: Path, payload: bytes) -> str | None:
    """A genuine signature with the other hash; None on an OpenSSH too old to choose it (before 8.9)."""
    try:
        return ssh_sign(tmp, key, payload, "-O", "hashalg=sha256")
    except subprocess.CalledProcessError:
        return None


def check(payload: bytes, sig: str, key: str) -> bool:
    return crypto.signature_valid(payload, sig, key)


# ------------------------------------------------------------------ tests --

class Ed25519Math(unittest.TestCase):
    def test_base_point_encoding(self):
        self.assertEqual(crypto._encode(crypto._B), bytes.fromhex("58" + "66" * 31))

    def test_group_order(self):
        self.assertEqual(crypto._encode(crypto._mul(L, crypto._B)), IDENTITY)
        self.assertEqual(crypto._encode(crypto._mul(L + 1, crypto._B)), crypto._encode(crypto._B))
        self.assertEqual(crypto._encode(crypto._mul(0, crypto._B)), IDENTITY)

    def test_addition_and_doubling_agree(self):
        b = crypto._B
        self.assertEqual(crypto._encode(crypto._add(b, b)), crypto._encode(crypto._mul(2, b)))
        self.assertEqual(crypto._encode(crypto._add(crypto._mul(5, b), crypto._mul(7, b))),
                         crypto._encode(crypto._mul(12, b)))

    def test_decode_is_the_inverse_of_encode(self):
        for k in (1, 2, 3, 2**200 + 9, L - 1):
            enc = crypto._encode(crypto._mul(k, crypto._B))
            self.assertEqual(crypto._encode(crypto._decode(enc)), enc)

    def test_rfc8032_test_vector_1(self):
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        pub = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertEqual(sign_raw(seed, b""), (pub, sig))
        self.assertTrue(crypto.ed25519_verify(pub, b"", sig))
        self.assertFalse(crypto.ed25519_verify(pub, b"x", sig))

    def test_own_signatures(self):
        for i, msg in enumerate(MESSAGES):
            pub, sig = sign_raw(bytes([i]) * 32, msg)
            self.assertTrue(crypto.ed25519_verify(pub, msg, sig))
            self.assertFalse(crypto.ed25519_verify(pub, msg + b"!", sig))
            self.assertFalse(crypto.ed25519_verify(pub, msg, flip(sig, 0)))
            self.assertFalse(crypto.ed25519_verify(pub, msg, flip(sig, 40)))

    def test_s_must_be_below_the_group_order(self):
        pub, sig = sign_raw(b"k" * 32, b"m")
        sc = int.from_bytes(sig[32:], "little")
        self.assertFalse(crypto.ed25519_verify(pub, b"m", sig[:32] + (sc + L).to_bytes(32, "little")))
        self.assertFalse(crypto.ed25519_verify(pub, b"m", sig[:32] + L.to_bytes(32, "little")))

    def test_r_must_be_canonical(self):
        """A signature whose R is the identity is valid; the same R written as y = p + 1 is not."""
        a, _, pub = keypair(b"r" * 32)
        for msg in (b"m", b""):
            k = int.from_bytes(hashlib.sha512(IDENTITY + pub + msg).digest(), "little") % L
            self.assertTrue(crypto.ed25519_verify(pub, msg, IDENTITY + (k * a % L).to_bytes(32, "little")))
            odd = (P + 1).to_bytes(32, "little")
            k = int.from_bytes(hashlib.sha512(odd + pub + msg).digest(), "little") % L
            self.assertFalse(crypto.ed25519_verify(pub, msg, odd + (k * a % L).to_bytes(32, "little")))

    def test_wrong_lengths(self):
        pub, sig = sign_raw(b"k" * 32, b"m")
        self.assertFalse(crypto.ed25519_verify(pub, b"m", sig[:63]))
        self.assertFalse(crypto.ed25519_verify(pub, b"m", sig + b"\x00"))
        self.assertFalse(crypto.ed25519_verify(pub[:31], b"m", sig))


class PublicKeys(unittest.TestCase):
    def bad(self, pub: bytes, why: str):
        self.assertFalse(crypto.valid_public_key(keyline(pub)), why)
        self.assertFalse(ed25519(keyline(pub)), why)

    def test_honest_keys(self):
        for i in range(4):
            line = keyline(keypair(bytes([i]) * 32)[2])
            self.assertTrue(crypto.valid_public_key(line))
            self.assertTrue(ed25519(line))

    def test_non_canonical_encodings(self):
        self.bad(P.to_bytes(32, "little"), "y = p (another spelling of y = 0)")
        self.bad((P + 1).to_bytes(32, "little"), "y = p + 1 (another spelling of the identity)")
        self.bad((2**255 - 1).to_bytes(32, "little"), "y = 2^255 - 1")
        self.bad(flip(IDENTITY, 31, 7), "x = 0 with the sign bit set")

    def test_not_on_the_curve(self):
        d = -121665 * pow(121666, -1, P) % P
        y = next(y for y in range(2, 100)
                 if pow((y * y - 1) * pow(d * y * y + 1, -1, P) % P, (P - 1) // 2, P) == P - 1)
        self.bad(y.to_bytes(32, "little"), f"y = {y} has no x on the curve")

    def test_points_outside_the_prime_order_group(self):
        self.bad(IDENTITY, "the identity")
        self.bad((P - 1).to_bytes(32, "little"), "the point of order 2")
        self.bad(bytes(32), "a point of order 4")
        order4 = crypto._decode(bytes(32))
        mixed = crypto._encode(crypto._add(crypto._mul(7, crypto._B), order4))
        self.assertIsNotNone(crypto._decode(mixed))
        self.bad(mixed, "an honest point plus a point of order 4")

    def test_key_line_format(self):
        pub = keypair(b"f" * 32)[2]
        good = keyline(pub)
        b64 = lambda raw: base64.b64encode(raw).decode()
        for line in (good + " comment", good + "\n", " " + good, good.replace(" ", "  "), good[:-1], good + "A",
                     "ssh-rsa " + good.split()[1],
                     "ssh-ed25519 " + b64(s(b"ssh-ed25518") + s(pub)),
                     "ssh-ed25519 " + b64(s(b"ssh-ed25519") + struct.pack(">I", 31) + pub),
                     "ssh-ed25519 " + b64(b"\x00" * 51), None, 7, b"ssh-ed25519"):
            self.assertFalse(ed25519(line), repr(line))
            if isinstance(line, str):
                self.assertFalse(crypto.valid_public_key(line), repr(line))

    def test_a_signature_under_an_invalid_key_is_refused(self):
        """Anyone can 'sign' for the identity key (R = [S]B for any S), so the key itself is refused."""
        sc = 12345
        r = crypto._encode(crypto._mul(sc, crypto._B))
        sig = r + sc.to_bytes(32, "little")
        self.assertFalse(crypto.ed25519_verify(IDENTITY, b"m", sig))
        self.assertFalse(check(b"m", armor(blob(IDENTITY, sig)), keyline(IDENTITY)))


class Canonical(unittest.TestCase):
    """No OpenSSH needed: signatures are made by the RFC 8032 signer above."""

    def setUp(self):
        self.payload = b'{"actor":"hiram","seq":0}'
        self.key, self.sig = sign_entry(b"s" * 32, self.payload)

    def test_valid(self):
        self.assertTrue(check(self.payload, self.sig, self.key))
        for i, msg in enumerate(MESSAGES):
            key, sig = sign_entry(bytes([i + 1]) * 32, msg)
            self.assertTrue(check(msg, sig, key))

    def test_canonical_armor(self):
        self.assertEqual(crypto._armor(dearmor(self.sig)), self.sig)
        lines = self.sig.split("\n")
        self.assertEqual(lines[0], "-----BEGIN SSH SIGNATURE-----")
        self.assertEqual([len(x) for x in lines[1:]], [70, 70, 70, 34, 27, 0])
        self.assertEqual(len(dearmor(self.sig)), 181)

    def test_every_mutation_is_refused(self):
        for name, payload, sig, key in mutations(self.payload, self.sig, self.key):
            with self.subTest(name):
                self.assertFalse(check(payload, sig, key))

    def test_signed_under_other_parameters(self):
        """Genuine signatures by the right key, over a structure this protocol does not use."""
        for fields in ({"namespace": b"file"}, {"namespace": b"openmasonry2"}, {"namespace": b""},
                       {"hashalg": b"sha256"}, {"reserved": b"x"}):
            with self.subTest(fields):
                key, sig = sign_entry(b"s" * 32, self.payload, **fields)
                self.assertEqual(key, self.key)
                self.assertFalse(check(self.payload, sig, key))

    def test_wrong_key(self):
        other, other_sig = sign_entry(b"o" * 32, self.payload)
        self.assertFalse(check(self.payload, self.sig, other))
        self.assertFalse(check(self.payload, other_sig, self.key))

    def test_bare_ed25519_signature_over_the_payload_is_not_enough(self):
        pub, sig = sign_raw(b"s" * 32, self.payload)
        self.assertFalse(check(self.payload, armor(blob(pub, sig)), self.key))

    def test_garbage_never_raises(self):
        for sig in ("", "\n", "-----BEGIN SSH SIGNATURE-----\n-----END SSH SIGNATURE-----\n", "λ" * 400,
                    self.sig.replace("A", "λ", 1), self.sig.replace("A", "\x00", 1), self.sig * 2,
                    "-----BEGIN SSH SIGNATURE-----\n!!!!\n-----END SSH SIGNATURE-----\n", "\ud800"):
            with self.subTest(sig[:20]):
                self.assertFalse(check(self.payload, sig, self.key))
                with mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
                    self.assertFalse(crypto.verify(self.payload, sig, "hiram", self.key))
        for key in ("", "ssh-ed25519", "ssh-ed25519 !!!!", "∑", self.key + "="):
            self.assertFalse(check(self.payload, self.sig, key))

    def test_verification_never_runs_a_program(self):
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("verification ran a program")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("verification ran a program")), \
                mock.patch.dict("os.environ", {"OM_NO_CACHE": "1", "PATH": ""}):
            self.assertTrue(crypto.verify(self.payload, self.sig, "hiram", self.key))
            self.assertFalse(crypto.verify(self.payload + b" ", self.sig, "hiram", self.key))

    def test_signing_without_openssh_says_so(self):
        with mock.patch.object(shutil, "which", return_value=None):
            with self.assertRaisesRegex(crypto.SigningError, "ssh-keygen not found"):
                crypto.sign(self.payload, Path("/nonexistent/key"))

    def test_cache_remembers_only_what_was_verified(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(crypto, "_CACHE", Path(d) / "verified"), \
                mock.patch.object(crypto, "_CACHE_KEY", Path(d) / "home" / "cache.key"), \
                mock.patch.dict("os.environ"):
            os.environ.pop("OM_NO_CACHE", None)
            self.assertTrue(crypto.verify(self.payload, self.sig, "hiram", self.key))
            self.assertEqual(len(list((Path(d) / "verified").glob("*/*"))), 1)
            with mock.patch.object(crypto, "signature_valid", side_effect=AssertionError("not cached")):
                self.assertTrue(crypto.verify(self.payload, self.sig, "hiram", self.key))
            crlf = self.sig.replace("\n", "\r\n")
            self.assertFalse(crypto.verify(self.payload, crlf, "hiram", self.key))
            self.assertFalse(crypto.verify(self.payload, self.sig + "\n", "hiram", self.key))
            self.assertEqual(len(list((Path(d) / "verified").glob("*/*"))), 1)


@unittest.skipUnless(HAVE_SSH, "ssh-keygen is not installed")
class AgainstOpenSSH(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.keys = [ssh_key(cls.tmp, f"k{i}") for i in range(4)]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_openssh_signatures_are_accepted_and_canonical(self):
        for path, key in self.keys:
            self.assertTrue(crypto.valid_public_key(key))
            for msg in MESSAGES:
                sig = ssh_sign(self.tmp, path, msg)
                with self.subTest(key=key, msg=msg[:12]):
                    self.assertEqual(crypto._armor(dearmor(sig)), sig)
                    self.assertTrue(check(msg, sig, key))

    def test_our_signer_and_openssh_agree(self):
        """Ed25519 is deterministic: OpenSSH and the RFC 8032 signer above produce the same bytes."""
        for i, msg in enumerate(MESSAGES):
            key, sig = sign_entry(bytes([i + 9]) * 32, msg)
            self.assertTrue(ssh_verify(msg, sig, key))

    def test_crypto_sign_returns_the_canonical_form(self):
        path, key = self.keys[0]
        sig = crypto.sign(b"payload", path)
        self.assertEqual(crypto._armor(dearmor(sig)), sig)
        self.assertTrue(check(b"payload", sig, key))

    def test_mutations_of_openssh_signatures_are_refused(self):
        for n, (path, key) in enumerate(self.keys):
            msg = MESSAGES[n % len(MESSAGES)] or b"m"
            sig = ssh_sign(self.tmp, path, msg)
            for name, payload, bad_sig, bad_key in mutations(msg, sig, key):
                with self.subTest(name, key=n):
                    self.assertFalse(check(payload, bad_sig, bad_key))

    def test_wrong_namespace_wrong_key_other_hash(self):
        (path, key), (_, other) = self.keys[:2]
        msg = b"an entry"
        self.assertFalse(check(msg, ssh_sign(self.tmp, path, msg, namespace="file"), key))
        self.assertFalse(check(msg, ssh_sign(self.tmp, path, msg, namespace="git"), key))
        self.assertFalse(check(msg, ssh_sign(self.tmp, path, msg), other))
        sha256 = ssh_sign_sha256(self.tmp, path, msg)
        if sha256 is not None:
            self.assertTrue(ssh_verify(msg, sha256, key), "OpenSSH accepts its own sha256 signature")
            self.assertFalse(check(msg, sha256, key), "the protocol pins sha512")

    def test_never_more_permissive_than_openssh(self):
        for row in differential(self.tmp, self.keys[0]):
            with self.subTest(row[0]):
                name, ssh_ok, py_ok = row
                self.assertFalse(py_ok and not ssh_ok, f"{name}: accepted here, refused by OpenSSH")
                if name != "unchanged":
                    self.assertFalse(py_ok, name)


def differential(tmp: Path, keypair_: tuple[Path, str]) -> list[tuple[str, bool, bool]]:
    """(mutation, OpenSSH accepts, protocol accepts) for every mutation of one OpenSSH signature."""
    path, key = keypair_
    msg = b'{"actor":"hiram","body":{},"seq":0}'
    sig = ssh_sign(tmp, path, msg)
    cases = [("unchanged", msg, sig, key)] + mutations(msg, sig, key)
    cases.append(("signed for namespace file", msg, ssh_sign(tmp, path, msg, namespace="file"), key))
    sha256 = ssh_sign_sha256(tmp, path, msg)
    if sha256 is not None:
        cases.append(("signed with hashalg=sha256", msg, sha256, key))
    seed = b"d" * 32
    own_key, own_sig = sign_entry(seed, msg)
    cases.append(("signed over a non-empty reserved field", msg, sign_entry(seed, msg, reserved=b"x")[1], own_key))
    cases.append(("another member's valid signature", msg, own_sig, key))
    return [(name, ssh_verify(p, sg, k), check(p, sg, k)) for name, p, sg, k in cases]


class HardwareKeys(unittest.TestCase):
    """sk-ssh-ed25519@openssh.com: keys and signatures of a hardware token, built here from software keys.
    No OpenSSH and no token is needed: the verdict is the protocol's own code."""

    def setUp(self):
        self.payload = b'{"actor":"hiram","seq":0}'
        self.pub = keypair(b"h" * 32)[2]
        self.key, self.sig = sk_sign_entry(b"h" * 32, self.payload, counter=41)

    def test_key_text_form(self):
        self.assertEqual(len(self.key), 127)
        self.assertRegex(self.key, r"^sk-ssh-ed25519@openssh\.com [A-Za-z0-9+/]{99}=$")
        self.assertEqual(base64.b64decode(self.key.split()[1]), s(SK) + s(self.pub) + s(b"ssh:"))
        self.assertTrue(crypto.valid_public_key(self.key))
        self.assertTrue(ed25519(self.key))
        for i in range(4):
            self.assertTrue(ed25519(sk_keyline(keypair(bytes([i]) * 32)[2])))

    def test_one_text_form_per_key(self):
        b64 = self.key.split()[1]
        loose = b64[:-2] + chr(ord(b64[-2]) + 1) + "="        # the two unused bits of the last character set
        self.assertEqual(base64.b64decode(loose), base64.b64decode(b64))
        plain = keyline(self.pub).split()[1]
        enc = lambda raw: base64.b64encode(raw).decode()
        for line in (self.key + " comment", self.key + "\n", " " + self.key, self.key.replace(" ", "  "),
                     self.key[:-1], self.key + "=", "sk-ssh-ed25519@openssh.com " + loose,
                     "SK-SSH-ED25519@OPENSSH.COM " + b64, "sk-ssh-ed25519 " + b64, "ssh-ed25519 " + b64,
                     "sk-ssh-ed25519@openssh.com " + plain,
                     "sk-ecdsa-sha2-nistp256@openssh.com " + b64,
                     sk_keyline(self.pub, b"ssh:x"), sk_keyline(self.pub, b""), sk_keyline(self.pub, b"SSH:"),
                     sk_keyline(self.pub, b"ssh"), sk_keyline(self.pub, b"https://example.org"),
                     "sk-ssh-ed25519@openssh.com " + enc(sk_keyblob(self.pub, keytype=b"sk-ssh-ed25518@openssh.com")),
                     "sk-ssh-ed25519@openssh.com " + enc(sk_keyblob(self.pub) + b"\x00"),
                     "sk-ssh-ed25519@openssh.com " + enc(s(SK) + s(self.pub)),
                     "sk-ssh-ed25519@openssh.com " + enc(s(SK) + s(self.pub[:31]) + s(b"ssh:x")),
                     "sk-ssh-ed25519@openssh.com " + enc(bytes(74))):
            self.assertFalse(ed25519(line), repr(line))
            self.assertFalse(crypto.valid_public_key(line), repr(line))

    def test_the_point_is_checked_as_for_plain_keys(self):
        order4 = crypto._decode(bytes(32))
        mixed = crypto._encode(crypto._add(crypto._mul(7, crypto._B), order4))
        for raw in (IDENTITY, (P - 1).to_bytes(32, "little"), bytes(32), P.to_bytes(32, "little"),
                    (2**255 - 1).to_bytes(32, "little"), mixed):
            self.assertFalse(crypto.valid_public_key(sk_keyline(raw)), raw.hex())
            self.assertFalse(ed25519(sk_keyline(raw)), raw.hex())

    def test_the_point_of_a_key_is_the_same_under_both_types(self):
        self.assertEqual(crypto.public_point(self.key), self.pub)
        self.assertEqual(crypto.public_point(keyline(self.pub)), self.pub)
        self.assertNotEqual(crypto.public_point(sk_keyline(keypair(b"i" * 32)[2])), self.pub)
        for bad in (sk_keyline(self.pub, b"ssh:x"), keyline(IDENTITY), self.key + " ", "", None, 7):
            self.assertIsNone(crypto.public_point(bad))

    def test_valid(self):
        self.assertTrue(check(self.payload, self.sig, self.key))
        for i, msg in enumerate(MESSAGES):
            for flags in (UP, UP | UV, UP | 0x40, 0xff):
                for counter in (0, 1, 2**31, 2**32 - 1):
                    key, sig = sk_sign_entry(bytes([i + 1]) * 32, msg, flags, counter)
                    self.assertTrue(check(msg, sig, key), (i, flags, counter))

    def test_canonical_armor_and_blob(self):
        raw = dearmor(self.sig)
        self.assertEqual(len(raw), 224)
        self.assertEqual(crypto._armor(raw), self.sig)
        self.assertEqual([len(x) for x in self.sig.split("\n")], [29, 70, 70, 70, 70, 20, 27, 0])
        self.assertEqual(raw[10:14] + raw[14:44], struct.pack(">I", 74) + s(SK))
        self.assertEqual((raw[-5], raw[-4:]), (UP, struct.pack(">I", 41)))

    def test_user_presence_is_required(self):
        """A token can be told to sign without a touch; such a signature is genuine and is refused."""
        for flags in (0, UV, 0x40, 0xfe):
            key, sig = sk_sign_entry(b"h" * 32, self.payload, flags, 41)
            self.assertEqual(key, self.key)
            self.assertFalse(check(self.payload, sig, key), flags)

    def test_the_application_is_ssh_colon_and_nothing_else(self):
        for app in (b"ssh:x", b"", b"ssh", b"SSH:", b"ssh:\x00"):
            key, sig = sk_sign_entry(b"h" * 32, self.payload, app=app)        # genuine, for another application
            self.assertFalse(check(self.payload, sig, key), app)
            self.assertFalse(check(self.payload, sig, self.key), app)
            # …and the same signature inside a blob that claims the application ssh:
            pub, ed = sign_raw(b"h" * 32, sk_signed(self.payload, app=app))
            self.assertFalse(check(self.payload, armor(sk_blob(pub, ed)), self.key), app)

    def test_counter_and_flags_are_signed(self):
        raw = dearmor(self.sig)
        ed = raw[-69:-5]
        for counter in (0, 40, 42, 2**32 - 1):
            self.assertFalse(check(self.payload, armor(sk_blob(self.pub, ed, UP, counter)), self.key), counter)
        for flags in (UP | UV, 0xff):
            self.assertFalse(check(self.payload, armor(sk_blob(self.pub, ed, flags, 41)), self.key), flags)
        self.assertTrue(check(self.payload, armor(sk_blob(self.pub, ed, UP, 41)), self.key))

    def test_every_mutation_is_refused(self):
        for flags, counter in ((UP, 41), (UP | UV, 0), (0xff, 2**32 - 1)):
            key, sig = sk_sign_entry(b"h" * 32, self.payload, flags, counter)
            self.assertTrue(check(self.payload, sig, key))
            for name, payload, bad_sig, bad_key in sk_mutations(self.payload, sig, key):
                with self.subTest(name, flags=flags):
                    self.assertFalse(check(payload, bad_sig, bad_key))

    def test_signed_under_other_parameters(self):
        for fields in ({"namespace": b"file"}, {"namespace": b""}, {"hashalg": b"sha256"}, {"reserved": b"x"}):
            with self.subTest(fields):
                key, sig = sk_sign_entry(b"h" * 32, self.payload, counter=41, **fields)
                self.assertEqual(key, self.key)
                self.assertFalse(check(self.payload, sig, key))

    def test_a_signature_of_one_type_never_passes_for_the_other(self):
        """The same Ed25519 point as a plain key and as a hardware key: neither accepts the other's signature."""
        plain_key, plain_sig = sign_entry(b"h" * 32, self.payload)
        self.assertEqual(raw_key(plain_key), self.pub)
        self.assertTrue(check(self.payload, plain_sig, plain_key))
        self.assertFalse(check(self.payload, plain_sig, self.key))
        self.assertFalse(check(self.payload, self.sig, plain_key))
        # a bare signature over the SSHSIG data, dressed as a hardware signature, and the reverse
        _, bare = sign_raw(b"h" * 32, to_be_signed(self.payload))
        self.assertFalse(check(self.payload, armor(sk_blob(self.pub, bare)), self.key))
        _, token = sign_raw(b"h" * 32, sk_signed(self.payload))
        self.assertFalse(check(self.payload, armor(blob(self.pub, token)), plain_key))

    def test_garbage_never_raises(self):
        raw = dearmor(self.sig)
        for cut in (0, 1, 4, 5, 68, 69, 73, 154, 155, 223):
            self.assertFalse(check(self.payload, armor(raw[:cut]), self.key), cut)
            self.assertFalse(check(self.payload, armor(raw[-cut:] if cut else b""), self.key), cut)
        with mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
            self.assertTrue(crypto.verify(self.payload, self.sig, "hiram", self.key))
            self.assertFalse(crypto.verify(self.payload, self.sig.replace("A", "\u00e9", 1), "hiram", self.key))

    def test_verification_never_runs_a_program(self):
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("verification ran a program")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("verification ran a program")), \
                mock.patch.dict("os.environ", {"OM_NO_CACHE": "1", "PATH": ""}):
            self.assertTrue(crypto.verify(self.payload, self.sig, "hiram", self.key))
            self.assertFalse(crypto.verify(self.payload + b" ", self.sig, "hiram", self.key))


class SigningWithAToken(unittest.TestCase):
    """`crypto.sign` calls ssh-keygen (which asks for the touch). Here ssh-keygen is replaced by a function that
    writes what a token would have made, so the check of its output is exercised without hardware."""

    def sign_with(self, armored: str, payload: bytes = b"payload") -> str:
        def fake(argv, **kw):
            if argv[0] == "ssh-add":
                return subprocess.CompletedProcess(argv, 1, "", "")
            self.assertEqual(argv[:4], ["ssh-keygen", "-q", "-Y", "sign"])
            self.assertEqual(argv[-3:-1], ["-n", "openmasonry"])
            msg = Path(argv[-1])
            self.assertEqual(msg.read_bytes(), payload)
            msg.with_name("msg.sig").write_text(armored)
            return subprocess.CompletedProcess(argv, 0, "", "")
        with mock.patch.object(shutil, "which", return_value="/usr/bin/ssh-keygen"), \
                mock.patch.object(subprocess, "run", fake):
            return crypto.sign(payload, Path("/nonexistent/id_ed25519_sk"))

    def test_the_output_of_a_token_is_accepted_and_returned_in_canonical_form(self):
        for flags, counter in ((UP, 3), (UP | UV, 2**32 - 1)):
            key, sig = sk_sign_entry(b"t" * 32, b"payload", flags, counter)
            out = self.sign_with(sig)
            self.assertEqual(out, sig)
            self.assertTrue(check(b"payload", out, key))
            self.assertEqual(self.sign_with(sig.replace("\n", "\r\n")), sig)      # re-armored, never passed through

    def test_a_plain_key_still_signs(self):
        key, sig = sign_entry(b"t" * 32, b"payload")
        self.assertEqual(self.sign_with(sig), sig)

    def test_what_the_protocol_would_refuse_is_never_returned(self):
        seed = b"t" * 32
        pub = keypair(seed)[2]
        _, ed = sign_raw(seed, sk_signed(b"payload", 0, 3))
        cases = {
            "without user presence": sk_sign_entry(seed, b"payload", 0, 3)[1],
            "another application": sk_sign_entry(seed, b"payload", app=b"ssh:x")[1],
            "the sha256 hash": sk_sign_entry(seed, b"payload", hashalg=b"sha256")[1],
            "trailing bytes": armor(sk_blob(pub, ed, UP, 3, tail=b"\x00")),
            "another key type": armor(sk_blob(pub, ed, UP, 3, keytype=b"sk-ecdsa-sha2-nistp256@openssh.com")),
            "not base64": "-----BEGIN SSH SIGNATURE-----\n!!!!\n-----END SSH SIGNATURE-----\n",
            "empty": "",
        }
        for name, armored in cases.items():
            with self.subTest(name), self.assertRaisesRegex(crypto.SigningError, "does not accept"):
                self.sign_with(armored)


@unittest.skipUnless(openssh_knows_sk(), "the installed OpenSSH does not know sk-ssh-ed25519@openssh.com")
class HardwareKeysAgainstOpenSSH(unittest.TestCase):
    """The wire format read by `crypto.signature_valid` is the one OpenSSH reads: `ssh-keygen -Y verify`, given an
    allowed_signers line for a synthetic hardware key, accepts the synthetic signatures made here."""

    def test_openssh_accepts_the_synthetic_keys_and_signatures(self):
        for i, msg in enumerate(MESSAGES):
            for flags, counter in ((UP, 0), (UP | UV, 7), (UP, 2**32 - 1)):
                key, sig = sk_sign_entry(bytes([i + 20]) * 32, msg, flags, counter)
                with self.subTest(msg=msg[:12], flags=flags, counter=counter):
                    self.assertTrue(ssh_verify(msg, sig, key), "OpenSSH refuses a signature built by this reading")
                    self.assertTrue(check(msg, sig, key))

    def test_openssh_reads_the_same_fields(self):
        """Each field this protocol reads is one OpenSSH reads too: bending it makes OpenSSH refuse as well."""
        msg = b"an entry"
        key, sig = sk_sign_entry(b"f" * 32, msg, UP, 9)
        pub, ed = sk_raw_key(key), dearmor(sig)[-69:-5]
        self.assertTrue(ssh_verify(msg, sig, key))
        for name, bad in (("counter", armor(sk_blob(pub, ed, UP, 10))), ("flags", armor(sk_blob(pub, ed, UP | UV, 9))),
                          ("application", armor(sk_blob(pub, ed, UP, 9, app=b"ssh:x"))),
                          ("trailing bytes after the counter", armor(sk_blob(pub, ed, UP, 9, inner_tail=b"\x00")))):
            self.assertFalse(ssh_verify(msg, bad, key), name)
            self.assertFalse(check(msg, bad, key), name)

    def test_never_more_permissive_than_openssh(self):
        rows = sk_differential()
        self.assertIn(("unchanged", True, True), rows)
        for name, ssh_ok, py_ok in rows:
            with self.subTest(name):
                self.assertFalse(py_ok and not ssh_ok, f"{name}: accepted here, refused by OpenSSH")
                if name != "unchanged":
                    self.assertFalse(py_ok, name)

    def test_this_protocol_is_stricter_where_it_says_so(self):
        """OpenSSH's `-Y verify` does not ask for user presence and accepts any application; the protocol does not."""
        rows = {name: (ssh_ok, py_ok) for name, ssh_ok, py_ok in sk_differential()}
        self.assertEqual(rows["signed without user presence"], (True, False))
        self.assertEqual(rows["signed for the application ssh:x"], (True, False))


def sk_differential() -> list[tuple[str, bool, bool]]:
    """(mutation, OpenSSH accepts, protocol accepts) for every mutation of one synthetic hardware signature."""
    msg = b'{"actor":"hiram","body":{},"seq":0}'
    seed = b"e" * 32
    key, sig = sk_sign_entry(seed, msg, UP, 77)
    cases = [("unchanged", msg, sig, key)] + sk_mutations(msg, sig, key)
    cases.append(("signed without user presence", msg, sk_sign_entry(seed, msg, 0, 77)[1], key))
    other_key, other_sig = sk_sign_entry(seed, msg, UP, 77, app=b"ssh:x")
    cases.append(("signed for the application ssh:x", msg, other_sig, other_key))
    cases.append(("signed for namespace file", msg, sk_sign_entry(seed, msg, UP, 77, namespace=b"file")[1], key))
    cases.append(("signed with hashalg=sha256", msg, sk_sign_entry(seed, msg, UP, 77, hashalg=b"sha256")[1], key))
    cases.append(("another member's valid signature", msg, sk_sign_entry(b"o" * 32, msg, UP, 77)[1], key))
    return [(name, ssh_verify(p, sg, k), check(p, sg, k)) for name, p, sg, k in cases]


class InTheLedger(unittest.TestCase):
    @unittest.skipUnless(HAVE_SSH, "ssh-keygen is not installed")
    def test_a_rewrapped_signature_makes_the_entry_invalid(self):
        from tests.test_protocol import founded
        with tempfile.TemporaryDirectory() as d, mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
            entries = founded(Path(d)).entries
            self.assertEqual(replay(entries).seq, len(entries) - 1)
            for bend in (lambda x: x.replace("\n", "\r\n"), lambda x: x + "\n", lambda x: x[:-1],
                         lambda x: armor(dearmor(x), width=0)):
                bad = [dict(e) for e in entries]
                bad[0]["sig"] = bend(bad[0]["sig"])
                with self.assertRaises(Invalid) as err:
                    replay(bad)
                self.assertEqual(err.exception.seq, 0)
                # A carriage return is outside the alphabet of entry strings: the encoding rules refuse it first.
                self.assertIn("not strict JSON" if "\r" in bad[0]["sig"] else "bad signature", str(err.exception))

    def test_a_ledger_founded_and_witnessed_by_hardware_keys_replays(self):
        from tests.test_protocol import checkpoint, genesis_body
        from tests.test_strict import Fast
        seeds = {"hiram": b"1" * 32, "ada": b"2" * 32, "tyler": b"3" * 32}
        c = Fast()
        c.keys = {name: (None, sk_keyline(keypair(seed)[2])) for name, seed in seeds.items()}
        c.keys["ada"] = (None, keyline(keypair(seeds["ada"])[2]))             # one plain key beside them
        body = genesis_body(c, ["hiram", "ada"], ["tyler"])
        ada, tyler = body["founders"][1], body["witnesses"][0]       # each proves possession with a real signature
        ada["proof"] = sign_entry(seeds["ada"], ledger.founder_message("ada", ada["github_id"], ada["key"]))[1]
        tyler["proof"] = sk_sign_entry(seeds["tyler"], ledger.witness_message("tyler", tyler["key"]), UP, 7)[1]
        e = c.add("genesis", "hiram", body)
        e["sig"] = sk_sign_entry(seeds["hiram"], signed_payload(e), UP, 1)[1]
        w = c.add("witness", "tyler", checkpoint(replay([e], verifier=lambda *_: True)))
        w["sig"] = sk_sign_entry(seeds["tyler"], signed_payload(w), UP | UV, 2)[1]
        k = c.add("work", "ada", {"ref": "https://example.org/w"})
        k["sig"] = sign_entry(seeds["ada"], signed_payload(k))[1]
        with mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
            st = replay(c.entries)
            self.assertEqual(st.members["hiram"].key, c.keys["hiram"][1])
            self.assertEqual(st.witnesses["tyler"], c.keys["tyler"][1])
            untouched = [dict(x) for x in c.entries]
            untouched[0]["sig"] = sk_sign_entry(seeds["hiram"], signed_payload(e), 0, 1)[1]
            with self.assertRaisesRegex(Invalid, "entry 0: bad signature"):
                replay(untouched)


if __name__ == "__main__":
    unittest.main()
