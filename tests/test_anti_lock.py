"""Rules that keep the ledger from locking up, and the holes they close.

Each class tests one rule: the stuck or exploitable scenario first, then what the rule lets through, then the
bound that keeps the rule from being used to seize anything. States are built by hand (`Hand`) or as `Fast`
chains: the "signature" of an entry is the public key that signed it. Nothing touches the network.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import unittest
from datetime import timedelta

from openmasonry import canon, ledger
from openmasonry.ledger import commitment, point
from tests.test_custodian import SEVEN, correct, lodge
from tests.test_liveness import Hand, amend, claim_body, draw, judge, lapse, open_exam, vote
from tests.test_protocol import DECL, T0, copy_governed, salt_of
from tests.test_strict import DAY, SEC, fake_key, mk, tmpdir

URL = "https://example.org/work"


def vote_all(h, bids, votes):
    """Every voter commits in every ballot, reveals past the gap, and the ballots close in order."""
    for bid in bids:
        for who, v in votes.items():
            h.add("ballot_commit", who, {"id": bid, "commitment": commitment(bid, who, v, salt_of(who))})
    h.now += timedelta(days=7.3)
    for bid in bids:
        for who, v in votes.items():
            h.add("ballot_reveal", who, {"id": bid, "vote": v, "salt": salt_of(who)}, days=0.01)
    h.now += timedelta(days=3)
    for bid in bids:
        h.add("ballot_close", next(iter(votes)), {"id": bid})
    return [h.st.ballots[b] for b in bids]


def ask(h, who, new=None, days=0.0):
    """`who` asks for the recovery of their key, signing with the new key `new`."""
    name = new or f"{who}-new"
    return h.add("rekey_recover", who, {"key": fake_key(name), "proof": fake_key(name)}, days=days, key_of=name)


def masters(*names, **kw):
    return [mk(x, 3, t=T0 - 100 * DAY, activity=[T0], **kw) for x in names]


# ---------------------------------------------------------------- the pinned core runs on Python 3.11 ----

class OldestPython(unittest.TestCase):
    def pinned_sources(self):
        return [canon.ROOT / rel for rel in ledger_manifest() if rel.endswith(".py")]

    def test_every_pinned_module_compiles_here(self):
        for path in self.pinned_sources():
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_every_pinned_module_compiles_on_python_3_11(self):
        """The project supports Python 3.11 (pyproject.toml): syntax of a later version in the core would make
        every command fail there. Checked with a python3.11 binary when one is installed."""
        exe = shutil.which("python3.11")
        if exe is None or sys.version_info[:2] == (3, 11):
            self.skipTest("no python3.11 binary to compile with")
        code = ("import sys\nfor p in sys.argv[1:]:\n    compile(open(p, encoding='utf-8').read(), p, 'exec')\n")
        r = subprocess.run([exe, "-I", "-c", code, *map(str, self.pinned_sources())], capture_output=True, text=True)
        if r.returncode != 0 and "Python 3.11" not in subprocess.run([exe, "--version"], capture_output=True,
                                                                     text=True).stdout:
            self.skipTest("python3.11 is not a working Python 3.11")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_floor_is_stated_once(self):
        self.assertIn('requires-python = ">=3.11"', (canon.ROOT / "pyproject.toml").read_text())


def ledger_manifest() -> list[str]:
    from openmasonry.govern import read_manifest
    return list(read_manifest(canon.ROOT))


# ---------------------------------------------------------------- M4 holds at the close ----

class CaseTwinAtClose(unittest.TestCase):
    def test_of_two_paths_that_differ_by_case_only_the_first_to_close_is_pinned(self):
        """Neither path was pinned when the two ballots opened, so both opened; the second fails at its close
        (else both pins would be frozen for good: M4 refuses every amendment of either)."""
        h = Hand(*masters("hiram", "ada", "carol"))
        amend(h, "lower", "hiram", path="docs/x.md")
        amend(h, "upper", "ada", path="Docs/x.md", new="cd" * 32)
        lower, upper = vote_all(h, ["lower", "upper"], {x: "yes" for x in ("hiram", "ada", "carol")})
        self.assertEqual((lower.result, upper.result), ("passed", "failed"))
        self.assertEqual(h.st.pins.get("docs/x.md"), "ab" * 32)
        self.assertNotIn("Docs/x.md", h.st.pins)


# ---------------------------------------------------------------- fraud and return ----

def voided(days_ago: float):
    return mk("vic", 1, t=T0 - 400 * DAY, status="voided", status_since=T0 - days_ago * DAY, github_id=55)


FRAUD = {"id": "fr", "kind": "sanction", "subject": {"member": "vic", "measure": "expel_for_fraud"}}


class FraudAndReturn(unittest.TestCase):
    def test_the_fraud_window_closes_when_the_wait_to_return_ends(self):
        """At 90 days a voided record may be invited again; from then on it is never expelled for fraud."""
        h = Hand(*masters("hiram", "ada", "carol"), voided(90))
        self.assertTrue(ledger.may_return(h.st.members["vic"], h.now))
        h.refused(self, "expelled for fraud only by a ballot opened before 90 days have passed", "ballot_open",
                  "hiram", FRAUD)
        h = Hand(*masters("hiram", "ada", "carol"), voided(90 - 1 / 86400))
        self.assertFalse(ledger.may_return(h.st.members["vic"], h.now))
        h.add("ballot_open", "hiram", FRAUD)

    def test_no_invitation_while_a_fraud_ballot_is_open(self):
        h = Hand(*masters("hiram", "ada", "carol"), voided(89))
        h.add("ballot_open", "hiram", FRAUD)
        h.refused(self, "a sanction ballot on vic is open", "invite", "ada", {"login": "vic", "github_id": 55}, days=2)

    def test_an_admission_waits_for_an_expulsion_as_an_invitation_does(self):
        h = Hand(*masters("hiram", "ada", "carol"),
                 mk("vic", 1, status="expelled", status_since=T0 - 10 * DAY, github_id=55))
        h.st.petitions["vic"] = {"key": fake_key("vic2"), "vouches": ["hiram"], "time": T0, "github_id": 55}
        self.assertFalse(ledger._admissible(h.st, "vic", fake_key("vic2"), 55, h.now))
        h.st.members["vic"].status_since = T0 - 365 * DAY
        self.assertTrue(ledger._admissible(h.st, "vic", fake_key("vic2"), 55, h.now))


# ---------------------------------------------------------------- invitations ----

class InvitationHolders(unittest.TestCase):
    def test_nobody_is_invited_under_the_name_of_a_pending_claim(self):
        h = Hand(mk("hiram", founder=True), mk("ada"))
        h.add("custodian_claim", "hiram", claim_body("keeper"))
        for login in ("keeper", "Keeper"):
            h.refused(self, "collides with the custodian name of a pending claim", "invite", "ada",
                      {"login": login, "github_id": 91})

    def test_a_petition_never_registers_a_key_the_ledger_held_before(self):
        h = Hand(*masters("hiram", "ada"))
        h.st.known_keys.add(point(fake_key("retired")))
        h.add("invite", "hiram", {"login": "eli", "github_id": 91})
        h.refused(self, "this key was used in this ledger before", "petition", "eli",
                  {"key": fake_key("retired"), "declaration_sha256": DECL}, key_of="retired")
        h.add("petition", "eli", {"key": fake_key("eli"), "declaration_sha256": DECL})


class SponsorBudget(unittest.TestCase):
    def test_a_lapsed_invitation_counts_for_ninety_days(self):
        """Otherwise one Master holds a login by inviting it again and again with a wrong account id."""
        h = Hand(*masters("hiram", "ada"))
        for i in range(canon.SPONSOR_BUDGET_PER_YEAR):
            h.add("invite", "hiram", {"login": f"p{i}", "github_id": 100 + i})
        h.refused(self, "sponsorship budget exhausted", "invite", "hiram", {"login": "q", "github_id": 99}, days=31)
        h.now = T0 + 120 * DAY
        h.refused(self, "sponsorship budget exhausted", "invite", "hiram", {"login": "q", "github_id": 99})
        h.now = T0 + 120 * DAY + SEC
        h.add("invite", "hiram", {"login": "q", "github_id": 99})

    def test_a_member_who_departed_stops_counting(self):
        sponsored = [mk(f"s{i}", 1, t=T0 - 10 * DAY, sponsors=("hiram", "ada")) for i in range(4)]
        h = Hand(*masters("hiram", "ada"), *sponsored)
        h.refused(self, "sponsorship budget exhausted", "invite", "hiram", {"login": "q", "github_id": 99})
        h.add("depart", "s0", {})
        h.add("invite", "hiram", {"login": "q", "github_id": 99})


# ---------------------------------------------------------------- room holds ----

class RoomHoldRest(unittest.TestCase):
    def test_the_same_login_is_held_again_only_ninety_days_after_the_last_hold_began(self):
        c = lodge()
        correct(c, "hold_room", {"login": "carol"}, days=1)
        correct(c, "hold_room", {"login": "carol"}, days=16)
        c.refused(self, "carol was held less than 90 days ago")
        c.now = T0 + 91 * DAY - SEC
        correct(c, "hold_room", {"login": "carol"})
        c.refused(self, "carol was held less than 90 days ago")
        c.now = T0 + 91 * DAY
        correct(c, "hold_room", {"login": "carol"})
        self.assertEqual(len([x for x in c.state().corrections.values() if x.act == "hold_room"]), 2)


# ---------------------------------------------------------------- the genesis is checked exactly ----

class GenesisPinsExactly(unittest.TestCase):
    def test_a_genesis_whose_pin_differs_from_an_unchanged_file_is_refused(self):
        """The judge downgrades a mismatch on a file the pull request did not change to a warning; entry 0 is
        never corrected, so the genesis gets no such allowance."""
        tmp = tmpdir(self)
        base, pr = copy_governed(tmp / "base"), copy_governed(tmp / "pr")
        c = lodge(custodians=(), pins={"CONSTITUTION.md": "ab" * 32})
        r = judge(self, c, pr, base, 0)
        self.assertFalse(r["valid"], r["message"])
        self.assertIn("CONSTITUTION.md", r["message"])
        good = lodge(custodians=())
        self.assertTrue(judge(self, good, pr, base, 0)["valid"])


# ---------------------------------------------------------------- a degree table archived with its ballot ----

class DegreeTableInTheLedgerPullRequest(unittest.TestCase):
    def trees(self):
        tmp = tmpdir(self)
        base, pr = copy_governed(tmp / "base"), copy_governed(tmp / "pr")
        raw = (canon.CANON / "degrees.toml").read_bytes()
        new = raw.replace(b'wait_days = 30', b'wait_days = 31', 1)
        self.assertNotEqual(new, raw)
        digest = hashlib.sha256(new).hexdigest()
        return base, pr, new, digest

    def opened(self, digest):
        c = lodge(custodians=())
        c.add("ballot_open", "hiram", {"id": "deg", "kind": "amendment",
                                       "subject": {"path": "canon/degrees.toml", "new_sha256": digest}})
        return c

    def test_the_pull_request_that_opens_the_ballot_may_carry_its_archive(self):
        base, pr, new, digest = self.trees()
        c = self.opened(digest)
        r = judge(self, c, pr, base, 1)
        self.assertFalse(r["valid"])                                       # not archived anywhere: refused
        self.assertIn("is not archived", r["message"])
        (pr / "canon" / "history" / f"{digest}.toml").write_bytes(new)
        r = judge(self, c, pr, base, 1)
        self.assertTrue(r["valid"], r["message"])

    def test_only_the_table_its_ballot_names_and_only_under_its_own_digest(self):
        base, pr, new, digest = self.trees()
        c = self.opened(digest)
        (pr / "canon" / "history" / f"{digest}.toml").write_bytes(new)
        other = new.replace(b'wait_days = 31', b'wait_days = 32', 1)
        (pr / "canon" / "history" / f"{hashlib.sha256(other).hexdigest()}.toml").write_bytes(other)
        r = judge(self, c, pr, base, 1)
        self.assertFalse(r["valid"])
        self.assertIn("archives only the degree table its new amendment ballot", r["message"])
        (pr / "canon" / "history" / f"{hashlib.sha256(other).hexdigest()}.toml").unlink()
        (pr / "canon" / "history" / f"{'ab' * 32}.toml").write_bytes(new)
        r = judge(self, c, pr, base, 1)
        self.assertFalse(r["valid"])
        self.assertIn("named after the sha256 of its bytes", r["message"])

    def test_the_identity_step_and_the_summary_replay_with_the_archive_too(self):
        """Without this rule, the judge refused the pull request that carries a degree table with the ballot that
        names it: the identity step replayed the entries again outside the archive and blamed the author."""
        import argparse
        from unittest import mock
        from openmasonry import identity, verify
        from tests.test_protocol import gid
        from tests.test_strict import by_key, write_ledger
        base, pr, new, digest = self.trees()
        (pr / "canon" / "history" / f"{digest}.toml").write_bytes(new)
        c = self.opened(digest)
        led = write_ledger(tmpdir(self) / "led", c.entries)
        def run(**over):
            a = argparse.Namespace(**({"ledger": led, "tree": True, "online": False, "clock_since": None, "root": pr,
                                       "pr_author": "hiram", "pr_author_id": gid("hiram"), "since": 1, "json": True,
                                       "base_root": base} | over))
            def offline(*_a, **_kw):
                raise AssertionError("no network")
            with mock.patch.object(verify, "replay", lambda entries, **kw: ledger.replay(entries, verifier=by_key, **kw)), \
                    mock.patch.object(identity, "fetch_github_user", offline), \
                    mock.patch.object(identity, "fetch_github_keys", offline):
                return verify.verify_report(a)
        r = run()
        self.assertTrue(r["valid"], r["message"])                          # the real identity step, not a stub
        bare = {"tree": False, "pr_author": None, "pr_author_id": None, "since": None, "base_root": None}
        self.assertTrue(run(**bare)["valid"])                              # the summary step: --root pr alone
        r = run(**bare | {"root": None})
        self.assertFalse(r["valid"])
        self.assertIn("is not archived", r["message"])

    def test_the_genesis_pull_request_archives_only_the_table_it_pins(self):
        """Without this rule, the genesis pull request could add any file under canon/history/, unchecked, and
        the directory is append-only."""
        base, pr, new, digest = self.trees()
        pinned = canon.CANON / "history"
        c = lodge(custodians=())
        genesis_table = c.entries[0]["body"]["pins"]["canon/degrees.toml"]
        for name in [x.name for x in (base / "canon" / "history").iterdir()]:
            (base / "canon" / "history" / name).unlink()                  # a main without any archive yet
        r = judge(self, c, pr, base, 0)
        self.assertTrue(r["valid"], r["message"])                          # it adds the table its genesis pins
        self.assertTrue((pinned / f"{genesis_table}.toml").exists())
        (pr / "canon" / "history" / f"{'ab' * 32}.toml").write_bytes(b"this is not a degree table\n")
        r = judge(self, c, pr, base, 0)
        self.assertTrue(r["message"].startswith("UNLAWFUL ARCHIVE"), r["message"])
        (pr / "canon" / "history" / f"{'ab' * 32}.toml").unlink()
        (pr / "canon" / "history" / f"{digest}.toml").write_bytes(new)      # well formed, but pinned by nobody
        r = judge(self, c, pr, base, 0)
        self.assertTrue(r["message"].startswith("UNLAWFUL ARCHIVE"), r["message"])
        self.assertIn("the genesis pull request: the one its genesis pins", r["message"])


# ---------------------------------------------------------------- the wake-up of dormant electors ----

class WakeUpTime(unittest.TestCase):
    def test_a_short_amendment_ballot_needs_every_elector_present(self):
        """Where dormant electors are not waited for, an opener could pass a text in two days before they can
        wake up: the commit window is then at least seven days."""
        dozing = mk("dan", 3, t=T0 - 500 * DAY, activity=[T0 - 400 * DAY])
        h = Hand(*masters("hiram", "ada", "carol"), dozing)
        h.refused(self, "at least 7 days to commit", "ballot_open", "hiram",
                  {"id": "am", "kind": "amendment", "subject": {"path": "README.md", "new_sha256": "ab" * 32},
                   "commit_days": 6})
        amend(h, "am", "hiram", commit_days=7)
        h = Hand(*masters("hiram", "ada", "carol"))
        amend(h, "am", "hiram", commit_days=2)


# ---------------------------------------------------------------- a departure signed by a stolen key ----

class RecoveryAfterADeparture(unittest.TestCase):
    def four(self) -> Hand:
        return Hand(*masters("hiram", "ada", "carol", "dan"))

    def test_a_recovery_asked_within_thirty_days_reverses_any_departure(self):
        h = self.four()
        h.add("depart", "dan", {})
        ask(h, "dan", days=29)
        for who in ("hiram", "ada", "carol"):
            h.add("rekey_cosign", who, {"login": "dan"})
        h.add("rekey_recover_apply", "dan", {}, days=30, key_of="dan-new")
        m = h.st.members["dan"]
        self.assertEqual((m.status, m.key, m.left), ("active", fake_key("dan-new"), None))

    def test_after_thirty_days_a_departure_stands(self):
        h = self.four()
        h.add("depart", "dan", {})
        h.refused(self, "departed more than 30 days ago", "rekey_recover", "dan",
                  {"key": fake_key("dan-new"), "proof": fake_key("dan-new")}, days=30 + 1 / 86400, key_of="dan-new")

    def test_a_recovery_asked_before_the_departure_goes_on(self):
        h = self.four()
        ask(h, "dan")
        h.add("depart", "dan", {}, days=1)
        for who in ("hiram", "ada", "carol"):
            h.add("rekey_cosign", who, {"login": "dan"}, days=1)
        h.add("rekey_recover_apply", "dan", {}, days=30, key_of="dan-new")
        self.assertEqual(h.st.members["dan"].status, "active")


# ---------------------------------------------------------------- one absent Master ----

class CosignersDropAfterThirtyDays(unittest.TestCase):
    def test_those_already_given_suffice_and_the_long_notice_runs_from_the_drop(self):
        h = Hand(*masters(*SEVEN))
        ask(h, "ada")
        start = h.now
        h.add("rekey_cosign", "carol", {"login": "ada"}, days=1)
        r = h.st.recoveries["ada"]
        self.assertEqual(ledger.cosigners_needed(h.st, r, start + 30 * DAY - SEC), 3)
        self.assertEqual(ledger.cosigners_needed(h.st, r, start + 30 * DAY), 1)
        self.assertEqual(h.st.recovery_status(r, start + 30 * DAY), "pending")
        self.assertEqual(h.st.recovery_notice_end(r, start + 30 * DAY), start + 75 * DAY)
        h.now = start + 75 * DAY - SEC
        h.refused(self, "under notice until", "rekey_recover_apply", "ada", {}, key_of="ada-new")
        h.now = start + 75 * DAY
        h.add("rekey_recover_apply", "ada", {}, key_of="ada-new")
        self.assertEqual(h.st.members["ada"].key, fake_key("ada-new"))

    def test_never_fewer_than_one_where_another_master_exists(self):
        h = Hand(*masters(*SEVEN))
        ask(h, "ada")
        start = h.now
        r = h.st.recoveries["ada"]
        self.assertEqual(ledger.cosigners_needed(h.st, r, start + 31 * DAY), 1)
        self.assertEqual(h.st.recovery_status(r, start + 31 * DAY), "requested")
        h.add("rekey_cosign", "carol", {"login": "ada"}, days=40)
        self.assertEqual(h.st.recovery_notice_end(r, h.now), h.now + 45 * DAY)
        h.add("rekey_cosign", "dan", {"login": "ada"}, days=1)      # a later co-signature changes nothing
        self.assertEqual(h.st.recovery_notice_end(r, h.now), start + 85 * DAY)

    def test_a_request_complete_in_time_keeps_its_notice(self):
        h = Hand(*masters(*SEVEN))
        ask(h, "ada")
        for who in ("carol", "dan", "eve"):
            h.add("rekey_cosign", who, {"login": "ada"}, days=1)
        r = h.st.recoveries["ada"]
        self.assertEqual(h.st.recovery_notice_end(r, h.now + 40 * DAY), T0 + 33 * DAY)


# ---------------------------------------------------------------- the silent Master ----

def silent_master(login="hiram", **kw):
    return mk(login, 3, t=T0 - 400 * DAY, activity=[T0 - DAY], missed=(T0 - 50 * DAY, T0 - 20 * DAY), **kw)


class SilentMaster(unittest.TestCase):
    def test_two_unanswered_calls_in_180_days_and_none_answered(self):
        m = silent_master()
        self.assertTrue(m.silent(T0))
        self.assertFalse(m.silent(T0 + 131 * DAY))                    # the older call is more than 180 days old
        m.heard = T0 - 100 * DAY
        self.assertFalse(m.silent(T0))                                  # one call answered in the window
        self.assertFalse(mk("x", missed=(T0 - DAY,)).silent(T0))        # one call is not enough

    def test_the_close_of_a_ballot_records_who_was_called_and_who_answered(self):
        h = Hand(*masters("hiram", "ada", "carol"))
        amend(h, "am", "hiram")
        vote_all(h, ["am"], {"hiram": "yes", "ada": "yes"})
        st = h.st
        self.assertEqual((st.members["carol"].missed, st.members["hiram"].heard), ((h.now,), h.now))
        self.assertEqual(st.members["hiram"].missed, ())

    def test_one_vote_ends_it(self):
        """A vote revealed ends it; a commitment alone does not (one never revealed decides nothing)."""
        h = Hand(silent_master(), *masters("ada", "carol"))
        amend(h, "am", "ada")
        self.assertTrue(h.st.members["hiram"].silent(h.now))
        h.add("ballot_commit", "hiram", {"id": "am", "commitment": commitment("am", "hiram", "yes", salt_of("hiram"))})
        self.assertTrue(h.st.members["hiram"].silent(h.now))
        h.now = h.st.ballots["am"].commit_until + ledger.REVEAL_GAP
        self.assertTrue(h.st.members["hiram"].silent(h.now))
        h.add("ballot_reveal", "hiram", {"id": "am", "vote": "yes", "salt": salt_of("hiram")})
        self.assertFalse(h.st.members["hiram"].silent(h.now))

    def test_a_silent_sole_master_does_not_bar_the_succession(self):
        h = Hand(silent_master(founder=True), mk("bea", 2), mk("cal", 1))
        h.add("succession_claim", "bea", {})
        h.add("work", "hiram", {"ref": URL}, days=1)                   # not an answer: the claim stands
        self.assertEqual(h.st.succession_status(h.now), "pending")
        h.now = T0 + 91 * DAY
        self.assertEqual(h.st.successors(h.now), ["bea"])

    def test_an_entry_of_a_master_who_is_not_silent_cancels_the_claim(self):
        h = Hand(silent_master(founder=True), mk("bea", 2), mk("cal", 1))
        h.add("succession_claim", "bea", {})
        h.st.members["hiram"].missed = ()
        h.add("work", "hiram", {"ref": URL}, days=1)
        self.assertEqual(h.st.succession_status(h.now), "canceled")

    def test_a_silent_master_seated_by_the_lowered_lot_is_skipped_once_his_exam_times_out(self):
        """No rung seats two: the lot draws everyone any rung holds, the silent Master beside the sponsor. That
        costs one exam (it times out after 60 days); the next lot leaves him out."""
        h = Hand(silent_master("hiram"), *masters("ada"), mk("bea", 1, t=T0 - 100 * DAY, sponsors=("ada",)))
        self.assertEqual(ledger.examiner_pool(h.st, h.st.members["bea"], 2, h.now), ["ada", "hiram"])
        ex = draw(h, "bea", 2, open_exam(h, "bea", 2))
        h.add("exam_report", "ada", {"candidate": "bea", "degree": 2, "verdict": "pass"})
        self.assertFalse(ex.passed())                                     # hiram never reports
        h.now = ex.opened + 60 * DAY + SEC
        self.assertTrue(ex.timed_out(h.now, h.st))
        self.assertEqual(draw(h, "bea", 2, open_exam(h, "bea", 2)).pool, ("ada",))

    def test_the_guide_tells_a_silent_master_and_that_a_work_does_not_end_it(self):
        from openmasonry import guide
        h = Hand(silent_master(), *masters("ada", "carol"))
        kinds = lambda who: [n.kind for n in guide.notices(h.st, who, h.now)]
        self.assertEqual((kinds("hiram").count("silent"), kinds("ada").count("silent")), (1, 0))
        h.add("work", "hiram", {"ref": URL})
        notice = next(n for n in guide.notices(h.st, "hiram", h.now) if n.kind == "silent")
        self.assertIn("A work does not end it.", notice.why)

    def test_the_guide_offers_no_re_run_of_a_short_ballot(self):
        from openmasonry import guide
        h = Hand(*masters("hiram", "ada", "carol", "dan"))
        for bid, days in (("short", 2), ("full", 7)):
            amend(h, bid, "hiram", path=f"docs/{bid}.md", commit_days=days)
        h.now = h.st.ballots["full"].reveal_until + SEC
        for bid in ("short", "full"):
            h.add("ballot_close", "hiram", {"id": bid})
        lapsed = [n.why.split()[1] for n in guide.notices(h.st, "hiram", h.now) if n.kind == "ballot_lapsed"]
        self.assertEqual(lapsed, ["full"])

    def test_an_advancement_does_not_wait_for_a_silent_master(self):
        h = Hand(silent_master("hiram"), *masters("ada", "carol"), mk("bea", 3, t=T0 - 400 * DAY))
        electors, base = ledger.electorate(h.st, "advancement", {"member": "bea", "degree": 4}, h.now)
        self.assertIn("hiram", electors)                                 # keeps the vote
        self.assertEqual(base, 2)                                        # and is not waited for


# ---------------------------------------------------------------- examiners who never report ----

class SkippedAccumulates(unittest.TestCase):
    def test_the_silent_examiners_of_every_exam_before_are_left_out_while_anyone_else_can_be_drawn(self):
        names = [f"m{i}" for i in range(6)]
        h = Hand(*masters(*names), mk("cal", 1, t=T0 - 100 * DAY))
        silent = set()
        for round_, seats in enumerate((2, 4)):                           # after a timeout the lot seats everyone left
            ex = draw(h, "cal", 2, open_exam(h, "cal", 2))
            self.assertTrue(silent.isdisjoint(ex.pool), (round_, ex.pool))
            self.assertEqual(len(ex.examiners), seats)
            silent |= set(ex.examiners)
            h.now += 61 * DAY                                             # nobody reports: the exam times out
        ex = draw(h, "cal", 2, open_exam(h, "cal", 2))
        self.assertEqual(sorted(ex.pool), names)                          # nobody else is left: everyone again
        self.assertEqual(ex.skipped, ())


# ---------------------------------------------------------------- what a call is ----

def short(h, bid, by, n, commit_days=2):
    """An amendment ballot of `by` with `commit_days` to commit and 1 to reveal."""
    return amend(h, bid, by, path=f"docs/{bid}.md", new=f"{n:02d}" * 32, commit_days=commit_days, reveal_days=1)


def seal(h, bid, who, v="no"):
    h.add("ballot_commit", who, {"id": bid, "commitment": commitment(bid, who, v, salt_of(who))})


SEVEN_MASTERS = ("hiram", "ada", "carol", "dan", "eve", "fay", "gus")


class Calls(unittest.TestCase):
    def test_a_ballot_with_less_than_seven_days_to_commit_calls_nobody(self):
        """Without this rule, one key opened two 2-day amendment ballots and, 3 days and 6 hours later, every
        other Master was silent: the examiner seats, the advancement quorum and the succession followed."""
        h = Hand(*masters(*SEVEN_MASTERS))
        for i in (1, 2):
            short(h, f"junk{i}", "hiram", i)
            seal(h, f"junk{i}", "hiram")
            seal(h, f"junk{i}", "ada")
        h.now = h.st.ballots["junk1"].reveal_until + SEC
        for i in (1, 2):
            h.add("ballot_close", "hiram", {"id": f"junk{i}"})
        self.assertEqual([h.st.members[x].missed for x in SEVEN_MASTERS], [()] * 7)
        self.assertEqual(h.st.present_masters(h.now), sorted(SEVEN_MASTERS))
        self.assertFalse(ledger.full_call(h.st.ballots["junk1"]))

    def test_two_calls_count_as_two_only_seven_days_apart_and_two_are_kept(self):
        h = Hand(*masters("hiram", "ada", "carol"))
        for i in (1, 2):
            short(h, f"a{i}", "hiram", i, commit_days=7)
        h.now = h.st.ballots["a1"].reveal_until + SEC
        for i in (1, 2):
            h.add("ballot_close", "hiram", {"id": f"a{i}"})               # the same absence, ended twice
        first = h.now
        self.assertEqual(h.st.members["carol"].missed, (first,))
        self.assertFalse(h.st.members["carol"].silent(h.now))
        for i in range(3, 8):                                             # five more, a week and a second apart
            short(h, f"a{i}", "hiram", i, commit_days=7)
            h.now = h.st.ballots[f"a{i}"].reveal_until + SEC
            h.add("ballot_close", "hiram", {"id": f"a{i}"})
            self.assertEqual(len(h.st.members["carol"].missed), ledger.SILENT_CALLS)
            self.assertTrue(h.st.members["carol"].silent(h.now))
        self.assertEqual(h.st.members["carol"].missed[-1], h.now)          # the newest are kept
        self.assertEqual(ledger.SILENT_APART_DAYS, 7)

    def test_a_commitment_never_revealed_does_not_answer(self):
        """Without this rule, a Master who committed once in 180 days, in a ballot of their own, was never silent."""
        h = Hand(*masters("hiram", "ada", "carol"))
        amend(h, "am", "ada")
        seal(h, "am", "hiram")
        h.now = h.st.ballots["am"].reveal_until + SEC
        h.add("ballot_close", "ada", {"id": "am"})
        self.assertEqual((h.st.members["hiram"].missed, h.st.members["hiram"].heard), ((h.now,), None))

    def test_a_short_ballot_that_lapses_is_never_re_run(self):
        """Without this rule, one Master passed any amendment alone in under twelve days: a 2-day ballot only they
        voted in lapsed, and its re-run waited for nobody else."""
        h = Hand(*masters("mallory", "ada", "carol", "dan", "eve"))
        short(h, "a1", "mallory", 1)
        seal(h, "a1", "mallory", "yes")
        h.now = h.st.ballots["a1"].commit_until + ledger.REVEAL_GAP
        h.add("ballot_reveal", "mallory", {"id": "a1", "vote": "yes", "salt": salt_of("mallory")})
        h.now = h.st.ballots["a1"].reveal_until + SEC
        h.add("ballot_close", "mallory", {"id": "a1"})
        self.assertEqual(h.st.ballots["a1"].result, "lapsed")
        body = {"id": "a2", "kind": "amendment", "subject": h.st.ballots["a1"].subject, "commit_days": 7,
                "reveal_days": 1, "rerun": "a1"}
        h.refused(self, "ballot a1 gave less than 7 days to commit and is never re-run", "ballot_open", "mallory", body)
        h.refused(self, "ballot a1 gave less than 7 days to commit and is never re-run", "ballot_open", "mallory",
                  {**body, "commit_days": 2})                             # B2g before B2f: no window would help
        del body["rerun"]
        h.add("ballot_open", "mallory", body)                             # a new ballot, with its whole quorum
        self.assertEqual(h.st.ballots["a2"].quorum_base(), 5)


class SilentSuccessors(unittest.TestCase):
    def test_a_successor_who_never_reports_is_left_out_and_the_next_degree_stands_in(self):
        """Without this rule, one inert member of the 2nd degree, the only successor, was drawn for every exam and
        nobody below could invite, be examined or advance, while that member signed one entry a year."""
        gone = mk("hiram", 3, t=T0 - 900 * DAY, status="departed", status_since=T0 - 500 * DAY, founder=True)
        h = Hand(gone, mk("bea", 2, t=T0 - 200 * DAY, activity=[T0 - DAY]), mk("cal", 1, t=T0 - 200 * DAY),
                 mk("dan", 1, t=T0 - 200 * DAY, activity=[T0]))
        h.add("succession_claim", "cal", {})
        h.now += 90 * DAY
        self.assertEqual(h.st.successors(h.now), ["bea"])
        for _ in range(2):                                                # two exams time out: bea never reports
            ex = draw(h, "cal", 2, open_exam(h, "cal", 2))
            self.assertEqual(ex.pool, ("bea",))
            h.now += 60.7 * DAY
        h.add("work", "bea", {"ref": URL})                                # a sign of activity is not an answer
        open_exam(h, "cal", 2)                                            # records the second call
        self.assertTrue(h.st.members["bea"].silent(h.now))
        self.assertEqual(h.st.successors(h.now), ["cal", "dan"])
        h.add("invite", "cal", {"login": "eli", "github_id": 91})
        h.now += 60.7 * DAY
        pools = []                                                        # the exam above lapsed undrawn: no skip
        while not pools or "dan" not in pools[-1] or "bea" in pools[-1]:
            ex = draw(h, "cal", 2, open_exam(h, "cal", 2))
            pools.append(ex.pool)
            if "dan" in ex.examiners:
                h.add("exam_report", "dan", {"candidate": "cal", "degree": 2, "verdict": "pass"})
            h.now += 60.7 * DAY                                           # bea never reports: the exam times out
        # The lowered lot seats bea beside dan; each lot is frozen before the call of the exam that timed out is
        # recorded, so bea's older call has expired and she is the sole successor at that instant, twice.
        self.assertEqual(pools, [("bea", "dan"), ("bea",), ("bea",), ("dan",)])
        self.assertTrue(h.st.exams[("cal", 2)].passed())


class SilentInTheAdmission(unittest.TestCase):
    def test_a_lone_apprentice_behind_a_silent_master_admits_and_the_newcomer_examines(self):
        """Without this rule, a lone member of the 1st degree whose only Master signed one entry a year and answered
        nothing could never admit anyone (the Master was the only elector, and every admission lapsed) and so was
        never examined: nobody else was there to draw."""
        h = Hand(mk("hiram", 3, t=T0 - 400 * DAY, activity=[T0 - DAY], founder=True),
                 mk("cal", 1, t=T0 - 100 * DAY, sponsors=("hiram",)))
        for _ in range(2):                                                # two exams time out: hiram never reports
            draw(h, "cal", 2, open_exam(h, "cal", 2))
            h.now += 60.7 * DAY
        open_exam(h, "cal", 2)                                            # records the second call
        self.assertTrue(h.st.members["hiram"].silent(h.now))
        h.add("succession_claim", "cal", {})
        h.now += 90 * DAY + SEC
        h.add("work", "hiram", {"ref": URL})                              # one entry a year: never dormant
        self.assertEqual(h.st.successors(h.now), ["cal"])
        h.add("invite", "cal", {"login": "eli", "github_id": 91})
        h.add("petition", "eli", {"key": fake_key("eli"), "declaration_sha256": DECL})
        h.add("ballot_open", "cal", {"id": "adm", "kind": "admission", "subject": {"candidate": "eli"}})
        b = h.st.ballots["adm"]
        self.assertEqual((sorted(b.electors), b.quorum_base()), (["cal", "hiram"], 1))   # hiram keeps the vote
        self.assertEqual(vote(h, "adm", {"cal": "yes"}).result, "passed")
        self.assertEqual(h.st.members["eli"].degree, 1)
        h.now += 60.7 * DAY
        self.assertEqual(draw(h, "cal", 2, open_exam(h, "cal", 2)).pool, ("eli",))

    def test_a_lone_apprentice_behind_a_silent_sponsor_and_a_silent_fellow_admits_within_five_years(self):
        """Without this rule, a member of the 1st degree whose sponsor (the only Master) and the only Fellow each
        signed one entry a year and answered nothing was never examined and never stood in: every lot seated one
        of the two, its calls were at least 60 days apart, and the two were never silent at the same time."""
        h = Hand(mk("hiram", 3, t=T0 - 400 * DAY, activity=[T0 - DAY], founder=True),
                 mk("bea", 2, t=T0 - 400 * DAY, activity=[T0 - DAY], sponsors=("hiram",)),
                 mk("cal", 1, t=T0 - 100 * DAY, sponsors=("hiram",)))
        claimed, pools = False, set()
        for n in range(30):                                               # five years: all that cal can do
            if n % 5 == 4:
                for x in ("hiram", "bea"):
                    h.add("work", x, {"ref": URL})                        # one entry a year each: never dormant
            if not claimed and h.st.present_masters(h.now) == []:
                h.add("succession_claim", "cal", {})
                claimed = True
            if h.st.stands_in("cal", h.now):
                break
            pools.add(draw(h, "cal", 2, open_exam(h, "cal", 2)).pool)
            h.now += 60.7 * DAY
        self.assertTrue(h.st.stands_in("cal", h.now), sorted(pools))
        self.assertIn(("bea", "hiram"), pools)                            # the lowered lot seats both
        self.assertLess(h.now - T0, 5 * 365 * DAY)
        h.add("invite", "cal", {"login": "eli", "github_id": 91})
        h.add("petition", "eli", {"key": fake_key("eli"), "declaration_sha256": DECL})
        h.add("ballot_open", "cal", {"id": "adm", "kind": "admission", "subject": {"candidate": "eli"}})
        b = h.st.ballots["adm"]
        self.assertEqual((sorted(b.electors), b.quorum_base()), (["bea", "cal", "hiram"], 1))   # no vote removed
        self.assertEqual(vote(h, "adm", {"cal": "yes"}).result, "passed")
        h.now += 60.7 * DAY
        self.assertIn("eli", draw(h, "cal", 2, open_exam(h, "cal", 2)).pool)

    def test_behind_a_silent_successor_the_lot_falls_back_on_them_only_until_a_newcomer_is_admitted(self):
        """The lot keeps a silent member of the target degree while nobody else can be drawn (they may still
        answer); that is no lock once the admission does not wait for them: the newcomer is drawn next."""
        gone = mk("hiram", 3, t=T0 - 900 * DAY, status="departed", status_since=T0 - 500 * DAY, founder=True)
        h = Hand(gone, mk("bea", 2, t=T0 - 200 * DAY, activity=[T0 - DAY]), mk("cal", 1, t=T0 - 200 * DAY),
                 mk("dan", 1, t=T0 - 600 * DAY, activity=[T0 - 400 * DAY]))         # dan is dormant
        h.add("succession_claim", "cal", {})
        h.now += 90 * DAY
        for _ in range(2):
            draw(h, "cal", 2, open_exam(h, "cal", 2))
            h.now += 60.7 * DAY
        h.add("work", "bea", {"ref": URL})
        self.assertEqual(draw(h, "cal", 2, open_exam(h, "cal", 2)).pool, ("bea",))   # nobody else can be drawn
        self.assertEqual(h.st.successors(h.now), ["cal"])
        h.add("invite", "cal", {"login": "eli", "github_id": 91})
        h.add("petition", "eli", {"key": fake_key("eli"), "declaration_sha256": DECL})
        h.add("ballot_open", "cal", {"id": "adm", "kind": "admission", "subject": {"candidate": "eli"}})
        b = h.st.ballots["adm"]
        self.assertEqual((sorted(b.electors), b.quorum_base()), (["bea", "cal", "dan"], 1))
        self.assertEqual(vote(h, "adm", {"cal": "yes"}).result, "passed")
        h.now += 60.7 * DAY
        self.assertEqual(draw(h, "cal", 2, open_exam(h, "cal", 2)).pool, ("eli",))

    def test_a_silent_master_keeps_the_vote_and_is_not_waited_for(self):
        h = Hand(silent_master("hiram"), *masters("ada", "carol"))
        electors, base = ledger.electorate(h.st, "admission", {"candidate": "eli"}, h.now)
        self.assertEqual((sorted(electors), base), (["ada", "carol", "hiram"], 2))

    def test_the_first_rung_keeps_its_voters_when_every_one_present_is_silent(self):
        h = Hand(silent_master("hiram"), mk("bea", 2, activity=[T0], missed=(T0 - 50 * DAY, T0 - 20 * DAY)),
                 mk("cal", 1, activity=[T0]))
        electors, base = ledger.electorate(h.st, "admission", {"candidate": "eli"}, h.now)
        self.assertEqual((sorted(electors), base), (["bea", "cal", "hiram"], 1))


class DepartureReversal(unittest.TestCase):
    def test_a_recovery_asked_in_time_is_followed_whatever_ended_it(self):
        """Without this rule, a departure signed by a stolen key stood for good whenever the recovery asked in
        time ended in any way but the old key's stop: expired for want of a co-signer, or opposed."""
        h = Hand(*masters("vic", "xavier"))                               # xavier is away; a thief holds vic's old key
        ask(h, "vic")                                                     # day 0
        h.add("depart", "vic", {}, days=10)                               # day 10: the thief
        self.assertEqual(h.st.recoveries["vic"].departure, h.now)
        h.now = T0 + 61 * DAY
        self.assertEqual(h.st.recovery_status(h.st.recoveries["vic"], h.now), "expired")
        h.refused(self, "requested less than 90 days ago", "rekey_recover", "vic",
                  {"key": fake_key("v3"), "proof": fake_key("v3")}, key_of="v3")
        late = h.fork()
        late.now = T0 + 150 * DAY + SEC                                   # more than 150 days after that request
        late.refused(self, "vic departed more than 30 days ago", "rekey_recover", "vic",
                     {"key": fake_key("v3"), "proof": fake_key("v3")}, key_of="v3")
        h.now = T0 + 150 * DAY                                            # the last second
        ask(h, "vic", new="v3")
        r = h.st.recoveries["vic"]
        self.assertEqual((r.departure, r.final), (T0 + 10 * DAY, False))
        h.add("rekey_cosign", "xavier", {"login": "vic"}, days=1)          # one other Master: a notice of 45 days
        h.add("rekey_recover_apply", "vic", {}, days=45, key_of="v3")
        self.assertEqual((h.st.members["vic"].status, h.st.members["vic"].key), ("active", fake_key("v3")))

    def test_an_opposed_recovery_is_followed_too(self):
        h = Hand(*masters("vic", "ada", "carol", "dan", "mallory"))
        ask(h, "vic")
        h.add("rekey_oppose", "mallory", {"login": "vic"})                 # one opposition voids it
        h.add("depart", "vic", {})
        self.assertEqual(h.st.recovery_status(h.st.recoveries["vic"], h.now), "opposed")
        h.now = T0 + 90 * DAY
        ask(h, "vic", new="v2")
        self.assertEqual(h.st.recoveries["vic"].departure, T0)

    def test_the_thief_who_stops_the_recovery_and_then_departs_does_not_win(self):
        h = Hand(*masters("vic", "ada", "carol", "dan"))
        ask(h, "vic")
        h.add("rekey_object", "vic", {}, days=1)                          # the old key stops it…
        h.add("depart", "vic", {}, days=1)                                # …and then departs
        h.now = T0 + 91 * DAY
        ask(h, "vic", new="v2")
        self.assertEqual((h.st.recoveries["vic"].final, h.st.recoveries["vic"].departure), (True, T0 + 2 * DAY))

    def test_an_old_objection_never_reverses_a_departure_long_after_it(self):
        """Without this rule, a member who once stopped a recovery could be brought back at full degree, with one
        co-signer and no admission ballot, years after leaving."""
        h = Hand(*masters(*SEVEN_MASTERS))
        ask(h, "ada", days=1)
        h.add("rekey_object", "ada", {}, days=1)                          # day 2
        h.add("depart", "ada", {}, days=400)                              # day 402
        self.assertIsNone(h.st.recoveries["ada"].departure)
        h.refused(self, "ada departed more than 30 days ago", "rekey_recover", "ada",
                  {"key": fake_key("ada-y"), "proof": fake_key("ada-y")}, days=400, key_of="ada-y")

    def test_a_reversed_departure_takes_back_a_seat_only_into_a_vacancy(self):
        """Without this rule, a reversed departure seated a 34th member of the Council."""
        until = T0 + 300 * DAY
        seated = [mk(f"s{i:02d}", 33, t=T0 - 100 * DAY, activity=[T0], seat_until=until) for i in range(33)]
        h = Hand(*seated, mk("p", 32, t=T0 - 100 * DAY, activity=[T0]))
        h.add("depart", "s00", {})
        h.st.members["p"].degree, h.st.members["p"].seat_until = 33, until    # a draw filled the vacancy
        self.assertEqual(len(h.st.seats(h.now)), 33)
        ask(h, "s00", days=1)
        for x in ("s01", "s02", "s03"):
            h.add("rekey_cosign", x, {"login": "s00"})
        h.add("rekey_recover_apply", "s00", {}, days=30, key_of="s00-new")
        self.assertEqual((h.st.members["s00"].status, h.st.members["s00"].seat_until, len(h.st.seats(h.now))),
                         ("active", None, 33))


class SponsorsAfterTheDrop(unittest.TestCase):
    def test_once_the_request_dropped_the_co_signatures_given_suffice_whoever_gave_them(self):
        """Without this rule, a member whose answering Masters were all their sponsors was never recovered while
        one other Master was away and not dormant."""
        h = Hand(*masters("hiram", "ada"), mk("vic", 2, t=T0 - 100 * DAY, sponsors=("hiram",)))
        ask(h, "vic")
        h.add("rekey_cosign", "hiram", {"login": "vic"}, days=1)
        r = h.st.recoveries["vic"]
        self.assertEqual(h.st.recovery_status(r, T0 + 30 * DAY - SEC), "requested")
        self.assertEqual((h.st.recovery_status(r, T0 + 30 * DAY), h.st.recovery_start(r, T0 + 30 * DAY)),
                         ("pending", T0 + 30 * DAY))
        h.now = T0 + 75 * DAY - SEC                                       # 45 days from the drop
        h.refused(self, "under notice until", "rekey_recover_apply", "vic", {}, key_of="vic-new")
        h.now += SEC
        h.add("rekey_recover_apply", "vic", {}, key_of="vic-new")
        self.assertEqual(h.st.members["vic"].key, fake_key("vic-new"))


class ClaimAfterAnObjection(unittest.TestCase):
    def test_after_an_objection_the_next_claim_waits_thirty_days(self):
        """Without this rule, a founder held one login out of invitations, claim after claim."""
        h = Hand(mk("hiram", founder=True), mk("mallory", founder=True), mk("ada"))
        h.add("custodian_claim", "mallory", claim_body("eli"))
        h.add("custodian_claim_object", "ada", {"seq": h.st.seq})
        again = claim_body("eli") | {"key": fake_key("k2"), "revoke_key": fake_key("r2"), "proof": fake_key("k2"),
                                     "revoke_proof": fake_key("r2")}
        for who in ("mallory", "hiram"):
            h.refused(self, "objected to less than 30 days ago", "custodian_claim", who, again)
        h.add("invite", "ada", {"login": "eli", "github_id": 91})          # the name is free meanwhile
        h.now += 30 * DAY
        h.add("custodian_claim", "hiram", again | {"name": "keeper"})



class TheFreezeSlotHoldsNoRecovery(unittest.TestCase):
    def test_a_login_held_frozen_never_holds_back_the_recovery_of_another(self):
        """Without this rule, with fewer than twenty members and two Masters, one accomplice frozen again every 90
        days (his own recovery, never co-signed, keeps the slot to day 90) refused for good the one co-signature
        that the other Master's open recovery needed: the request expired, and so did the next."""
        from tests.test_liveness import custodian
        h = Hand(mk("hiram", founder=True), mk("vic"), mk("mal", 1), mk("p2", 1),
                 custodians={"warden": custodian()}, custodian_threshold=1)
        freeze = {"act": "freeze_key", "target": {"login": "mal"}, "ground": "key_compromised",
                  "reason_sha256": "ab" * 32}
        h.add("correction", "warden", freeze)
        ask(h, "mal", new="m0")
        ask(h, "vic", new="v0")
        h.add("rekey_cosign", "hiram", {"login": "vic"}, days=1)         # completes vic's recovery: its notice starts
        r = h.st.recoveries["vic"]
        self.assertEqual((r.notice, h.st.recovery_status(r, h.now)), (h.now, "pending"))
        self.assertEqual(h.st.frozen_keys(h.now), {"mal", "vic"})
        h.refused(self, "too many keys are frozen at once: at most 1 ", "correction", "warden",
                  {**freeze, "target": {"login": "p2"}})                  # the cap still bounds the freezes
        h.add("rekey_recover_apply", "vic", {}, days=45 + SEC / DAY, key_of="v0")     # the lowered notice
        self.assertEqual(h.st.members["vic"].key, fake_key("v0"))


# ---------------------------------------------------------------- Masters who sign a work a year and answer nothing ----

def inert(*names, **kw):
    """Master Builders for more than a year who never answer (no vote revealed, no report): never dormant while they
    sign one work a year."""
    return [mk(x, 3, t=T0 - 400 * DAY, activity=[T0], **kw) for x in names]


def time_out(h, who, degree, draw_it=True):
    """`who` opens the exam for `degree`; nobody reports (or nobody draws the lot), and it times out."""
    rnd = open_exam(h, who, degree)
    if not draw_it:
        h.now = ledger.drand_time(rnd) + (ledger.LOT_DRAW_DAYS + 1) * DAY
        return h.st.exams[(who, degree)]
    ex = draw(h, who, degree, rnd)
    h.now = ex.opened + ledger.EXAM_EXPIRY_DAYS * DAY + SEC
    return ex


class AfterATimeoutTheLotSeatsEveryone(unittest.TestCase):
    def test_stuck_without_it_an_apprentice_among_three_inert_masters_was_never_examined(self):
        """Without this rule the lot seated two of three Masters who never answer, then left the two out as silent
        and seated the third alone, and so on: never more than two were silent at once, and the apprentice was
        never examined and never stood in, for as long as each signed one work a year."""
        h = Hand(mk("hon", 1, t=T0 - 400 * DAY, activity=[T0], sponsors=("m0", "m1")), *inert("m0", "m1", "m2"))
        for x in ("m0", "m1", "m2"):
            h.add("work", x, {"ref": URL})                                # signs, never answers
        for _ in range(3):
            time_out(h, "hon", 2)
        rnd = open_exam(h, "hon", 2)                                      # records the calls of the last one
        self.assertEqual(h.st.present_masters(h.now), [])
        self.assertLess((h.now - T0).days, 200)
        h.add("succession_claim", "hon", {})
        claimed = h.now
        ex = draw(h, "hon", 2, rnd)                                       # the lots go on calling all three
        h.now = ex.opened + ledger.EXAM_EXPIRY_DAYS * DAY + SEC
        open_exam(h, "hon", 2)
        h.now = claimed + 91 * DAY
        self.assertEqual(h.st.successors(h.now), ["hon"])

    def test_the_next_lot_seats_everyone_any_rung_holds_but_the_silent_examiners(self):
        names = [f"m{i}" for i in range(6)]
        h = Hand(*masters(*names), mk("cal", 1, t=T0 - 100 * DAY))
        first = time_out(h, "cal", 2)
        self.assertEqual((first.k, len(first.pool)), (2, 6))
        open_exam(h, "cal", 2)
        ex = h.st.exams[("cal", 2)]
        self.assertEqual(sorted(ex.pool), sorted(set(names) - set(first.examiners)))
        self.assertEqual(ex.k, 4)                                         # never fewer than the lot it follows
        self.assertEqual(ex.skipped, tuple(sorted(first.examiners)))

    def test_a_lot_never_drawn_widens_the_next_one_too(self):
        names = [f"m{i}" for i in range(6)]
        h = Hand(*masters(*names), mk("cal", 1, t=T0 - 100 * DAY))
        self.assertTrue(time_out(h, "cal", 2, draw_it=False).timed_out(h.now, h.st))
        open_exam(h, "cal", 2)
        ex = h.st.exams[("cal", 2)]
        self.assertEqual((sorted(ex.pool), ex.k), (names, 6))

    def test_the_founding_cohort_stays_out_of_a_founders_lot_while_enough_others_remain_but_not_after_a_timeout(self):
        """A founder's lot keeps the founding cohort out while the others seat the number; the lot after a
        timeout seats every member who never answered, the cohort too, so each of them is called."""
        others = [f"n{i}" for i in range(7)]
        h = Hand(mk("fc", 3, t=T0 - 400 * DAY, activity=[T0], founder=True), *masters(*others),
                 *masters("f1", "f2", founder=True))
        first = time_out(h, "fc", 4)
        self.assertTrue(set(first.pool) <= set(others))                   # the normal lot: the cohort stays out
        open_exam(h, "fc", 4)
        ex = h.st.exams[("fc", 4)]
        self.assertEqual(sorted(ex.pool), sorted(set(others) - set(first.examiners) | {"f1", "f2"}))
        self.assertEqual(ex.k, len(ex.pool))

    def test_stuck_without_it_a_returning_founder_among_an_inert_founder_and_inert_masters_was_never_examined(self):
        """A founder who departs and is admitted again keeps the title below the 3rd degree. When the lot after a
        timeout still kept the cohort out while the others filled it, the inert founder Master was called once,
        then carried as skipped and never called again: he never fell silent, and the founder below him was
        never examined and never stood in, for as long as each signed one work a year."""
        h = Hand(mk("hon", 1, t=T0 - 400 * DAY, activity=[T0], founder=True), *inert("f0", founder=True),
                 *inert("m0", "m1"))
        for x in ("f0", "m0", "m1"):
            h.add("work", x, {"ref": URL})                                # signs, never answers
        for _ in range(3):
            time_out(h, "hon", 2)
        rnd = open_exam(h, "hon", 2)                                      # records the calls of the last one
        self.assertEqual(h.st.present_masters(h.now), [])
        self.assertLess((h.now - T0).days, 200)
        h.add("succession_claim", "hon", {})
        claimed = h.now
        ex = draw(h, "hon", 2, rnd)
        self.assertEqual(sorted(ex.examiners), ["f0", "m0", "m1"])        # the lots go on calling all three
        h.now = ex.opened + ledger.EXAM_EXPIRY_DAYS * DAY + SEC
        open_exam(h, "hon", 2)
        h.now = claimed + 91 * DAY
        self.assertEqual(h.st.successors(h.now), ["hon"])

    def test_a_lot_that_calls_the_skipped_members_again_carries_none_of_them(self):
        """When every member a rung holds was skipped, the lot calls them again: the skip left nobody out, so
        nobody is carried to the next lot as skipped (one who was would never be called again, and never fall
        silent)."""
        h = Hand(mk("hon", 1, t=T0 - 400 * DAY, activity=[T0], founder=True), *inert("f0", founder=True),
                 *inert("m0", "m1"))
        prev = draw(h, "hon", 2, open_exam(h, "hon", 2))
        prev.lapsed, prev.skipped = True, ("f0", "m0", "m1")          # ended with no penalty, after skipping all
        open_exam(h, "hon", 2)
        ex = h.st.exams[("hon", 2)]
        self.assertEqual((ex.pool, ex.skipped), (("m0", "m1"), ()))

    def test_no_member_passes_an_exam_alone_in_the_wider_lot(self):
        h = Hand(*masters("m0", "m1", "m2", "m3"), mk("cal", 1, t=T0 - 100 * DAY))
        first = time_out(h, "cal", 2)
        ex = draw(h, "cal", 2, open_exam(h, "cal", 2))
        self.assertEqual(len(ex.examiners), 2)
        h.add("exam_report", ex.examiners[0], {"candidate": "cal", "degree": 2, "verdict": "pass"})
        self.assertFalse(ex.passed())                                     # one pass of two is no majority
        self.assertTrue(set(first.examiners).isdisjoint(ex.examiners))


class InertMastersNeverHoldARecovery(unittest.TestCase):
    def test_stuck_without_it_a_lost_key_waited_forever_for_a_master_who_answers_nothing(self):
        """Without this rule every request waited for the co-signature of a Master who signs one work a year and
        answers nothing, expired at 60 days, and the next came 90 days later: forever."""
        h = Hand(*inert("hon", "ina"))
        ask(h, "hon", new="hon-new")
        r = h.st.recoveries["hon"]
        self.assertEqual(ledger.cosigners_needed(h.st, r, h.now), 0)
        self.assertEqual(h.st.recovery_status(r, h.now), "pending")       # the notice starts with the request
        h.refused(self, "under notice until", "rekey_recover_apply", "hon", {}, days=44, key_of="hon-new")
        h.add("rekey_recover_apply", "hon", {}, days=1 + SEC / DAY, key_of="hon-new")      # the lowered notice
        self.assertEqual(h.st.members["hon"].key, fake_key("hon-new"))

    def test_a_thiefs_departure_is_reversed_the_same_way(self):
        h = Hand(*inert("hon", "ina", "ivy"))
        h.add("depart", "hon", {})                                        # signed by a thief holding the key alone
        ask(h, "hon", new="hon-new")
        h.add("rekey_recover_apply", "hon", {}, days=45 + SEC / DAY, key_of="hon-new")
        self.assertEqual(h.st.members["hon"].status, "active")

    def test_a_master_who_answered_or_reached_the_third_degree_within_the_year_is_waited_for(self):
        h = Hand(*inert("hon", "ina"), mk("new", 3, t=T0 - 100 * DAY, activity=[T0]))
        h.st.members["ina"].heard = T0 - 300 * DAY
        ask(h, "hon", new="hon-new")
        r = h.st.recoveries["hon"]
        self.assertEqual(ledger.cosigners_needed(h.st, r, h.now), 2)
        self.assertEqual(h.st.recovery_status(r, h.now), "requested")
        h.st.members["ina"].heard = T0 - 366 * DAY                        # a year without an answer
        self.assertEqual(ledger.cosigners_needed(h.st, r, h.now), 1)

    def test_any_master_still_opposes_and_the_old_key_still_objects(self):
        h = Hand(*inert("hon", "ina"))
        ask(h, "hon", new="hon-new")
        h.add("rekey_oppose", "ina", {"login": "hon"}, days=1)            # an inert Master keeps the power to oppose
        self.assertEqual(h.st.recovery_status(h.st.recoveries["hon"], h.now), "opposed")
        h = Hand(*inert("hon", "ina"))
        ask(h, "hon", new="hon-new")
        h.add("rekey_object", "hon", {}, days=1)
        self.assertEqual(h.st.recovery_status(h.st.recoveries["hon"], h.now), "objected")

    def test_the_sponsors_suffice_where_the_only_other_master_answers_nothing(self):
        """The rule that one co-signer must not be a sponsor counts the same Masters: an inert Master who is not a
        sponsor does not hold it shut (it would have held it shut forever)."""
        h = Hand(*inert("hon", sponsors=("s0", "s1")), *masters("s0", "s1"), *inert("ina"))
        ask(h, "hon", new="hon-new")
        h.add("rekey_cosign", "s0", {"login": "hon"}, days=1)
        h.add("rekey_cosign", "s1", {"login": "hon"}, days=1)
        r = h.st.recoveries["hon"]
        self.assertEqual((r.notice, ledger.only_sponsors(h.st, r, r.cosigners, h.now)), (h.now, False))

    def test_a_recovery_that_lacks_its_cosignatures_is_never_shown_ready(self):
        from tests.test_liveness import custodian
        h = Hand(*inert("hon"), *masters("ada"), custodians={"warden": custodian(member="ada")},
                 custodian_threshold=1)
        h.add("correction", "warden", {"act": "freeze_key", "target": {"login": "hon"}, "ground": "key_compromised",
                                       "reason_sha256": "ab" * 32})
        ask(h, "hon", new="hon-new")
        r = h.st.recoveries["hon"]
        h.now = h.st.recovery_notice_end(r, h.now) + SEC
        self.assertEqual(h.st.recovery_status(r, h.now), "pending")
        h.refused(self, "has 0 of the 1 co-signatures", "rekey_recover_apply", "hon", {}, key_of="hon-new")
        h.add("rekey_cosign", "ada", {"login": "hon"})
        self.assertEqual(h.st.recovery_status(r, h.now), "ready")
        h.add("rekey_recover_apply", "hon", {}, key_of="hon-new")


class InertMastersHoldNoDoorShut(unittest.TestCase):
    def test_stuck_without_it_one_master_among_six_inert_peers_never_admitted_anyone(self):
        """Without this rule, outside the Founding Phase, a responsive Master among six who sign a work a year
        needed a second sponsor nobody would give: every admission ballot was refused, for good."""
        h = Hand(*inert("hon", *[f"m{i}" for i in range(6)]))
        self.assertFalse(h.st.founding_phase(h.now))
        for i, bid in enumerate(("a1", "a2")):                            # two full calls make the six silent
            amend(h, bid, "hon", path=f"docs/x{i}.md")
            lapse(h, bid, ["hon"], "hon")
        self.assertEqual(h.st.present_masters(h.now), ["hon"])
        h.add("invite", "hon", {"login": "eli", "github_id": 77})
        h.add("petition", "eli", {"key": fake_key("eli"), "declaration_sha256": DECL})
        p = h.st.petitions["eli"]
        self.assertEqual(ledger.sponsors_required(h.st, h.now + 30 * DAY - SEC, p), 2)
        h.now += 30 * DAY
        self.assertEqual(ledger.sponsors_required(h.st, h.now, p), 1)
        h.add("ballot_open", "hon", {"id": "adm", "kind": "admission", "subject": {"candidate": "eli"}})
        self.assertEqual(len(h.st.ballots["adm"].electors), 7)            # every Master keeps the vote
        self.assertEqual(vote(h, "adm", {"hon": "yes"}).result, "passed")

    def test_seven_present_masters_still_need_two_sponsors(self):
        h = Hand(*masters(*SEVEN_MASTERS))
        h.add("invite", "hiram", {"login": "eli", "github_id": 77})
        h.add("petition", "eli", {"key": fake_key("eli"), "declaration_sha256": DECL})
        self.assertEqual(ledger.sponsors_required(h.st, h.now + 31 * DAY, h.st.petitions["eli"]), 2)


if __name__ == "__main__":
    unittest.main()
