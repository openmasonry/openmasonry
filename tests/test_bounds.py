"""Bounds and guards of SPEC sections 5.4, 6 and 9, each tested against the abuse it stops.

Each class holds one guard: nobody writes without bound, a ballot slot cannot
be held by opening on it again and again, a key is registered only by whoever holds it, a person is a GitHub
account and an account is its numeric id, a correction never changes who decides a ballot, and a custodian
never reads a vote before pausing or ending a ballot. Every test uses `Fast` (tests.test_strict): the
"signature" of an entry is the public key that signed it. Nothing touches the network.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from openmasonry import actions, canon, crypto, govern, identity, ledger, verify
from openmasonry.ledger import (DAY, REVEAL_GAP, SECOND, Ballot, Invalid, Member, State, apply, commitment, drand_round,
                                founder_message, iso, replay, witness_message)
from tests.test_guide import OmHarness
from tests.test_custodian import (REASON, REASON_TEXT, SEVEN, advance, apply_, commit, correct, cosign, fork, freeze,
                                  lodge, objection, open_ballot, quarry, reveal, sanction, undo, void, withdraw)
from tests.test_protocol import (DECL, FOUNDERS, T0, checkpoint, copy_governed, genesis_body, gid, initiate, invite, petition,
                                 salt_of, witness_subject)
from tests.test_recovery import ask, co, finish, stop
from tests.test_strict import Fast, absorbed, by_key, fake_key, founded, hand_state, mk, tmpdir, write_ledger

HOUR = timedelta(hours=1)
URL = "https://example.org/work"


def amendment(c, bid, by="ada", path="docs/x.md", days=0.0, **windows):
    return open_ballot(c, bid, by, "amendment", {"path": path, "new_sha256": "ab" * 32}, **windows) if not days else \
        c.add("ballot_open", by, {"id": bid, "kind": "amendment", "subject": {"path": path, "new_sha256": "ab" * 32}}
              | windows, days=days)


def run_to_end(c, bid, votes=None, closer=None):
    """Commit and reveal `votes`, then close the ballot one second after its reveal window."""
    votes = votes or {}
    for who, vote in votes.items():
        commit(c, bid, who, vote)
    b = c.state().ballots[bid]
    c.now = max(c.now, b.commit_until + REVEAL_GAP)
    for who, vote in votes.items():
        reveal(c, bid, who, vote)
    c.now = max(c.now, b.reveal_until + SECOND)
    c.add("ballot_close", closer or "hiram", {"id": bid})
    return c.state().ballots[bid]


# ---------------------------------------------------------------- nobody writes without bound ----

class RateLimits(unittest.TestCase):
    def test_an_actor_has_twenty_entries_in_a_utc_day(self):
        c = founded()
        c.add("work", "ada", {"ref": URL}, days=1)
        st = c.state()
        self.assertEqual((st.day, st.day_entries), ("2027-01-02", {"ada": 1}))
        st.day_entries["ada"] = ledger.ENTRIES_PER_DAY
        nxt = lambda typ, body: {"seq": st.seq + 1, "prev": st.head, "time": iso(c.now + HOUR), "type": typ, "actor": "ada",
                                 "body": body, "sig": c.key("ada")}
        with self.assertRaisesRegex(Invalid, "ada already has 20 entries dated 2027-01-02 .at most 20 entries per actor "
                                             "per UTC day"):
            apply(copy.deepcopy(st), nxt("invite", {"login": "zed", "github_id": 9}), verifier=by_key)
        amend = copy.deepcopy(st)                                # an amendment is in the unstoppable set
        apply(amend, nxt("ballot_open", {"id": "am", "kind": "amendment",
                                         "subject": {"path": "docs/x.md", "new_sha256": "ab" * 32}}), verifier=by_key)
        self.assertEqual(amend.day_entries["ada"], 20)
        left = copy.deepcopy(st)
        apply(left, nxt("depart", {}), verifier=by_key)          # Landmark VII: leaving is never counted
        self.assertEqual((left.members["ada"].status, left.day_entries["ada"]), ("departed", 20))
        later = copy.deepcopy(st)                                # the next UTC day starts a new count
        e = nxt("invite", {"login": "zed", "github_id": 9})
        apply(later, e | {"time": iso(c.now + DAY)}, verifier=by_key)
        self.assertEqual((later.day, later.day_entries), ("2027-01-03", {"ada": 1}))

    def test_the_exempt_types_are_the_defenses_the_vote_and_what_happens_once(self):
        self.assertEqual(ledger.DAILY_EXEMPT, {"depart", "rekey", "rekey_object", "custodian_revoke", "correction_object",
                                               "custodian_claim_object", "rekey_recover", "rekey_cosign", "rekey_oppose",
                                               "rekey_recover_apply", "ballot_commit", "ballot_reveal", "ballot_close",
                                               "exam_draw", "council_draw"})
        c = founded()
        amendment(c, "am")
        commit(c, "am", "ada")
        c.add("invite", "ada", {"login": "zed", "github_id": 9})
        self.assertEqual(c.state().day_entries, {"hiram": 1, "ada": 1})      # the genesis and the invite; not the
        #                                                                      amendment and not the vote

    def test_a_member_has_three_open_ballots(self):
        """Without this rule, one member could open amendment ballots without end."""
        c = founded()
        for i in range(3):
            amendment(c, f"am{i}", path=f"docs/{i}.md")
        amendment(c, "am3", path="docs/3.md")
        c.refused(self, "ada has 3 ballots open .a member has at most 3 open ballots of their own at once.")
        amendment(c, "am3", by="carol", path="docs/3.md")        # another member is not held by ada's ballots
        run_to_end(c, "am0")
        amendment(c, "am4", path="docs/4.md")                    # a closed ballot frees its place
        self.assertEqual(c.state().open_by("ada"), 3)

    def test_a_witness_checkpoints_once_per_new_entry_and_per_hour(self):
        """Without this rule, one witness key could post hundreds of checkpoints, each a full digest of the state."""
        c = founded(witnesses=("tyler", "node2"))
        c.add("witness", "tyler", checkpoint(c.state()))
        c.add("witness", "tyler", checkpoint(c.state()), days=1)
        c.refused(self, "no entry but checkpoints since the last checkpoint of tyler")
        c.add("witness", "node2", checkpoint(c.state()))         # another witness's checkpoint is not a new entry
        c.add("witness", "tyler", checkpoint(c.state()), days=1)
        c.refused(self, "no entry but checkpoints since the last checkpoint of tyler")
        c.add("work", "ada", {"ref": URL})
        st = c.state()
        self.assertTrue(ledger.checkpoint_due(st, "tyler", c.now))
        c.add("witness", "tyler", checkpoint(st))
        c.add("work", "carol", {"ref": URL})
        c.now += HOUR - SECOND
        self.assertFalse(ledger.checkpoint_due(c.state(), "tyler", c.now))
        c.add("witness", "tyler", checkpoint(c.state()))
        c.refused(self, "the last checkpoint of tyler is less than 1 hour old .at most one checkpoint per witness per hour.")
        c.now += SECOND
        c.add("witness", "tyler", checkpoint(c.state()))
        st = c.state()
        self.assertEqual((st.acts, st.witness_marks["tyler"]), (3, {"acts": 3, "time": c.now}))

    def test_a_custodian_gives_one_sign_of_life_in_24_hours(self):
        c = lodge()
        c.add("custodian_alive", "warden", {}, days=1 - 1 / 86400)
        c.refused(self, "the custodian warden gave a sign of life less than 24 hours ago")
        c.add("custodian_alive", "warden", {}, days=1 / 86400)
        c.add("custodian_alive", "warden", {}, days=0.5)
        c.refused(self, "at most one custodian_alive per custodian in 24 hours")
        self.assertEqual(c.state().custodians["warden"].alive, T0 + DAY)


# ---------------------------------------------------------------- who may open, and how often ----

class Openers(unittest.TestCase):
    def lodge_with_mallory(self):
        c = lodge()
        initiate(c, "mallory")
        return c

    def test_only_master_builders_open_amendment_and_witness_ballots(self):
        """Without this rule, a member of the 1st degree could hold the amendment slot of `@protocol`."""
        c = self.lodge_with_mallory()
        amendment(c, "sq", by="mallory", path="@protocol")
        c.refused(self, "only Master Builders may open an amendment ballot")
        c.add("ballot_open", "mallory", {"id": "w", "kind": "witness", "subject": witness_subject(c, "node2")})
        c.refused(self, "only Master Builders may open a witness ballot")
        c.add("ballot_open", "mallory", {"id": "w", "kind": "witness", "subject": {"action": "remove", "name": "tyler"}})
        c.refused(self, "only Master Builders may open a witness ballot")
        open_ballot(c, "rm", "mallory", "custodian", {"remove": "warden"})
        c.refused(self, "only Master Builders may open the ballot that removes a custodian")
        amendment(c, "am", by="ada", path="@protocol")
        self.assertEqual(c.state().ballots["am"].opened_by, "ada")

    def test_nobody_opens_a_sanction_ballot_on_themselves_and_a_measure_holds_only_its_own_place(self):
        """Without this rule, mallory could keep an `admonish` ballot on herself open, and no `expel` could open."""
        c = self.lodge_with_mallory()
        sanction(c, "sq", "mallory", "mallory")
        c.refused(self, "a member cannot open a sanction ballot on themselves")
        sanction(c, "s0", "ada", "mallory")
        c.refused(self, "only Master Builders may open a sanction ballot")
        sanction(c, "s1", "mallory", "ada", "admonish")
        sanction(c, "s2", "mallory", "carol", "expel")           # another measure: its own place
        sanction(c, "s3", "mallory", "hiram", "admonish")
        c.refused(self, "a ballot on this subject is already open")
        st = c.state()
        self.assertEqual((ledger.subject_key("sanction", st.ballots["s1"].subject), st.open_sanction_on("mallory").id),
                         ("mallory|admonish", "s1"))

    def test_an_arbiter_opens_the_sanction_ballot_where_three_exist(self):
        now = T0 + DAY
        arbiters = [mk(x, 7) for x in ("a1", "a2", "a3")]
        st = hand_state(mk("m1", 3), mk("bob", 1), *arbiters)
        body = {"id": "s", "kind": "sanction", "subject": {"member": "bob", "measure": "admonish"}}
        with self.assertRaisesRegex(Invalid, "only an Arbiter .7th degree or higher. may open a sanction ballot while three "
                                             "or more active Arbiters exist"):
            ledger._ballot_open(st, {}, now, 1, "m1", body)
        ledger._ballot_open(st, {}, now, 1, "a1", body)
        self.assertEqual(st.ballots["s"].electors, frozenset({"a1", "a2", "a3"}))
        two = hand_state(mk("m1", 3), mk("bob", 1), *arbiters[:2])   # fewer than three Arbiters: a Master Builder opens
        ledger._ballot_open(two, {}, now, 1, "m1", body)
        self.assertEqual(two.ballots["s"].electors, frozenset({"a1", "a2", "m1"}))

    def test_the_opener_of_a_failed_ballot_waits_ninety_days_on_that_subject(self):
        """Without this rule, the squatter could close and reopen in two consecutive entries, so the slot was never free.
        The wait is for sanction and witness ballots; an amendment's slot is its text, and it has no wait."""
        c = founded()
        subject = {"member": "carol", "measure": "admonish"}
        open_ballot(c, "s1", "ada", "sanction", subject)
        closed = run_to_end(c, "s1", {"hiram": "no", "ada": "yes"}).closed
        self.assertEqual(c.state().ballots["s1"].result, "failed")
        open_ballot(c, "s2", "ada", "sanction", subject)
        c.refused(self, "ada opened ballot s1 on this subject, and it failed less than 90 days ago")
        open_ballot(c, "other", "ada", "sanction", {"member": "carol", "measure": "suspend"})   # another subject is not held
        open_ballot(c, "s2", "hiram", "sanction", subject)       # …and neither is another member
        run_to_end(c, "s2")                                      # nobody votes: it lapses
        self.assertEqual(c.state().ballots["s2"].result, "lapsed")
        open_ballot(c, "s3", "hiram", "sanction", subject)
        c.refused(self, "hiram opened ballot s2 on this subject, and it lapsed less than 90 days ago")
        c.now = closed + 90 * DAY - SECOND
        open_ballot(c, "s3", "ada", "sanction", subject)
        c.refused(self, "ada opened ballot s1")
        c.now += SECOND
        open_ballot(c, "s3", "ada", "sanction", subject)
        self.assertIsNone(c.state().ballots["s3"].result)
        amendment(c, "am1", path="@protocol")                    # an amendment that failed is opened again at once
        run_to_end(c, "am1", {"hiram": "no", "ada": "yes", "carol": "no"})
        amendment(c, "am2", path="@protocol")
        self.assertIsNone(c.state().ballots["am2"].result)

    def test_a_passed_ballot_leaves_no_wait(self):
        c = founded()
        amendment(c, "am1", path="docs/x.md")
        run_to_end(c, "am1", {f: "yes" for f in FOUNDERS})
        amendment(c, "am2", path="docs/x.md")                    # the same opener corrects the pin at once
        self.assertEqual((c.state().ballots["am1"].result, c.state().ballots["am2"].result), ("passed", None))

    def test_an_admission_and_an_advancement_that_lapse_are_opened_again_at_once(self):
        self.assertEqual(ledger.REOPEN_KINDS, {"sanction", "witness"})
        c = founded()
        petition(c, "alice")
        c.add("vouch", "ada", {"candidate": "alice"})
        open_ballot(c, "a1", "hiram", "admission", {"candidate": "alice"})
        run_to_end(c, "a1", {"hiram": "yes"})
        st = c.state()
        self.assertEqual((st.ballots["a1"].result, "alice" in st.petitions, "alice" in st.members), ("lapsed", True, False))
        open_ballot(c, "a2", "hiram", "admission", {"candidate": "alice"})
        run_to_end(c, "a2", {f: "yes" for f in FOUNDERS})
        self.assertEqual(c.state().members["alice"].degree, 1)

    def test_only_the_candidate_or_an_examiner_opens_the_advancement_ballot(self):
        c = lodge(founders=SEVEN)
        initiate(c, "alice")
        ex = c.exam("alice", 2, days=31)
        outsider = next(x for x in SEVEN if x not in ex.examiners)
        subject = {"member": "alice", "degree": 2}
        open_ballot(c, "adv", outsider, "advancement", subject)
        c.refused(self, "only the candidate, or an examiner of the passed examination, may open the advancement ballot")
        d = fork(c)
        open_ballot(d, "adv", ex.examiners[0], "advancement", subject)
        self.assertEqual(d.state().ballots["adv"].opened_by, ex.examiners[0])
        open_ballot(c, "adv", "alice", "advancement", subject)
        self.assertEqual(c.state().ballots["adv"].opened_by, "alice")

    def test_only_an_amendment_chooses_its_windows(self):
        c = lodge()
        initiate(c, "bob")
        for kind, by, subject in (("sanction", "ada", {"member": "carol", "measure": "admonish"}),
                                  ("witness", "ada", witness_subject(c, "node2")),
                                  ("custodian", "ada", {"remove": "warden"}),
                                  ("admission", "hiram", {"candidate": "nobody"}),
                                  ("advancement", "bob", {"member": "bob", "degree": 2})):
            for windows in ({"commit_days": 30}, {"reveal_days": 14}, {"commit_days": 7, "reveal_days": 3}):
                open_ballot(c, "x", by, kind, subject, **windows)
                c.refused(self, f"an? {kind} ballot has fixed windows .7 days to commit, 3 to reveal.: it takes no "
                                "commit_days and no reveal_days .only an amendment ballot does.")
        amendment(c, "am", commit_days=2, reveal_days=1)
        b = c.state().ballots["am"]
        self.assertEqual((b.commit_until - b.opened, b.reveal_until - b.commit_until), (2 * DAY, REVEAL_GAP + DAY))
        sanction(c, "s")
        b = c.state().ballots["s"]
        self.assertEqual((b.commit_until - b.opened, b.reveal_until - b.commit_until), (7 * DAY, REVEAL_GAP + 3 * DAY))


# ---------------------------------------------------------------- a key proves itself ----

class Possession(unittest.TestCase):
    def test_a_witness_ballot_registers_only_a_key_that_signed_its_proof(self):
        """Without this rule, any member could burn any public key forever by proposing it as a witness key."""
        c = founded()
        nxt = c.key("ada-next")                                  # the key ada means to rekey to
        subject = {"action": "add", "name": "x1", "key": nxt, "proof": c.key("carol")}
        open_ballot(c, "w", "carol", "witness", subject)
        c.refused(self, "bad witness proof: the proposed key must sign the witness message .name, key.")
        self.assertNotIn(ledger.point(nxt), c.state().known_keys)
        c.add("rekey", "ada", {"key": nxt, "proof": nxt})        # ada's rekey is untouched
        self.assertEqual(c.state().members["ada"].key, nxt)
        for bad in ({"action": "add", "name": "x1", "key": c.key("x1")},
                    {"action": "add", "name": "x1", "proof": c.key("x1")},
                    {"action": "remove", "name": "x1", "proof": c.key("x1")}):
            open_ballot(c, "w", "carol", "witness", bad)
            c.refused(self, "a witness subject has action, name, key and proof to add a witness, and action and name only")
        open_ballot(c, "w", "carol", "witness", witness_subject(c, "x1"))
        self.assertIn(ledger.point(c.key("x1")), c.state().known_keys)

    def test_the_proof_names_the_witness_and_is_no_other_proof(self):
        self.assertEqual(witness_message("node2", "ssh-ed25519 AAAA"), b"openmasonry witness v1\nnode2\nssh-ed25519 AAAA\n")
        self.assertEqual(founder_message("ada", 42, "ssh-ed25519 AAAA"),
                         b"openmasonry founder v1\nada\n42\nssh-ed25519 AAAA\n")
        seen = []
        c = founded()
        open_ballot(c, "w", "ada", "witness", witness_subject(c, "node2"))
        replay(c.entries, verifier=lambda payload, sig, actor, key: seen.append((payload, actor, key)) or True)
        self.assertIn((witness_message("node2", c.key("node2")), "node2", c.key("node2")), seen)

    def test_the_founders_after_the_first_and_the_witnesses_of_a_genesis_prove_possession(self):
        c = Fast()
        good = genesis_body(c, FOUNDERS, ("tyler",))
        self.assertEqual(["proof" in f for f in good["founders"]], [False, True, True])
        cases = (
            (lambda b: b["founders"][1].pop("proof"), "the first founder signs the genesis itself and carries no proof; "
                                                      "every other founder carries one"),
            (lambda b: b["founders"][0].update(proof=c.key("hiram")), "the first founder signs the genesis itself"),
            (lambda b: b["founders"][2].update(proof=c.key("ada")), "bad founder proof: the key of carol must sign the "
                                                                    "founder message .login, github_id, key."),
            (lambda b: b["witnesses"][0].update(proof=c.key("ada")), "bad witness proof: the key of tyler must sign the "
                                                                     "witness message .name, key."),
            (lambda b: b["witnesses"][0].pop("proof"), "malformed genesis entry: witness: missing field 'proof'"),
        )
        for change, pattern in cases:
            body = copy.deepcopy(good)
            change(body)
            c.add("genesis", "hiram", body)
            c.refused(self, pattern)
        c.add("genesis", "hiram", good)
        self.assertEqual(len(c.state().known_keys), 4)

    def test_the_proofs_are_signed_over_the_messages(self):
        c = Fast()
        seen = []
        c.add("genesis", "hiram", genesis_body(c, FOUNDERS, ("tyler",)))
        replay(c.entries, verifier=lambda payload, sig, actor, key: seen.append((payload, key)) or True)
        self.assertIn((founder_message("ada", gid("ada"), c.key("ada")), c.key("ada")), seen)
        self.assertIn((witness_message("tyler", c.key("tyler")), c.key("tyler")), seen)


# ---------------------------------------------------------------- the identity gate ----

class IdentityById(unittest.TestCase):
    def gate(self, c, since, author, author_id, keys=None, **kw):
        user = mock.Mock(side_effect=AssertionError("the id of the pull request event is enough"))
        return identity.pr_problems(c.entries, since, author, fetch=keys or (lambda login: []), fetch_user=user,
                                    author_id=author_id, **kw)

    def test_the_old_keys_objection_and_a_departure_are_carried_by_anyone(self):
        """Without this rule, with the GitHub account in other hands, the owner's `rekey_object` and `depart` would be refused."""
        c = lodge(founders=SEVEN)
        freeze(c, "carol")
        ask(c, "carol", days=1)
        n = len(c.entries)
        stop(c, "carol")
        for author, author_id in (("carol-real", 999), ("ada", gid("ada")), ("carol", gid("carol"))):
            self.assertEqual(self.gate(c, n, author, author_id), [])
        d = lodge(founders=SEVEN)
        d.add("depart", "carol", {})
        self.assertEqual(self.gate(d, 1, "somebody-else", 999), [])
        self.assertEqual(identity.CARRIED, {"depart", "rekey_object"})

    def test_an_account_is_its_numeric_id_whatever_its_login(self):
        """Without this rule, a member who renamed the GitHub account could sign nothing through the gate."""
        c = founded()
        c.add("work", "ada", {"ref": URL})
        self.assertEqual(self.gate(c, 1, "ada-new-name", gid("ada")), [])
        bad = self.gate(c, 1, "ada", gid("ada") + 1)             # the login, taken by another account
        self.assertEqual(bad, [f"entry 1 (work): ada is the GitHub account with id {gid('ada')}, but the pull request is "
                               f"by the account with id {gid('ada') + 1}"])

    def test_the_new_key_of_a_renamed_account_is_listed_under_its_login_of_today(self):
        c = founded()
        new = c.key("ada-2")
        c.add("rekey", "ada", {"key": new, "proof": new})
        listed = lambda login: [new] if login == "ada-new-name" else []
        self.assertEqual(self.gate(c, 1, "ada-new-name", gid("ada"), keys=listed), [])
        self.assertIn("the new key is not listed at https://github.com/ada.keys", self.gate(c, 1, "ada", gid("ada"), keys=listed)[0])

    def test_without_the_event_id_the_author_is_looked_up_once(self):
        c = founded()
        c.add("work", "ada", {"ref": URL})
        c.add("work", "ada", {"ref": URL}, days=1)
        calls = []

        def user(login):
            calls.append(login)
            return {"id": gid("ada"), "login": login}
        self.assertEqual(identity.pr_problems(c.entries, 1, "ada", fetch=lambda login: [], fetch_user=user), [])
        self.assertEqual(calls, ["ada"])

    def test_the_genesis_comes_from_the_founders_account(self):
        """Without this rule, nothing would tie entry 0 to the owner of the repository."""
        c = founded()
        users = lambda login: {"id": gid(login), "login": login}
        gate = lambda author, author_id, **kw: identity.pr_problems(c.entries, 0, author, fetch=lambda login: [],
                                                                    fetch_user=users, author_id=author_id, **kw)
        self.assertEqual(canon.FOUNDER_GITHUB_ID, gid("hiram"))          # tests/__init__.py: the founder of the test lodges
        self.assertEqual(gate("hiram", gid("hiram")), [])
        self.assertEqual(gate("hiram-renamed", gid("hiram")), [])
        self.assertIn(f"the genesis comes from the founder's GitHub account (id {gid('hiram')}), but the pull request is by "
                      f"the account with id {gid('ada')}", gate("ada", gid("ada"))[0])
        unset = gate("hiram", gid("hiram"), founder_id=0)
        self.assertIn("founder_github_id is not set in src/openmasonry/network.toml", unset[0])
        other = gate("hiram", gid("hiram"), founder_id=7)
        self.assertIn(f"the first founder states the GitHub id {gid('hiram')}, but src/openmasonry/network.toml names the "
                      "founder with id 7", other[0])

    def test_the_repository_names_the_founding_account(self):
        import tomllib
        network = tomllib.loads((canon.ROOT / "src" / "openmasonry" / "network.toml").read_text(encoding="utf-8"))
        self.assertEqual(sorted(network), ["founder_github_id", "repository"])
        self.assertEqual(type(network["founder_github_id"]), int)
        self.assertGreater(network["founder_github_id"], 0)                # set in the tree the genesis pins
        self.assertIn("src/openmasonry/network.toml", govern.read_manifest())


# ---------------------------------------------------------------- who decides a ballot ----

class WhoDecides(unittest.TestCase):
    def test_a_frozen_elector_commits_and_reveals_in_every_ballot(self):
        """Without this rule, one freeze of one opposing elector could pass an amendment."""
        def run(frozen: bool):
            c = lodge(founders=("hiram", "ada", "carol", "eve", "finn"))
            amendment(c, "am", path="CONSTITUTION.md", commit_days=2, reveal_days=1)
            if frozen:
                freeze(c, "finn")
            votes = {"hiram": "yes", "ada": "yes", "carol": "yes", "eve": "no", "finn": "no"}
            return run_to_end(c, "am", votes).result
        self.assertEqual((run(False), run(True)), ("failed", "failed"))

    def test_a_frozen_member_still_signs_nothing_else(self):
        c = lodge()
        open_ballot(c, "s", "ada", "sanction", {"member": "carol", "measure": "admonish"})
        freeze(c, "ada")
        for typ, body in (("work", {"ref": URL}), ("ballot_close", {"id": "s"}),
                          ("ballot_open", {"id": "x", "kind": "sanction", "subject": {"member": "carol", "measure": "suspend"}})):
            c.add(typ, "ada", body)
            c.refused(self, "a frozen member may only depart, rekey, vote .commit and reveal., take part in an amendment "
                            "ballot or the ballot that removes a custodian, or object to a recovery of their own key")
        self.assertEqual(ledger.FREEZE_ALLOWED, {"depart", "rekey", "rekey_object", "ballot_commit", "ballot_reveal"})

    def test_an_undo_never_shrinks_an_electorate_and_a_sealed_vote_is_still_revealed(self):
        """Without this rule, a stay and the undo of a voter's advancement and admission could remove a black ball."""
        c = quarry()
        initiate(c, "bob")
        initiate(c, "dave")
        advb = advance(c, "bob", 2)
        c.exam("dave", 2)
        open_ballot(c, "bb", "dave", "advancement", {"member": "dave", "degree": 2})
        electors = c.state().ballots["bb"].electors
        self.assertEqual(electors, frozenset(SEVEN) | {"bob"})
        votes = {"hiram": "yes", "ada": "yes", "carol": "yes", "bob": "no"}
        for who, vote in votes.items():
            commit(c, "bb", who, vote)
        correct(c, "stay", {"ballot": "bb"})
        u1, u2 = undo(c, advb), undo(c, "adm-bob")
        apply_(c, u1, days=14)
        apply_(c, u2)
        st = c.state()
        b = st.ballots["bb"]
        self.assertEqual((st.members["bob"].status, b.electors), ("voided", electors))
        c.add("work", "bob", {"ref": URL})
        c.refused(self, "bob is not an active member")           # the record signs nothing…
        c.now = st.ballot_due(b, b.commit_until + REVEAL_GAP)
        for who, vote in votes.items():
            reveal(c, "bb", who, vote)                           # …but the vote it sealed is revealed, and counted
        c.now = st.ballot_due(b, b.reveal_until) + SECOND
        c.add("ballot_close", "ada", {"id": "bb"})
        st = c.state()
        self.assertEqual((st.ballots["bb"].result, st.members["dave"].degree), ("failed", 1))     # one black ball in four

    def test_a_voided_record_reveals_only_what_it_sealed(self):
        c = quarry()
        initiate(c, "bob")
        amendment(c, "am", by="ada")
        u = undo(c, "adm-bob")
        apply_(c, u, days=14)
        c.add("ballot_reveal", "bob", {"id": "am", "vote": "no", "salt": salt_of("bob")})
        c.refused(self, "bob is not an active member")
        c.add("ballot_commit", "bob", {"id": "am", "commitment": "ab" * 32})
        c.refused(self, "bob is not an active member")

    def test_a_vote_revealed_before_the_undo_is_counted(self):
        st = hand_state(mk("a"), mk("b"), mk("c"), mk("bob", 1, status="voided"), mk("cand", 1))
        now = T0 + 20 * DAY
        st.petitions["x"] = {"key": fake_key("x"), "vouches": ["a", "b"], "time": now - DAY, "github_id": 9}
        st.ballots["adm"] = Ballot("adm", "admission", {"candidate": "x"}, frozenset({"a", "b", "c", "bob"}), now - 4 * DAY,
                                   now - DAY, "a", reveals={"a": "yes", "b": "yes", "c": "yes", "bob": "no"},
                                   frozen={"key": fake_key("x"), "vouches": ["a", "b"], "github_id": 9}, opened=now - 11 * DAY)
        ledger._ballot_close(st, {}, now, 9, "a", {"id": "adm"})
        self.assertEqual(st.ballots["adm"].result, "failed")     # 5 x 1 black ball >= 4 votes: bob's vote stands

    def test_a_ballot_is_stayed_or_its_voiding_posted_only_before_a_vote_can_be_revealed(self):
        """Without this rule, the custodian could read the revealed votes, then void the ballot."""
        c = quarry()
        sanction(c, "sx", "eve", "ada", "expel")
        for who in ("hiram", "ada", "carol"):
            commit(c, "sx", who)
        b = c.state().ballots["sx"]
        opens = b.commit_until + REVEAL_GAP
        c.now = opens
        for act, target in (("void_ballot", {"id": "sx"}), ("stay", {"ballot": "sx"})):
            correct(c, act, target)
            c.refused(self, f"the reveal window of ballot sx opened at {iso(opens)}: a ballot is stayed, or its voiding "
                            "posted, only before any vote can be revealed")
        c.now = opens - SECOND
        d = fork(c)
        correct(d, "stay", {"ballot": "sx"})
        self.assertIsNotNone(d.state().stayed("sx", d.now))
        void(c, "sx", "protocol_defect")
        self.assertIsNotNone(c.state().void_pending("sx", c.now))

    def test_a_pending_void_pauses_the_ballot_so_no_vote_is_read_during_the_notice(self):
        c = quarry()
        sanction(c, "sx", "eve", "ada", "expel")
        commit(c, "sx", "hiram")
        v = void(c, "sx", "protocol_defect", days=1)
        commit(c, "sx", "ada", "yes")
        c.refused(self, f"ballot sx is paused while the correction that would void it is pending .correction {v}, until")
        st = c.state()
        b = st.ballots["sx"]
        self.assertEqual(st.pauses("sx"), [(c.now, c.now + 21 * DAY + SECOND)])
        c.now = b.commit_until + REVEAL_GAP + DAY                # past its stored reveal opening: the clock stands still
        reveal(c, "sx", "hiram")
        c.refused(self, "ballot sx is paused while the correction that would void it is pending")
        withdraw(c, v)                                           # the pause ends, and the windows are as long as before
        commit(c, "sx", "ada", "yes")
        st = c.state()
        paused = st.paused(b.opened, c.now, "sx")
        self.assertEqual(st.ballot_due(b, b.commit_until), b.commit_until + paused)
        c.now = st.ballot_due(b, b.commit_until + REVEAL_GAP)
        reveal(c, "sx", "hiram")
        reveal(c, "sx", "ada")
        self.assertEqual(c.state().ballots["sx"].reveals, {"hiram": "yes", "ada": "yes"})


# ---------------------------------------------------------------- a ballot can always be closed ----

class Amendments(unittest.TestCase):
    def test_a_canon_amendment_opens_only_once_its_text_is_archived(self):
        """Without this rule, a passed amendment of the degree canon whose text was not archived would never close."""
        c = founded()
        amendment_of_canon = {"path": "canon/degrees.toml", "new_sha256": "77" * 32}
        open_ballot(c, "canon", "ada", "amendment", amendment_of_canon)
        c.refused(self, "the new degree canon 777777777777… is not archived: add canon/history/" + "77" * 32
                        + ".toml before opening this ballot .in an earlier pull request, or in the pull request that opens it.")
        current = c.state().pins["canon/degrees.toml"]
        open_ballot(c, "canon", "ada", "amendment", {"path": "canon/degrees.toml", "new_sha256": current},
                    commit_days=2, reveal_days=1)
        self.assertEqual(run_to_end(c, "canon", {f: "yes" for f in FOUNDERS}).result, "passed")

    def test_a_pull_request_of_amendment_ballot_entries_passes_a_tree_that_does_not_match_the_pins(self):
        c = founded()
        root = copy_governed(tmpdir(self) / "tree")
        (root / "CONSTITUTION.md").write_text("another text\n", encoding="utf-8")       # the tree became unlawful
        amendment(c, "fix", path="CONSTITUTION.md")
        commit(c, "fix", "ada")
        led = write_ledger(tmpdir(self) / "led", c.entries)

        def report(since, tree=True):
            a = argparse.Namespace(ledger=led, tree=tree, online=False, clock_since=None, root=root, pr_author=None,
                                   since=since, json=True)
            with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)), \
                    mock.patch.object(identity, "pr_problems", return_value=[]):
                a.pr_author = "ada" if since is not None else None
                return verify.verify_report(a)
        self.assertIn("UNRATIFIED", report(None)["message"])
        through = report(1)
        self.assertTrue(through["valid"], through["message"])
        self.assertIn("accepted because every new entry belongs to an amendment ballot", through["message"])
        self.assertIn("CONSTITUTION.md", through["warnings"][0])
        c.add("work", "ada", {"ref": URL})
        led = write_ledger(tmpdir(self) / "led2", c.entries)
        self.assertIn("UNRATIFIED", report(1)["message"])        # any other entry, and the tree is held to its pins
        self.assertTrue(govern.amendment_only(c.entries[:3], 1))
        self.assertFalse(govern.amendment_only(c.entries, 1))
        self.assertFalse(govern.amendment_only(c.entries[:3], 3))


# ---------------------------------------------------------------- withdrawal ----

class Withdrawal(unittest.TestCase):
    def three(self):
        return lodge(custodians=(("c1", "hiram"), ("c2", "ada"), ("c3", "carol")), founders=SEVEN, custodian_threshold=2)

    def test_one_custodian_of_several_does_not_withdraw_the_act_of_another(self):
        """Without this rule, one custodian key could withdraw another's freeze and cancel the recovery that followed."""
        c = self.three()
        f = freeze(c, "eve", by="c1")
        ask(c, "eve", days=1)
        withdraw(c, f, by="c3", days=1)
        st = c.state()
        self.assertEqual((st.corrections[f].withdrawals, st.corrections[f].withdrawn), (("c3",), None))
        self.assertEqual(st.recovery_status(st.recoveries["eve"], c.now), "pending")
        withdraw(c, f, by="c3")
        c.refused(self, f"c3 already signed the withdrawal of correction {f}")
        withdraw(c, f, by="c2")                                  # the second of the two it takes
        st = c.state()
        self.assertEqual((st.corrections[f].withdrawn, st.corrections[f].withdrawn_by), (c.now, "c2"))
        self.assertEqual(st.recovery_status(st.recoveries["eve"], c.now), "canceled")

    def test_the_poster_withdraws_alone(self):
        c = self.three()
        f = freeze(c, "eve", by="c1")
        withdraw(c, f, by="c1")
        self.assertEqual(c.state().corrections[f].withdrawn_by, "c1")

    def test_an_act_others_withdrew_leaves_no_wait_and_frees_the_slot(self):
        c = self.three()
        f = freeze(c, "eve", by="c1")
        withdraw(c, f, by="c2")
        withdraw(c, f, by="c3")
        freeze(c, "eve", by="c1", days=1)                        # no wait of 90 days: the others ended the first one
        c = self.three()
        sanction(c, "s1", "eve", "dan")
        v = void(c, "s1", by="c1")
        withdraw(c, v, by="c2")
        withdraw(c, v, by="c3")
        again = void(c, "s1", by="c1")
        self.assertTrue(c.state().pending(c.state().corrections[again], c.now))

    def test_an_act_its_poster_withdrew_is_spent(self):
        c = self.three()
        f = freeze(c, "eve", by="c1")
        withdraw(c, f, by="c1")
        freeze(c, "eve", by="c2", days=1)
        c.refused(self, "the key of eve was frozen less than 90 days ago .the same key is frozen again only 90 days after "
                        "the previous freeze began, unless other custodians withdrew that freeze.")
        sanction(c, "s1", "eve", "dan")
        v = void(c, "s1", by="c2")
        withdraw(c, v, by="c2")
        void(c, "s1", by="c3")
        c.refused(self, f"ballot s1 was the target of a void_ballot once already .correction {v}.: a ballot is the target "
                        "of a void_ballot at most once, unless other custodians withdrew it")


# ---------------------------------------------------------------- recoveries ----

class Recoveries(unittest.TestCase):
    def test_two_masters_recover_with_the_one_co_signer_that_exists(self):
        """Without this rule, with two Masters a lost key would never be recovered."""
        c = lodge(founders=("hiram", "ada"))
        freeze(c, "ada")
        ask(c, "ada")
        finish(c, "ada", days=45)                                # lowered to the one co-signer: 45 days of notice
        c.refused(self, "the recovery of the key of ada has 0 of the 1 co-signatures of active Master Builders it needs")
        co(c, "ada", "hiram")
        finish(c, "ada")
        self.assertEqual(c.state().members["ada"].key, c.key("ada-new"))

    def test_a_sole_founder_recovers_after_the_freeze_and_the_notice(self):
        """Without this rule, one founder, key lost: nothing could ever be signed again."""
        c = lodge(founders=("hiram",))
        freeze(c, "hiram")
        ask(c, "hiram")
        finish(c, "hiram", days=45)                              # no co-signer exists: the longer notice
        st = c.state()
        self.assertEqual((st.members["hiram"].key, ledger.cosigners_needed(st, st.recoveries["hiram"], c.now)),
                         (c.key("hiram-new"), 0))

    def test_where_no_custodian_key_is_live_three_masters_start_the_notice(self):
        c = Fast()                                               # no custodian at all
        c.add("genesis", "hiram", genesis_body(c, SEVEN))
        ask(c, "ada", days=1)
        st = c.state()
        r = st.recoveries["ada"]
        self.assertEqual((r.freeze, r.notice, st.recovery_status(r, c.now), st.key_frozen("ada", c.now)),
                         (None, None, "requested", False))
        self.assertEqual(st.key_holders(c.key("ada-new"), c.now), [("recovery", "ada")])
        c.add("work", "ada", {"ref": URL})                       # not frozen yet: the old key still signs
        finish(c, "ada", days=1)
        c.refused(self, "the recovery of the key of ada has 0 of the 3 co-signatures of active Master Builders that start "
                        "its notice")
        co(c, "ada", "carol")
        co(c, "ada", "dan")
        self.assertIsNone(c.state().recoveries["ada"].notice)
        co(c, "ada", "eve", days=1)
        st = c.state()
        r = st.recoveries["ada"]
        self.assertEqual((r.notice, st.recovery_status(r, c.now), st.key_frozen("ada", c.now)), (c.now, "pending", True))
        c.add("work", "ada", {"ref": URL}, days=1)
        c.refused(self, "the key of ada stays frozen while its recovery is pending")
        d = fork(c)
        finish(d, "ada", days=29 - 1 / 86400)
        d.refused(self, f"is under notice until {iso(r.notice + 30 * DAY)} .30 days after its notice began.")
        c.now = r.notice + 30 * DAY
        finish(c, "ada")
        self.assertEqual(c.state().members["ada"].key, c.key("ada-new"))

    def test_a_recovery_never_needs_a_custodian_who_answers(self):
        """with a live custodian key and no freeze, the recovery is an open one (it is not refused)."""
        c = lodge(founders=SEVEN)
        ask(c, "ada")
        r = c.state().recoveries["ada"]
        self.assertEqual((r.freeze, r.notice), (None, None))

    def test_the_only_master_builder_needs_no_co_signer(self):
        """The coordinator's case: a sole Master without a custodian is not a dead end."""
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, ["hiram"]))
        ask(c, "hiram", days=1)
        st = c.state()
        r = st.recoveries["hiram"]
        self.assertEqual((ledger.cosigners_needed(st, r, c.now), r.notice, st.recovery_status(r, c.now)), (0, c.now, "pending"))
        self.assertTrue(st.key_frozen("hiram", c.now))
        finish(c, "hiram", days=30 - 1 / 86400)
        c.refused(self, "is under notice until")
        d = fork(c)
        stop(d, "hiram", days=10)                                # the old key still stops it
        self.assertEqual(d.state().recovery_status(d.state().recoveries["hiram"], d.now), "objected")
        finish(c, "hiram", days=30)
        self.assertEqual(c.state().members["hiram"].key, c.key("hiram-new"))

    def test_fewer_than_three_other_masters_co_sign_as_many_as_exist(self):
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, FOUNDERS))
        ask(c, "ada", days=1)
        co(c, "ada", "hiram")
        self.assertIsNone(c.state().recoveries["ada"].notice)
        co(c, "ada", "carol")
        self.assertEqual(c.state().recoveries["ada"].notice, c.now)

    def test_the_co_signers_are_not_all_sponsors_of_the_member(self):
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, SEVEN))
        initiate(c, "bob")                                       # sponsors: hiram and ada
        st = c.state()
        st.members["bob"].sponsors = ("hiram", "ada", "carol")
        r = ledger.Recovery("bob", fake_key("bob-new"), 99, c.now)
        self.assertTrue(ledger.only_sponsors(st, r, ("hiram", "ada", "carol"), c.now))
        self.assertFalse(ledger.cosigned(st, r, ("hiram", "ada", "carol"), c.now))
        self.assertTrue(ledger.cosigned(st, r, ("hiram", "ada", "dan"), c.now))

    def test_master_builders_oppose_a_recovery_asked_without_a_freeze(self):
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, SEVEN))
        ask(c, "ada", days=1)
        co(c, "ada", "carol")
        c.add("rekey_oppose", "carol", {"login": "ada"})
        c.refused(self, "carol co-signed the recovery of the key of ada and cannot oppose it")
        c.add("rekey_oppose", "ada", {"login": "ada"})
        c.refused(self, "a member stops the recovery of their own key with rekey_object, signed by the old key")
        c.add("rekey_oppose", "dan", {"login": "ada"})           # six other Masters, a co-signer among them: two void it
        st = c.state()
        r = st.recoveries["ada"]
        self.assertEqual((r.opposed, r.void, st.recovery_status(r, c.now)), (("dan",), None, "requested"))
        co(c, "ada", "dan")
        c.refused(self, "dan opposed the recovery of the key of ada and cannot co-sign it")
        c.add("rekey_oppose", "eve", {"login": "ada"})
        self.assertEqual(c.state().recoveries["ada"].void, c.now)
        co(c, "ada", "fay")
        c.refused(self, "no recovery of the key of ada is pending")

    def test_one_fifth_of_the_other_masters_void_it(self):
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, SEVEN))
        ask(c, "ada", days=1)
        c.add("rekey_oppose", "dan", {"login": "ada"})
        st = c.state()
        self.assertEqual(st.recoveries["ada"].void, None)        # 6 others: max(1, ceil(6 / 5)) = 2
        c.add("rekey_oppose", "dan", {"login": "ada"})
        c.refused(self, "already opposed the recovery of the key of ada")
        c.add("rekey_oppose", "eve", {"login": "ada"})
        st = c.state()
        self.assertEqual((st.recoveries["ada"].void, st.recovery_status(st.recoveries["ada"], c.now)), (c.now, "opposed"))
        finish(c, "ada", days=40)
        c.refused(self, "no recovery of the key of ada is pending")

    def test_a_recovery_after_a_freeze_is_checked_by_objecting_to_the_freeze(self):
        c = lodge(founders=SEVEN)
        f = freeze(c, "ada")
        ask(c, "ada")
        c.add("rekey_oppose", "dan", {"login": "ada"})
        c.refused(self, f"the recovery of the key of ada follows a freeze .correction {f}.: a Master Builder objects to that "
                        "correction instead")

    def test_after_an_objected_recovery_the_next_one_is_not_stopped_by_the_old_key_and_needs_three(self):
        """Without this rule, a thief who holds only the key could stop every recovery forever."""
        c = lodge(founders=SEVEN)
        freeze(c, "ada")
        ask(c, "ada", days=1)
        stop(c, "ada", days=1)
        freeze(c, "ada", days=89)                                # T0 + 91 d: 90 days after the request, 89 after the objection
        ask(c, "ada", new="ada-3")
        c.refused(self, "the old key of ada stopped a recovery less than 90 days ago .the next request, 90 days after that, "
                        "cannot be stopped by the old key and needs 3 co-signers.")
        c.now += 2 * DAY
        ask(c, "ada", new="ada-3")
        st = c.state()
        r = st.recoveries["ada"]
        self.assertEqual((r.final, ledger.cosigners_needed(st, r, c.now)), (True, 3))
        stop(c, "ada")
        c.refused(self, "the recovery of the key of ada follows one the old key stopped, and the old key cannot stop this one")
        co(c, "ada", "carol")
        co(c, "ada", "dan")
        finish(c, "ada", new="ada-3", days=21)
        c.refused(self, "has 2 of the 3 co-signatures of active Master Builders it needs")
        co(c, "ada", "eve")
        finish(c, "ada", new="ada-3")
        self.assertEqual(c.state().members["ada"].key, c.key("ada-3"))

    def test_the_login_of_a_co_signature_is_a_login(self):
        """Without this rule, an unvalidated string of an entry would reach the judge's log, line feed and all."""
        c = lodge()
        for typ in ("rekey_cosign", "rekey_oppose"):
            c.add(typ, "ada", {"login": "x\n::notice title=judge::PASSED"})
            c.refused(self, "login must be a valid GitHub login$")


# ---------------------------------------------------------------- keys are validated once ----

class KeyCache(unittest.TestCase):
    def test_asking_who_holds_a_key_validates_no_key_the_state_holds(self):
        """Without this rule, past 4,096 keys every question about a key would validate every member's key again."""
        st = State()
        for i in range(300):
            st.members[f"m{i}"] = Member(f"m{i}", fake_key(f"m{i}"), 1, {1: T0}, activity=[T0], github_id=i + 1)
        probe, held = fake_key("probe"), fake_key("m7")
        ledger.point(probe)                                      # validated once
        crypto._POINTS.clear()                                   # as in a process that has met none of these keys
        ledger.point(probe), ledger.point(held)
        with mock.patch.object(crypto, "_mul", side_effect=AssertionError("a stored key was validated again")):
            self.assertEqual(st.key_holders(probe, T0), [])
            self.assertEqual(st.key_holders(held, T0), [("member", "m7")])
        self.assertEqual(len(crypto._POINTS), 2)                 # the 300 keys of the state were decoded, never validated

    def test_a_valid_key_is_never_checked_twice_however_many_keys_there_are(self):
        self.assertFalse(hasattr(crypto._key_point, "cache_info"))       # no bounded cache to fall off
        raw = crypto.public_point(fake_key("probe"))
        self.assertIn(raw, crypto._POINTS)
        self.assertIsNone(crypto._key_point(b"\x01" + b"\x00" * 31))      # a point of small order is not remembered
        self.assertNotIn(b"\x01" + b"\x00" * 31, crypto._POINTS)
        self.assertEqual(crypto.key_bytes(fake_key("probe")), raw)
        self.assertIsNone(crypto.key_bytes("ssh-ed25519 not-base64"))


# ---------------------------------------------------------------- the judge ----

class Judge(unittest.TestCase):
    def ledger_of(self, c):
        return write_ledger(tmpdir(self) / "led", c.entries)

    def args(self, led, **flags):
        a = argparse.Namespace(ledger=led, tree=False, online=False, clock_since=None, root=None, pr_author=None,
                               since=None, json=True)
        for k, v in flags.items():
            setattr(a, k, v)
        return a

    def test_entries_before_since_are_taken_on_trust_and_a_run_without_it_verifies_everything(self):
        c = founded(witnesses=("tyler",))
        c.add("work", "ada", {"ref": URL}, key_of="carol")       # entry 1: not ada's signature
        st = replay(c.entries, verifier=lambda *_: True)
        c.add("witness", "tyler", checkpoint(st) | {"state_sha256": "00" * 32}, days=1)     # entry 2: not the digest
        c.add("work", "carol", {"ref": URL})
        full = lambda entries, **kw: replay(entries, verifier=by_key, **kw)
        with self.assertRaisesRegex(Invalid, "entry 1: bad signature"):
            full(c.entries)
        with self.assertRaisesRegex(Invalid, "entry 2: witness state digest mismatch"):
            full(c.entries, trusted=2)
        st = full(c.entries, trusted=3)                          # old entries: neither the signature nor the digest is asked
        self.assertEqual((st.seq, st.history["checkpoints"]),
                         (3, absorbed({"witness": "tyler"} | c.entries[2]["body"])))      # the stated digest, as it stands
        self.assertEqual(st.digest(), replay(c.entries, verifier=lambda *_: True, trusted=3).digest())
        c.entries[3]["sig"] = "forged"                           # a new entry is verified in full
        with self.assertRaisesRegex(Invalid, "entry 3: bad signature"):
            full(c.entries, trusted=3)
        c.add("work", "ada", {"ref": URL}, days=-5)              # every rule but those two holds for an old entry too
        with self.assertRaisesRegex(Invalid, "entry 4: time goes backwards"):
            full(c.entries, trusted=5)

    def test_only_the_beacons_of_new_entries_are_fetched_again(self):
        c = founded(witnesses=("tyler",))
        initiate(c, "alice")
        c.exam("alice", 2, days=31)
        n = len(c.entries)
        initiate(c, "bob")
        c.exam("bob", 2, days=31)
        led = self.ledger_of(c)
        seen = []
        with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)), \
                mock.patch("openmasonry.beacon.fetch", side_effect=lambda rnd: seen.append(rnd) or f"{rnd:064x}"), \
                mock.patch.object(identity, "pr_problems", return_value=[]):
            clock = lambda: c.now
            new = verify.verify_report(self.args(led, online=True, since=n, pr_author="hiram"), clock)
            self.assertEqual((new["valid"], len(seen)), (True, 1))
            verify.verify_report(self.args(led, online=True), clock)
            self.assertEqual(len(seen), 3)

    def test_the_clock_is_read_once_before_the_replay(self):
        c = founded()
        led = self.ledger_of(c)
        ticks = []

        def clock():
            ticks.append(1)
            return T0 + HOUR * len(ticks) * 100                  # a clock that would drift far if it were asked again
        with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)):
            r = verify.verify_report(self.args(led, clock_since=0, online=False), clock)
        self.assertEqual(len(ticks), 1)
        self.assertIn("STALE OR FUTURE TIME", r["message"])

    def test_the_judge_takes_two_minutes_ahead_and_the_alarm_starts_at_ten(self):
        """Without this rule, the judge would accept +10 minutes and the client alarm above +10 minutes."""
        self.assertEqual((ledger.JUDGE_FUTURE_TOLERANCE, ledger.FUTURE_TOLERANCE), (timedelta(minutes=2), timedelta(minutes=10)))
        c = founded()
        led = self.ledger_of(c)
        with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)):
            ok = verify.verify_report(self.args(led, clock_since=0), lambda: T0 - timedelta(minutes=2))
            late = verify.verify_report(self.args(led, clock_since=0), lambda: T0 - timedelta(minutes=2, seconds=1))
        self.assertTrue(ok["valid"], ok["message"])
        self.assertIn("STALE OR FUTURE TIME", late["message"])
        self.assertFalse(ledger.future_head(T0 + timedelta(minutes=2), T0 - timedelta(minutes=8)))
        self.assertTrue(ledger.future_head(T0 + timedelta(minutes=10, seconds=1), T0))

    def test_a_tool_never_stamps_an_entry_before_the_head(self):
        st = founded().state()
        with mock.patch.object(ledger, "utc_now", return_value=iso(T0 - HOUR)):       # this clock is behind the head
            self.assertEqual(ledger.make_entry(st, "work", "ada", {"ref": URL})["time"], iso(T0 + SECOND))
        with mock.patch.object(ledger, "utc_now", return_value=iso(T0 + HOUR)):
            self.assertEqual(ledger.make_entry(st, "work", "ada", {"ref": URL})["time"], iso(T0 + HOUR))
        self.assertEqual(ledger.make_entry(st, "work", "ada", {"ref": URL}, iso(T0))["time"], iso(T0))

    def test_an_anchor_belongs_to_a_checkpoint_of_the_same_pull_request(self):
        c = founded(witnesses=("tyler",))
        c.add("work", "ada", {"ref": URL})
        st = c.state()
        c.add("witness", "tyler", checkpoint(st, root=st.entries_root(), anchor="ledger/anchors/000001.root.ots"))
        old = len(c.entries)
        c.add("work", "ada", {"ref": URL}, days=1)
        st = c.state()
        c.add("witness", "tyler", checkpoint(st, root=st.entries_root(), anchor="ledger/anchors/000003.root.ots"))
        root_file = (st.entries_root() + "\n").encode()
        proof = govern.OTS_PREFIX + hashlib.sha256(root_file).digest() + b"\x00(the timestamp)"
        root = tmpdir(self)
        (root / "ledger" / "anchors").mkdir(parents=True)
        files = {"000001.root": b"x", "000001.root.ots": b"x", "000003.root": root_file, "000003.root.ots": proof,
                 "000009.root": root_file, "big.root.ots": b"x" * (govern.ANCHOR_MAX_BYTES + 1)}
        for name, data in files.items():
            (root / "ledger" / "anchors" / name).write_bytes(data)
        check = lambda changes, since=old: govern.anchor_problems(c.entries, since, govern.parse_changes(changes), root)
        self.assertEqual(check("A\tledger/anchors/000003.root\nA\tledger/anchors/000003.root.ots\n"), [])
        self.assertEqual(check("A\tledger/anchors/000009.root\n"),
                         ["ledger/anchors/000009.root: no witness entry of this pull request names this anchor"])
        self.assertIn("never changed once merged", check("M\tledger/anchors/000001.root.ots\n")[0])
        self.assertIn("never changed once merged", check("M\tledger/anchors/000001.root\n")[0])
        self.assertIn("never changed, deleted or renamed", check("D\tledger/anchors/000001.root.ots\n")[0])
        self.assertIn("no witness entry of this pull request", check("A\tledger/anchors/000003.root.ots\n", len(c.entries))[0])
        (root / "ledger" / "anchors" / "000003.root").write_bytes(b"x" * (govern.ANCHOR_MAX_BYTES + 1))
        self.assertEqual(check("A\tledger/anchors/000003.root\n"), ["ledger/anchors/000003.root is larger than 16384 bytes"])
        self.assertEqual(govern.parse_changes("garbage line\nA\tx\n"), [("?", "garbage line"), ("A", "x")])

    def test_the_workflow_hands_the_anchor_changes_to_the_verifier(self):
        text = (canon.ROOT / ".github/workflows/judge.yml").read_text(encoding="utf-8")
        self.assertIn('git diff --no-renames --name-status "$range" -- ledger/anchors > "$RUNNER_TEMP/anchors-changed"', text)
        self.assertIn('--anchors-changed "$RUNNER_TEMP/anchors-changed"', text)
        self.assertIn(r'$1 == "A" && $2 ~ /^ledger\/anchors\/[0-9][0-9][0-9][0-9][0-9][0-9][0-9]*\.root(\.ots)?$/ { next }',
                      text)
        self.assertNotIn(r'$1 == "M" && $2 ~ /^ledger\/anchors', text)          # a merged anchor is never changed
        self.assertNotIn('($1 == "A" || $1 == "M")', text)

    def test_a_reason_is_required_of_the_pull_request_that_adds_its_correction(self):
        c = lodge()
        f = freeze(c, "ada")
        root = copy_governed(tmpdir(self) / "tree")
        (root / "ledger" / "reasons").mkdir(parents=True)
        st = c.state()
        missing = f"correction {f}: ledger/reasons/{REASON}.md is missing"
        self.assertIn(missing, govern.check_tree(st, root, c.entries, since=f)[0])              # its own pull request
        self.assertEqual(govern.check_tree(st, root, c.entries, since=f + 1), [])               # a later one
        self.assertEqual(govern.check_tree(st, root, c.entries), [])                            # the audit
        self.assertIn(missing, govern.tree_warnings(st, root, c.entries)[0])
        (root / "ledger" / "reasons" / f"{REASON}.md").write_bytes(REASON_TEXT + b"changed")
        self.assertIn("which is not its name", govern.check_tree(st, root, c.entries)[0])       # altered: always unlawful

    def test_a_free_url_has_at_most_300_characters(self):
        c = founded()
        c.add("work", "ada", {"ref": "https://" + "a" * 300})    # 300 characters after the scheme
        c.add("work", "carol", {"ref": "https://" + "a" * 301})
        c.refused(self, "work needs an http.s. URL")
        self.assertEqual(c.state().seq, 1)

    def test_the_canonical_branch_is_read_by_its_full_name(self):
        """Without this rule, a tag named `origin/main` would shadow the branch in `git ls-tree origin/main`."""
        calls = []

        def git(*args):
            calls.append(args)
            return mock.Mock(returncode=1, stdout="")
        with mock.patch.object(actions, "canonical_remote", return_value="origin"), mock.patch.object(actions, "_git", git):
            self.assertIsNone(actions.canonical_ledger())
        self.assertEqual(calls, [("ls-tree", "-r", "refs/remotes/origin/main", "ledger/entries/")])
        node = (canon.ROOT / "node" / "witness.py").read_text(encoding="utf-8")
        self.assertIn('MAIN = "refs/remotes/origin/main"', node)
        self.assertNotIn('"origin/main"', node)


# ---------------------------------------------------------------- the term, and recusal ----

class Term(unittest.TestCase):
    def test_a_genesis_custodian_key_ends_seven_years_after_the_genesis(self):
        self.assertEqual(ledger.CUSTODIAN_TERM_DAYS, 2555)
        c = lodge()
        for _ in range(14):
            c.add("custodian_alive", "warden", {}, days=180)
        st = c.state()
        w = st.custodians["warden"]
        self.assertEqual((w.since, st.custodian_end(w)), (T0, T0 + 2555 * DAY + SECOND))
        self.assertEqual((st.custodian_status(w, T0 + 2555 * DAY), st.custodian_status(w, T0 + 2555 * DAY + SECOND)),
                         ("live", "lapsed"))
        c.now = T0 + 2555 * DAY
        c.add("custodian_alive", "warden", {})
        c.add("custodian_alive", "warden", {}, days=2)
        c.refused(self, "the custodian key of warden is lapsed and signs nothing")

    def test_no_correction_touches_a_ballot_the_sunset_counts(self):
        c = quarry()
        open_ballot(c, "w", "ada", "witness", witness_subject(c, "node2"))
        initiate(c, "bob")
        advance(c, "bob", 2)
        c.exam("bob", 3, days=61)
        open_ballot(c, "adv3", "bob", "advancement", {"member": "bob", "degree": 3})
        recusal = ("recusal: a ballot that adds a witness, or that advances a member to the 3rd degree, is never stayed, "
                   "voided or undone by a correction")
        for bid in ("w", "adv3"):
            for act, target in (("stay", {"ballot": bid}), ("void_ballot", {"id": bid}), ("undo_ballot", {"id": bid})):
                correct(c, act, target)
                c.refused(self, recusal if (act, bid) != ("undo_ballot", "w") else "only an admission or an advancement is "
                                                                                     "undone by a correction")
        self.assertEqual(ledger.UNDO_KINDS, ("admission", "advancement"))
        correct(c, "undo_ballot", {"id": "adv-bob-2"})            # an advancement to another degree is undone as before
        self.assertEqual(c.state().corrections[c.state().seq].act, "undo_ballot")


# ---------------------------------------------------------------- notes, allowances, undone admissions, returns, departures and closing ----

class Notes(unittest.TestCase):
    def test_a_note_takes_the_ground_moderation_and_nothing_else_does(self):
        c = lodge()
        note = {"action": "hide", "target": "discussion/42", "rule": "ROOMS.md#5"}
        for ground in ("protocol_defect", "key_compromised", "identity_fraud", "attack_in_progress"):
            correct(c, "note", note, ground if ground != "protocol_defect" else "identity_fraud")
            c.refused(self, "note takes one ground only: moderation")
        correct(c, "freeze_key", {"login": "ada"}, "moderation")
        c.refused(self, "freeze_key takes one ground only: key_compromised")
        correct(c, "hold_room", {"login": "ada"}, "moderation")
        c.refused(self, "the ground moderation is the ground of a note, and of no other act")
        seq = correct(c, "note", note, "moderation")
        st = c.state()
        self.assertEqual((st.corrections, st.notes), ({}, [{"seq": seq, "by": "warden", **note, "reason_sha256": REASON,
                                                            "time": c.now}]))

    def test_notes_are_no_corrections_and_the_state_keeps_the_newest(self):
        c = lodge()
        seq = correct(c, "note", {"action": "hide", "target": "t", "rule": "r"})
        for typ, by in (("correction_object", "ada"), ("correction_withdraw", "warden"), ("correction_cosign", "warden"),
                        ("correction_apply", "warden")):
            c.add(typ, by, {"seq": seq})
            c.refused(self, "no such correction")
        self.assertEqual(ledger.NOTES_KEPT, 200)
        st = c.state()
        st.notes = [dict(st.notes[0], seq=i) for i in range(ledger.NOTES_KEPT)]
        body = {"act": "note", "target": {"action": "hide", "target": "t", "rule": "r"}, "ground": "moderation",
                "reason_sha256": REASON}
        ledger._correction(st, {}, c.now + DAY, 999, "warden", body)
        self.assertEqual((len(st.notes), st.notes[0]["seq"], st.notes[-1]["seq"]), (200, 1, 999))

    def test_a_note_uses_no_part_of_the_allowance(self):
        c = lodge()
        for i in range(10):
            correct(c, "note", {"action": "hide", "target": f"t{i}", "rule": "r"})
        correct(c, "note", {"action": "hide", "target": "t10", "rule": "r"})
        c.refused(self, "at most 10 notes per custodian per UTC day")
        for login in ("ada", "carol"):
            correct(c, "hold_room", {"login": login})
        self.assertEqual(len(c.state().corrections), 2)


class Allowance(unittest.TestCase):
    def test_each_custodian_has_a_share_of_the_five(self):
        c = lodge(custodians=(("c1", "hiram"), ("c2", "ada"), ("c3", "carol")), founders=SEVEN, custodian_threshold=2)
        for login in ("dan", "eve"):
            correct(c, "hold_room", {"login": login}, by="c1")
        correct(c, "hold_room", {"login": "fay"}, by="c1")
        c.refused(self, "at most 2 corrections per custodian in any 30 days while 3 custodian key.s. are live")
        for login in ("fay", "gus"):
            correct(c, "hold_room", {"login": login}, by="c2")
        correct(c, "hold_room", {"login": "hiram"}, by="c3")     # the fifth of all together
        correct(c, "halt", {}, "attack_in_progress", by="c3")
        c.refused(self, "at most 5 corrections in any 30 days, all custodians together")
        c.add("custodian_revoke", "c3", {"name": "c3"}, key_of="c3-revoke")
        c.now += 90 * DAY                                        # past the window, and past the rest between holds
        for login in ("dan", "eve", "fay"):                      # two keys live: a share of three
            correct(c, "hold_room", {"login": login}, by="c1")
        correct(c, "hold_room", {"login": "gus"}, by="c1")
        c.refused(self, "at most 3 corrections per custodian in any 30 days while 2 custodian key.s. are live")

    def test_an_act_voided_by_objection_is_not_posted_again_for_ninety_days(self):
        c = lodge()
        f = correct(c, "hold_room", {"login": "ada"})
        objection(c, f, "carol", days=1)
        voided = c.now
        self.assertEqual(c.state().corrections[f].void, voided)
        correct(c, "hold_room", {"login": "ada"}, days=1)
        c.refused(self, "ada was held less than 90 days ago")    # a voided hold still began a rest, as a voided freeze
        correct(c, "hold_room", {"login": "carol"})              # another target is not held
        c.now = voided + 90 * DAY - SECOND
        correct(c, "hold_room", {"login": "ada"})
        c.refused(self, "was voided by objections less than 90 days ago")
        c.now += SECOND
        correct(c, "hold_room", {"login": "ada"})
        self.assertEqual(len(c.state().corrections), 3)


class UndoneAdmissions(unittest.TestCase):
    def undone(self):
        c = quarry()
        initiate(c, "alice")
        seq = undo(c, "adm-alice", days=1)
        return c, seq

    def test_an_undo_waits_for_an_open_sanction_ballot_on_that_member(self):
        """Without this rule, a custodian could turn a pending expel_for_fraud into `voided`: no ban, no wait."""
        c, seq = self.undone()
        sanction(c, "fraud", "alice", "eve", "expel_for_fraud")
        apply_(c, seq, days=14)
        c.refused(self, "the undo of ballot adm-alice is not applied while a sanction ballot on alice is open .ballot fraud.: "
                        "the members decide first")
        self.assertEqual(c.state().members["alice"].status, "active")

    def test_a_voided_record_is_still_expelled_for_fraud_before_ninety_days_have_passed(self):
        c, seq = self.undone()
        apply_(c, seq, days=14)
        at = c.now
        for measure in ("admonish", "suspend", "expel", "reinstate"):
            sanction(c, "s", "alice", "eve", measure)
            c.refused(self, "no such member")
        d = fork(c)
        d.now = at + 90 * DAY                               # the wait to return is over: so is the fraud window
        sanction(d, "late", "alice", "eve", "expel_for_fraud")
        d.refused(self, "the admission of alice was undone 90 days ago or more .a voided record is expelled for fraud "
                        "only by a ballot opened before 90 days have passed since the undo; from then on the login may "
                        "be invited again.")
        c.now = at + 90 * DAY - SECOND
        sanction(c, "fraud", "alice", "eve", "expel_for_fraud")
        run_to_end(c, "fraud", {x: "yes" for x in ("hiram", "ada", "carol", "dan")})
        st = c.state()
        m = st.members["alice"]
        self.assertEqual((st.ballots["fraud"].result, m.status, m.fraud_history), ("passed", "expelled", (c.now,)))
        self.assertEqual({st.members[s].sponsor_ban_until for s in m.sponsors}, {c.now + 730 * DAY})

    def test_a_voided_login_waits_ninety_days_before_a_new_invitation(self):
        c, seq = self.undone()
        apply_(c, seq, days=14)
        at = c.now
        c.now = at + 90 * DAY - SECOND
        invite(c, "alice", by="dan")
        c.refused(self, "alice is already a member .a departed member, or one whose admission was undone, may be invited "
                        "again once 90 days have passed")
        c.now += SECOND
        invite(c, "alice", by="dan")
        self.assertTrue(c.state().invited("alice", c.now))


class Returning(unittest.TestCase):
    def readmit(self, old: Member, github_id: int):
        now = T0 + 500 * DAY
        st = hand_state(old, *(mk(f) for f in FOUNDERS))
        st.petitions[old.login] = {"key": fake_key("new"), "vouches": ["hiram", "ada"], "time": now - 20 * DAY,
                                   "github_id": github_id}
        st.ballots["re"] = Ballot("re", "admission", {"candidate": old.login}, frozenset(FOUNDERS), now - 2 * DAY,
                                  now - DAY, "hiram", reveals={f: "yes" for f in FOUNDERS}, opened=now - 12 * DAY,
                                  frozen={"key": fake_key("new"), "vouches": ["hiram", "ada"], "github_id": github_id})
        ledger._ballot_close(st, {}, now, 9, "hiram", {"id": "re"})
        return st.members[old.login], now

    def test_a_login_that_returns_under_another_account_inherits_nothing(self):
        ban = T0 + 900 * DAY
        old = mk("vet", 5, status="departed", status_since=T0 + 100 * DAY, sponsor_ban_until=ban, github_id=7,
                 fraud_history=(T0 + 50 * DAY,), past_seats=1, founder=True, suspended_until=T0 + 600 * DAY)
        same, now = self.readmit(copy.deepcopy(old), 7)
        self.assertEqual((same.founder, same.past_seats, same.sponsor_ban_until, same.fraud_history),
                         (True, 1, ban, (T0 + 50 * DAY,)))
        other, _ = self.readmit(copy.deepcopy(old), 8)
        self.assertEqual((other.founder, other.past_seats, other.sponsor_ban_until, other.fraud_history, other.status,
                          other.suspended_until, other.github_id), (False, 0, None, (), "active", None, 8))

    def test_a_suspension_still_running_is_carried_into_the_new_membership(self):
        until = T0 + 600 * DAY
        old = mk("vet", 5, status="departed", status_since=T0 + 300 * DAY, suspended_until=until, github_id=7)
        m, now = self.readmit(old, 7)
        self.assertEqual((m.status, m.suspended_until, m.is_active(now), m.is_active(until)), ("suspended", until, False, True))
        served = mk("vet", 5, status="departed", status_since=T0 + 300 * DAY, suspended_until=T0 + 400 * DAY, github_id=7)
        m, now = self.readmit(served, 7)
        self.assertEqual((m.status, m.suspended_until), ("active", None))

    def test_a_suspended_member_who_leaves_and_returns_is_still_suspended(self):
        c = lodge(founders=SEVEN)
        initiate(c, "bob")
        sanction(c, "s", "bob", "ada", "suspend")
        c.vote("s", {x: "yes" for x in ("hiram", "ada", "carol")})
        until = c.state().members["bob"].suspended_until
        c.add("depart", "bob", {})
        invite(c, "bob", days=90)
        c.add("petition", "bob", {"key": c.key("bob"), "declaration_sha256": DECL})
        c.add("vouch", "ada", {"candidate": "bob"})
        open_ballot(c, "back", "hiram", "admission", {"candidate": "bob"})
        c.vote("back", {x: "yes" for x in ("hiram", "ada", "carol")})
        m = c.state().members["bob"]
        self.assertEqual((m.status, m.suspended_until, m.degree), ("suspended", until, 1))
        c.add("work", "bob", {"ref": URL})
        c.refused(self, "bob is not an active member")


class FrozenDeparture(unittest.TestCase):
    def test_a_departure_signed_with_a_frozen_key_is_reversed_by_the_recovery_of_that_key(self):
        """A stolen (frozen) key signed `depart` and ended the membership for good; recovery was then refused."""
        c = lodge(founders=SEVEN)
        freeze(c, "ada")
        c.add("depart", "ada", {}, days=1)                       # whoever holds the old key
        st = c.state()
        self.assertEqual((st.members["ada"].status, st.members["ada"].left), ("departed", {"status": "active"}))
        ask(c, "ada", days=1)                                    # the member, with the new key, while the freeze runs
        co(c, "ada", "carol")
        co(c, "ada", "dan")
        finish(c, "ada", days=21)
        m = c.state().members["ada"]
        self.assertEqual((m.status, m.left, m.key, m.status_since), ("active", None, c.key("ada-new"), None))
        c.add("work", "ada", {"ref": URL}, key_of="ada-new")
        c.add("depart", "ada", {}, key_of="ada-new")             # Landmark VII: the member leaves again
        self.assertEqual((c.state().members["ada"].status, c.state().members["ada"].left),
                         ("departed", {"status": "active"}))

    def test_a_departure_with_a_key_that_is_not_frozen_stands_after_thirty_days(self):
        c = lodge(founders=SEVEN)
        c.add("depart", "ada", {})
        self.assertEqual(c.state().members["ada"].left, {"status": "active"})
        freeze(c, "ada")
        c.refused(self, "no such member")
        ask(c, "ada", days=30 + 1 / 86400)
        c.refused(self, "ada departed more than 30 days ago")

    def test_the_departure_stands_when_no_recovery_completes(self):
        c = lodge(founders=SEVEN)
        freeze(c, "ada")
        c.add("depart", "ada", {})
        ask(c, "ada", days=1)
        stop(c, "ada", days=1)                                   # the old key, still the member's, stops it
        st = c.state()
        self.assertEqual((st.members["ada"].status, st.recovery_status(st.recoveries["ada"], c.now)), ("departed", "objected"))
        d = lodge(founders=SEVEN)
        freeze(d, "ada")
        d.add("depart", "ada", {})
        ask(d, "ada", days=31)                                   # more than 30 days after the departure
        d.refused(self, "ada departed more than 30 days ago")

    def test_a_departure_during_a_recovery_asked_without_a_freeze_is_reversed_too(self):
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, SEVEN))
        ask(c, "ada", days=1)
        c.add("depart", "ada", {})                               # the holder of the old key answers the request by leaving
        self.assertEqual(c.state().members["ada"].left, {"status": "active"})
        for who in ("carol", "dan", "eve"):
            co(c, "ada", who)
        finish(c, "ada", days=30)
        self.assertEqual(c.state().members["ada"].status, "active")


class Closing(unittest.TestCase):
    def test_a_ballot_that_misses_the_quorum_lapses_and_nobody_is_penalized(self):
        """The quorum trap: with three electors one absent elector failed an advancement and cost 90 days."""
        c = founded()
        initiate(c, "alice")
        c.exam("alice", 2, days=31)
        subject = {"member": "alice", "degree": 2}
        open_ballot(c, "adv1", "alice", "advancement", subject)
        b = run_to_end(c, "adv1", {"hiram": "yes", "ada": "yes"})        # carol is absent: 2 of 3, and the quorum is 3
        st = c.state()
        ex = st.exams[("alice", 2)]
        self.assertEqual((b.result, ex.consumed, ex.ballot_failed, ex.passed()), ("lapsed", False, False, True))
        open_ballot(c, "adv2", "alice", "advancement", subject)          # at once, on the same exam
        run_to_end(c, "adv2", {f: "yes" for f in FOUNDERS})
        self.assertEqual(c.state().members["alice"].degree, 2)
        self.assertTrue(ledger.quorate(3, 3))
        self.assertFalse(ledger.quorate(2, 3))
        self.assertFalse(ledger.quorate(0, 0))

    def test_a_ballot_closes_as_soon_as_every_elector_has_revealed(self):
        c = founded()
        amendment(c, "am", commit_days=30, reveal_days=14)
        for f in FOUNDERS:
            commit(c, "am", f)
        b = c.state().ballots["am"]
        c.now = b.commit_until + REVEAL_GAP
        reveal(c, "am", "hiram")
        reveal(c, "am", "ada")
        c.add("ballot_close", "carol", {"id": "am"})
        c.refused(self, "ballot still open")
        self.assertEqual(ledger.due_actions(c.state(), c.now), [])
        reveal(c, "am", "carol")
        self.assertEqual(ledger.due_actions(c.state(), c.now), [("ballot_close", {"id": "am"})])
        c.add("ballot_close", "carol", {"id": "am"})
        st = c.state()
        self.assertEqual((st.ballots["am"].result, st.ballots["am"].closed), ("passed", b.commit_until + REVEAL_GAP))

    def test_the_reveal_window_includes_its_first_and_its_last_second(self):
        c = founded()
        amendment(c, "am")
        commit(c, "am", "ada")
        commit(c, "am", "carol")
        b = c.state().ballots["am"]
        opens = b.commit_until + REVEAL_GAP
        c.now = opens - SECOND
        reveal(c, "am", "ada")
        c.refused(self, f"not in the reveal window .{iso(opens)} to {iso(b.reveal_until)}, both included.")
        c.now = opens
        reveal(c, "am", "ada")
        c.now = b.reveal_until
        reveal(c, "am", "carol")
        c.now += SECOND
        reveal(c, "am", "hiram")
        c.refused(self, "not in the reveal window")
        self.assertEqual(c.state().ballots["am"].reveals, {"ada": "yes", "carol": "yes"})


class Commands(OmHarness):
    """The command line of the rules above: what a new rule needs a person to be able to do."""

    def proof(self, what, name, *extra):
        out = self.tmp / f"{name}.proof"
        self.c.key(name)
        r = self.run_om("proof", what, name, "--key", str(self.c.keys[name][0]), "--out", str(out), *extra, env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out

    def test_a_witness_is_proposed_with_the_proof_its_key_signed(self):
        out = self.proof("witness", "node2")
        key = self.c.key("node2")
        self.assertTrue(crypto.signature_valid(witness_message("node2", key), out.read_text(encoding="utf-8"), key))
        r = self.run_om("open", "witness", "node2", "--witness-key", key, "--ledger", str(self.led), "--time", self.T(1),
                        "--json", env=self.env("ada"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("--witness-proof FILE", r.stdout)
        d = self.draft("open", "witness", "node2", "--witness-key", key, "--witness-proof", str(out), "--id", "w", who="ada", day=1)
        self.assertEqual(d["entry"]["body"]["subject"], {"action": "add", "name": "node2", "key": key,
                                                         "proof": out.read_text(encoding="utf-8")})
        self.approve(d["digest"], who="ada")
        st = replay(ledger.load(self.led))                       # real signatures: the proof is checked by the ledger
        self.assertEqual((st.ballots["w"].opened_by, ledger.point(key) in st.known_keys), ("ada", True))
        other = self.proof("witness", "node3")                   # a proof made for another name proves nothing here
        bad = self.run_om("open", "witness", "node9", "--witness-key", self.c.key("node3"), "--witness-proof", str(other),
                          "--ledger", str(self.led), "--time", self.T(2), "--json", env=self.env("ada"))
        self.assertEqual(bad.returncode, 3, bad.stdout + bad.stderr)        # a draft checks no signature…
        refused = self.run_om("approve", json.loads(bad.stdout)["digest"][:16], "--no-submit", env=self.env("ada"))
        self.assertIn("bad witness proof", refused.stdout)                    # …the approval does

    def test_a_genesis_carries_the_proofs_of_its_cofounders_and_witnesses(self):
        led = self.tmp / "new"
        ada = self.proof("founder", "ada", "--github-id", str(gid("ada")))     # made by ada, on her own machine
        self.c.key("tyler")                                                    # the witness key is here: it signs at approval
        r = self.run_om("genesis", "--ledger", str(led), "--json", "--github-id", str(gid("hiram")), "--time", self.T(0),
                        "--cofounder", f"ada:{self.c.keys['ada'][0]}.pub:{gid('ada')}", "--cofounder-proof", f"ada:{ada}",
                        "--witness", f"tyler:{self.c.keys['tyler'][0]}.pub", env=self.env())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("founder_github_id", r.stderr)                           # the founder is told to name the account
        body = json.loads(r.stdout)["entry"]["body"]
        self.assertEqual((body["founders"][1]["proof"], "proof" in body["founders"][0]), (ada.read_text(encoding="utf-8"), False))
        self.approve(json.loads(r.stdout)["digest"])
        st = replay(ledger.load(led))
        self.assertEqual((sorted(st.members), sorted(st.witnesses)), (["ada", "hiram"], ["tyler"]))

    def test_a_cofounder_without_a_proof_and_without_the_key_stops_the_approval(self):
        led = self.tmp / "new"
        pub = self.tmp / "elsewhere.pub"
        pub.write_text(self.c.key("ada") + "\n", encoding="utf-8")            # only the public half is here
        r = self.run_om("genesis", "--ledger", str(led), "--json", "--github-id", str(gid("hiram")), "--time", self.T(0),
                        "--cofounder", f"ada:{pub}:{gid('ada')}", env=self.env())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        no = self.run_om("approve", json.loads(r.stdout)["digest"][:16], "--no-submit", env=self.env())
        self.assertEqual(no.returncode, 1, no.stdout + no.stderr)
        self.assertIn("proof founder ada --key PATH --github-id N", no.stdout)
        self.assertFalse(led.exists() and any(led.iterdir()))

    def test_an_opposition_is_a_command(self):
        r = self.run_om("recover-oppose", "ada", "--ledger", str(self.led), "--time", self.T(1), "--json", env=self.env("carol"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no recovery of the key of ada is pending", r.stdout)


class DeadCode(unittest.TestCase):
    def test_the_core_holds_nothing_that_nothing_reads(self):
        self.assertFalse(hasattr(crypto, "_raw_key"))
        self.assertFalse(hasattr(ledger, "signer_key"))
        self.assertFalse(hasattr(State, "council"))
        self.assertFalse(hasattr(State, "cut_short"))
        self.assertFalse(hasattr(canon, "file_digest"))
        self.assertFalse(hasattr(canon, "canon_digest"))
        self.assertNotIn("old_key", ledger.Recovery.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
