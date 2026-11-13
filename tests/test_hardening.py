"""Regression tests: sponsors rule in the Guide, stale outbox entries and re-sequencing, canon text not yet
archived, key uniqueness and the judge's PR identity check, and the test-mode bypass. (The @protocol digest
is covered by tests/test_core.py.)"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from openmasonry import actions, canon, govern, identity
from openmasonry.crypto import canonical, sha256
from openmasonry.guide import next_steps
from openmasonry.ledger import Invalid, State, commitment, entry_hash, load, replay, sponsors_required
from tests.test_extended import founded_with_witness
from tests.test_guide import MemberCommands
from tests.test_protocol import (canon_digest, witness_subject, DECL, FOUNDERS, Chain, entry_file, entry_path, founded,
                                 genesis_body, gid, initiate, invite, petition)

REPO = Path(__file__).resolve().parents[1]


def tmpdir(test) -> Path:
    t = tempfile.TemporaryDirectory()
    test.addCleanup(t.cleanup)
    return Path(t.name)


def solo(tmp: Path) -> Chain:
    c = Chain(tmp)
    c.add("genesis", "hiram", genesis_body(c, ["hiram"], name="L"))
    return c


# -- A: the Guide follows the ledger's sponsor rule -------------------------------

class SponsorRule(unittest.TestCase):
    def test_sole_founder_is_offered_open_admission_with_one_sponsor(self):
        c = solo(tmpdir(self))
        petition(c, "alice")                       # the inviter is the one sponsor required
        st = c.state()
        self.assertEqual(sponsors_required(st, st.time), 1)
        self.assertIn("open_admission", [s.action for s in next_steps(st, "hiram", st.time)])
        alice = next_steps(st, "alice", st.time)
        self.assertEqual(alice[0].action, "wait")
        self.assertIn("1 of 1 sponsors", alice[0].why)
        c.add("ballot_open", "hiram", {"id": "adm-a", "kind": "admission", "subject": {"candidate": "alice"}})
        c.state()                                  # the ledger agrees

    def test_three_founders_still_need_two(self):
        c = founded(tmpdir(self))
        petition(c, "alice")
        st = c.state()
        self.assertEqual(sponsors_required(st, st.time), 2)
        self.assertIn("1 of 2 sponsors", next_steps(st, "alice", st.time)[0].why)
        self.assertNotIn("open_admission", [s.action for s in next_steps(st, "hiram", st.time)])


# -- C: an amendment pinning canon text that is not archived ------------------------

class CanonPending(unittest.TestCase):
    def amend(self, c: Chain, sha: str):
        c.add("ballot_open", "hiram", {"id": "am-c", "kind": "amendment",
                                       "subject": {"path": "canon/degrees.toml", "new_sha256": sha}})
        c.vote("am-c", {f: "yes" for f in FOUNDERS})

    def test_ratifying_unarchived_canon_text_is_refused_at_the_opening(self):
        c = founded(tmpdir(self))
        self.amend(c, "ee" * 32)
        with self.assertRaisesRegex(Invalid, "not archived"):
            c.state()

    def test_ratifying_archived_canon_text_closes(self):
        c = founded(tmpdir(self))
        self.amend(c, canon_digest())
        self.assertEqual(c.state().ballots["am-c"].result, "passed")

    def test_the_ballot_opens_only_once_the_new_canon_is_archived(self):
        c = founded(tmpdir(self))
        c.add("ballot_open", "hiram", {"id": "am-c", "kind": "amendment",
                                       "subject": {"path": "canon/degrees.toml", "new_sha256": "ee" * 32}})
        with self.assertRaisesRegex(Invalid, "add canon/history/" + "ee" * 32 + ".toml before opening this ballot .in an earlier pull request"):
            c.state()

    def test_readers_degrade_when_the_pinned_canon_is_missing(self):
        from openmasonry.actions import me_report
        from openmasonry.__main__ import state_report
        st = founded(tmpdir(self)).state()
        st.pins["canon/degrees.toml"] = "ee" * 32      # e.g. a clone missing canon/history/<sha>.toml
        me = me_report(st, "hiram", st.time)
        self.assertEqual(me["canon_pending"], "ee" * 32)
        self.assertEqual([s["action"] for s in me["steps"]], ["wait"])
        self.assertIsNone(me["member"]["title"])
        rep = state_report(st, st.time)
        self.assertEqual(rep["canon_pending"], "ee" * 32)
        self.assertIsNone(rep["members"][0]["title"])


# -- H: founding phase is exposed --------------------------------------------------

class FoundingPhaseExposed(unittest.TestCase):
    def test_state_and_me_expose_founding_phase(self):
        from openmasonry.actions import me_report
        from openmasonry.__main__ import state_report
        st = founded(tmpdir(self)).state()
        self.assertIs(state_report(st, st.time)["founding_phase"], True)
        self.assertIs(me_report(st, "hiram", st.time)["founding_phase"], True)
        self.assertIsNone(state_report(st, st.time)["canon_pending"])


# -- a key belongs to one login ----------------------------------------------------

class KeyUniqueness(unittest.TestCase):
    def test_petition_with_a_members_key_is_refused(self):
        c = founded(tmpdir(self))
        invite(c, "eve", by="ada")
        c.add("petition", "eve", {"key": c.key("hiram"), "declaration_sha256": DECL}, key_of="hiram")
        with self.assertRaisesRegex(Invalid, "already used by hiram"):
            c.state()

    def test_petition_with_a_pending_petitions_key_is_refused(self):
        c = founded(tmpdir(self))
        petition(c, "alice")
        invite(c, "bob")
        c.add("petition", "bob", {"key": c.key("alice"), "declaration_sha256": DECL}, key_of="alice")
        with self.assertRaisesRegex(Invalid, "already used by alice"):
            c.state()

    def test_petition_with_a_witness_key_is_refused(self):
        c = founded_with_witness(tmpdir(self))
        invite(c, "eve")
        c.add("petition", "eve", {"key": c.key("tyler"), "declaration_sha256": DECL}, key_of="tyler")
        with self.assertRaisesRegex(Invalid, "already used by tyler"):
            c.state()

    def test_departed_member_may_return_with_the_same_key(self):
        c = founded(tmpdir(self))
        initiate(c, "bob")
        c.add("depart", "bob", {})
        petition(c, "bob", days=91)
        self.assertIn("bob", c.state().petitions)

    def test_genesis_keys_must_be_distinct(self):
        c = Chain(tmpdir(self))
        k = c.key("hiram")
        c.add("genesis", "hiram", genesis_body(c, ["hiram"]) | {"founders": [
            {"login": "hiram", "key": k, "github_id": 1}, {"login": "ada", "key": k, "github_id": 2}]})
        with self.assertRaisesRegex(Invalid, "distinct keys"):
            c.state()


# -- the judge's PR identity check -------------------------------------------------

class PrIdentity(unittest.TestCase):
    def report(self, c: Chain, since: int, author: str, keys=None, fail=False):
        from openmasonry.verify import verify_report
        led = tmpdir(self) / "led"
        led.mkdir()
        for e in c.entries:
            entry_file(led, e["seq"]).write_text(json.dumps(e))
        a = argparse.Namespace(ledger=led, tree=False, online=False, clock_since=None, root=None,
                               pr_author=author, since=since, json=True)

        def fetch(login):
            if fail:
                raise OSError("network unreachable")
            return keys.get(login, []) if keys else []
        def user(login):                     # every login is the GitHub account the tests gave it
            if fail:
                raise OSError("network unreachable")
            return {"id": gid(login), "login": login}
        with mock.patch.object(identity, "fetch_github_keys", side_effect=fetch), \
                mock.patch.object(identity, "fetch_github_user", side_effect=user):
            return verify_report(a)

    def test_entries_must_be_signed_by_the_pr_author(self):
        c = founded(tmpdir(self))
        c.add("work", "ada", {"ref": "https://example.org/a"})
        self.assertTrue(self.report(c, 1, "ADA")["valid"])          # case-insensitive
        r = self.report(c, 1, "hiram")
        self.assertFalse(r["valid"])
        self.assertIn(f"ada is the GitHub account with id {gid('ada')}, but the pull request is by the account with id "
                      f"{gid('hiram')}", r["message"])

    def test_witness_entries_may_be_pushed_by_anyone(self):
        c = founded_with_witness(tmpdir(self))
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness", "subject": witness_subject(c, "node2")})
        c.add("ballot_close", "tyler", {"id": "w"}, days=11)
        self.assertTrue(self.report(c, 2, "witness-bot")["valid"])

    def test_petition_key_must_be_listed_on_github(self):
        c = founded(tmpdir(self))
        petition(c, "alice")                       # entry 1: hiram's invitation; entry 2: the petition
        self.assertTrue(self.report(c, 2, "alice", keys={"alice": [c.key("alice") + " laptop"]})["valid"])
        r = self.report(c, 2, "alice", keys={"alice": [c.key("other")]})
        self.assertFalse(r["valid"])
        self.assertIn("github.com/alice.keys", r["message"])

    def test_network_failure_fails_closed(self):
        c = founded(tmpdir(self))
        petition(c, "alice")
        r = self.report(c, 2, "alice", fail=True)
        self.assertFalse(r["valid"])
        self.assertIn("fail closed", r["message"])


# -- B, D, G: the outbox, re-sequencing and the test-mode bypass ---------------------

class Outbox(MemberCommands):
    def ledger_id(self):
        return entry_hash(json.loads(entry_path(self.led, 0).read_text()))[:16]

    def outbox(self, who="hiram") -> Path:
        d = self.tmp / f"home-{who}" / "outbox" / self.ledger_id()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def make_stale(self, seq: int, who="hiram"):
        """Move our signed entry `seq` back to the outbox (its PR never merged) …"""
        shutil.move(str(entry_path(self.led, seq)), str(self.outbox(who) / f"{seq:06d}.json"))

    def pending(self, *extra, who="hiram", day=0.0, code=0):
        r = self.run_om("pending", *extra, "--ledger", str(self.led), "--time", self.T(day), "--json", env=self.env(who))
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_merged_entry_is_cleaned_and_superseded_one_is_kept_as_stale(self):
        self.approve(self.draft("work", "https://example.org/a", day=1)["digest"], day=1)
        shutil.copy(entry_path(self.led, 1), self.outbox() / "000001.json")
        self.assertEqual(self.pending(day=1)["pending"], [])          # identical entry: merged
        self.assertFalse((self.outbox() / "000001.json").exists())
        self.make_stale(1)
        self.approve(self.draft("work", "https://example.org/ada", who="ada", day=1)["digest"], who="ada", day=1)
        items = self.pending(day=1)["pending"]
        self.assertEqual([(i["seq"], i["type"], i["state"]) for i in items], [(1, "work", "stale")])
        self.assertTrue((self.outbox() / "000001.json").exists())     # kept: it needs re-sequencing
        self.draft("work", "https://example.org/b", day=1.1)          # a stale entry does not block new drafts

    def test_stale_vote_frees_the_ballot_and_rebases_with_the_same_seal(self):
        self.approve(self.draft("open", "amendment", "CONSTITUTION.md", "--sha256", "ab" * 32, "--id", "am",
                                day=2)["digest"], day=2)
        self.approve(self.draft("vote", "am", day=3)["digest"], day=3, vote="Yes")
        sealed = json.loads((self.tmp / "home-hiram" / "vault.json").read_text())
        old = json.loads(entry_path(self.led, 2).read_text())["body"]["commitment"]
        self.make_stale(2)
        self.approve(self.draft("work", "https://example.org/ada", who="ada", day=3)["digest"], who="ada", day=3)
        self.assertEqual(self.pending(day=3)["pending"][0]["state"], "stale")
        self.draft("vote", "am", day=3.05)                            # not locked out
        d = self.pending("--rebase", "2", day=3.1, code=3)
        self.assertEqual(d["entry"]["seq"], 3)
        self.assertEqual(d["entry"]["body"]["commitment"], old)       # the same sealed vote
        self.approve(d["digest"], day=3.1)
        signed = json.loads(entry_path(self.led, 3).read_text())
        self.assertEqual((signed["actor"], signed["body"]["commitment"]), ("hiram", old))
        self.assertEqual(self.pending(day=3.1)["pending"], [])
        vault = json.loads((self.tmp / "home-hiram" / "vault.json").read_text())
        v = list(vault.values())[0]
        self.assertEqual((v["seq"], v.get("stale"), v["salt"]), (3, None, list(sealed.values())[0]["salt"]))
        self.approve(self.draft("reveal", "am", day=9.5)["digest"], day=9.5)

    def approve_here(self, digest: str, who="hiram"):
        """`om approve` in this process, with the dialog recorded instead of shown: (exit code or the refusal,
        [(title, text, buttons)])."""
        env = self.env(who) | {"OM_NO_CACHE": "1"}
        home = Path(env["OM_HOME"])
        shown = []

        def ask(title, text, buttons, ledger, test_answer=None, key=None, limit=1500):
            shown.append((title, text, buttons))
            return buttons[-1]
        patches = [mock.patch.dict(os.environ, env), mock.patch.object(actions, "_ask", ask)]
        patches += [mock.patch.object(actions, name, home / rel) for name, rel in
                    (("HOME", ""), ("PENDING", "pending"), ("VAULT", "vault.json"), ("CONFIG", "config.json"),
                     ("HEADS", "heads.json"))]
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
            for x in patches:
                stack.enter_context(x)
            try:
                result = actions.cmd_approve(argparse.Namespace(digest=digest[:16], no_submit=True, json=False,
                                                                test_vote=None))
            except actions.UserError as err:
                result = str(err)
        return result, shown

    def forge_rebase(self, d: dict, vote: str, who="hiram") -> str:
        """What an agent with write access to the pending drafts can do: mark a vote draft as a re-sealed one,
        name `vote` as the sealed vote and commit to it with the draft's own salt. Returns the forged digest."""
        p = self.tmp / f"home-{who}" / "pending" / f"{d['digest']}.json"
        draft = json.loads(p.read_text())
        p.unlink()
        bid, salt = draft["entry"]["body"]["id"], draft["secret"]["salt"]
        draft["entry"]["body"]["commitment"] = commitment(bid, who, vote, salt)
        draft["secret"] |= {"rebase": True, "vote": vote}
        draft["digest"] = sha256(canonical(draft["entry"]))
        (p.parent / f"{draft['digest']}.json").write_text(json.dumps(draft))
        return draft["digest"]

    def test_a_vote_marked_as_re_sealed_is_refused_unless_the_vault_sealed_it(self):
        self.approve(self.draft("open", "amendment", "CONSTITUTION.md", "--sha256", "ab" * 32, "--id", "am",
                                day=2)["digest"], day=2)
        forged = self.forge_rebase(self.draft("vote", "am", day=3), "yes")
        result, shown = self.approve_here(forged)
        self.assertIn("TAMPERED", str(result))
        self.assertEqual(shown, [])                                   # never offered for a signature
        self.assertFalse(entry_path(self.led, 2).exists())

    def test_a_re_sealed_vote_is_the_one_the_vault_holds_and_the_dialog_names_it(self):
        self.approve(self.draft("open", "amendment", "CONSTITUTION.md", "--sha256", "ab" * 32, "--id", "am",
                                day=2)["digest"], day=2)
        self.approve(self.draft("vote", "am", day=3)["digest"], day=3, vote="No")
        self.make_stale(2)
        self.approve(self.draft("work", "https://example.org/ada", who="ada", day=3)["digest"], who="ada", day=3)
        d = self.pending("--rebase", "2", day=3.1, code=3)
        forged = self.forge_rebase(d, "yes")                          # the vault holds NO
        result, shown = self.approve_here(forged)
        self.assertIn("TAMPERED", str(result))
        self.assertEqual(shown, [])
        d = self.pending("--rebase", "2", day=3.1, code=3)
        result, shown = self.approve_here(d["digest"])
        self.assertEqual(result, 0)
        (title, text, buttons), = shown
        self.assertEqual((title, buttons), ("OpenMasonry: re-seal your vote?", ["Approve and sign"]))
        self.assertIn("Your sealed vote: NO", text)

    def test_stale_vouch_is_rebased(self):
        self.c.key("alice")
        self.approve(self.draft("invite", "alice", "--github-id", "4242", day=1)["digest"], day=1)
        self.approve(self.draft("join", who="alice", day=1)["digest"], who="alice", day=1)
        self.approve(self.draft("vouch", "alice", who="ada", day=1)["digest"], who="ada", day=1)
        self.make_stale(3, who="ada")
        self.approve(self.draft("work", "https://example.org/c", who="carol", day=1)["digest"], who="carol", day=1)
        d = self.pending("--rebase", "3", who="ada", day=1.1, code=3)
        self.assertEqual((d["entry"]["seq"], d["entry"]["type"], d["entry"]["body"]), (4, "vouch", {"candidate": "alice"}))
        self.approve(d["digest"], who="ada", day=1.1)
        st = replay(load(self.led))
        self.assertEqual(st.petitions["alice"]["vouches"], ["hiram", "ada"])
        self.assertEqual(self.pending(who="ada", day=1.1)["pending"], [])

    def test_bypass_needs_the_key_inside_om_home(self):
        d = self.draft("work", "https://example.org/w", day=1)
        p = self.tmp / "home-hiram" / "pending" / f"{d['digest']}.json"
        data = json.loads(p.read_text())
        data["key"] = str(self.c.keys["hiram"][0])                    # a key outside OM_HOME (think ~/.ssh)
        p.write_text(json.dumps(data))
        import os
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "-m", "openmasonry", "approve", d["digest"][:16], "--no-submit"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, start_new_session=True,
                           env={**os.environ, **self.env(), "PYTHONPATH": str(REPO / "src"), "DISPLAY": "",
                                "WAYLAND_DISPLAY": "", "PATH": "/nonexistent"})
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("bypassed", r.stderr)
        self.assertFalse(entry_path(self.led, 1).exists())


# -- a candidate core is code of someone else's ----------------------------------------------------------------

class CandidateCore(unittest.TestCase):
    """`om verify --candidate-root DIR` runs the code of DIR as the person: never without their say."""

    def setUp(self):
        self.tmp = tmpdir(self)
        (self.tmp / "keys").mkdir()
        self.led = self.tmp / "led"
        for e in founded(self.tmp / "keys").entries:
            entry_file(self.led, e["seq"]).write_text(json.dumps(e))
        cand = self.tmp / "cand" / "src" / "openmasonry"
        cand.mkdir(parents=True)
        (cand / "__init__.py").write_text("")
        self.marker = self.tmp / "ran.txt"
        (cand / "verify.py").write_text(f"import json, pathlib\npathlib.Path({str(self.marker)!r}).write_text('ran')\n"
                                        "print(json.dumps({'valid': False, 'message': 'a refusal'}))\n")

    def om(self, *extra):
        import subprocess
        import sys
        return subprocess.run([sys.executable, "-m", "openmasonry", "verify", "--ledger", str(self.led),
                               "--candidate-root", str(self.tmp / "cand"), *extra], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env={**os.environ, "PYTHONPATH": str(REPO / "src"),
                                                             "OM_NO_CACHE": "1", "OM_HOME": str(self.tmp / "home")})

    def test_it_runs_nothing_without_the_flag(self):
        r = self.om()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--i-trust-this-code", r.stdout + r.stderr)
        self.assertIn("executes", r.stdout + r.stderr)
        self.assertFalse(self.marker.exists())

    def test_the_flag_runs_it(self):
        r = self.om("--i-trust-this-code")
        self.assertIn("CANDIDATE DIFFERS", r.stdout)
        self.assertTrue(self.marker.exists())

    def test_the_documents_say_it_runs_the_tree(self):
        for rel in ("docs/operations/RECOVERY.md", "docs/operations/LAUNCH.md", "docs/whitepaper/SPEC.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("--i-trust-this-code", text, rel)
            self.assertIn("disposable", text, rel)


if __name__ == "__main__":
    unittest.main()
