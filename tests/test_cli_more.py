"""What the Guide and the member commands tell a person in the cases a dress rehearsal found unclear.

The sponsorship budget, recusal and lapsed or timed-out exams, dormancy, the end of a key recovery, notices
after a departure, an undone admission and applied corrections, objections to an applied correction, a lot
whose beacon cannot be fetched, the empty ledger, the witnesses, the reasons of a scratch ledger, the
canonical guard of `om me` and the search of `om rules`.

The Guide tests are pure and use `Fast` (the "signature" of an entry is the public key that signed it); the
commands are run in-process with the state, the beacon and the canonical guard mocked, or through `om` on a
scratch ledger. Nothing touches the network.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from openmasonry import actions, crypto, verify
from openmasonry.__main__ import _custodian_line, _witness_line, state_report, witness_rows
from openmasonry.guide import custodian_steps, next_steps, notices, recusal_replacement, sponsorship_budget
from openmasonry.ledger import (BEACON_DELAY_ROUNDS, INVITE_EXPIRY_DAYS, PETITION_EXPIRY_DAYS, RECOVER_INTERVAL_DAYS,
                                custodian_message, custodian_revoke_message, drand_round, iso, load, rekey_message,
                                replay, signed_payload, ts)
from tests.test_cli_custodian import ADVICE, REASON_SHA, REASON_TEXT, Lodge
from tests.test_custodian import (REASON, SEVEN, advance, apply_, correct, freeze, lodge, open_ballot, quarry,
                                  undo)
from tests.test_guide import OmHarness, tmpdir
from tests.test_protocol import (FOUNDERS, T0, Chain, checkpoint, entry_file, entry_path, founded, genesis_body,
                                 initiate, invite, petition)
from tests.test_strict import DAY, SEC


URL = "https://example.org/work"


def kinds(st, login, now):
    return [n.kind for n in notices(st, login, now)]


def by_kind(st, login, now):
    return {n.kind: n for n in notices(st, login, now)}


def acts(st, login, now):
    return {s.action: s for s in next_steps(st, login, now)}


def drawn(c, who="alice", degree=2, days=31.0):
    """`who` opens the exam for `degree` and the lot is drawn; nobody reports. Returns the exam."""
    rnd = drand_round(c.now + timedelta(days=days)) + BEACON_DELAY_ROUNDS
    c.add("exam_open", who, {"candidate": who, "degree": degree, "work_ref": URL, "beacon_round": rnd}, days=days)
    c.add("exam_draw", who, {"candidate": who, "degree": degree, "beacon": f"{rnd:064x}"}, days=0.34)
    return c.state().exams[(who, degree)]


def run(fn, a) -> tuple[int | None, str]:
    """Run a command function in-process; (exit code or None when it raised UserError, what it printed)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = fn(a)
        except actions.UserError as err:
            return None, str(err)
    return code, out.getvalue()


class SponsorshipBudget(unittest.TestCase):
    """The Guide offers `sponsor` only within the ledger's own budget, and tells a candidate plainly when
    nobody can sponsor them."""

    def test_an_exhausted_budget_is_no_sponsor_step_and_om_me_shows_it(self):
        c = lodge(custodians=())
        for i in range(4):                                  # ada's four sponsorships at a time
            petition(c, f"cand{i}", by="ada")
        petition(c, "eve")                                  # hiram invites eve: one more sponsor is needed
        st = c.state()
        self.assertNotIn("sponsor", acts(st, "ada", st.time))
        self.assertIn("sponsor", acts(st, "carol", st.time))
        budget = sponsorship_budget(st, "ada", st.time)
        self.assertEqual((budget["used"], budget["allowed"], budget["invitations"]), (4, 4, []))
        self.assertEqual(budget["next_free_at"], iso(T0 + PETITION_EXPIRY_DAYS * DAY))
        c.add("vouch", "ada", {"candidate": "eve"})
        c.refused(self, "sponsorship budget exhausted")     # what the Guide no longer offers, the ledger refuses
        invite(c, "zed", by="carol")
        rep = actions.me_report(c.state(), "carol", c.now)
        self.assertEqual(rep["sponsorship"]["invitations"],
                         [{"login": "zed", "expires_at": iso(c.now + INVITE_EXPIRY_DAYS * DAY)}])
        self.assertEqual(rep["sponsorship"]["used"], 1)
        self.assertIsNone(actions.me_report(c.state(), "nobody", c.now)["sponsorship"])

    def test_nobody_left_to_sponsor_is_said_plainly(self):
        c = lodge(custodians=(), founders=["hiram", "ada"])
        for i in range(4):
            petition(c, f"cand{i}", by="ada")
        petition(c, "eve")                                  # 1 of the 2 sponsors; ada has no budget left
        st = c.state()
        (step,) = next_steps(st, "eve", st.time)
        self.assertEqual(step.action, "wait")
        self.assertNotIn("ask another", step.why)
        self.assertIn("nobody else can sponsor you now", step.why)
        self.assertIn(f"lapses at {iso(st.time + PETITION_EXPIRY_DAYS * DAY)}", step.why)
        self.assertIn(f"one sponsor suffices from {iso(st.time + 30 * DAY)}", step.why)    # the Founding Phase waiver
        self.assertEqual(step.due_by, iso(st.time + PETITION_EXPIRY_DAYS * DAY))


class Exams(unittest.TestCase):
    """What a recusal does, and why a candidate's exam ended."""

    def test_recusal_says_who_replaces_you_and_when_the_exam_lapses(self):
        c = lodge(custodians=())
        initiate(c, "alice")
        ex = drawn(c)
        st = c.state()
        first = ex.examiners[0]
        nxt = recusal_replacement(st, ex, first, st.time)
        why = acts(st, first, st.time)["recuse"].why
        if nxt is not None:                                 # the lot's order still holds someone
            self.assertIn(f"the next examiner in the lot's order ({nxt}) takes your place", why)
            c.add("exam_recuse", first, {"candidate": "alice", "degree": 2})
            st = c.state()
            self.assertEqual(st.exams[("alice", 2)].examiners[-1], nxt)
        while not c.state().exams[("alice", 2)].lapsed:     # step aside until nobody is left
            st = c.state()
            ex = st.exams[("alice", 2)]
            who = ex.examiners[0]
            if recusal_replacement(st, ex, who, st.time) is None:
                self.assertIn("so the exam lapses, with no penalty to alice", acts(st, who, st.time)["recuse"].why)
            c.add("exam_recuse", who, {"candidate": "alice", "degree": 2})
        st = c.state()
        n = by_kind(st, "alice", st.time)["exam_lapsed"]
        self.assertIn("an examiner stood aside", n.why)
        self.assertIn("you may open a new one at once", n.why)
        self.assertIn("exam", acts(st, "alice", st.time))
        row = next(e for e in state_report(st, st.time)["exams"] if e["candidate"] == "alice")
        self.assertEqual((row["lapsed"], row["timed_out"]), (True, False))

    def test_an_exam_without_verdicts_times_out_and_names_the_silent(self):
        c = lodge(custodians=())
        initiate(c, "alice")
        ex = drawn(c)
        later = ex.opened + 61 * DAY
        n = by_kind(c.state(), "alice", later)["exam_timed_out"]
        self.assertIn("no majority verdict came within 60 days", n.why)
        for x in ex.examiners:
            self.assertIn(x, n.why)
        row = next(e for e in state_report(c.state(), later)["exams"] if e["candidate"] == "alice")
        self.assertEqual((row["lapsed"], row["timed_out"]), (False, True))
        self.assertNotIn("exam_timed_out", kinds(c.state(), "alice", ex.opened + 30 * DAY))


class Dormancy(unittest.TestCase):
    """A dormant member is told so, with no deadline in the past."""

    def test_keep_alive_before_and_after_dormancy(self):
        c = lodge(custodians=())
        st = c.state()
        warn = acts(st, "carol", T0 + 320 * DAY)["keep_alive"]
        self.assertEqual(warn.due_by, iso(T0 + 365 * DAY))
        late = acts(st, "carol", T0 + 400 * DAY)["keep_alive"]
        self.assertIsNone(late.due_by)
        self.assertIn("You are dormant", late.why)
        self.assertIn("Recording a work brings you back", late.why)
        rep = actions.me_report(st, "carol", T0 + 400 * DAY)
        self.assertEqual((rep["member"]["dormant"], rep["member"]["last_activity"]), (True, iso(T0)))
        self.assertFalse(actions.me_report(st, "carol", T0 + 10 * DAY)["member"]["dormant"])


class Recoveries(unittest.TestCase):
    """Recoveries: a recovery that ended, `recover_apply`, the frozen wait, and the notice to
    Master Builders."""

    def requested(self):
        c = lodge()
        freeze(c, "ada", days=1)
        c.add("rekey_recover", "ada", {"key": c.key("ada-new"), "proof": c.key("ada-new")}, key_of="ada-new", days=1)
        return c, c.state().recoveries["ada"]

    def test_a_stopped_recovery_is_told_and_the_frozen_notice_points_at_nothing_refused(self):
        c, r = self.requested()
        c.add("rekey_object", "ada", {}, days=1)
        st = c.state()
        found = by_kind(st, "ada", c.now)
        self.assertIn("recovery_stopped", found)
        self.assertIn(f"accepted from {iso(c.now + RECOVER_INTERVAL_DAYS * DAY)}", found["recovery_stopped"].why)
        self.assertNotIn("bin/om recover --new-key", found["frozen"].why)
        self.assertIn("A new recovery of your key is accepted only from", found["frozen"].why)
        c.add("rekey_recover", "ada", {"key": c.key("ada-3"), "proof": c.key("ada-3")}, key_of="ada-3")
        c.refused(self, "less than 90 days ago")             # the ledger does refuse what the notice no longer offers

    def test_an_expired_recovery_is_told(self):
        """Co-signed, so its notice started at the request and it expires 60 days later, before a new request is
        accepted. (A request after a freeze that nobody co-signed restarts its notice at the drop and expires at the
        very moment a new request is accepted: there is nothing to tell then.)"""
        c, r = self.requested()
        for who in ("hiram", "carol"):
            c.add("rekey_cosign", who, {"login": "ada"})
        st, r = c.state(), c.state().recoveries["ada"]
        end = st.recovery_end(r, r.drop_time())
        self.assertEqual(end, r.time + 60 * DAY)
        n = by_kind(st, "ada", end + SEC)["recovery_expired"]
        self.assertIn(f"expired at {iso(end)}", n.why)
        self.assertNotIn("recovery_expired", kinds(st, "ada", r.time + (RECOVER_INTERVAL_DAYS + 1) * DAY))

    def test_frozen_wait_accounts_for_the_recovery_and_recover_apply_is_a_step_once_ready(self):
        c, r = self.requested()
        st = c.state()
        (wait,) = [s for s in next_steps(st, "ada", c.now) if s.action == "wait"]
        self.assertEqual(wait.opens_at, iso(st.recovery_end(r)))
        self.assertIn("A recovery of your key is under way", wait.why)
        cosign = by_kind(st, "carol", c.now)["recovery_cosign"]
        self.assertIn("A recovery of the key of ada", cosign.why)
        self.assertIn("0 of the 2", cosign.why)
        self.assertIsNone(cosign.correction)
        for who in ("hiram", "carol"):
            c.add("rekey_cosign", who, {"login": "ada"})
        st = c.state()
        self.assertNotIn("recovery_cosign", kinds(st, "carol", c.now))
        self.assertNotIn("recover_apply", acts(st, "ada", c.now))       # under notice
        ready = r.time + 21 * DAY
        step = acts(st, "ada", ready)["recover_apply"]
        self.assertEqual((step.argv, step.public, step.opens_at, step.due_by),
                         (["bin/om", "recover-apply"], True, iso(ready), iso(st.recovery_end(r))))
        c.add("rekey_recover_apply", "ada", {}, days=21, key_of="ada-new")   # the ledger takes it then
        self.assertEqual(c.state().members["ada"].key, c.key("ada-new"))


class AfterTheFact(unittest.TestCase):
    """No stale notice after a departure; an undone admission and applied corrections are told."""

    def test_a_departure_leaves_no_notice_about_the_person(self):
        c = lodge()
        correct(c, "hold_room", {"login": "carol"}, "identity_fraud", days=1)
        self.assertIn("room_hold", kinds(c.state(), "carol", c.now))
        c.add("depart", "carol", {}, days=1)
        self.assertEqual(kinds(c.state(), "carol", c.now), [])

    def test_an_undone_admission_is_told_with_its_reason(self):
        c = quarry(witnesses=("tyler",))
        initiate(c, "alice")
        u = undo(c, "adm-alice", days=1)
        apply_(c, u, days=14)
        st = c.state()
        n = by_kind(st, "alice", c.now)["voided"]
        self.assertEqual((n.correction, n.concerns_you), (u, True))
        for part in (f"correction {u}", "ground identity_fraud", f"ledger/reasons/{REASON}.md",
                     iso(c.now + 90 * DAY)):
            self.assertIn(part, n.why)
        (step,) = next_steps(st, "alice", c.now)
        self.assertEqual((step.action, step.opens_at), ("wait", iso(c.now + 90 * DAY)))

    def test_an_applied_correction_is_told_to_whom_it_concerns_for_a_time(self):
        c = quarry(witnesses=("tyler",))
        initiate(c, "alice")
        bid = advance(c, "alice", 2)
        u = undo(c, bid, days=1)
        apply_(c, u, days=14)
        st = c.state()
        n = by_kind(st, "alice", c.now)["correction_applied"]
        self.assertEqual((n.correction, n.until, n.may_object), (u, iso(c.now + 90 * DAY), False))
        self.assertIn(f"ballot {bid}", n.why)
        self.assertIn(f"ledger/reasons/{REASON}.md", n.why)
        self.assertNotIn("correction_applied", kinds(st, "alice", c.now + 91 * DAY))
        self.assertNotIn("correction_applied", kinds(st, "dan", c.now))         # it does not concern dan
        lapsed = by_kind(st, "alice", c.now)["exam_lapsed"]                   # the exam behind it no longer counts
        self.assertIn("the advancement it supported was undone", lapsed.why)


class Commands(unittest.TestCase):
    """The summaries of `om recuse` and `om depart`, and the canonical guard of `om me`: in-process,
    with the state mocked (a `Fast` chain) and nothing signed."""

    def ns(self, **kw):
        return argparse.Namespace(**({"ledger": Path("/nonexistent/ledger/entries"), "login": "hiram", "key": None,
                                      "time": None, "json": False} | kw))

    def test_an_objection_to_an_applied_correction_is_refused_before_drafting(self):
        c = quarry(witnesses=("tyler",))
        initiate(c, "alice")
        u = undo(c, "adm-alice", days=1)
        apply_(c, u, days=14)
        st = c.state()
        with mock.patch.object(actions, "state_of", return_value=st), mock.patch.object(actions, "propose") as p:
            code, msg = run(actions.cmd_object, self.ns(seq=u, login="dan", time=iso(c.now)))
        self.assertIsNone(code)
        p.assert_not_called()
        self.assertEqual(msg, f"correction {u} was applied at {iso(c.now)}: an objection no longer changes it (an "
                              "applied correction is never voided), so none is drafted")
        c.add("correction_object", "dan", {"seq": u})        # the ledger would record it, and change nothing
        self.assertEqual(c.state().members["alice"].status, "voided")

    def test_a_beacon_that_cannot_be_fetched_is_one_clear_message(self):
        c = lodge(custodians=())
        initiate(c, "alice")
        rnd = drand_round(c.now + 31 * DAY) + BEACON_DELAY_ROUNDS
        c.add("exam_open", "alice", {"candidate": "alice", "degree": 2, "work_ref": URL, "beacon_round": rnd}, days=31)
        st = c.state()
        with mock.patch.object(actions, "state_of", return_value=st), \
                mock.patch("openmasonry.beacon.fetch", side_effect=RuntimeError("offline")), \
                mock.patch.object(actions, "propose") as p:
            code, msg = run(actions.cmd_draw, self.ns(candidate=None, beacon=None, time=iso(c.now + 1 * DAY)))
            self.assertIsNone(code)
            p.assert_not_called()
            self.assertEqual(msg, f"the public drand beacon (round {rnd}) could not be fetched: retry when online, or "
                                  "pass a beacon fetched elsewhere with --beacon HEX")
            run(actions.cmd_draw, self.ns(candidate=None, beacon="ab" * 32, time=iso(c.now + 1 * DAY)))
            self.assertEqual(p.call_args.args[2]["beacon"], "ab" * 32)       # --beacon needs no network

    def test_recuse_and_depart_summaries_say_what_happens(self):
        c = lodge(custodians=())
        initiate(c, "alice")
        ex = drawn(c)
        st = c.state()
        who = ex.examiners[0]
        nxt = recusal_replacement(st, ex, who, c.now)
        with mock.patch.object(actions, "state_of", return_value=st), mock.patch.object(actions, "propose") as p:
            run(actions.cmd_recuse, self.ns(candidate="alice", degree=2, login=who, time=iso(c.now)))
            summary = p.call_args.args[3]
            self.assertTrue(summary.startswith("Recuse yourself from alice's 2° examination: "))
            self.assertIn(f"({nxt}) takes your place" if nxt else "so the exam lapses", summary)
            run(actions.cmd_depart, self.ns())
            self.assertEqual(p.call_args.args[3], "Leave the fraternity (a Master Builder may invite you again after "
                                                  "90 days; you would return at the 1st degree)")

    def test_om_me_on_a_rewound_canonical_ledger_shows_only_the_message(self):
        st = lodge(custodians=()).state()
        msg = "ROLLBACK — the canonical ledger no longer contains entry 3"
        with mock.patch.object(actions, "state_of", return_value=st), \
                mock.patch.object(actions, "is_repo_ledger", return_value=True), \
                mock.patch.object(actions, "canonical_guard", return_value=("rollback", msg)) as guard, \
                mock.patch.object(actions, "outbox", return_value=([], [])):
            code, out = run(actions.cmd_me, self.ns(json=True, as_custodian=None, time=iso(T0 + DAY)))
            guard.assert_called_once_with(st.hashes)
            rep = json.loads(out)
            self.assertEqual(rep["canonical"], {"verdict": "rollback", "message": msg})
            self.assertEqual([(s["action"], s["why"], s["argv"]) for s in rep["steps"]], [("wait", msg, [])])
            code, out = run(actions.cmd_me, self.ns(as_custodian=None, time=iso(T0 + DAY)))
            self.assertTrue(out.startswith(msg))
            self.assertNotIn(" 1. ", out)
            self.assertEqual(out.count(msg), 1)


class Reads(unittest.TestCase):
    """Custodian lines, witnesses, stays, the removal ballot of one's custodian key, and `om rules`."""

    def test_a_dead_custodian_has_no_deadline_and_the_live_one_does(self):
        c = lodge()
        rep = state_report(c.state(), T0 + 200 * DAY)
        line = _custodian_line(rep["custodians"][0])
        self.assertIn(f"lapsed since {iso(T0 + 180 * DAY + SEC)}", line)
        self.assertNotIn("due again", line)
        live = state_report(c.state(), T0 + DAY)["custodians"][0]
        self.assertIsNone(live["ended_at"])
        self.assertIn("due again by", _custodian_line(live))

    def test_witnesses_are_listed_with_their_latest_checkpoint(self):
        c = lodge(custodians=(), witnesses=("tyler", "node2"))
        e = c.add("witness", "tyler", checkpoint(c.state()), days=1)
        st = c.state()
        rows = {w["name"]: w for w in witness_rows(st, c.now, c.entries)}
        self.assertEqual((rows["tyler"]["last_checkpoint_seq"], rows["tyler"]["last_checkpoint_time"]), (e["seq"], e["time"]))
        self.assertEqual((rows["node2"]["last_checkpoint_seq"], rows["node2"]["frozen_until"]), (None, None))
        self.assertTrue(rows["tyler"]["key_fingerprint"].startswith("SHA256:"))
        self.assertIn("no checkpoint yet", _witness_line(rows["node2"]))
        self.assertEqual(state_report(st, c.now, c.entries)["witnesses"], list(rows.values()))

    def test_a_stay_wait_has_its_end_and_a_removal_ballot_is_told_to_the_custodians_member(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN)
        open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"})
        st = c.state()
        n = by_kind(st, "gus", c.now)["custodian_removal"]
        self.assertIn("Ballot rm, on the removal of the custodian key warden that you hold, is open", n.why)
        self.assertNotIn("custodian_removal", kinds(st, "fay", c.now))
        open_ballot(c, "s", "ada", "sanction", {"member": "carol", "measure": "admonish"})
        seq = correct(c, "stay", {"ballot": "s"}, by="keeper", days=1)
        st = c.state()
        (wait,) = [s for s in next_steps(st, "dan", c.now) if s.action == "wait" and "Ballot s" in s.why]
        self.assertEqual(wait.opens_at, iso(st.span(st.corrections[seq])[1]))

    def test_rules_find_black_balls_however_spelled_and_read_more_sources(self):
        for topic in ("blackball", "black ball", "black-balls"):
            sources = {h["source"] for h in actions.rule_sources(topic, limit=20)}
            self.assertIn("docs/whitepaper/WHITEPAPER.md", sources, topic)
        self.assertIn("docs/whitepaper/SPEC.md", {h["source"] for h in actions.rule_sources("rekey_cosign")})
        study = {h["source"] for h in actions.rule_sources("apprentice masterwork", limit=50)}
        self.assertTrue(any(s.startswith("docs/study/") for s in study), study)
        for rel in actions.RULE_SOURCES:
            self.assertTrue((actions.canon.ROOT / rel).is_file(), rel)


class NeverAdvice(unittest.TestCase):
    """The Guide's rule: no new step is an objection, a co-signature, a removal or a correction, and nothing
    it says advises."""

    def test_new_steps_and_notices_never_advise(self):
        c = quarry(witnesses=("tyler",))
        initiate(c, "alice")
        u = undo(c, "adm-alice", days=1)
        freeze(c, "ada")
        c.add("rekey_recover", "ada", {"key": c.key("ada-new"), "proof": c.key("ada-new")}, key_of="ada-new")
        open_ballot(c, "rm", "dan", "custodian", {"remove": "warden"})
        apply_(c, u, days=14)
        st = c.state()
        for when in (c.now, c.now + 30 * DAY, c.now + 400 * DAY):
            for who in (*SEVEN, "alice", "nobody"):
                for s in next_steps(st, who, when):
                    self.assertNotIn(s.action, {"object", "cosign", "recover_cosign", "recover_oppose", "remove",
                                                "correct", "recover_object"})
                    self.assertIsNone(re.search(ADVICE, s.why), s.why)
                for n in notices(st, who, when):
                    self.assertIsNone(re.search(ADVICE, n.why), n.why)
        self.assertEqual(custodian_steps(st, "nobody", c.now), [])


class EmptyLedger(OmHarness):
    """`om state`, `om witnesses`, `om me` and `om draw --help` before genesis, through `om` on an empty scratch ledger."""

    def setUp(self):
        self.tmp = tmpdir(self)
        self.led = self.tmp / "ledger" / "entries"
        self.led.mkdir(parents=True)

    def om(self, *args):
        r = self.run_om(*args, "--ledger", str(self.led), env={"OM_LOGIN": "hiram", "OM_HOME": str(self.tmp / "home")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_state_witnesses_and_me_say_the_ledger_is_empty(self):
        empty = "The ledger is empty: the fraternity has not been founded yet."
        self.assertEqual(self.om("state").strip(), empty)
        self.assertNotIn("founding phase", self.om("state"))
        rep = json.loads(self.om("state", "--json"))
        self.assertEqual((rep["schema"], rep["founding_phase"], rep["members"], rep["witnesses"], rep["entries"]),
                         ("om.state/2", None, [], [], 0))
        self.assertEqual(self.om("witnesses").strip(), empty)
        self.assertEqual(json.loads(self.om("witnesses", "--json"))["witnesses"], [])
        self.assertEqual(self.om("me").splitlines(),
                         [empty, "Founding it is the founder's act: see docs/operations/LAUNCH.md (bin/om genesis)."])
        me = json.loads(self.om("me", "--json"))
        self.assertEqual((me["schema"], me["before_genesis"], me["steps"]), ("om.me/2", True, []))
        self.assertIn("docs/operations/LAUNCH.md", me["launch"])

    def test_draw_help_shows_the_beacon_flag(self):
        r = self.run_om("draw", "--help", env={})
        self.assertIn("--beacon HEX", r.stdout)


class ScratchReasons(Lodge):
    """`verify --tree` of a scratch ledger without --root reads the reasons beside its entries."""

    def verify(self, *extra):
        p = argparse.ArgumentParser()
        verify.add_arguments(p)
        return verify.verify_report(p.parse_args(["--ledger", str(self.led), "--tree", *extra]))

    def test_the_reasons_of_a_scratch_ledger_are_its_own(self):
        self.chain("correction", "warden", {"act": "freeze_key", "target": {"login": "ada"}, "ground": "key_compromised",
                                            "reason_sha256": REASON_SHA}, day=1)
        missing = f"reasons/{REASON_SHA}.md is missing"
        rep = self.verify()
        self.assertTrue(rep["valid"], rep["message"])
        self.assertTrue(any(missing in w for w in rep["warnings"]), rep["warnings"])
        here = self.led.parent / "reasons"
        here.mkdir()
        (here / f"{REASON_SHA}.md").write_text(REASON_TEXT, encoding="utf-8")
        rep = self.verify()
        self.assertTrue(rep["valid"], rep["message"])
        self.assertFalse(any(REASON_SHA in w for w in rep["warnings"]), rep["warnings"])
        (here / "stray.md").write_text("not a reason\n", encoding="utf-8")
        rep = self.verify()
        self.assertFalse(rep["valid"])
        self.assertIn("reasons/stray.md: no correction of the ledger pins this file", rep["message"])
        rep = self.verify("--root", str(actions.canon.ROOT))            # with --root: the tree's ledger/reasons/
        self.assertTrue(any(f"ledger/reasons/{REASON_SHA}.md is missing" in w for w in rep["warnings"]), rep["warnings"])



# ---------------------------------------------------------------- claims, succession, re-runs ----

ADVICE = r"(?i)\b(should|recommend|suggest|advise|ought)"


CLAIM_WORDS = ("claim-custodian", "object-claim", "apply-claim", "claim-succession")


def keygen(path: Path, kind: str = "ed25519") -> Path:
    subprocess.run(["ssh-keygen", "-q", "-t", kind, "-N", "", "-C", path.name, "-f", str(path)], check=True)
    return path


def bare(path: Path) -> str:
    return " ".join(Path(f"{path}.pub").read_text().split()[:2])


def make_master(c: Chain, who: str = "alice") -> None:
    """`who` is admitted and advanced to the 3rd degree by the three founders: a Master who is not a founder."""
    initiate(c, who)
    for degree, days in ((2, 31), (3, 61)):
        c.exam(who, degree, days=days)
        c.add("ballot_open", who, {"id": f"adv-{who}-{degree}", "kind": "advancement",
                                   "subject": {"member": who, "degree": degree}})
        c.vote(f"adv-{who}-{degree}", {f: "yes" for f in FOUNDERS})


def claim_body(c: Chain, name: str = "keeper", founder: str = "hiram") -> dict:
    key, revoke = c.key(name), c.key(f"{name}-revoke")
    return {"name": name, "key": key, "revoke_key": revoke,
            "proof": c.prove(name, custodian_message(name, founder, key)),
            "revoke_proof": c.prove(f"{name}-revoke", custodian_revoke_message(name, key, revoke))}


def claim_kinds(st, login, now) -> dict:
    return {n.kind: n for n in notices(st, login, now)}


class ClaimHarness(OmHarness):
    """OmHarness (three founders, no custodian key at all) with the chain kept in step with the scratch ledger."""

    def sync(self):
        for e in self.c.entries:
            p = entry_path(self.led, e["seq"])
            if not p.exists():
                entry_file(self.led, e["seq"]).write_text(json.dumps(e))

    def reload(self):
        self.c.entries = load(self.led)
        self.c.now = max(self.c.now, ts(self.c.entries[-1]["time"]))
        return self.c.entries[-1]

    def later(self, days: float = 0.01) -> float:
        """The day (from t0) `days` after the chain's last entry, for `--time`."""
        return (self.c.now - self.t0) / DAY + days

    def om_(self, *args, who="hiram", day=0.0):
        return self.run_om(*args, "--ledger", str(self.led), "--time", self.T(day), env=self.env(who))

    def act(self, *args, who="hiram", day=0.0):
        self.approve(self.draft(*args, who=who, day=day)["digest"], who=who)
        return self.reload()

    def state(self):
        return replay(load(self.led))


class ClaimCustodianCommand(ClaimHarness):
    def keys(self, name="keeper"):
        home = Path(self.env("hiram")["OM_HOME"])
        return keygen(home / name), keygen(home / f"{name}-revoke")

    def test_drafted_with_placeholders_and_approved_with_both_proofs(self):
        k, r = self.keys()
        d = self.draft("claim-custodian", "keeper", "--custodian-key", str(k), "--revoke-key", f"{r}.pub", day=1)
        key, revoke = bare(k), bare(r)
        self.assertEqual(d["entry"]["type"], "custodian_claim")
        self.assertEqual(d["entry"]["actor"], "hiram")
        self.assertEqual(d["entry"]["body"], {"name": "keeper", "key": key, "revoke_key": revoke,
                                              "proof": actions.CUSTODIAN_PROOF_PENDING,
                                              "revoke_proof": actions.CUSTODIAN_PROOF_PENDING})
        for words in ("30 days of notice", "day 60", actions.fingerprint(key), actions.fingerprint(revoke),
                      "bin/om apply-claim 1", "offline"):
            self.assertIn(words, d["summary"])
        self.assertNotIn(str(k), json.dumps(d))                      # the private key paths stay in the draft
        text = actions.describe(self.state(), d["entry"])             # the dialog
        self.assertIn(actions.fingerprint(key), text)
        self.assertIn(actions.fingerprint(revoke), text)
        self.assertFalse(entry_path(self.led, 1).exists())
        self.approve(d["digest"])
        signed = json.loads(entry_path(self.led, 1).read_text())
        b = signed["body"]
        self.assertTrue(crypto.signature_valid(custodian_message("keeper", "hiram", key), b["proof"], key))
        self.assertTrue(crypto.signature_valid(custodian_revoke_message("keeper", key, revoke), b["revoke_proof"], revoke))
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], self.c.keys["hiram"][1]))
        cl = self.state().claims[1]                                   # the real verifier accepts it
        self.assertEqual((cl.founder, cl.name, cl.key, cl.revoke_key), ("hiram", "keeper", key, revoke))

    def test_refused_at_approval_without_both_private_keys(self):
        k, r = self.keys()
        d = self.draft("claim-custodian", "keeper", "--custodian-key", str(k), "--revoke-key", str(r), day=1)
        r.unlink()                                                    # only the public half is left
        res = self.approve(d["digest"], ok=False)
        self.assertIn("the private half of the revoke key of the claimed custodian keeper", res.stdout)
        self.assertIn("both private keys must be present when the claim is approved", res.stdout)
        self.assertFalse(entry_path(self.led, 1).exists())

    def test_refused_at_the_draft(self):
        k, r = self.keys()
        initiate(self.c, "alice")
        self.sync()
        day = self.later()
        res = self.om_("claim-custodian", "keeper", "--custodian-key", str(k), "--revoke-key", str(r), who="alice", day=day)
        self.assertEqual(res.returncode, 1)
        self.assertIn("alice is not a founder: only a founder may claim the Custodian office", res.stdout)
        res = self.om_("claim-custodian", "keeper", "--custodian-key", str(k), "--revoke-key", str(k), day=day)
        self.assertEqual(res.returncode, 1)
        self.assertIn("the custodian key and the revoke key are the same key", res.stdout)
        ecdsa = keygen(Path(self.env("hiram")["OM_HOME"]) / "ecdsa", "ecdsa")
        res = self.om_("claim-custodian", "keeper", "--custodian-key", str(ecdsa), "--revoke-key", str(r), day=day)
        self.assertEqual(res.returncode, 1)
        self.assertIn("(the custodian key): keys must be ssh-ed25519", res.stdout)
        res = self.om_("claim-custodian", "ada", "--custodian-key", str(k), "--revoke-key", str(r), day=day)
        self.assertEqual(res.returncode, 1)                           # the protocol's own refusal
        self.assertIn("WOULD BE REFUSED", res.stdout)
        self.assertIn("the custodian name 'ada' is held by the member", res.stdout)

    def test_a_stale_claim_is_not_re_sequenced(self):
        with self.assertRaisesRegex(actions.UserError, r"entry #5 \(custodian_claim\) carries proofs of possession .* "
                                                       r"\(bin/om pending --drop 5\)"):
            actions._rebase(SimpleNamespace(rebase=-1), self.state(),
                            [{"seq": 5, "type": "custodian_claim", "actor": "hiram", "body": {}}])


class ClaimApplyCommand(ClaimHarness):
    def test_applied_by_its_founder_after_the_notice(self):
        self.c.now = self.t0 + 1 * DAY
        seq = self.c.add("custodian_claim", "hiram", claim_body(self.c))["seq"]
        self.sync()
        start = self.c.now
        res = self.om_("apply-claim", str(seq), day=20)
        self.assertEqual(res.returncode, 1)
        self.assertIn(f"WOULD BE REFUSED — entry {seq + 1}: the claim of entry {seq} is under notice until", res.stdout)
        res = self.om_("apply-claim", str(seq), who="ada", day=31.1)
        self.assertIn(f"only hiram, who signed the claim of entry {seq}, applies it", res.stdout)
        d = self.draft("apply-claim", str(seq), day=31.1)
        self.assertEqual(d["entry"]["body"], {"seq": seq})
        self.assertIn("by the founder hiram, as keeper", d["summary"])
        self.assertIn(f"applied not later than {(start + timedelta(days=60)).strftime('%Y-%m-%dT%H:%M:%SZ')}", d["summary"])
        self.approve(d["digest"])
        st = self.state()
        self.assertEqual(st.custodians_live(st.time), ["keeper"])
        self.assertEqual(st.claim_status(st.claims[seq], st.time), "applied")


class ClaimObjectCommand(ClaimHarness):
    def setUp(self):
        super().setUp()
        make_master(self.c)                                           # alice: a Master who is not a founder
        self.c.now += DAY
        self.seq = self.c.add("custodian_claim", "hiram", claim_body(self.c))["seq"]
        self.sync()

    def test_a_master_who_is_not_a_founder_objects(self):
        res = self.om_("object-claim", str(self.seq), who="ada", day=self.later())
        self.assertEqual(res.returncode, 1)
        self.assertIn("only a Master Builder who is not a founder may object to a claim of the Custodian office",
                      res.stdout)
        d = self.draft("object-claim", str(self.seq), who="alice", day=self.later())
        self.assertEqual(d["entry"]["body"], {"seq": self.seq})
        self.assertIn(f"Object to the claim of the Custodian office of entry {self.seq} (by the founder hiram, as keeper",
                      d["summary"])
        self.assertIn("One objection is enough", d["summary"])
        self.approve(d["digest"], who="alice")
        st = self.state()
        self.assertEqual((st.claims[self.seq].objector, st.claim_status(st.claims[self.seq], st.time)),
                         ("alice", "objected"))
        res = self.om_("apply-claim", str(self.seq), day=self.later(31))
        self.assertIn(f"the claim of entry {self.seq} is objected", res.stdout)

    def test_the_pending_claim_is_told_to_its_founder_and_to_who_may_object(self):
        st, now = self.c.state(), self.c.now
        mine = claim_kinds(st, "hiram", now)["claim_pending"]
        self.assertIn(f"Your claim of the Custodian office as keeper (entry {self.seq}) is under notice until", mine.why)
        self.assertIn(f"bin/om apply-claim {self.seq}", mine.why)
        self.assertEqual(mine.until, (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        other = claim_kinds(st, "alice", now)["claim_pending"]
        self.assertIn(f"bin/om object-claim {self.seq}", other.why)
        self.assertTrue(other.may_object)
        self.assertEqual(other.object_until, (now + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        for who in ("ada", "carol"):                                  # other founders: no objection, no new claim
            self.assertNotIn("claim_pending", claim_kinds(st, who, now))
            self.assertNotIn("custodian_claim", claim_kinds(st, who, now))
        for who in ("hiram", "alice"):
            for n in notices(st, who, now):
                self.assertNotRegex(n.why, ADVICE)
            for s in next_steps(st, who, now):
                self.assertFalse(any(w in s.argv for w in CLAIM_WORDS), s)


class ClaimNotices(unittest.TestCase):
    def setUp(self):
        import tempfile
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)

    def test_a_founder_where_no_custodian_key_is_live_is_told_and_it_is_never_a_step(self):
        c = Chain(self.tmp)
        c.add("genesis", FOUNDERS[0], genesis_body(c, custodians=("warden",)))
        st = c.state()
        self.assertNotIn("custodian_claim", claim_kinds(st, "hiram", T0 + DAY))          # warden is live
        later = T0 + 181 * DAY                                                    # silent: lapsed
        n = claim_kinds(st, "hiram", later)["custodian_claim"]
        for words in ("you may take up the Custodian office again",
                      "bin/om claim-custodian NAME --custodian-key PATH --revoke-key PATH",
                      "30 days of notice", "one active Master Builder who is not a founder can stop it", "day 60"):
            self.assertIn(words, n.why)
        self.assertNotRegex(n.why, ADVICE)
        self.assertTrue(n.concerns_you)
        self.assertIn("custodian_claim", claim_kinds(st, "carol", later))                # any founder
        self.assertNotIn("custodian_claim", claim_kinds(st, "stranger", later))
        for s in next_steps(st, "hiram", later):
            self.assertFalse(any(w in s.argv for w in CLAIM_WORDS), s)

    def test_never_once_a_claim_is_pending_nor_for_a_member_who_is_not_a_founder(self):
        c = Chain(self.tmp)
        c.add("genesis", FOUNDERS[0], genesis_body(c))
        initiate(c, "alice")
        st = c.state()
        self.assertIn("custodian_claim", claim_kinds(st, "ada", c.now))
        self.assertNotIn("custodian_claim", claim_kinds(st, "alice", c.now))
        c.add("custodian_claim", "hiram", claim_body(c), days=1)
        st = c.state()
        self.assertNotIn("custodian_claim", claim_kinds(st, "ada", c.now))
        self.assertNotIn("claim_pending", claim_kinds(st, "alice", c.now))               # 1st degree: no objection

    def test_succession_is_told_to_a_member_below_the_third_degree_where_no_master_is_left(self):
        c = Chain(self.tmp)
        c.add("genesis", FOUNDERS[0], genesis_body(c))
        initiate(c, "alice")
        self.assertNotIn("succession", claim_kinds(c.state(), "alice", c.now))
        for f in FOUNDERS:
            c.add("depart", f, {}, days=0.01)
        st = c.state()
        n = claim_kinds(st, "alice", c.now)["succession"]
        self.assertIn("A member below the 3rd degree may claim the succession (bin/om claim-succession)", n.why)
        self.assertNotRegex(n.why, ADVICE)
        self.assertFalse(any(w in s.argv for s in next_steps(st, "alice", c.now) for w in CLAIM_WORDS))
        c.add("succession_claim", "alice", {}, days=0.01)
        st = c.state()
        n = claim_kinds(st, "alice", c.now)["succession"]
        self.assertIn("A succession claim was made by alice", n.why)
        self.assertEqual(n.until, (c.now + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        n = claim_kinds(st, "alice", c.now + timedelta(days=91))["succession"]
        self.assertIn("is in force", n.why)
        self.assertIn("You are one of them.", n.why)


class ClaimSuccessionCommand(ClaimHarness):
    def test_drafted_by_a_member_below_the_third_degree_where_no_master_is_left(self):
        res = self.om_("claim-succession", day=1)
        self.assertEqual(res.returncode, 1)
        self.assertIn("a Master Builder needs no succession", res.stdout)
        initiate(self.c, "alice")
        for f in FOUNDERS:
            self.c.add("depart", f, {}, days=0.01)
        self.sync()
        d = self.draft("claim-succession", who="alice", day=self.later())
        self.assertEqual((d["entry"]["type"], d["entry"]["body"]), ("succession_claim", {}))
        self.assertIn("Any entry a Master Builder signs within 90 days cancels it", d["summary"])
        self.assertIn("until 3 active Master Builders exist", d["summary"])
        self.approve(d["digest"], who="alice")
        st = self.state()
        self.assertEqual((st.succession.by, st.succession_status(st.time)), ("alice", "pending"))
        res = self.om_("claim-succession", who="alice", day=self.later(1))
        self.assertIn("a succession claim is already pending", res.stdout)


class ClaimRerunCommand(ClaimHarness):
    SUBJECT = {"path": "README.md", "new_sha256": "ab" * 32}

    def lapsed(self):
        self.c.add("ballot_open", "hiram", {"id": "am", "kind": "amendment", "subject": self.SUBJECT}, days=1)
        self.c.add("ballot_close", "hiram", {"id": "am"}, days=10.3)   # nobody voted: no quorum
        self.sync()
        self.assertEqual(self.c.state().ballots["am"].result, "lapsed")

    def test_a_lapsed_ballot_is_re_run(self):
        self.lapsed()
        args = ("open", "amendment", "README.md", "--sha256", "ab" * 32, "--id", "am-2", "--rerun", "am")
        res = self.om_(*args, "--commit-days", "6", day=self.later())
        self.assertIn("WOULD BE REFUSED", res.stdout)
        self.assertIn("a re-run gives at least 7 days to commit", res.stdout)
        d = self.draft(*args, day=self.later())
        self.assertEqual(d["entry"]["body"], {"id": "am-2", "kind": "amendment", "subject": self.SUBJECT, "rerun": "am"})
        self.assertIn("It re-runs the lapsed ballot am", d["summary"])
        self.assertIn("This re-runs the lapsed ballot am", actions.describe(self.state(), d["entry"]))
        self.approve(d["digest"])
        b = self.state().ballots["am-2"]
        self.assertEqual((b.rerun, b.quorum_base()), ("am", 1))
        res = self.om_("open", "amendment", "README.md", "--sha256", "ab" * 32, "--id", "am-3", "--rerun", "am",
                       who="ada", day=self.later())
        self.assertIn("ballot am was re-run already, by ballot am-2", res.stdout)

    def test_an_amendment_chooses_its_windows_and_no_other_kind_does(self):
        d = self.draft("open", "amendment", "README.md", "--sha256", "ab" * 32, "--id", "am",
                       "--commit-days", "14", "--reveal-days", "5", day=1)
        self.assertEqual((d["entry"]["body"]["commit_days"], d["entry"]["body"]["reveal_days"]), (14, 5))
        self.assertIn("with 14 days to commit and 5 to reveal", d["summary"])
        self.assertIn("14 days to commit, 5 to reveal.", actions.describe(self.state(), d["entry"]))
        res = self.om_("open", "sanction", "ada", "--measure", "admonish", "--commit-days", "14", day=1)
        self.assertIn("WOULD BE REFUSED", res.stdout)
        self.assertIn("a sanction ballot has fixed windows", res.stdout)


class ClaimRecoverOpposeCommand(ClaimHarness):
    def test_a_master_opposes_an_open_recovery(self):
        old, new = self.c.keys["ada"][1], self.c.key("ada-new")
        self.c.add("rekey_recover", "ada", {"key": new, "proof": self.c.prove("ada-new", rekey_message("ada", old, new))},
                   days=1, key_of="ada-new")
        self.sync()
        res = self.om_("recover-oppose", "ada", who="ada", day=self.later())
        self.assertIn("WOULD BE REFUSED", res.stdout)
        self.assertIn("a member stops the recovery of their own key with rekey_object", res.stdout)
        d = self.draft("recover-oppose", "ada", who="carol", day=self.later())
        self.assertEqual((d["entry"]["type"], d["entry"]["body"]), ("rekey_oppose", {"login": "ada"}))
        self.assertIn("Oppose the key recovery of ada", d["summary"])
        self.approve(d["digest"], who="carol")
        r = self.state().recoveries["ada"]
        self.assertEqual(tuple(r.opposed), ("carol",))
        self.assertIsNotNone(r.void)                                  # two other Masters: one opposition voids it


REPO = Path(__file__).resolve().parents[1]


TYLER = REPO / ".github/workflows/tyler.yml"




def decision() -> str:
    """The inline Python of the `applications` job, as the shell hands it to `python3 -P -c`."""
    m = re.search(r"python3 -P -c '\n(.*?)\n\s*' ledger/entries < ", TYLER.read_text(encoding="utf-8"), re.S)
    assert m, "the decision of the applications job is gone"
    return textwrap.dedent(m.group(1))


def write_ledger(directory: Path, entries: list[dict]) -> Path:
    directory.mkdir(parents=True)
    (directory / ".gitkeep").write_text("")
    for e in entries:
        entry_file(directory, e["seq"]).write_text(json.dumps(e))
    return directory


def issue(number: int, login: str | None, days: float, title: str | None = None, labels=("application",)) -> dict:
    created = datetime.now(timezone.utc) - timedelta(days=days)
    return {"number": number, "title": f"Application: @{login}" if title is None else title,
            "author": None if login is None else {"login": login, "id": number, "is_bot": False},
            "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"), "labels": [{"name": n} for n in labels]}


class ApplicationsJob(unittest.TestCase):
    def run_decision(self, led: Path, issues: list[dict]) -> list[int]:
        r = subprocess.run([sys.executable, "-P", "-c", decision(), str(led)], input=json.dumps(issues),
                           capture_output=True, text=True, cwd=led.parent,
                           env={**os.environ, "PYTHONPATH": str(REPO / "src"), "OM_NO_CACHE": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return [int(x) for x in r.stdout.split()]

    def test_the_job_runs_on_schedule_and_on_demand_only_with_plain_git_and_the_pinned_core(self):
        text = TYLER.read_text(encoding="utf-8")
        job = text.split("\n  applications:\n", 1)[1]
        self.assertIn("    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'\n", job)
        self.assertIn("    permissions:\n      issues: write\n      contents: read\n", job)
        self.assertIn("git fetch --quiet --no-tags --depth 1 origin refs/heads/main\n", job)
        self.assertIn("from openmasonry.ledger import fold, load, replay\n", job)
        self.assertIn("https://github.com/${{ github.repository }}/issues/new?template=application.yml", job)
        self.assertIn("`bin/om apply`", job)
        self.assertNotIn("uses:", job)
        self.assertIn("\npermissions:\n  contents: read\n", text.split("\njobs:\n", 1)[0])

    def test_it_closes_only_stale_applications_of_strangers(self):
        tmp = tmpdir(self)
        c = founded(tmp)
        initiate(c, "bob")                                   # a member
        petition(c, "dora", by="ada")                        # a pending petition
        invite(c, "Erin", by="carol")                        # an invitation not yet used, the login in capitals
        petition(c, "gina", by="carol")                      # a petition that a ballot refuses
        c.add("vouch", "ada", {"candidate": "gina"})
        c.add("ballot_open", "carol", {"id": "adm-gina", "kind": "admission", "subject": {"candidate": "gina"}})
        c.vote("adm-gina", {f: "no" for f in FOUNDERS})
        st = c.state()
        self.assertIn("bob", st.members)
        self.assertIn("dora", st.petitions)
        self.assertIn("Erin", st.invitations)
        self.assertFalse({"gina"} & {*st.members, *st.petitions, *st.invitations})   # only the entries remember her
        led = write_ledger(tmp / "repo" / "ledger" / "entries", c.entries)
        issues = [
            issue(1, "hiram", 90),                                        # a founder
            issue(2, "HIRAM", 90, labels=()),                             # the same login in another case, no label
            issue(3, "bob", 90),                                          # a member
            issue(4, "Dora", 90),                                         # a petitioner
            issue(5, "erin", 90, labels=()),                              # holds an invitation (as Erin)
            issue(6, "gina", 90),                                         # petitioned once, refused
            issue(7, "stranger1", 80),                                    # stale, labeled
            issue(8, "stranger2", 90, labels=()),                         # stale, titled by `om apply` with no label
            issue(9, "stranger3", 59),                                    # younger than 60 days
            issue(10, "stranger4", 90, title="Bug: the guide is slow", labels=()),       # not an application
            issue(11, "stranger5", 90, title="A question", labels=("question",)),       # not an application
            issue(12, "stranger6", 90, title="Application: @ada"),        # names a member
            issue(13, None, 90),                                          # a deleted account: left alone
            issue(14, "stranger7", 61, title="application: @stranger7", labels=()),    # title in another case
        ]
        self.assertEqual(self.run_decision(led, issues), [8, 7, 14])  # oldest first

    def test_before_the_genesis_only_the_age_decides(self):
        tmp = tmpdir(self)
        led = write_ledger(tmp / "ledger" / "entries", [])
        self.assertEqual(self.run_decision(led, [issue(1, "hiram", 61), issue(2, "someone", 30),
                                                 issue(3, "other", 61, title="Something else", labels=())]), [1])

    def test_a_run_closes_at_most_fifty_the_oldest_first(self):
        tmp = tmpdir(self)
        led = write_ledger(tmp / "ledger" / "entries", founded(tmp).entries)
        issues = [issue(n, f"applicant{n}", 61 + n) for n in range(1, 61)]
        self.assertEqual(self.run_decision(led, issues), list(range(60, 10, -1)))

    def test_a_ledger_that_does_not_replay_closes_nothing(self):
        tmp = tmpdir(self)
        c = founded(tmp)
        initiate(c, "bob")
        c.entries[-1]["body"]["id"] = "forged"
        led = write_ledger(tmp / "ledger" / "entries", c.entries)
        r = subprocess.run([sys.executable, "-P", "-c", decision(), str(led)], input=json.dumps([issue(1, "x", 90)]),
                           capture_output=True, text=True, cwd=tmp,
                           env={**os.environ, "PYTHONPATH": str(REPO / "src"), "OM_NO_CACHE": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
