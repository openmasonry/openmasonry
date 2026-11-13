"""The Guide (`guide.next_steps`, pure next steps) and the member commands' human-in-the-loop gate."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from openmasonry.guide import next_steps
from tests.test_protocol import DECL, FOUNDERS, Chain, founded, initiate, petition, entry_file, entry_path

REPO = Path(__file__).resolve().parents[1]


def tmpdir(test) -> Path:
    t = tempfile.TemporaryDirectory()
    test.addCleanup(t.cleanup)
    return Path(t.name)


def actions(steps):
    return [s.action for s in steps]


class Guide(unittest.TestCase):
    def test_stranger_is_told_to_apply(self):
        st = founded(tmpdir(self)).state()
        self.assertEqual(actions(next_steps(st, "nobody", st.time)), ["apply"])

    def test_candidate_sees_sponsor_progress_then_ballot(self):
        c = founded(tmpdir(self))
        petition(c, "alice")                       # hiram invites, and so is the first sponsor
        st = c.state()
        self.assertEqual(actions(next_steps(st, "alice", st.time)), ["find_sponsors"])
        c.add("vouch", "ada", {"candidate": "alice"})
        st = c.state()
        self.assertIn("open_admission", actions(next_steps(st, "hiram", st.time)))
        c.add("ballot_open", "hiram", {"id": "a", "kind": "admission", "subject": {"candidate": "alice"}})
        st = c.state()
        self.assertEqual(actions(next_steps(st, "alice", st.time)), ["wait"])
        self.assertIn("vote", actions(next_steps(st, "carol", st.time)))

    def test_elector_is_told_to_reveal_then_anyone_to_close(self):
        c = founded(tmpdir(self))
        petition(c, "alice")
        c.add("vouch", "ada", {"candidate": "alice"})
        c.add("ballot_open", "hiram", {"id": "a", "kind": "admission", "subject": {"candidate": "alice"}})
        from openmasonry.ledger import commitment
        c.add("ballot_commit", "ada", {"id": "a", "commitment": commitment("a", "ada", "yes", "s" * 16)})
        st = c.state()
        self.assertIn("wait", actions(next_steps(st, "ada", st.time + timedelta(days=7.1))))
        self.assertIn("reveal", actions(next_steps(st, "ada", st.time + timedelta(days=7.5))))
        self.assertIn("close", actions(next_steps(st, "carol", st.time + timedelta(days=11))))

    def test_new_apprentice_studies_until_the_waiting_period_then_exams(self):
        c = founded(tmpdir(self))
        initiate(c, "bob")
        st = c.state()
        self.assertEqual(actions(next_steps(st, "bob", st.time)), ["study"])
        self.assertEqual(actions(next_steps(st, "bob", st.time + timedelta(days=31))), ["exam"])

    def test_drawn_examiner_is_asked_to_report(self):
        c = founded(tmpdir(self))
        initiate(c, "bob")
        from openmasonry.ledger import BEACON_DELAY_ROUNDS, drand_round
        rnd = drand_round(c.now + timedelta(days=31)) + BEACON_DELAY_ROUNDS
        c.add("exam_open", "bob", {"candidate": "bob", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd}, days=31)
        c.add("exam_draw", "bob", {"candidate": "bob", "degree": 2, "beacon": f"{rnd:064x}"}, days=0.34)
        st = c.state()
        ex = st.exams[("bob", 2)]
        self.assertIn("report", actions(next_steps(st, ex.examiners[0], st.time)))
        self.assertEqual(actions(next_steps(st, "bob", st.time)), ["wait"])


class OmHarness(unittest.TestCase):
    """Runs `om` against a scratch ledger founded by FOUNDERS, with the test-mode approval bypass."""

    def run_om(self, *args, env):
        return subprocess.run([sys.executable, "-m", "openmasonry", *args], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(REPO / "src"), **env})

    def setUp(self):
        self.tmp = tmpdir(self)
        self.led = self.tmp / "led"
        self.c = founded(self.tmp)
        self.led.mkdir()
        for e in self.c.entries:
            entry_file(self.led, e["seq"]).write_text(json.dumps(e))
        self.t0 = self.c.now

    def T(self, d):
        return (self.t0 + timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def env(self, who="hiram", approve=False):
        home = self.tmp / f"home-{who}"
        home.mkdir(exist_ok=True)
        (home / ".test-mode").write_text("tests only")       # the dialog bypass needs this marker + a scratch ledger
        key = home / "key"                                    # …and a signing key inside the temporary OM_HOME
        if not key.exists():
            shutil.copy2(self.c.keys[who][0], key)
            shutil.copy2(f"{self.c.keys[who][0]}.pub", f"{key}.pub")
        return {"OM_LOGIN": who, "OM_KEY": str(key), "OM_HOME": str(home),
                "OM_CONFIRM": "insecure-auto-approve-for-tests", "OM_CACHE": str(self.tmp / "cache")}

    def draft(self, *args, who="hiram", day=0.0):
        r = self.run_om(*args, "--ledger", str(self.led), "--time", self.T(day), "--json", env=self.env(who))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def approve(self, digest, who="hiram", day=0.0, ok=True, vote=None):
        extra = ["--test-vote", vote] if vote else []
        r = self.run_om("approve", digest[:16], "--no-submit", *extra, env=self.env(who, approve=True))
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r


class MemberCommands(OmHarness):
    """Drafts never sign; only `approve` (the person, via a dialog) signs exactly the draft."""

    def test_draft_signs_nothing_and_approve_signs_exactly_it(self):
        d = self.draft("work", "https://example.org/essay", day=1)
        self.assertFalse(entry_path(self.led, 1).exists())
        self.approve(d["digest"], day=1)
        signed = json.loads(entry_path(self.led, 1).read_text())
        self.assertEqual({k: v for k, v in signed.items() if k != "sig"}, d["entry"])

    def test_vote_reveal_and_refused_revote_keeps_the_sealed_vote(self):
        self.approve(self.draft("open", "amendment", "CONSTITUTION.md", "--sha256", "ab" * 32, "--id", "am", day=2)["digest"], day=2)
        d = self.draft("vote", "am", day=3)
        self.assertEqual(d["entry"]["body"]["commitment"], "0" * 64)       # the agent never knows the vote
        self.approve(d["digest"], day=3, vote="Yes")
        r = self.run_om("vote", "am", "--ledger", str(self.led), "--time", self.T(4), env=self.env())
        self.assertEqual(r.returncode, 1)
        self.assertIn("already sealed", r.stdout)
        vault = json.loads((self.tmp / "home-hiram" / "vault.json").read_text())
        self.assertEqual(list(vault.values())[0]["vote"], "yes")
        self.assertEqual(oct((self.tmp / "home-hiram" / "vault.json").stat().st_mode)[-3:], "600")
        rv = self.draft("reveal", "am", day=9.5)
        self.assertEqual(rv["entry"]["body"]["vote"], "(sealed)")          # the agent never sees the vote
        self.approve(rv["digest"], day=9.5)

    def test_would_be_refused_drafts_exit_1(self):
        r = self.run_om("vouch", "someone", "--ledger", str(self.led), "--time", self.T(1),
                        env={**self.env(), "OM_LOGIN": "stranger"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("WOULD BE REFUSED", r.stdout)

    def test_stale_draft_is_refused(self):
        d1 = self.draft("work", "https://a.example", day=1)
        d2 = self.draft("work", "https://b.example", day=1)
        self.approve(d1["digest"], day=1)
        r = self.approve(d2["digest"], day=1, ok=False)
        self.assertIn("STALE", r.stdout)

    def test_me_json_has_schema_and_argv(self):
        r = self.run_om("me", "--json", "--ledger", str(self.led), "--time", self.T(1), env=self.env())
        me = json.loads(r.stdout)
        self.assertEqual(me["schema"], "om.me/2")
        self.assertTrue(me["member"]["founding_architect"])
        self.assertTrue(all(isinstance(s["argv"], list) for s in me["steps"]))


class ApprovalIntegrity(MemberCommands):
    def test_tampered_draft_is_refused(self):
        d = self.draft("work", "https://example.org/harmless", day=1)
        p = self.tmp / "home-hiram" / "pending" / f"{d['digest']}.json"
        data = json.loads(p.read_text())
        data["entry"]["type"], data["entry"]["body"] = "depart", {}
        p.write_text(json.dumps(data))
        r = self.approve(d["digest"], day=1, ok=False)
        self.assertIn("TAMPERED", r.stdout)
        self.assertFalse(entry_path(self.led, 1).exists())

    def test_bypass_needs_the_marker(self):
        d = self.draft("work", "https://example.org/w", day=1)
        (self.tmp / "home-hiram" / ".test-mode").unlink()
        r = subprocess.run([sys.executable, "-m", "openmasonry", "approve", d["digest"][:16], "--no-submit"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, start_new_session=True,
                           env={**os.environ, "PYTHONPATH": str(REPO / "src"), "OM_HOME": str(self.tmp / "home-hiram"),
                                "OM_CONFIRM": "insecure-auto-approve-for-tests", "DISPLAY": "", "WAYLAND_DISPLAY": "",
                                "PATH": "/nonexistent"})   # no zenity/osascript: never a real dialog in tests
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(entry_path(self.led, 1).exists())


class Describe(unittest.TestCase):
    def test_dialog_text_is_built_from_the_entry_and_cleaned(self):
        from openmasonry.actions import describe
        e = {"type": "work", "actor": "hiram", "seq": 4, "time": "2027-01-01T00:00:00Z",
             "body": {"ref": "https://x.example/\x1b[2Jfake\x07"}}
        text = describe(None, e)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)
        self.assertIn("RECORD the work", text)
        self.assertIn("entry #4", text)


if __name__ == "__main__":
    unittest.main()
