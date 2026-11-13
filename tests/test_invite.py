"""Invite-first admission: no outsider writes to the ledger.

A Master Builder signs `invite {login, github_id}` and thereby becomes the candidate's first sponsor. A
`petition` is valid only under a live invitation for exactly that login. The judge's gate binds both to
the numeric GitHub user id. The network (`identity.fetch_github_user`) is always replaced here.
"""
from __future__ import annotations

import argparse
import copy
import json
import unittest
from datetime import timedelta
from unittest import mock

from openmasonry import identity, ledger
from openmasonry.guide import next_steps
from openmasonry.ledger import INVITE_EXPIRY_DAYS, Invalid, apply, iso
from tests.test_guide import OmHarness
from tests.test_protocol import DECL, T0, gid, invite, petition, salt_of, witness_subject, entry_file, entry_path
from tests.test_protocol import founded as real_founded
from tests.test_strict import DAY, SEC, Fast, by_key, fake_key, founded, hand_state, mk, tmpdir


def plea(c, who, days=0.0, key_of=None):
    """A bare `petition` entry (whether an invitation exists is the test's business)."""
    return c.add("petition", who, {"key": c.key(key_of or who), "declaration_sha256": DECL}, days=days, key_of=key_of)


def admit(c, who, by="hiram", second="ada"):
    petition(c, who, by)
    if second:
        c.add("vouch", second, {"candidate": who})
    c.add("ballot_open", by, {"id": f"adm-{who}", "kind": "admission", "subject": {"candidate": who}})
    c.vote(f"adm-{who}", {f: "yes" for f in ("hiram", "ada", "carol") if f in c.state().members})


# ---------------------------------------------------------------- the invitation ----

class Invitation(unittest.TestCase):
    def test_an_outsider_cannot_petition_without_an_invitation(self):
        c = founded()
        plea(c, "alice")
        c.refused(self, "entry 1: no live invitation for 'alice'")

    def test_the_invitation_is_recorded_and_the_inviter_is_the_first_sponsor(self):
        c = founded()
        invite(c, "alice")
        st = c.state()
        self.assertEqual(st.invitations, {"alice": {"by": "hiram", "github_id": gid("alice"), "time": T0}})
        self.assertTrue(st.invited("alice", T0))
        self.assertEqual(st.petitions, {})
        plea(c, "alice", days=3)
        st = c.state()
        self.assertEqual(st.invitations, {})                 # converted, not kept beside the petition
        self.assertEqual(st.petitions["alice"], {"key": c.key("alice"), "vouches": ["hiram"],
                                                 "time": T0 + 3 * DAY, "github_id": gid("alice")})

    def test_the_inviter_cannot_vouch_for_their_own_candidate(self):
        c = founded()
        petition(c, "alice")
        c.add("vouch", "hiram", {"candidate": "alice"})
        c.refused(self, "already a sponsor of this petition")
        c.add("vouch", "ada", {"candidate": "alice"})
        self.assertEqual(c.state().petitions["alice"]["vouches"], ["hiram", "ada"])

    def test_members_carry_the_github_id(self):
        c = founded()
        self.assertEqual({m.login: m.github_id for m in c.state().members.values()},
                         {f: gid(f) for f in ("hiram", "ada", "carol")})
        admit(c, "alice")
        m = c.state().members["alice"]
        self.assertEqual((m.github_id, m.sponsors, m.degree), (gid("alice"), ("hiram", "ada"), 1))

    def test_only_an_active_master_builder_may_invite(self):
        c = founded()
        admit(c, "alice")                                    # an Apprentice
        invite(c, "bob", by="alice")
        c.refused(self, "only Master Builders may invite")
        invite(c, "bob", by="stranger")
        c.refused(self, "stranger is not an active member")
        c.add("depart", "carol", {})
        invite(c, "bob", by="carol")
        c.refused(self, "carol is not an active member")

    def test_a_master_cannot_invite_themselves(self):
        c = founded()
        invite(c, "hiram", by="hiram")
        c.refused(self, "a Master Builder cannot invite themselves")
        invite(c, "HIRAM", by="hiram")
        c.refused(self, "a Master Builder cannot invite themselves")

    def test_the_body_is_exact(self):
        c = founded()
        for body, pattern in (({"login": "alice"}, "malformed invite entry: missing field 'github_id'"),
                              ({"github_id": 7}, "malformed invite entry: missing field 'login'"),
                              ({"login": "alice", "github_id": 7, "note": "x"}, "unknown field 'note'"),
                              ({"login": "alice", "github_id": "7"}, "field 'github_id' must be an integer"),
                              ({"login": "alice", "github_id": True}, "field 'github_id' must be an integer"),
                              ({"login": ["alice"], "github_id": 7}, "field 'login' must be a string"),
                              ({"login": "alice", "github_id": 0}, "github_id must be a positive integer"),
                              ({"login": "alice", "github_id": -7}, "github_id must be a positive integer"),
                              ({"login": "-alice", "github_id": 7}, "login must be a valid GitHub login"),
                              ({"login": "a" * 40, "github_id": 7}, "login must be a valid GitHub login")):
            c.add("invite", "hiram", body)
            c.refused(self, pattern)
        c.add("invite", "hiram", {"login": "alice", "github_id": 1})
        self.assertEqual(c.state().invitations["alice"]["github_id"], 1)

    def test_a_sponsor_under_a_ban_cannot_invite(self):
        c = founded()
        st = c.state()
        st.members["hiram"].sponsor_ban_until = T0 + 10 * DAY
        e = invite(Fast_after(c, 10 * DAY - SEC), "alice")
        with self.assertRaisesRegex(Invalid, "sponsorship suspended"):
            apply(copy.deepcopy(st), e, verifier=by_key)
        e = invite(Fast_after(c, 10 * DAY), "alice")
        apply(st, e, verifier=by_key)                        # the ban is served at its last instant
        self.assertTrue(st.invited("alice", st.time))

    def test_a_refused_invitation_changes_nothing(self):
        c = founded()
        st = c.state()
        before = copy.deepcopy(st)
        e = c.add("invite", "hiram", {"login": "ada", "github_id": 5})
        with self.assertRaises(Invalid):
            apply(st, e, verifier=by_key)
        self.assertEqual(st, before)


def Fast_after(c: Fast, delta: timedelta) -> Fast:
    """A copy of the chain whose clock has advanced by `delta` (the next entry is stamped then)."""
    d = Fast()
    d.keys, d.entries, d.now = c.keys, list(c.entries), c.now + delta
    return d


class Lapse(unittest.TestCase):
    def test_an_invitation_lasts_thirty_days_to_the_second(self):
        self.assertEqual(INVITE_EXPIRY_DAYS, 30)
        c = founded()
        invite(c, "alice")
        d = Fast_after(c, 30 * DAY)
        plea(d, "alice")
        self.assertIn("alice", d.state().petitions)
        d = Fast_after(c, 30 * DAY + SEC)
        plea(d, "alice")
        d.refused(self, "no live invitation for 'alice'")

    def test_a_lapsed_invitation_frees_the_name_and_is_replaced(self):
        c = founded()
        invite(c, "alice")
        st = c.state()
        self.assertFalse(st.invited("alice", T0 + 30 * DAY + SEC))
        self.assertIn("alice", st.invitations)               # lapse is a matter of time, not of an entry
        invite(c, "Alice", by="ada", days=31)                # another spelling, another Master
        st = c.state()
        self.assertEqual(list(st.invitations), ["Alice"])
        self.assertEqual(st.invitations["Alice"]["by"], "ada")
        plea(c, "alice")
        c.refused(self, "login 'alice' collides with the invitation of 'Alice'")
        plea(c, "Alice")
        self.assertEqual(c.state().petitions["Alice"]["vouches"], ["ada"])


class Budget(unittest.TestCase):
    def test_live_invitations_count_against_the_budget(self):
        c = founded()
        for i in range(4):
            invite(c, f"cand{i}")
        self.assertEqual(ledger.sponsorships(c.state(), "hiram", c.now), 4)
        invite(c, "cand4")
        c.refused(self, "sponsorship budget exhausted")
        petition(c, "other", by="ada")
        c.add("vouch", "hiram", {"candidate": "other"})      # a vouch draws on the same budget
        c.refused(self, "sponsorship budget exhausted")

    def test_a_petition_under_the_invitation_is_counted_once(self):
        c = founded()
        for i in range(4):
            invite(c, f"cand{i}")
        plea(c, "cand0")
        self.assertEqual(ledger.sponsorships(c.state(), "hiram", c.now), 4)
        invite(c, "cand4")
        c.refused(self, "sponsorship budget exhausted")

    def test_a_lapsed_invitation_returns_its_place_ninety_days_after_it_lapsed(self):
        c = founded()
        for i in range(4):
            invite(c, f"cand{i}")
        plea(c, "cand0", days=1)
        st = c.state()
        self.assertEqual(ledger.sponsorships(st, "hiram", T0 + 30 * DAY + SEC), 4)    # lapsed, and still counted
        self.assertEqual(ledger.sponsorships(st, "hiram", T0 + 120 * DAY), 4)
        self.assertEqual(ledger.sponsorships(st, "hiram", T0 + 120 * DAY + SEC), 1)   # the petition remains
        invite(c, "cand4", days=30)
        c.refused(self, "sponsorship budget exhausted")
        invite(c, "cand4", days=90)
        self.assertTrue(c.state().invited("cand4", c.now))


class Names(unittest.TestCase):
    """One name, one role: an invitation holds its login against every other use, up to case."""

    def test_a_member_a_witness_or_a_proposed_witness_cannot_be_invited(self):
        c = founded(witnesses=("tyler",))
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness", "subject": witness_subject(c, "node2")})
        for login, pattern in (("ada", "ada is already a member"),
                               ("Ada", "login 'Ada' collides with 'ada'"),
                               ("Tyler", "login 'Tyler' collides with the witness 'tyler'"),
                               ("NODE2", "login 'NODE2' is the name proposed by an open witness ballot")):
            invite(c, login)
            c.refused(self, pattern)

    def test_one_live_invitation_per_login(self):
        c = founded()
        invite(c, "alice")
        invite(c, "alice", by="ada")
        c.refused(self, "alice already has a live invitation")
        invite(c, "ALICE", by="ada")
        c.refused(self, "login 'ALICE' collides with the invitation of 'alice'")

    def test_a_login_with_a_pending_petition_cannot_be_invited(self):
        c = founded()
        petition(c, "alice")
        invite(c, "alice", by="ada")
        c.refused(self, "alice already has a pending petition")
        invite(c, "Alice", by="ada")
        c.refused(self, "login 'Alice' collides with the pending petition of 'alice'")
        c.add("vouch", "ada", {"candidate": "alice"})
        c.add("ballot_open", "ada", {"id": "adm", "kind": "admission", "subject": {"candidate": "alice"}})
        invite(c, "alice", by="carol", days=200)             # lapsed by time, still held by its open ballot
        c.refused(self, "alice already has a pending petition")

    def test_a_new_witness_cannot_take_an_invited_name(self):
        c = founded()
        invite(c, "node2")
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness", "subject": witness_subject(c, "Node2", "n2")})
        c.refused(self, "a new witness name cannot equal")

    def test_a_petition_uses_exactly_the_invited_login(self):
        c = founded()
        invite(c, "Mallory")
        plea(c, "mallory")
        c.refused(self, "login 'mallory' collides with the invitation of 'Mallory'")
        plea(c, "Mallory")
        self.assertIn("Mallory", c.state().petitions)


class Returning(unittest.TestCase):
    def member_gone(self, measure=None):
        c = founded()
        admit(c, "jo")
        if measure is None:
            c.add("depart", "jo", {})
        else:
            c.add("ballot_open", "hiram", {"id": "x", "kind": "sanction", "subject": {"member": "jo", "measure": measure}})
            c.vote("x", {f: "yes" for f in ("hiram", "ada", "carol")})
        return c, c.now

    def test_a_departed_member_needs_a_new_invitation_after_ninety_days(self):
        c, left = self.member_gone()
        plea(c, "jo", days=100)
        c.refused(self, "no live invitation for 'jo'")
        c.now = left
        d = Fast_after(c, 90 * DAY - SEC)
        invite(d, "jo")
        d.refused(self, "jo is already a member .a departed member, or one whose admission was undone, may be invited again once 90 days have passed")
        d = Fast_after(c, 90 * DAY)
        invite(d, "jo")
        plea(d, "jo")
        self.assertEqual(d.state().petitions["jo"]["vouches"], ["hiram"])

    def test_an_expelled_member_needs_a_new_invitation_after_a_year(self):
        c, out = self.member_gone("expel")
        c.now = out
        d = Fast_after(c, 365 * DAY - SEC)
        invite(d, "jo")
        d.refused(self, "an expelled member once 365 have")
        d = Fast_after(c, 365 * DAY)
        invite(d, "jo")
        self.assertTrue(d.state().invited("jo", d.now))

    def test_an_expelled_member_reinstated_after_the_invitation_cannot_petition(self):
        c, out = self.member_gone("expel")
        c.now = out + 365 * DAY
        invite(c, "jo")
        c.add("ballot_open", "ada", {"id": "back", "kind": "sanction", "subject": {"member": "jo", "measure": "reinstate"}})
        # After a silent year ada and carol are dormant: they keep the vote, and hiram, who has just invited, is the
        # whole quorum.
        b = c.state().ballots["back"]
        self.assertEqual((b.electors, b.quorum_base()), (frozenset({"hiram", "ada", "carol"}), 1))
        c.add("ballot_commit", "hiram", {"id": "back", "commitment": ledger.commitment("back", "hiram", "yes", salt_of("hiram"))})
        c.now += 7 * DAY + ledger.REVEAL_GAP
        c.add("ballot_reveal", "hiram", {"id": "back", "vote": "yes", "salt": salt_of("hiram")})
        c.add("ballot_close", "ada", {"id": "back"}, days=3.1)   # the dormant electors may still reveal: the window runs out
        self.assertEqual(c.state().members["jo"].status, "active")
        self.assertTrue(c.state().invited("jo", c.now))
        plea(c, "jo")
        c.refused(self, "already a member")

    def test_the_waiting_period_is_still_enforced_at_the_petition(self):
        left = T0 + 400 * DAY
        st = hand_state(mk("hiram"), mk("jo", 1, status="departed", status_since=left), time=left, seq=5)
        st.invitations["jo"] = {"by": "hiram", "github_id": 9, "time": left + 80 * DAY}     # a state replay cannot reach
        e = {"seq": 6, "prev": st.head, "time": iso(left + 85 * DAY), "type": "petition", "actor": "jo",
             "body": {"key": fake_key("jo2"), "declaration_sha256": DECL}, "sig": fake_key("jo2")}
        with self.assertRaisesRegex(Invalid, "already a member"):
            apply(st, e, verifier=by_key)


class Sponsors(unittest.TestCase):
    def test_with_one_master_the_inviter_alone_suffices(self):
        c = Fast()
        from tests.test_protocol import genesis_body
        c.add("genesis", "hiram", genesis_body(c, ["hiram"]))
        petition(c, "alice")
        c.add("ballot_open", "hiram", {"id": "adm", "kind": "admission", "subject": {"candidate": "alice"}})
        c.vote("adm", {"hiram": "yes"})
        m = c.state().members["alice"]
        self.assertEqual((m.sponsors, m.github_id), (("hiram",), gid("alice")))

    def test_with_more_masters_a_second_sponsor_is_still_needed(self):
        c = founded()
        petition(c, "alice")
        c.add("ballot_open", "hiram", {"id": "adm", "kind": "admission", "subject": {"candidate": "alice"}})
        c.refused(self, "candidate lacks sponsors")
        c.add("vouch", "ada", {"candidate": "alice"})
        c.add("ballot_open", "hiram", {"id": "adm", "kind": "admission", "subject": {"candidate": "alice"}})
        self.assertEqual(c.state().ballots["adm"].frozen,
                         {"key": c.key("alice"), "vouches": ["hiram", "ada"], "github_id": gid("alice")})


class Genesis(unittest.TestCase):
    def test_a_founder_is_exactly_login_key_and_github_id(self):
        from tests.test_protocol import genesis_body
        for founder, pattern in (({"login": "hiram", "key": fake_key("hiram")}, "founder: missing field 'github_id'"),
                                 ({"login": "hiram", "key": fake_key("hiram"), "github_id": "1"},
                                  "founder: field 'github_id' must be an integer"),
                                 ({"login": "hiram", "key": fake_key("hiram"), "github_id": 0},
                                  "founder github_id must be a positive integer"),
                                 ({"login": "hiram", "key": fake_key("hiram"), "github_id": 1, "id": 1},
                                  "founder: unknown field 'id'")):
            c = Fast()
            c.add("genesis", "hiram", genesis_body(c, ["hiram"]) | {"founders": [founder]})
            c.refused(self, pattern)


# ---------------------------------------------------------------- the gate ----

class Gate(unittest.TestCase):
    """identity.pr_problems: the invited login and the petitioner are bound to a numeric GitHub user id."""

    def chain(self):
        c = founded()
        invite(c, "alice")
        plea(c, "alice")
        return c

    def problems(self, c, since, author, users=None, author_id="event", fail=False, keys=None):
        """The author's numeric id comes with the pull request event (`gid(author)`), unless the test gives
        another one, or None to have it looked up."""
        def user(login):
            if fail:
                raise OSError("network unreachable")
            return (users or {})[login.lower()]
        keys = keys or (lambda login: [c.key(login) + " laptop"])
        return identity.pr_problems(c.entries, since, author, fetch=keys, fetch_user=user,
                                    author_id=gid(author) if author_id == "event" else author_id)

    def test_the_invited_login_must_own_the_github_id(self):
        c = self.chain()
        ok = {"alice": {"id": gid("alice"), "login": "Alice"}}
        self.assertEqual(self.problems(Cut(c, 2), 1, "hiram", ok), [])
        bad = self.problems(Cut(c, 2), 1, "hiram", {"alice": {"id": 1, "login": "alice"}})
        self.assertEqual(len(bad), 1)
        self.assertIn(f"entry 1: the GitHub account alice has id 1, not {gid('alice')}", bad[0])
        other = self.problems(Cut(c, 2), 1, "hiram", {"alice": {"id": gid("alice"), "login": "someone-else"}})
        self.assertIn("answered for another login", other[0])

    def test_a_failed_lookup_of_the_invited_login_fails_closed(self):
        bad = self.problems(Cut(self.chain(), 2), 1, "hiram", fail=True)
        self.assertEqual(len(bad), 1)
        self.assertIn("https://api.github.com/users/alice", bad[0])
        self.assertIn("fail closed", bad[0])
        missing = self.problems(Cut(self.chain(), 2), 1, "hiram", {"alice": {"login": "alice"}})
        self.assertIn("fail closed", missing[0])

    def test_the_petitioner_must_be_the_invited_github_account(self):
        c = self.chain()
        self.assertEqual(self.problems(c, 2, "alice", author_id=gid("alice")), [])
        bad = self.problems(c, 2, "alice", author_id=gid("alice") + 1)
        self.assertEqual(len(bad), 1)
        self.assertIn(f"entry 2: the invitation is for the GitHub account with id {gid('alice')}", bad[0])

    def test_without_the_id_of_the_event_the_author_is_looked_up(self):
        c = self.chain()
        self.assertEqual(self.problems(c, 2, "alice", {"alice": {"id": gid("alice"), "login": "alice"}}, author_id=None), [])
        bad = self.problems(c, 2, "alice", {"alice": {"id": 3, "login": "alice"}}, author_id=None)
        self.assertIn("the pull request is by the account with id 3", bad[0])
        closed = self.problems(c, 2, "alice", fail=True, author_id=None)
        self.assertIn("fail closed", closed[0])

    def test_the_account_is_its_numeric_id_not_its_login(self):
        c = self.chain()
        bad = self.problems(c, 2, "mallory")                 # another account, whatever it is called
        self.assertIn(f"the invitation is for the GitHub account with id {gid('alice')}", bad[0])
        # The invited account, renamed since the invitation: the same person, and the key is listed under the new login.
        renamed = self.problems(c, 2, "alice-new-name", author_id=gid("alice"),
                                keys=lambda login: [c.key("alice")] if login == "alice-new-name" else [])
        self.assertEqual(renamed, [])
        unlisted = identity.pr_problems(c.entries, 2, "alice", fetch=lambda login: [], author_id=gid("alice"))
        self.assertIn("the petition key is not listed", unlisted[0])

    def test_the_founders_of_a_genesis_must_own_their_github_ids(self):
        c = founded()
        users = {f: {"id": gid(f), "login": f} for f in ("hiram", "ada", "carol")}
        self.assertEqual(self.problems(c, 0, "hiram", users), [])
        users["ada"] = {"id": 5, "login": "ada"}
        bad = self.problems(c, 0, "hiram", users)
        self.assertEqual(len(bad), 1)
        self.assertIn(f"entry 0: the GitHub account ada has id 5, not {gid('ada')}", bad[0])

    def test_entries_before_the_pull_request_are_not_looked_up(self):
        c = self.chain()
        c.add("work", "ada", {"ref": "https://example.org/a"})
        self.assertEqual(self.problems(c, 3, "ada", fail=True), [])

    def test_the_verifier_takes_the_author_id_of_the_event(self):
        from openmasonry.verify import parser, verify_report
        c = real_founded(tmpdir(self))
        invite(c, "alice")
        plea(c, "alice")
        led = tmpdir(self) / "led"
        led.mkdir()
        for e in c.entries:
            entry_file(led, e["seq"]).write_text(json.dumps(e))
        args = ["--ledger", str(led), "--pr-author", "alice", "--since", "2", "--json"]
        with mock.patch.object(identity, "fetch_github_keys", side_effect=lambda login: [c.key(login)]), \
                mock.patch.object(identity, "fetch_github_user", side_effect=AssertionError("no lookup")):
            good = verify_report(parser().parse_args([*args, "--pr-author-id", str(gid("alice"))]))
            bad = verify_report(parser().parse_args([*args, "--pr-author-id", "1"]))
        self.assertTrue(good["valid"], good["message"])
        self.assertFalse(bad["valid"])
        self.assertIn("WRONG AUTHOR OR KEY", bad["message"])
        self.assertIn(f"account with id {gid('alice')}", bad["message"])
        alone = verify_report(argparse.Namespace(ledger=led, tree=False, online=False, clock_since=None, root=None,
                                                 pr_author=None, since=None, pr_author_id=7, json=True))
        self.assertIn("USAGE", alone["message"])

    def test_the_lookup_is_one_small_function(self):
        calls = []

        class Reply:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, n):
                return b'{"login": "Alice", "id": 42, "name": "ignored"}'

        def opener(req, timeout):
            calls.append((req.full_url, dict(req.header_items())))
            return Reply()
        with mock.patch.object(identity.urllib.request, "urlopen", side_effect=opener), \
                mock.patch.dict(identity.os.environ, {"GITHUB_TOKEN": ""}):
            self.assertEqual(identity.fetch_github_user("alice"), {"id": 42, "login": "Alice"})
        self.assertEqual(calls[0][0], "https://api.github.com/users/alice")
        self.assertNotIn("Authorization", calls[0][1])


def Cut(c: Fast, n: int) -> Fast:
    """The first `n` entries of the chain."""
    d = Fast()
    d.keys, d.entries, d.now = c.keys, c.entries[:n], c.now
    return d


# ---------------------------------------------------------------- the Guide and the commands ----

def actions(steps):
    return [s.action for s in steps]


class GuideSteps(unittest.TestCase):
    def test_an_outsider_is_told_to_apply_in_a_public_issue(self):
        st = founded().state()
        steps = next_steps(st, "nobody", st.time)
        self.assertEqual(actions(steps), ["apply"])
        self.assertEqual((steps[0].argv, steps[0].public), ([], False))
        self.assertIn("public issue", steps[0].why)

    def test_an_invited_person_is_told_to_join_before_the_invitation_lapses(self):
        c = founded()
        invite(c, "alice")
        st = c.state()
        steps = next_steps(st, "alice", st.time + 2 * DAY)
        self.assertEqual(actions(steps), ["join"])
        self.assertEqual(steps[0].argv, ["bin/om", "join"])
        self.assertEqual(steps[0].due_by, iso(T0 + 30 * DAY))
        self.assertIn("hiram invited you", steps[0].why)
        self.assertEqual(actions(next_steps(st, "alice", T0 + 30 * DAY + SEC)), ["apply"])

    def test_a_candidate_with_the_inviter_only_looks_for_a_second_sponsor(self):
        c = founded()
        petition(c, "alice")
        st = c.state()
        self.assertEqual(actions(next_steps(st, "alice", st.time)), ["find_sponsors"])
        self.assertIn("1 of 2", next_steps(st, "alice", st.time)[0].why)
        self.assertIn("sponsor", actions(next_steps(st, "ada", st.time)))
        self.assertNotIn("sponsor", actions(next_steps(st, "hiram", st.time)))

    def test_a_master_is_never_told_to_invite(self):
        c = founded()
        st = c.state()
        for at in (st.time, st.time + 40 * DAY):
            self.assertNotIn("invite", actions(next_steps(st, "hiram", at)))
            self.assertFalse(any("invite" in " ".join(s.argv) for s in next_steps(st, "hiram", at)))

    def test_a_departed_member_waits_then_applies(self):
        c = founded()
        c.add("depart", "carol", {})
        st = c.state()
        self.assertEqual(actions(next_steps(st, "carol", st.time + DAY)), ["wait"])
        self.assertEqual(actions(next_steps(st, "carol", st.time + 91 * DAY)), ["apply"])


class Commands(OmHarness):
    def test_om_invite_drafts_the_invitation_and_the_dialog_says_what_it_means(self):
        from openmasonry.actions import describe
        d = self.draft("invite", "alice", "--github-id", "4242", day=1)
        self.assertEqual((d["entry"]["type"], d["entry"]["body"]), ("invite", {"login": "alice", "github_id": 4242}))
        text = describe(None, d["entry"])
        self.assertIn("INVITE alice (GitHub account id 4242)", text)
        self.assertIn("first sponsor", text)
        self.assertIn("identity, adulthood and good faith", text)
        self.approve(d["digest"], day=1)
        signed = json.loads(entry_path(self.led, 1).read_text())
        self.assertEqual(signed["body"], {"login": "alice", "github_id": 4242})

    def test_om_invite_refuses_what_the_ledger_would(self):
        r = self.run_om("invite", "ada", "--github-id", "5", "--ledger", str(self.led), "--time", self.T(1), env=self.env())
        self.assertEqual(r.returncode, 1)
        self.assertIn("WOULD BE REFUSED", r.stdout)
        self.assertIn("already a member", r.stdout)

    def test_om_join_without_an_invitation_explains_how_to_apply(self):
        self.c.key("alice")
        r = self.run_om("join", "--ledger", str(self.led), "--time", self.T(1), env=self.env("alice"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no live invitation for alice", r.stdout)
        self.assertIn("public issue", r.stdout)
        self.assertIn("issues/new", r.stdout)
        self.assertFalse((self.tmp / "home-alice" / "pending").exists())

    def test_om_join_under_an_invitation_drafts_the_petition(self):
        self.approve(self.draft("invite", "Alice", "--github-id", "4242", day=1)["digest"], day=1)
        self.c.key("alice")
        d = self.draft("join", who="alice", day=2)
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"]), ("petition", "Alice"))     # the invited spelling
        r = self.run_om("join", "--ledger", str(self.led), "--time", self.T(40), env=self.env("alice"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no live invitation", r.stdout)

    def test_om_me_shows_an_outsider_how_to_apply_and_an_invited_person_the_deadline(self):
        self.c.key("alice")
        me = json.loads(self.run_om("me", "--json", "--ledger", str(self.led), "--time", self.T(1),
                                    env=self.env("alice")).stdout)
        self.assertEqual((me["schema"], me["member"], me["invitation"]), ("om.me/2", None, None))
        self.assertEqual([s["action"] for s in me["steps"]], ["apply"])
        self.approve(self.draft("invite", "alice", "--github-id", "4242", day=1)["digest"], day=1)
        me = json.loads(self.run_om("me", "--json", "--ledger", str(self.led), "--time", self.T(2),
                                    env=self.env("alice")).stdout)
        self.assertEqual(me["invitation"], {"by": "hiram", "github_id": 4242, "expires_at": self.T(31)})
        self.assertEqual([(s["action"], s["due_by"]) for s in me["steps"]], [("join", self.T(31))])
        text = self.run_om("me", "--ledger", str(self.led), "--time", self.T(2), env=self.env("alice")).stdout
        self.assertIn("invited by hiram", text)

    def test_the_json_contracts_expose_the_github_id(self):
        self.approve(self.draft("invite", "alice", "--github-id", "4242", day=1)["digest"], day=1)
        me = json.loads(self.run_om("me", "--json", "--ledger", str(self.led), "--time", self.T(1), env=self.env()).stdout)
        self.assertEqual(me["member"]["github_id"], gid("hiram"))
        self.assertNotIn("invite", [s["action"] for s in me["steps"]])
        state = json.loads(self.run_om("state", "--json", "--ledger", str(self.led), env=self.env()).stdout)
        self.assertEqual(state["schema"], "om.state/2")
        self.assertEqual({m["login"]: m["github_id"] for m in state["members"]}, {f: gid(f) for f in ("hiram", "ada", "carol")})
        self.assertEqual([(i["login"], i["by"], i["github_id"]) for i in state["invitations"]], [("alice", "hiram", 4242)])


if __name__ == "__main__":
    unittest.main()
