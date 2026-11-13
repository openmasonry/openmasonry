"""Liveness: the ledger and the game never lock up while one honest member with a key exists.

Each rule is tested the same way: the stuck scenario first (it is refused, or nothing can
move, without the rule), then what the rule lets through, then an abuse test (the rule cannot be used to seize
power). The last class replays whole populations. Every test uses `Fast` chains or states built by hand
(tests.test_strict): the "signature" of an entry is the public key that signed it. Nothing touches the network.

The rules: the founder's fallback (a founder takes up the Custodian office again), succession, no requirement
exceeds the people who exist, no sanction on a Master decided by one elector, non-responders never block,
dormancy lowers the quorum and never removes a vote, the unstoppable set, amendment hygiene, upgrade safety, the
judge is a convenience, and a lot that cannot be drawn lapses.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import re
import shutil
import subprocess
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from openmasonry import canon, govern, identity, ledger, verify
from openmasonry.ledger import (BEACON_DELAY_ROUNDS, Ballot, Custodian, Invalid, Succession, apply, commitment,
                                drand_round, drand_time, iso, replay)
from tests.test_custodian import SEVEN, correct, freeze, halt, lodge
from tests.test_protocol import DECL, FOUNDERS, T0, Chain, canon_digest, copy_governed, genesis_body, gid, salt_of
from tests.test_strict import DAY, SEC, Fast, by_key, fake_key, hand_state, mk, tmpdir, write_ledger

REPO = Path(__file__).resolve().parents[1]
URL = "https://example.org/work"
ZERO = "0" * 64


class Hand:
    """A state built by hand (members of any degree, custodians, a past), carried forward entry by entry."""

    def __init__(self, *members, now=T0, **kw):
        self.st = hand_state(*members, seq=0, head="11" * 32, time=now, **kw)
        self.now = now

    def entry(self, typ, actor, body, key_of=None) -> dict:
        return {"seq": self.st.seq + 1, "prev": self.st.head, "time": iso(self.now), "type": typ, "actor": actor,
                "body": body, "sig": fake_key(key_of or actor)}

    def add(self, typ, actor, body, days=0.0, key_of=None) -> int:
        self.now += timedelta(days=days)
        apply(self.st, self.entry(typ, actor, body, key_of), by_key)
        return self.st.seq

    def refused(self, test, pattern, typ, actor, body, days=0.0, key_of=None) -> None:
        """The entry is refused with `pattern`; nothing changes (the clock moves by `days` all the same)."""
        self.now += timedelta(days=days)
        st = copy.deepcopy(self.st)
        with test.assertRaisesRegex(Invalid, pattern):
            apply(st, self.entry(typ, actor, body, key_of), by_key)

    def fork(self) -> "Hand":
        return copy.deepcopy(self)


def vote(h, bid, votes, close_by=None, wait_close=True):
    """Commit every vote now, reveal them past the gap, and close the ballot (`close_by`, else the first voter)."""
    for who, v in votes.items():
        h.add("ballot_commit", who, {"id": bid, "commitment": commitment(bid, who, v, salt_of(who))})
    h.now += timedelta(days=7.3)
    for who, v in votes.items():
        h.add("ballot_reveal", who, {"id": bid, "vote": v, "salt": salt_of(who)}, days=0.01)
    h.now += timedelta(days=3 if wait_close else 0)
    h.add("ballot_close", close_by or next(iter(votes)), {"id": bid})
    return h.st.ballots[bid]


def lapse(h, bid, voters, closer):
    """Only `voters` vote; the ballot runs to its end and lapses for want of quorum."""
    return vote(h, bid, {v: "yes" for v in voters}, close_by=closer) if voters else _close_empty(h, bid, closer)


def _close_empty(h, bid, closer):
    h.now += timedelta(days=10.3)
    h.add("ballot_close", closer, {"id": bid})
    return h.st.ballots[bid]


def amend(h, bid, by, path="README.md", new="ab" * 32, **extra):
    h.add("ballot_open", by, {"id": bid, "kind": "amendment", "subject": {"path": path, "new_sha256": new}} | extra)
    return h.st.ballots[bid]


def claim_body(name="keeper") -> dict:
    """A custodian claim in Fast form: each proof is the key that signs it."""
    return {"name": name, "key": fake_key(name), "revoke_key": fake_key(f"{name}-revoke"), "proof": fake_key(name),
            "revoke_proof": fake_key(f"{name}-revoke")}


def custodian(name="warden", member="hiram", alive=T0, **kw) -> Custodian:
    return Custodian(name, fake_key(name), fake_key(f"{name}-revoke"), member, alive, since=alive, **kw)


def open_exam(h, who, degree):
    rnd = drand_round(h.now) + BEACON_DELAY_ROUNDS
    h.add("exam_open", who, {"candidate": who, "degree": degree, "work_ref": URL, "beacon_round": rnd})
    return rnd


def draw(h, who, degree, rnd, days=0.34):
    h.add("exam_draw", who, {"candidate": who, "degree": degree, "beacon": f"{rnd:064x}"}, days=days)
    return h.st.exams[(who, degree)]


def examine(h, who, degree, verdict="pass"):
    ex = draw(h, who, degree, open_exam(h, who, degree))
    for x in ex.examiners:
        h.add("exam_report", x, {"candidate": who, "degree": degree, "verdict": verdict})
    return h.st.exams[(who, degree)]


def advance(h, who, degree, electors=None):
    examine(h, who, degree)
    bid = f"adv-{who}-{degree}"
    h.add("ballot_open", who, {"id": bid, "kind": "advancement", "subject": {"member": who, "degree": degree}})
    b = h.st.ballots[bid]
    return vote(h, bid, {x: "yes" for x in sorted(electors or b.electors)}, close_by=who)


def admit(h, who, by, github_id=77, voters=None):
    h.add("invite", by, {"login": who, "github_id": github_id})
    h.add("petition", who, {"key": fake_key(who), "declaration_sha256": DECL})
    bid = f"adm-{who}"
    h.add("ballot_open", by, {"id": bid, "kind": "admission", "subject": {"candidate": who}})
    return vote(h, bid, {x: "yes" for x in sorted(voters or h.st.ballots[bid].electors)}, close_by=by)


def dormant(login, degree=3, **kw):
    """A member whose last activity is more than a year old."""
    return mk(login, degree, activity=[T0 - 400 * DAY], **kw)


# ---------------------------------------------------------------- the founder's fallback ----

class FoundersFallback(unittest.TestCase):
    def lapsed(self) -> Fast:
        """Three founders and the custodian `warden` (hiram's), silent for more than 180 days."""
        c = lodge()
        c.now = T0 + 181 * DAY
        return c

    def test_stuck_without_it_a_lapsed_custodian_can_never_be_replaced(self):
        c = self.lapsed()
        st = c.state()
        self.assertEqual(st.custodians_live(c.now), [])
        correct(c, "freeze_key", {"login": "ada"}, "key_compromised")
        c.refused(self, "the custodian key of warden is lapsed and signs nothing")

    def test_a_founder_takes_up_the_office_again_after_thirty_days_of_notice(self):
        c = self.lapsed()
        seq = c.add("custodian_claim", "hiram", claim_body())["seq"]
        st = c.state()
        cl = st.claims[seq]
        self.assertEqual((cl.founder, cl.name, cl.key, cl.revoke_key, cl.time, st.claim_status(cl, c.now)),
                         ("hiram", "keeper", fake_key("keeper"), fake_key("keeper-revoke"), c.now, "pending"))
        self.assertEqual(st.name_holders("KEEPER", c.now), [("claim", "keeper")])
        self.assertEqual(st.key_holders(fake_key("keeper-revoke"), c.now), [("claim", "keeper")])
        self.assertIn(ledger.point(fake_key("keeper")), st.known_keys)
        start = c.now
        c.now = start + 30 * DAY - SEC
        c.add("custodian_claim_apply", "hiram", {"seq": seq})
        c.refused(self, rf"the claim of entry {seq} is under notice until .* \(30 days after it\)")
        c.now = start + 30 * DAY
        c.add("custodian_claim_apply", "hiram", {"seq": seq})
        st = c.state()
        k = st.custodians["keeper"]
        self.assertEqual((k.member, k.alive, k.since, k.claim, k.genesis, st.custodian_threshold, st.claims[seq].applied),
                         ("hiram", c.now, c.now, seq, False, 1, c.now))
        self.assertEqual(st.custodians_live(c.now), ["keeper"])
        self.assertEqual(st.custodian_end(k), c.now + 180 * DAY + SEC)          # silence, as at genesis
        k.alive = c.now + 2550 * DAY
        self.assertEqual(st.custodian_end(k), c.now + 2555 * DAY + SEC)         # the term runs from the claim's effect
        f = correct(c, "freeze_key", {"login": "ada"}, "key_compromised", by="keeper")
        self.assertIn(f, c.state().corrections)

    def test_the_conditions_are_checked_when_signed_and_again_when_applied(self):
        c = lodge()                                                     # warden is live
        c.add("custodian_claim", "hiram", claim_body())
        c.refused(self, "the custodian key of warden is live: the office is taken up again only when no custodian "
                        "key is live")
        c = self.lapsed()
        seq = c.add("custodian_claim", "ada", claim_body())["seq"]      # any founder, not only the custodian's
        c.add("custodian_claim", "carol", claim_body("porter"))
        c.refused(self, rf"a claim of the Custodian office is already pending \(entry {seq}\)")
        c.add("custodian_claim_apply", "carol", {"seq": seq}, days=30)
        c.refused(self, f"only ada, who signed the claim of entry {seq}, applies it")
        c.add("custodian_claim_apply", "ada", {"seq": seq}, days=30.1)
        c.refused(self, f"the claim of entry {seq} is expired")       # 60 days: applied in time, or never
        c.add("custodian_claim", "carol", claim_body("porter"))          # and a new claim may be made
        self.assertEqual(c.state().claims[c.state().seq].name, "porter")

    def test_never_with_three_non_founder_masters_never_after_the_sunset_never_by_a_non_founder(self):
        base = [mk("hiram", founder=True), mk("ada", founder=True), mk("m1"), mk("m2"), mk("bea", 2)]
        h = Hand(*base)
        h.refused(self, "only a founder may claim the Custodian office", "custodian_claim", "m1", claim_body())
        h.refused(self, "only a founder may claim", "custodian_claim", "bea", claim_body())
        h.fork().add("custodian_claim", "hiram", claim_body())            # two non-founder Masters: allowed
        h3 = Hand(*base, mk("m3"))
        h3.refused(self, "3 active Master Builders who are not founders exist: with 3 or more the Custodian office "
                         "is filled only by amendment", "custodian_claim", "hiram", claim_body())
        hs = Hand(*base)
        hs.st.sunset = T0 - DAY
        hs.refused(self, "the Sunset was reached at .*: no founder takes up the Custodian office after it",
                   "custodian_claim", "hiram", claim_body())

    def test_never_after_a_removal_ballot_passed_against_that_founders_key_and_repeatable_otherwise(self):
        removed = custodian(revoked=T0 - DAY, removed="rm-warden")
        h = Hand(mk("hiram", founder=True), mk("ada", founder=True), custodians={"warden": removed})
        h.refused(self, r"a removal ballot \(rm-warden\) passed against the custodian key warden of hiram: that founder "
                        "never takes up the office again", "custodian_claim", "hiram", claim_body())
        h.fork().add("custodian_claim", "ada", claim_body())              # another founder still may
        revoked = custodian(revoked=T0 - DAY)                             # its own revoke key removed it: no bar
        h = Hand(mk("hiram", founder=True), custodians={"warden": revoked})
        seq = h.add("custodian_claim", "hiram", claim_body())
        h.add("custodian_claim_apply", "hiram", {"seq": seq}, days=30)
        h.add("custodian_revoke", "keeper", {"name": "keeper"}, key_of="keeper-revoke", days=1)
        h.refused(self, "the custodian name 'keeper' is held by the custodian 'keeper'", "custodian_claim", "hiram",
                  claim_body(), days=1)
        again = h.add("custodian_claim", "hiram", claim_body("keeper2"))   # as often as needed
        self.assertEqual(h.st.claim_status(h.st.claims[again], h.now), "pending")

    def test_the_claim_proves_new_keys_under_a_free_name(self):
        c = self.lapsed()
        for change, pattern in ((dict(name="Warden"), "the custodian name 'Warden' is held by the custodian 'warden'"),
                                (dict(name="ADA"), "is held by the member 'ada'"),
                                (dict(name="-x"), "custodian names follow login rules"),
                                (dict(key=fake_key("warden"), proof=fake_key("warden")), "must differ from each other "
                                                                                          "and be new keys"),
                                (dict(revoke_key=fake_key("keeper"), revoke_proof=fake_key("keeper")), "be new keys"),
                                (dict(key=fake_key("ada"), proof=fake_key("ada")), "be new keys"),
                                (dict(proof=fake_key("other")), "bad custodian proof"),
                                (dict(revoke_proof=fake_key("other")), "bad custodian revoke proof"),
                                (dict(key="ssh-rsa AAAA"), "keys must be ssh-ed25519")):
            c.add("custodian_claim", "hiram", claim_body() | change)
            c.refused(self, pattern)
        c.add("custodian_claim", "hiram", claim_body() | {"extra": 1})
        c.refused(self, "malformed custodian_claim entry: unknown field 'extra'")

    def test_abuse_a_stolen_founder_key_is_stopped_by_one_non_founder_master(self):
        """The thief holds hiram's member key and claims the office; m1, a Master who is not a founder, objects."""
        h = Hand(mk("hiram", founder=True), mk("m1"), mk("bea", 2))
        seq = h.add("custodian_claim", "hiram", claim_body("thief"))
        h.refused(self, "only a Master Builder who is not a founder may object", "custodian_claim_object", "bea",
                  {"seq": seq})
        h.refused(self, "only a Master Builder who is not a founder may object", "custodian_claim_object", "hiram",
                  {"seq": seq})
        h.add("custodian_claim_object", "m1", {"seq": seq}, days=29)
        cl = h.st.claims[seq]
        self.assertEqual((cl.objected, cl.objector, h.st.claim_status(cl, h.now)), (h.now, "m1", "objected"))
        h.refused(self, f"the claim of entry {seq} is objected", "custodian_claim_apply", "hiram", {"seq": seq}, days=2)
        h.refused(self, f"the claim of entry {seq} is objected", "custodian_claim_object", "m1", {"seq": seq})
        self.assertEqual(h.st.custodians, {})
        self.assertEqual(h.st.name_holders("thief", h.now), [])          # the name and keys are free again…
        self.assertIn(ledger.point(fake_key("thief")), h.st.known_keys)    # …but the keys are never registered again

    def test_abuse_a_master_who_appears_during_the_notice_stops_the_application(self):
        h = Hand(mk("hiram", founder=True), mk("m1"), mk("m2"), mk("bea", 2, t=T0 - 100 * DAY, activity=[T0]))
        seq = h.add("custodian_claim", "hiram", claim_body())
        h.st.members["bea"].degree, h.st.members["bea"].since[3] = 3, h.now    # a third non-founder Master
        h.refused(self, "3 active Master Builders who are not founders exist", "custodian_claim_apply", "hiram",
                  {"seq": seq}, days=30)

    def test_the_identity_gate_requires_the_founders_github_account(self):
        c = self.lapsed()
        since = len(c.entries)
        c.add("custodian_claim", "hiram", claim_body())
        stub = mock.Mock(side_effect=AssertionError("no network"))
        self.assertEqual(identity.pr_problems(c.entries, since, "hiram", stub, stub, author_id=gid("hiram")), [])
        bad = identity.pr_problems(c.entries, since, "hiram", stub, stub, author_id=gid("ada"))
        self.assertEqual(len(bad), 1)
        self.assertIn(f"hiram is the GitHub account with id {gid('hiram')}", bad[0])


# ---------------------------------------------------------------- succession ----

def orphans(**kw) -> Hand:
    """hiram, the only Master Builder (a founder); bea of the 2nd degree; cal and dot of the 1st."""
    return Hand(mk("hiram", founder=True), mk("bea", 2), mk("cal", 1), mk("dot", 1), **kw)


class Succession_(unittest.TestCase):
    def test_stuck_without_it_nobody_can_invite_once_the_last_master_leaves(self):
        h = orphans()
        h.add("depart", "hiram", {})
        h.refused(self, "only Master Builders may invite", "invite", "bea", {"login": "eli", "github_id": 77})
        h.refused(self, "only Master Builders may open an amendment ballot", "ballot_open", "bea",
                  {"id": "am", "kind": "amendment", "subject": {"path": "README.md", "new_sha256": "ab" * 32}})

    def test_a_claim_nobody_answers_for_ninety_days_takes_effect(self):
        h = orphans()
        h.add("depart", "hiram", {})
        seq = h.add("succession_claim", "cal", {})
        self.assertEqual((h.st.succession.seq, h.st.succession.by, h.st.succession_status(h.now)), (seq, "cal", "pending"))
        self.assertEqual(h.st.successors(h.now), [])
        start = h.now
        h.now = start + 90 * DAY - SEC
        h.refused(self, "only Master Builders may invite", "invite", "bea", {"login": "eli", "github_id": 77})
        h.now = start + 90 * DAY
        self.assertEqual((h.st.succession_status(h.now), h.st.successors(h.now)), ("in_force", ["bea"]))
        b = admit(h, "eli", "bea")                                       # one sponsor: no Master exists
        self.assertEqual((b.result, b.electors, h.st.members["eli"].sponsors), ("passed", frozenset({"bea"}), ("bea",)))
        h.refused(self, "only Master Builders may invite", "invite", "cal", {"login": "fay", "github_id": 78})

    def test_successors_examine_and_elect_and_the_game_reaches_the_third_degree_again(self):
        h = orphans()
        h.add("depart", "hiram", {})
        h.add("succession_claim", "cal", {})
        h.now += 90 * DAY
        b = advance(h, "cal", 2)                                          # bea examines (k lowered) and elects
        self.assertEqual((b.result, h.st.exams[("cal", 2)].examiners, b.electors), ("passed", ("bea",), frozenset({"bea"})))
        self.assertEqual(h.st.successors(h.now), ["bea", "cal"])
        b = advance(h, "bea", 3)                                          # cal examines and elects
        self.assertEqual((b.result, h.st.exams[("bea", 3)].examiners, b.electors), ("passed", ("cal",), frozenset({"cal"})))
        self.assertEqual((h.st.masters(h.now), h.st.successors(h.now), h.st.succession_status(h.now)),
                         (["bea"], [], "in_force"))                     # a real Master: successors are no more

    def test_successors_hold_no_other_power(self):
        h = orphans()
        h.add("depart", "hiram", {})
        h.add("succession_claim", "cal", {})
        h.now += 91 * DAY
        for kind, subject in (("amendment", {"path": "README.md", "new_sha256": "ab" * 32}),
                              ("witness", {"action": "remove", "name": "tyler"}),
                              ("sanction", {"member": "cal", "measure": "admonish"})):
            h.refused(self, "only Master Builders may open", "ballot_open", "bea", {"id": "x", "kind": kind,
                                                                                    "subject": subject})
        st, now = h.st, h.now
        self.assertEqual((st.masters(now), st.founding_phase(now), ledger.sponsors_required(st, now),
                          st.non_founder_masters(now), ledger.electors_for(st, "amendment", {}, now)),
                         ([], True, 1, 0, frozenset()))
        self.assertFalse(ledger.sunset_reached(st, now))

    def test_who_may_claim_and_when(self):
        h = orphans()
        h.refused(self, r"an active Master Builder who is neither dormant nor silent exists \(hiram\): no succession", "succession_claim", "bea", {})
        hd = Hand(dormant("hiram", founder=True), mk("cal", 1))
        hd.refused(self, "a Master Builder needs no succession", "succession_claim", "hiram", {})
        seq = hd.add("succession_claim", "cal", {})
        hd.refused(self, rf"a succession claim is already pending \(entry {seq}\)", "succession_claim", "cal", {})
        hd.refused(self, rf"a succession claim is already in force \(entry {seq}\)", "succession_claim", "cal", {},
                   days=90)

    def test_abuse_a_dormant_master_who_wakes_up_cancels_the_claim(self):
        """cal (1st degree) claims while hiram, the only Master, is dormant: one entry of hiram ends it."""
        h = Hand(dormant("hiram", founder=True), mk("cal", 1), mk("dot", 1))
        h.add("succession_claim", "cal", {})
        h.add("work", "hiram", {"ref": URL}, days=89)
        s = h.st.succession
        self.assertEqual((s.end, s.canceled_by, h.st.succession_status(h.now + 30 * DAY)), (h.now, "hiram", "canceled"))
        h.refused(self, "only Master Builders may invite", "invite", "cal", {"login": "eli", "github_id": 77}, days=2)
        h.refused(self, r"an active Master Builder who is neither dormant nor silent exists \(hiram\)", "succession_claim", "cal", {})

    def test_a_departure_or_a_vote_of_the_claimant_does_not_cancel_and_three_masters_end_it(self):
        h = Hand(dormant("hiram", founder=True), mk("cal", 1), mk("dot", 1))
        h.add("succession_claim", "cal", {})
        h.add("depart", "hiram", {}, days=1)                              # a Master who leaves cancels nothing
        self.assertEqual(h.st.succession_status(h.now), "pending")
        h3 = Hand(mk("m1"), mk("m2"), mk("m3"), mk("cal", 1))
        h3.st.succession = Succession(1, "cal", T0 - 100 * DAY)
        h3.add("work", "cal", {"ref": URL})
        self.assertEqual((h3.st.succession.end, h3.st.succession_status(h3.now)), (h3.now, "ended"))


# ---------------------------------------------------------------- no requirement exceeds who exists ----

def ask(c, who="ada", new=None, days=0.0):
    name = new or f"{who}-new"
    return c.add("rekey_recover", who, {"key": c.key(name), "proof": c.key(name)}, days=days, key_of=name)


class NoRequirementExceedsWhoExists(unittest.TestCase):
    def test_the_final_recovery_needs_as_many_cosigners_as_exist_with_the_longer_notice(self):
        """Two founders and no custodian: the old key of ada stops her first recovery; the second is final."""
        c = lodge(custodians=(), founders=["hiram", "ada"])
        ask(c)
        c.add("rekey_cosign", "hiram", {"login": "ada"})
        c.add("rekey_object", "ada", {}, days=1)                          # whoever holds the old key says no
        ask(c, new="ada-2", days=90)
        st = c.state()
        r = st.recoveries["ada"]
        self.assertTrue(r.final)
        self.assertEqual((ledger.cosigners_needed(st, r, c.now), ledger.nominal_cosigners(r)), (1, 3))   # was 3 flat
        c.add("rekey_cosign", "hiram", {"login": "ada"})
        c.add("rekey_object", "ada", {})
        c.refused(self, "the old key cannot stop this one")
        start = c.now
        c.now = start + 45 * DAY - SEC
        c.add("rekey_recover_apply", "ada", {}, key_of="ada-2")
        c.refused(self, r"under notice until .* \(45 days after its notice began; 45 because fewer "
                        r"Master Builders exist than the 3 co-signers it asks for\)")
        c.now = start + 45 * DAY
        c.add("rekey_recover_apply", "ada", {}, key_of="ada-2")
        self.assertEqual(c.state().members["ada"].key, fake_key("ada-2"))

    def test_a_recovery_never_needs_a_custodian_who_answers(self):
        """warden is live but never freezes: the open recovery goes ahead with three Masters and 30 days."""
        c = lodge(founders=SEVEN)
        ask(c)
        st = c.state()
        r = st.recoveries["ada"]
        self.assertEqual((r.freeze, st.recovery_status(r, c.now), ledger.cosigners_needed(st, r, c.now)),
                         (None, "requested", 3))
        for who in ("carol", "dan", "eve"):
            c.add("rekey_cosign", who, {"login": "ada"})
        c.add("rekey_recover_apply", "ada", {}, days=30, key_of="ada-new")
        self.assertEqual(c.state().members["ada"].key, fake_key("ada-new"))

    def test_the_notice_is_longer_whenever_the_cosigners_were_lowered(self):
        c = lodge(custodians=(), founders=["hiram", "ada"])
        ask(c)
        c.add("rekey_cosign", "hiram", {"login": "ada"})
        st = c.state()
        r = st.recoveries["ada"]
        self.assertEqual((st.recovery_notice_days(r, c.now), st.recovery_notice_end(r, c.now)), (45, c.now + 45 * DAY))
        c.add("rekey_recover_apply", "ada", {}, days=30, key_of="ada-new")
        c.refused(self, "45 because fewer Master Builders exist than the 3 co-signers it asks for")

    def test_objections_never_need_more_objectors_than_exist(self):
        for eligible in range(1, 40):
            self.assertLessEqual(ledger.objections_needed(eligible), eligible)


# ---------------------------------------------------------------- a sanction on a Master ----

class NoSanctionByOneElector(unittest.TestCase):
    def test_stuck_scenario_two_masters_one_expels_the_other_alone(self):
        h = Hand(mk("hiram", founder=True), mk("ada", founder=True))
        for measure in ("expel", "suspend", "admonish", "expel_for_fraud"):
            h.refused(self, "a sanction on a Master Builder is never decided by a single elector: this electorate "
                            "has 1", "ballot_open", "hiram",
                      {"id": "s", "kind": "sanction", "subject": {"member": "ada", "measure": measure}})

    def test_one_vote_never_decides_it_even_where_the_quorum_is_one(self):
        h = Hand(mk("hiram", founder=True), mk("ada", founder=True), dormant("carol", founder=True))
        h.add("ballot_open", "hiram", {"id": "s", "kind": "sanction", "subject": {"member": "ada", "measure": "suspend"}})
        b = h.st.ballots["s"]
        self.assertEqual((b.electors, b.quorum_base(), b.frozen["master"]), (frozenset({"hiram", "carol"}), 1, True))
        b = vote(h, "s", {"hiram": "yes"})
        self.assertEqual((b.result, h.st.members["ada"].status), ("lapsed", "active"))

    def test_a_sanction_on_a_member_below_the_third_degree_is_unchanged(self):
        h = Hand(mk("hiram", founder=True), mk("bea", 2))
        h.add("ballot_open", "hiram", {"id": "s", "kind": "sanction", "subject": {"member": "bea", "measure": "suspend"}})
        b = vote(h, "s", {"hiram": "yes"})
        self.assertEqual((b.result, h.st.members["bea"].status), ("passed", "suspended"))


# ---------------------------------------------------------------- non-responders never block ----

class NonRespondersNeverBlock(unittest.TestCase):
    def three(self) -> Hand:
        return Hand(mk("hiram", founder=True), mk("ada", founder=True), mk("carol", founder=True))

    def test_a_lapsed_ballot_is_re_run_once_without_waiting_for_those_who_did_not_vote(self):
        h = self.three()
        amend(h, "am", "hiram")
        self.assertEqual(lapse(h, "am", ["hiram"], "hiram").result, "lapsed")     # stuck: quorum 3, one vote
        b = amend(h, "am-2", "hiram", rerun="am")
        self.assertEqual((b.rerun, b.electors, b.quorum_base()), ("am", frozenset({"hiram", "ada", "carol"}), 1))
        self.assertEqual(vote(h, "am-2", {"hiram": "yes"}).result, "passed")
        self.assertEqual(h.st.pins["README.md"], "ab" * 32)

    def test_abuse_a_re_run_timed_for_an_absence_still_counts_the_absent_who_returns(self):
        h = self.three()
        amend(h, "am", "hiram")
        lapse(h, "am", ["hiram"], "hiram")
        amend(h, "am-2", "hiram", rerun="am")
        self.assertEqual(vote(h, "am-2", {"hiram": "yes", "ada": "no"}).result, "failed")   # ada kept her vote

    def test_what_a_re_run_is(self):
        h = self.three()
        amend(h, "am", "hiram")
        lapse(h, "am", ["hiram"], "hiram")
        for body, pattern in (({"rerun": "nope"}, "ballot nope did not lapse"),
                              ({"rerun": "am", "commit_days": 6}, "a re-run gives at least 7 days to commit"),
                              ({"rerun": 5}, "field 'rerun' must be a string")):
            h.refused(self, pattern, "ballot_open", "hiram", {"id": "x", "kind": "amendment",
                                                              "subject": {"path": "README.md", "new_sha256": "ab" * 32}} | body)
        h.refused(self, "a re-run has the kind and the subject of the ballot it re-runs", "ballot_open", "hiram",
                  {"id": "x", "kind": "amendment", "subject": {"path": "README.md", "new_sha256": "cd" * 32}, "rerun": "am"})
        h.fork().refused(self, "lapsed more than 30 days ago", "ballot_open", "ada",
                         {"id": "x", "kind": "amendment", "subject": {"path": "README.md", "new_sha256": "ab" * 32},
                          "rerun": "am"}, days=30.1)
        amend(h, "am-2", "ada", rerun="am")                               # any member qualified to open it
        lapse(h, "am-2", [], "ada")
        h.refused(self, "ballot am-2 re-ran ballot am: a ballot is re-run once, and a re-run never", "ballot_open",
                  "ada", {"id": "x", "kind": "amendment", "subject": {"path": "README.md", "new_sha256": "ab" * 32},
                          "rerun": "am-2"})
        h.refused(self, "ballot am was re-run already, by ballot am-2", "ballot_open", "carol",
                  {"id": "x", "kind": "amendment", "subject": {"path": "README.md", "new_sha256": "ab" * 32},
                   "rerun": "am"})

    def exam_hand(self) -> Hand:
        return Hand(mk("hiram", founder=True), mk("ada", founder=True), mk("carol", founder=True),
                    mk("cand", 1, t=T0 - 40 * DAY, activity=[T0]))

    def test_an_exam_whose_examiner_never_reports_lapses_and_the_silent_one_is_skipped_next(self):
        h = self.exam_hand()
        ex = draw(h, "cand", 2, open_exam(h, "cand", 2))
        speaker, silent = ex.examiners
        h.add("exam_report", speaker, {"candidate": "cand", "degree": 2, "verdict": "pass"})
        h.now = ex.opened + 60 * DAY + SEC
        ex = h.st.exams[("cand", 2)]
        self.assertEqual((ex.failed(h.now, h.st), ex.timed_out(h.now, h.st), ex.silent(h.now, h.st)), (False, True, (silent,)))
        open_exam(h, "cand", 2)                                         # at once: no retry wait, no penalty
        ex = h.st.exams[("cand", 2)]
        self.assertEqual((ex.skipped, silent in ex.pool), ((silent,), False))

    def test_the_silent_examiner_is_kept_when_nobody_else_is_left(self):
        h = Hand(mk("hiram", founder=True), mk("cand", 1, t=T0 - 40 * DAY, activity=[T0]))
        ex = draw(h, "cand", 2, open_exam(h, "cand", 2))
        self.assertEqual(ex.examiners, ("hiram",))
        h.now = ex.opened + 61 * DAY
        open_exam(h, "cand", 2)
        self.assertEqual((h.st.exams[("cand", 2)].pool, h.st.exams[("cand", 2)].skipped), (("hiram",), ()))

    def test_the_32nd_degree_exam_at_exactly_seven_masters(self):
        """Stuck before: seven examiners, six Masters besides the candidate, and the Founding Phase over."""
        others = [mk(f"m{i}") for i in range(6)]
        h = Hand(mk("cand", 31, t=T0 - 400 * DAY, activity=[T0]), *others)
        self.assertFalse(h.st.founding_phase(h.now))
        open_exam(h, "cand", 32)
        ex = h.st.exams[("cand", 32)]
        self.assertEqual((ex.k, len(ex.pool)), (6, 6))

    def test_the_lowered_number_still_needs_somebody(self):
        h = Hand(mk("cand", 3, t=T0 - 400 * DAY, activity=[T0]))
        h.refused(self, "3 examiners required, only 0 available", "exam_open", "cand",
                  {"candidate": "cand", "degree": 4, "work_ref": URL,
                   "beacon_round": drand_round(T0) + BEACON_DELAY_ROUNDS})

    def test_founding_phase_the_second_sponsor_is_waived_after_thirty_days_and_the_other_master_still_votes(self):
        h = Hand(mk("hiram", founder=True), mk("ada", founder=True))
        h.add("invite", "hiram", {"login": "eli", "github_id": 77})
        h.add("petition", "eli", {"key": fake_key("eli"), "declaration_sha256": DECL})
        body = {"id": "adm", "kind": "admission", "subject": {"candidate": "eli"}}
        h.now = T0 + 30 * DAY - SEC
        h.refused(self, "candidate lacks sponsors", "ballot_open", "hiram", body)
        self.assertEqual(ledger.sponsors_required(h.st, h.now, h.st.petitions["eli"]), 2)
        h.now = T0 + 30 * DAY
        self.assertEqual(ledger.sponsors_required(h.st, h.now, h.st.petitions["eli"]), 1)
        h.add("ballot_open", "hiram", body)
        self.assertEqual(h.st.ballots["adm"].electors, frozenset({"hiram", "ada"}))
        self.assertEqual(vote(h, "adm", {"hiram": "yes", "ada": "no"}).result, "failed")   # ada's black ball stands
        self.assertNotIn("eli", h.st.members)


# ---------------------------------------------------------------- dormancy and the vote ----

class DormancyKeepsTheVote(unittest.TestCase):
    def test_abuse_the_first_dormant_founder_to_wake_is_no_electorate_of_one(self):
        h = Hand(mk("hiram", founder=True), dormant("ada", founder=True), dormant("carol", founder=True))
        b = amend(h, "am", "hiram")
        self.assertEqual((b.electors, b.quorum_base()), (frozenset({"hiram", "ada", "carol"}), 1))
        self.assertEqual(vote(h, "am", {"hiram": "yes", "ada": "no"}).result, "failed")
        self.assertNotIn("README.md", h.st.pins)

    def test_the_dormant_do_not_hold_up_the_quorum(self):
        h = Hand(mk("hiram", founder=True), dormant("ada", founder=True), dormant("carol", founder=True))
        amend(h, "am", "hiram")
        self.assertEqual(vote(h, "am", {"hiram": "yes"}).result, "passed")

    def test_every_rung_keeps_its_dormant_members(self):
        st = hand_state(mk("a"), mk("b"), dormant("c"), mk("x", 1), dormant("y", 2))
        for kind, subject, electors, base in (("amendment", {}, {"a", "b", "c"}, 2),
                                              ("admission", {"candidate": "z"}, {"a", "b", "c", "y"}, 2),
                                              ("sanction", {"member": "a"}, {"b", "c"}, 1),
                                              # fewer than three present on the first rung: the Masters decide,
                                              # and the dormant Fellow y keeps the vote of that rung
                                              ("advancement", {"member": "x", "degree": 2}, {"a", "b", "c", "y"}, 2)):
            self.assertEqual(ledger.electorate(st, kind, subject, T0), (frozenset(electors), base), kind)


# ---------------------------------------------------------------- the unstoppable set ----

class TheUnstoppableSet(unittest.TestCase):
    def test_the_daily_cap_never_refuses_the_unstoppable_set(self):
        c = lodge(founders=SEVEN)
        f = freeze(c, "gus")
        c.state()
        h_entries = list(c.entries)
        for typ, actor, body, key_of in (("depart", "ada", {}, None), ("rekey", "ada", {"key": fake_key("ada-2"),
                                                                                      "proof": fake_key("ada-2")}, None),
                                         ("correction_object", "ada", {"seq": f}, None),
                                         ("rekey_recover", "ada", {"key": fake_key("ada-3"), "proof": fake_key("ada-3")},
                                          "ada-3"),
                                         ("ballot_open", "ada", {"id": "am", "kind": "amendment",
                                                                 "subject": {"path": "README.md", "new_sha256": "ab" * 32}},
                                          None),
                                         ("ballot_open", "ada", {"id": "rm", "kind": "custodian",
                                                                 "subject": {"remove": "warden"}}, None)):
            st = replay(h_entries, verifier=by_key)
            st.day, st.day_entries = iso(c.now)[:10], {"ada": ledger.ENTRIES_PER_DAY}
            e = {"seq": st.seq + 1, "prev": st.head, "time": iso(c.now), "type": typ, "actor": actor, "body": body,
                 "sig": fake_key(key_of or actor)}
            apply(st, e, by_key)
            self.assertEqual(st.day_entries["ada"], ledger.ENTRIES_PER_DAY, typ)
        st = replay(h_entries, verifier=by_key)
        st.day, st.day_entries = iso(c.now)[:10], {"ada": ledger.ENTRIES_PER_DAY}
        with self.assertRaisesRegex(Invalid, "already has 20 entries"):
            apply(st, {"seq": st.seq + 1, "prev": st.head, "time": iso(c.now), "type": "work", "actor": "ada",
                       "body": {"ref": URL}, "sig": fake_key("ada")}, by_key)

    def test_the_open_ballot_cap_and_the_reopen_wait_never_stop_an_amendment_or_a_removal(self):
        h = Hand(*(mk(x, founder=True) for x in ("hiram", "ada", "carol")), mk("bea", 2), mk("cal", 2), mk("dot", 2),
                 custodians={"warden": custodian(member="carol")})
        for who in ("bea", "cal", "dot"):
            h.add("ballot_open", "hiram", {"id": f"s-{who}", "kind": "sanction",
                                           "subject": {"member": who, "measure": "admonish"}})
        h.refused(self, "hiram has 3 ballots open", "ballot_open", "hiram",
                  {"id": "s-ada", "kind": "sanction", "subject": {"member": "ada", "measure": "admonish"}})
        h.add("ballot_open", "hiram", {"id": "rm", "kind": "custodian", "subject": {"remove": "warden"}})
        amend(h, "am", "hiram")
        self.assertEqual(vote(h, "am", {"hiram": "yes", "ada": "no", "carol": "no"}).result, "failed")
        amend(h, "am-again", "hiram")                                     # no 90-day wait for an amendment

    def test_a_halt_stops_neither_an_amendment_nor_a_recovery(self):
        c = lodge(founders=SEVEN)
        halt(c)
        c.add("ballot_open", "ada", {"id": "am", "kind": "amendment",
                                     "subject": {"path": "README.md", "new_sha256": "ab" * 32}})
        c.add("ballot_commit", "ada", {"id": "am", "commitment": commitment("am", "ada", "yes", salt_of("ada"))})
        ask(c, "carol")
        c.add("rekey_cosign", "dan", {"login": "carol"})
        st = c.state()
        self.assertEqual(st.pauses("am"), [])                             # its clock runs on wall time
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the ledger is halted")

    def test_an_unratified_main_is_an_alarm_and_a_plain_depart_still_passes_the_gate(self):
        unratified_main(self)

    def test_the_base_root_goes_with_the_tree_and_since(self):
        c = lodge(custodians=())
        led = write_ledger(tmpdir(self) / "led", c.entries)
        a = argparse.Namespace(ledger=led, tree=False, online=False, clock_since=None, root=None, pr_author=None,
                               since=None, json=True, base_root=Path("x"))
        with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)):
            self.assertEqual(verify.verify_report(a)["problems"], ["usage"])


def judge(test, c, root, base, since):
    """`verify --tree --root ROOT [--base-root BASE --since SEQ --pr-author carol]`, with Fast signatures."""
    led = write_ledger(tmpdir(test) / "led", c.entries)
    a = argparse.Namespace(ledger=led, tree=True, online=False, clock_since=None, root=root,
                           pr_author="carol" if since is not None else None, since=since, json=True, base_root=base)
    with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)), \
            mock.patch("openmasonry.identity.pr_problems", lambda *a, **kw: []):
        return verify.verify_report(a)


def unratified_main(test):
    """An amendment of the Constitution passed and nobody applied the text: after PRIOR_PIN_DAYS main is unlawful.
    Stuck before: every pull request of entries but those of amendment ballots was refused."""
    tmp = tmpdir(test)
    base, pr = copy_governed(tmp / "base"), copy_governed(tmp / "pr")
    c = lodge(custodians=())
    new = hashlib.sha256(b"a better constitution\n").hexdigest()
    c.add("ballot_open", "hiram", {"id": "am", "kind": "amendment",
                                   "subject": {"path": "CONSTITUTION.md", "new_sha256": new}})
    c.vote("am", {x: "yes" for x in FOUNDERS})
    c.now += 31 * DAY
    since = len(c.entries)
    c.add("depart", "carol", {})
    test.assertFalse(judge(test, c, pr, None, None)["valid"])            # the audit: an alarm
    r = judge(test, c, pr, base, since)
    test.assertTrue(r["valid"], r["message"])
    test.assertTrue(any("CONSTITUTION.md" in w and "an alarm, not a refusal" in w for w in r["warnings"]), r["warnings"])
    (pr / "CONSTITUTION.md").write_bytes(b"something nobody voted on\n")    # a change of the pull request itself
    r = judge(test, c, pr, base, since)
    test.assertFalse(r["valid"])
    test.assertTrue(r["message"].startswith("UNRATIFIED — CONSTITUTION.md"), r["message"])


# ---------------------------------------------------------------- amendment hygiene ----

class AmendmentHygiene(unittest.TestCase):
    def three(self) -> Hand:
        return Hand(mk("hiram", founder=True), mk("ada", founder=True), mk("carol", founder=True))

    def test_a_squatted_path_no_longer_holds_the_slot_and_a_stale_base_fails(self):
        h = self.three()
        amend(h, "bogus", "carol", new="cd" * 32)
        h.refused(self, "a ballot on this subject is already open", "ballot_open", "ada",
                  {"id": "x", "kind": "amendment", "subject": {"path": "readme.MD", "new_sha256": "cd" * 32}})
        amend(h, "real", "hiram", path="README.md", new="ab" * 32)        # stuck before: the path was held
        self.assertEqual(h.st.ballots["real"].frozen, {"base": ""})
        voters = ("hiram", "ada", "carol")
        for bid in ("bogus", "real"):
            for who in voters:
                h.add("ballot_commit", who, {"id": bid, "commitment": commitment(bid, who, "yes", salt_of(who))})
        h.now += timedelta(days=7.3)
        for bid in ("real", "bogus"):
            for who in voters:
                h.add("ballot_reveal", who, {"id": bid, "vote": "yes", "salt": salt_of(who)})
        h.add("ballot_close", "hiram", {"id": "real"})
        h.add("ballot_close", "carol", {"id": "bogus"})
        self.assertEqual((h.st.ballots["real"].result, h.st.ballots["bogus"].result), ("passed", "failed"))
        self.assertEqual(h.st.pins["README.md"], "ab" * 32)                # the base of `bogus` had changed

    def test_a_pin_an_amendment_added_can_be_removed_and_a_genesis_pin_never(self):
        h = self.three()
        everyone = {x: "yes" for x in ("hiram", "ada", "carol")}
        h.refused(self, "docs/x.md is not pinned: there is no pin to remove", "ballot_open", "hiram",
                  {"id": "x", "kind": "amendment", "subject": {"path": "docs/x.md", "new_sha256": ZERO}})
        amend(h, "add", "hiram", path="docs/x.md")
        vote(h, "add", everyone)
        amend(h, "drop", "hiram", path="docs/x.md", new=ZERO)
        self.assertEqual(vote(h, "drop", everyone).result, "passed")
        self.assertNotIn("docs/x.md", h.st.pins)
        self.assertNotIn("docs/x.md", h.st.prior_pins)
        h.refused(self, "canon/degrees.toml is pinned by the genesis, and a genesis pin is never removed",
                  "ballot_open", "hiram", {"id": "x", "kind": "amendment",
                                           "subject": {"path": "canon/degrees.toml", "new_sha256": ZERO}})

    def test_every_degree_table_ever_pinned_stays_archived(self):
        root = copy_governed(tmpdir(self) / "tree")
        c = lodge(custodians=())
        st = c.state()
        self.assertEqual(govern.check_tree(st, root, c.entries), [])
        self.assertEqual(govern.pinned_tables(st, c.entries), [canon_digest()])
        (root / f"canon/history/{canon_digest()}.toml").unlink()
        problems = govern.check_tree(st, root, c.entries)
        self.assertEqual(len(problems), 1)
        self.assertIn(f"canon/history/{canon_digest()}.toml is missing (every degree table the ledger ever pinned "
                      "stays archived)", problems[0])

    def test_the_archive_has_a_code_owner_and_the_judge_refuses_its_deletion(self):
        owners = (REPO / ".github/CODEOWNERS").read_text()
        self.assertRegex(owners, r"(?m)^/canon/history/\s+@openmasonry$")
        judge = (REPO / ".github/workflows/judge.yml").read_text()
        self.assertIn("-- canon/history | grep -v '^A'", judge)


# ---------------------------------------------------------------- upgrade safety ----

class UpgradeSafety(unittest.TestCase):
    def test_the_protocol_epoch_counts_the_passed_amendments_of_the_core(self):
        h = Hand(mk("hiram", founder=True))
        h.st.pins["@protocol"] = "aa" * 32
        self.assertEqual((h.st.epoch, h.st.document()["scalars"]["epoch"]), (0, 0))
        amend(h, "core", "hiram", path="@protocol", new="bb" * 32)
        vote(h, "core", {"hiram": "yes"})
        amend(h, "readme", "hiram")
        vote(h, "readme", {"hiram": "yes"})
        self.assertEqual((h.st.epoch, h.st.document()["scalars"]["epoch"]), (1, 1))

    def test_a_checkpoint_states_the_version_of_the_state_document(self):
        c = lodge(custodians=(), witnesses=("tyler",))
        c.add("work", "ada", {"ref": URL})
        st = c.state()
        body = {"upto_seq": st.seq, "head": st.head, "state_sha256": st.digest()}
        c.add("witness", "tyler", body)
        c.refused(self, "malformed witness entry: missing field 'state_version'")
        for other in (1, 3):                                         # version 1 is gone: only version 2 exists
            c.add("witness", "tyler", body | {"state_version": other})
            c.refused(self, "witness state_version must be 2")
        c.add("witness", "tyler", body | {"state_version": 2})
        self.assertEqual(c.state().history["checkpoints"][0], 1)

    def candidate(self, change=None) -> tuple[Path, Path]:
        tmp = tmpdir(self)
        c = Chain(tmp / "keys")
        (tmp / "keys").mkdir()
        c.add("genesis", "hiram", genesis_body(c, ["hiram"]))
        c.add("work", "hiram", {"ref": URL}, days=1)
        root = copy_governed(tmp / "candidate")
        if change is not None:
            path = root / "src/openmasonry/ledger.py"
            text = path.read_text(encoding="utf-8")
            old, new = change
            self.assertIn(old, text)
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return write_ledger(tmp / "led", c.entries), root

    def report(self, led, root):
        a = argparse.Namespace(ledger=led, tree=False, online=False, clock_since=None, root=None, pr_author=None,
                               since=None, json=True, candidate_root=root)
        return verify.verify_report(a)

    def test_a_candidate_core_must_replay_the_ledger_to_the_same_head_and_state(self):
        led, root = self.candidate()
        r = self.report(led, root)
        self.assertTrue(r["valid"], r["message"])
        led, root = self.candidate(("    return _plain(out)\n", '    return _plain(out | {"acts": st.acts + 1})\n'))
        r = self.report(led, root)
        self.assertFalse(r["valid"])
        self.assertTrue(r["message"].startswith("CANDIDATE DIFFERS — the candidate core reaches the state digest"))
        led, root = self.candidate(('_need(founders[0]["login"] == actor', '_need(False'))
        r = self.report(led, root)
        self.assertTrue(r["message"].startswith("CANDIDATE DIFFERS — the candidate core refuses the ledger"), r["message"])
        led, root = self.candidate(("STATE_VERSION = 2 ", "STATE_VERSION = 3 "))
        r = self.report(led, root)
        self.assertTrue(r["valid"], r["message"])
        self.assertIn("writes version 3 of the state document (this core: 2)", r["warnings"][0])

    def test_the_ci_runs_the_candidate_core_on_every_pull_request(self):
        tyler = (REPO / ".github/workflows/tyler.yml").read_text()
        self.assertIn("--candidate-root pr", tyler)


# ---------------------------------------------------------------- the judge is a convenience ----

class TheJudgeIsAConvenience(unittest.TestCase):
    def test_the_pinned_workflows_run_no_third_party_action_and_fix_no_python(self):
        for name in ("judge.yml", "tyler.yml"):
            text = (REPO / ".github/workflows" / name).read_text()
            self.assertNotIn("actions/checkout", text, name)
            self.assertNotIn("setup-python", text, name)
            self.assertNotIn("python-version", text, name)

    def test_entry_names_have_six_digits_at_least_and_more_past_a_million(self):
        self.assertEqual([ledger.entry_name(n) for n in (0, 999999, 1000000)],
                         ["0000/000000.json", "0999/999999.json", "1000/1000000.json"])
        names = ["1000/1000000.json", "0999/999999.json", "0000/000010.json"]
        self.assertEqual(sorted(names, key=ledger.entry_seq), ["0000/000010.json", "0999/999999.json", "1000/1000000.json"])

    def test_the_judge_admits_only_entry_files_in_their_shard(self):
        """The gate of judge.yml on added entry files, run as the workflow runs it (awk over the added paths)."""
        workflow = (REPO / ".github/workflows/judge.yml").read_text()
        m = re.search(r'junk=\$\(git diff --no-renames --name-only --diff-filter=A "\$range" -- ledger/entries \| awk \'\n(.*?)\' \|\| true\)',
                      workflow, re.S)
        self.assertIsNotNone(m, "the gate on entry names is gone")
        lawful = ["0000/000000.json", "0000/000999.json", "0001/001000.json", "0001/001001.json", "0999/999999.json",
                  "1000/1000000.json", "9999/9999999.json", "10000/10000000.json", "9007199254740/9007199254740991.json"]
        unlawful = ["000001.json", "1000000.json", "0000/001000.json", "0001/000999.json", "0000/0000001.json",
                    "0000/00001.json", "000/000001.json", "00000/000001.json", "1000/0999999.json", "9999/10000000.json",
                    "01000/1000000.json", "0000/000001.JSON", "0000/sub/000001.json", "0000/.gitkeep", ".gitkeep",
                    "0000/000001.json.bak", "90071992547409/90071992547409910.json", "0000/00001a.json"]
        for name in lawful + unlawful:
            self.assertEqual(ledger.entry_seq(name) is not None, name in lawful, name)       # the loader agrees
        paths = "".join(f"ledger/entries/{n}\n" for n in lawful + unlawful)
        out = subprocess.run(["awk", m.group(1)], input=paths, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.splitlines(), [f"ledger/entries/{n}" for n in unlawful])

    def test_manual_judging_is_documented(self):
        text = (REPO / "docs/operations/RECOVERY.md").read_text()
        self.assertIn("Manual judging", text)
        self.assertIn("verify --tree", text)


# ---------------------------------------------------------------- a lot that cannot be drawn ----

class ALotThatCannotBeDrawn(unittest.TestCase):
    def test_an_exam_whose_beacon_never_comes_lapses_without_penalty(self):
        h = Hand(mk("hiram", founder=True), mk("ada", founder=True), mk("cand", 1, t=T0 - 40 * DAY, activity=[T0]))
        rnd = open_exam(h, "cand", 2)
        h.now = drand_time(rnd) + 7 * DAY
        ex = h.st.exams[("cand", 2)]
        self.assertFalse(ex.draw_lapsed(h.now, h.st))
        h.now += SEC
        self.assertTrue(ex.draw_lapsed(h.now, h.st) and ex.timed_out(h.now, h.st) and not ex.failed(h.now, h.st))
        h.refused(self, "the lot of this exam was not drawn within 7 days of its beacon round", "exam_draw", "cand",
                  {"candidate": "cand", "degree": 2, "beacon": f"{rnd:064x}"})
        self.assertEqual(ledger.due_actions(h.st, h.now), [])
        open_exam(h, "cand", 2)                                         # at once
        self.assertGreater(h.st.exams[("cand", 2)].beacon_round, rnd)

    def test_a_council_call_whose_beacon_never_comes_lapses(self):
        h = Hand(mk("hiram", founder=True), mk("old", 32, t=T0 - 900 * DAY, activity=[T0]))
        rnd = drand_round(h.now) + BEACON_DELAY_ROUNDS
        h.add("council_call", "hiram", {"beacon_round": rnd})
        h.refused(self, "a council draw is already pending", "council_call", "hiram",
                  {"beacon_round": drand_round(h.now + DAY) + BEACON_DELAY_ROUNDS}, days=1)
        h.now = drand_time(rnd) + 7 * DAY + SEC
        h.refused(self, "the council call was not drawn within 7 days", "council_draw", "hiram", {"beacon": "ab" * 32})
        h.add("council_call", "hiram", {"beacon_round": drand_round(h.now) + BEACON_DELAY_ROUNDS})


# ---------------------------------------------------------------- whole populations ----

class Populations(unittest.TestCase):
    def test_the_sole_founder_departs(self):
        h = orphans()
        h.add("depart", "hiram", {})
        h.add("succession_claim", "dot", {})
        h.now += 90 * DAY
        admit(h, "eli", "bea")
        advance(h, "cal", 2)
        advance(h, "bea", 3)
        h.now += 61 * DAY                                                 # cal waits 60 days at the 2nd degree
        advance(h, "cal", 3)                                              # bea, now a Master, examines and elects
        self.assertEqual(h.st.masters(h.now), ["bea", "cal"])
        h.add("invite", "cal", {"login": "fay", "github_id": 78})

    def test_the_sole_founder_is_dormant(self):
        h = Hand(dormant("hiram", founder=True), mk("bea", 2), mk("cal", 1))
        h.add("succession_claim", "bea", {})
        h.now += 90 * DAY
        self.assertEqual(admit(h, "eli", "bea", voters=["bea"]).electors, frozenset({"bea", "hiram"}))
        b = advance(h, "cal", 2)
        self.assertEqual(b.electors, frozenset({"bea", "hiram"}))         # the dormant Master keeps the vote
        h.add("work", "hiram", {"ref": URL})                              # and may come back: nothing breaks
        self.assertEqual((h.st.masters(h.now), h.st.successors(h.now)), (["hiram"], []))

    def test_the_sole_founder_loses_the_key(self):
        c = lodge(custodians=(), founders=["hiram"])
        ask(c, "hiram")                                                   # nobody to co-sign: the notice starts at once
        st = c.state()
        self.assertEqual(st.recovery_notice_days(st.recoveries["hiram"], c.now), 45)
        c.add("rekey_recover_apply", "hiram", {}, days=45, key_of="hiram-new")
        self.assertEqual(c.state().members["hiram"].key, fake_key("hiram-new"))

    def test_two_masters_no_unilateral_expulsion_and_no_veto_by_omission(self):
        h = Hand(mk("hiram", founder=True), mk("ada", founder=True))
        h.refused(self, "never decided by a single elector", "ballot_open", "hiram",
                  {"id": "s", "kind": "sanction", "subject": {"member": "ada", "measure": "expel"}})
        h.add("invite", "hiram", {"login": "eli", "github_id": 77})
        h.add("petition", "eli", {"key": fake_key("eli"), "declaration_sha256": DECL})
        h.now += 30 * DAY
        h.add("ballot_open", "hiram", {"id": "adm", "kind": "admission", "subject": {"candidate": "eli"}})
        lapse(h, "adm", ["hiram"], "hiram")                               # ada neither sponsors nor votes
        h.add("ballot_open", "hiram", {"id": "adm-2", "kind": "admission", "subject": {"candidate": "eli"},
                                       "rerun": "adm"})
        self.assertEqual(vote(h, "adm-2", {"hiram": "yes"}).result, "passed")
        amend(h, "am", "hiram")
        lapse(h, "am", ["hiram"], "hiram")
        amend(h, "am-2", "hiram", rerun="am")
        self.assertEqual(vote(h, "am-2", {"hiram": "yes"}).result, "passed")

    def test_seven_masters_and_the_32nd_degree(self):
        others = [mk(f"m{i}") for i in range(6)]
        h = Hand(mk("cand", 31, t=T0 - 400 * DAY, activity=[T0]), *others)
        ex = examine(h, "cand", 32)
        self.assertTrue(ex.passed())
        h.add("ballot_open", "cand", {"id": "adv", "kind": "advancement", "subject": {"member": "cand", "degree": 32}})
        self.assertEqual(vote(h, "adv", {f"m{i}": "yes" for i in range(6)}, close_by="cand").result, "passed")

    def test_a_lapsed_custodian_the_fallback_and_a_recovery_without_one(self):
        c = lodge(custodians=("warden",), founders=["hiram", "ada"])
        c.now = T0 + 200 * DAY
        ask(c)
        c.add("rekey_cosign", "hiram", {"login": "ada"})
        seq = c.add("custodian_claim", "hiram", claim_body())["seq"]
        c.add("custodian_claim_apply", "hiram", {"seq": seq}, days=30)
        c.add("rekey_recover_apply", "ada", {}, days=15, key_of="ada-new")
        st = c.state()
        self.assertEqual((st.custodians_live(c.now), st.members["ada"].key), (["keeper"], fake_key("ada-new")))

    def test_an_unapplied_amendment_and_a_plain_depart(self):
        unratified_main(self)


if __name__ == "__main__":
    unittest.main()
