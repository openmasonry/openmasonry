"""Member commands that people and their agents drive. The rules are pure and live in
ledger.py; this module holds the side effects (git, GitHub, approval dialogs).

The human-in-the-loop has two parts:

1. **Sealed draft.** Every command that would sign or publish only *drafts*: it builds
   the exact entry (time, seq, prev, ballot id, salt…), checks it against the protocol
   on a copy of the state, stores it in ~/.config/openmasonry/pending/<digest>.json and
   exits with code 3. Nothing is signed.
2. **Approval outside the agent.** `om approve <digest>` shows the summary in an
   operating-system dialog (macOS, Linux desktop) or, failing that, asks on the
   terminal (/dev/tty). Only the person can answer. Then it signs *exactly* the stored
   draft and opens the pull request in the same step.

An agent can prepare drafts freely; it cannot approve one. (A program running as the
person can always bypass a local check, so this protects against mistakes and
prompt injection, not against malware on the person's own machine.)

The same two parts serve the acts that a member key does not sign. A custodian act
(`om correct`, `cosign-correction`, `apply-correction`, `withdraw-correction`, `alive`)
names the custodian as its actor and is signed with the custodian key; `revoke-custodian`
is signed with the revoke key; a key recovery (`om recover`, `recover-apply`) is signed
with the member's new key. The public reason of a correction is read when the draft is
made and kept inside it; approval writes it as ledger/reasons/<sha256>.md beside the
entry, and both go in one pull request.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import canon
from .crypto import SigningError, canonical, sha256, sign
from .govern import REASON_MAX_BYTES, REASONS_DIR
from .guide import APPLY_URL, custodian_steps, next_steps, notices
from .onboard import cmdline
from .ledger import (ACT_DAYS, ACT_GROUND, BEACON_DELAY_ROUNDS, CLAIM_EXPIRY_DAYS, CLAIM_NOTICE_DAYS, CLOCK_TOLERANCE,
                     CUSTODIAN_SIGNED, RECOVER_LOWERED_NOTICE_DAYS, SUCCESSION_DAYS, CUSTODIAN_TERM_DAYS,
                     SUCCESSION_MASTERS, COMMIT_DAYS, REVEAL_DAYS, RERUN_DAYS,
                     CUSTODIAN_SILENCE_DAYS, DAY, FREEZE_DAYS, GROUNDS, HALT_DAYS, HOLD_DAYS, INVITE_EXPIRY_DAYS,
                     KEY_RULE, NOTICE_DAYS, NOTICED_ACTS, APPLY_WINDOW_DAYS, OBJECTION_DAYS, RECOVER_COSIGNERS,
                     RECOVER_INTERVAL_DAYS, RECOVER_NOTICE_DAYS, RECOVER_OPEN_COSIGNERS, RECOVER_OPEN_NOTICE_DAYS,
                     REKEY_INTERVAL_DAYS, STAY_DAYS,
                     UNDO_WINDOW_DAYS, CanonPending, Invalid, State, apply, commitment, custodian_message,
                     custodian_revoke_message, drand_round, ed25519, entry_hash, entry_order, entry_path, entry_seq,
                     entry_text, founder_message, future_head,
                     head_verdict, iso, load, make_entry, rekey_message, remember_head, replay, signed_payload,
                     strict_json, ts, valid_login, witness_message)

NEEDS_APPROVAL = 3
HOME = Path(os.environ.get("OM_HOME", Path.home() / ".config" / "openmasonry"))
PENDING = HOME / "pending"
VAULT = HOME / "vault.json"
CONFIG = HOME / "config.json"       # {"key": the private key that signs, "previous_key": the one it replaced,
                                    #  "recovery_key": the new key of a key recovery that is under way}
HEADS = HOME / "heads.json"         # the head of the canonical ledger this clone last verified, per genesis (never in the repository)
REKEY_PROOF_PENDING = "(the new key signs this proof when the person approves)"
CUSTODIAN_PROOF_PENDING = "(this key signs its proof of possession when the person approves)"
# Entries signed by a key that is not the member key this machine is configured with: a stale one is not
# re-sequenced by `om pending --rebase` (which signs with the member key); it is dropped and drafted again.
OTHER_KEY_TYPES = CUSTODIAN_SIGNED | {"rekey_recover", "rekey_recover_apply", "rekey_object"}
# Entries signed by the member key that carry proofs of possession made by other keys at approval: a stale one
# is not re-sequenced either (its other private keys may no longer be at hand); it is dropped and drafted again.
PROOF_TYPES = frozenset({"custodian_claim"})
DEFAULT_LEDGER = canon.ROOT / "ledger" / "entries"
OM = "bin\\om.cmd" if sys.platform == "win32" else "bin/om"      # the launcher, as this platform runs it


class UserError(Exception):
    """A problem the person can fix; printed without a traceback."""


# ------------------------------------------------------------------ helpers --

def _private_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    os.chmod(p, 0o700)
    return p


def _write_private(path: Path, data: dict) -> None:
    """Atomic, owner-only write (0600 from creation, unique temp name)."""
    _private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


_TOKEN_WARNED: list[bool] = []


def detect_login(explicit: str | None) -> str | None:
    if explicit or os.environ.get("OM_LOGIN"):
        return explicit or os.environ["OM_LOGIN"]
    if shutil.which("gh"):
        r = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            tokens = [v for v in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN") if os.environ.get(v)]
            if tokens and not _TOKEN_WARNED:      # that token, not the account logged in, picks who you are
                _TOKEN_WARNED.append(True)
                print(f"note: {' and '.join(tokens)} is set, so gh acts as the account of that token "
                      f"({r.stdout.strip()}), not necessarily the one you logged in with; unset it to use your login",
                      file=sys.stderr)
            return r.stdout.strip()
    return None


def key_path(explicit: str | None) -> Path:
    """The private key that signs: --key, else $OM_KEY, else the key `om rekey` configured, else ~/.ssh/id_ed25519."""
    return Path(explicit or os.environ.get("OM_KEY") or _read_json(CONFIG).get("key")
                or Path.home() / ".ssh" / "id_ed25519").expanduser()


def fingerprint(key: str) -> str:
    """The fingerprint OpenSSH prints for a public key line (`ssh-keygen -lf`): SHA256 of the key blob."""
    try:
        blob = base64.b64decode(key.split()[1], validate=True)
    except (IndexError, ValueError, AttributeError):
        return "(not a key)"
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def key_kind(bare: str) -> str | None:
    """What kind of key the protocol sees in a bare public key line; None when it accepts none."""
    if not ed25519(bare):
        return None
    return "Ed25519 key held by a hardware token" if bare.startswith("sk-") else "Ed25519 key"


def key_advice(st: State | None, login: str | None, bare: str) -> str | None:
    """What to tell a member whose configured key is not the key the ledger holds for them; None otherwise."""
    m = st.members.get(login) if st is not None and login else None
    if m is None or m.key == bare:
        return None
    return (f"your configured key ({fingerprint(bare)}) is not the key the ledger holds for {m.login} "
            f"({fingerprint(m.key)}): nothing you sign with it is accepted. If the ledger's key is another key of "
            f"yours, use it (--key, or OM_KEY). To make a new key yours, with the ledger's key still in hand: "
            f"{OM} rekey --new-key PATH --key PATH-OF-THE-LEDGER-KEY (the ledger's key signs the entry, the new "
            f"key signs a proof, and the new key must be listed at github.com/{m.login}.keys; once in "
            f"{REKEY_INTERVAL_DAYS} days). If the ledger's key is lost or stolen, see SECURITY.md")


def bare_public_key(key: Path) -> str:
    pub = key.with_name(key.name + ".pub")
    if not pub.exists():
        raise UserError(f"public key {pub} not found (create a key with: ssh-keygen -t ed25519)")
    parts = pub.read_text().split()
    if len(parts) < 2:
        raise UserError(f"{pub} is not an OpenSSH public key")
    return f"{parts[0]} {parts[1]}"


def state_of(ledger: Path) -> State | None:
    entries = load(ledger)
    return replay(entries) if entries else None


def canonical_login(st: State | None, login: str) -> str:
    """GitHub logins are case-insensitive: use the spelling the ledger already knows."""
    if st is not None:
        return st.login_taken(login) or next((p for p in (*st.petitions, *st.invitations)
                                              if p.casefold() == login.casefold()), login)
    return login


def ledger_id(st: State | None) -> str:
    return st.hashes[0][:16] if st and st.hashes else "pre-genesis"


def vault_key(st: State | None, login: str, ballot: str) -> str:
    return f"{ledger_id(st)}:{login.casefold()}:{ballot}"


def need_login(a) -> str:
    login = detect_login(a.login)
    if not login:
        raise UserError("cannot tell your GitHub login: run `gh auth login`, or pass --login / set OM_LOGIN")
    return login


def is_repo_ledger(ledger: Path) -> bool:
    return Path(ledger).resolve() == DEFAULT_LEDGER.resolve()


def reasons_dir(ledger: Path) -> Path:
    """Where the public reasons of a ledger's corrections are archived: `reasons/` beside its entries directory
    (`ledger/reasons/` of the repository)."""
    return Path(ledger).resolve().parent / Path(REASONS_DIR).name


def read_reason(path: Path | str) -> tuple[bytes, str]:
    """(bytes, sha256) of the public reason of a correction: a text for people, in UTF-8 (ASCII included), of
    at most REASON_MAX_BYTES bytes. The bytes are archived as they are, under their sha256."""
    try:
        with open(Path(path).expanduser(), "rb") as f:
            data = f.read(REASON_MAX_BYTES + 1)
    except OSError as err:
        raise UserError(f"cannot read the reason {path}: {err.strerror or err}") from None
    if not data:
        raise UserError(f"the reason {path} is empty: a correction states its reason in public")
    if len(data) > REASON_MAX_BYTES:
        raise UserError(f"the reason {path} is larger than {REASON_MAX_BYTES} bytes (a reason is a text for people "
                        "to read, not an archive)")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise UserError(f"the reason {path} is not UTF-8 text") from None
    if any((ord(ch) < 32 and ch not in "\n\r\t") or ord(ch) == 127 for ch in text):
        raise UserError(f"the reason {path} holds a control character: it must be plain text")
    return data, sha256(data)


# The target flags of `om correct`, per act: flag -> the field of the target the protocol reads.
CORRECTION_FLAGS: dict[str, dict[str, str]] = {
    "freeze_key": {"login": "login"}, "freeze_witness": {"name": "name"}, "stay": {"ballot": "ballot"}, "halt": {},
    "hold_room": {"login": "login"}, "note": {"action": "action", "target": "target", "rule": "rule"},
    "void_ballot": {"ballot": "id"}, "undo_ballot": {"ballot": "id"},
}
TARGET_FLAGS = ("login", "name", "ballot", "action", "target", "rule")


def correction_target(act: str, **flags: str | None) -> dict:
    """The target of a correction from the flags given: each act takes exactly its own. Pure."""
    wanted = CORRECTION_FLAGS.get(act)
    if wanted is None:
        raise UserError(f"unknown act {act!r}: one of {', '.join(sorted(CORRECTION_FLAGS))}")
    given = {k: v for k, v in flags.items() if v is not None}
    for flag in wanted:
        if flag not in given:
            raise UserError(f"{act} needs --{flag}")
    for flag in given:
        if flag not in wanted:
            raise UserError(f"{act} takes no --{flag}"
                            + (f" (it takes {', '.join('--' + x for x in wanted)})" if wanted else " (it has no target)"))
    return {field: given[flag] for flag, field in wanted.items()}


def custodian_name(a) -> str | None:
    """The custodian the person says they are: --as NAME, else $OM_CUSTODIAN."""
    return getattr(a, "as_custodian", None) or os.environ.get("OM_CUSTODIAN") or None


def custodian_identity(a, st: State | None) -> tuple[str, Path]:
    """(name, private key path) of the custodian who signs this act: --as NAME and --custodian-key PATH, else
    $OM_CUSTODIAN and $OM_CUSTODIAN_KEY. A custodian act is never signed with a member key."""
    name = custodian_name(a)
    key = getattr(a, "custodian_key", None) or os.environ.get("OM_CUSTODIAN_KEY")
    if not name:
        raise UserError("a custodian act says which custodian signs it: pass --as NAME (or set OM_CUSTODIAN) and "
                        "--custodian-key PATH (or OM_CUSTODIAN_KEY). It is signed with the custodian key, never "
                        "with a member key")
    if not key:
        raise UserError(f"a custodian act of {name} is signed with its custodian key, never with a member key: pass "
                        "--custodian-key PATH (or set OM_CUSTODIAN_KEY)")
    name, path = canonical_login(st, name), Path(key).expanduser()
    c = st.custodians.get(name) if st is not None else None
    if c is not None and bare_public_key(path) != c.key:
        raise UserError(f"the key {path} ({fingerprint(bare_public_key(path))}) is not the custodian key the ledger "
                        f"holds for {name} ({fingerprint(c.key)})")
    return name, path


def _pending_proofs(body: dict, paths: dict) -> dict[tuple[str, str], Path]:
    """(role, name) -> private key, for every cofounder and witness of a genesis draft whose proof of possession
    is still to be signed. Refuses unless the private half of each such key is present and is the key of the
    draft: otherwise its holder makes the proof (`om proof`) and the genesis is drafted with it."""
    held = {}
    for role, rows, field, flag in (("founder", body.get("founders", [])[1:], "login", "--cofounder-proof"),
                                    ("witness", body.get("witnesses", []), "name", "--witness-proof")):
        for row in rows:
            if row.get("proof") != CUSTODIAN_PROOF_PENDING:
                continue
            path = Path(str(paths.get(f"{role}:{row[field]}") or "missing")).expanduser()
            if not path.is_file() or bare_public_key(path) != row["key"]:
                how = f"{OM} proof {role} {row[field]} --key PATH" + (" --github-id N" if role == "founder" else "")
                raise UserError(f"the private key of the {role} {row[field]} is not here ({path}): its holder signs the "
                                f"proof of possession with `{how} --out FILE`, and the genesis is drafted again with "
                                f"{flag} {row[field]}:FILE")
            held[(role, row[field])] = path
    return held


def _custodian_keys(named: list[dict], paths: dict) -> dict[str, tuple[Path, Path]]:
    """name -> (custodian key, revoke key), the private halves a genesis needs to prove possession. Refuses
    unless both files of every custodian are present and are the keys of the draft."""
    held = {}
    for c in named:
        found = []
        for field, what in (("key", "custodian key"), ("revoke_key", "revoke key")):
            path = Path(str((paths.get(c["name"]) or {}).get(field) or "missing")).expanduser()
            if not path.is_file():
                raise UserError(f"the private half of the {what} of the custodian {c['name']} is not at {path}: both "
                                "private keys of every custodian must be present when the genesis is approved (each "
                                "signs its proof of possession once). Draft again when they are; afterwards store "
                                "the revoke key separately and offline")
            if bare_public_key(path) != c[field]:
                raise UserError(f"the key {path} is not the {what} of the custodian {c['name']} in this draft")
            found.append(path)
        held[c["name"]] = (found[0], found[1])
    return held


def _claim_keys(body: dict, paths: dict) -> tuple[Path, Path]:
    """(custodian key, revoke key), the private halves a claim of the Custodian office needs to prove
    possession. Refuses unless both files are present and are the keys of the draft."""
    found = []
    for field, what in (("key", "custodian key"), ("revoke_key", "revoke key")):
        path = Path(str(paths.get(field) or "missing")).expanduser()
        if not path.is_file():
            raise UserError(f"the private half of the {what} of the claimed custodian {body.get('name')} is not at "
                            f"{path}: both private keys must be present when the claim is approved (each signs its "
                            "proof of possession once). Draft again when they are; afterwards store the revoke key "
                            "separately and offline")
        if bare_public_key(path) != body.get(field):
            raise UserError(f"the key {path} is not the {what} of the claimed custodian {body.get('name')} in this draft")
        found.append(path)
    return found[0], found[1]


# ------------------------------------------------------- describing acts -----

_CTRL = dict.fromkeys(c for c in range(32) if c not in (10,)) | {127: None}


def clean(text: object, limit: int = 300) -> str:
    """Untrusted text for a human: no control characters, no escape sequences, bounded length."""
    s = str(text).translate(_CTRL)
    s = "".join(ch for ch in s if ch.isprintable() or ch == "\n")
    return s if len(s) <= limit else s[:limit] + "…"


def describe(st: State | None, entry: dict) -> str:
    """What the person is about to sign, built from the entry itself (never from stored prose)."""
    t, b, who = entry["type"], entry["body"], entry["actor"]
    lines = {
        "genesis": lambda: f"FOUND the fraternity “{clean(b.get('name'))}”.\nFounders: "
                           + ", ".join(clean(f.get("login")) for f in b.get("founders", []))
                           + "\nWitnesses: " + (", ".join(clean(w.get("name")) for w in b.get("witnesses", [])) or "none")
                           + "\nCustodians: " + (", ".join(
                               f"{clean(c.get('name'))} (the member {clean(c.get('member'))})"
                               for c in b.get("custodians", []) if isinstance(c, dict)) or "none")
                           + "".join(
                               f"\n  {clean(c.get('name'), 40)}: key {fingerprint(str(c.get('key')))} · revoke key "
                               f"{fingerprint(str(c.get('revoke_key')))}"
                               for c in b.get("custodians", []) if isinstance(c, dict))
                           + (f"\nA noticed correction needs {clean(b.get('custodian_threshold'), 4)} of their keys."
                              if b.get("custodians") else "")
                           + "\nThis pins, until an amendment changes them (the Landmarks: forever): "
                           + (", ".join(clean(p) for p in sorted(b["pins"])) if isinstance(b.get("pins"), dict) else "nothing") + ".",
        "invite": lambda: f"INVITE {clean(b.get('login'))} (GitHub account id {clean(b.get('github_id'))}) to petition "
                          "for admission.\nYou become their first sponsor: you answer for their identity, adulthood "
                          f"and good faith.\nThe invitation counts in your sponsorship budget (four at a time) and lapses after "
                          f"{INVITE_EXPIRY_DAYS} days without a petition.",
        "petition": lambda: "PETITION for admission, declaring the Declaration of OpenMasonry.\nKey: " + clean(b.get("key"), 90),
        "vouch": lambda: f"SPONSOR {clean(b.get('candidate'))} for admission.",
        "ballot_open": lambda: f"OPEN ballot {clean(b.get('id'))} ({clean(b.get('kind'))}): "
                               + "; ".join(f"{clean(k)} = {clean(v, 120)}" for k, v in (b.get("subject") or {}).items())
                               + ("\nIf more Master Builders vote yes than no, that custodian key is removed at once and "
                                  "for good. The windows are fixed, and no correction can pause this ballot."
                                  if b.get("kind") == "custodian" else "")
                               + (f"\n{clean(b.get('commit_days', COMMIT_DAYS), 4)} days to commit, "
                                  f"{clean(b.get('reveal_days', REVEAL_DAYS), 4)} to reveal."
                                  if "commit_days" in b or "reveal_days" in b else "")
                               + (f"\nThis re-runs the lapsed ballot {clean(b.get('rerun'), 64)}, once: those who did not "
                                  "vote in it are not waited for again, and keep their vote." if b.get("rerun") else ""),
        "ballot_commit": lambda: f"SEAL your vote in ballot {clean(b.get('id'))}" + _ballot_about(st, b.get("id")),
        "ballot_reveal": lambda: f"REVEAL your vote in ballot {clean(b.get('id'))}: {clean(b.get('vote')).upper()}. After this it is public.",
        "ballot_close": lambda: f"CLOSE ballot {clean(b.get('id'))} and apply its result" + _ballot_about(st, b.get("id")),
        "exam_open": lambda: f"OPEN your examination for the {clean(b.get('degree'))}° with the work {clean(b.get('work_ref'), 200)}",
        "exam_draw": lambda: f"DRAW the examiners of {clean(b.get('candidate'))} for the {clean(b.get('degree'))}°.",
        "exam_report": lambda: f"VERDICT {clean(b.get('verdict')).upper()} on {clean(b.get('candidate'))}'s {clean(b.get('degree'))}° examination"
                               + (f"\nReason: {clean(b.get('reason'), 200)}" if b.get("reason") else ""),
        "exam_recuse": lambda: f"RECUSE yourself from {clean(b.get('candidate'))}'s {clean(b.get('degree'))}° examination.",
        "council_call": lambda: "CALL the lot of the Supreme Council.",
        "council_draw": lambda: "DRAW the Supreme Council.",
        "work": lambda: f"RECORD the work {clean(b.get('ref'), 200)}",
        "depart": lambda: "LEAVE the fraternity. A Master Builder may invite you again after 90 days, and you "
                          "would return at the 1st degree.",
        "rekey": lambda: "REPLACE your signing key.\nOld key: "
                         + (fingerprint(st.members[who].key) if st and who in st.members else "(unknown)")
                         + "\nNew key: " + fingerprint(str(b.get("key"))) + " " + clean(str(b.get("key")).split(" ")[0], 40)
                         + "\nFrom this entry on, only the new key signs for you; the old one is retired for good."
                         f"\nYou may replace your key again after {REKEY_INTERVAL_DAYS} days.",
        "correction": lambda: _correction_about(b, entry.get("time")),
        "correction_withdraw": lambda: f"WITHDRAW correction {clean(b.get('seq'))}" + _correction_ref(st, b.get("seq"))
                                       + "\nWhat it had in force ends with this entry; a pending act is canceled.",
        "correction_cosign": lambda: f"CO-SIGN correction {clean(b.get('seq'))}" + _correction_ref(st, b.get("seq"))
                                     + "\nYour custodian key endorses it. It changes nothing until it is applied, "
                                       "after its notice.",
        "correction_apply": lambda: f"APPLY correction {clean(b.get('seq'))}" + _correction_ref(st, b.get("seq"))
                                    + f"\nIts {NOTICE_DAYS} days of notice are over: the act takes effect with this "
                                      "entry, once, and an objection made afterwards does not reverse it.",
        "rekey_recover": lambda: "ASK to recover your membership with a NEW key, because the old one is lost or stolen."
                                 "\nOld key: " + (fingerprint(st.members[who].key) if st and who in st.members else "(unknown)")
                                 + "\nNew key: " + fingerprint(str(b.get("key"))) + " " + clean(str(b.get("key")).split(" ")[0], 40)
                                 + f"\nNothing changes yet. Master Builders co-sign it ({RECOVER_COSIGNERS} after a "
                                 f"freeze; {RECOVER_OPEN_COSIGNERS} without one, or after a recovery the old key stopped; "
                                 "never more than the other active Master Builders who exist), a notice of "
                                 f"{RECOVER_NOTICE_DAYS} days after a freeze or {RECOVER_OPEN_NOTICE_DAYS} without one runs "
                                 f"({RECOVER_LOWERED_NOTICE_DAYS} whenever fewer co-signers are enough), and whoever holds "
                                 "the old key can stop it, unless it follows a recovery that key stopped. The old key is "
                                 "frozen during the notice.",
        "rekey_cosign": lambda: f"CO-SIGN the key recovery of {clean(b.get('login'))}.\nYou answer that the person asking "
                                "for the new key is that member. Check with them outside the ledger first.",
        "rekey_object": lambda: "STOP the recovery of your key.\nThe request is canceled, and no new one is accepted for "
                                f"your login for {RECOVER_INTERVAL_DAYS} days.",
        "rekey_oppose": lambda: f"OPPOSE the key recovery of {clean(b.get('login'))}.\nYour opposition is public and "
                                "counts once. When enough Master Builders oppose (one in five of those who may, and at "
                                "least one), the recovery is void.",
        "rekey_recover_apply": lambda: "COMPLETE the recovery of your key.\nFrom this entry on, only the new key signs "
                                       "for you; the old one is retired for good, and the freeze ends.",
        "correction_object": lambda: f"OBJECT to correction {clean(b.get('seq'))}" + _correction_ref(st, b.get("seq"))
                                     + "\nYour objection is public and counts once. When enough Master Builders object "
                                       "(one in five of those who may, and at least one), the correction is void for good.",
        "custodian_alive": lambda: f"SIGN OF LIFE of the custodian key {clean(who)}.\nWithout one, the key lapses for "
                                   f"good more than {CUSTODIAN_SILENCE_DAYS} days after the last.",
        "custodian_revoke": lambda: f"REVOKE the custodian key of {clean(b.get('name'))}, with its revoke key.\nThe key is "
                                    "removed at once and for good: it signs nothing more, and whatever it had in force ends.",
        "custodian_claim": lambda: f"CLAIM the office of Custodian again, as {clean(b.get('name'))}, with a new custodian "
                                   f"key {fingerprint(str(b.get('key')))} and a new revoke key "
                                   f"{fingerprint(str(b.get('revoke_key')))}.\nThe claim is public for "
                                   f"{CLAIM_NOTICE_DAYS} days; one Master Builder who is not a founder can stop it. You "
                                   f"apply it yourself between day {CLAIM_NOTICE_DAYS} and day {CLAIM_EXPIRY_DAYS}.",
        "custodian_claim_object": lambda: f"OBJECT to the claim of the Custodian office of entry {clean(b.get('seq'))}.\n"
                                          "One objection is enough: the claim is void for good.",
        "custodian_claim_apply": lambda: f"APPLY your claim of the Custodian office of entry {clean(b.get('seq'))}.\nIts "
                                         "custodian key becomes the only live one; it lapses by silence, at the Sunset, "
                                         "by its revoke key, by a removal ballot, and seven years from now.",
        "succession_claim": lambda: "CLAIM the succession: no active Master Builder is left.\nAny entry a Master Builder "
                                    f"signs within {SUCCESSION_DAYS} days cancels it. After them, the members of the highest "
                                    "degree present may examine, elect an advancement, invite and sponsor, and nothing "
                                    "else, until three Master Builders exist.",
    }.get(t, lambda: f"{clean(t)}: " + clean(json.dumps(b, ensure_ascii=False), 400))()
    return f"{lines}\n\nAs {clean(who)} · entry #{clean(entry['seq'], 20)} · {clean(entry['time'], 40)}"


def _correction_when(act: object, time: object) -> str:
    """When an immediate act lapses, or when the notice of a noticed act ends, counted from the entry's time."""
    try:
        t = ts(time)
    except (TypeError, ValueError):
        return ""
    if act in NOTICED_ACTS:
        return (f"\nIts notice ends at {iso(t + NOTICE_DAYS * DAY)}; it is applied by "
                f"{iso(t + (NOTICE_DAYS + APPLY_WINDOW_DAYS) * DAY)}, or never.")
    if isinstance(act, str) and act in ACT_DAYS:
        return f"\nIt lapses by itself at {iso(t + ACT_DAYS[act] * DAY)} at the latest."
    return ""


def reason_excerpt(data: bytes, lines: int = 5, limit: int = 400) -> str:
    """The first lines of a public reason, cleaned for a dialog."""
    rows = [x for x in clean(data.decode("utf-8", "replace"), 4000).splitlines() if x.strip()]
    text = "\n".join(rows[:lines])
    return text[:limit] + ("\n…" if len(rows) > lines or len(text) > limit else "")


def _correction_about(b: dict, time: object = None) -> str:
    """The dialog text of a `correction`: the act in plain words, when it lapses or its notice ends, then its
    ground and where its reason is."""
    act, target = b.get("act"), b.get("target")
    target = target if isinstance(target, dict) else {}
    name = lambda k: clean(target.get(k), 80)
    line = {
        "freeze_key": lambda: f"FREEZE the key of {name('login')} for {FREEZE_DAYS} days.\nWhile frozen, that member's "
                              "entries are refused, except to depart, rekey, vote (seal and reveal) in any ballot, "
                              "take part in an amendment ballot or the ballot that removes a custodian, or stop a "
                              "recovery of their key.",
        "freeze_witness": lambda: f"FREEZE the witness {name('name')} for {FREEZE_DAYS} days: its entries are refused.",
        "stay": lambda: f"STAY ballot {name('ballot')} for up to {STAY_DAYS} days.\nNo vote is sealed, revealed or counted "
                        "meanwhile, and its windows are extended by exactly the stayed time. A ballot is stayed once.",
        "halt": lambda: f"HALT the ledger for up to {HALT_DAYS} days.\nOnly custodian entries, objections, departures, "
                        "key replacements and recoveries, witness checkpoints, amendment ballots and the ballot that "
                        "removes a custodian are accepted meanwhile; other ballots, exams, invitations and petitions "
                        "lose no time.",
        "void_ballot": lambda: f"VOID ballot {name('id')}: it would end with no effect, and nobody is penalized.\nThis "
                               "only gives notice. The ballot is not closed while this is pending.",
        "undo_ballot": lambda: f"UNDO ballot {name('id')}: what it decided would be taken back, if nothing it changed "
                               f"was changed again since.\nThis only gives notice. Only an admission, an advancement or "
                               f"the addition of a witness closed in the last {UNDO_WINDOW_DAYS} days is undone.",
        "hold_room": lambda: f"HOLD {name('login')} out of the rooms for up to {HOLD_DAYS} days.",
        "note": lambda: f"NOTE a moderation act outside the ledger: {name('action')} {name('target')} under {name('rule')}."
                        "\nIt changes nothing in the ledger.",
    }.get(act, lambda: f"CORRECTION {clean(act, 40)}: " + clean(json.dumps(target, ensure_ascii=False), 200))()
    tail = ("" if act == "note" else
            f"\nNothing changes for {NOTICE_DAYS} days. Then a custodian applies it within {APPLY_WINDOW_DAYS} days, or it "
            "expires. Enough objections by Master Builders before that void it for good." if act in ("void_ballot", "undo_ballot")
            else f"\nIt takes effect at once, ends by itself, and Master Builders may object for {OBJECTION_DAYS} days.")
    return (f"{line}{tail}{_correction_when(act, time)}\nGround: {clean(b.get('ground'), 40)}"
            f"\nReason: {REASONS_DIR}/{clean(b.get('reason_sha256'), 64)}.md")


def _correction_ref(st: State | None, seq: object) -> str:
    c = st.corrections.get(seq) if st and isinstance(seq, int) and not isinstance(seq, bool) else None
    if c is None:
        return "."
    about = ", ".join(f"{clean(k)}={clean(v, 80)}" for k, v in c.target.items())
    return f" ({clean(c.act)}{': ' + about if about else ''}; by the custodian {clean(c.by)}, on the ground {clean(c.ground)})."


def _ballot_about(st: State | None, bid: object) -> str:
    bal = st.ballots.get(bid) if st and isinstance(bid, str) else None
    if bal is None:
        return "."
    return f" ({clean(bal.kind)}: " + ", ".join(f"{clean(k)}={clean(v, 80)}" for k, v in bal.subject.items() if k != "key") + ")."


# ------------------------------------------------------------- drafting -----

def _redact(entry: dict) -> dict:
    out = copy.deepcopy(entry)
    if out.get("type") == "ballot_reveal":
        out["body"] = {"id": out["body"].get("id"), "vote": "(sealed)", "salt": "(sealed)"}
    return out


def outbox_dir(st: State | None) -> Path:
    return HOME / "outbox" / ledger_id(st)


def _outbox_file(st: State | None, entry: dict) -> Path:
    """Where a signed entry of one's own waits for its pull request; a genesis, under the ledger it founds."""
    return (outbox_dir(st) if st is not None else HOME / "outbox" / entry_hash(entry)[:16]) / f"{entry['seq']:06d}.json"


def _waiting_genesis(e: dict) -> bool:
    try:
        return e.get("type") == "genesis" and e.get("seq") == 0 and _read_json(_outbox_file(None, e)) == e
    except (TypeError, ValueError, KeyError):
        return False


def _keep_in_outbox(st: State | None, entry: dict) -> None:
    _private_dir(HOME / "outbox")
    _write_private(_outbox_file(st, entry), entry)


def _outbox_reason(st: State | None, entry: dict) -> Path:
    """Where the public reason of a correction waits beside its entry, when publishing failed before its branch."""
    return _outbox_file(st, entry).with_suffix(".md")


def _forget_outbox(p: Path) -> None:
    p.unlink(missing_ok=True)
    p.with_suffix(".md").unlink(missing_ok=True)


def pushed(entry: dict) -> bool:
    """Whether this clone pushed the entry's branch: its upstream is the remote branch of the same name, which
    `git push -u` sets (the branch is made with --no-track, so a branch never pushed has no upstream). Git only."""
    branch = entry_branch(entry)
    up = _git("rev-parse", "--symbolic-full-name", f"{branch}@{{upstream}}")
    if up.returncode != 0:
        return False
    return any(up.stdout.strip() == f"refs/remotes/{r}/{branch}" for r in _git("remote").stdout.split())


def published(entry: dict, github: bool = False) -> bool:
    """Whether a signed entry of one's own reached GitHub. Without `github`, git only: its branch was pushed. With
    it, GitHub is asked for the pull request of this very entry (`entry_pr`): a pushed branch whose pull request
    could not be opened is not published, a pull request opened from another clone is, and a closed one (by hand,
    or by GitHub when its head branch was deleted) is not, as it never merges. When GitHub cannot be asked
    (offline, no gh), git's answer stands."""
    if github:
        asked, pr = entry_pr(entry)
        if asked:
            return live_pr(pr)
    return pushed(entry)


def live_pr(pr: dict | None) -> bool:
    """A pull request that is open or merged: a closed one never merges."""
    return pr is not None and pr.get("state") != "CLOSED"


def entry_tag(entry: dict) -> str:
    """The line of a pull request's body that names its entry, by the entry's digest."""
    return f"Entry sha256: {entry_hash(entry)}"


def entry_pr(entry: dict, state: str = "all") -> tuple[bool, dict | None]:
    """(GitHub answered, the pull request of this very entry or None). A pull request is the entry's when its body
    names the entry's digest (`entry_tag`, as `om` opens it), or when its head is this clone's branch and that
    branch holds this entry. An older pull request from the same branch name, of an entry dropped and drafted
    again at the same seq, is not this entry's. Among this entry's own, an open one comes first, then a merged one,
    then a closed one, whatever order gh lists them in. `state` is gh's: open, closed, merged or all."""
    branch = entry_branch(entry)
    try:
        r = _gh("pr", "list", "--repo", canon.CANONICAL_REPO, "--state", state, "--search", f"head:{branch}",
                "--json", "url,state,headRefName,headRefOid,body")
        prs = json.loads(r.stdout.strip() or "[]") if r.returncode == 0 else None
    except (OSError, ValueError):
        prs = None
    if not isinstance(prs, list):
        return False, None
    local = _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").stdout.strip()
    try:
        held = json.loads(_git("show", f"refs/heads/{branch}:{entry_path(Path(ENTRIES_DIR), entry['seq']).as_posix()}")
                          .stdout or "null") if local else None
    except ValueError:
        held = None
    local = local if held == entry else ""          # the branch holds another entry: its head says nothing here
    tag = entry_tag(entry)
    own = [{"url": pr.get("url"), "state": pr.get("state")} for pr in prs
           if isinstance(pr, dict) and pr.get("headRefName", branch) == branch
           and ((local and pr.get("headRefOid") == local) or tag in (pr.get("body") or ""))]
    rank = {"OPEN": 0, "MERGED": 1}
    return True, min(own, key=lambda pr: rank.get(pr["state"], 2), default=None)


def outbox(st: State | None, ledger: Path) -> tuple[list[dict], list[dict]]:
    """Own signed entries not in the ledger: (waiting for their PR, stale).

    An entry whose seq the ledger already holds is either *merged* (the ledger holds this very entry:
    its file is removed) or *stale* (another entry took that seq: it is kept for `om pending --rebase`,
    and a stale sealed vote no longer locks its ballot).
    """
    if not (is_repo_ledger(ledger) or _test_mode(ledger)):
        return [], []
    if st is None:                                 # before the genesis merged: one's own signed genesis waits
        return [e for e in map(_read_json, sorted(HOME.glob("outbox/*/000000.json"))) if _waiting_genesis(e)], []
    waiting, stale = [], []
    vault, vault_changed = None, False
    for p in sorted(outbox_dir(st).glob("*.json")) if outbox_dir(st).exists() else []:
        e = _read_json(p)
        seq = e.get("seq", -1)
        if not isinstance(seq, int) or seq < 0:
            continue
        if seq > st.seq:
            waiting.append(e)
            continue
        try:
            merged = entry_hash(e) == st.hashes[seq]
        except (TypeError, ValueError):
            merged = False
        if merged:
            _forget_outbox(p)                      # merged: the ledger is the truth now
            continue
        if e.get("type") == "ballot_commit":
            bal = st.ballots.get((e.get("body") or {}).get("id"))
            if bal is not None and e.get("actor") in bal.commits:
                _forget_outbox(p)                  # the person already sealed another vote there: obsolete
                continue
            vault = _read_json(VAULT) if vault is None else vault
            vk = vault_key(st, e.get("actor", ""), (e.get("body") or {}).get("id", ""))
            if vk in vault and vault[vk].get("seq") == seq and not vault[vk].get("stale"):
                vault[vk] = {**vault[vk], "stale": True}     # free the ballot: the vote never reached the ledger
                vault_changed = True
        stale.append(e)
    if vault_changed:
        _write_private(VAULT, vault)
    return waiting, stale


def pending_own(st: State | None, ledger: Path) -> list[dict]:
    """Own signed entries still waiting for their PR (stale ones excluded: see `outbox`)."""
    return outbox(st, ledger)[0]


def propose(a, typ: str, body: dict, summary: str, secret: dict | None = None, actor: str | None = None,
            key: Path | None = None, extra: dict | None = None) -> int:
    """Seal a draft. Never signs. Prints WOULD BE REFUSED (exit 1) or DRAFT (exit 3).

    The actor is the person's login and the key their member key, unless the act is signed otherwise: a
    custodian act names the custodian as `actor` and its key (or revoke key) as `key`; a key recovery is
    signed by the new key. `extra` adds fields to the printed contract (om.draft/1)."""
    st = state_of(a.ledger)
    _require_canonical(st, a.ledger)
    own_key = key is None                         # the member key, not a custodian, revoke or recovery key
    key = Path(key) if key is not None else key_path(getattr(a, "key", None))
    login = actor if actor is not None else canonical_login(st, need_login(a))
    if typ != "genesis" and st is None:
        raise UserError("the ledger is empty: the fraternity has not been founded yet")
    waiting = pending_own(st, a.ledger)
    if waiting:
        raise UserError(f"your entry #{waiting[0]['seq']} is still waiting for its pull request to be merged; "
                        f"draft again after it merges and you `git pull` (see `{OM} pending`)")
    if own_key and actor is None and typ not in ("genesis", "petition") and key.with_name(key.name + ".pub").exists():
        advice = key_advice(st, login, bare_public_key(key))   # a wrong configured key: say so now, not at approval
        if advice and st.members[login].status not in ("departed", "expelled", "voided"):
            raise UserError(f"{advice}. {OM} doctor shows which key is configured and why")
    entry = make_entry(st, typ, login, body, a.time if _test_mode(a.ledger, key) else None)
    trial = copy.deepcopy(st) if st else State()
    try:
        apply(trial, {**entry, "sig": ""}, verifier=lambda *_: True)
    except Invalid as err:
        return _out(a, {"refused": str(err)}, f"WOULD BE REFUSED — {err}", 1)
    digest = sha256(canonical(entry))
    _write_private(PENDING / f"{digest}.json", {
        "digest": digest, "ledger": str(Path(a.ledger).resolve()), "key": str(key),
        "entry": entry, "summary": summary, "secret": secret or {},
    })
    approve = [OM, "approve", digest[:16]]
    data = {"schema": "om.draft/1", "digest": digest, "summary": summary, "entry": _redact(entry), "approve": approve,
            **(extra or {})}
    if typ == "petition":
        import tomllib
        data["declaration"] = tomllib.loads((canon.CANON / "eternal.toml").read_text())["declaration"]["text"]
    text = (f"DRAFT {digest[:16]} — nothing was signed or published.\n  {summary}\n"
            f"  entry #{entry['seq']} · {typ} · by {login} · {entry['time']}\n\n"
            f"The person approves it with:  {cmdline(approve)}\n"
            "(a system dialog asks them; approving signs exactly this draft and opens the pull request)")
    return _out(a, data, text, NEEDS_APPROVAL)


def _out(a, data: dict, text: str, code: int) -> int:
    print(json.dumps(data, indent=2, ensure_ascii=False) if getattr(a, "json", False) else text)
    return code


# ------------------------------------------------------------- approving ----

TEST_CONFIRM = "insecure-auto-approve-for-tests"


def _test_mode(ledger: Path | None, key: Path | str | None = None) -> bool:
    """The dialog bypass for automated tests: never on the repository's own ledger, only with a marker file
    created by the test in its own temporary OM_HOME, and only when the signing key (`key`, else $OM_KEY)
    also lives inside that temporary OM_HOME, never in ~/.ssh."""
    if not (os.environ.get("OM_CONFIRM") == TEST_CONFIRM and (HOME / ".test-mode").exists()
            and ledger is not None and not is_repo_ledger(ledger)):
        return False
    import tempfile
    try:
        home = HOME.resolve()
        k = Path(key if key is not None else key_path(None)).expanduser().resolve()
        ssh = (Path.home() / ".ssh").resolve()
        return (home.is_relative_to(Path(tempfile.gettempdir()).resolve()) and k.is_relative_to(home)
                and not k.is_relative_to(ssh))
    except (OSError, RuntimeError):
        return False


# The Windows dialog: a small Windows Forms window, its text in a read-only box and one button per choice, Cancel
# first and default. Title, text and buttons come in through the environment, never through the command line.
# Any error (no window can open: an SSH session, no interactive desktop) exits 3, never 0 with no choice, so that
# the console is asked instead of reading the failure as Cancel.
WINDOWS_DIALOG = r"""
$ErrorActionPreference = 'Stop'
try {
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.Form
$f.Text = $env:OM_DIALOG_TITLE; $f.TopMost = $true; $f.StartPosition = 'CenterScreen'
$f.Width = 720; $f.Height = 480; $f.FormBorderStyle = 'FixedDialog'; $f.MaximizeBox = $false; $f.MinimizeBox = $false
$t = New-Object System.Windows.Forms.TextBox
$t.Multiline = $true; $t.ReadOnly = $true; $t.ScrollBars = 'Vertical'; $t.WordWrap = $true; $t.Dock = 'Fill'
$t.Text = ($env:OM_DIALOG_TEXT -replace "`r?`n", "`r`n"); $t.Font = New-Object System.Drawing.Font('Consolas', 10)
$p = New-Object System.Windows.Forms.FlowLayoutPanel
$p.Dock = 'Bottom'; $p.Height = 44; $p.FlowDirection = 'RightToLeft'
$script:choice = ''
foreach ($b in ($env:OM_DIALOG_BUTTONS -split "`n")) {
  $x = New-Object System.Windows.Forms.Button; $x.Text = $b; $x.AutoSize = $true
  $x.Add_Click({ $script:choice = $this.Text; $f.Close() }); $p.Controls.Add($x)
  if ($b -eq 'Cancel') { $f.CancelButton = $x; $f.AcceptButton = $x }
}
$f.Controls.Add($t); $f.Controls.Add($p)
[void]$f.ShowDialog()
} catch { exit 3 }
[Console]::Out.Write($script:choice)
"""


def _typed_code(title: str, text: str, buttons: list[str], read, write) -> str | None:
    """The terminal fallback: the person types `<button>-<code>`, a code made for this run; anything else cancels."""
    code = secrets.token_hex(2)
    options = " / ".join(f"{b.lower()}-{code}" for b in buttons)
    write(f"\n{title}\n{text}\n\nType one of: {options} (anything else cancels): ")
    answer = read().strip().lower()
    return next((b for b in buttons if answer == f"{b.lower()}-{code}"), None)


def _ask_windows(title: str, text: str, buttons: list[str]) -> str | None:
    """Native Windows: the PowerShell dialog, else the console (CONIN$/CONOUT$, never stdin, which an agent may
    hold). False when neither can ask."""
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell:
        env = {**os.environ, "OM_DIALOG_TITLE": title, "OM_DIALOG_TEXT": text,
               "OM_DIALOG_BUTTONS": "\n".join(["Cancel", *buttons])}
        try:
            r = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-STA", "-Command", WINDOWS_DIALOG],
                               capture_output=True, text=True, env=env)
        except OSError:
            r = None
        if r is not None and r.returncode == 0:
            choice = r.stdout.strip()
            return choice if choice in buttons else None
    try:
        with open("CONIN$", "r") as cin, open("CONOUT$", "w") as cout:
            return _typed_code(title, text, buttons, cin.readline, lambda s: (cout.write(s), cout.flush()))
    except OSError:
        return False                               # type: ignore[return-value]


def _ask(title: str, text: str, buttons: list[str], ledger: Path | None, test_answer: str | None = None,
         key: Path | None = None, limit: int = 1500) -> str | None:
    """Ask the human outside the agent. Returns the chosen button, or None if canceled. `limit` bounds the text
    shown (the application dialog shows all of it)."""
    if _test_mode(ledger, key):
        print("WARNING: approval dialog bypassed (test mode)", file=sys.stderr)
        return test_answer or buttons[-1]
    text = clean(text, limit)
    if sys.platform == "win32":
        choice = _ask_windows(title, text, buttons)
        if choice is not False:
            return choice
        raise UserError("no way to ask the person: approve from a desktop session or a console window of your own")
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = ('on run argv\n set b to items 3 thru -1 of argv\n'
                  ' display dialog (item 2 of argv) with title (item 1 of argv) buttons b '
                  'default button 1 cancel button 1 with icon caution\n return button returned of result\nend run')
        r = subprocess.run(["osascript", "-e", script, title, text, "Cancel", *buttons], capture_output=True, text=True)
        choice = r.stdout.strip()
        if r.returncode == 0:
            return choice if choice in buttons else None
        if "-128" in r.stderr:                     # the person pressed Cancel; any other failure (no desktop
            return None                            # session: -1713, -1728…) falls back to the terminal
    elif os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        if shutil.which("zenity"):
            args = ["zenity", "--question", "--no-markup", "--title", title, "--text", text,
                    "--ok-label", buttons[-1], "--cancel-label", "Cancel"]
            for extra in buttons[:-1]:
                args += ["--extra-button", extra]
            r = subprocess.run(args, capture_output=True, text=True)
            if r.returncode == 0:
                return buttons[-1]
            return r.stdout.strip() if r.stdout.strip() in buttons else None
        if shutil.which("kdialog") and len(buttons) <= 2:
            esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if len(buttons) == 1:
                return buttons[0] if subprocess.run(["kdialog", "--title", title, "--yesno", esc]).returncode == 0 else None
            r = subprocess.run(["kdialog", "--title", title, "--yesnocancel", esc,
                                "--yes-label", buttons[1], "--no-label", buttons[0]]).returncode
            return {0: buttons[1], 1: buttons[0]}.get(r)
    try:                                           # two files: a text-mode "r+" open of a terminal is refused
        with open("/dev/tty", "r") as tin, open("/dev/tty", "w") as tout:
            return _typed_code(title, text, buttons, tin.readline, lambda s: (tout.write(s), tout.flush()))
    except OSError:
        raise UserError("no way to ask the person: approve from a desktop session or a real terminal")


def _expected_key(st: State | None, entry: dict) -> str | None:
    if entry["type"] == "genesis":
        return (entry["body"].get("founders") or [{}])[0].get("key")
    if entry["type"] == "petition":
        return entry["body"].get("key")
    if st is None:
        return None
    if entry["type"] in CUSTODIAN_SIGNED:          # the custodian key, or its revoke key: never a member key
        c = st.custodians.get(entry["actor"])
        return None if c is None else c.revoke_key if entry["type"] == "custodian_revoke" else c.key
    if entry["type"] == "rekey_recover":           # the new key signs the request…
        return entry["body"].get("key")
    if entry["type"] == "rekey_recover_apply":     # …and its application
        r = st.recoveries.get(entry["actor"])
        return r.key if r is not None else None
    m = st.members.get(entry["actor"])
    return m.key if m else None


def _tip(err: Exception) -> str:
    """The text of a SigningError, with the `ssh-add PATH` it may suggest quoted for this platform's shell."""
    import re as _re
    return _re.sub(r"`ssh-add (.+?)`", lambda m: f"`{cmdline(['ssh-add', m.group(1)])}`", str(err))


def _find_pending(digest: str) -> Path:
    import re as _re
    if not _re.fullmatch(r"[0-9a-f]{12,64}", digest or ""):
        raise UserError("a draft digest is 12 to 64 lowercase hex characters")
    hits = [p for p in PENDING.glob(f"{digest}*.json")] if PENDING.exists() else []
    if len(hits) != 1:
        raise UserError(f"no single pending draft matches {digest}" + (" (ambiguous)" if hits else ""))
    return hits[0]


CLOCK_REFUSE_AHEAD = 90                         # seconds: the judge refuses an entry stamped 2 minutes ahead of its clock


def clock_gate(entry: dict) -> None:
    """Before signing: hold the entry's time against GitHub's clock (the Date header of api.github.com), when it
    can be read. Refuse an entry stamped more than CLOCK_REFUSE_AHEAD seconds ahead (the judge would refuse it
    only after the pull request is open), or too old for the judge; warn when this clock is off by over 30 s."""
    from .onboard import CLOCK_FIX, CLOCK_WARN, github_clock_skew
    skew = github_clock_skew()
    if skew is None:
        return
    github_now = now_utc() - timedelta(seconds=skew)
    ahead = (ts(entry["time"]) - github_now).total_seconds()
    if ahead > CLOCK_REFUSE_AHEAD:
        raise UserError(f"this draft is stamped {ahead:.0f} seconds ahead of GitHub's clock (this machine's clock is "
                        f"{skew:.0f} seconds fast): the judge refuses an entry more than 2 minutes ahead of its clock. "
                        f"Set the clock ({CLOCK_FIX}), then draft again")
    if github_now - ts(entry["time"]) > CLOCK_TOLERANCE - CLOCK_TOLERANCE / 12:
        raise UserError("STALE — by GitHub's clock this draft is too old to be accepted by the Tyler; draft it again")
    if abs(skew) > CLOCK_WARN:
        print(f"note: this machine's clock is {abs(skew):.0f} seconds {'ahead of' if skew > 0 else 'behind'} GitHub's; "
              f"{CLOCK_FIX}", file=sys.stderr)


def publish_preflight() -> None:
    """Before signing an entry that is published at once: gh must name the account that publishes (the commit of
    the entry is made in its name, `commit_account`) and git must be able to push over HTTPS (credentials), or the
    signed entry would be left unpublished. A git identity of the clone that differs is named in one line and never
    refused: `om` does not commit an entry with it."""
    from . import onboard
    try:
        name, mail = noreply(commit_account())
    except UserError as err:
        raise UserError(f"{err}; nothing was signed") from None
    had = tuple(onboard._git("config", "--get", k).stdout.strip() for k in ("user.name", "user.email"))
    if had != (name, mail):
        print(f"note: this clone's git identity is {had[0] or '(no name)'} <{had[1] or 'no e-mail'}>; om commits "
              f"each entry as {name} <{mail}> in UTC instead", file=sys.stderr)
    c = onboard.git_credentials()
    fix = c["fix"] or {}
    how = (cmdline(fix["argv"]) + ": " if fix.get("argv") else "") + (fix.get("text") or "")
    if c["status"] == "fail":
        raise UserError(f"{c['message']}. Fix it first ({how}); nothing was signed")
    if c["status"] == "warn":
        print(f"note: {c['message']} ({how})", file=sys.stderr)


def commit_account() -> tuple[str, int]:
    """(login, numeric id) of the GitHub account that publishes, as gh reports it. Every commit `om` makes for an
    entry is authored and committed in that account's name, with GitHub's private address, in UTC (`commit_env`),
    whatever the clone's git configuration says: no personal e-mail and no time zone ever enter `main`."""
    from .onboard import gh_user
    user = gh_user()
    if user is None:
        raise UserError("gh cannot tell which GitHub account publishes (`gh auth status`; with a separate "
                        "configuration, set GH_CONFIG_DIR to it): the commit of an entry is made in that account's "
                        "name, with GitHub's private address")
    return user


def noreply(user: tuple[str, int]) -> tuple[str, str]:
    """The name and e-mail of a GitHub account's commits: its login and its private address."""
    return user[0], f"{user[1]}+{user[0]}@users.noreply.github.com"


def commit_env(user: tuple[str, int]) -> dict[str, str]:
    """git's environment for the commit of an entry: author and committer are `user` (`noreply`), and both dates are
    now, in UTC (+0000)."""
    name, mail = noreply(user)
    when = now_utc().strftime("%Y-%m-%dT%H:%M:%S+0000")
    return {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": mail, "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": mail, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "TZ": "UTC"}


def commit_checked(st: State | None, entry: dict) -> bool:
    """Whether the commit of an entry is read back before it is pushed: an entry only the founding account may
    publish (`founding_account`), and every custodian entry."""
    return founding_account(st, entry) is not None or entry.get("type") in CUSTODIAN_SIGNED


def commit_mismatch(ref: str, user: tuple[str, int]) -> str | None:
    """None when the commit `ref` names is authored and committed as `user` (`noreply`) with both dates in +0000;
    else what it carries."""
    want = "{} <{}>".format(*noreply(user))
    r = _git("log", "-1", "--date=raw", "--format=%an <%ae>%x00%ad%x00%cn <%ce>%x00%cd", ref)
    parts = r.stdout.strip("\n").split("\0") if r.returncode == 0 else []
    if len(parts) != 4:
        return "a commit git could not read"
    if parts[0] == parts[2] == want and parts[1].endswith(" +0000") and parts[3].endswith(" +0000"):
        return None
    return f"author {parts[0]} {parts[1]} and committer {parts[2]} {parts[3]}"


def founding_account(st: State | None, entry: dict) -> tuple[int, str] | None:
    """(the numeric GitHub id an entry must be published from, who it is), or None when any account may publish it.
    The genesis comes only from the founding account (`founder_github_id` of network.toml). An entry a founder
    signs comes only from the account the ledger records for that founder, and so does an entry of a custodian
    linked to a founder: a slip that published one from another account would tie that account to the founder's
    for good, in public. A petition comes only from the account its invitation names, whatever record the login
    held before: a departed founder's login may now name a newcomer, and a returning founder is invited by the
    founder's own id."""
    if entry.get("type") == "genesis":
        return canon.FOUNDER_GITHUB_ID, "the genesis"
    actor = entry.get("actor")
    if st is None or not isinstance(actor, str):
        return None
    if entry.get("type") == "petition":
        inv = st.invitations.get(actor)
        return (inv["github_id"], f"a petition of {actor} (by the account its invitation names)") if inv else None
    m = st.members.get(actor)
    if m is not None and m.founder and entry.get("type") not in CUSTODIAN_SIGNED:
        return m.github_id, f"an entry signed by the founder {actor}"
    c = st.custodians.get(actor) if entry.get("type") in CUSTODIAN_SIGNED else None
    linked = st.members.get(c.member) if c is not None and c.member else None
    if linked is not None and linked.founder:
        return linked.github_id, f"an entry signed by the custodian {actor} (linked to the founder {linked.login})"
    return None


def account_guard(st: State | None, entry: dict, then: str) -> None:
    """Refuse to publish an entry from a GitHub account other than the one it must come from (`founding_account`),
    as gh reports it (the account of GH_CONFIG_DIR, or of a token in the environment). `then` ends the message."""
    need = founding_account(st, entry)
    if need is None:
        return
    want, who = need
    if want <= 0:
        raise UserError(f"NOT PUBLISHED — {who} is published only from the founding account, and founder_github_id is "
                        f"not set in src/openmasonry/network.toml. {then}")
    from .onboard import gh_user
    user = gh_user()
    if user is None:
        raise UserError(f"NOT PUBLISHED — {who} is published only from the GitHub account with id {want}, and gh "
                        "cannot tell which account it is logged in as (`gh auth status`; with a separate "
                        f"configuration, set GH_CONFIG_DIR to it). {then}")
    if user[1] != want:
        raise UserError(f"NOT PUBLISHED — {who} is published only from the GitHub account with id {want}, but gh is "
                        f"logged in as {user[0]} (id {user[1]}). Log gh in to that account (or set GH_CONFIG_DIR to "
                        f"its configuration) and try again. {then}")


def cmd_approve(a) -> int:
    path = _find_pending(a.digest)
    d = _read_json(path)
    e = d.get("entry") or {}
    if not e or sha256(canonical(e)) != path.stem or d.get("digest") != path.stem:
        raise UserError("TAMPERED — this draft does not match its digest; discard it and draft again")
    ledger = Path(d["ledger"])
    key = Path(d["key"])
    test = _test_mode(ledger, key)
    if not is_repo_ledger(ledger) and not test:
        raise UserError("drafts can only be approved into this repository's ledger")
    st = state_of(ledger)
    _require_canonical(st, ledger)
    if e["seq"] != (st.seq if st else -1) + 1 or e["prev"] != (st.head if st else canon.ZERO_HASH):
        raise UserError("STALE — the ledger moved since this draft; draft it again")
    if not test and now_utc() - ts(e["time"]) > CLOCK_TOLERANCE - (CLOCK_TOLERANCE / 12):
        raise UserError("STALE — this draft is too old to be accepted by the Tyler; draft it again")
    waiting = pending_own(st, ledger)
    if waiting:                                   # a signed entry of yours already takes this place in the ledger
        w = waiting[0]
        raise UserError(f"STALE — your signed entry #{w['seq']} ({w['type']}) is waiting for its pull request at this "
                        f"place in the ledger; once it merges, `git pull` and draft this act again (if it was "
                        f"abandoned: {OM} pending --drop {w['seq']} first). Nothing was signed")
    expected = _expected_key(st, e)
    if expected is None or bare_public_key(key) != expected:
        raise UserError(f"the key {key} is not the one this act must be signed with ({OM} doctor shows which key is "
                        "configured)")
    if not test:
        clock_gate(e)
        from .onboard import AGENT_FIX, AGENT_SILENT, add_key_command, agent_listing, passphrase_blocks
        if agent_listing()[1]:
            raise UserError(f"NOT SIGNED — {AGENT_SILENT}: {AGENT_FIX}. Nothing was signed")
        if passphrase_blocks(key):
            raise UserError(f"NOT SIGNED — the key {key} asks for its passphrase and is not in the ssh-agent, and there "
                            f"is no terminal here to type it: the person loads it first ({cmdline(add_key_command(key))}"
                            f") or runs {cmdline([OM, 'approve', path.stem[:16]])} in a terminal of their own. Nothing "
                            "was signed")
    canon_remote, submit_login = "origin", None
    if is_repo_ledger(ledger) and not a.no_submit:
        canon_remote = _require_in_sync(st.hashes if st else ())
        publish_preflight()
        account_guard(st, e, "Nothing was signed")
        if e["type"] in CUSTODIAN_SIGNED:           # the actor is a custodian name, not a GitHub account
            submit_login = detect_login(None)
            if not submit_login:
                raise UserError("cannot tell your GitHub login: the pull request of a custodian entry is opened from "
                                "a GitHub account (any account: the judge reads the custodian signature, not the "
                                "author). Run `gh auth login`, or set OM_LOGIN")
    secret = d.get("secret") or {}
    entry = dict(e)
    reason: bytes | None = None
    rebased = e["type"] == "ballot_commit" and secret.get("rebase")
    if rebased:                                   # re-sequencing re-seals the vote the person already chose
        bid = e["body"]["id"]
        # Only a vote this machine's vault sealed at an earlier approval, and that lost its place in the ledger: the
        # draft file names the vote, and whoever can write it must not choose it.
        vk = vault_key(st, e["actor"], bid)
        sealed = _read_json(VAULT).get(vk) or {}
        if (secret.get("vault_key") != vk or not sealed.get("stale") or sealed.get("vote") not in ("yes", "no")
                or (sealed.get("vote"), sealed.get("salt")) != (secret.get("vote"), secret.get("salt"))
                or e["body"].get("commitment") != commitment(bid, e["actor"], sealed["vote"], str(sealed.get("salt")))):
            raise UserError("TAMPERED — this re-sealed vote is not the vote this machine sealed for that ballot and "
                            "that lost its place in the ledger; discard it, and vote again")
        if _ask("OpenMasonry: re-seal your vote?", describe(st, e) + f"\n\nYour sealed vote: {sealed['vote'].upper()}."
                "\n\nYour earlier sealed vote never reached the ledger; this signs the same sealed vote again at a new "
                "position.", ["Approve and sign"], ledger, key=key) is None:
            return _out(a, {"canceled": True}, "Canceled. Nothing was signed.", 1)
    elif e["type"] == "ballot_commit":            # the vote is chosen here, by the person, never by the agent
        bid = e["body"]["id"]
        choice = _ask("OpenMasonry: your vote", describe(st, e) + "\n\nChoose your vote. It stays sealed until you reveal it.",
                      ["No", "Yes"], ledger, test_answer=getattr(a, "test_vote", None), key=key)
        if choice is None:
            return _out(a, {"canceled": True}, "Canceled. Nothing was signed.", 1)
        vote = choice.lower()
        entry = {**e, "body": {"id": bid, "commitment": commitment(bid, e["actor"], vote, secret["salt"])}}
        secret = {**secret, "vote": vote}
    elif e["type"] == "rekey" and e["body"].get("proof") == REKEY_PROOF_PENDING:
        new_key = Path(str(secret.get("new_key", "")))
        if bare_public_key(new_key) != e["body"].get("key"):
            raise UserError(f"the key {new_key} is not the new key of this draft")
        if _ask("OpenMasonry: replace your signing key?", describe(st, e) + "\n\nApproving signs twice: the new key "
                "proves it is yours, then your current key signs the entry.", ["Approve and sign"], ledger,
                key=key) is None:
            return _out(a, {"canceled": True}, "Canceled. Nothing was signed.", 1)
        try:                                      # the proof: the new key binds itself to this login and the old key
            proof = sign(rekey_message(e["actor"], expected, e["body"]["key"]), new_key)
        except SigningError as err:
            raise UserError(f"NOT SIGNED — the new key could not sign its proof: {_tip(err)}") from None
        entry = {**e, "body": {"key": e["body"]["key"], "proof": proof}}
    elif e["type"] == "rekey_recover" and e["body"].get("proof") == REKEY_PROOF_PENDING:
        old = st.members[e["actor"]].key if st and e["actor"] in st.members else None
        if old is None:
            raise UserError(f"{e['actor']} is not a member: only a member has a key to recover")
        if _ask("OpenMasonry: ask to recover your key?", describe(st, e) + "\n\nApproving signs twice with the NEW "
                "key: the proof that it is yours, then the entry. The key the ledger holds signs nothing here.",
                ["Approve and sign"], ledger, key=key) is None:
            return _out(a, {"canceled": True}, "Canceled. Nothing was signed.", 1)
        try:
            proof = sign(rekey_message(e["actor"], old, e["body"]["key"]), key)
        except SigningError as err:
            raise UserError(f"NOT SIGNED — the new key could not sign its proof: {_tip(err)}") from None
        entry = {**e, "body": {"key": e["body"]["key"], "proof": proof}}
    elif e["type"] == "genesis" and CUSTODIAN_PROOF_PENDING in json.dumps(e["body"]):
        named = e["body"]["custodians"]
        held = _custodian_keys(named, secret.get("custodians") or {})      # refuses unless every private key is here
        others = _pending_proofs(e["body"], secret.get("proofs") or {})    # cofounders and witnesses whose key is here
        if _ask("OpenMasonry: found the fraternity?", describe(st, e) + f"\n\nApproving signs "
                f"{2 * len(named) + len(others) + 1} times: each custodian key and each revoke key signs its proof of "
                "possession, so both private keys of every custodian must be here now, and so does the key of each "
                "cofounder and witness whose proof was not given; then your founder key signs the entry. Afterwards "
                "store each revoke key separately and offline.", ["Approve and sign"], ledger, key=key) is None:
            return _out(a, {"canceled": True}, "Canceled. Nothing was signed.", 1)
        proved = []
        for c in named:
            k, r = held[c["name"]]
            try:
                proved.append({**c, "proof": sign(custodian_message(c["name"], c["member"], c["key"]), k),
                               "revoke_proof": sign(custodian_revoke_message(c["name"], c["key"], c["revoke_key"]), r)})
            except SigningError as err:
                raise UserError(f"NOT SIGNED — a key of the custodian {c['name']} could not sign its proof of "
                                f"possession: {_tip(err)}") from None
        body = {**e["body"], "custodians": proved}
        try:
            body["founders"] = [{**f, "proof": sign(founder_message(f["login"], f["github_id"], f["key"]),
                                                    others[("founder", f["login"])])}
                                if ("founder", f["login"]) in others else f for f in body["founders"]]
            body["witnesses"] = [{**w, "proof": sign(witness_message(w["name"], w["key"]), others[("witness", w["name"])])}
                                 if ("witness", w["name"]) in others else w for w in body["witnesses"]]
        except SigningError as err:
            raise UserError(f"NOT SIGNED — a cofounder or witness key could not sign its proof of possession: {_tip(err)}") from None
        entry = {**e, "body": body}
    elif e["type"] == "custodian_claim" and CUSTODIAN_PROOF_PENDING in (e["body"].get("proof"), e["body"].get("revoke_proof")):
        b = e["body"]
        k, r = _claim_keys(b, secret.get("claim") or {})                  # refuses unless both private keys are here
        if _ask("OpenMasonry: claim the Custodian office?", describe(st, e) + "\n\nApproving signs three times: the "
                "custodian key and the revoke key each sign their proof of possession, once, so both private keys "
                "must be here now; then your member key signs the entry. Afterwards store the revoke key separately "
                "and offline: it is the one key that removes the custodian key at once.", ["Approve and sign"],
                ledger, key=key) is None:
            return _out(a, {"canceled": True}, "Canceled. Nothing was signed.", 1)
        try:
            proofs = {"proof": sign(custodian_message(b["name"], e["actor"], b["key"]), k),
                      "revoke_proof": sign(custodian_revoke_message(b["name"], b["key"], b["revoke_key"]), r)}
        except SigningError as err:
            raise UserError(f"NOT SIGNED — a key of the claimed custodian {b['name']} could not sign its proof of "
                            f"possession: {_tip(err)}") from None
        entry = {**e, "body": {**b, **proofs}}
    elif e["type"] == "correction":
        try:
            reason = base64.b64decode(str(secret.get("reason", "")), validate=True)
        except ValueError:
            reason = b""
        if not reason or sha256(reason) != e["body"].get("reason_sha256"):
            raise UserError("TAMPERED — the staged reason does not match the reason_sha256 of this draft; discard it "
                            "and draft again")
        if _ask("OpenMasonry: approve this correction?", describe(st, e) + "\n\nThe reason, as it will be published "
                f"(public for good, {len(reason)} bytes):\n" + reason_excerpt(reason), ["Approve and sign"], ledger,
                key=key) is None:
            return _out(a, {"canceled": True}, "Canceled. Nothing was signed.", 1)
    elif _ask("OpenMasonry: approve this act?", describe(st, e)
              + ("\n\nThis re-sequences an act of yours that never reached the ledger." if secret.get("rebase") else ""),
              ["Approve and sign"], ledger, key=key) is None:
        return _out(a, {"canceled": True}, "Canceled. Nothing was signed.", 1)
    try:
        entry["sig"] = sign(signed_payload(entry), key)
    except SigningError as err:
        raise UserError(f"NOT SIGNED — {_tip(err)}") from None
    trial = copy.deepcopy(st) if st else State()
    try:
        apply(trial, entry)
    except Invalid as err:
        return _out(a, {"refused": str(err)}, f"REFUSED — {err}", 1)
    ledger.mkdir(parents=True, exist_ok=True)
    extra: list[Path] = []
    if entry["type"] == "genesis":              # archive the ratified canon so history replays forever
        hist = canon.CANON / "history" / f"{entry['body']['pins']['canon/degrees.toml']}.toml"
        hist.parent.mkdir(exist_ok=True)
        if not hist.exists():
            hist.write_bytes((canon.CANON / "degrees.toml").read_bytes())
        extra.append(hist)
    out = entry_path(ledger, entry["seq"])
    try:
        text = entry_text(entry)
    except Invalid as err:
        return _out(a, {"refused": str(err)}, f"REFUSED — {err}", 1)
    if reason is not None:                      # the public reason travels with the entry that pins it
        archived = reasons_dir(ledger) / f"{entry['body']['reason_sha256']}.md"
        archived.parent.mkdir(parents=True, exist_ok=True)
        if not archived.exists() or archived.read_bytes() != reason:
            archived.write_bytes(reason)
        extra.append(archived)
    out.parent.mkdir(exist_ok=True)              # the shard of the entry (SPEC §2.7)
    out.write_text(text, encoding="utf-8")
    if secret.get("vault_key"):                    # the sealed vote is kept only once it is signed
        vault = _read_json(VAULT)
        vault[secret["vault_key"]] = {"salt": secret["salt"], "vote": secret["vote"], "seq": entry["seq"]}
        _write_private(VAULT, vault)
    path.unlink(missing_ok=True)
    if entry["type"] == "rekey":                   # from now on this machine signs with the new key
        config = _read_json(CONFIG)
        new_key = str(secret.get("new_key") or config.get("key") or "")
        if new_key and new_key != str(key):
            _write_private(CONFIG, {**config, "key": new_key, "previous_key": str(key)})
            if os.environ.get("OM_KEY"):
                print(f"note: OM_KEY still names {os.environ['OM_KEY']}; point it to {new_key} (or unset it: the new "
                      f"key is now configured in {CONFIG})", file=sys.stderr)
    if entry["type"] == "rekey_recover":           # remembered, so that `om recover-apply` signs with it later
        _write_private(CONFIG, {**_read_json(CONFIG), "recovery_key": str(key)})
    if entry["type"] == "rekey_recover_apply":     # the recovery is complete: this machine signs with the new key
        config = {k: v for k, v in _read_json(CONFIG).items() if k != "recovery_key"}
        previous = config.get("key") or os.environ.get("OM_KEY")
        _write_private(CONFIG, {**config, "key": str(key)} | ({"previous_key": previous} if previous and previous != str(key) else {}))
        if os.environ.get("OM_KEY") and os.environ["OM_KEY"] != str(key):
            print(f"note: OM_KEY still names {os.environ['OM_KEY']}; point it to {key} (or unset it: the new key is "
                  f"now configured in {CONFIG})", file=sys.stderr)
    if secret.get("replaces") and st is not None:      # the stale entry this one re-sequenced
        old = outbox_dir(st) / Path(str(secret["replaces"])).name
        old.unlink(missing_ok=True)
    result = {"schema": "om.approved/1", "seq": entry["seq"], "type": entry["type"], "file": str(out), "pr": None}
    if reason is not None:
        result["reason_file"] = str(reasons_dir(ledger) / f"{entry['body']['reason_sha256']}.md")
    if is_repo_ledger(ledger) and not a.no_submit:
        _keep_in_outbox(trial, entry)             # keep it visible locally until its PR merges
        code, pr = _publish_kept([out, *extra], entry, canon_remote, submit_login, trial)
        result["pr"] = pr
        return _out(a, result, f"signed: {out}\n{pr or ''}".strip(), code)
    return _out(a, result, f"signed: {out}", 0)


# --------------------------------------------------------------- git/PR ----

def _git(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run git in this clone (with `env` as its whole environment, when given); without git installed, it answers
    exit code 127, as a shell would."""
    try:
        return subprocess.run(["git", "-C", str(canon.ROOT), *args], capture_output=True, text=True, env=env)
    except (FileNotFoundError, PermissionError, NotADirectoryError) as err:
        return subprocess.CompletedProcess(["git", *args], 127, "", f"git: {err.strerror or err}")


def remote_slug(url: str) -> str | None:
    """'git@github.com:o/r.git' or 'https://github.com/o/r(.git)' -> 'o/r' (lower case)."""
    import re as _re
    m = _re.search(r"github\.com[:/]([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$", url.strip())
    return m.group(1).lower() if m else None


def canonical_remote() -> str | None:
    """The name of the git remote that points to the canonical repository, if any."""
    for line in _git("remote", "-v").stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and remote_slug(parts[1]) == canon.CANONICAL_REPO.lower():
            return parts[0]
    return None


# The client rule of SPEC §9.7. `ledger.head_verdict` decides; here are the files and git.

BLOCKING = ("rollback", "canonical_behind", "genesis", "future", "invalid")   # on these nothing is drafted, approved or signed


def _batch_blobs(out: bytes, count: int) -> list[bytes]:
    """The contents `git cat-file --batch` printed for `count` objects, in order. Pure. ValueError when the
    output is not `count` records of `<id> blob <size>`, a line feed, `size` bytes and a line feed."""
    blobs, at = [], 0
    for _ in range(count):
        end = out.index(b"\n", at)
        head = out[at:end].split()
        if len(head) != 3 or head[1] != b"blob":
            raise ValueError("not a blob")
        size = int(head[2])
        blobs.append(out[end + 1:end + 1 + size])
        if len(blobs[-1]) != size or out[end + 1 + size:end + 2 + size] != b"\n":
            raise ValueError("truncated")
        at = end + 2 + size
    return blobs


ENTRIES_DIR = "ledger/entries"                 # the entries directory of the repository's tree


def _tree_files(listing: str) -> dict[str, tuple[str, str]]:
    """`git ls-tree -r` of the entries directory as {path inside it: (mode, object id)}. Pure."""
    files = {}
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        if len(meta.split()) == 3 and path.startswith(ENTRIES_DIR + "/"):
            files[path.removeprefix(ENTRIES_DIR + "/")] = (meta.split()[0], meta.split()[2])
    return files


def canonical_ledger() -> list[dict] | None:
    """The entries of the canonical ledger as this clone last fetched it: `ledger/entries/` of the branch
    `main` of the canonical remote, read from git, never from the working tree (which may hold entries of
    one's own that are not merged). None when the clone has no such branch. Raises Invalid when what is
    there is not a ledger."""
    remote = canonical_remote()
    if remote is None:
        return None
    listing = _git("ls-tree", "-r", f"refs/remotes/{remote}/main", ENTRIES_DIR + "/")   # the branch, never a tag of that name
    if listing.returncode != 0:
        return None
    blobs = _tree_files(listing.stdout)
    names = entry_order(blobs)                   # the rules of the loader (SPEC §2.7) on the names of the tree
    for i, name in enumerate(names):
        if blobs[name][0] not in ("100644", "100755"):
            raise Invalid(i, f"ledger file {name} must be a regular file, not a symlink or a directory")
    r = subprocess.run(["git", "-C", str(canon.ROOT), "cat-file", "--batch"], capture_output=True,
                       input="".join(blobs[n][1] + "\n" for n in names).encode())
    try:
        raws = _batch_blobs(r.stdout, len(names)) if r.returncode == 0 else None
    except ValueError:
        raws = None
    if raws is None:
        raise Invalid(0, f"cannot read the entries of {remote}/main from git")
    entries = []
    for i, (name, raw) in enumerate(zip(names, raws)):
        try:
            e = strict_json(raw)
        except ValueError as err:
            raise Invalid(i, f"{name} is not strict JSON: {err}") from None
        if type(e) is not dict or type(e.get("seq")) is not int or e["seq"] != i:
            raise Invalid(i, f"{name} does not hold entry {i}")
        entries.append(e)
    return entries


def canonical_guard(known=(), accept: str | None = None, now: datetime | None = None) -> tuple[str, str]:
    """(verdict, message): the canonical ledger against the head this clone verified earlier (SPEC §9.7).

    `known` are the entry hashes of the ledger the caller has just replayed (the working copy). The canonical
    ledger is verified first: it is a prefix of `known`, or it is replayed here. Only then is it compared with
    the remembered head, and only when it holds that head (or nothing was remembered, or the person accepts
    it with `accept`, the hash of its genesis) is its own head remembered in `HEADS`.

    Verdicts: `none` (no canonical ledger to look at), `ok`; and those of `BLOCKING`: `rollback`,
    `canonical_behind`, `genesis`, `future` (its last entry is dated ahead of this clock) and `invalid`.
    """
    try:
        entries = canonical_ledger()
        if not entries:
            return "none", ""
        hashes = [entry_hash(e) for e in entries]
        if list(known[:len(hashes)]) != hashes:
            replay(entries)                      # not what was just replayed: verify it from its own genesis
    except Invalid as err:
        return "invalid", f"INVALID — the canonical ledger does not verify: {err}"
    now = now or now_utc()
    if future_head(ts(entries[-1]["time"]), now):
        return "future", (f"FUTURE HEAD — entry {len(entries) - 1} of the canonical ledger is dated {entries[-1]['time']}, "
                          f"ahead of this clock ({iso(now)}): notice periods rest on honest timestamps, so nothing is "
                          "drafted or signed on it")
    if accept is not None and accept != hashes[0]:
        raise UserError(f"--accept-genesis names {accept}, but the canonical ledger starts from the genesis {hashes[0]}")
    store = _read_json(HEADS)
    verdict, seq, h = head_verdict(store, hashes, known)
    if verdict in ("first", "ok") or accept is not None:
        new = remember_head(store, hashes)
        if new != store:
            _write_private(HEADS, new)
        return "ok", ""
    how = f"if you mean to follow this history, accept it once: {OM} verify --accept-genesis {hashes[0]}"
    if verdict == "rollback":
        return "rollback", (f"ROLLBACK — the canonical ledger no longer contains entry {seq} (hash {h}) that this clone "
                            f"verified earlier. Nothing is drafted, approved or signed. Raise the alarm ({OM} alarm); "
                            + how + " (a fork)")
    if verdict == "behind":
        return "canonical_behind", (f"BEHIND — the canonical ledger this clone fetched has {len(hashes)} entries, and this "
                                    f"clone verified entry {seq} (hash {h}) earlier: the same history, shorter (a mirror "
                                    "that lags). Nothing is drafted or signed on it until it holds that entry again")
    return "genesis", (f"DIFFERENT GENESIS — the canonical ledger starts from the genesis {hashes[0]}, and this clone has "
                       "verified another fraternity before, never this one; " + how)


def _require_canonical(st: State | None, ledger: Path) -> None:
    """Refuse to draft, approve or sign on a canonical ledger that was rewound, lags behind what this clone
    verified, starts from another genesis, is dated ahead of the clock or does not verify. Only for the
    repository's own ledger: a scratch ledger has no canonical one."""
    if not is_repo_ledger(ledger):
        return
    verdict, msg = canonical_guard(st.hashes if st is not None else ())
    if verdict in BLOCKING:
        raise UserError(msg)
    # After `verify --accept-genesis`, or on a clone of a fork, the working copy may follow another history than
    # the canonical ledger it accepted: nothing is drafted on it.
    try:
        entries = canonical_ledger() or []
    except Invalid:
        return
    mine = st.hashes if st is not None else []
    theirs = [entry_hash(e) for e in entries]
    n = min(len(mine), len(theirs))
    if theirs and mine[:n] != theirs[:n]:
        at = next(i for i in range(n) if mine[i] != theirs[i]) if mine[:n] != theirs[:n] else n
        remote = canonical_remote() or "upstream"
        raise UserError(f"this clone's ledger/entries follows another history than the canonical ledger (entry {at} "
                        f"differs): nothing is drafted on it. Bring the working copy to the canonical ledger first: "
                        f"git switch main && git reset --keep {remote}/main (the person decides; it keeps no commit "
                        "of the other history)")


def verify_client(a, report: dict) -> dict:
    """What `om verify` adds to the pinned verifier's report when the ledger is this repository's and it
    verifies: the head must not be dated ahead of this clock, and the canonical ledger must still hold the
    head this clone verified earlier (SPEC §9.7). The report keeps its schema (om.verify/1)."""
    if not report.get("valid") or not is_repo_ledger(a.ledger):
        return report
    entries = load(a.ledger)
    now = now_utc()
    if entries and future_head(ts(entries[-1]["time"]), now):
        msg = (f"entry {len(entries) - 1} is dated {entries[-1]['time']}, ahead of this clock ({iso(now)})")
        return report | {"valid": False, "message": "FUTURE HEAD — " + msg, "problems": [msg]}
    verdict, msg = canonical_guard([entry_hash(e) for e in entries], accept=getattr(a, "accept_genesis", None), now=now)
    if verdict == "canonical_behind":
        return report | {"message": report["message"] + "\n" + msg}
    if verdict in BLOCKING:
        return report | {"valid": False, "message": msg, "problems": [msg]}
    return report


def ledger_relation(local: dict[str, str], canonical: dict[str, str]) -> tuple[str, int]:
    """Compare two ledgers given as {path inside the entries directory: git blob id}. Pure.

    Returns ("in_sync" | "behind" | "ahead" | "diverged", n): n is how many entries
    behind/ahead, or the first diverging seq. Paths that are not those of entries are left out.
    """
    local = {entry_seq(k): v for k, v in local.items() if entry_seq(k) is not None}
    canonical = {entry_seq(k): v for k, v in canonical.items() if entry_seq(k) is not None}
    for seq in sorted(set(local) & set(canonical)):
        if local[seq] != canonical[seq]:
            return "diverged", seq
    extra_local = sorted(set(local) - set(canonical))
    extra_canon = sorted(set(canonical) - set(local))
    if extra_local and extra_canon:
        return "diverged", min(extra_local + extra_canon)
    if extra_canon:
        return "behind", len(extra_canon)
    if extra_local:
        return "ahead", len(extra_local)
    return "in_sync", 0


def _ledger_blobs(ref: str) -> dict[str, str]:
    return {name: oid for name, (_, oid) in _tree_files(_git("ls-tree", "-r", ref, ENTRIES_DIR + "/").stdout).items()}


def canonical_status(known=()) -> tuple[str, str]:
    """(status, human message) of this clone's ledger against the canonical repository. `known` are the entry
    hashes of the ledger the caller has just replayed: the canonical ledger is first held against the head
    this clone verified earlier (`canonical_guard`), also when the repository cannot be reached."""
    remote = canonical_remote()
    if remote is None:
        return "no_remote", (f"no git remote points to {canon.CANONICAL_REPO}: "
                             f"git remote add upstream https://github.com/{canon.CANONICAL_REPO}.git")
    reached = _git("fetch", "--quiet", remote).returncode == 0
    verdict, msg = canonical_guard(known)
    if verdict in BLOCKING:
        return verdict, msg
    if not reached:
        return "offline", f"could not reach {canon.CANONICAL_REPO}"
    rel, n = ledger_relation(_ledger_blobs("HEAD"), _ledger_blobs(f"refs/remotes/{remote}/main"))
    return rel, {"in_sync": f"ledger in sync with {canon.CANONICAL_REPO}",
                 "behind": f"your clone is {n} entr{'y' if n == 1 else 'ies'} behind {canon.CANONICAL_REPO}: git pull {remote} main",
                 "ahead": f"your clone has {n} committed entr{'y' if n == 1 else 'ies'} not in {canon.CANONICAL_REPO} yet "
                          "(an open pull request, or a separate fork)",
                 "diverged": f"your ledger DIVERGES from {canon.CANONICAL_REPO} at entry {n}: this clone follows a different "
                             f"fraternity (a fork). Rejoin with: git fetch {remote} && git reset --hard {remote}/main"}[rel]


def _require_in_sync(known=()) -> str:
    """Refuse to publish from a stale or diverged clone, or into a canonical ledger that was rewound; return
    the canonical remote name."""
    if _git("diff", "--cached", "--quiet").returncode != 0:
        raise UserError("you have staged changes; commit or unstage them before publishing an entry")
    status, msg = canonical_status(known)
    if status == "ahead":
        raise UserError(msg + "; publish only from a clone whose ledger matches the canonical one")
    if status in BLOCKING:
        raise UserError(msg)
    if status in ("no_remote", "offline", "behind", "diverged"):
        raise UserError(msg + ("; then draft again" if status == "behind" else ""))
    return canonical_remote() or "origin"


def _gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], cwd=canon.ROOT, capture_output=True, text=True)


def fork_parent(slug: str) -> str | None:
    """The repository `slug` is a fork of (`owner/name`, lower case), or None (not a fork, or not found)."""
    r = _gh("api", f"repos/{slug}", "--jq", ".parent.full_name // empty")
    return r.stdout.strip().lower() or None if r.returncode == 0 else None


def find_fork(login: str) -> str | None:
    """The fork of the canonical repository that `login` owns, whatever its name (`openmasonry-1` when the
    account already had a repository called `openmasonry`): read from the canonical repository's forks."""
    r = _gh("api", "--paginate", f"repos/{canon.CANONICAL_REPO}/forks?per_page=100", "--jq",
            f'.[] | select((.owner.login | ascii_downcase) == "{login.casefold()}") | .full_name')
    names = r.stdout.split() if r.returncode == 0 else []
    return names[0].lower() if names else None


def _push_target(canon_remote: str, login: str, seq: object = "SEQ") -> tuple[str, str]:
    """(remote to push to, head owner). Members with write access push to the canonical repository; everyone
    else pushes to their own fork, created on first use. The fork is found through the canonical repository's
    forks (its name may differ), and nothing is ever pushed to a repository that is not a fork of the canonical
    one: a remote is used only when GitHub says its repository's parent is the canonical repository, and only when
    it also pushes there (`_own_push_url`). `seq` is the entry's, for the command that publishes it again."""
    perm = _gh("api", f"repos/{canon.CANONICAL_REPO}", "--jq", ".permissions.push")
    if perm.returncode == 0 and perm.stdout.strip() == "true":
        return canon_remote, canon.CANONICAL_REPO.split("/")[0]
    canonical = canon.CANONICAL_REPO.lower()
    remotes = {}
    for line in _git("remote", "-v").stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and remote_slug(parts[1]):
            remotes.setdefault(parts[0], remote_slug(parts[1]))
    for name, slug in remotes.items():          # a remote of one's own fork, whatever its name
        if slug.split("/")[0] == login.casefold() and slug != canonical and fork_parent(slug) == canonical:
            _own_push_url(name, slug, seq)
            return name, login
    fork = find_fork(login)
    if fork is None:
        r = _gh("repo", "fork", canon.CANONICAL_REPO, "--clone=false")
        if r.returncode != 0 and "already exists" not in (r.stderr + r.stdout):
            raise UserError(f"could not create your fork of {canon.CANONICAL_REPO}: {(r.stderr or r.stdout).strip()[:200]}")
        for _ in range(6):                        # GitHub creates forks asynchronously
            fork = find_fork(login)
            if fork:
                break
            import time
            time.sleep(5)
    if fork is None or fork_parent(fork) != canonical:
        raise UserError(f"could not find your fork of {canon.CANONICAL_REPO} on GitHub (it may still be being created): "
                        f"wait a minute, then publish again with {OM} pending --publish {seq}")
    name = "fork" if "fork" not in remotes else next(f"fork-{i}" for i in range(2, 99) if f"fork-{i}" not in remotes)
    if remotes.get("fork") == fork:
        name = "fork"
        _own_push_url(name, fork, seq)
    elif _git("remote", "add", name, f"https://github.com/{fork}.git").returncode != 0:
        raise UserError(f"could not add the git remote {name} for your fork {fork}")
    return name, login


def _push_url(remote: str) -> str:
    """Where a push to `remote` goes: its push URL (remote.NAME.pushurl, else its URL), with insteadOf and
    pushInsteadOf applied. The remote's name when git cannot say."""
    r = _git("remote", "get-url", "--push", remote)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else remote


def _own_push_url(name: str, slug: str, seq: object) -> None:
    """A remote that fetches from the person's own fork must push to that fork too: `_push` forces the fork's
    branch, and a push URL to the canonical repository or to another account's fork would force it there. (A push
    URL git names in a form this cannot read, such as an SSH host alias, is the person's own setting.)"""
    push = remote_slug(_push_url(name))
    if push is not None and (push == canon.CANONICAL_REPO.lower() or push.split("/")[0] != slug.split("/")[0]):
        raise UserError(f"the git remote {name} fetches from your fork {slug} but pushes to {push}: "
                        f"nothing was pushed. Make it push to your fork (git remote set-url --push {name} "
                        f"https://github.com/{slug}.git, or remove the pushurl or pushInsteadOf that sends it "
                        f"elsewhere), then {OM} pending --publish {seq}")


PR_BODY = ("Signed entry submitted with `om approve`. The judge checks it; it merges itself when the judge passes "
           "(only the `judge` check is required).")


def entry_branch(entry: dict) -> str:
    return f"om/{entry['actor'].casefold()}/{entry['seq']:06d}"


def _branch_holds(branch: str, base: str, rel: list[str]) -> bool:
    """The local branch is one commit's worth of exactly these files over `base`, with the bytes they have now."""
    if _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode != 0:
        return False
    changed = sorted(_git("diff", "--name-only", f"{base}...refs/heads/{branch}").stdout.split())
    if changed != sorted(rel):
        return False
    for r in rel:
        shown = subprocess.run(["git", "-C", str(canon.ROOT), "show", f"refs/heads/{branch}:{r}"], capture_output=True)
        here = canon.ROOT / r
        if shown.returncode != 0 or (here.exists() and here.read_bytes() != shown.stdout):
            return False
    return True


def _publish_login(entry: dict, login: str | None) -> str:
    """The GitHub account that publishes: the active gh account (a renamed account petitions under its old login,
    and a custodian is no account), else the entry's actor."""
    return login or detect_login(None) or entry["actor"]


def _push(remote: str, branch: str, canon_remote: str, login: str | None = None) -> subprocess.CompletedProcess:
    """Push an entry's branch and set its upstream. To the person's own fork the push replaces what an earlier attempt
    at the same seq left there (an entry dropped and drafted again takes the same branch name), with a lease on what
    the fork holds now, read just before: it never overwrites a push made in between. To the canonical repository
    (the remote, or any remote whose push URL reaches it) it never forces: when git rejects the push because the
    branch there holds an earlier attempt, that branch is deleted under a lease if it is `login`'s own and no open
    pull request uses it (`_drop_own_branch`), and the push is made again."""
    url = _push_url(remote)
    if remote == canon_remote or remote_slug(url) == canon.CANONICAL_REPO.lower():
        r = _git("push", "-u", remote, branch)
        if r.returncode != 0 and _behind(r) and _drop_own_branch(remote, branch, login):
            r = _git("push", "-u", remote, branch)
        return r
    seen = _git("ls-remote", url, f"refs/heads/{branch}")                 # where the push goes, not where fetch reads
    if seen.returncode != 0:
        return seen
    held = seen.stdout.split()[0] if seen.stdout.split() else ""          # empty: the branch must not exist there
    return _git("push", f"--force-with-lease=refs/heads/{branch}:{held}", "-u", remote, branch)


def _behind(r: subprocess.CompletedProcess) -> bool:
    """git refused the push because the remote branch holds commits this one lacks (not a hook, not access)."""
    return "[rejected]" in r.stderr and ("non-fast-forward" in r.stderr or "fetch first" in r.stderr)


def _drop_own_branch(remote: str, branch: str, login: str | None) -> bool:
    """Delete the branch om/LOGIN/SEQ that an entry dropped and drafted again at the same seq left on `remote` (the
    canonical repository, for a member with write access), so that the new entry can take its name. Only `login`'s
    own branch, only when GitHub answers that no open pull request has it as its head, and under a lease on what the
    remote holds just before: a push made in between is kept. Whether it was deleted."""
    if not login or not branch.startswith(f"om/{login.casefold()}/"):
        return False                                # never another login's branch
    url = _push_url(remote)
    seen = _git("ls-remote", url, f"refs/heads/{branch}")
    held = seen.stdout.split()[0] if seen.returncode == 0 and seen.stdout.split() else ""
    if not held:
        return False
    try:
        r = _gh("pr", "list", "--repo", canon.CANONICAL_REPO, "--state", "open", "--search", f"head:{branch}",
                "--json", "headRefName")
        prs = json.loads(r.stdout.strip() or "[]") if r.returncode == 0 else None
    except (OSError, ValueError):
        prs = None
    if not isinstance(prs, list) or any(not isinstance(pr, dict) or pr.get("headRefName", branch) == branch for pr in prs):
        return False                                # an open pull request uses it, or GitHub could not be asked
    return _git("push", f"--force-with-lease=refs/heads/{branch}:{held}", remote, f":refs/heads/{branch}").returncode == 0


def _failed(what: str, r: subprocess.CompletedProcess, then: str = "") -> str:
    """`WHAT failed: …` with git's or gh's own message cut short, never what follows it (what to do next)."""
    return f"{what} failed: {clean((r.stderr or r.stdout).strip(), 300)}{then}"


def _kept(branch: str, seq: object) -> str:
    return f" (the signed entry is kept on the branch {branch}: fix the cause, then {OM} pending --publish {seq})"


def _open_pr(entry: dict, branch: str, head_owner: str) -> tuple[int, str | None]:
    r = _gh("pr", "create", "--repo", canon.CANONICAL_REPO, "--base", "main", "--head", f"{head_owner}:{branch}",
            "--title", f"ledger: {entry['type']} #{entry['seq']} by {entry['actor']}",
            "--body", f"{PR_BODY}\n\n{entry_tag(entry)}")
    url = r.stdout.strip() if r.returncode == 0 else None
    if url is None and "already exists" in (r.stderr + r.stdout):   # an open one from this branch now shows this entry
        url = (entry_pr(entry, "open")[1] or {}).get("url")
    if url is None:
        print(f"✘ could not open the pull request: {clean(r.stderr.strip(), 300)} (branch {branch} is pushed; open it "
              f"with {OM} pending --publish {entry['seq']})")
    return (0 if url else 1), url


def _submit(paths: list[Path], entry: dict, canon_remote: str = "origin", login: str | None = None,
            st: State | None = None, checked: bool = False) -> tuple[int, str | None]:
    """Commit only these files on a branch from the canonical main, push it, open the PR. Returns (code, PR URL).
    `login` is the GitHub account that publishes (default: the active gh account). A branch left by an earlier
    attempt at the same entry is reused when it holds exactly these files, and replaced otherwise; a failure
    leaves it for `om pending --publish SEQ`. The commit is made as the account gh reports (`commit_env`); for an
    entry of `commit_checked` (or when `checked`), the branch's commit is read back before the push, and a branch
    that carries another identity or time zone is deleted, unpushed."""
    rel = [str(p.resolve().relative_to(canon.ROOT.resolve())) for p in paths]
    branch = entry_branch(entry)
    base = f"refs/remotes/{canon_remote}/main"
    start = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if start == "HEAD":                                  # detached: come back to the exact commit
        start = _git("rev-parse", "HEAD").stdout.strip()
    back = lambda: _git("switch", "--detach" if len(start) == 40 else start, *([start] if len(start) == 40 else []))
    login = _publish_login(entry, login)
    holds = _branch_holds(branch, base, rel)
    checked = checked or commit_checked(st, entry)
    try:
        user = commit_account() if checked or not holds else None
    except UserError as err:
        raise UserError(f"{err}; nothing was committed") from None
    push_remote, head_owner = _push_target(canon_remote, login, entry["seq"])
    steps = [("push", push_remote, branch)]
    if not holds:
        if _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
            _git("branch", "-D", branch)                 # an earlier attempt at this seq with other content
        steps = [("switch", "--no-track", "-c", branch, base), ("add", "--", *rel),   # no upstream until pushed
                 ("commit", "-m", f"ledger: {entry['type']} #{entry['seq']} by {entry['actor']}", "--", *rel), *steps]
    for step in steps:
        if step[0] == "push" and checked and (found := commit_mismatch(f"refs/heads/{branch}", user)):
            back()
            _git("branch", "-D", branch)
            raise UserError(f"NOT PUBLISHED — the commit of this entry carries {found}, not "
                            f"{'{} <{}>'.format(*noreply(user))} in UTC: nothing was pushed, and the branch {branch} "
                            "was deleted")
        r = (_push(step[1], step[2], canon_remote, login) if step[0] == "push" else
             _git(*step, env=commit_env(user)) if step[0] == "commit" else _git(*step))
        if r.returncode != 0:
            back()
            raise UserError(_failed(f"git {step[0]}", r, _kept(branch, entry["seq"]) if step[0] != "switch" else ""))
    code, url = _open_pr(entry, branch, head_owner)
    back()
    return code, url


def _publish_kept(paths: list[Path], entry: dict, canon_remote: str, login: str | None,
                  st: State | None) -> tuple[int, str | None]:
    """`_submit` for a signed entry the outbox keeps. When publishing fails before the entry's branch exists (the
    fork is not found, cannot be made, or the branch cannot be made), the entry file is taken back out of the
    working tree, as a successful publish leaves it: the outbox keeps it, `om pending` lists it, and
    `om pending --publish SEQ` publishes it. Left there, the clone would replay it as if it were in the ledger.
    The public reason of a correction goes the same way: into the outbox beside its entry, out of ledger/reasons/."""
    try:
        return _submit(paths, entry, canon_remote, login, st)
    except UserError as err:
        if _git("rev-parse", "--verify", "--quiet", f"refs/heads/{entry_branch(entry)}").returncode == 0:
            raise
        reasons = [p for p in paths[1:] if entry.get("type") == "correction" and p.parent.name == Path(REASONS_DIR).name]
        for p in [paths[0], *reasons]:             # never the degree canon a genesis archives
            rel = str(p.resolve().relative_to(canon.ROOT.resolve()))
            if not p.exists() or _git("ls-files", "--error-unmatch", "--", rel).returncode == 0:
                continue                           # never a tracked file
            if p in reasons:
                kept = _outbox_reason(st, entry)
                _private_dir(kept.parent)
                with os.fdopen(os.open(kept, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
                    f.write(p.read_bytes())
            p.unlink()
        msg = str(err)
        if "pending --publish" not in msg:
            msg += f" (the signed entry is kept: fix the cause, then {OM} pending --publish {entry['seq']})"
        raise UserError(msg) from None


def _drop_canonical_branch(entry: dict) -> str | None:
    """`om pending --drop SEQ`, for a member with write access: the entry's own branch on the canonical repository,
    deleted when no open pull request uses it (`_drop_own_branch`), so that the act drafted again at the same seq
    can be published. The branch's name when it was deleted, else None (nothing there, another login's, or still
    the head of an open pull request: once that is closed, publishing deletes it then)."""
    remote = canonical_remote()
    branch = entry_branch(entry)
    if remote is None or not _drop_own_branch(remote, branch, _publish_login(entry, None)):
        return None
    return branch


def publish_pending(a, st: State | None, entry: dict) -> int:
    """`om pending --publish SEQ`: publish a signed entry of one's own whose push or pull request failed. The branch
    of the first attempt is pushed again (or the entry file is written back from the outbox), and the pull
    request is opened unless it exists. Asks the person first, like `om submit`."""
    if not is_repo_ledger(a.ledger):
        raise UserError("only the repository's own ledger is published")
    if now_utc() - ts(entry["time"]) > CLOCK_TOLERANCE - CLOCK_TOLERANCE / 12:
        raise UserError(f"entry #{entry['seq']} is too old for the judge now: forget it ({OM} pending --drop "
                        f"{entry['seq']}) and draft the act again")
    branch = entry_branch(entry)
    found = entry_pr(entry, "open")[1]
    if found:
        return _out(a, {"schema": "om.submitted/1", "pr": found["url"]},
                    f"its pull request is open already: {found['url']}", 0)
    account_guard(st, entry, "Nothing was published")
    canon_remote = _require_in_sync(st.hashes if st else ())
    if _ask("OpenMasonry: publish this signed entry?", describe(st, entry), ["Publish"], a.ledger) is None:
        return _out(a, {"canceled": True}, "Canceled.", 1)
    rel = entry_path(DEFAULT_LEDGER, entry["seq"])
    if _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        if commit_checked(st, entry) and (found := commit_mismatch(f"refs/heads/{branch}", user := commit_account())):
            raise UserError(f"NOT PUBLISHED — the commit on the branch {branch} carries {found}, not "
                            f"{'{} <{}>'.format(*noreply(user))} in UTC: nothing was pushed. Delete the branch "
                            f"(git branch -D {branch}), then {OM} pending --publish {entry['seq']} commits it again")
        login = _publish_login(entry, None)
        push_remote, head_owner = _push_target(canon_remote, login, entry["seq"])
        r = _push(push_remote, branch, canon_remote, login)
        if r.returncode != 0:
            raise UserError(_failed("git push", r, _kept(branch, entry["seq"])))
        code, url = _open_pr(entry, branch, head_owner)
        return _out(a, {"schema": "om.submitted/1", "pr": url}, url or "", code)
    paths = [rel]
    if entry["type"] == "correction":             # its public reason travels with it, from where approval wrote it
        reason = reasons_dir(DEFAULT_LEDGER) / f"{entry['body'].get('reason_sha256')}.md"
        kept = _outbox_reason(st, entry)          # …or from the outbox, where a failed publish put it
        if not reason.exists() and kept.exists() and sha256(kept.read_bytes()) == entry["body"].get("reason_sha256"):
            reason.parent.mkdir(parents=True, exist_ok=True)
            reason.write_bytes(kept.read_bytes())
        if not reason.exists() or sha256(reason.read_bytes()) != entry["body"].get("reason_sha256"):
            raise UserError(f"the branch {branch} is gone and the public reason of correction #{entry['seq']} travels "
                            f"with it: forget it ({OM} pending --drop {entry['seq']}) and draft it again")
        paths.append(reason)
    rel.parent.mkdir(parents=True, exist_ok=True)
    if not rel.exists():
        rel.write_text(entry_text(entry), encoding="utf-8")
    code, url = _publish_kept(paths, entry, canon_remote, None, st)
    if url:
        _outbox_reason(st, entry).unlink(missing_ok=True)
    return _out(a, {"schema": "om.submitted/1", "pr": url}, url or "", code)


def cmd_submit(a) -> int:
    """Publish signed entries that were approved with --no-submit (asks again)."""
    if not is_repo_ledger(a.ledger):
        raise UserError("submit only publishes the repository's own ledger/entries")
    found = _git("ls-files", "--others", "--exclude-standard", ENTRIES_DIR).stdout.split()
    new = sorted((n for n in found if entry_seq(n.removeprefix(ENTRIES_DIR + "/")) is not None),
                 key=lambda n: entry_seq(n.removeprefix(ENTRIES_DIR + "/")))
    if not new:
        print("No new ledger entries to submit.")
        return 0
    entries = [json.loads((canon.ROOT / n).read_text()) for n in new]
    st = state_of(a.ledger)
    for e in entries:
        account_guard(st, e, "Nothing was published")
    canon_remote = _require_in_sync(st.hashes if st else ())
    text = "\n\n".join(describe(st, e) for e in entries)
    if _ask("OpenMasonry: publish these signed entries?", text, ["Publish"], a.ledger) is None:
        return _out(a, {"canceled": True}, "Canceled.", 1)
    for e in entries:                              # `om pending` lists them until they merge
        _keep_in_outbox(st, e)
    # The public reason of a correction goes in the same pull request as the entry that pins it.
    cited = {f"{REASONS_DIR}/{e['body'].get('reason_sha256')}.md" for e in entries
             if e.get("type") == "correction" and isinstance(e.get("body"), dict)}
    reasons = [n for n in _git("ls-files", "--others", "--exclude-standard", REASONS_DIR).stdout.split() if n in cited]
    code, url = _submit([canon.ROOT / n for n in (*new, *reasons)], entries[-1], canon_remote, st=st,
                        checked=any(commit_checked(st, e) for e in entries))
    return _out(a, {"schema": "om.submitted/1", "pr": url}, url or "", code)


# ----------------------------------------------------------------- reading --

def cmd_doctor(a) -> int:
    ok = True

    def check(cond: bool, good: str, bad: str):
        nonlocal ok
        print(("✔ " + good) if cond else ("✘ " + bad))
        ok &= cond

    from . import onboard
    check(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "Python ≥ 3.11 is required (install it from your package manager or python.org)")
    check(shutil.which("gh") is not None, "GitHub CLI found", "install gh (https://cli.github.com) and run `gh auth login`")
    login = detect_login(a.login)
    check(login is not None, f"GitHub login: {login}", "no GitHub login (gh auth login, or --login)")
    for c in onboard.doctor_checks(login):        # OpenSSH and -Y, git and its identity and credentials, the clock
        how = (c["fix"] or {}).get("argv") or []
        line = c["message"] + (f": {cmdline(how)}" if how else f" ({c['fix']['text']})" if c["fix"] else "")
        if c["status"] in ("ok", "fail"):
            check(c["status"] == "ok", c["message"], line)
        else:
            print("· " + line)
    k = key_path(a.key)
    pub = k.with_name(k.name + ".pub")
    check(pub.exists(), f"public key {pub}", f"public key {pub} not found: {cmdline(['ssh-keygen', '-y', '-f', str(k)])} > "
          f"{cmdline([str(pub)])}" if k.exists()
          else f"no key at {k}: {OM} onboard --create-key (or --use-key PATH)")
    if pub.exists():
        bare = bare_public_key(k)
        check(key_kind(bare) is not None, str(key_kind(bare)), KEY_RULE)
        url = f"https://github.com/{login}.keys"
        if key_kind(bare) is None:                # a key the ledger refuses: whether GitHub lists it is moot
            pass
        elif login and shutil.which("curl") is None:
            print(f"· curl not found: the key listing was not checked (open {url} in a browser)")
        elif login:
            r = subprocess.run(["curl", "-fsS", "--max-time", "10", url], capture_output=True, text=True)
            if r.returncode != 0:                 # offline, throttled or no such account: say so, never "add it"
                print(f"· could not read {url} ({(r.stderr or 'no answer').strip()[:80]}): the key listing was not checked")
            else:
                check(bare.split()[1] in r.stdout, f"key listed at github.com/{login}.keys",
                      f"the key is not listed at {url}: {OM} onboard --upload (asks you first)")
        held, silent = onboard.agent_listing()
        if silent:
            check(False, "", f"{onboard.AGENT_SILENT} ({onboard.AGENT_FIX})")
        elif not shutil.which("ssh-add"):
            print("· ssh-add not found: the ssh-agent was not checked")
        else:
            held = held or ""
            print(("✔ key loaded in ssh-agent" if bare.split()[1] in held else
                   f"· key not in ssh-agent: signing will ask for its passphrase (or: {cmdline(['ssh-add', str(k)])}"
                   + ("; the OpenSSH Authentication Agent service must be running: Start-Service ssh-agent"
                      if sys.platform == "win32" else "") + ")"))
        if bare.startswith("sk-"):
            print("· hardware-backed key: every signature asks for a touch of the token")
    known = ()
    try:
        st = state_of(a.ledger)
        check(True, "ledger verifies", "")
        known = st.hashes if st is not None else ()
        if st is not None and is_repo_ledger(a.ledger) and future_head(st.time, now_utc()):
            check(False, "", f"FUTURE HEAD — entry {st.seq} is dated {iso(st.time)}, ahead of this clock: raise the alarm "
                             f"({OM} alarm) unless this machine's clock is wrong")
        if st is not None and login and pub.exists():
            for e in pending_own(st, a.ledger):       # a rekey of yours still waiting for its PR counts here
                try:
                    trial = copy.deepcopy(st)
                    apply(trial, e)
                    st = trial
                except Invalid:
                    break
            advice = key_advice(st, canonical_login(st, login), bare_public_key(k))
            if advice:
                check(False, "", advice)
    except Invalid as err:
        check(False, "", f"ledger INVALID: {err}")
    if is_repo_ledger(a.ledger) and shutil.which("git") is None:
        print("· git is not installed: the canonical ledger was not compared")
    elif is_repo_ledger(a.ledger):
        status, msg = canonical_status(known)
        if status == "offline":
            print("· " + msg)
        else:
            check(status in ("in_sync", "ahead"), msg, msg)
    return 0 if ok else 1


def me_report(st: State, login: str, now: datetime, waiting: list[dict] = (), stale: list[dict] = (),
              custodian: str | None = None, onboarding: dict | None = None, asked: bool = False,
              unpublished: list[dict] = ()) -> dict:
    """What `om me` shows, as data (schema om.me/2). `onboarding` is what `onboard.onboarding_info` found for a
    person who is not a member (their key, whether GitHub lists it, their application): it turns the `apply`
    and `join` steps into `bin/om apply` and `bin/om onboard` steps (`guide.onboarding_steps`). Degrades instead of crashing when this clone lacks
    the text of the ratified degree canon (canon/history/<sha256>.toml). `notices` are what exists and
    concerns the person (never steps); `custodian` names the custodian key the person says they hold, and
    adds its two possible steps. `unpublished` are the signed entries of `waiting` that never reached GitHub:
    publishing them is then the only step, as nothing else can be drafted before they merge."""
    from .guide import Step
    m = st.members.get(login)
    pending = st.canon_pending()
    keeper = None
    if custodian:                                 # the person also holds a custodian key: its duties, nothing more
        c = st.custodians.get(custodian)
        keeper = {"name": custodian, "member": c.member if c else None,
                  "status": st.custodian_status(c, now) if c else "unknown",
                  "last_alive": iso(c.alive) if c else None,
                  "silence_deadline": iso(c.alive + CUSTODIAN_SILENCE_DAYS * DAY) if c else None}
    try:
        steps = next_steps(st, login, now)
    except CanonPending as err:
        pending = err.digest
        steps = [Step("wait", f"The ratified degree canon {err.digest[:12]}… is not in this clone yet "
                      f"(canon/history/{err.digest}.toml); update your clone (git pull) and ask again.")]
    if onboarding is not None:
        from .guide import onboarding_steps
        steps = onboarding_steps(steps, onboarding, login, asked)
    if unpublished:
        steps = [Step("publish", f"Your {e['type']} #{e['seq']} is signed but not published yet: publishing it opens "
                      "its pull request (it asks you first). Nothing else can be drafted until it merges.",
                      [OM, "pending", "--publish", str(e["seq"])], public=True) for e in unpublished]
    petition = next((e for e in waiting if e not in unpublished and e.get("type") == "petition"
                     and str(e.get("actor", "")).casefold() == login.casefold()), None)
    if petition is not None:                      # its pull request is open: the sponsors act once it merges
        steps = [Step("wait", f"Your petition #{petition['seq']} waits for its pull request to merge ({OM} pending "
                      "shows its state). Once it merges: " + s.why.replace(" can now open ", " can open "),
                      [OM, "pending"], due_by=s.due_by) if s.why.startswith("Your petition has ") else s for s in steps]
    title = None
    if m is not None:
        try:
            title = st.degree(m.degree).title
        except CanonPending as err:
            pending = err.digest
    member = None if m is None else {
        "degree": m.degree, "title": title,
        "status": "active" if m.is_active(now) else m.status,
        "founding_architect": m.founder, "light": round(m.light(now), 2), "github_id": m.github_id,
        "dormant": m.dormant(now), "last_activity": iso(m.last_active())}
    from .guide import sponsorship_budget
    budget = sponsorship_budget(st, login, now) if m is not None and st.stands_in(login, now) else None
    inv = st.invitations[login] if st.invited(login, now) else None
    invitation = None if inv is None else {"by": inv["by"], "github_id": inv["github_id"],
                                           "expires_at": iso(st.due(inv["time"], INVITE_EXPIRY_DAYS * DAY))}
    return {"schema": "om.me/2", "login": login, "member": member, "invitation": invitation,
            "founding_phase": st.founding_phase(now), "canon_pending": pending,
            "pending_prs": [{"seq": e["seq"], "type": e["type"], "published": e not in unpublished} for e in waiting],
            "stale": [{"seq": e["seq"], "type": e["type"]} for e in stale],
            "notices": [n.to_dict() for n in notices(st, login, now)], "custodian": keeper, "sponsorship": budget,
            "onboarding": onboarding,
            "steps": [s.to_dict() for s in (*steps, *(custodian_steps(st, custodian, now) if custodian else ()))]}


def outsider(st: State, login: str, now: datetime) -> bool:
    """Not a member (or no longer one), with no live petition and no open admission ballot: the door's steps."""
    m = st.members.get(login)
    return ((m is None or m.status in ("departed", "expelled", "voided")) and not st.live(login, now)
            and st.open_ballot_on("admission", login.casefold()) is None)


LAUNCH_HINT = "Founding it is the founder's act: see docs/operations/LAUNCH.md (bin/om genesis)."


def cmd_me(a) -> int:
    st = state_of(a.ledger)
    login = canonical_login(st, need_login(a))
    now = ts(a.time) if a.time else now_utc()
    if st is None:                                # before genesis: a founder's signed genesis may wait for its PR
        from .guide import Step
        repo = is_repo_ledger(a.ledger)
        waiting, launch, steps = outbox(None, a.ledger)[0], LAUNCH_HINT, []
        shown = []
        for e in waiting:
            asked, pr = entry_pr(e) if repo else (False, None)
            shown.append((e, live_pr(pr) if asked else pushed(e)))
            if shown[-1][1]:
                url = (pr or {}).get("url")
                launch = (f"The ledger is empty: your signed genesis is waiting for its pull request to merge"
                          f"{': ' + url if url else ''} ({OM} pending). Once it merges: git pull, then {OM} me.")
            else:
                launch = (f"The ledger is empty: your signed genesis is not published yet: {OM} pending --publish "
                          f"{e['seq']} (it asks you first).")
                steps.append(Step("publish", "Your genesis is signed but not published yet: publishing it opens its "
                                  "pull request (it asks you first).", [OM, "pending", "--publish", str(e["seq"])],
                                  public=True).to_dict())
        print(json.dumps({"schema": "om.me/2", "login": login, "member": None, "invitation": None, "founding_phase": None,
                          "canon_pending": None, "stale": [], "notices": [], "custodian": None,
                          "pending_prs": [{"seq": e["seq"], "type": e["type"], "published": d} for e, d in shown],
                          "steps": steps, "before_genesis": True, "launch": launch}) if a.json else
              launch if waiting else f"The ledger is empty: the fraternity has not been founded yet.\n{LAUNCH_HINT}")
        return 0
    # The canonical ledger against the head this clone verified earlier (SPEC §9.7): git only, no network.
    guard = canonical_guard(st.hashes) if is_repo_ledger(a.ledger) else ("none", "")
    waiting, stale = outbox(st, a.ledger)
    unpublished = [e for e in waiting if not published(e, github=is_repo_ledger(a.ledger))]
    if len(unpublished) < len(waiting):           # own signed entries whose PR is open count as done here
        st = copy.deepcopy(st)
        for e in (x for x in waiting if x not in unpublished):
            try:
                apply(st, e)
            except Invalid:
                break
    keeper = custodian_name(a)
    door = None
    if outsider(st, login, now):                  # not a member: their key and application, outside the ledger
        from .onboard import onboarding_info
        door = onboarding_info(a, st, login, now)
    rep = me_report(st, login, now, waiting, stale, custodian=canonical_login(st, keeper) if keeper else None,
                    onboarding=door, asked=is_repo_ledger(a.ledger), unpublished=unpublished)
    blocked = guard[0] in BLOCKING
    if blocked:                                   # nothing can be drafted, approved or signed: the message is all
        from .guide import Step
        rep["canonical"] = {"verdict": guard[0], "message": guard[1]}
        rep["steps"] = [Step("wait", guard[1]).to_dict()]
        if not a.json:
            print(guard[1])
    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0
    member = rep["member"]
    print(f"{login} — " + (f"{member['degree']}° {member['title'] or '(canon text pending)'}"
                           f"{' · Founding Architect' if member['founding_architect'] else ''} · {member['status']}"
                           f"{' (dormant)' if member['dormant'] else ''}"
                           f" · Light {member['light']}" if member else "not a member")
          + (f" · invited by {rep['invitation']['by']} until {rep['invitation']['expires_at']}" if rep["invitation"] else "")
          + (" · Founding Phase" if rep["founding_phase"] else ""))
    for e in waiting:
        print(f" · your {e['type']} #{e['seq']} is signed but not published yet: {OM} pending --publish {e['seq']}"
              if e in unpublished else f" · your {e['type']} #{e['seq']} is waiting for its pull request to merge "
              f"({OM} pending)")
    for e in stale:
        print(f" · your {e['type']} #{e['seq']} lost its place in the ledger: {OM} pending --rebase {e['seq']}")
    if rep["custodian"]:
        k = rep["custodian"]
        print(f" · custodian key {k['name']}: {k['status']}"
              + (f" · sign of life due by {k['silence_deadline']}" if k["status"] == "live" else ""))
    if member and member["dormant"]:
        print(f" · dormant: no signed activity since {member['last_activity']}")
    if rep["sponsorship"]:
        b = rep["sponsorship"]
        print(f" · sponsorships this year: {b['used']} of {b['allowed']} used"
              + (f"; the next frees after {b['next_free_at']}" if b["used"] and b["next_free_at"] else ""))
        for i in b["invitations"]:
            print(f" · your invitation of {i['login']} lapses at {i['expires_at']} unless they petition")
    for n in rep["notices"]:                      # what exists, and what the person may do: never a step
        print(f" ! {n['why']}")
    if blocked:
        return 0
    for i, s in enumerate(rep["steps"], 1):
        flag = "✍" if s["public"] else "·"
        due = (f" (by {s['due_by']})" if s["due_by"] else "") + (f" (from {s['opens_at']})" if s["opens_at"] else "")
        print(f" {i}. {flag} {s['why']}{due}")
        if s["argv"]:
            print(f"      → {cmdline(s['argv'])}" + (f"   choices: {', '.join(s['choices'])}" if s["choices"] else ""))
    if not rep["steps"]:
        print(f" Nothing is due. Study your degree: {OM} learn")
    return 0


def cmd_learn(a) -> int:
    st = state_of(a.ledger)
    n = a.degree
    if n is None:
        login = detect_login(a.login)
        m = st.members.get(canonical_login(st, login)) if st and login else None
        n = min(33, (m.degree + 1) if m else 1)
    if not 1 <= n <= 33:
        raise UserError("degrees go from 1 to 33")
    text = (canon.ROOT / "docs" / "degrees" / f"degree-{n:02d}.md").read_text(encoding="utf-8")
    print(json.dumps({"schema": "om.degree/1", "degree": n, "markdown": text}, ensure_ascii=False)
          if getattr(a, "json", False) else text)
    return 0


RULE_SOURCES = ("canon/eternal.toml", "docs/whitepaper/WHITEPAPER.md", "CONSTITUTION.md", "docs/whitepaper/SEALS.md",
                "docs/whitepaper/SPEC.md", "docs/governance/ROOMS.md", "docs/governance/CUSTODIAN.md",
                "docs/operations/RECOVERY.md")
RULE_STUDY = "docs/study"                     # …and every page of the study course in it
# One spelling for words the texts write in several ways (a topic and a text are both read through these).
RULE_SPELLINGS = ((r"black[\s-]+balls?|blackballs?", "blackball"), (r"\bco-sign", "cosign"))


def _rule_text(text: str) -> str:
    import re as _re
    low = text.casefold()
    for pattern, word in RULE_SPELLINGS:
        low = _re.sub(pattern, word, low)
    return low


def rule_sources(topic: str, limit: int = 5) -> list[dict]:
    """Deterministic retrieval: the sections whose text mentions the most topic words.

    It finds sources; it does not interpret them (that is the Counselor's job, with a person).
    """
    import re as _re
    words = [w for w in _re.findall(r"[a-z0-9°]{3,}", _rule_text(topic))]
    if not words:
        return []
    hits = []
    study = sorted(p.relative_to(canon.ROOT).as_posix() for p in (canon.ROOT / RULE_STUDY).glob("*.md"))
    for rel in (*RULE_SOURCES, *study):
        if not (canon.ROOT / rel).is_file():
            continue
        text = (canon.ROOT / rel).read_text(encoding="utf-8")
        parts = _re.split(r"(?m)^(?=#{1,4} |\[\[landmark\]\])", text)
        for part in parts:
            low = _rule_text(part)
            score = sum(low.count(w) for w in words)
            if score:
                head = part.strip().splitlines()[0][:120] if part.strip() else rel
                hits.append({"source": rel, "section": head.lstrip("# ").strip(), "score": score,
                             "excerpt": part.strip()[:1200]})
    return sorted(hits, key=lambda h: -h["score"])[:limit]


def cmd_rules(a) -> int:
    hits = rule_sources(a.topic)
    if a.json:
        print(json.dumps({"schema": "om.rules/1", "topic": a.topic, "sources": hits}, indent=2, ensure_ascii=False))
        return 0
    for h in hits:
        print(f"• {h['source']} — {h['section']}")
    if not hits:
        print("No source mentions that topic.")
    return 0


# ---------------------------------------------------------------- drafting --

def cmd_join(a) -> int:
    import tomllib
    decl = tomllib.loads((canon.CANON / "eternal.toml").read_text())["declaration"]["text"]
    st = state_of(a.ledger)
    digest = canon.declaration_digest()
    if st is not None and st.declaration_sha256 != digest:      # the ledger, not this clone's file, is what counts
        raise UserError("the Declaration in this clone's canon/eternal.toml is not the one this fraternity recorded "
                        "at genesis; update your clone before petitioning")
    actor = None
    if st is not None:
        login = canonical_login(st, need_login(a))
        now = ts(a.time) if a.time and _test_mode(a.ledger, key_path(a.key)) else now_utc()
        if not st.invited(login, now) and not st.reserved(login, now) and not (a.login or os.environ.get("OM_LOGIN")):
            renamed = invitation_by_id(st, now)     # an account renamed after its invitation: the invitation's login
            if renamed:
                print(f"note: the invitation names your GitHub account by its id under its earlier login {renamed}; "
                      f"you petition as {renamed} (the judge checks the account by its id)", file=sys.stderr)
                login = actor = renamed
        if st.reserved(login, now):
            raise UserError(f"the petition of {login} is already pending (see `{OM} me`)")
        if not st.invited(login, now):
            raise UserError(f"no live invitation for {login}: OpenMasonry admits by invitation. Introduce yourself in "
                            f"a public issue ({APPLY_URL}); a Master Builder who comes to answer for you may invite "
                            f"you, and then `{OM} join` works for {INVITE_EXPIRY_DAYS} days")
    if not a.json:
        print("THE DECLARATION (petition only if you agree in your own words):\n\n  " + decl + "\n")
    return propose(a, "petition", {"key": bare_public_key(key_path(a.key)), "declaration_sha256": digest},
                   "Petition for admission, committing to the Declaration", actor=actor)


def invitation_by_id(st: State, now: datetime) -> str | None:
    """The login of the live invitation whose GitHub account id is the active gh account's, if any."""
    from .onboard import gh_user
    user = gh_user()
    if user is None:
        return None
    return next((login for login, inv in st.invitations.items()
                 if inv.get("github_id") == user[1] and st.invited(login, now)), None)


def _pub_file(spec: str) -> tuple[str, str]:
    """'name:path/to/key.pub' -> (name, bare ssh-ed25519 key)."""
    name, _, path = spec.partition(":")
    parts = Path(path).expanduser().read_text().split() if path else []
    if not name or len(parts) < 2:
        raise UserError(f"expected login:path/to/key.pub, got {spec!r}")
    return name, f"{parts[0]} {parts[1]}"


def _proof_file(spec: str) -> tuple[str, str]:
    """'name:path/to/proof' -> (name, the proof of possession as `om proof` wrote it)."""
    name, _, path = spec.partition(":")
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8") if name and path else ""
    except OSError as err:
        raise UserError(f"cannot read the proof {path}: {err.strerror or err}") from None
    if not text.startswith("-----BEGIN SSH SIGNATURE-----"):
        raise UserError(f"expected NAME:FILE with the proof `{OM} proof` wrote, got {spec!r}")
    return name, text


def cmd_genesis(a) -> int:
    """Draft the genesis (entry 0). Inputs are validated by the protocol itself; nothing is pasted as text."""
    if load(a.ledger):
        raise UserError("the ledger already has entries: genesis happens once")
    login = need_login(a)
    founders = [{"login": login, "key": bare_public_key(key_path(a.key)),
                 "github_id": a.github_id if a.github_id is not None else github_account(login)[1]}]
    if canon.FOUNDER_GITHUB_ID != founders[0]["github_id"]:
        # The identity gate lets the genesis in only from the account named in the pinned network.toml.
        if canon.FOUNDER_GITHUB_ID > 0:           # set in the tree the genesis pins: the id given is what is wrong
            how = (f"the GitHub id given ({founders[0]['github_id']}) does not match founder_github_id "
                   f"({canon.FOUNDER_GITHUB_ID}) of src/openmasonry/network.toml: check --github-id (and the login) "
                   "for a typo, and draft the genesis again. The judge accepts entry 0 only from that GitHub account; "
                   "network.toml is part of @protocol, which the genesis pins")
        else:
            how = (f"the founder is not named yet: set founder_github_id = {founders[0]['github_id']} in "
                   "src/openmasonry/network.toml and draft the genesis again: the file is part of @protocol, which "
                   "the genesis pins, and the judge accepts entry 0 only from that GitHub account")
        if is_repo_ledger(a.ledger):
            raise UserError(how)
        print(f"note: {how}", file=sys.stderr)
    given_proofs = {"founder": dict(_proof_file(x) for x in getattr(a, "cofounder_proof", None) or []),
                    "witness": dict(_proof_file(x) for x in getattr(a, "witness_proof", None) or [])}
    proof_keys: dict[str, str] = {}

    def proof_of(role: str, name: str, pub: str) -> str:
        """The proof given for this key, or the mark that its private half signs it at approval."""
        if name in given_proofs[role]:
            return given_proofs[role][name]
        proof_keys[f"{role}:{name}"] = str(Path(pub).expanduser().with_suffix(""))
        return CUSTODIAN_PROOF_PENDING

    for spec in a.cofounder or []:               # LOGIN:KEY.pub, or LOGIN:KEY.pub:ID with the numeric GitHub user id
        head, sep, last = spec.rpartition(":")
        given = int(last) if sep and ":" in head and last.isascii() and last.isdigit() else None
        name, key = _pub_file(head if given is not None else spec)
        founders.append({"login": name, "key": key, "github_id": given if given is not None else github_account(name)[1],
                         "proof": proof_of("founder", name, (head if given is not None else spec).partition(":")[2])})
    witnesses = [{"name": n, "key": k, "proof": proof_of("witness", n, spec.partition(":")[2])}
                 for spec in a.witness or [] for n, k in [_pub_file(spec)]]
    custodians, held = [], {}
    for spec in getattr(a, "custodian", None) or []:
        record, paths = _custodian_spec(spec, login)
        custodians.append(record)
        held[record["name"]] = paths
    threshold = getattr(a, "custodian_threshold", None)
    if threshold is None:
        if len(custodians) > 1:
            raise UserError(f"{len(custodians)} custodians are named: say how many of their keys a noticed correction "
                            f"needs with --custodian-threshold N (1 to {len(custodians)})")
        threshold = len(custodians)
    from .govern import genesis_pins
    body = {"name": a.name, "pins": genesis_pins(), "declaration_sha256": canon.declaration_digest(),
            "founders": founders, "witnesses": witnesses, "custodians": custodians, "custodian_threshold": threshold}
    who = ", ".join(f["login"] for f in founders)
    keepers = ("" if not custodians else
               " and the custodian(s) " + ", ".join(f"{c['name']} (the member {c['member']})" for c in custodians)
               + f"; a noticed correction needs {threshold} of their keys. Approving needs both private keys of each "
               "custodian (each signs its proof of possession); store the revoke keys separately and offline afterwards")
    return propose(a, "genesis", body, f"Found {a.name} with founders {who} and {len(witnesses)} witness(es){keepers}",
                   secret={"custodians": held, "proofs": proof_keys} if held or proof_keys else None)


def _custodian_spec(spec: str, first_founder: str) -> tuple[dict, dict]:
    """'NAME:KEY.pub:REVOKE.pub[:MEMBER_LOGIN]' -> (the custodian record with its two proofs pending, the paths
    of the two private keys). The member defaults to the first founder."""
    parts = spec.split(":")
    if len(parts) not in (3, 4) or not all(parts):
        raise UserError(f"expected NAME:KEY.pub:REVOKE.pub[:MEMBER_LOGIN], got {spec!r}")
    keys, paths = [], []
    for pub in parts[1:3]:
        path = Path(pub).expanduser()
        if path.suffix != ".pub":
            raise UserError(f"expected NAME:KEY.pub:REVOKE.pub[:MEMBER_LOGIN], got {spec!r} ({pub} is not a .pub file)")
        paths.append(path.with_suffix(""))
        keys.append(bare_public_key(paths[-1]))
    return ({"name": parts[0], "key": keys[0], "revoke_key": keys[1], "member": parts[3] if len(parts) == 4 else first_founder,
             "proof": CUSTODIAN_PROOF_PENDING, "revoke_proof": CUSTODIAN_PROOF_PENDING},
            {"key": str(paths[0]), "revoke_key": str(paths[1])})


def github_account(login: str) -> tuple[str, int]:
    """(the login as GitHub spells it, its numeric user id), asked of GitHub through `gh`."""
    r = subprocess.run(["gh", "api", f"users/{login}", "--jq", '[.login, (.id | tostring)] | join(" ")'],
                       capture_output=True, text=True) if shutil.which("gh") else None
    parts = r.stdout.split() if r is not None and r.returncode == 0 else []
    if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit():
        raise UserError(f"cannot look up the GitHub account {login}: check the login and `gh auth login`, or pass "
                        f"--github-id N (the \"id\" at https://api.github.com/users/{login})")
    return parts[0], int(parts[1])


def cmd_invite(a) -> int:
    """Draft an invitation. Whom to invite is the Master Builder's own decision: nothing here suggests anyone."""
    login, github_id = a.candidate, a.github_id
    if not valid_login(login):
        raise UserError(f"{login!r} is not a GitHub login")
    if github_id is None:
        login, github_id = github_account(login)
    return propose(a, "invite", {"login": login, "github_id": github_id},
                   f"Invite {login} (GitHub account id {github_id}) to petition for admission; you become their first "
                   f"sponsor, and the invitation lapses after {INVITE_EXPIRY_DAYS} days")


def cmd_vouch(a) -> int:
    return propose(a, "vouch", {"candidate": a.candidate}, f"Sponsor {a.candidate} for admission")


def cmd_vote(a) -> int:
    """Draft a sealed vote. The person chooses Yes or No in the approval dialog, never through the agent."""
    st = state_of(a.ledger)
    login = canonical_login(st, need_login(a))
    vk = vault_key(st, login, a.ballot)
    outbox(st, a.ledger)                          # marks a vote that lost its place in the ledger as stale
    sealed = _read_json(VAULT).get(vk)
    if sealed and not sealed.get("stale"):
        raise UserError(f"you already sealed a vote in {a.ballot}; it cannot be changed")
    placeholder = "0" * 64                       # replaced by the real commitment once the person chooses
    return propose(a, "ballot_commit", {"id": a.ballot, "commitment": placeholder},
                   f"Seal a vote in ballot {a.ballot}{_ballot_about(st, a.ballot)} The person chooses Yes or No in "
                   "the approval dialog.", secret={"vault_key": vk, "salt": secrets.token_hex(16)})


def cmd_reveal(a) -> int:
    st = state_of(a.ledger)
    login = canonical_login(st, need_login(a))
    v = _read_json(VAULT).get(vault_key(st, login, a.ballot))
    if v and v.get("stale"):
        raise UserError(f"your sealed vote in {a.ballot} never reached the ledger: {OM} pending --rebase {v.get('seq')}")
    if not v:
        raise UserError(f"no sealed vote of {login} for {a.ballot} on this machine (only the machine that voted can reveal)")
    return propose(a, "ballot_reveal", {"id": a.ballot, "vote": v["vote"], "salt": v["salt"]},
                   f"Reveal your sealed vote in ballot {a.ballot} (the vote is shown only in the dialog)")


def cmd_open(a) -> int:
    st = state_of(a.ledger)
    if a.kind == "admission":
        subject = {"candidate": a.target}
    elif a.kind == "advancement":
        m = st.members.get(canonical_login(st, a.target)) if st else None
        if m is None:
            raise UserError(f"{a.target} is not a member")
        subject = {"member": m.login, "degree": m.degree + 1}
    elif a.kind == "sanction":
        if not a.measure:
            raise UserError("a sanction needs --measure admonish|suspend|expel|expel_for_fraud|reinstate")
        subject = {"member": a.target, "measure": a.measure}
    elif a.kind == "amendment":
        if not a.sha256:
            raise UserError(f"an amendment needs --sha256 <hash of the new text> (sha256sum {a.target}, or shasum -a 256 {a.target} on macOS)")
        subject = {"path": a.target, "new_sha256": a.sha256}
    elif a.kind == "custodian":                   # the one decision of the Master Builders about a custodian
        subject = {"remove": canonical_login(st, a.target)}
    else:
        subject = {"action": a.measure or "add", "name": a.target}
        if subject["action"] == "add":
            if not a.witness_key or not getattr(a, "witness_proof", None):
                raise UserError("adding a witness needs --witness-key \"ssh-ed25519 AAAA…\" and --witness-proof FILE: "
                                f"the proof that the new witness holds that key, which its holder makes with `{OM} proof "
                                f"witness {a.target} --key PATH`")
            subject["key"] = " ".join(a.witness_key.split()[:2])
            subject["proof"] = _proof_file(f"{a.target}:{a.witness_proof}")[1]
    seq = (st.seq + 1) if st else 0
    stem = "".join(c if c.isalnum() else "-" for c in a.target.lower()).strip("-")[:40] or "x"
    bid = a.id or f"{a.kind[:3]}-{stem}-{seq}"
    summary = (f"Open the ballot {bid} that would remove the custodian key of {subject['remove']} (decided by the "
               "Master Builders; no correction pauses it)" if a.kind == "custodian" else
               f"Open the {a.kind} ballot {bid} on {', '.join(f'{k}={v}' for k, v in subject.items() if k not in ('key', 'proof'))}")
    body = {"id": bid, "kind": a.kind, "subject": subject}
    for field in ("commit_days", "reveal_days"):  # the ledger decides which kinds take them (only an amendment)
        if getattr(a, field, None) is not None:
            body[field] = getattr(a, field)
    if "commit_days" in body or "reveal_days" in body:
        summary += (f", with {body.get('commit_days', COMMIT_DAYS)} days to commit and "
                    f"{body.get('reveal_days', REVEAL_DAYS)} to reveal")
    if getattr(a, "rerun", None):
        body["rerun"] = a.rerun
        summary += (f". It re-runs the lapsed ballot {a.rerun}: the same subject, once, within {RERUN_DAYS} days of its close, "
                    "without waiting again for those who did not vote in it (they keep their vote)")
    return propose(a, "ballot_open", body, summary)


def cmd_close(a) -> int:
    return propose(a, "ballot_close", {"id": a.ballot}, f"Close ballot {a.ballot} and apply its result")


def cmd_exam(a) -> int:
    st = state_of(a.ledger)
    login = canonical_login(st, need_login(a))
    t = ts(a.time) if a.time else now_utc()
    return propose(a, "exam_open", {"candidate": login, "degree": a.degree, "work_ref": a.work,
                                    "beacon_round": drand_round(t) + BEACON_DELAY_ROUNDS},
                   f"Open your examination for the {a.degree}° with the work {a.work}")


def cmd_report(a) -> int:
    body = {"candidate": a.candidate, "degree": a.degree, "verdict": a.verdict}
    if a.reason:
        body["reason"] = a.reason
    return propose(a, "exam_report", body, f"Give the verdict {a.verdict.upper()} on {a.candidate}'s {a.degree}° examination")


def cmd_recuse(a) -> int:
    from .guide import recusal_outcome
    st = state_of(a.ledger)
    ex = st.exams.get((canonical_login(st, a.candidate), a.degree)) if st is not None else None
    login = canonical_login(st, need_login(a))
    then = ("the next examiner in the lot's order replaces you if one remains; otherwise the exam lapses, with no "
            "penalty to the candidate")
    if ex is not None and ex.examiners is not None and login in ex.examiners:
        then = recusal_outcome(st, ex, login, ts(a.time) if a.time else now_utc()).rstrip(".")
    return propose(a, "exam_recuse", {"candidate": a.candidate, "degree": a.degree},
                   f"Recuse yourself from {a.candidate}'s {a.degree}° examination: {then}")


def cmd_draw(a) -> int:
    """Perform a pending lot with the public drand beacon (anyone may)."""
    from .beacon import fetch as _fetch
    from .ledger import drand_time

    def fetch(rnd: int) -> str:
        try:
            return _fetch(rnd)
        except Exception:
            raise UserError(f"the public drand beacon (round {rnd}) could not be fetched: retry when online, or pass "
                            "a beacon fetched elsewhere with --beacon HEX") from None
    st = state_of(a.ledger)
    now = ts(a.time) if a.time else now_utc()
    for ex in st.exams.values():
        if ex.examiners is None and not ex.lapsed and not ex.expired(now, st) and now >= drand_time(ex.beacon_round) and \
                (a.candidate is None or ex.candidate.casefold() == a.candidate.casefold()):
            return propose(a, "exam_draw", {"candidate": ex.candidate, "degree": ex.degree,
                                            "beacon": a.beacon or fetch(ex.beacon_round)},
                           f"Draw the examiners of {ex.candidate} for the {ex.degree}° (drand round {ex.beacon_round})")
    if st.council_call is not None and now >= drand_time(st.council_call):
        return propose(a, "council_draw", {"beacon": a.beacon or fetch(st.council_call)},
                       f"Draw the Supreme Council (drand round {st.council_call})")
    print("No lot is due yet.")
    return 0


def cmd_call_council(a) -> int:
    from .ledger import drand_round as _dr
    t = ts(a.time) if a.time else now_utc()
    return propose(a, "council_call", {"beacon_round": _dr(t) + BEACON_DELAY_ROUNDS},
                   "Call the lot of the Supreme Council for its vacant seats")


def cmd_work(a) -> int:
    return propose(a, "work", {"ref": a.ref}, f"Record the work {a.ref}")


def cmd_depart(a) -> int:
    from .ledger import REJOIN_AFTER_DAYS
    return propose(a, "depart", {}, f"Leave the fraternity (a Master Builder may invite you again after "
                                    f"{REJOIN_AFTER_DAYS} days; you would return at the 1st degree)")


def cmd_rekey(a) -> int:
    """Draft the replacement of your own key. Nothing is signed here: when the person approves, the new key
    signs the proof and the current key signs the entry."""
    st = state_of(a.ledger)
    login = canonical_login(st, need_login(a))
    m = st.members.get(login) if st else None
    if m is None:
        raise UserError(f"{login} is not a member: only a member has a key to replace")
    new_key = Path(a.new_key).expanduser()
    new = bare_public_key(new_key)
    if key_kind(new) is None:
        raise UserError(f"{new_key}.pub: {KEY_RULE}")
    return propose(a, "rekey", {"key": new, "proof": REKEY_PROOF_PENDING},
                   f"Replace your signing key {fingerprint(m.key)} by {fingerprint(new)} ({new.split(' ')[0]}); "
                   "when you approve, the new key signs a proof and your current key signs the entry",
                   secret={"new_key": str(new_key)})


# ------------------------------------------------ custodians, corrections ----
# Every command below only drafts, like the others. A custodian act names the custodian as its actor and is
# signed with the custodian key (--as NAME --custodian-key PATH, or OM_CUSTODIAN and OM_CUSTODIAN_KEY).

def _custodian_act(a, typ: str, body: dict, summary, **kw) -> int:
    st = state_of(a.ledger)
    name, key = custodian_identity(a, st)
    return propose(a, typ, body, summary(st, name) if callable(summary) else summary, actor=name, key=key, **kw)


def cmd_correct(a) -> int:
    """Draft a correction. The reason is read now and staged inside the draft; when the person approves, it is
    written as ledger/reasons/<sha256>.md beside the entry, and both go in the same pull request."""
    target = correction_target(a.act, **{flag: getattr(a, f"target_{flag}", None) for flag in TARGET_FLAGS})
    ground = a.ground or ACT_GROUND.get(a.act)
    if not ground:
        raise UserError(f"{a.act} needs --ground: one of {', '.join(GROUNDS)}")
    data, digest = read_reason(a.reason)
    about = ", ".join(str(v) for v in target.values())
    where = f"{REASONS_DIR}/{digest}.md"
    return _custodian_act(
        a, "correction", {"act": a.act, "target": target, "ground": ground, "reason_sha256": digest},
        lambda st, name: (f"Correction by the custodian {name}: {a.act}{' ' + about if about else ''} on the ground "
                          f"{ground}. Its reason ({len(data)} bytes, sha256 {digest[:12]}…) is published as {where} "
                          "in the same pull request, for good"),
        secret={"reason": base64.b64encode(data).decode("ascii")},
        extra={"reason": {"sha256": digest, "path": where, "bytes": len(data)}})


def cmd_cosign_correction(a) -> int:
    return _custodian_act(a, "correction_cosign", {"seq": a.seq},
                          lambda st, name: f"Co-sign correction {a.seq}{_correction_ref(st, a.seq)} with the custodian "
                                           f"key {name}")


def cmd_apply_correction(a) -> int:
    return _custodian_act(a, "correction_apply", {"seq": a.seq},
                          lambda st, name: f"Apply correction {a.seq}{_correction_ref(st, a.seq)} It takes effect with "
                                           "this entry, once")


def cmd_withdraw_correction(a) -> int:
    return _custodian_act(a, "correction_withdraw", {"seq": a.seq},
                          lambda st, name: f"Withdraw correction {a.seq}{_correction_ref(st, a.seq)} What it had in "
                                           "force ends; a pending act is canceled")


def cmd_alive(a) -> int:
    return _custodian_act(a, "custodian_alive", {},
                          lambda st, name: f"Sign of life of the custodian key {name} (without one it lapses for good "
                                           f"more than {CUSTODIAN_SILENCE_DAYS} days after the last)")


def cmd_revoke_custodian(a) -> int:
    """Draft the removal of a custodian key by its own revoke key (the one thing that key signs)."""
    st = state_of(a.ledger)
    name, key = canonical_login(st, a.name), Path(a.revoke_key).expanduser()
    c = st.custodians.get(name) if st is not None else None
    if c is not None and bare_public_key(key) != c.revoke_key:
        raise UserError(f"the key {key} ({fingerprint(bare_public_key(key))}) is not the revoke key the ledger holds "
                        f"for {name} ({fingerprint(c.revoke_key)})")
    return propose(a, "custodian_revoke", {"name": name},
                   f"Revoke the custodian key of {name} with its revoke key: it is removed at once and for good, and "
                   "whatever it had in force ends", actor=name, key=key)


def cmd_object(a) -> int:
    """Draft a Master Builder's objection to a correction. Whether to object is the person's alone to decide."""
    st = state_of(a.ledger)
    c = st.corrections.get(a.seq) if st is not None else None
    now = ts(a.time) if a.time else now_utc()
    if c is not None and c.class_ == "noticed" and st.noticed_status(c, now) == "applied":
        # The ledger records such an objection and it reverses nothing (`ledger._correction_object`).
        raise UserError(f"correction {a.seq} was applied at {iso(c.applied)}: an objection no longer changes it "
                        "(an applied correction is never voided), so none is drafted")
    return propose(a, "correction_object", {"seq": a.seq},
                   f"Object to correction {a.seq}{_correction_ref(st, a.seq)} The objection is public and counts once")


# ------------------------------------------------------ a lost or stolen key --

def cmd_recover(a) -> int:
    """Draft the request to go on with a new key (the old one is lost or stolen): after a freeze, or open, with no
    freeze in force (a recovery never needs a custodian).
    Nothing is signed here: when the person approves, the NEW key signs its proof and the entry."""
    st = state_of(a.ledger)
    login = canonical_login(st, need_login(a))
    m = st.members.get(login) if st else None
    if m is None:
        raise UserError(f"{login} is not a member: only a member has a key to recover")
    new_key = Path(a.new_key).expanduser()
    new = bare_public_key(new_key)
    if key_kind(new) is None:
        raise UserError(f"{new_key}.pub: {KEY_RULE}")
    return propose(a, "rekey_recover", {"key": new, "proof": REKEY_PROOF_PENDING},
                   f"Ask to recover the membership of {login} with the new key {fingerprint(new)} ({new.split(' ')[0]}) "
                   f"in place of {fingerprint(m.key)}. Nothing changes yet: Master Builders co-sign "
                   f"({RECOVER_COSIGNERS} after a freeze; {RECOVER_OPEN_COSIGNERS} with no freeze in force, or after a "
                   "recovery the old key stopped; never more than the other active Master Builders who exist), "
                   f"{RECOVER_NOTICE_DAYS} days of notice pass after a freeze, {RECOVER_OPEN_NOTICE_DAYS} without one, "
                   f"{RECOVER_LOWERED_NOTICE_DAYS} whenever fewer co-signers are enough, and the old key can stop it, "
                   "unless it follows a recovery that key stopped. The new key signs this request, and it must be "
                   "listed on your GitHub account", key=new_key)


def cmd_recover_cosign(a) -> int:
    st = state_of(a.ledger)
    login = canonical_login(st, a.member)
    return propose(a, "rekey_cosign", {"login": login},
                   f"Co-sign the key recovery of {login}: you answer that the person asking for the new key is that "
                   "member (check with them outside the ledger first)")


def cmd_recover_oppose(a) -> int:
    """Draft a Master Builder's opposition to an open recovery (one asked with no freeze in force). Whether to
    oppose is the person's alone to decide."""
    st = state_of(a.ledger)
    login = canonical_login(st, a.member)
    return propose(a, "rekey_oppose", {"login": login},
                   f"Oppose the key recovery of {login}: the opposition is public and counts once; enough of them void "
                   "the recovery")


def cmd_recover_object(a) -> int:
    return propose(a, "rekey_object", {},
                   "Stop the recovery of your key, with the key the ledger holds for you; no new recovery is accepted "
                   f"for your login for {RECOVER_INTERVAL_DAYS} days")


def cmd_recover_apply(a) -> int:
    """Draft the completion of a recovery; it is signed by the new key the recovery was requested with."""
    new_key = getattr(a, "new_key", None) or _read_json(CONFIG).get("recovery_key")
    if not new_key:
        raise UserError("which key completes the recovery? pass --new-key PATH: the private key file (or hardware-key "
                        f"handle) of the new key the recovery was requested with (`{OM} recover --new-key PATH`)")
    return propose(a, "rekey_recover_apply", {},
                   "Complete the recovery of your key: from this entry on only the new key signs for you, the old one "
                   "is retired for good and the freeze ends", key=Path(str(new_key)).expanduser())


# ------------------------------------------------ the founder's fallback, the succession --
# Whether to claim, object or apply is the person's alone to decide: the Guide states these acts, never as steps.

def _key_file(spec: str) -> Path:
    """A private key path, given as the key file or as its .pub (the .pub is stripped)."""
    p = Path(spec).expanduser()
    return p.with_suffix("") if p.suffix == ".pub" else p


def _claim_about(st: State | None, seq: object) -> str:
    c = st.claims.get(seq) if st is not None and isinstance(seq, int) else None
    if c is None:
        return ""
    return (f" (by the founder {c.founder}, as {c.name}, made at {iso(c.time)}: under notice until "
            f"{iso(c.time + CLAIM_NOTICE_DAYS * DAY)}, applied not later than {iso(c.time + CLAIM_EXPIRY_DAYS * DAY)})")


def cmd_claim_custodian(a) -> int:
    """Draft a founder's claim of the Custodian office (where no custodian key is live). Nothing is signed here:
    when the person approves, the custodian key and the revoke key each sign their proof of possession, then the
    member key signs the entry."""
    st = state_of(a.ledger)
    if st is None:
        raise UserError("the ledger is empty: the fraternity has not been founded yet")
    login = canonical_login(st, need_login(a))
    m = st.members.get(login)
    if m is None or not m.founder:
        raise UserError(f"{login} is not a founder: only a founder may claim the Custodian office, with their member key")
    paths, keys = {}, {}
    for field, what in (("custodian_key", "custodian key"), ("revoke_key", "revoke key")):
        paths[field] = _key_file(getattr(a, field))
        keys[field] = bare_public_key(paths[field])
        if key_kind(keys[field]) is None:
            raise UserError(f"{paths[field]}.pub (the {what}): {KEY_RULE}")
    if keys["custodian_key"] == keys["revoke_key"]:
        raise UserError("the custodian key and the revoke key are the same key: a claim names two different new keys "
                        "(make each with ssh-keygen -t ed25519)")
    name, key, revoke = a.name, keys["custodian_key"], keys["revoke_key"]
    return propose(a, "custodian_claim", {"name": name, "key": key, "revoke_key": revoke,
                                          "proof": CUSTODIAN_PROOF_PENDING, "revoke_proof": CUSTODIAN_PROOF_PENDING},
                   f"Claim the Custodian office again as {name}, with the new custodian key {fingerprint(key)} and the "
                   f"new revoke key {fingerprint(revoke)}. The claim is public for {CLAIM_NOTICE_DAYS} days of notice, "
                   "during which one active Master Builder who is not a founder can stop it; you apply it yourself "
                   f"from day {CLAIM_NOTICE_DAYS} to day {CLAIM_EXPIRY_DAYS} ({OM} apply-claim {st.seq + 1}). When you "
                   "approve, both private keys sign their proofs of possession once; afterwards store the revoke key "
                   "separately and offline",
                   secret={"claim": {"key": str(paths["custodian_key"]), "revoke_key": str(paths["revoke_key"])}})


def cmd_object_claim(a) -> int:
    """Draft the objection of a Master Builder who is not a founder to a pending claim of the Custodian office."""
    st = state_of(a.ledger)
    return propose(a, "custodian_claim_object", {"seq": a.seq},
                   f"Object to the claim of the Custodian office of entry {a.seq}{_claim_about(st, a.seq)}. One "
                   "objection is enough: the claim is void for good, and a founder may make a new one")


def cmd_apply_claim(a) -> int:
    """Draft the founder's application of their claim of the Custodian office, after its notice."""
    st = state_of(a.ledger)
    return propose(a, "custodian_claim_apply", {"seq": a.seq},
                   f"Apply your claim of the Custodian office of entry {a.seq}{_claim_about(st, a.seq)}. Its custodian "
                   "key becomes the only live one from this entry on; it lapses after "
                   f"{CUSTODIAN_SILENCE_DAYS} days without a sign of life ({OM} alive), at the Sunset, by its revoke "
                   f"key, by a removal ballot, and {CUSTODIAN_TERM_DAYS} days after this entry")


def cmd_claim_succession(a) -> int:
    """Draft a succession claim: a member below the 3rd degree states that no active Master Builder is left."""
    now = ts(a.time) if a.time else now_utc()
    return propose(a, "succession_claim", {},
                   "Claim the succession: no active Master Builder is left. Any entry a Master Builder signs within "
                   f"{SUCCESSION_DAYS} days cancels it; after them (from about {iso(now + SUCCESSION_DAYS * DAY)}), "
                   f"until {SUCCESSION_MASTERS} active Master Builders exist, the members of the highest degree present "
                   "may examine, elect an advancement, invite and sponsor, and nothing else")


def draft_stale(d: dict, heads: dict) -> bool | None:
    """Whether a stored draft can no longer be approved, as `om approve` would say STALE: the ledger moved past
    it, or it is too old for the Tyler. None when its ledger cannot be read. `heads` caches (seq, head) per ledger."""
    e = d.get("entry") or {}
    try:
        led = Path(d["ledger"])
        if led not in heads:
            st = state_of(led)
            heads[led] = (st.seq, st.head) if st else (-1, canon.ZERO_HASH)
        seq, head = heads[led]
        if e.get("seq") != seq + 1 or e.get("prev") != head:
            return True
        return not _test_mode(led, d.get("key")) and now_utc() - ts(e["time"]) > CLOCK_TOLERANCE - CLOCK_TOLERANCE / 12
    except (KeyError, TypeError, ValueError, OSError, Invalid):
        return None


def cmd_drafts(a) -> int:
    """List pending drafts (summaries only); a draft that can no longer be approved is marked stale."""
    items, heads = [], {}
    for p in sorted(PENDING.glob("*.json")) if PENDING.exists() else []:
        d = _read_json(p)
        items.append({"digest": p.stem, "seq": (d.get("entry") or {}).get("seq"), "summary": d.get("summary"),
                      "stale": draft_stale(d, heads)})
    text = "\n".join(f"{i['digest'][:16]}  #{i['seq']}  {i['summary']}"
                     + (f"  → stale: {OM} discard {i['digest'][:16]}, then draft it again" if i["stale"] else "")
                     for i in items) or "No pending drafts."
    return _out(a, {"schema": "om.drafts/1", "drafts": items}, text, 0)


def cmd_discard(a) -> int:
    p = _find_pending(a.digest)
    p.unlink()
    return _out(a, {"discarded": p.stem}, f"discarded {p.stem[:16]}", 0)


def cmd_pending(a) -> int:
    """Own signed entries waiting for their pull request (the ledger shows them once merged), and stale ones
    that lost their seq to another entry (`--rebase SEQ` re-drafts them on top of the current ledger)."""
    st = state_of(a.ledger)
    waiting, stale = outbox(st, a.ledger)
    if getattr(a, "rebase", None) is not None:
        return _rebase(a, st, stale)
    if getattr(a, "publish", None) is not None:
        e = next((x for x in waiting if x["seq"] == a.publish), None)
        if e is None:
            raise UserError(f"no signed entry #{a.publish} of yours is waiting to be published (see {OM} pending)")
        return publish_pending(a, st, e)
    items = []
    for e, state in [(e, "waiting") for e in waiting] + [(e, "stale") for e in stale]:
        pr = {}
        if is_repo_ledger(a.ledger):               # never asks GitHub about a scratch (test) ledger
            pr = entry_pr(e)[1] or {}              # this very entry's, never an older one from the same branch name
        items.append({"seq": e["seq"], "type": e["type"], "pr": pr.get("url"),
                      "state": "stale" if state == "stale" else pr.get("state", "unknown")})
        if a.drop is not None and a.drop == e["seq"]:
            _forget_outbox(_outbox_file(st, e))
            if e["type"] == "ballot_commit":       # the PR was abandoned: the vote may be cast again
                vault = _read_json(VAULT)
                vault.pop(vault_key(st, e["actor"], e["body"]["id"]), None)
                _write_private(VAULT, vault)
            items[-1]["state"] = "dropped"
            if is_repo_ledger(a.ledger):
                items[-1]["deleted_branch"] = _drop_canonical_branch(e)
    hint = {"stale": "  → needs re-sequencing: {OM} pending --rebase {seq}",
            "unknown": "  → no pull request found: {OM} pending --publish {seq} (it asks you first)",
            "CLOSED": "  → its pull request was closed: {OM} pending --publish {seq} opens a new one (it asks you "
                      "first), or {OM} pending --drop {seq}"}
    text = "\n".join(f"#{i['seq']} {i['type']}: {i['state']} {i['pr'] or ''}"
                     + hint.get(i["state"], "").format(OM=OM, seq=i["seq"])
                     + (f"  (deleted its branch {i['deleted_branch']} from {canon.CANONICAL_REPO})"
                        if i.get("deleted_branch") else "")
                     for i in items) or "Nothing is waiting: all your signed entries are in the ledger."
    return _out(a, {"schema": "om.pending/1", "pending": items}, text, 0)


def _rebase(a, st: State | None, stale: list[dict]) -> int:
    """Re-draft a stale act on top of the current ledger: new seq, prev and time, same body. A vote reuses
    the sealed commitment kept in the vault. The person approves the new draft with `om approve` again."""
    e = next((x for x in stale if a.rebase in (-1, x["seq"])), None)
    if e is None:
        raise UserError("no stale entry " + ("" if a.rebase == -1 else f"#{a.rebase} ") + f"to re-sequence (see {OM} pending)")
    if e["type"] in OTHER_KEY_TYPES:
        raise UserError(f"entry #{e['seq']} ({e['type']}) is not signed with your member key and is not "
                        f"re-sequenced: forget it ({OM} pending --drop {e['seq']}) and draft the act again")
    if e["type"] in PROOF_TYPES:
        raise UserError(f"entry #{e['seq']} ({e['type']}) carries proofs of possession that its other keys signed at "
                        f"approval, and is not re-sequenced: forget it ({OM} pending --drop {e['seq']}) and draft the "
                        "act again")
    login = canonical_login(st, need_login(a))
    if e["actor"].casefold() != login.casefold():
        raise UserError(f"entry #{e['seq']} is {e['actor']}'s, not yours")
    typ, body = e["type"], copy.deepcopy(e["body"])
    secret: dict = {"rebase": True, "replaces": f"{e['seq']:06d}.json"}
    t = ts(a.time) if a.time and _test_mode(a.ledger, key_path(a.key)) else now_utc()
    if typ in ("exam_open", "council_call"):     # the lot's future round follows the new time
        body["beacon_round"] = drand_round(t) + BEACON_DELAY_ROUNDS
    if typ == "ballot_commit":
        vk = vault_key(st, login, body.get("id", ""))
        v = _read_json(VAULT).get(vk)
        if not v or body.get("commitment") != commitment(body["id"], login, v.get("vote", ""), v.get("salt", "")):
            raise UserError(f"the sealed vote of #{e['seq']} is not in this machine's vault: drop it "
                            f"({OM} pending --drop {e['seq']}) and vote again")
        secret |= {"vault_key": vk, "salt": v["salt"], "vote": v["vote"]}
    if typ == "genesis":
        raise UserError("the genesis cannot be re-sequenced")
    if typ == "rekey" and not a.key:              # still signed by the key the ledger holds, not the configured new one
        a.key = _read_json(CONFIG).get("previous_key")
    return propose(a, typ, body, f"Re-sequence your {typ} #{e['seq']} (it lost its place in the ledger) as a new "
                   "entry with the same content", secret=secret)


def cmd_alarm(a) -> int:
    """The Tyler's public act: open an issue on the canonical repository, after the person approves."""
    title, body = clean(a.title, 120), clean(a.body, 4000)
    if _ask("OpenMasonry: open a public issue?", f"Title: {title}\n\n{body}", ["Open the issue"], None) is None:
        return _out(a, {"canceled": True}, "Canceled.", 1)
    r = subprocess.run(["gh", "issue", "create", "--repo", canon.CANONICAL_REPO, "--title", title, "--body", body],
                       cwd=canon.ROOT, capture_output=True, text=True)
    return _out(a, {"issue": r.stdout.strip() or None}, r.stdout.strip() or r.stderr.strip(), 0 if r.returncode == 0 else 1)
