"""A clone remembers the head it verified (SPEC section 9.7), and a head dated ahead of the clock is an alarm.

Replay cannot see that history was rewound: a shorter or rewritten ledger replays as well as the true one.
So every client remembers the highest head of the canonical ledger it verified, outside the repository, and
holds the canonical ledger against it before it drafts, approves or signs anything.

No test here runs git or reaches the network: the canonical ledger is given by the test.

Run: PYTHONPATH=src python3 -m unittest tests.test_rollback -v
"""
from __future__ import annotations

import argparse
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from openmasonry import actions, ledger, verify
from openmasonry.ledger import (FUTURE_TOLERANCE, Invalid, entry_hash, future_head, head_marks, head_verdict,
                                remember_head, replay)
import tests.test_core as core
from tests.test_protocol import witness_subject, Chain, genesis_body, entry_path
from tests.test_strict import DAY, SEC, Fast, by_key, founded, tmpdir, write_ledger

URL = "https://example.org/work"


def chain(n: int, who: str = "ada", start: datetime | None = None, founders=None) -> Fast:
    """A founded ledger followed by `n` works, one a day."""
    c = Fast()
    if start is not None:
        c.now = start
    c.add("genesis", (founders or ["hiram"])[0], genesis_body(c, founders or ["hiram", "ada", "carol"]))
    for i in range(n):
        c.add("work", who, {"ref": f"{URL}/{i}"}, days=1)
    return c


def branch(c: Fast, keep: int, n: int, who: str = "carol") -> Fast:
    """The first `keep` entries of `c`, then `n` other entries: the same genesis, another history."""
    d = Fast()
    d.keys, d.entries = c.keys, list(c.entries[:keep])
    d.now = ledger.ts(d.entries[-1]["time"])
    for i in range(n):
        d.add("work", who, {"ref": f"{URL}/other/{i}"}, days=1)
    return d


def hashes(c) -> list[str]:
    return [entry_hash(e) for e in c.entries]


class Verdict(unittest.TestCase):
    """`ledger.head_verdict` and `ledger.remember_head`: pure."""

    def setUp(self):
        self.c = chain(6)
        self.h = hashes(self.c)
        self.store = remember_head({}, self.h)

    def test_a_device_with_no_mark_takes_the_first_history_it_verifies(self):
        self.assertEqual(head_verdict({}, self.h), ("first", 6, self.h[6]))
        self.assertEqual(self.store, {"v": 1, "heads": {self.h[0]: [{"seq": 6, "hash": self.h[6]}]}})
        for junk in (None, [], "x", {"heads": 7}, {"heads": {self.h[0]: "x"}}, {"heads": {self.h[0]: [{"seq": -1, "hash": "x"}]}}):
            self.assertEqual(head_verdict(junk, self.h)[0], "first", junk)       # what is not a mark is not a mark

    def test_the_same_history_and_a_longer_one_are_ok(self):
        self.assertEqual(head_verdict(self.store, self.h), ("ok", 6, self.h[6]))
        longer = chain(9)
        self.assertEqual(hashes(longer)[:7], self.h)
        self.assertEqual(head_verdict(self.store, hashes(longer)), ("ok", 9, hashes(longer)[9]))
        self.assertEqual(head_marks(remember_head(self.store, hashes(longer)), self.h[0]), [(9, hashes(longer)[9])])

    def test_a_shorter_history_of_the_same_entries_is_behind(self):
        self.assertEqual(head_verdict(self.store, self.h[:4], known=self.h), ("behind", 6, self.h[6]))
        self.assertEqual(head_verdict(self.store, self.h[:4]), ("behind", 6, self.h[6]))      # nothing shows it lost anything
        self.assertEqual(head_verdict(self.store, self.h[:1], known=self.h[:3]), ("behind", 6, self.h[6]))

    def test_another_entry_at_the_remembered_seq_is_a_rollback(self):
        other = hashes(branch(self.c, 4, 3))                      # as long as before, rewritten from entry 4 on
        self.assertEqual(len(other), 7)
        self.assertEqual(head_verdict(self.store, other, known=self.h), ("rollback", 6, self.h[6]))
        self.assertEqual(head_verdict(self.store, other), ("rollback", 6, self.h[6]))
        longer = hashes(branch(self.c, 4, 9))
        self.assertEqual(head_verdict(self.store, longer), ("rollback", 6, self.h[6]))
        last = hashes(branch(self.c, 6, 1))                       # only the remembered entry itself was replaced
        self.assertEqual(head_verdict(self.store, last), ("rollback", 6, self.h[6]))

    def test_a_shorter_history_that_differs_from_the_one_this_clone_holds_is_a_rollback(self):
        other = hashes(branch(self.c, 2, 2))                      # 4 entries, the last 2 rewritten
        self.assertEqual(head_verdict(self.store, other, known=self.h), ("rollback", 6, self.h[6]))
        self.assertEqual(head_verdict(self.store, other)[0], "behind")     # without the copy, only its length is known
        self.assertEqual(head_verdict(self.store, other, known=other)[0], "behind")   # a copy that follows it shows nothing

    def test_another_genesis_is_another_fraternity(self):
        other = hashes(chain(2, founders=["ada", "hiram"]))
        self.assertNotEqual(other[0], self.h[0])
        self.assertEqual(head_verdict(self.store, other), ("genesis", 0, other[0]))
        both = remember_head(self.store, other)                   # accepted once
        self.assertEqual(head_verdict(both, other)[0], "ok")
        self.assertEqual(head_verdict(both, self.h)[0], "ok")     # and the first one is still remembered

    def test_a_fork_accepted_explicitly_is_remembered_beside_the_history_it_left(self):
        fork = hashes(branch(self.c, 4, 5))
        self.assertEqual(head_verdict(self.store, fork)[0], "rollback")
        both = remember_head(self.store, fork)
        self.assertEqual(head_marks(both, self.h[0]), [(6, self.h[6]), (8, fork[8])])
        self.assertEqual(head_verdict(both, fork), ("ok", 8, fork[8]))
        self.assertEqual(head_verdict(both, self.h), ("ok", 6, self.h[6]))
        again = hashes(branch(self.c, 3, 9))                      # a third history: neither head is in it
        self.assertEqual(head_verdict(both, again)[0], "rollback")
        self.assertEqual(remember_head(both, fork), both)         # remembering what is remembered changes nothing

    def test_the_memory_only_moves_forward_along_one_history(self):
        store = self.store
        for n in (7, 8, 12):
            h = hashes(chain(n))
            self.assertEqual(head_verdict(store, h)[0], "ok")
            store = remember_head(store, h)
            self.assertEqual(head_marks(store, h[0]), [(n, h[n])])
        self.assertEqual(head_verdict(store, self.h)[0], "behind")

    def test_a_head_dated_ahead_of_the_clock(self):
        now = datetime(2027, 3, 1, tzinfo=timezone.utc)
        self.assertEqual(FUTURE_TOLERANCE, timedelta(minutes=10))
        self.assertFalse(future_head(now, now))
        self.assertFalse(future_head(now + FUTURE_TOLERANCE, now))               # the tolerance itself is allowed
        self.assertTrue(future_head(now + FUTURE_TOLERANCE + SEC, now))
        self.assertFalse(future_head(now - 400 * DAY, now))


class Client(unittest.TestCase):
    """`actions.canonical_guard` and what stands on it: the file in the config directory, never the repository."""

    def setUp(self):
        self.tmp = tmpdir(self)
        self.heads = self.tmp / "home" / "heads.json"
        self.canonical = None
        for name, value in (("HEADS", self.heads), ("HOME", self.tmp / "home"), ("PENDING", self.tmp / "home" / "pending"),
                            ("canonical_ledger", lambda: self.canonical),
                            ("replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw))):
            p = mock.patch.object(actions, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.c = chain(5, start=datetime.now(timezone.utc).replace(microsecond=0) - 40 * DAY)
        self.h = hashes(self.c)

    def marks(self, genesis=None):
        return head_marks(json.loads(self.heads.read_text()), genesis or self.h[0]) if self.heads.exists() else None

    def test_the_head_is_remembered_only_after_the_canonical_ledger_verified(self):
        self.assertEqual(actions.canonical_guard(self.h), ("none", ""))                 # no canonical ledger to look at
        self.assertIsNone(self.marks())
        self.canonical = self.c.entries
        self.assertEqual(actions.canonical_guard(self.h), ("ok", ""))
        self.assertEqual(self.marks(), [(5, self.h[5])])
        self.assertEqual(self.heads.stat().st_mode & 0o077, 0)                          # private, like the other files there
        self.assertFalse(self.heads.resolve().is_relative_to(ledger.canon.ROOT.resolve()))

    def test_entries_of_ones_own_that_are_not_merged_do_not_move_it(self):
        self.canonical = self.c.entries[:4]
        mine = chain(7, start=ledger.ts(self.c.entries[0]["time"]))                      # the working copy: three more
        self.assertEqual(actions.canonical_guard(hashes(mine)), ("ok", ""))
        self.assertEqual(self.marks(), [(3, self.h[3])])                                # the canonical head, not one's own

    def test_a_canonical_ledger_that_does_not_verify_is_never_remembered(self):
        bad = copy.deepcopy(self.c.entries)
        bad[3]["sig"] = self.c.key("carol")                                             # signed by somebody else
        self.canonical = bad
        verdict, msg = actions.canonical_guard(self.h)
        self.assertEqual(verdict, "invalid")
        self.assertIn("INVALID — the canonical ledger does not verify: entry 3: bad signature", msg)
        self.assertIsNone(self.marks())

        def broken():
            raise Invalid(2, "000002.json is not strict JSON: duplicate key 'seq'")
        with mock.patch.object(actions, "canonical_ledger", broken):
            self.assertEqual(actions.canonical_guard(self.h)[0], "invalid")

    def test_rollback_behind_and_ahead(self):
        self.canonical = self.c.entries
        actions.canonical_guard(self.h)
        self.canonical = chain(8, start=ledger.ts(self.c.entries[0]["time"])).entries    # the ledger grew
        self.assertEqual(actions.canonical_guard(self.h)[0], "ok")
        grown = [entry_hash(e) for e in self.canonical]
        self.assertEqual(self.marks(), [(8, grown[8])])
        self.canonical = self.canonical[:6]                                              # a mirror that lags
        verdict, msg = actions.canonical_guard(grown)
        self.assertEqual(verdict, "canonical_behind")
        self.assertTrue(msg.startswith(f"BEHIND — the canonical ledger this clone fetched has 6 entries, and this clone "
                                       f"verified entry 8 (hash {grown[8]}) earlier"), msg)
        self.assertNotIn("ROLLBACK", msg)
        self.assertEqual(self.marks(), [(8, grown[8])])                                  # nothing is forgotten
        self.canonical = branch(self.c, 3, 8).entries                                    # rewound, and written again
        verdict, msg = actions.canonical_guard(grown)
        self.assertEqual(verdict, "rollback")
        self.assertTrue(msg.startswith(f"ROLLBACK — the canonical ledger no longer contains entry 8 (hash {grown[8]}) that "
                                       "this clone verified earlier"), msg)
        self.assertEqual(self.marks(), [(8, grown[8])])
        self.assertEqual(actions.canonical_guard(())[0], "rollback")                     # also for a clone reset onto it

    def test_another_genesis_needs_to_be_accepted_once(self):
        self.canonical = self.c.entries
        actions.canonical_guard(self.h)
        other = chain(2, founders=["ada", "hiram"], start=ledger.ts(self.c.entries[0]["time"]))
        self.canonical = other.entries
        verdict, msg = actions.canonical_guard(hashes(other))
        self.assertEqual(verdict, "genesis")
        self.assertIn(f"DIFFERENT GENESIS — the canonical ledger starts from the genesis {hashes(other)[0]}", msg)
        self.assertIn(f"verify --accept-genesis {hashes(other)[0]}", msg)
        with self.assertRaisesRegex(actions.UserError, "--accept-genesis names"):
            actions.canonical_guard(hashes(other), accept=self.h[0])                     # the wrong hash accepts nothing
        self.assertIsNone(self.marks(hashes(other)[0]) or None)
        self.assertEqual(actions.canonical_guard(hashes(other), accept=hashes(other)[0]), ("ok", ""))
        self.assertEqual(actions.canonical_guard(hashes(other)), ("ok", ""))             # once is enough
        self.assertEqual(self.marks(), [(5, self.h[5])])                                 # the first fraternity is still remembered

    def test_a_fork_is_followed_only_when_the_person_accepts_it(self):
        self.canonical = self.c.entries
        actions.canonical_guard(self.h)
        fork = branch(self.c, 3, 6)
        self.canonical = fork.entries
        self.assertEqual(actions.canonical_guard(hashes(fork))[0], "rollback")
        self.assertEqual(actions.canonical_guard(hashes(fork), accept=self.h[0]), ("ok", ""))
        self.assertEqual(actions.canonical_guard(hashes(fork)), ("ok", ""))
        self.assertEqual(self.marks(), [(5, self.h[5]), (8, hashes(fork)[8])])
        self.canonical = self.c.entries                                                  # the clone of the history it left
        self.assertEqual(actions.canonical_guard(self.h), ("ok", ""))

    def test_a_canonical_head_dated_ahead_of_the_clock(self):
        self.canonical = self.c.entries
        head = ledger.ts(self.c.entries[-1]["time"])
        self.assertEqual(actions.canonical_guard(self.h, now=head - FUTURE_TOLERANCE), ("ok", ""))
        self.heads.unlink()
        verdict, msg = actions.canonical_guard(self.h, now=head - FUTURE_TOLERANCE - SEC)
        self.assertEqual(verdict, "future")
        self.assertTrue(msg.startswith(f"FUTURE HEAD — entry 5 of the canonical ledger is dated {self.c.entries[-1]['time']}"), msg)
        self.assertIsNone(self.marks())                                                  # and it is not remembered

    # -- what stands on it: drafting, approving, the sync status, `om verify` --

    def args(self, **kw):
        led = write_ledger(self.tmp / "led", self.c.entries)
        return argparse.Namespace(ledger=led, login="ada", key=str(self.tmp / "key"), time=None, json=True, **kw)

    def test_nothing_is_drafted_or_approved_on_a_rewound_ledger(self):
        a = self.args()
        self.canonical = self.c.entries
        with mock.patch.object(actions, "is_repo_ledger", lambda led: True), mock.patch("builtins.print") as out:
            self.assertEqual(actions.propose(a, "work", {"ref": URL + "/new"}, "a work"), actions.NEEDS_APPROVAL)
            digest = json.loads(out.call_args.args[0])["digest"]
            self.assertTrue((actions.PENDING / f"{digest}.json").exists())
            self.canonical = branch(self.c, 3, 4).entries
            with self.assertRaisesRegex(actions.UserError, "^ROLLBACK — the canonical ledger no longer contains entry 5"):
                actions.propose(a, "work", {"ref": URL + "/newer"}, "a work")
            with self.assertRaisesRegex(actions.UserError, "^ROLLBACK — "):
                actions.cmd_approve(argparse.Namespace(digest=digest[:16], no_submit=True, json=True))
            self.assertFalse(entry_path(a.ledger, 6).exists())                        # nothing was signed
            self.canonical = self.c.entries[:2]
            with self.assertRaisesRegex(actions.UserError, "^BEHIND — "):
                actions.propose(a, "work", {"ref": URL + "/newer"}, "a work")
        self.canonical = branch(self.c, 3, 4).entries                                    # a scratch ledger has no canonical one
        with mock.patch("builtins.print"):
            self.assertEqual(actions.propose(a, "work", {"ref": URL + "/x"}, "a work"), actions.NEEDS_APPROVAL)

    def test_the_sync_status_reports_it_also_when_the_repository_cannot_be_reached(self):
        done = lambda code, out="": argparse.Namespace(returncode=code, stdout=out, stderr="")
        self.canonical = self.c.entries
        with mock.patch.object(actions, "canonical_remote", lambda: "origin"):
            with mock.patch.object(actions, "_git", lambda *args: done(0)):
                self.assertEqual(actions.canonical_status(self.h)[0], "in_sync")
            self.canonical = branch(self.c, 2, 5).entries
            for fetched in (0, 1):
                with mock.patch.object(actions, "_git", lambda *args: done(fetched if args[0] == "fetch" else 0)):
                    status, msg = actions.canonical_status(self.h)
                    self.assertEqual(status, "rollback")
                    self.assertIn("no longer contains entry 5", msg)
                    with self.assertRaisesRegex(actions.UserError, "^ROLLBACK — "):
                        actions._require_in_sync(self.h)
            self.canonical = self.c.entries[:3]
            with mock.patch.object(actions, "_git", lambda *args: done(0)):
                self.assertEqual(actions.canonical_status(self.h)[0], "canonical_behind")
            self.canonical = self.c.entries
            with mock.patch.object(actions, "_git", lambda *args: done(1 if args[0] == "fetch" else 0)):
                self.assertEqual(actions.canonical_status(self.h)[0], "offline")

    def report(self, a, **kw):
        with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)), \
                mock.patch.object(actions, "is_repo_ledger", lambda led: True):
            return actions.verify_client(argparse.Namespace(**{**vars(a), **kw}), verify.verify_report(a))

    def test_om_verify_reports_rollback_behind_and_a_future_head(self):
        a = argparse.Namespace(ledger=write_ledger(self.tmp / "led", self.c.entries), tree=False, online=False,
                               clock_since=None, root=None, pr_author=None, since=None, json=True, accept_genesis=None)
        self.canonical = self.c.entries
        first = self.report(a)
        self.assertEqual((first["valid"], first["schema"], first["state_sha256"]),
                         (True, "om.verify/1", self.c.state().digest()))
        self.assertEqual(self.marks(), [(5, self.h[5])])
        self.canonical = self.c.entries[:2]
        r = self.report(a)
        self.assertTrue(r["valid"])                                                      # behind is not a rollback
        self.assertIn("\nBEHIND — the canonical ledger this clone fetched has 2 entries", r["message"])
        self.assertTrue(r["message"].startswith("VALID — "))
        fork = branch(self.c, 2, 6)
        self.canonical = fork.entries
        r = self.report(a)
        self.assertEqual((r["valid"], r["problems"]), (False, [r["message"]]))
        self.assertTrue(r["message"].startswith("ROLLBACK — the canonical ledger no longer contains entry 5 (hash "), r["message"])
        self.assertEqual(sorted(r), sorted(first))                                       # the same members: om.verify/1
        r = self.report(a, accept_genesis=self.h[0])
        self.assertTrue(r["valid"], r["message"])
        self.assertTrue(self.report(a)["valid"])
        with mock.patch.object(actions, "now_utc", lambda: ledger.ts(self.c.entries[-1]["time"]) - 11 * 60 * SEC):
            r = self.report(a)
        self.assertEqual(r["valid"], False)
        self.assertTrue(r["message"].startswith("FUTURE HEAD — entry 5 is dated "), r["message"])

    def doctor(self, own: bool, now) -> tuple[int, str]:
        """`om doctor` in this process, with every program replaced; `own` says whether the ledger is the
        repository's own."""
        import contextlib
        import io
        import subprocess
        (self.tmp / "key.pub").write_text(self.c.key("ada") + " a comment\n")
        a = argparse.Namespace(login="ada", key=str(self.tmp / "key"), ledger=self.tmp / "led")
        out = io.StringIO()
        done = lambda *args: argparse.Namespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(actions, "state_of", return_value=self.c.state()), \
                mock.patch("openmasonry.onboard.doctor_checks", return_value=[]), \
                mock.patch.object(actions.shutil, "which", lambda name, *x, **k: None if name == "curl" else "/bin/x"), \
                mock.patch.object(actions.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")), \
                mock.patch.object(actions, "is_repo_ledger", lambda led: own), \
                mock.patch.object(actions, "canonical_remote", lambda: "origin"), \
                mock.patch.object(actions, "_git", done), mock.patch.object(actions, "now_utc", lambda: now), \
                contextlib.redirect_stdout(out):
            code = actions.cmd_doctor(a)
        return code, out.getvalue()

    def test_om_doctor_reports_a_rewound_ledger_and_a_head_dated_ahead(self):
        head = ledger.ts(self.c.entries[-1]["time"])
        self.canonical = self.c.entries
        code, text = self.doctor(True, head + DAY)
        self.assertEqual(code, 0, text)
        self.assertNotIn("ROLLBACK", text)
        self.assertEqual(self.marks(), [(5, self.h[5])])
        self.canonical = branch(self.c, 2, 6).entries
        code, text = self.doctor(True, head + 30 * DAY)
        self.assertEqual(code, 1, text)
        self.assertIn("✘ ROLLBACK — the canonical ledger no longer contains entry 5 (hash " + self.h[5], text)
        self.canonical = self.c.entries
        code, text = self.doctor(True, head - 11 * 60 * SEC)
        self.assertEqual(code, 1, text)
        self.assertIn("✘ FUTURE HEAD — entry 5 is dated ", text)
        code, text = self.doctor(False, head - 11 * 60 * SEC)                            # a scratch ledger is not held to the clock
        self.assertEqual(code, 0, text)
        self.assertNotIn("FUTURE HEAD", text)

    def test_a_scratch_ledger_or_an_invalid_one_is_left_to_the_pinned_verifier(self):
        a = argparse.Namespace(ledger=self.tmp / "nowhere", accept_genesis=None)
        invalid = {"valid": False, "message": "INVALID — x", "problems": ["x"]}
        self.assertIs(actions.verify_client(a, invalid), invalid)
        valid = {"valid": True, "message": "VALID — x", "problems": []}
        self.canonical = branch(self.c, 2, 6).entries
        self.assertIs(actions.verify_client(a, valid), valid)                            # not this repository's ledger
        self.assertIsNone(self.marks())

    def test_the_output_of_git_is_read_exactly(self):
        blobs = [b'{"seq": 0}', b"", b"x\ny\n"]
        out = b"".join(b"%040d blob %d\n%s\n" % (i, len(b), b) for i, b in enumerate(blobs))
        self.assertEqual(actions._batch_blobs(out, 3), blobs)
        for bad in (out[:-1], out[:30], out.replace(b"blob", b"tree", 1), b"0 missing\n"):
            with self.assertRaises(ValueError):
                actions._batch_blobs(bad, 3)


class PinnedVerifier(unittest.TestCase):
    """The audit path: `verify --online` refuses a head dated ahead of the clock (an injected one here)."""

    def report(self, c, clock, **flags):
        a = argparse.Namespace(ledger=write_ledger(tmpdir(self) / "led", c.entries), tree=False, online=True,
                               clock_since=None, root=None, pr_author=None, since=None, json=True)
        for k, v in flags.items():
            setattr(a, k, v)
        with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)), \
                mock.patch("openmasonry.beacon.audit", lambda beacons: []):
            return verify.verify_report(a, clock=lambda: clock)

    def test_future_head(self):
        c = chain(3)
        head = c.now
        r = self.report(c, head - FUTURE_TOLERANCE - SEC)
        self.assertEqual(r["valid"], False)
        self.assertEqual(r["message"], "FUTURE HEAD — entry 3 is dated 2027-01-04T00:00:00Z, more than 10 minutes ahead of "
                                       "this clock (2027-01-03T23:49:59Z)")
        self.assertEqual(r["problems"], [r["message"].removeprefix("FUTURE HEAD — ")])
        self.assertTrue(self.report(c, head - FUTURE_TOLERANCE)["valid"])                # the tolerance itself is allowed
        self.assertTrue(self.report(c, head + 400 * DAY)["valid"])                       # an old ledger is not stale
        self.assertTrue(self.report(c, head - 400 * DAY, online=False)["valid"])         # replay alone reads no clock

    def test_the_clock_gate_of_the_judge_reads_the_same_clock(self):
        c = chain(1)
        self.assertTrue(self.report(c, c.now, clock_since=1)["valid"])
        r = self.report(c, c.now - 11 * 60 * SEC, clock_since=1, online=False)
        self.assertTrue(r["message"].startswith("STALE OR FUTURE TIME — entry 1 claims"), r["message"])


class WitnessNode(unittest.TestCase):
    """node/witness.py: it remembers the head it verified beside its clone, and signs nothing on a rewound main."""

    node, written = core.Witness.node, core.Witness.written

    def found(self, age=timedelta(days=30)) -> Chain:
        c = Chain(tmpdir(self))
        c.now = datetime.now(timezone.utc).replace(microsecond=0) - age
        c.add("genesis", "hiram", genesis_body(c, ["hiram", "ada"], ["tyler"]))
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness",
                                     "subject": witness_subject(c, "node2")})
        self.chain = c
        return c

    def other(self, keep: int, n: int) -> list[dict]:
        d = Chain(self.chain.tmp)
        d.keys, d.entries = self.chain.keys, list(self.chain.entries[:keep])
        d.now = ledger.ts(d.entries[-1]["time"])
        for i in range(n):
            d.add("work", "ada", {"ref": f"{URL}/{i}"}, days=1)
        return d.entries

    def marks(self, w):
        return head_marks(json.loads(w.HEADS.read_text()), entry_hash(self.chain.entries[0])) if w.HEADS.exists() else None

    def test_it_remembers_the_canonical_head_and_not_its_own_entries(self):
        c = self.found()
        w = self.node()
        self.assertFalse(w.HEADS.resolve().is_relative_to(w.REPO.resolve()))             # beside the clone, never in it
        w.cycle()                                                                        # git answers nothing: no branch to read
        self.assertEqual((self.written(w), self.alarms, self.marks(w)), (["ballot_close", "witness"], [], None))
        checkpoint = w.load(w.LEDGER)[-1]["body"]
        self.assertEqual(checkpoint["state_sha256"], replay(w.load(w.LEDGER)[:-1]).digest())
        w = self.node()
        w.canonical_entries = lambda: c.entries
        w.cycle()
        self.assertEqual(self.written(w), ["ballot_close", "witness"])
        self.assertEqual(self.marks(w), [(1, entry_hash(c.entries[1]))])                 # what main holds, not what it just signed

    def test_a_rewound_main_is_a_capture_alarm_and_nothing_is_signed(self):
        c = self.found()
        w = self.node(mode="none")
        w.canonical_entries = lambda: c.entries
        w.cycle()
        signed = self.written(w)
        rewritten = self.other(1, 3)
        w.canonical_entries = lambda: rewritten
        w.cycle()
        self.assertEqual(self.written(w), signed)                                        # nothing more
        self.assertEqual(len(self.alarms), 1)
        self.assertEqual(str(self.alarms[0]), f"ROLLBACK — the canonical ledger no longer contains entry 1 (hash "
                                              f"{entry_hash(c.entries[1])}) that this witness verified earlier")
        self.assertEqual(self.marks(w), [(1, entry_hash(c.entries[1]))])

    def test_a_shorter_main_makes_it_wait_without_an_alarm(self):
        c = self.found()
        w = self.node()
        w.canonical_entries = lambda: c.entries
        w.HEADS.write_text(json.dumps(remember_head({}, [entry_hash(e) for e in c.entries])))
        w.canonical_entries = lambda: c.entries[:1]
        w.cycle()
        self.assertEqual((self.written(w), self.alarms), ([], []))
        self.assertTrue(any(line.startswith("BEHIND — the canonical main has 1 entries") for line in self.logs), self.logs)

    def test_another_genesis_is_an_alarm_until_the_operator_accepts_it(self):
        c = self.found()
        w = self.node()
        w.HEADS.write_text(json.dumps({"v": 1, "heads": {"ab" * 32: [{"seq": 4, "hash": "cd" * 32}]}}))
        w.canonical_entries = lambda: c.entries
        w.cycle()
        self.assertEqual(self.written(w), [])
        self.assertIn("DIFFERENT GENESIS — the canonical main starts from the genesis " + entry_hash(c.entries[0]),
                      str(self.alarms[0]))
        w.ACCEPT_GENESIS = entry_hash(c.entries[0])
        w.cycle()
        self.assertEqual((self.written(w), len(self.alarms)), (["ballot_close", "witness"], 1))
        self.assertEqual(self.marks(w), [(1, entry_hash(c.entries[1]))])

    def test_a_head_dated_ahead_of_its_clock_is_a_capture_alarm(self):
        c = self.found(age=timedelta(days=1))
        c.now = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
        c.add("work", "ada", {"ref": URL})
        w = self.node()
        w.cycle()
        self.assertEqual(self.written(w), [])
        self.assertEqual(len(self.alarms), 1)
        self.assertTrue(str(self.alarms[0]).startswith("FUTURE HEAD — entry 2 is dated "), self.alarms)

    def test_a_main_that_does_not_verify_is_a_capture_alarm(self):
        c = self.found()
        w = self.node()
        forged = copy.deepcopy(c.entries)
        forged[1]["body"]["id"] = "another"
        w.canonical_entries = lambda: forged
        w.cycle()
        self.assertEqual(self.written(w), [])
        self.assertIn("the canonical main does not verify: entry 1: bad signature", str(self.alarms[0]))
        self.assertIsNone(self.marks(w))


if __name__ == "__main__":
    unittest.main()
