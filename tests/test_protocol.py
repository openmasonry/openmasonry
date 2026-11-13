"""Protocol tests: a full initiation, tampering, decisions and the lot.

Run: PYTHONPATH=src python3 -m unittest -v
"""
from __future__ import annotations

import copy
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openmasonry import canon
from openmasonry.crypto import merkle_root, sign
from openmasonry.govern import genesis_pins, read_manifest

DECL = canon.declaration_digest()
from openmasonry.ledger import (BEACON_DELAY_ROUNDS, GENESIS_PINS, PROTOCOL_PIN, STATE_VERSION, Invalid, commitment, custodian_message,
                                custodian_revoke_message, decide, drand_round, entry_hash, entry_path, founder_message, quorum,
                                replay, signed_payload, witness_message)
from openmasonry.lot import draw

T0 = datetime(2027, 1, 1, tzinfo=timezone.utc)


def entry_file(directory: Path, seq: int) -> Path:
    """The file of entry `seq` in a ledger directory (`ledger.entry_path`), its shard directory made: to write."""
    path = entry_path(directory, seq)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def canon_digest() -> str:
    """sha256 of the degree table of the working tree: what a genesis founded on it pins."""
    return hashlib.sha256((canon.CANON / "degrees.toml").read_bytes()).hexdigest()


def salt_of(login: str) -> str:
    """A commit salt in the form the protocol requires (32 lowercase hex characters), fixed per login."""
    return hashlib.sha256(login.encode()).hexdigest()[:32]


class Chain:
    """Builds a signed chain in memory, with a fake clock."""

    def __init__(self, tmp: Path):
        self.tmp, self.keys, self.entries, self.now = tmp, {}, [], T0

    def key(self, login: str) -> str:
        if login not in self.keys:
            path = self.tmp / login
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", login, "-f", str(path)], check=True)
            pub = path.with_suffix(".pub").read_text().split()
            self.keys[login] = (path, f"{pub[0]} {pub[1]}")
        return self.keys[login][1]

    def add(self, typ: str, actor: str, body: dict, days: float = 0, key_of: str | None = None) -> dict:
        self.now += timedelta(days=days)
        prev = entry_hash(self.entries[-1]) if self.entries else canon.ZERO_HASH
        e = {"seq": len(self.entries), "prev": prev, "time": self.now.isoformat().replace("+00:00", "Z"),
             "type": typ, "actor": actor, "body": body}
        self.key(key_of or actor)
        e["sig"] = sign(signed_payload(e), self.keys[key_of or actor][0])
        self.entries.append(e)
        return e

    def exam(self, cand: str, degree: int, days: float = 0, verdict: str = "pass"):
        rnd = drand_round(self.now + timedelta(days=days)) + BEACON_DELAY_ROUNDS
        self.add("exam_open", cand, {"candidate": cand, "degree": degree, "work_ref": "https://example.org/work", "beacon_round": rnd}, days=days)
        self.add("exam_draw", cand, {"candidate": cand, "degree": degree, "beacon": f"{rnd:064x}"}, days=0.34)
        ex = self.state().exams[(cand, degree)]
        for x in ex.examiners:
            self.add("exam_report", x, {"candidate": cand, "degree": degree, "verdict": verdict})
        return ex

    def prove(self, name: str, message: bytes) -> str:
        """The signature of the key named `name` over a proof message (never an entry)."""
        self.key(name)
        return sign(message, self.keys[name][0])

    def state(self):
        return replay(self.entries)

    def vote(self, bid: str, votes: dict[str, str]):
        for login in votes:
            self.add("ballot_commit", login, {"id": bid, "commitment": commitment(bid, login, votes[login], salt_of(login))})
        self.now += timedelta(days=7.3)          # past commit_until + REVEAL_GAP
        for login, v in votes.items():
            self.add("ballot_reveal", login, {"id": bid, "vote": v, "salt": salt_of(login)}, days=0.01)
        self.add("ballot_close", next(iter(votes)), {"id": bid}, days=3)


FOUNDERS = ["hiram", "ada", "carol"]


def gid(login: str) -> int:
    """The numeric GitHub user id of a test login: a positive integer, fixed per login whatever its case."""
    return int(hashlib.sha256(login.lower().encode()).hexdigest()[:8], 16) + 1


def invite(c: "Chain", who: str, by: str = "hiram", days: float = 0) -> dict:
    """`by` (a Master Builder) invites `who`, and so becomes the first sponsor."""
    return c.add("invite", by, {"login": who, "github_id": gid(who)}, days=days)


def petition(c: "Chain", who: str, by: str = "hiram", days: float = 0, key_of: str | None = None) -> dict:
    """An admission as far as the petition: after `days`, `by` invites `who`, who petitions at once."""
    invite(c, who, by, days=days)
    return c.add("petition", who, {"key": c.key(key_of or who), "declaration_sha256": DECL}, key_of=key_of)


def custodian_record(c: "Chain", name: str, member: str) -> dict:
    """A lawful custodian record of a genesis: the key named `name`, the revoke key named `name`-revoke,
    and the two proofs of possession, each signed by its own key."""
    key, revoke = c.key(name), c.key(f"{name}-revoke")
    return {"name": name, "key": key, "revoke_key": revoke, "member": member,
            "proof": c.prove(name, custodian_message(name, member, key)),
            "revoke_proof": c.prove(f"{name}-revoke", custodian_revoke_message(name, key, revoke))}


def founder_record(c: "Chain", login: str, first: bool = False) -> dict:
    """A lawful founder record of a genesis: the first founder signs the entry itself, every other founder
    proves possession of the key."""
    key = c.key(login)
    return {"login": login, "key": key, "github_id": gid(login)} | (
        {} if first else {"proof": c.prove(login, founder_message(login, gid(login), key))})


def witness_record(c: "Chain", name: str) -> dict:
    """A lawful witness record of a genesis: the witness key proves possession."""
    return {"name": name, "key": c.key(name), "proof": c.prove(name, witness_message(name, c.key(name)))}


def witness_subject(c: "Chain", name: str, key_of: str | None = None) -> dict:
    """The subject of a ballot that adds the witness `name`, with the proof of its key (the key named `key_of`)."""
    key = c.key(key_of or name)
    return {"action": "add", "name": name, "key": key, "proof": c.prove(key_of or name, witness_message(name, key))}


def genesis_body(c: Chain, founders=FOUNDERS, witnesses=(), pins=None, custodians=(), **over) -> dict:
    """A lawful genesis body for the working tree's governed files. `pins` replaces single pins
    (path -> sha256); `custodians` names custodians, each a name (linked to the first founder) or a pair
    (name, member); `over` replaces or adds whole fields."""
    named = [custodian_record(c, *(x if isinstance(x, tuple) else (x, founders[0]))) for x in custodians]
    body = {
        "name": "OpenMasonry Test Lodge",
        "pins": {**genesis_pins(), **(pins or {})},
        "declaration_sha256": DECL,
        "founders": [founder_record(c, f, first=i == 0) for i, f in enumerate(founders)],
        "witnesses": [witness_record(c, w) for w in witnesses],
        "custodians": named,
        "custodian_threshold": 1 if named else 0,
    }
    return {**body, **over}


def checkpoint(st, **extra) -> dict:
    """The body of a lawful `witness` entry on top of the state `st`: it covers every entry so far, and states
    the digest of that state. `extra` adds `root` or `anchor`, or replaces a field."""
    return {"upto_seq": st.seq, "head": st.head, "state_sha256": st.digest(), "state_version": STATE_VERSION} | extra


def copy_governed(root: Path) -> Path:
    """A scratch tree at `root` holding what genesis pins: the files of the `@protocol` manifest, the
    governed documents and the archived copy of the degree table (`canon/history/<sha256>.toml`), copied from
    this repository. Nothing else of the repository is in it."""
    for rel in (*read_manifest(canon.ROOT), *(p for p in GENESIS_PINS if p != PROTOCOL_PIN),
                f"canon/history/{canon_digest()}.toml"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(canon.ROOT / rel, root / rel)
    return root


def founded(tmp: Path) -> Chain:
    c = Chain(tmp)
    c.add("genesis", FOUNDERS[0], genesis_body(c))
    return c


def initiate(c: Chain, who: str) -> None:
    """A whole admission: hiram invites (the first sponsor), `who` petitions, ada is the second sponsor."""
    petition(c, who)
    c.add("vouch", "ada", {"candidate": who})
    c.add("ballot_open", "hiram", {"id": f"adm-{who}", "kind": "admission", "subject": {"candidate": who}})
    c.vote(f"adm-{who}", {f: "yes" for f in FOUNDERS})


class Initiation(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.c = founded(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def test_founders_abdicate_to_master_builder(self):
        st = self.c.state()
        self.assertEqual({m.degree for m in st.members.values()}, {3})
        self.assertTrue(st.founding_phase(st.time))

    def test_full_admission_and_advancement(self):
        initiate(self.c, "alice")
        st = self.c.state()
        self.assertEqual(st.members["alice"].degree, 1)
        self.assertEqual(st.members["alice"].sponsors, ("hiram", "ada"))

        # Too early: the 30-day waiting period for the 2nd degree is not complete.
        rnd = drand_round(self.c.now) + BEACON_DELAY_ROUNDS
        self.c.add("exam_open", "alice", {"candidate": "alice", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd})
        with self.assertRaisesRegex(Invalid, "waiting period"):
            self.c.state()
        self.c.entries.pop()

        exam = self.c.exam("alice", 2, days=31)
        self.assertEqual(len(exam.examiners), 2)
        self.assertNotIn("alice", exam.examiners)
        self.c.add("ballot_open", "carol", {"id": "adv-alice-2", "kind": "advancement",
                                             "subject": {"member": "alice", "degree": 2}})
        self.c.vote("adv-alice-2", {f: "yes" for f in FOUNDERS})
        self.assertEqual(self.c.state().members["alice"].degree, 2)

    def test_one_fifth_black_balls_reject(self):
        petition(self.c, "mallory")
        self.c.add("vouch", "ada", {"candidate": "mallory"})
        self.c.add("ballot_open", "ada", {"id": "adm-m", "kind": "admission", "subject": {"candidate": "mallory"}})
        self.c.vote("adm-m", {"hiram": "yes", "ada": "yes", "carol": "no"})
        st = self.c.state()
        self.assertNotIn("mallory", st.members)
        self.assertEqual(st.ballots["adm-m"].result, "failed")

    def test_cannot_skip_degrees_or_self_examine(self):
        initiate(self.c, "bob")
        with self.assertRaisesRegex(Invalid, "next degree"):
            self.c.exam("bob", 3, days=400)

    def test_beacon_round_must_be_in_the_future(self):
        initiate(self.c, "erin")
        self.c.add("exam_open", "erin", {"candidate": "erin", "degree": 2, "work_ref": "https://example.org/work",
                                          "beacon_round": drand_round(self.c.now)}, days=31)
        with self.assertRaisesRegex(Invalid, "beacon_round"):
            self.c.state()

    def test_draw_waits_for_the_round_and_exams_cannot_be_reshuffled(self):
        initiate(self.c, "fay")
        rnd = drand_round(self.c.now + timedelta(days=31)) + BEACON_DELAY_ROUNDS
        self.c.add("exam_open", "fay", {"candidate": "fay", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd}, days=31)
        self.c.add("exam_draw", "fay", {"candidate": "fay", "degree": 2, "beacon": "ab" * 32}, days=0.01)
        with self.assertRaisesRegex(Invalid, "not happened"):
            self.c.state()
        self.c.entries.pop()
        self.c.add("exam_open", "fay", {"candidate": "fay", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd + 1})
        with self.assertRaisesRegex(Invalid, "exam for this degree exists"):
            self.c.state()

    def test_sponsor_budget_counts_pending_petitions(self):
        for i in range(4):
            petition(self.c, f"cand{i}", by="ada")
            self.c.add("vouch", "hiram", {"candidate": f"cand{i}"})
        petition(self.c, "cand4", by="carol")
        self.c.add("vouch", "hiram", {"candidate": "cand4"})
        with self.assertRaisesRegex(Invalid, "budget"):
            self.c.state()

    def test_witness_added_by_ballot(self):
        self.c.add("ballot_open", "ada", {"id": "w-1", "kind": "witness", "subject": witness_subject(self.c, "node2")})
        self.c.vote("w-1", {f: "yes" for f in FOUNDERS})
        self.assertIn("node2", self.c.state().witnesses)

    def test_malformed_entries_are_invalid_not_crashes(self):
        self.c.add("ballot_open", "hiram", {"id": "x", "kind": "admission", "subject": {"candidate": "nobody"}})
        with self.assertRaises(Invalid):
            self.c.state()

    def test_eternal_landmarks_cannot_be_amended(self):
        self.c.add("ballot_open", "hiram", {"id": "am-1", "kind": "amendment", "subject": {
            "path": "./canon//eternal.toml", "new_sha256": "00" * 32}})
        with self.assertRaises(Invalid):
            self.c.state()

    def test_reveal_must_match_commitment(self):
        initiate(self.c, "grace")
        self.c.add("ballot_open", "hiram", {"id": "am-2", "kind": "amendment",
                                             "subject": {"path": "CONSTITUTION.md", "new_sha256": "11" * 32}})
        self.c.add("ballot_commit", "ada", {"id": "am-2", "commitment": commitment("am-2", "ada", "no", salt_of("ada"))})
        self.c.add("ballot_reveal", "ada", {"id": "am-2", "vote": "yes", "salt": salt_of("ada")}, days=8)
        with self.assertRaisesRegex(Invalid, "does not match commitment"):
            self.c.state()


class Governed(unittest.TestCase):
    def test_tree_matches_genesis_pins(self):
        from openmasonry.govern import check_tree
        with tempfile.TemporaryDirectory() as t:
            st = founded(Path(t)).state()
            self.assertEqual(check_tree(st), [])
            st.pins["canon/degrees.toml"] = "00" * 32
            self.assertEqual(len(check_tree(st)), 2)       # the pin, and the table it names is not archived


class Tamper(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.c = founded(Path(self._t.name))
        initiate(self.c, "dave")

    def tearDown(self):
        self._t.cleanup()

    def test_editing_history_breaks_the_chain(self):
        forged = copy.deepcopy(self.c.entries)
        forged[2]["body"]["key"] = self.c.key("eve")          # entry 2 is dave's petition
        with self.assertRaisesRegex(Invalid, "signature|prev"):
            replay(forged)

    def test_deleting_an_entry_is_detected(self):
        forged = copy.deepcopy(self.c.entries)
        del forged[2]
        with self.assertRaises(Invalid):
            replay(forged)

    def test_impersonation_is_rejected(self):
        self.c.add("vouch", "hiram", {"candidate": "dave"}, key_of="dave")
        with self.assertRaisesRegex(Invalid, "signature"):
            self.c.state()

    def test_reordering_is_detected(self):
        forged = copy.deepcopy(self.c.entries)
        forged[2], forged[3] = forged[3], forged[2]
        with self.assertRaises(Invalid):
            replay(forged)


class Decisions(unittest.TestCase):
    def test_quorum(self):
        self.assertEqual([quorum(n) for n in (1, 2, 3, 9, 10, 30, 300)], [1, 2, 3, 3, 4, 10, 100])

    def test_one_fifth_rule_exhaustive(self):
        for n in range(1, 60):
            for y in range(0, n + 1):
                for b in range(0, n + 1 - y):
                    got = decide("admission", y, b, n)
                    want = (y + b) >= quorum(n) and 5 * b < (y + b)
                    self.assertEqual(got, want, (n, y, b))

    def test_monotonic_in_yes(self):
        for n in range(1, 60):
            for y in range(0, n):
                for b in range(0, n - y):
                    for k in ("admission", "amendment"):
                        if decide(k, y, b, n):
                            self.assertTrue(decide(k, y + 1, b, n) or y + 1 + b > n)

    def test_amendment_needs_two_thirds_and_turnout(self):
        self.assertTrue(decide("amendment", 20, 10, 90))
        self.assertFalse(decide("amendment", 19, 10, 90))   # turnout 29 < 30
        self.assertFalse(decide("amendment", 19, 11, 90))   # 19/30 < 2/3


class Lot(unittest.TestCase):
    def test_deterministic_and_beacon_sensitive(self):
        pool = [f"m{i}" for i in range(50)]
        self.assertEqual(draw(pool, 5, "beacon-A", "p"), draw(list(reversed(pool)), 5, "beacon-A", "p"))
        self.assertNotEqual(draw(pool, 5, "beacon-A", "p"), draw(pool, 5, "beacon-B", "p"))

    def test_roughly_uniform(self):
        pool = [f"m{i}" for i in range(10)]
        hits = {p: 0 for p in pool}
        for r in range(5000):
            hits[draw(pool, 1, f"round-{r}", "u")[0]] += 1
        self.assertTrue(all(380 < h < 620 for h in hits.values()), hits)


class Canon(unittest.TestCase):
    def test_33_degrees_and_houses_cover_them(self):
        d, h = canon.degrees(), canon.houses()
        self.assertEqual(len(d), 33)
        for deg in d.values():
            lo, hi = h[deg.house].range
            self.assertTrue(lo <= deg.n <= hi, deg.n)

    def test_merkle_rfc6962_vectors_and_no_duplication_ambiguity(self):
        import hashlib
        a, b, c = (hashlib.sha256(x).hexdigest() for x in (b"a", b"b", b"c"))
        self.assertNotEqual(merkle_root([a, b, c]), merkle_root([a, b, c, c]))
        h = lambda p, *xs: hashlib.sha256(p + b"".join(xs)).digest()
        la, lb, lc = (h(b"\x00", bytes.fromhex(x)) for x in (a, b, c))
        self.assertEqual(merkle_root([a, b, c]), h(b"\x01", h(b"\x01", la, lb), lc).hex())

    def test_merkle_root_changes_with_any_leaf(self):
        leaves = [f"{i:064x}" for i in range(7)]
        base = merkle_root(leaves)
        for i in range(7):
            alt = leaves.copy()
            alt[i] = "f" * 64
            self.assertNotEqual(merkle_root(alt), base)


if __name__ == "__main__":
    unittest.main()
