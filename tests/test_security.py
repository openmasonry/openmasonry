"""Regression tests for security and specification guarantees."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from openmasonry import canon, govern, identity, ledger, verify
from openmasonry.govern import check_tree
from openmasonry.ledger import (BEACON_DELAY_ROUNDS, Invalid, Member, State, commitment, drand_round, load,
                                replay, valid_login)
from tests.test_protocol import (canon_digest, DECL, FOUNDERS, T0, Chain, checkpoint, copy_governed, entry_file, founded,
                                 genesis_body, gid, initiate, invite, salt_of)

REPO = Path(__file__).resolve().parents[1]


def tmpdir(test) -> Path:
    t = tempfile.TemporaryDirectory()
    test.addCleanup(t.cleanup)
    return Path(t.name)


def petition(c: Chain, who: str, decl: str = DECL, days: float = 0, by: str | None = "hiram"):
    """A petition after `days`, under an invitation signed by `by` at that same time (`by=None`: no invitation)."""
    if by is not None:
        invite(c, who, by, days=days)
        days = 0
    c.add("petition", who, {"key": c.key(who), "declaration_sha256": decl}, days=days)


class GenesisAndDeclaration(unittest.TestCase):
    def test_nothing_before_genesis(self):
        c = Chain(tmpdir(self))
        petition(c, "early", by=None)
        with self.assertRaisesRegex(Invalid, "entry 0 is the genesis"):
            c.state()

    def test_petition_must_commit_to_the_real_declaration(self):
        c = founded(tmpdir(self))
        petition(c, "kim", decl="ab" * 32)
        with self.assertRaisesRegex(Invalid, "sha256 of the Declaration"):
            c.state()

    def test_genesis_must_pin_everything_and_canon_must_be_archived(self):
        c = Chain(tmpdir(self))
        c.add("genesis", "hiram", genesis_body(c, ["hiram"], pins={"canon/degrees.toml": "ab" * 32}))
        with self.assertRaisesRegex(Invalid, "not archived"):
            c.state()


class Ballots(unittest.TestCase):
    def setUp(self):
        self.c = founded(tmpdir(self))
        petition(self.c, "pat")                               # hiram invites, and so is the first sponsor
        self.c.add("vouch", "ada", {"candidate": "pat"})

    def test_subjects_have_exact_keys(self):
        self.c.add("ballot_open", "hiram", {"id": "d", "kind": "admission", "subject": {"candidate": "pat", "z": 1}})
        with self.assertRaisesRegex(Invalid, "exactly the keys"):
            self.c.state()

    def test_one_open_ballot_per_subject(self):
        self.c.add("ballot_open", "hiram", {"id": "a1", "kind": "admission", "subject": {"candidate": "pat"}})
        self.c.add("ballot_open", "ada", {"id": "a2", "kind": "admission", "subject": {"candidate": "pat"}})
        with self.assertRaisesRegex(Invalid, "already open"):
            self.c.state()

    def test_only_a_sponsor_opens_an_admission_ballot(self):
        self.c.add("ballot_open", "carol", {"id": "a1", "kind": "admission", "subject": {"candidate": "pat"}})
        with self.assertRaisesRegex(Invalid, "only a sponsor"):
            self.c.state()

    def test_open_ballot_freezes_the_petition_against_hijack(self):
        self.c.add("ballot_open", "hiram", {"id": "a1", "kind": "admission", "subject": {"candidate": "pat"}})
        st = self.c.state()
        self.assertEqual(st.ballots["a1"].frozen["vouches"], ["hiram", "ada"])
        # Even after the petition would lapse, the login cannot be invited or petition again while the ballot is open.
        invite(self.c, "pat", by="carol", days=181)
        with self.assertRaisesRegex(Invalid, "pat already has a pending petition"):
            self.c.state()
        self.c.entries.pop()
        self.c.add("petition", "pat", {"key": self.c.key("mallory"), "declaration_sha256": DECL})
        with self.assertRaisesRegex(Invalid, "no live invitation for 'pat'"):
            self.c.state()

    def test_reveal_waits_for_the_clock_tolerance_gap(self):
        self.c.add("ballot_open", "hiram", {"id": "a1", "kind": "admission", "subject": {"candidate": "pat"}})
        self.c.add("ballot_commit", "ada", {"id": "a1", "commitment": commitment("a1", "ada", "yes", "s" * 16)})
        self.c.add("ballot_reveal", "ada", {"id": "a1", "vote": "yes", "salt": "s" * 16}, days=7.1)
        with self.assertRaisesRegex(Invalid, "not in the reveal window"):
            self.c.state()


class Exams(unittest.TestCase):
    def test_only_the_candidate_opens_their_exam(self):
        c = founded(tmpdir(self))
        initiate(c, "vic")
        rnd = drand_round(c.now + timedelta(days=31)) + BEACON_DELAY_ROUNDS
        c.add("exam_open", "ada", {"candidate": "vic", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd}, days=31)
        with self.assertRaisesRegex(Invalid, "only the candidate"):
            c.state()

    def test_examiner_pool_is_frozen_at_open(self):
        c = founded(tmpdir(self))
        initiate(c, "vic")
        rnd = drand_round(c.now + timedelta(days=31)) + BEACON_DELAY_ROUNDS
        c.add("exam_open", "vic", {"candidate": "vic", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd}, days=31)
        ex = c.state().exams[("vic", 2)]
        # Ladder: no 2° peer, Masters minus sponsors leaves 1 < k=2, so the last rung (any Master but the candidate).
        self.assertEqual((ex.pool, ex.k), (("ada", "carol", "hiram"), 2))


class FoundingCohort(unittest.TestCase):
    def test_founders_are_honorary_and_never_grade_each_other_when_others_exist(self):
        mk = lambda l, d, founder=False: Member(l, "k", d, {i: T0 for i in range(1, d + 1)}, activity=[T0], founder=founder)
        members = [mk("f1", 3, True), mk("f2", 3, True), mk("f3", 3, True), mk("o1", 3), mk("o2", 3), mk("o3", 3)]
        st = State(members={m.login: m for m in members}, pins={"canon/degrees.toml": canon_digest()})
        from openmasonry.ledger import examiner_pool
        self.assertEqual(examiner_pool(st, st.members["f1"], 4, T0), ["o1", "o2", "o3"])
        st.members.pop("o3")                       # not enough outsiders: fall back to the normal ladder
        self.assertEqual(examiner_pool(st, st.members["f1"], 4, T0), ["f2", "f3", "o1", "o2"])
        self.assertTrue(founded(tmpdir(self)).state().members["hiram"].founder)


class Sanctions(unittest.TestCase):
    def test_suspension_ends_by_itself_after_a_year(self):
        c = founded(tmpdir(self))
        c.add("ballot_open", "hiram", {"id": "s", "kind": "sanction", "subject": {"member": "carol", "measure": "suspend"}})
        c.vote("s", {"hiram": "yes", "ada": "yes"})
        c.add("work", "carol", {"ref": "https://example.org/back"}, days=366)
        self.assertTrue(c.state().members["carol"].is_active(c.state().time))

    def test_fraud_expulsion_bans_the_sponsors(self):
        c = founded(tmpdir(self))
        initiate(c, "fake")
        c.add("ballot_open", "carol", {"id": "x", "kind": "sanction", "subject": {"member": "fake", "measure": "expel_for_fraud"}})
        c.vote("x", {f: "yes" for f in FOUNDERS})
        invite(c, "next")                                     # a banned sponsor can neither invite…
        with self.assertRaisesRegex(Invalid, "sponsorship suspended"):
            c.state()
        c.entries.pop()
        petition(c, "next", by="carol")
        c.add("vouch", "hiram", {"candidate": "next"})        # …nor vouch
        with self.assertRaisesRegex(Invalid, "sponsorship suspended"):
            c.state()

    def test_a_suspended_member_keeps_the_seat_and_cannot_act(self):
        now = T0 + timedelta(days=10)
        m = Member("g", "k", 33, {1: T0}, activity=[now], seat_until=now + timedelta(days=100),
                   status="suspended", suspended_until=now + timedelta(days=50))
        self.assertEqual((State(members={"g": m}).seats(now), m.is_active(now)), (["g"], False))


class Identity(unittest.TestCase):
    def test_logins_are_strict_and_case_insensitive(self):
        self.assertFalse(valid_login("hiram\n"))
        self.assertFalse(valid_login("-hiram"))
        c = founded(tmpdir(self))
        invite(c, "Hiram", by="ada")
        with self.assertRaisesRegex(Invalid, "case-insensitive"):
            c.state()


class Loader(unittest.TestCase):
    def _write(self, d: Path, c: Chain, names=None):
        d.mkdir(parents=True, exist_ok=True)
        for i, e in enumerate(c.entries):
            path = d / (names[i] if names else ledger.entry_name(e["seq"]))
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(e))

    def test_filenames_must_match_seq(self):
        c = founded(tmpdir(self))
        c.add("work", "ada", {"ref": "https://example.org/x"})
        d = tmpdir(self) / "led"
        self._write(d, c, ["0000/000000.json", "0000/00001a.json"])
        with self.assertRaisesRegex(Invalid, "0000/00001a.json is not an entry"):
            load(d)

    def test_duplicate_json_keys_are_refused(self):
        c = founded(tmpdir(self))
        d = tmpdir(self) / "led"
        self._write(d, c)
        raw = (d / "0000" / "000000.json").read_text()
        (d / "0000" / "000000.json").write_text(raw[:-1] + ', "seq": 0}')
        with self.assertRaisesRegex(Invalid, "duplicate key"):
            load(d)


class Governance(unittest.TestCase):
    def test_protocol_code_is_pinned(self):
        root = copy_governed(tmpdir(self) / "tree")
        st = founded(tmpdir(self)).state()
        self.assertEqual(check_tree(st, root), [])
        with open(root / "src/openmasonry/ledger.py", "a") as f:
            f.write("\n# a quiet change to the judge\n")
        self.assertTrue(any("@protocol" in p for p in check_tree(st, root)))

    def test_amended_file_may_lag_one_version_until_applied(self):
        st = State(pins={"A.md": "11" * 32}, prior_pins={"A.md": "22" * 32}, prior_until={"A.md": T0 + timedelta(days=30)})
        st.time = T0
        root = tmpdir(self)
        (root / "A.md").write_text("x")
        self.assertEqual(len(check_tree(st, root)), 1)          # neither version: unlawful
        st.prior_pins["A.md"] = __import__("hashlib").sha256(b"x").hexdigest()
        self.assertEqual(check_tree(st, root), [])               # previous ratified text: lawful for now


# -- the judge's verdict on a pull request of entries --------------------------------------------------------

OTS_HEADER = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"


def proof_of(root_text: bytes, rest: bytes = b"\xf0\x10" + b"\x01" * 16 + b"\x08\x00" + b"\x83\xdf\xe3\x0d\x2e\xf9\x0c\x8e") -> bytes:
    """The bytes an OpenTimestamps client writes for the file `root_text`: the header, major version 1, the
    sha256 file-hash operation and the file's digest, then the timestamp (here a stand-in)."""
    return OTS_HEADER + b"\x01\x08" + hashlib.sha256(root_text).digest() + rest


class PullRequestGate(unittest.TestCase):
    """`verify --tree --root PR --base-root BASE --since N --pr-author LOGIN --pr-author-id ID`, as the judge runs it,
    with GitHub out of reach (no lookup is needed: the author's id is given, and no entry here lists a key)."""

    def setUp(self):
        self.tmp = tmpdir(self)
        (self.tmp / "keys").mkdir()
        for p in (mock.patch.dict(os.environ, {"OM_NO_CACHE": "1"}),
                  mock.patch.object(identity, "fetch_github_keys", side_effect=OSError("no network in tests")),
                  mock.patch.object(identity, "fetch_github_user", side_effect=OSError("no network in tests"))):
            p.start()
            self.addCleanup(p.stop)

    def tree(self, name: str, entries: list[dict], files: dict | None = None) -> Path:
        root = copy_governed(self.tmp / name)
        led = root / "ledger" / "entries"
        led.mkdir(parents=True, exist_ok=True)
        (root / "ledger" / "reasons").mkdir(exist_ok=True)
        for e in entries:
            entry_file(led, e["seq"]).write_text(json.dumps(e))
        for rel, data in (files or {}).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        return root

    def judge(self, base: Path, pr: Path, since: int, author: str, author_id: int | None = None,
              changes: str | None = None) -> str:
        anchors = None
        if changes is not None:
            anchors = self.tmp / f"changes-{pr.name}"
            anchors.write_text(changes)
        a = argparse.Namespace(ledger=pr / "ledger" / "entries", tree=True, root=pr, base_root=base, since=since,
                               pr_author=author, pr_author_id=gid(author) if author_id is None else author_id,
                               anchors_changed=anchors, online=False, clock_since=None, candidate_root=None, json=False)
        return verify.verify_report(a)["message"].splitlines()[0]


class StrayReasons(PullRequestGate):
    """`ledger/reasons/` holds only the reasons corrections pin. A pull request of amendment-ballot entries is let
    through a tree that does not match the pins, never with a file of its own in that directory; and a stray
    already on the base branch is an alarm, not a lock on everyone else's entries."""

    STRAY = "ledger/reasons/" + "e" * 64 + ".md"
    JUNK = b"Any bytes at all, and nobody reviewed them.\n" * 1000

    def setUp(self):
        super().setUp()
        self.c = founded(self.tmp / "keys")
        self.c.add("ballot_open", "hiram", {"id": "am1", "kind": "amendment",
                                            "subject": {"path": "CONSTITUTION.md", "new_sha256": "ab" * 32}}, days=1)
        self.n = len(self.c.entries)
        self.c.add("ballot_commit", "ada", {"id": "am1", "commitment": commitment("am1", "ada", "no", salt_of("ada"))},
                   days=0.1)

    def test_an_amendment_vote_cannot_bring_an_unpinned_reason(self):
        base = self.tree("main", self.c.entries[:self.n])
        verdict = self.judge(base, self.tree("pr", self.c.entries, {self.STRAY: self.JUNK}), self.n, "ada")
        self.assertTrue(verdict.startswith("UNRATIFIED — " + self.STRAY + ": no correction of the ledger pins this file"),
                        verdict)
        self.assertTrue(self.judge(base, self.tree("pr-clean", self.c.entries), self.n, "ada").startswith("VALID"))

    def test_a_stray_reason_already_on_main_does_not_block_other_entries(self):
        main = self.tree("main", self.c.entries, {self.STRAY: self.JUNK})
        self.c.add("work", "carol", {"ref": "https://example.org/work"}, days=0.1)
        pr = self.tree("pr", self.c.entries, {self.STRAY: self.JUNK})
        self.assertTrue(self.judge(main, pr, self.n + 1, "carol").startswith("VALID"))
        a = argparse.Namespace(ledger=pr / "ledger" / "entries", tree=True, root=pr, base_root=main, since=self.n + 1,
                               pr_author="carol", pr_author_id=gid("carol"), anchors_changed=None, online=False,
                               clock_since=None, candidate_root=None, json=False)
        warnings = verify.verify_report(a)["warnings"]
        self.assertTrue(any(w.startswith(self.STRAY) and "an alarm, not a refusal" in w for w in warnings), warnings)
        changed = self.tree("pr-changed", self.c.entries, {self.STRAY: self.JUNK + b"more"})
        self.assertTrue(self.judge(main, changed, self.n + 1, "carol").startswith("UNRATIFIED — " + self.STRAY))
        audit = check_tree(self.c.state(), main)                     # the audit of main: the alarm
        self.assertTrue(any(p.startswith(f"{self.STRAY}: no correction of the ledger pins this file") for p in audit), audit)


class WitnessAnchors(PullRequestGate):
    """The anchor files of a checkpoint are exactly what its signed body determines: `.root` is the root and a
    newline, and `.ots` is an OpenTimestamps proof of that file. A proof already merged is never changed."""

    def setUp(self):
        super().setUp()
        c = self.c = Chain(self.tmp / "keys")
        c.add("genesis", "hiram", genesis_body(c, witnesses=["w1"]))
        c.add("work", "hiram", {"ref": "https://example.org/a"}, days=0.1)
        st = replay(c.entries)
        self.root1 = (st.entries_root() + "\n").encode()
        c.add("witness", "w1", checkpoint(st, root=st.entries_root(), anchor="ledger/anchors/000001.root.ots"), days=0.1)
        self.merged = {"ledger/anchors/000001.root": self.root1, "ledger/anchors/000001.root.ots": proof_of(self.root1)}
        c.add("work", "ada", {"ref": "https://example.org/b"}, days=0.1)
        self.n = len(c.entries)
        self.base = self.tree("base", c.entries, self.merged)
        st = replay(c.entries)
        self.root3 = (st.entries_root() + "\n").encode()
        c.add("witness", "w1", checkpoint(st, root=st.entries_root(), anchor="ledger/anchors/000003.root.ots"), days=0.1)

    def carry(self, files: dict, changes: str, author="mallory", author_id=999) -> str:
        return self.judge(self.base, self.tree(f"pr{len(os.listdir(self.tmp))}", self.c.entries, {**self.merged, **files}),
                          self.n, author, author_id, changes)

    ADDED = "A\tledger/anchors/000003.root\nA\tledger/anchors/000003.root.ots\n"

    def test_the_witness_files_of_a_checkpoint_pass_whoever_carries_them(self):
        honest = {"ledger/anchors/000003.root": self.root3, "ledger/anchors/000003.root.ots": proof_of(self.root3)}
        self.assertTrue(self.carry(honest, self.ADDED).startswith("VALID"))

    def test_a_root_file_is_the_signed_root_and_nothing_else(self):
        for data in (b"not the root\n", self.root3 + b"x", self.root3.rstrip(b"\n"), self.root1):
            verdict = self.carry({"ledger/anchors/000003.root": data,
                                  "ledger/anchors/000003.root.ots": proof_of(self.root3)}, self.ADDED)
            self.assertTrue(verdict.startswith("UNLAWFUL ANCHOR — ledger/anchors/000003.root: "), verdict)
            self.assertIn("the root the checkpoint signs", verdict)

    def test_a_proof_commits_to_the_signed_root(self):
        for data in (b"not a proof at all\n" * 300, proof_of(self.root1), proof_of(self.root3)[:40],
                     OTS_HEADER + b"\x01\x02" + hashlib.sha1(self.root3).digest() + b"\x00"):
            verdict = self.carry({"ledger/anchors/000003.root": self.root3, "ledger/anchors/000003.root.ots": data},
                                 self.ADDED)
            self.assertTrue(verdict.startswith("UNLAWFUL ANCHOR — ledger/anchors/000003.root.ots: "), verdict)
            self.assertIn("not an OpenTimestamps proof of the root the checkpoint signs", verdict)

    def test_a_merged_proof_is_never_changed(self):
        honest = {"ledger/anchors/000003.root": self.root3, "ledger/anchors/000003.root.ots": proof_of(self.root3)}
        for data in (b"junk" * 100, proof_of(self.root1, b"\x00upgraded")):
            verdict = self.carry({**honest, "ledger/anchors/000001.root.ots": data},
                                 "M\tledger/anchors/000001.root.ots\n" + self.ADDED, author="w1", author_id=None)
            self.assertTrue(verdict.startswith("UNLAWFUL ANCHOR — ledger/anchors/000001.root.ots: "), verdict)
            self.assertIn("never changed", verdict)

    def test_a_checkpoint_without_a_root_anchors_no_file(self):
        (self.tmp / "keys2").mkdir()
        c = Chain(self.tmp / "keys2")
        c.add("genesis", "hiram", genesis_body(c, witnesses=["w1"]))
        c.add("work", "hiram", {"ref": "https://example.org/a"}, days=0.1)
        c.add("witness", "w1", checkpoint(replay(c.entries), anchor="ledger/anchors/000001.root.ots"), days=0.1)
        root = self.tree("rootless", c.entries, {"ledger/anchors/000001.root.ots": proof_of(b"x\n")})
        problems = govern.anchor_problems(c.entries, 2, govern.parse_changes("A\tledger/anchors/000001.root.ots\n"), root)
        self.assertEqual(len(problems), 1)
        self.assertIn("states no root", problems[0])


if __name__ == "__main__":
    unittest.main()
