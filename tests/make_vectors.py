"""Conformance vectors: small ledgers with the outcome every implementation must reach (SPEC section 14).

    PYTHONPATH=src python3 -m tests.make_vectors        writes tests/vectors/<name>.json

Each vector is one JSON object:

    {"name": …, "description": …, "entries": [ … ],
     "expect": {"valid": true,  "seq": N, "head": …, "state_sha256": …}
             | {"valid": false, "seq": N, "error": …}}

An element of `entries` is an entry (a JSON object), or a string holding the exact text of an entry file,
where the text itself is the point (a duplicate key, a number with a fraction). A valid vector states the
`seq` and the entry hash of its last entry and the digest of the state it leaves (SPEC section 4.11). An
invalid one states the `seq` of the entry that is refused and the refusal message, without its
`entry N: ` prefix.

Everything is fixed: the keys (Ed25519 keys derived from names, signed here in pure Python, so no OpenSSH
is needed), the times, the beacons, the pins. The degree table the vectors pin is the one archived as
canon/history/<DEGREES>.toml. `tests/test_vectors.py` generates the vectors again in memory and compares
them with the committed files byte for byte, then replays the files with real signature verification.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openmasonry import canon, crypto, ledger
from openmasonry.crypto import merkle_root
from openmasonry.ledger import (BEACON_DELAY_ROUNDS, GENESIS_PINS, REVEAL_GAP, Invalid, State, commitment,
                                custodian_message, custodian_revoke_message, drand_round, drand_time, entry_hash,
                                entry_path, founder_message, iso, load, rekey_message, replay, signed_payload, witness_message)
from tests.test_signatures import L, armor, dearmor, keyline, keypair, sign_entry

VECTORS = Path(__file__).with_name("vectors")
T0 = datetime(2027, 1, 1, tzinfo=timezone.utc)
DAY, HOUR, SEC = timedelta(days=1), timedelta(hours=1), timedelta(seconds=1)
DEGREES = "cc5055199c8213648f536a6856c9d6879944c48be7151593ad279f73b84b7b32"    # canon/history/<this>.toml
URL = "https://example.org/work"
THREE = ["hiram", "ada", "carol"]
SEVEN = ["hiram", "ada", "carol", "dan", "eve", "fay", "gus"]

_signatures: dict[tuple[bytes, bytes], str] = {}
_verdicts: dict[tuple[bytes, str, str], bool] = {}


def digest_of(what: str) -> str:
    return hashlib.sha256(f"openmasonry vector {what}".encode()).hexdigest()


def seed(name: str) -> bytes:
    return hashlib.sha256(f"openmasonry vector key: {name}".encode()).digest()


def github_id(login: str) -> int:
    return int(hashlib.sha256(login.lower().encode()).hexdigest()[:8], 16) + 1


def salt(login: str) -> str:
    return hashlib.sha256(login.encode()).hexdigest()[:32]


def beacon(rnd: int) -> str:
    return digest_of(f"beacon of round {rnd}")


def real(payload: bytes, sig: str, actor: str, key: str) -> bool:
    """The protocol's own verdict on a signature (`crypto.signature_valid`), computed once for each triple."""
    k = (payload, sig, key)
    if k not in _verdicts:
        _verdicts[k] = isinstance(sig, str) and sig.isascii() and crypto.signature_valid(payload, sig, key)
    return _verdicts[k]


def run(entries: list, verifier=real) -> State:
    """Replay the entries of a vector. Where an element is the text of a file, every element becomes a file
    and the strict loader reads them, as it reads a ledger directory."""
    if not any(isinstance(e, str) for e in entries):
        return replay(entries, verifier)
    with tempfile.TemporaryDirectory() as d:
        for i, e in enumerate(entries):
            path = entry_path(Path(d), i)
            path.parent.mkdir(exist_ok=True)
            path.write_text(e if isinstance(e, str) else json.dumps(e), encoding="utf-8")
        return replay(load(Path(d)), verifier)


def outcome(entries: list, verifier=real) -> dict:
    try:
        st = run(entries, verifier)
    except Invalid as err:
        return {"valid": False, "seq": err.seq, "error": str(err).removeprefix(f"entry {err.seq}: ")}
    return {"valid": True, "seq": st.seq, "head": st.head, "state_sha256": st.digest()}


class Ledger:
    """A ledger under construction: a clock, and real signatures by keys derived from names."""

    def __init__(self):
        self.entries: list = []
        self.now = T0

    @staticmethod
    def key(name: str) -> str:
        return keyline(keypair(seed(name))[2])

    @staticmethod
    def sign(name: str, payload: bytes) -> str:
        k = (seed(name), payload)
        if k not in _signatures:
            _signatures[k] = sign_entry(seed(name), payload)[1]
        return _signatures[k]

    def draft(self, typ: str, actor: str, body: dict) -> dict:
        prev = entry_hash(self.entries[-1]) if self.entries else canon.ZERO_HASH
        return {"seq": len(self.entries), "prev": prev, "time": iso(self.now), "type": typ, "actor": actor, "body": body}

    def add(self, typ: str, actor: str, body: dict, after: timedelta = timedelta(0), key_of: str | None = None) -> dict:
        self.now += after
        e = self.draft(typ, actor, body)
        e["sig"] = self.sign(key_of or actor, signed_payload(e))
        self.entries.append(e)
        return e

    def state(self) -> State:
        return replay(self.entries, real)

    def copy(self) -> "Ledger":
        other = Ledger()
        other.entries, other.now = list(self.entries), self.now
        return other


def founded(founders=THREE, witnesses=("tyler",), custodians=(), threshold=None) -> Ledger:
    """A genesis with fixed pins. `custodians` are pairs (name, member)."""
    c = Ledger()
    records = []
    for name, member in custodians:
        key, revoke = c.key(name), c.key(f"{name}-revoke")
        records.append({"name": name, "key": key, "revoke_key": revoke, "member": member,
                        "proof": c.sign(name, custodian_message(name, member, key)),
                        "revoke_proof": c.sign(f"{name}-revoke", custodian_revoke_message(name, key, revoke))})
    c.add("genesis", founders[0], {
        "name": "OpenMasonry Vector Lodge",
        "pins": {path: DEGREES if path == "canon/degrees.toml" else digest_of(f"pin of {path}") for path in GENESIS_PINS},
        "declaration_sha256": digest_of("declaration"),
        # The first founder signs the entry; every other founder and every witness proves possession of the key.
        "founders": [{"login": f, "key": c.key(f), "github_id": github_id(f)}
                     | ({"proof": c.sign(f, founder_message(f, github_id(f), c.key(f)))} if i else {})
                     for i, f in enumerate(founders)],
        "witnesses": [{"name": w, "key": c.key(w), "proof": c.sign(w, witness_message(w, c.key(w)))} for w in witnesses],
        "custodians": records,
        "custodian_threshold": (1 if records else 0) if threshold is None else threshold,
    })
    return c


def lodge() -> Ledger:
    """Seven founders, the witness tyler and the custodian warden, linked to gus."""
    return founded(SEVEN, custodians=(("warden", "gus"),))


def open_ballot(c: Ledger, bid: str, by: str, kind: str, subject: dict, after=timedelta(0)) -> None:
    c.add("ballot_open", by, {"id": bid, "kind": kind, "subject": subject}, after=after)


def commit(c: Ledger, bid: str, who: str, vote: str, after=timedelta(0)) -> None:
    c.add("ballot_commit", who, {"id": bid, "commitment": commitment(bid, who, vote, salt(who))}, after=after)


def reveal(c: Ledger, bid: str, who: str, vote: str, after=timedelta(0)) -> None:
    c.add("ballot_reveal", who, {"id": bid, "vote": vote, "salt": salt(who)}, after=after)


def decide(c: Ledger, bid: str, votes: dict[str, str], closer: str = "tyler") -> None:
    """Commit at once, reveal one second after the reveal window opens, close one second after it ends."""
    for who, vote in votes.items():
        commit(c, bid, who, vote)
    b = c.state().ballots[bid]
    c.now = b.commit_until + REVEAL_GAP + SEC
    for who, vote in votes.items():
        reveal(c, bid, who, vote)
    c.now = b.reveal_until + SEC
    c.add("ballot_close", closer, {"id": bid})


def admit(c: Ledger, who: str, votes: dict[str, str], by: str = "hiram", second: str = "ada") -> None:
    """invite, petition, vouch, and the admission ballot with the given votes."""
    c.add("invite", by, {"login": who, "github_id": github_id(who)})
    c.add("petition", who, {"key": c.key(who), "declaration_sha256": digest_of("declaration")}, after=HOUR)
    c.add("vouch", second, {"candidate": who}, after=HOUR)
    open_ballot(c, f"adm-{who}", by, "admission", {"candidate": who}, after=HOUR)
    decide(c, f"adm-{who}", votes)


def witness_subject(c: Ledger, name: str, signed_by: str | None = None) -> dict:
    """The subject of a ballot that adds the witness `name`: its key, and the proof of possession signed by
    that key (or, to make a bad one, by the key named `signed_by`)."""
    key = c.key(name)
    return {"action": "add", "name": name, "key": key, "proof": c.sign(signed_by or name, witness_message(name, key))}


def correct(c: Ledger, act: str, target: dict, ground: str, after=timedelta(0), by: str = "warden") -> int:
    return c.add("correction", by, {"act": act, "target": target, "ground": ground,
                                    "reason_sha256": digest_of(f"reason of the {act}")}, after=after)["seq"]


def checkpoint(c: Ledger, witness: str, root: bool = False, after=timedelta(0), **over) -> None:
    st = c.state()
    body = {"upto_seq": st.seq, "head": st.head, "state_sha256": st.digest(), "state_version": ledger.STATE_VERSION} \
        | ({"root": merkle_root(st.hashes)} if root else {})
    c.add("witness", witness, body | over, after=after)


# ------------------------------------------------------------------ valid ----

def founding_with_custodians():
    """A genesis with three founders, one witness and two custodians (threshold 2), each custodian key and
    revoke key proving possession; then a sign of life of one custodian."""
    c = founded(custodians=(("warden", "hiram"), ("keeper", "ada")), threshold=2)
    c.add("custodian_alive", "keeper", {}, after=DAY)
    return c.entries


def admission_passes():
    """invite, petition, vouch and an admission ballot (commit, reveal, close by the witness) with three white
    balls: the candidate becomes a member of the 1st degree, with the inviter and the voucher as sponsors."""
    c = founded()
    admit(c, "alice", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    return c.entries


def admission_blackballed():
    """The same admission with one black ball in three: 5 x 1 >= 3, so the ballot fails, nobody is admitted
    and the petition is removed."""
    c = founded()
    admit(c, "alice", {"hiram": "yes", "ada": "yes", "carol": "no"})
    return c.entries


def exam_and_advancement():
    """A member of the 1st degree waits 30 days and opens an exam; the witness draws two examiners with the
    beacon; one recuses and the next in the lot's order takes the seat; both report `pass`; an advancement
    ballot passes and the member holds the 2nd degree."""
    c = founded(SEVEN)
    admit(c, "alice", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    c.now += 30 * DAY
    rnd = drand_round(c.now) + BEACON_DELAY_ROUNDS
    c.add("exam_open", "alice", {"candidate": "alice", "degree": 2, "work_ref": URL, "beacon_round": rnd})
    c.now = drand_time(rnd)
    c.add("exam_draw", "tyler", {"candidate": "alice", "degree": 2, "beacon": beacon(rnd)})
    first, second = c.state().exams[("alice", 2)].examiners
    c.add("exam_recuse", first, {"candidate": "alice", "degree": 2}, after=HOUR)
    for who in c.state().exams[("alice", 2)].examiners:
        c.add("exam_report", who, {"candidate": "alice", "degree": 2, "verdict": "pass", "reason": f"{URL}/verdict"}, after=HOUR)
    open_ballot(c, "adv-alice-2", "alice", "advancement", {"member": "alice", "degree": 2}, after=HOUR)
    decide(c, "adv-alice-2", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    return c.entries


def amendment_with_prior_pin():
    """An amendment of CONSTITUTION.md passes by two thirds: the pin changes, the pin it replaces is kept as
    the prior pin with its 30 days, and the amendment is recorded."""
    c = founded()
    open_ballot(c, "am-1", "ada", "amendment", {"path": "CONSTITUTION.md", "new_sha256": digest_of("amended constitution")}, after=DAY)
    decide(c, "am-1", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    return c.entries


def sanction_suspends():
    """A sanction ballot suspends a member (the accused is not an elector); the suspended member can still
    depart, and does."""
    c = founded()
    open_ballot(c, "s-1", "ada", "sanction", {"member": "carol", "measure": "suspend"}, after=DAY)
    decide(c, "s-1", {"hiram": "yes", "ada": "yes"})
    c.add("depart", "carol", {}, after=DAY)
    return c.entries


def witness_added_and_checkpoints():
    """A witness ballot adds a second witness, whose key signed the proof of possession in the subject; the
    new witness signs a checkpoint with the Merkle root, and the first one a checkpoint without it. Each
    states the digest of the state it covers."""
    c = founded()
    open_ballot(c, "w-1", "ada", "witness", witness_subject(c, "node2"), after=DAY)
    decide(c, "w-1", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    checkpoint(c, "node2", root=True, after=HOUR, anchor="ledger/anchors/000009.root.ots")
    checkpoint(c, "tyler", after=HOUR)
    return c.entries


def rekey_replaces_a_key():
    """A member replaces their key: the old key signs the entry, the new key signs the proof; the next entry
    of that member is signed by the new key."""
    c = founded()
    new = c.key("ada-2")
    c.add("rekey", "ada", {"key": new, "proof": c.sign("ada-2", rekey_message("ada", c.key("ada"), new))}, after=DAY)
    c.add("work", "ada", {"ref": URL, "kind": "essay"}, after=DAY, key_of="ada-2")
    return c.entries


def freeze_halt_stay_and_the_effective_clock():
    """A sanction ballot is opened; a custodian freezes a member's key, stays the ballot, halts the ledger,
    then withdraws the halt and the stay. The ballot was paused for three days, so a commit two days after its
    stored deadline is accepted, the frozen member reveals a vote, and the ballot closes three days later than
    its stored windows say."""
    c = lodge()
    open_ballot(c, "s-1", "ada", "sanction", {"member": "carol", "measure": "admonish"}, after=DAY)       # T0 + 1 d
    for who in ("ada", "hiram", "dan"):
        commit(c, "s-1", who, "yes")
    correct(c, "freeze_key", {"login": "ada"}, "key_compromised", after=DAY)                               # T0 + 2 d
    stay = correct(c, "stay", {"ballot": "s-1"}, "protocol_defect", after=DAY)                             # T0 + 3 d
    halt = correct(c, "halt", {}, "attack_in_progress", after=DAY)                                         # T0 + 4 d
    c.add("correction_withdraw", "warden", {"seq": halt}, after=DAY)                                       # T0 + 5 d
    c.add("correction_withdraw", "warden", {"seq": stay}, after=DAY)                                       # T0 + 6 d
    commit(c, "s-1", "eve", "no", after=4 * DAY)                                 # T0 + 10 d: stored commit_until is T0 + 8 d
    c.now = T0 + 11 * DAY + REVEAL_GAP + SEC
    for who, vote in (("ada", "yes"), ("hiram", "yes"), ("dan", "yes"), ("eve", "no")):
        reveal(c, "s-1", who, vote)
    c.now = T0 + 14 * DAY + REVEAL_GAP + SEC
    c.add("ballot_close", "tyler", {"id": "s-1"})
    return c.entries


def void_of_an_open_ballot():
    """A custodian posts a `void_ballot` on an open ballot; after its 14 days of notice it is applied: the
    ballot ends as `voided`, with no effect."""
    c = lodge()
    open_ballot(c, "s-1", "ada", "sanction", {"member": "carol", "measure": "suspend"}, after=DAY)
    commit(c, "s-1", "hiram", "yes")
    seq = correct(c, "void_ballot", {"id": "s-1"}, "protocol_defect", after=DAY)
    c.add("correction_apply", "warden", {"seq": seq}, after=14 * DAY)
    return c.entries


def undo_with_an_objection():
    """A passed admission is undone by a custodian's `undo_ballot`. One Master Builder objects during the
    notice (two would be needed to void it), so the objection is on the record and the undo is applied: the
    member's record becomes `voided`."""
    c = lodge()
    admit(c, "bob", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    seq = correct(c, "undo_ballot", {"id": "adm-bob"}, "identity_fraud", after=DAY)
    c.add("correction_object", "dan", {"seq": seq}, after=DAY)
    c.add("correction_apply", "warden", {"seq": seq}, after=13 * DAY)
    return c.entries


def custodian_removed_by_ballot():
    """The Master Builders remove a custodian key by a ballot of kind `custodian` (simple majority, the linked
    member not among the electors)."""
    c = lodge()
    open_ballot(c, "rm-warden", "ada", "custodian", {"remove": "warden"}, after=DAY)
    decide(c, "rm-warden", {"hiram": "yes", "ada": "yes", "carol": "no", "dan": "yes"})
    return c.entries


def key_recovery():
    """A custodian freezes a member's key; the member asks for a new one with the new key; two Master Builders
    co-sign; after 21 days the new key applies the recovery and signs the member's next entry."""
    c = lodge()
    correct(c, "freeze_key", {"login": "carol"}, "key_compromised", after=DAY)
    new = c.key("carol-2")
    c.add("rekey_recover", "carol", {"key": new, "proof": c.sign("carol-2", rekey_message("carol", c.key("carol"), new))},
          after=DAY, key_of="carol-2")
    c.add("rekey_cosign", "hiram", {"login": "carol"}, after=HOUR)
    c.add("rekey_cosign", "dan", {"login": "carol"}, after=HOUR)
    c.now = T0 + 23 * DAY
    c.add("rekey_recover_apply", "carol", {}, key_of="carol-2")
    c.add("work", "carol", {"ref": URL}, after=HOUR, key_of="carol-2")
    return c.entries


def frozen_elector_votes():
    """A custodian freezes the key of an elector of an open amendment ballot. The frozen elector still commits
    and reveals, so the freeze does not change the outcome: two thirds of the votes are not reached, and the
    amendment fails."""
    c = lodge()
    open_ballot(c, "am-1", "ada", "amendment", {"path": "CONSTITUTION.md", "new_sha256": digest_of("amended constitution")},
                after=DAY)
    correct(c, "freeze_key", {"login": "fay"}, "key_compromised", after=HOUR)
    decide(c, "am-1", {"hiram": "yes", "ada": "yes", "carol": "yes", "dan": "no", "fay": "no"})
    return c.entries


def note_on_the_moderation_ground():
    """A custodian records a moderation act done outside the ledger: a `note`, on the ground `moderation`. It
    is kept in the notes of the state, not among the corrections, and changes nothing else."""
    c = lodge()
    correct(c, "note", {"action": "hide", "target": "discussion/42", "rule": "ROOMS.md#5"}, "moderation", after=DAY)
    return c.entries


def recovery_without_a_custodian():
    """No custodian exists, so no key can be frozen first. A member asks for a new key with the new key; one
    Master Builder opposes, which is on the record and too few to void it; three Master Builders co-sign; the
    third co-signature freezes the old key and starts 30 days of notice; then the new key applies the recovery
    and signs the member's next entry."""
    c = founded(SEVEN)
    new = c.key("carol-2")
    c.add("rekey_recover", "carol", {"key": new, "proof": c.sign("carol-2", rekey_message("carol", c.key("carol"), new))},
          after=DAY, key_of="carol-2")
    c.add("rekey_oppose", "fay", {"login": "carol"}, after=HOUR)       # one opposition: two of the six others would void it
    for who in ("hiram", "dan", "eve"):
        c.add("rekey_cosign", who, {"login": "carol"}, after=HOUR)
    c.add("rekey_recover_apply", "carol", {}, after=30 * DAY, key_of="carol-2")
    c.add("work", "carol", {"ref": URL}, after=HOUR, key_of="carol-2")
    return c.entries


def sole_master_recovers_without_a_custodian():
    """One founder, no custodian: nobody exists to co-sign. The request starts its notice at once; the number of
    co-signers was lowered to the Master Builders who exist (none), so the notice is 45 days, not 30; the old
    key stays silent, and the new key applies the recovery."""
    c = founded(["hiram"])
    new = c.key("hiram-2")
    c.add("rekey_recover", "hiram", {"key": new, "proof": c.sign("hiram-2", rekey_message("hiram", c.key("hiram"), new))},
          after=DAY, key_of="hiram-2")
    c.add("rekey_recover_apply", "hiram", {}, after=45 * DAY, key_of="hiram-2")
    return c.entries


def dropped_recovery_after_a_freeze():
    """A custodian freezes a member's key and the member asks for a new one, but nobody co-signs for 30 days.
    After a freeze the drop starts the notice at once, 45 days, and the old key stays frozen meanwhile: one
    co-signature on day 50 is then enough, and the new key applies the recovery on day 77, 45 days after the drop."""
    c = lodge()
    correct(c, "freeze_key", {"login": "carol"}, "key_compromised", after=DAY)
    new = c.key("carol-2")
    c.add("rekey_recover", "carol", {"key": new, "proof": c.sign("carol-2", rekey_message("carol", c.key("carol"), new))},
          after=DAY, key_of="carol-2")
    c.now = T0 + 50 * DAY
    c.add("rekey_cosign", "hiram", {"login": "carol"})
    c.now = T0 + 77 * DAY
    c.add("rekey_recover_apply", "carol", {}, key_of="carol-2")
    return c.entries


def departure_reversed_by_the_recovery_that_follows():
    """A member asks for a new key; a day later the old key, in other hands, signs a departure; nobody co-signs
    and the request expires. The member asks again 90 days after the first request: it follows a recovery asked
    in time for this departure, so it is accepted, and once completed it reverses the departure."""
    c = founded()
    new = c.key("carol-2")
    c.add("rekey_recover", "carol", {"key": new, "proof": c.sign("carol-2", rekey_message("carol", c.key("carol"), new))},
          after=DAY, key_of="carol-2")
    c.add("depart", "carol", {}, after=DAY)
    c.now = T0 + 91 * DAY
    third = c.key("carol-3")
    c.add("rekey_recover", "carol", {"key": third, "proof": c.sign("carol-3", rekey_message("carol", c.key("carol"), third))},
          key_of="carol-3")
    for who in ("hiram", "ada"):
        c.add("rekey_cosign", who, {"login": "carol"}, after=HOUR)
    c.add("rekey_recover_apply", "carol", {}, after=45 * DAY, key_of="carol-3")
    c.add("work", "carol", {"ref": URL}, after=HOUR, key_of="carol-3")
    return c.entries

def ballot_lapses_then_closes_early():
    """An admission ballot in which one elector of three votes misses the quorum: it lapses, nobody is
    penalized and the petition stays. The sponsor opens another at once; all three vote, and it is closed as
    soon as the last of them has revealed, before the reveal window ends."""
    c = founded()
    c.add("invite", "hiram", {"login": "alice", "github_id": github_id("alice")})
    c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": digest_of("declaration")}, after=HOUR)
    c.add("vouch", "ada", {"candidate": "alice"}, after=HOUR)
    open_ballot(c, "adm-1", "hiram", "admission", {"candidate": "alice"}, after=HOUR)
    decide(c, "adm-1", {"hiram": "yes"})
    open_ballot(c, "adm-2", "hiram", "admission", {"candidate": "alice"}, after=HOUR)
    votes = {"hiram": "yes", "ada": "yes", "carol": "yes"}
    for who, vote in votes.items():
        commit(c, "adm-2", who, vote)
    c.now = c.state().ballots["adm-2"].commit_until + REVEAL_GAP          # the first second of the reveal window
    for who, vote in votes.items():
        reveal(c, "adm-2", who, vote)
    c.add("ballot_close", "tyler", {"id": "adm-2"}, after=SEC)
    return c.entries


def custodian_key_through_its_term():
    """A custodian key kept alive by a sign of life every 180 days signs through the last second of its term,
    2,555 days after the genesis."""
    c = lodge()
    for _ in range(14):
        c.add("custodian_alive", "warden", {}, after=180 * DAY)
    c.now = T0 + 2555 * DAY
    correct(c, "note", {"action": "other", "target": "end-of-term", "rule": "CUSTODIAN.md"}, "moderation")
    return c.entries


def claim_body(c: Ledger, name: str, member: str) -> dict:
    key, revoke = c.key(name), c.key(f"{name}-revoke")
    return {"name": name, "key": key, "revoke_key": revoke, "proof": c.sign(name, custodian_message(name, member, key)),
            "revoke_proof": c.sign(f"{name}-revoke", custodian_revoke_message(name, key, revoke))}


def founder_takes_up_the_office_again():
    """The custodian warden (hiram's) gives no sign of life for 180 days and its key lapses. hiram, a founder,
    claims the office again with a new custodian key and a new revoke key, both proved; after 30 days of notice
    nobody objected, hiram applies the claim, and the new custodian keeper records a note."""
    c = founded(custodians=(("warden", "hiram"),))
    c.add("custodian_claim", "hiram", claim_body(c, "keeper", "hiram"), after=181 * DAY)
    seq = len(c.entries) - 1
    c.add("custodian_claim_apply", "hiram", {"seq": seq}, after=30 * DAY)
    correct(c, "note", {"action": "other", "target": "office-resumed", "rule": "CUSTODIAN.md"}, "moderation",
            after=HOUR, by="keeper")
    return c.entries


def succession_after_the_last_master_departs():
    """The only Master Builder admits alice and bob, then departs. alice claims the succession; nobody of the
    3rd degree answers for 90 days; alice, of the highest degree present, invites carol, who petitions."""
    c = founded(["hiram"])
    for who in ("alice", "bob"):
        c.add("invite", "hiram", {"login": who, "github_id": github_id(who)}, after=HOUR)
        c.add("petition", who, {"key": c.key(who), "declaration_sha256": digest_of("declaration")}, after=HOUR)
        open_ballot(c, f"adm-{who}", "hiram", "admission", {"candidate": who}, after=HOUR)
        decide(c, f"adm-{who}", {"hiram": "yes"})
    c.add("depart", "hiram", {}, after=DAY)
    c.add("succession_claim", "alice", {}, after=DAY)
    c.add("invite", "alice", {"login": "carol", "github_id": github_id("carol")}, after=90 * DAY)
    c.add("petition", "carol", {"key": c.key("carol"), "declaration_sha256": digest_of("declaration")}, after=HOUR)
    return c.entries


def lapsed_ballot_re_run():
    """An amendment ballot of three Master Builders lapses with one vote. The same opener re-runs it at once,
    without waiting for the two who did not vote: its quorum counts one elector, and it passes with one vote."""
    c = founded()
    subject = {"path": "CONSTITUTION.md", "new_sha256": digest_of("amended constitution")}
    open_ballot(c, "am-1", "ada", "amendment", subject, after=DAY)
    decide(c, "am-1", {"ada": "yes"})
    c.add("ballot_open", "ada", {"id": "am-2", "kind": "amendment", "subject": subject, "rerun": "am-1"}, after=HOUR)
    decide(c, "am-2", {"ada": "yes"})
    return c.entries


def exam_times_out_without_penalty():
    """An examiner never reports: 60 days after it opened the exam has timed out, with no penalty. The
    candidate opens a new one at once, and the silent examiner is left out of its pool, which seats everyone
    any rung holds: the six other Master Builders, the sponsors among them, all six to be drawn."""
    c = founded(SEVEN)
    admit(c, "alice", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    c.now += 30 * DAY
    rnd = drand_round(c.now) + BEACON_DELAY_ROUNDS
    c.add("exam_open", "alice", {"candidate": "alice", "degree": 2, "work_ref": URL, "beacon_round": rnd})
    opened = c.now
    c.now = drand_time(rnd)
    c.add("exam_draw", "tyler", {"candidate": "alice", "degree": 2, "beacon": beacon(rnd)})
    first, _ = c.state().exams[("alice", 2)].examiners
    c.add("exam_report", first, {"candidate": "alice", "degree": 2, "verdict": "pass"}, after=HOUR)
    c.now = opened + 60 * DAY + SEC
    c.add("exam_open", "alice", {"candidate": "alice", "degree": 2, "work_ref": URL,
                                 "beacon_round": drand_round(c.now) + BEACON_DELAY_ROUNDS})
    return c.entries


def founding_phase_second_sponsor_waived():
    """Two Master Builders; the second never sponsors. 30 days after the petition the inviter alone opens the
    admission ballot, and both vote."""
    c = founded(["hiram", "ada"])
    c.add("invite", "hiram", {"login": "alice", "github_id": github_id("alice")})
    c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": digest_of("declaration")}, after=HOUR)
    open_ballot(c, "adm-alice", "hiram", "admission", {"candidate": "alice"}, after=30 * DAY)
    decide(c, "adm-alice", {"hiram": "yes", "ada": "yes"})
    return c.entries


def amendment_removes_a_pin():
    """An amendment pins a new path; a second one removes that pin (new_sha256 of 64 zeros); a third pins a new
    protocol core, and the protocol epoch becomes 1."""
    c = founded()
    open_ballot(c, "am-1", "ada", "amendment", {"path": "docs/page.md", "new_sha256": digest_of("page")}, after=DAY)
    decide(c, "am-1", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    open_ballot(c, "am-2", "ada", "amendment", {"path": "docs/page.md", "new_sha256": "0" * 64}, after=HOUR)
    decide(c, "am-2", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    open_ballot(c, "am-3", "ada", "amendment", {"path": "@protocol", "new_sha256": digest_of("core 2")}, after=HOUR)
    decide(c, "am-3", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    return c.entries


def case_twin_fails_at_its_close():
    """Two amendments open on paths that differ only by case, neither pinned yet; the first to close pins its
    path, and the second fails at its close (M4 holds at the close as at the opening)."""
    c = founded()
    open_ballot(c, "am-1", "ada", "amendment", {"path": "docs/x.md", "new_sha256": digest_of("x")}, after=DAY)
    open_ballot(c, "am-2", "hiram", "amendment", {"path": "Docs/x.md", "new_sha256": digest_of("X")})
    for bid in ("am-1", "am-2"):
        for who in ("hiram", "ada", "carol"):
            commit(c, bid, who, "yes")
    b = c.state().ballots["am-2"]
    c.now = b.commit_until + REVEAL_GAP + SEC
    for bid in ("am-1", "am-2"):
        for who in ("hiram", "ada", "carol"):
            reveal(c, bid, who, "yes")
    c.now = b.reveal_until + SEC
    c.add("ballot_close", "tyler", {"id": "am-1"})
    c.add("ballot_close", "tyler", {"id": "am-2"})
    assert c.state().ballots["am-2"].result == "failed"
    return c.entries


# ---------------------------------------------------------------- invalid ----

def bad_prev():
    """The second entry names another hash as `prev`."""
    c = founded()
    c.now += DAY
    e = c.draft("work", "ada", {"ref": URL}) | {"prev": digest_of("another history")}
    return c.entries + [e | {"sig": c.sign("ada", signed_payload(e))}]


def time_goes_backwards():
    """An entry dated one second before the entry it follows."""
    c = founded()
    c.add("work", "ada", {"ref": URL}, after=DAY)
    c.add("work", "carol", {"ref": URL}, after=-SEC)
    return c.entries


def wrong_signer():
    """An entry of one member signed, validly, by the key of another."""
    c = founded()
    c.add("work", "ada", {"ref": URL}, after=DAY, key_of="carol")
    return c.entries


def signature_rewrapped():
    """A valid signature whose armor is wrapped at 76 columns instead of 70: the same bytes, another spelling."""
    c = founded()
    e = c.add("work", "ada", {"ref": URL}, after=DAY)
    return c.entries[:-1] + [e | {"sig": armor(dearmor(e["sig"]), width=76)}]


def signature_s_plus_l():
    """A valid signature with the group order added to its scalar S: the classic malleation."""
    c = founded()
    e = c.add("work", "ada", {"ref": URL}, after=DAY)
    raw = dearmor(e["sig"])
    scalar = int.from_bytes(raw[-32:], "little") + L
    return c.entries[:-1] + [e | {"sig": armor(raw[:-32] + scalar.to_bytes(32, "little"))}]


def float_in_body():
    """The file of an entry holds a number with a fraction (`"github_id": 1.5`). Given as the text of the
    file: the strict parser refuses it before any rule is asked."""
    c = founded()
    c.now += DAY
    e = c.draft("invite", "ada", {"login": "zoe", "github_id": 15})
    e["sig"] = c.sign("ada", signed_payload(e))
    text = json.dumps(e)
    assert text.count('"github_id": 15') == 1
    return c.entries + [text.replace('"github_id": 15', '"github_id": 1.5')]


def unknown_field():
    """A body with a field its type does not have."""
    c = founded()
    c.add("work", "ada", {"ref": URL, "extra": "x"}, after=DAY)
    return c.entries


def integer_out_of_range():
    """The file of an entry holds the integer 2^53, one more than the largest the protocol carries."""
    c = founded()
    c.now += DAY
    e = c.draft("invite", "ada", {"login": "zoe", "github_id": 15})
    e["sig"] = c.sign("ada", signed_payload(e))
    text = json.dumps(e)
    assert text.count('"github_id": 15') == 1
    return c.entries + [text.replace('"github_id": 15', f'"github_id": {2 ** 53}')]


def oversized_entry():
    """An entry, validly signed, whose canonical encoding is larger than 8,192 bytes."""
    c = founded()
    c.add("work", "ada", {"ref": "https://example.org/" + "a" * 8200}, after=DAY)
    return c.entries


def duplicate_key():
    """The file of an entry names `seq` twice. Given as the text of the file."""
    c = founded()
    e = c.add("work", "ada", {"ref": URL}, after=DAY)
    return c.entries[:-1] + ['{"seq": 1, ' + json.dumps(e)[1:]]


def petition_without_invitation():
    """A petition by a login no Master Builder invited: no key outside the state signs anything."""
    c = founded()
    c.add("petition", "zoe", {"key": c.key("zoe"), "declaration_sha256": digest_of("declaration")}, after=DAY)
    return c.entries


def second_reveal():
    """An elector reveals the same vote twice."""
    c = founded()
    open_ballot(c, "am-1", "ada", "amendment", {"path": "CONSTITUTION.md", "new_sha256": digest_of("amended constitution")}, after=DAY)
    commit(c, "am-1", "hiram", "yes")
    c.now = c.state().ballots["am-1"].commit_until + REVEAL_GAP + SEC
    reveal(c, "am-1", "hiram", "yes")
    reveal(c, "am-1", "hiram", "yes", after=HOUR)
    return c.entries


def frozen_member_acts():
    """A member whose key a custodian froze signs a `work` entry."""
    c = lodge()
    correct(c, "freeze_key", {"login": "ada"}, "key_compromised", after=DAY)
    c.add("work", "ada", {"ref": URL}, after=HOUR)
    return c.entries


def entry_during_a_halt():
    """A member signs a `work` entry while the ledger is halted."""
    c = lodge()
    correct(c, "halt", {}, "attack_in_progress", after=DAY)
    c.add("work", "ada", {"ref": URL}, after=HOUR)
    return c.entries


def correction_by_a_lapsed_key():
    """A custodian key that gave no sign of life for more than 180 days signs a correction."""
    c = lodge()
    correct(c, "halt", {}, "attack_in_progress", after=180 * DAY + SEC)
    return c.entries


def frozen_key_signs_during_a_dropped_recovery():
    """A custodian freezes a member's key; the member asks for a new one and nobody co-signs. On day 33 the freeze
    has run its time, but the request dropped on day 32 and its notice runs: the old key is still frozen."""
    c = lodge()
    correct(c, "freeze_key", {"login": "carol"}, "key_compromised", after=DAY)
    new = c.key("carol-2")
    c.add("rekey_recover", "carol", {"key": new, "proof": c.sign("carol-2", rekey_message("carol", c.key("carol"), new))},
          after=DAY, key_of="carol-2")
    c.now = T0 + 33 * DAY
    c.add("work", "carol", {"ref": URL})
    return c.entries


def short_ballot_re_run():
    """An amendment ballot that gave 2 days to commit lapses with the opener's vote alone; its re-run is refused:
    only a ballot that gave at least 7 days to commit is re-run."""
    c = founded()
    subject = {"path": "CONSTITUTION.md", "new_sha256": digest_of("amended constitution")}
    c.add("ballot_open", "ada", {"id": "am-1", "kind": "amendment", "subject": subject, "commit_days": 2,
                                 "reveal_days": 1}, after=DAY)
    decide(c, "am-1", {"ada": "yes"})
    c.add("ballot_open", "ada", {"id": "am-2", "kind": "amendment", "subject": subject, "rerun": "am-1"}, after=HOUR)
    return c.entries

def apply_before_the_notice_ends():
    """A noticed correction is applied one second before its 14 days of notice are over."""
    c = lodge()
    open_ballot(c, "s-1", "ada", "sanction", {"member": "carol", "measure": "suspend"}, after=DAY)
    seq = correct(c, "void_ballot", {"id": "s-1"}, "protocol_defect", after=DAY)
    c.add("correction_apply", "warden", {"seq": seq}, after=14 * DAY - SEC)
    return c.entries


def room_hold_again_within_ninety_days():
    """A custodian holds a member out of the rooms again 15 days after the first hold began: the same login is
    held again only 90 days after the previous hold began."""
    c = lodge()
    correct(c, "hold_room", {"login": "carol"}, "protocol_defect", after=DAY)
    correct(c, "hold_room", {"login": "carol"}, "protocol_defect", after=15 * DAY)
    return c.entries


def recovery_long_after_a_departure():
    """A member departs, and a recovery of the key is asked 30 days and one second later: a departure is
    reversed only by a recovery asked before it or within 30 days of it."""
    c = founded()
    c.add("depart", "carol", {}, after=DAY)
    old, new = c.key("carol"), c.key("carol-new")
    c.add("rekey_recover", "carol", {"key": new, "proof": c.sign("carol-new", ledger.rekey_message("carol", old, new))},
          after=30 * DAY + SEC, key_of="carol-new")
    return c.entries


def undo_after_a_conflicting_change():
    """An admission is to be undone, but the member departed during the notice: what the ballot set no longer
    stands, so the undo is refused and nothing is undone."""
    c = lodge()
    admit(c, "bob", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    seq = correct(c, "undo_ballot", {"id": "adm-bob"}, "identity_fraud", after=DAY)
    c.add("depart", "bob", {}, after=DAY)
    c.add("correction_apply", "warden", {"seq": seq}, after=13 * DAY)
    return c.entries


def checkpoint_with_a_wrong_state_digest():
    """A witness checkpoint that names the right entry and the right hash, and another state digest."""
    c = founded()
    c.add("work", "ada", {"ref": URL}, after=DAY)
    checkpoint(c, "tyler", after=HOUR, state_sha256=digest_of("another state"))
    return c.entries


def witness_ballot_with_a_bad_proof():
    """A witness ballot proposes a key whose proof of possession was signed by another key: nobody registers a
    witness key they do not hold."""
    c = founded()
    open_ballot(c, "w-1", "ada", "witness", witness_subject(c, "node2", signed_by="ada"), after=DAY)
    return c.entries


def amendment_opened_by_an_apprentice():
    """A member of the 1st degree opens an amendment ballot: only Master Builders may."""
    c = founded()
    admit(c, "alice", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    open_ballot(c, "am-1", "alice", "amendment", {"path": "CONSTITUTION.md", "new_sha256": digest_of("amended constitution")},
                after=DAY)
    return c.entries


def fourth_open_ballot():
    """A Master Builder with three ballots open opens a fourth."""
    c = founded()
    for i in range(4):
        open_ballot(c, f"am-{i}", "ada", "amendment", {"path": f"docs/page-{i}.md", "new_sha256": digest_of(f"page {i}")},
                    after=HOUR)
    return c.entries


def checkpoint_without_a_new_entry():
    """A witness posts a second checkpoint, an hour after its first, with no entry in between."""
    c = founded()
    c.add("work", "ada", {"ref": URL}, after=DAY)
    checkpoint(c, "tyler", after=HOUR)
    checkpoint(c, "tyler", after=HOUR)
    return c.entries


def twenty_first_entry_in_a_day():
    """Seven Master Builders open three amendment ballots each in one UTC day, and the witness posts a
    checkpoint after each, an hour apart: its twenty-first entry of that day is refused."""
    c = founded(SEVEN)
    for i in range(21):
        who = SEVEN[i % 7]
        open_ballot(c, f"am-{i}", who, "amendment", {"path": f"docs/page-{i}.md", "new_sha256": digest_of(f"page {i}")},
                    after=HOUR - 60 * SEC)
        checkpoint(c, "tyler", after=60 * SEC)
    return c.entries


def note_on_another_ground():
    """A note stated on a ground other than `moderation`."""
    c = lodge()
    correct(c, "note", {"action": "hide", "target": "discussion/42", "rule": "ROOMS.md#5"}, "protocol_defect", after=DAY)
    return c.entries


def correction_after_the_term():
    """A custodian key that never fell silent signs one second after its term of 2,555 days."""
    c = lodge()
    for _ in range(14):
        c.add("custodian_alive", "warden", {}, after=180 * DAY)
    c.now = T0 + 2555 * DAY + SEC
    correct(c, "note", {"action": "other", "target": "end-of-term", "rule": "CUSTODIAN.md"}, "moderation")
    return c.entries


def claim_applied_before_its_notice():
    """A founder claims the Custodian office while no custodian exists, and applies the claim one second before
    its 30 days of notice are over."""
    c = founded(["hiram"])
    c.add("custodian_claim", "hiram", claim_body(c, "keeper", "hiram"), after=DAY)
    seq = len(c.entries) - 1
    c.add("custodian_claim_apply", "hiram", {"seq": seq}, after=30 * DAY - SEC)
    return c.entries


def sanction_on_a_master_by_one_elector():
    """Two Master Builders: one opens a ballot to expel the other, whose only elector would be the opener."""
    c = founded(["hiram", "ada"])
    open_ballot(c, "s-1", "hiram", "sanction", {"member": "ada", "measure": "expel"}, after=DAY)
    return c.entries


def successor_invites_before_ninety_days():
    """A member of the 1st degree, whose only Master Builder departed, claims the succession and invites one
    second before 90 days have passed."""
    c = founded(["hiram"])
    c.add("invite", "hiram", {"login": "alice", "github_id": github_id("alice")}, after=HOUR)
    c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": digest_of("declaration")}, after=HOUR)
    open_ballot(c, "adm-alice", "hiram", "admission", {"candidate": "alice"}, after=HOUR)
    decide(c, "adm-alice", {"hiram": "yes"})
    c.add("depart", "hiram", {}, after=DAY)
    c.add("succession_claim", "alice", {}, after=DAY)
    c.add("invite", "alice", {"login": "carol", "github_id": github_id("carol")}, after=90 * DAY - SEC)
    return c.entries


def checkpoint_without_a_state_version():
    """A witness checkpoint that does not state the version of the state document its digest is of."""
    c = founded()
    c.add("work", "ada", {"ref": URL}, after=DAY)
    st = c.state()
    c.add("witness", "tyler", {"upto_seq": st.seq, "head": st.head, "state_sha256": st.digest()}, after=HOUR)
    return c.entries


def exam_drawn_after_its_lot_lapsed():
    """The lot of an exam is drawn one second more than 7 days after its beacon round."""
    c = founded(SEVEN)
    admit(c, "alice", {"hiram": "yes", "ada": "yes", "carol": "yes"})
    c.now += 30 * DAY
    rnd = drand_round(c.now) + BEACON_DELAY_ROUNDS
    c.add("exam_open", "alice", {"candidate": "alice", "degree": 2, "work_ref": URL, "beacon_round": rnd})
    c.now = drand_time(rnd) + 7 * DAY + SEC
    c.add("exam_draw", "tyler", {"candidate": "alice", "degree": 2, "beacon": beacon(rnd)})
    return c.entries


def second_re_run():
    """A ballot that re-ran a lapsed one lapses too, and is re-run again."""
    c = founded()
    subject = {"path": "CONSTITUTION.md", "new_sha256": digest_of("amended constitution")}
    open_ballot(c, "am-1", "ada", "amendment", subject, after=DAY)
    decide(c, "am-1", {"ada": "yes"})
    c.add("ballot_open", "ada", {"id": "am-2", "kind": "amendment", "subject": subject, "rerun": "am-1"}, after=HOUR)
    decide(c, "am-2", {})
    c.add("ballot_open", "ada", {"id": "am-3", "kind": "amendment", "subject": subject, "rerun": "am-2"}, after=HOUR)
    return c.entries


def void_posted_after_the_reveal_opened():
    """A custodian posts a `void_ballot` in the first second of the ballot's reveal window: a ballot is voided
    only by a correction posted before any vote can be revealed."""
    c = lodge()
    open_ballot(c, "s-1", "ada", "sanction", {"member": "carol", "measure": "suspend"}, after=DAY)
    commit(c, "s-1", "hiram", "yes")
    c.now = c.state().ballots["s-1"].commit_until + REVEAL_GAP
    correct(c, "void_ballot", {"id": "s-1"}, "protocol_defect")
    return c.entries


VALID = (founding_with_custodians, admission_passes, admission_blackballed, exam_and_advancement,
         amendment_with_prior_pin, sanction_suspends, witness_added_and_checkpoints, rekey_replaces_a_key,
         freeze_halt_stay_and_the_effective_clock, void_of_an_open_ballot, undo_with_an_objection,
         custodian_removed_by_ballot, key_recovery, frozen_elector_votes, note_on_the_moderation_ground,
         recovery_without_a_custodian, sole_master_recovers_without_a_custodian, ballot_lapses_then_closes_early,
         custodian_key_through_its_term, founder_takes_up_the_office_again, succession_after_the_last_master_departs,
         lapsed_ballot_re_run, exam_times_out_without_penalty, founding_phase_second_sponsor_waived,
         amendment_removes_a_pin, case_twin_fails_at_its_close, dropped_recovery_after_a_freeze,
         departure_reversed_by_the_recovery_that_follows)
# Each invalid vector with the start of the refusal it must meet, so that none passes for another reason.
INVALID = (
    (bad_prev, "prev does not match head"), (time_goes_backwards, "time goes backwards"),
    (wrong_signer, "bad signature"), (signature_rewrapped, "bad signature"), (signature_s_plus_l, "bad signature"),
    (float_in_body, "0000/000001.json is not strict JSON: a number with a fraction or an exponent is not allowed"),
    (unknown_field, "malformed work entry: unknown field 'extra'"),
    (integer_out_of_range, "0000/000001.json is not strict JSON: an integer is outside"),
    (oversized_entry, "entry exceeds 8192 bytes"),
    (duplicate_key, "0000/000001.json is not strict JSON: duplicate key 'seq'"),
    (petition_without_invitation, "no live invitation for 'zoe'"), (second_reveal, "already revealed"),
    (frozen_member_acts, "the key of ada is frozen until 2027-02-01T00:00:00Z (correction 1)"),
    (entry_during_a_halt, "the ledger is halted until 2027-01-16T00:00:00Z (correction 1)"),
    (correction_by_a_lapsed_key, "the custodian key of warden is lapsed and signs nothing"),
    (apply_before_the_notice_ends, "correction 2 is under notice until 2027-01-17T00:00:00Z"),
    (undo_after_a_conflicting_change, "the undo of ballot adm-bob no longer applies: member.status is 'departed', not 'active'"),
    (checkpoint_with_a_wrong_state_digest, "witness state digest mismatch"),
    (witness_ballot_with_a_bad_proof, "bad witness proof: the proposed key must sign the witness message"),
    (amendment_opened_by_an_apprentice, "only Master Builders may open an amendment ballot"),
    (fourth_open_ballot, "ada has 3 ballots open"),
    (checkpoint_without_a_new_entry, "no entry but checkpoints since the last checkpoint of tyler"),
    (twenty_first_entry_in_a_day, "tyler already has 20 entries dated 2027-01-01"),
    (note_on_another_ground, "note takes one ground only: moderation"),
    (room_hold_again_within_ninety_days, "carol was held less than 90 days ago"),
    (recovery_long_after_a_departure, "carol departed more than 30 days ago"),
    (correction_after_the_term, "the custodian key of warden is lapsed and signs nothing"),
    (void_posted_after_the_reveal_opened, "the reveal window of ballot s-1 opened at 2027-01-09T06:15:00Z"),
    (claim_applied_before_its_notice, "the claim of entry 1 is under notice until"),
    (sanction_on_a_master_by_one_elector, "a sanction on a Master Builder is never decided by a single elector"),
    (successor_invites_before_ninety_days, "only Master Builders may invite"),
    (checkpoint_without_a_state_version, "malformed witness entry: missing field 'state_version'"),
    (exam_drawn_after_its_lot_lapsed, "the lot of this exam was not drawn within 7 days of its beacon round"),
    (second_re_run, "ballot am-2 re-ran ballot am-1: a ballot is re-run once"),
    (frozen_key_signs_during_a_dropped_recovery, "the key of carol stays frozen while its recovery is pending"),
    (short_ballot_re_run, "ballot am-1 gave less than 7 days to commit and is never re-run"),
)


def describe(fn) -> str:
    return " ".join(fn.__doc__.split())


def vectors() -> dict[str, dict]:
    """Every vector, by file name. Deterministic: the same on every machine and on every run."""
    assert canon.canon_status(DEGREES) == "ok", f"canon/history/{DEGREES}.toml is the degree table the vectors pin"
    out = {}
    for fn in VALID:
        entries = fn()
        expect = outcome(entries)
        assert expect["valid"] and expect["seq"] == len(entries) - 1, (fn.__name__, expect)
        out[f"valid-{fn.__name__.replace('_', '-')}.json"] = {"name": fn.__name__, "description": describe(fn),
                                                              "entries": entries, "expect": expect}
    for fn, refusal in INVALID:
        entries = fn()
        expect = outcome(entries)
        assert not expect["valid"] and expect["seq"] == len(entries) - 1 and expect["error"].startswith(refusal), \
            (fn.__name__, expect)
        assert outcome(entries[:-1])["valid"], fn.__name__          # everything before the refused entry is lawful
        out[f"invalid-{fn.__name__.replace('_', '-')}.json"] = {"name": fn.__name__, "description": describe(fn),
                                                                "entries": entries, "expect": expect}
    return out


def text(vector: dict) -> str:
    """The bytes of a vector file."""
    return json.dumps(vector, indent=1, ensure_ascii=True) + "\n"


def main() -> int:
    made = vectors()
    VECTORS.mkdir(exist_ok=True)
    for old in VECTORS.glob("*.json"):
        if old.name not in made:
            old.unlink()
    for name, vector in made.items():
        (VECTORS / name).write_text(text(vector), encoding="ascii")
    print(f"{len(made)} vectors in {VECTORS}: {len(VALID)} valid, {len(INVALID)} invalid, "
          f"{sum(len(v['entries']) for v in made.values())} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
