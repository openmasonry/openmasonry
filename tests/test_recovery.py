"""Peer key recovery: a member whose key is lost or stolen takes a new one (SPEC sections 6.26 to 6.29).

It is not a correction. A custodian only freezes the key; the member asks with the NEW key, two Master
Builders co-sign, 21 days of notice run, and whoever holds the old key can stop it. Every test here uses
`Fast` (tests.test_strict): the "signature" of an entry is the public key that signed it, so the signer rule
is exercised without OpenSSH. One class checks real signatures with the pure-Python signer of
tests.test_signatures. Nothing touches the network.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from openmasonry import actions, crypto, identity, ledger
from openmasonry.__main__ import state_report
from openmasonry.ledger import Correction, Custodian, Exam, Invalid, Recovery, apply, iso, rekey_message, replay, signed_payload
from tests.test_custodian import (REASON, SEVEN, URL, commit, fork, freeze, halt, lodge, objection, open_ballot, reveal,
                                  withdraw)
from tests.test_protocol import T0, gid, initiate, salt_of
from tests.test_signatures import keyline, keypair, sign_entry
from tests.test_strict import DAY, SEC, Fast, by_key, fake_key, hand_state, mk

REPO = Path(__file__).resolve().parents[1]
FROZEN = (r"a frozen member may only depart, rekey, vote \(commit and reveal\), take part in an amendment ballot "
          "or the ballot that removes a custodian, or object to a recovery of their own key")


def ask(c, who="ada", new=None, days=0.0, key_of=None, proof=None):
    """`who` asks to recover their key. The entry is signed by the new key, named `<who>-new` unless given."""
    name = new or f"{who}-new"
    key = c.key(name)
    return c.add("rekey_recover", who, {"key": key, "proof": key if proof is None else proof}, days=days,
                 key_of=key_of or name)


def co(c, who, by, days=0.0):
    return c.add("rekey_cosign", by, {"login": who}, days=days)


def stop(c, who="ada", days=0.0, key_of=None):
    """The key the ledger holds for `who` (the old key) stops the recovery."""
    return c.add("rekey_object", who, {}, days=days, key_of=key_of)


def finish(c, who="ada", new=None, days=0.0, key_of=None):
    return c.add("rekey_recover_apply", who, {}, days=days, key_of=key_of or new or f"{who}-new")


def asked(cosigners=("carol", "dan")) -> Fast:
    """Seven founders, the custodian `warden` (linked to hiram). ada's key is frozen at T0, she asks for a new
    one a day later, and the given Master Builders co-sign at once."""
    c = lodge(founders=SEVEN)
    freeze(c, "ada")
    ask(c, days=1)
    for who in cosigners:
        co(c, "ada", who)
    return c


class Recover(unittest.TestCase):
    def test_a_lost_key_is_replaced_after_the_freeze_two_masters_and_the_notice(self):
        c = lodge(founders=SEVEN)
        f = freeze(c, "ada", days=1)
        ask(c, days=1)                                       # at T0 + 2 d, signed by the new key
        old, new = fake_key("ada"), fake_key("ada-new")
        st = c.state()
        r = st.recoveries["ada"]
        self.assertEqual((r.login, r.key, r.seq, r.time, r.freeze, r.cosigners, r.objected, r.applied, r.notice, r.final),
                         ("ada", new, 2, T0 + 2 * DAY, f, (), None, None, None, False))
        self.assertEqual((st.recovery_status(r, c.now), st.members["ada"].key, st.recovering("ada", c.now)), ("pending", old, r))
        self.assertIn(ledger.point(new), st.known_keys)
        self.assertEqual(st.key_holders(new, c.now), [("recovery", "ada")])
        co(c, "ada", "carol", days=1)
        co(c, "ada", "dan")
        self.assertEqual(c.state().recoveries["ada"].cosigners, ("carol", "dan"))
        c.now = T0 + 23 * DAY - SEC
        finish(c)
        c.refused(self, r"the recovery of the key of ada is under notice until 2027-01-24T00:00:00Z \(21 days after its "
                        r"notice began\)")
        c.now = T0 + 23 * DAY                                # the first second
        self.assertEqual(c.state().recovery_status(c.state().recoveries["ada"], c.now), "ready")
        finish(c)
        st = c.state()
        m, r, k = st.members["ada"], st.recoveries["ada"], st.corrections[f]
        self.assertEqual((m.key, m.last_rekey, r.applied, k.released, st.correction_status(k, c.now), st.span(k)[1]),
                         (new, c.now, c.now, c.now, "released", c.now))
        self.assertEqual((st.frozen("ada", c.now), st.recovering("ada", c.now), st.recovery_status(r, c.now)),
                         (None, None, "applied"))
        self.assertEqual(st.key_holders(new, c.now), [("member", "ada")])
        c.add("work", "ada", {"ref": URL})                   # still signed by the old key
        c.refused(self, "bad signature")
        c.keys["ada"] = (None, new)
        c.add("work", "ada", {"ref": URL})                   # in the same second: the new key signs, and nothing is frozen
        self.assertEqual((ledger.RECOVER_NOTICE_DAYS, ledger.RECOVER_EXPIRY_DAYS, ledger.RECOVER_INTERVAL_DAYS,
                          ledger.RECOVER_COSIGNERS), (21, 60, 90, 2))

    def test_without_a_freeze_the_recovery_is_an_open_one(self):
        """a recovery never needs a custodian. Without a freeze in force (none was posted, it was withdrawn, or it
        ran its time) the request is an open recovery: three co-signers, 30 days, and the Masters may oppose it."""
        for prepare in (lambda c: None,
                        lambda c: withdraw(c, freeze(c, "ada"), days=1),
                        lambda c: (freeze(c, "ada"), setattr(c, "now", c.now + 31 * DAY))):
            c = lodge(founders=SEVEN)
            prepare(c)
            ask(c)
            st = c.state()
            r = st.recoveries["ada"]
            self.assertEqual((r.freeze, st.recovery_status(r, c.now), ledger.cosigners_needed(st, r, c.now)),
                             (None, "requested", 3))

    def test_the_request_is_signed_by_the_new_key_and_by_no_other(self):
        c = lodge(founders=SEVEN)
        freeze(c, "ada")
        for signer in ("ada", "hiram", "warden"):            # the old key, another member, the custodian
            ask(c, key_of=signer)
            c.refused(self, "entry 2: bad signature")
        ask(c)
        self.assertEqual(c.state().seq, 2)
        self.assertEqual(ledger._signer(replay(c.entries[:2], verifier=by_key), c.entries[2], c.now)[0], fake_key("ada-new"))

    def test_who_may_ask(self):
        c = lodge(founders=SEVEN)
        c.add("depart", "carol", {})
        ask(c, "carol", days=30 + 1 / 86400)
        c.refused(self, r"carol departed more than 30 days ago")
        for who in ("nobody", "warden"):
            ask(c, who)
            c.refused(self, rf"{who} is not a member whose key can be recovered \(not a member, departed, expelled or voided\)")
            finish(c, who)
            c.refused(self, f"{who} is not a member whose key can be recovered")
        finish(c, "ada")
        c.refused(self, "no recovery of the key of ada is pending")

    def test_the_new_key_was_never_used_and_proves_itself(self):
        c = lodge(founders=SEVEN, witnesses=("tyler",))
        freeze(c, "ada")
        c.add("rekey_recover", "ada", {"key": "ssh-rsa AAAA", "proof": "x"}, key_of="ada-new")
        c.refused(self, "keys must be ssh-ed25519 or sk-ssh-ed25519")
        for holder in ("carol", "tyler", "warden", "warden-revoke"):
            ask(c, new=holder)
            c.refused(self, rf"this key is already used by {holder.split('-')[0]} \(one key per login")
        ask(c, new="ada")
        c.refused(self, "this is already your key")
        ask(c, proof="not-the-key")
        c.refused(self, r"bad proof: the new key must sign the rekey message \(login, old key, new key\)")
        seen = []

        def verifier(payload, sig, actor, key):
            seen.append((payload, sig, actor, key))
            return sig == key
        ask(c)
        replay(c.entries, verifier=verifier)
        new = fake_key("ada-new")
        self.assertEqual(seen[-2], (signed_payload(c.entries[-1]), new, "ada", new))            # the entry, by the new key
        self.assertEqual(seen[-1], (rekey_message("ada", fake_key("ada"), new), new, "ada", new))   # and the proof: login, old, new

    def test_a_key_the_ledger_ever_saw_is_never_the_new_key_of_a_recovery(self):
        c = lodge(founders=SEVEN)
        other = c.key("carol-2")
        c.add("rekey", "carol", {"key": other, "proof": other})
        c.keys["carol-old"], c.keys["carol"] = c.keys["carol"], (None, other)
        freeze(c, "ada")
        ask(c, new="carol-old")                              # a key carol replaced: held by nobody, but seen
        c.refused(self, r"this key was used in this ledger before \(a key that was ever registered here is never registered "
                        r"again\)")
        ask(c)
        c.add("rekey", "dan", {"key": fake_key("ada-new"), "proof": fake_key("ada-new")})
        c.refused(self, "this key is already used by ada")   # held by the recovery while it is under way

    def test_the_bodies_are_exact(self):
        c = asked()
        for typ, who, body, pattern in (
                ("rekey_recover", "carol", {"key": fake_key("x")}, "malformed rekey_recover entry: missing field 'proof'"),
                ("rekey_recover", "carol", {"key": fake_key("x"), "proof": "p", "login": "carol"},
                 "malformed rekey_recover entry: unknown field 'login'"),
                ("rekey_cosign", "eve", {}, "malformed rekey_cosign entry: missing field 'login'"),
                ("rekey_cosign", "eve", {"login": 7}, "malformed rekey_cosign entry: field 'login' must be a string"),
                ("rekey_object", "ada", {"login": "ada"}, "malformed rekey_object entry: unknown field 'login'"),
                ("rekey_recover_apply", "ada", {"key": fake_key("ada-new")}, "malformed rekey_recover_apply entry: unknown field 'key'")):
            c.add(typ, who, body)
            c.refused(self, pattern)


class CoSign(unittest.TestCase):
    def test_two_distinct_master_builders_answer_for_it(self):
        c = lodge(founders=SEVEN)
        initiate(c, "alice")                                 # a member of the 1st degree
        start = c.now
        freeze(c, "ada")
        ask(c, days=1)
        for by, pattern in (("alice", "only Master Builders may co-sign a key recovery"),
                            ("ada", "the key of ada is frozen"), ("nobody", "nobody is not an active member"),
                            ("warden", "warden is not an active member")):
            co(c, "ada", by)
            c.refused(self, pattern)
        co(c, "carol", "dan")
        c.refused(self, "no recovery of the key of carol is pending")
        co(c, "ada", "carol")
        co(c, "ada", "carol")
        c.refused(self, "already co-signed the recovery of the key of ada")
        c.now = start + 22 * DAY
        finish(c)
        c.refused(self, "the recovery of the key of ada has 1 of the 2 co-signatures of active Master Builders it needs")
        co(c, "ada", "hiram")                                # the member the custodian is linked to is a Master like any other
        finish(c)
        self.assertEqual(c.state().members["ada"].key, fake_key("ada-new"))

    def test_a_member_never_co_signs_the_recovery_of_their_own_key(self):
        st = hand_state(*(mk(f) for f in SEVEN), seq=5, head="66" * 32, time=T0)
        st.recoveries["ada"] = Recovery("ada", fake_key("ada-new"), 3, T0, 2)
        with self.assertRaisesRegex(Invalid, "a member cannot co-sign the recovery of their own key"):
            ledger._rekey_cosign(st, {}, T0 + DAY, 6, "ada", {"login": "ada"})
        ledger._rekey_cosign(st, {}, T0 + DAY, 6, "carol", {"login": "ada"})
        self.assertEqual(st.recoveries["ada"].cosigners, ("carol",))

    def test_a_co_signer_who_is_no_longer_an_active_master_no_longer_counts(self):
        c = asked()
        c.add("depart", "dan", {}, days=5)
        c.now = T0 + 22 * DAY
        finish(c)
        c.refused(self, "has 1 of the 2 co-signatures of active Master Builders it needs")
        co(c, "ada", "eve")
        finish(c)
        self.assertEqual(c.state().recoveries["ada"].cosigners, ("carol", "dan", "eve"))

    def test_co_signing_is_an_act_of_the_master_and_the_recovery_credits_nobody_else(self):
        c = lodge(founders=SEVEN)
        freeze(c, "ada")
        before = copy.deepcopy(c.state().members["ada"].activity)
        ask(c, days=1)
        co(c, "ada", "carol", days=1)
        co(c, "ada", "dan")
        finish(c, days=21)
        st = c.state()
        self.assertEqual(st.members["ada"].activity, before)                  # neither the request nor its application
        self.assertEqual(st.members["carol"].activity[-1], T0 + 2 * DAY)
        d = asked()
        stop(d, days=1)
        self.assertEqual(d.state().members["ada"].activity, before)           # nor the objection of the old key


class OldKey(unittest.TestCase):
    def test_whoever_holds_the_old_key_can_stop_a_recovery_but_cannot_complete_one(self):
        c = asked()
        c.now = T0 + 22 * DAY                                # the notice is over, the two Masters have signed
        finish(c, key_of="ada")                              # …and the old key tries to take the new key's place
        c.refused(self, "bad signature")
        ask(c, new="thief")                                  # or to ask for a key of its own
        c.refused(self, r"a recovery of the key of ada is already pending \(entry 2\)")
        co(c, "ada", "ada")
        c.refused(self, "the key of ada is frozen")
        thief = fork(c)
        stop(thief)                                          # what it can do is stop it
        st = thief.state()
        r = st.recoveries["ada"]
        self.assertEqual((r.objected, r.applied, st.recovery_status(r, thief.now), st.members["ada"].key),
                         (thief.now, None, "objected", fake_key("ada")))
        finish(thief)
        thief.refused(self, "no recovery of the key of ada is pending")
        stop(thief)
        thief.refused(self, "no recovery of the key of ada is pending")
        finish(c)                                            # unopposed, the new key completes it
        self.assertEqual(c.state().members["ada"].key, fake_key("ada-new"))
        stop(c)                                              # the old key signs nothing any more
        c.refused(self, "bad signature")

    def test_after_an_objection_the_old_key_stays_frozen_for_the_rest_of_the_freeze_only(self):
        c = asked()
        stop(c, days=4)                                      # at T0 + 5 d
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the key of ada is frozen until 2027-01-31T00:00:00Z " + r"\(correction 1\): " + FROZEN)
        c.now = T0 + 30 * DAY - SEC
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the key of ada is frozen until 2027-01-31T00:00:00Z")
        c.now = T0 + 30 * DAY
        c.add("work", "ada", {"ref": URL})
        self.assertIsNone(c.state().recovering("ada", c.now))

    def test_no_new_recovery_for_ninety_days_after_an_objection(self):
        c = asked()                                          # frozen at T0, requested at T0 + 1 d
        stop(c, days=21)                                     # stopped at T0 + 22 d
        c.now = T0 + 90 * DAY
        freeze(c, "ada")                                     # the matter went to a new freeze
        ask(c, new="ada-3")
        c.refused(self, r"the last recovery of the key of ada was requested less than 90 days ago \(one request per member "
                        r"in 90 days\)")
        c.now = T0 + 112 * DAY - SEC
        ask(c, new="ada-3")
        c.refused(self, r"the old key of ada stopped a recovery less than 90 days ago \(the next request, 90 days after "
                        r"that, cannot be stopped by the old key and needs 3 co-signers, or as many other Master Builders as exist\)")
        c.now = T0 + 112 * DAY
        ask(c, new="ada-3")
        self.assertEqual(c.state().recoveries["ada"].key, fake_key("ada-3"))

    def test_one_request_per_member_in_ninety_days_and_never_the_same_new_key(self):
        c = asked(cosigners=())                              # requested at T0 + 1 d; nobody co-signs
        st = c.state()
        r = st.recoveries["ada"]
        # Its notice of 21 days has run, but a recovery that cannot be applied is never shown ready: it lacks the
        # co-signatures it needs.
        self.assertEqual([st.recovery_status(r, T0 + 31 * DAY - SEC)], ["pending"])
        # Open 30 days without a co-signature after a freeze, it needs one, and its notice of 45 days starts at
        # that moment (day 31) whatever was given: the key stays frozen, it may be applied from day 76 once that
        # one co-signature is given (until then it stays pending), and it lapses 60 days after the drop.
        self.assertEqual([st.recovery_status(r, T0 + d * DAY + s * SEC) for d, s in ((31, 0), (76, -1), (76, 0), (91, 0), (91, 1))],
                         ["pending", "pending", "pending", "pending", "expired"])
        self.assertEqual(st.recovery_notice_end(r, T0 + 76 * DAY), T0 + 76 * DAY)
        self.assertEqual((st.recovery_start(r, T0 + 31 * DAY), st.key_frozen("ada", T0 + 60 * DAY)), (T0 + 31 * DAY, True))
        c.now = T0 + 91 * DAY
        ask(c, new="ada-3")
        c.refused(self, "a recovery of the key of ada is already pending")
        c.now += SEC
        ask(c)
        c.refused(self, "this key was used in this ledger before")     # the key of the request that expired
        ask(c, new="ada-3")
        self.assertEqual(c.state().recoveries["ada"].seq, c.state().seq)

    def test_every_entry_of_a_recovery_is_accepted_during_a_halt(self):
        """a halt never holds back a member's new key (before, only the old key's objection went through)."""
        c = asked()
        halt(c, days=1)
        finish(c)
        c.refused(self, "is under notice until")              # refused for its notice, not for the halt
        co(c, "ada", "eve")
        stop(c)
        self.assertEqual((c.state().recoveries["ada"].objected, c.state().recoveries["ada"].cosigners),
                         (c.now, ("carol", "dan", "eve")))
        self.assertTrue(ledger.RECOVERY_TYPES | {"rekey_object", "rekey_cosign", "rekey_oppose"} <= ledger.HALT_ALLOWED)

    def test_a_member_who_left_with_a_key_that_was_not_frozen_may_recover_it_within_thirty_days(self):
        c = lodge(founders=SEVEN)
        c.add("depart", "ada", {}, days=1)                   # Landmark VII, with a key nobody froze
        stop(c)
        c.refused(self, "no recovery of the key of ada is pending")
        d = fork(c)
        ask(d, days=30 + 1 / 86400)
        d.refused(self, "ada departed more than 30 days ago")
        ask(c, days=30)                                      # the last second of the 30 days
        st = c.state()
        self.assertEqual(st.recovery_status(st.recoveries["ada"], c.now), "requested")

    def test_a_departure_signed_with_the_frozen_key_does_not_end_the_recovery(self):
        c = asked()
        c.add("depart", "ada", {}, days=1)                   # with the old key, which may be in other hands
        d = fork(c)
        stop(d)                                              # the old key still stops the recovery, and then the departure stands
        self.assertEqual((d.state().recoveries["ada"].objected, d.state().members["ada"].status), (d.now, "departed"))
        finish(c, days=21)                                   # completed: the departure is reversed
        self.assertEqual((c.state().members["ada"].status, c.state().members["ada"].key), ("active", fake_key("ada-new")))


class Pending(unittest.TestCase):
    def test_the_key_stays_frozen_while_the_recovery_is_pending_also_after_the_freeze_has_run_out(self):
        c = lodge(founders=SEVEN)
        f = freeze(c, "ada")
        ask(c, days=29)                                      # asked on the last day of the freeze
        c.now = T0 + 35 * DAY
        st = c.state()
        self.assertEqual((st.frozen("ada", c.now), st.key_frozen("ada", c.now), st.correction_status(st.corrections[f], c.now)),
                         (None, True, "lapsed"))
        c.add("work", "ada", {"ref": URL})
        c.refused(self, r"the key of ada stays frozen while its recovery is pending \(entry 2, until 2027-03-31T00:00:00Z at "
                        r"the latest\): " + FROZEN)
        freeze(c, "carol")                                   # a key held by a recovery counts in the cap on freezes
        c.refused(self, r"too many keys are frozen at once: at most 1 ")
        rekeyed = fork(c)
        other = rekeyed.key("ada-other")
        rekeyed.add("rekey", "ada", {"key": other, "proof": other})          # the old key may still be replaced by its holder
        self.assertEqual(rekeyed.state().members["ada"].key, other)
        c.now = T0 + 59 * DAY - SEC                          # the last second before 30 days without a co-signature
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the key of ada stays frozen while its recovery is pending")
        c.now += SEC                                         # it now needs one co-signature; its notice of 45 days
        st = c.state()                                       # starts here, and the key stays frozen meanwhile
        r = st.recoveries["ada"]
        self.assertEqual((st.recovery_status(r, c.now), st.key_frozen("ada", c.now), st.recovery_start(r, c.now),
                          st.recovery_notice_end(r, c.now)), ("pending", True, c.now, c.now + 45 * DAY))
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the key of ada stays frozen while its recovery is pending")
        c.now = T0 + 119 * DAY                               # the last second: 60 days after the drop
        st = c.state()                                       # past its notice, but short of its one co-signature
        self.assertEqual((st.recovery_status(st.recoveries["ada"], c.now), st.key_frozen("ada", c.now)), ("pending", True))
        c.now += SEC
        st = c.state()
        self.assertEqual((st.recovery_status(st.recoveries["ada"], c.now), st.key_frozen("ada", c.now)), ("expired", False))
        finish(c)
        c.refused(self, r"the recovery of the key of ada expired at 2027-04-30T00:00:00Z \(60 days after its notice began\)")
        c.add("work", "ada", {"ref": URL})                   # nobody completed it: the old key signs again
        freeze(c, "carol")

    def test_a_recovery_completes_after_the_freeze_ran_out_and_within_sixty_days(self):
        c = asked()                                          # requested at T0 + 1 d
        c.now = T0 + 61 * DAY                                # the last second
        finish(c)
        st = c.state()
        self.assertEqual((st.members["ada"].key, st.corrections[1].released, st.correction_status(st.corrections[1], c.now)),
                         (fake_key("ada-new"), None, "lapsed"))                # the freeze had ended by itself

    def test_it_ends_when_the_freeze_it_followed_is_withdrawn_or_voided(self):
        for end in ("withdrawn", "voided"):
            c = asked()
            if end == "withdrawn":
                withdraw(c, 1, days=2)
            else:
                objection(c, 1, "carol", days=2)             # E = 5: one objection voids the freeze
            st = c.state()
            self.assertEqual((st.recovery_status(st.recoveries["ada"], c.now), st.key_frozen("ada", c.now)), ("canceled", False))
            self.assertEqual(st.recovery_status(st.recoveries["ada"], c.now - SEC), "pending")      # earlier answers stand
            c.add("work", "ada", {"ref": URL})               # the old key signs at once
            co(c, "ada", "eve")
            c.refused(self, "no recovery of the key of ada is pending")
            finish(c, days=21)
            c.refused(self, r"the recovery of the key of ada ended when the freeze it followed \(correction 1\) was withdrawn "
                            "or voided")

    def test_objecting_to_the_freeze_after_it_ran_out_still_stops_the_recovery(self):
        c = asked(cosigners=("carol", "dan"))
        c.now = T0 + 40 * DAY                                # the freeze ran its 30 days; the recovery is still under way
        self.assertTrue(c.state().key_frozen("ada", c.now))
        objection(c, 1, "eve")
        st = c.state()
        self.assertEqual((st.corrections[1].void, st.recovery_status(st.recoveries["ada"], c.now)), (c.now, "canceled"))
        finish(c)
        c.refused(self, "ended when the freeze it followed")

    def test_it_outlives_the_custodian_who_froze_the_key(self):
        c = asked()
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke", days=3)
        st = c.state()
        self.assertEqual((st.frozen("ada", c.now), st.key_frozen("ada", c.now), st.correction_status(st.corrections[1], c.now)),
                         (None, True, "ended"))
        finish(c, days=18)
        self.assertEqual(c.state().members["ada"].key, fake_key("ada-new"))

    def test_the_earlier_commitments_of_the_member_are_revealed_with_the_new_key(self):
        c = lodge(founders=SEVEN)
        open_ballot(c, "s", "dan", "amendment", {"path": "docs/x.md", "new_sha256": "ab" * 32}, commit_days=30)
        commit(c, "s", "ada", "no")
        freeze(c, "ada", days=1)
        ask(c, days=1)
        co(c, "ada", "carol")
        co(c, "ada", "dan")
        finish(c, days=21)
        c.keys["ada-old"], c.keys["ada"] = c.keys["ada"], (None, fake_key("ada-new"))
        c.now = T0 + 30 * DAY + ledger.REVEAL_GAP + SEC
        c.add("ballot_reveal", "ada", {"id": "s", "vote": "no", "salt": salt_of("ada")}, key_of="ada-old")
        c.refused(self, "bad signature")
        reveal(c, "s", "ada", "no")
        self.assertEqual(c.state().ballots["s"].reveals, {"ada": "no"})

    def test_a_recovery_never_reaches_a_later_membership_of_the_login(self):
        """Hand-built: the admission of the member was undone and the login admitted anew within the 60 days."""
        st = hand_state(mk("ada", 1, T0 + 30 * DAY), *(mk(f) for f in ("hiram", "carol", "dan")), seq=9, head="77" * 32,
                        time=T0 + 30 * DAY)
        st.recoveries["ada"] = Recovery("ada", fake_key("ada-new"), 3, T0 + 5 * DAY, 2, admitted=iso(T0),
                                        cosigners=("carol", "dan"))
        self.assertEqual([st.recovery_status(st.recoveries["ada"], T0 + d * DAY) for d in (6, 29, 30, 40)],
                         ["pending", "ready", "canceled", "canceled"])
        self.assertFalse(st.key_frozen("ada", T0 + 30 * DAY))
        e = {"seq": 10, "prev": st.head, "time": iso(T0 + 31 * DAY), "type": "rekey_recover_apply", "actor": "ada", "body": {},
             "sig": fake_key("ada-new")}
        with self.assertRaisesRegex(Invalid, "the recovery of the key of ada was asked for an earlier membership of the login, "
                                             "and ended with it"):
            apply(copy.deepcopy(st), e, by_key)
        st.recoveries["ada"].admitted = iso(T0 + 30 * DAY)   # the same membership: it completes
        apply(st, e, by_key)
        self.assertEqual(st.members["ada"].key, fake_key("ada-new"))
        c = asked()
        self.assertEqual(c.state().recoveries["ada"].admitted, iso(T0))

    def test_an_examiner_whose_key_is_under_recovery_is_passed_over(self):
        now = T0 + 40 * DAY
        st = hand_state(mk("dave", 1), *(mk(f) for f in SEVEN), seq=3, head="33" * 32, time=now,
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "hiram", now)})
        st.corrections[1] = Correction(1, "warden", "freeze_key", {"login": "carol"}, "key_compromised", REASON, T0,
                                       until=T0 + 30 * DAY, subject="carol")
        st.recoveries["carol"] = Recovery("carol", fake_key("carol-new"), 2, T0 + 20 * DAY, 1)
        ex = Exam("dave", 2, ("ada", "eve"), opened=now, k=2, ranking=("ada", "eve", "carol", "dan"), pool=("ada", "carol", "dan", "eve"))
        self.assertEqual((st.frozen("carol", now), st.key_frozen("carol", now)), (None, True))
        ledger._stand_aside(st, ex, "ada", now)
        self.assertEqual(ex.examiners, ("eve", "dan"))

    def test_the_replaced_key_waits_thirty_days_like_any_rekey(self):
        c = asked()
        finish(c, days=21)
        c.keys["ada"] = (None, fake_key("ada-new"))
        again = c.key("ada-again")
        c.add("rekey", "ada", {"key": again, "proof": again}, days=29)
        c.refused(self, "one rekey per member per 30 days")
        c.add("rekey", "ada", {"key": again, "proof": again}, days=1)
        self.assertEqual(c.state().members["ada"].key, again)


class RealSignatures(unittest.TestCase):
    """The recovery entries with `crypto.signature_valid`: the new key signs the request, its proof and the
    application; every other entry of the scratch ledger keeps its stand-in signature."""

    NEW, OTHER = b"7" * 32, b"8" * 32

    @staticmethod
    def verifier(payload, sig, actor, key):
        return sig == key or crypto.signature_valid(payload, sig, key)

    def chain(self):
        c = lodge(founders=SEVEN)
        freeze(c, "ada")
        return c, keyline(keypair(self.NEW)[2])

    def request(self, c, new, signer=None, proof_seed=None, proof_over=None):
        e = c.add("rekey_recover", "ada", {"key": new, "proof": sign_entry(
            proof_seed or self.NEW, proof_over or rekey_message("ada", fake_key("ada"), new))[1]}, days=1)
        e["sig"] = sign_entry(signer or self.NEW, signed_payload(e))[1]
        return e

    def test_the_new_key_signs_the_request_its_proof_and_the_application(self):
        c, new = self.chain()
        self.request(c, new)
        co(c, "ada", "carol")
        co(c, "ada", "dan")
        e = c.add("rekey_recover_apply", "ada", {}, days=21)
        e["sig"] = sign_entry(self.OTHER, signed_payload(e))[1]
        with self.assertRaisesRegex(Invalid, "entry 5: bad signature"):
            replay(c.entries, verifier=self.verifier)
        e["sig"] = sign_entry(self.NEW, signed_payload(e))[1]
        self.assertEqual(replay(c.entries, verifier=self.verifier).members["ada"].key, new)

    def test_a_request_or_a_proof_by_another_key_or_over_anything_else_is_refused(self):
        for name, kw, pattern in (
                ("signed by another key", {"signer": self.OTHER}, "entry 2: bad signature"),
                ("proof by another key", {"proof_seed": self.OTHER}, "entry 2: bad proof"),
                ("proof over another login", {"proof_over": rekey_message("carol", fake_key("ada"), "x")}, "entry 2: bad proof"),
                ("proof over another old key", {"proof_over": rekey_message("ada", fake_key("carol"), "x")}, "entry 2: bad proof")):
            c, new = self.chain()
            if "proof_over" in kw:
                kw = {"proof_over": kw["proof_over"].replace(b"\nx\n", f"\n{new}\n".encode())}
            self.request(c, new, **kw)
            with self.subTest(name), self.assertRaisesRegex(Invalid, pattern):
                replay(c.entries, verifier=self.verifier)


class Gate(unittest.TestCase):
    """The online gate (identity.py): the new key is listed for the login, and the pull request comes from the
    member's own GitHub account, at the request and again at its application."""

    NO_NET = mock.Mock(side_effect=AssertionError("no lookup"))

    def setUp(self):
        c = asked()                                          # 0 genesis, 1 freeze, 2 request, 3 and 4 co-signatures
        finish(c, days=21)                                   # 5
        self.entries, self.new = c.entries, fake_key("ada-new")
        self.listed = lambda login: [self.new + " laptop", fake_key("ada") + " old"]

    def problems(self, upto, since, author="ada", fetch=None, author_id=None, **kw):
        return identity.pr_problems(self.entries[:upto], since, author, fetch=fetch or self.listed,
                                    fetch_user=kw.pop("fetch_user", self.NO_NET),
                                    author_id=gid("ada") if author_id is None else author_id, **kw)

    def test_the_request_comes_from_the_members_account_with_a_key_that_account_lists(self):
        self.assertEqual(self.problems(3, 2), [])
        self.assertEqual(self.problems(3, 2, fetch=lambda login: [fake_key("ada") + " old"]),
                         ["entry 2: the new key is not listed at https://github.com/ada.keys"])
        self.assertEqual(self.problems(3, 2, author_id=gid("ada") + 1),
                         [f"entry 2 (rekey_recover): ada is the GitHub account with id {gid('ada')}, but the pull request is "
                          f"by the account with id {gid('ada') + 1}"])
        self.assertEqual(self.problems(3, 2, author="ada-renamed", author_id=gid("ada")), [])     # the account, not its login

    def test_the_application_is_checked_again(self):
        self.assertEqual(self.problems(6, 5), [])
        self.assertEqual(self.problems(6, 5, fetch=lambda login: []),
                         ["entry 5: the new key is not listed at https://github.com/ada.keys"])
        self.assertEqual(self.problems(6, 5, author_id=7),
                         [f"entry 5 (rekey_recover_apply): ada is the GitHub account with id {gid('ada')}, but the pull "
                          "request is by the account with id 7"])

    def test_a_failed_lookup_fails_closed(self):
        def down(login):
            raise OSError("network unreachable")
        for upto, since in ((3, 2), (6, 5)):
            bad = self.problems(upto, since, fetch=down)
            self.assertEqual(bad, [f"entry {since}: cannot fetch https://github.com/ada.keys (network unreachable); refusing "
                                   "(fail closed)"])
            bad = identity.pr_problems(self.entries[:upto], since, "ada", fetch=self.listed, fetch_user=down)
            self.assertEqual(bad, [f"entry {since}: cannot fetch https://api.github.com/users/ada (network unreachable); "
                                   "refusing (fail closed)"])
        looked = identity.pr_problems(self.entries[:3], 2, "ada", fetch=self.listed,
                                      fetch_user=lambda login: {"id": gid("ada"), "login": "ada"})
        self.assertEqual(looked, [])

    def test_a_co_signature_and_an_objection_are_ordinary_entries_of_their_author(self):
        self.assertEqual(self.problems(4, 3, author="carol", fetch=self.NO_NET, author_id=gid("carol")), [])
        self.assertEqual(self.problems(4, 3, author="ada", fetch=self.NO_NET),
                         [f"entry 3 (rekey_cosign): carol is the GitHub account with id {gid('carol')}, but the pull "
                          f"request is by the account with id {gid('ada')}"])
        c = asked()
        stop(c, days=1)
        self.assertEqual(identity.pr_problems(c.entries, 5, "ada", fetch=self.NO_NET, fetch_user=self.NO_NET), [])


class Reads(unittest.TestCase):
    def test_the_state_report_shows_recoveries(self):
        c = asked()
        rep = state_report(c.state(), c.now)
        json.dumps(rep)
        self.assertEqual(rep["recoveries"], [{"login": "ada", "seq": 2, "time": iso(T0 + DAY), "status": "pending",
                                              "cosigners": ["carol", "dan"], "cosigners_needed": 2, "freeze": 1,
                                              "notice_until": iso(T0 + 22 * DAY), "expires_at": iso(T0 + 61 * DAY)}])
        ada = next(m for m in rep["members"] if m["login"] == "ada")
        self.assertEqual((ada["frozen_until"], ada["recovering"]), (iso(T0 + 30 * DAY), True))
        later = state_report(c.state(), T0 + 40 * DAY)
        ada = next(m for m in later["members"] if m["login"] == "ada")
        self.assertEqual((ada["frozen_until"], ada["recovering"], later["recoveries"][0]["status"]), (None, True, "ready"))

    def test_the_guide_tells_a_member_under_recovery_what_is_left_to_them(self):
        from openmasonry.guide import next_steps
        c = lodge(founders=SEVEN)
        freeze(c, "ada")
        ask(c, days=29)
        steps = [(s.action, s.why) for s in next_steps(c.state(), "ada", T0 + 40 * DAY)]     # the freeze ran out ten days ago
        self.assertEqual([a for a, _ in steps], ["wait", "depart"])
        self.assertIn("A recovery of your key is under way (entry 2)", steps[0][1])
        self.assertIn("2027-03-31T00:00:00Z at the latest", steps[0][1])

    def test_every_entry_type_has_its_own_line_in_the_dialog(self):
        c = asked()
        text = actions.describe(c.state(), c.entries[2])
        for part in ("recover your membership with a NEW key", "Old key: SHA256:", "New key: SHA256:", "entry #2"):
            self.assertIn(part, text)
        self.assertNotIn('{"', text)


class Documents(unittest.TestCase):
    def test_the_specification_states_the_rules_of_recovery(self):
        spec = (REPO / "docs/whitepaper/SPEC.md").read_text(encoding="utf-8")
        for message in ("a recovery never needs a custodian",
                        "a recovery of the key of {actor} is already pending (entry {seq})",
                        "only Master Builders may co-sign a key recovery",
                        "a member cannot co-sign the recovery of their own key",
                        "no recovery of the key of {actor} is pending",
                        "{actor} is not a member whose key can be recovered (not a member, departed, expelled or voided)",
                        "stays frozen while its recovery is pending",
                        "co-signatures of active Master Builders it needs"):
            self.assertIn(message, spec, message)
        for word in ("requested", "pending", "ready", "applied", "objected", "opposed", "canceled", "expired"):
            self.assertIn(f"`{word}`", spec)


if __name__ == "__main__":
    unittest.main()
