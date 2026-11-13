"""Accounts and keys: one GitHub account per member, self-service key rotation (`rekey`) and hardware-backed keys
in the ledger.

Most tests use `Fast` (tests.test_strict): the "signature" of an entry is the public key that signed it. The
tests that check real signatures build them with the pure-Python signer of tests.test_signatures, so no
OpenSSH and no token is needed; the network (`identity.fetch_github_keys`) is always replaced.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from openmasonry import actions, crypto, identity, ledger
from openmasonry.guide import next_steps
from openmasonry.ledger import Invalid, apply, commitment, replay, signed_payload
from tests.test_guide import OmHarness
from tests.test_protocol import witness_subject, DECL, FOUNDERS, T0, genesis_body, gid, invite, petition, salt_of, entry_path
from tests.test_signatures import (UP, UV, keyline, keypair, sign_entry, sk_keyline, sk_sign_entry)
from tests.test_strict import DAY, SEC, Fast, by_key, fake_key, founded, hand_state, mk

URL = "https://example.org/work"


def point_of(name: str) -> bytes:
    scalar = int.from_bytes(hashlib.sha512(name.encode()).digest(), "little") % crypto._L
    return crypto._encode(crypto._mul(scalar, crypto._B))


def fake_sk_key(name: str) -> str:
    """The hardware-backed spelling of `fake_key(name)`: the same Ed25519 point in an sk key blob."""
    return sk_keyline(point_of(name))


def admit(c, who, by="hiram", second="ada", key_of=None):
    petition(c, who, by, key_of=key_of)
    if second:
        c.add("vouch", second, {"candidate": who})
    c.add("ballot_open", by, {"id": f"adm-{who}", "kind": "admission", "subject": {"candidate": who}})
    c.vote(f"adm-{who}", {f: "yes" for f in FOUNDERS})


def rekey(c, who, new_name, days=0.0, proof=None, old_name=None):
    """`who` replaces their key by the key named `new_name`; the chain then signs for `who` with it."""
    new = c.key(new_name) if isinstance(new_name, str) and " " not in new_name else new_name
    e = c.add("rekey", who, {"key": new, "proof": new if proof is None else proof}, days=days, key_of=old_name)
    return e, new


def switch(c, who, key: str) -> None:
    c.keys[who] = (None, key)


# ---------------------------------------------------------------- B: one GitHub account, one member ----

class OneAccountOneMember(unittest.TestCase):
    def test_two_founders_cannot_be_the_same_github_account(self):
        c = Fast()
        body = genesis_body(c)
        body["founders"][2]["github_id"] = body["founders"][0]["github_id"]
        c.add("genesis", "hiram", body)
        c.refused(self, "entry 0: founders must be distinct GitHub accounts .*one GitHub account, one member")

    def test_the_account_of_a_member_cannot_be_invited_under_another_login(self):
        c = founded()
        c.add("invite", "ada", {"login": "hiram-two", "github_id": gid("hiram")})
        c.refused(self, f"entry 1: the GitHub account with id {gid('hiram')} is already the member 'hiram' "
                        r"\(one GitHub account, one member")
        c.add("invite", "ada", {"login": "hiram-two", "github_id": gid("hiram-two")})
        self.assertTrue(c.state().invited("hiram-two", c.now))

    def test_a_live_invitation_holds_its_account(self):
        c = founded()
        invite(c, "alice")
        c.add("invite", "ada", {"login": "alice-two", "github_id": gid("alice")}, days=30)
        c.refused(self, f"the GitHub account with id {gid('alice')} is already the invitation 'alice'")
        st = c.state()
        self.assertEqual(st.id_holders(gid("alice"), c.now), [("invitation", "alice")])
        self.assertEqual(st.id_holders(gid("alice"), c.now + SEC), [])              # lapsed: it holds nothing
        c.now += SEC
        c.add("invite", "ada", {"login": "alice-two", "github_id": gid("alice")})
        self.assertTrue(c.state().invited("alice-two", c.now))

    def test_a_reserved_petition_holds_its_account(self):
        c = founded()
        petition(c, "alice")
        c.add("invite", "ada", {"login": "alice-two", "github_id": gid("alice")}, days=180)
        c.refused(self, f"the GitHub account with id {gid('alice')} is already the petition 'alice'")
        c.add("invite", "ada", {"login": "alice-two", "github_id": gid("alice")}, days=1)   # the petition lapsed
        self.assertEqual(c.state().id_holders(gid("alice"), c.now), [("invitation", "alice-two")])

    def test_the_petition_under_an_open_ballot_still_holds_it(self):
        c = founded()
        petition(c, "alice")
        c.add("vouch", "ada", {"candidate": "alice"})
        c.add("ballot_open", "hiram", {"id": "adm", "kind": "admission", "subject": {"candidate": "alice"}}, days=179)
        c.add("invite", "carol", {"login": "alice-two", "github_id": gid("alice")}, days=5)
        c.refused(self, "is already the petition 'alice'")

    def test_a_member_of_any_status_holds_the_account(self):
        c = founded()
        admit(c, "alice")
        c.add("depart", "alice", {})
        c.add("invite", "ada", {"login": "alice-two", "github_id": gid("alice")}, days=100)
        c.refused(self, f"the GitHub account with id {gid('alice')} is already the member 'alice'")
        c.add("ballot_open", "hiram", {"id": "x", "kind": "sanction", "subject": {"member": "carol", "measure": "expel"}})
        c.vote("x", {"hiram": "yes", "ada": "yes"})
        self.assertEqual(c.state().members["carol"].status, "expelled")
        c.add("invite", "ada", {"login": "carol-two", "github_id": gid("carol")}, days=1)
        c.refused(self, "is already the member 'carol'")

    def test_a_returning_member_is_the_same_account_on_the_same_login(self):
        c = founded()
        admit(c, "alice")
        c.add("depart", "alice", {})
        invite(c, "alice", days=90)                                  # the same id on the same login
        st = c.state()
        self.assertEqual(st.id_holders(gid("alice"), c.now), [("member", "alice"), ("invitation", "alice")])
        c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": DECL})
        c.add("vouch", "ada", {"candidate": "alice"})
        c.add("ballot_open", "hiram", {"id": "again", "kind": "admission", "subject": {"candidate": "alice"}})
        c.vote("again", {f: "yes" for f in FOUNDERS})
        m = c.state().members["alice"]
        self.assertEqual((m.status, m.degree, m.github_id), ("active", 1, gid("alice")))

    def test_a_refused_invitation_changes_nothing(self):
        c = founded()
        st = c.state()
        before = copy.deepcopy(st)
        e = c.add("invite", "ada", {"login": "someone", "github_id": gid("carol")})
        with self.assertRaisesRegex(Invalid, "one GitHub account, one member"):
            apply(st, e, verifier=by_key)
        self.assertEqual(st, before)

    def test_the_view_lists_members_then_invitations_then_petitions(self):
        st = hand_state(mk("a", github_id=7), mk("b", github_id=7, status="departed", status_since=T0),
                        invitations={"c": {"by": "a", "github_id": 7, "time": T0},
                                     "d": {"by": "a", "github_id": 8, "time": T0}},
                        petitions={"e": {"key": fake_key("e"), "vouches": ["a"], "time": T0, "github_id": 7}})
        self.assertEqual(st.id_holders(7, T0), [("member", "a"), ("member", "b"), ("invitation", "c"), ("petition", "e")])
        self.assertEqual(st.id_holders(8, T0), [("invitation", "d")])
        self.assertEqual(st.id_holders(9, T0), [])


# ---------------------------------------------------------------- C: rekey ----

class Rekey(unittest.TestCase):
    def test_a_member_replaces_their_key_and_signs_with_the_new_one(self):
        c = founded()
        old = c.key("ada")
        e, new = rekey(c, "ada", "ada-2", days=3)
        st = c.state()
        m = st.members["ada"]
        self.assertEqual((m.key, m.last_rekey), (new, T0 + 3 * DAY))
        self.assertIn(point_of("ada-2").hex(), st.known_keys)
        self.assertIn(point_of("ada").hex(), st.known_keys)                # the old key stays known forever
        self.assertEqual(st.key_holders(old, c.now), [])
        self.assertEqual(st.key_holders(new, c.now), [("member", "ada")])
        c.add("work", "ada", {"ref": URL})                                 # still signed by the old key
        c.refused(self, "entry 2: bad signature")
        switch(c, "ada", new)
        c.add("work", "ada", {"ref": URL})
        self.assertEqual(c.state().seq, 2)

    def test_the_proof_is_the_new_keys_signature_over_login_old_key_and_new_key(self):
        c = founded()
        old, new = c.key("ada"), c.key("ada-2")
        rekey(c, "ada", "ada-2")
        seen = []

        def verifier(payload, sig, actor, key):
            seen.append((payload, sig, actor, key))
            return sig == key
        replay(c.entries, verifier=verifier)
        self.assertEqual(seen[-2], (signed_payload(c.entries[-1]), old, "ada", old))        # the entry: the current key
        self.assertEqual(seen[-1], (f"openmasonry rekey v1\nada\n{old}\n{new}\n".encode(), new, "ada", new))
        self.assertEqual(ledger.rekey_message("ada", old, new), seen[-1][0])
        c.entries.pop()
        for bad in (old, "", c.key("carol"), new + " "):
            rekey(c, "ada", "ada-2", proof=bad)
            c.refused(self, "entry 1: bad proof: the new key must sign the rekey message")

    def test_the_body_is_exact(self):
        c = founded()
        new = c.key("n")
        for body, pattern in (({"key": new}, "malformed rekey entry: missing field 'proof'"),
                              ({"proof": new}, "malformed rekey entry: missing field 'key'"),
                              ({"key": new, "proof": new, "old_key": c.key("ada")}, "unknown field 'old_key'"),
                              ({"key": 7, "proof": new}, "field 'key' must be a string"),
                              ({"key": new, "proof": ["x"]}, "field 'proof' must be a string"),
                              ({"key": new + " comment", "proof": new}, "keys must be ssh-ed25519 or sk-ssh-ed25519"),
                              ({"key": "ssh-rsa AAAA", "proof": new}, "keys must be ssh-ed25519 or sk-ssh-ed25519")):
            c.add("rekey", "ada", body)
            c.refused(self, pattern)

    def test_who_may_rekey(self):
        c = founded(witnesses=("tyler",))
        rekey(c, "stranger", "s-2")
        c.refused(self, "stranger is not a member who can replace their key")
        rekey(c, "tyler", "t-2")                                   # a witness is not a member
        c.refused(self, "tyler is not a member who can replace their key")
        c.add("ballot_open", "hiram", {"id": "x", "kind": "sanction", "subject": {"member": "ada", "measure": "expel"}})
        c.vote("x", {"hiram": "yes", "carol": "yes"})            # never one elector on a Master
        self.assertEqual(c.state().members["ada"].status, "expelled")
        c.add("depart", "carol", {})
        rekey(c, "carol", "carol-2")
        c.refused(self, r"carol is not a member who can replace their key \(not a member, departed, expelled or voided\)")
        rekey(c, "ada", "ada-2")
        c.refused(self, "ada is not a member who can replace their key")

    def test_a_suspended_member_may_rekey_and_nothing_else(self):
        c = founded()
        c.add("ballot_open", "hiram", {"id": "x", "kind": "sanction", "subject": {"member": "ada", "measure": "suspend"}})
        c.vote("x", {"hiram": "yes", "carol": "yes"})
        st = c.state()
        self.assertEqual(st.members["ada"].standing(c.now), "suspended")
        before = list(st.members["ada"].activity)
        _, new = rekey(c, "ada", "ada-2")
        st = c.state()
        self.assertEqual((st.members["ada"].key, st.members["ada"].status), (new, "suspended"))
        self.assertEqual(st.members["ada"].activity, before)
        switch(c, "ada", new)
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "ada is not an active member")

    def test_a_rekey_is_not_activity(self):
        c = founded()
        rekey(c, "ada", "ada-2", days=5)
        self.assertEqual(c.state().members["ada"].activity, [T0])

    def test_the_new_key_must_be_held_by_nobody(self):
        c = founded(witnesses=("tyler",))
        petition(c, "alice")
        c.add("ballot_open", "hiram", {"id": "w", "kind": "witness",
                                       "subject": witness_subject(c, "node2")})
        rekey(c, "ada", "ada")
        c.refused(self, "this is already your key")
        for name, holder in (("hiram", "hiram"), ("tyler", "tyler"), ("alice", "alice"), ("node2", "node2")):
            rekey(c, "ada", name)
            c.refused(self, f"this key is already used by {holder} "
                            r"\(one key per login: members, witnesses and petitions\)")

    def test_the_new_key_must_never_have_been_in_the_ledger(self):
        c = founded(witnesses=("tyler",))
        petition(c, "alice")                                       # …a petition that will lapse
        c.add("ballot_open", "hiram", {"id": "w-add", "kind": "witness",
                                       "subject": witness_subject(c, "node2")})
        c.vote("w-add", {"hiram": "no", "ada": "no", "carol": "no"})        # …a witness who was never added
        c.add("ballot_open", "hiram", {"id": "w-rm", "kind": "witness", "subject": {"action": "remove", "name": "tyler"}})
        c.vote("w-rm", {f: "yes" for f in FOUNDERS})                        # …a witness who was removed
        _, second = rekey(c, "ada", "ada-2", days=200)
        switch(c, "ada", second)
        st = c.state()
        for name in ("alice", "node2", "tyler", "ada"):
            self.assertEqual(st.key_holders(fake_key(name), c.now), [], name)
            rekey(c, "ada", fake_key(name), days=31)
            c.refused(self, "this key was used in this ledger before")
        _, third = rekey(c, "ada", "ada-3", days=31)                        # a key the ledger never saw
        self.assertEqual(c.state().members["ada"].key, third)

    def test_the_other_spelling_of_a_key_is_the_same_key(self):
        c = founded()
        rekey(c, "ada", fake_sk_key("ada"))                         # her own point as a hardware key
        c.refused(self, "this is already your key")
        rekey(c, "ada", fake_sk_key("hiram"))
        c.refused(self, "this key is already used by hiram")
        _, new = rekey(c, "ada", fake_sk_key("token"))
        self.assertEqual(c.state().members["ada"].key, new)
        switch(c, "ada", new)
        rekey(c, "ada", fake_key("token"), days=40)                 # …and back to the plain spelling of it
        c.refused(self, "this is already your key")
        rekey(c, "hiram", fake_key("token"))
        c.refused(self, "this key is already used by ada")

    def test_once_in_thirty_days_to_the_second(self):
        c = founded()
        _, k2 = rekey(c, "ada", "ada-2")
        switch(c, "ada", k2)
        c.now = T0 + 30 * DAY - SEC
        rekey(c, "ada", "ada-3")
        c.refused(self, "one rekey per member per 30 days")
        c.now = T0 + 30 * DAY
        _, k3 = rekey(c, "ada", "ada-3")
        self.assertEqual((c.state().members["ada"].key, c.state().members["ada"].last_rekey), (k3, T0 + 30 * DAY))
        rekey(c, "hiram", "hiram-2")                                # the limit is per member
        self.assertEqual(c.state().members["hiram"].key, c.key("hiram-2"))

    def test_a_commitment_made_before_the_rekey_is_revealed_with_the_new_key(self):
        c = founded()
        c.add("ballot_open", "hiram", {"id": "am", "kind": "amendment",
                                       "subject": {"path": "CONSTITUTION.md", "new_sha256": "ab" * 32}})
        for who in FOUNDERS:
            c.add("ballot_commit", who, {"id": "am", "commitment": commitment("am", who, "yes", salt_of(who))})
        old = c.key("ada")
        _, new = rekey(c, "ada", "ada-2", days=1)
        c.add("ballot_reveal", "ada", {"id": "am", "vote": "yes", "salt": salt_of("ada")}, days=6.5)
        c.refused(self, "bad signature")                            # the old key reveals nothing any more
        switch(c, "ada", new)
        c.add("ballot_reveal", "ada", {"id": "am", "vote": "no", "salt": salt_of("ada")})
        c.refused(self, "reveal does not match commitment")
        for who in FOUNDERS:
            c.add("ballot_reveal", who, {"id": "am", "vote": "yes", "salt": salt_of(who)})
        c.add("ballot_close", "ada", {"id": "am"}, days=4)
        st = c.state()
        self.assertEqual((st.ballots["am"].result, st.ballots["am"].reveals["ada"]), ("passed", "yes"))
        self.assertNotEqual(old, new)

    def test_a_refused_rekey_changes_nothing(self):
        c = founded()
        st = c.state()
        before = copy.deepcopy(st)
        for body in ({"key": c.key("hiram"), "proof": c.key("hiram")}, {"key": c.key("n"), "proof": "x"}):
            e = c.add("rekey", "ada", body)
            c.entries.pop()
            with self.assertRaises(Invalid):
                apply(st, e, verifier=by_key)
            self.assertEqual(st, before)

    def test_the_guide_never_lists_a_rekey(self):
        c = founded()
        st = c.state()
        for who in FOUNDERS:
            self.assertFalse(any("rekey" in (s.action, *s.argv) for s in next_steps(st, who, c.now + 400 * DAY)))


class RekeyWithRealSignatures(unittest.TestCase):
    """The whole path with `crypto.verify`: a plain key hands over to a hardware-backed one."""

    SEEDS = {"hiram": b"1" * 32, "token": b"2" * 32, "other": b"3" * 32}

    def chain(self):
        c = Fast()
        c.keys["hiram"] = (None, keyline(keypair(self.SEEDS["hiram"])[2]))
        e = c.add("genesis", "hiram", genesis_body(c, ["hiram"]))
        e["sig"] = sign_entry(self.SEEDS["hiram"], signed_payload(e))[1]
        return c

    def rekey(self, c, proof_over: bytes, proof_seed: bytes = SEEDS["token"], flags: int = UP):
        new = sk_keyline(keypair(self.SEEDS["token"])[2])
        e = c.add("rekey", "hiram", {"key": new, "proof": sk_sign_entry(proof_seed, proof_over, flags, 5)[1]})
        e["sig"] = sign_entry(self.SEEDS["hiram"], signed_payload(e))[1]
        return new

    def test_a_plain_key_hands_over_to_a_token(self):
        c = self.chain()
        old = c.keys["hiram"][1]
        token = sk_keyline(keypair(self.SEEDS["token"])[2])
        with mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
            new = self.rekey(c, ledger.rekey_message("hiram", old, token))
            self.assertEqual(replay(c.entries).members["hiram"].key, new)
            w = c.add("work", "hiram", {"ref": URL})
            w["sig"] = sk_sign_entry(self.SEEDS["token"], signed_payload(w), UP | UV, 6)[1]
            self.assertEqual(replay(c.entries).seq, 2)
            w["sig"] = sign_entry(self.SEEDS["hiram"], signed_payload(w))[1]            # the retired key
            with self.assertRaisesRegex(Invalid, "entry 2: bad signature"):
                replay(c.entries)

    def test_a_proof_for_anything_else_is_refused(self):
        c = self.chain()
        old = c.keys["hiram"][1]
        token = sk_keyline(keypair(self.SEEDS["token"])[2])
        other = keyline(keypair(self.SEEDS["other"])[2])
        good = ledger.rekey_message("hiram", old, token)
        with mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
            for name, over, seed, flags in (
                    ("another login", ledger.rekey_message("ada", old, token), self.SEEDS["token"], UP),
                    ("another old key", ledger.rekey_message("hiram", other, token), self.SEEDS["token"], UP),
                    ("another new key", ledger.rekey_message("hiram", old, other), self.SEEDS["token"], UP),
                    ("the entry's own payload", b"", self.SEEDS["token"], UP),
                    ("signed by the old key's seed", good, self.SEEDS["hiram"], UP),
                    ("signed without a touch", good, self.SEEDS["token"], 0)):
                d = Fast()
                d.keys, d.entries, d.now = c.keys, list(c.entries), c.now
                self.rekey(d, over, seed, flags)
                with self.subTest(name), self.assertRaisesRegex(Invalid, "entry 1: bad proof"):
                    replay(d.entries)

    def test_the_proof_message_is_not_an_entry_payload(self):
        msg = ledger.rekey_message("hiram", "ssh-ed25519 A", "ssh-ed25519 B")
        self.assertEqual(msg, b"openmasonry rekey v1\nhiram\nssh-ed25519 A\nssh-ed25519 B\n")
        self.assertFalse(msg.startswith(b"{"))                      # every signed payload of an entry is a JSON object

    def test_the_vector_of_the_specification(self):
        old, new = fake_key("old"), fake_sk_key("new")
        msg = ledger.rekey_message("ada", old, new)
        self.assertEqual((len(msg), hashlib.sha256(msg).hexdigest()),
                         (234, "872750786a97b04505b889d8fb0a3b4789744b86cfed00e9ac671d07394d185d"))
        spec = (Path(__file__).resolve().parents[1] / "docs/whitepaper/SPEC.md").read_text(encoding="utf-8")
        for part in (f"`{old}`", f"`{new}`", hashlib.sha256(msg).hexdigest(),
                     'message = "openmasonry rekey v1" LF actor LF old-key LF new-key LF'):
            self.assertIn(part, spec)


class RekeyGate(unittest.TestCase):
    """identity.pr_problems: the new key of a `rekey` must be listed at github.com/<login>.keys."""

    def chain(self):
        c = founded()
        rekey(c, "ada", "ada-2")
        return c

    def problems(self, c, listed, since=1, author="ada"):
        def keys(login):
            if isinstance(listed, Exception):
                raise listed
            return [k + " laptop" for k in listed.get(login, [])]
        return identity.pr_problems(c.entries, since, author, fetch=keys, author_id=gid(author),
                                    fetch_user=mock.Mock(side_effect=AssertionError("the event's id is enough for a rekey")))

    def test_the_new_key_must_be_listed_for_the_login(self):
        c = self.chain()
        self.assertEqual(self.problems(c, {"ada": [c.key("other"), c.key("ada-2")]}), [])
        bad = self.problems(c, {"ada": [c.key("ada")], "hiram": [c.key("ada-2")]})
        self.assertEqual(bad, ["entry 1: the new key is not listed at https://github.com/ada.keys"])

    def test_it_fails_closed(self):
        bad = self.problems(self.chain(), OSError("network unreachable"))
        self.assertEqual(len(bad), 1)
        self.assertIn("entry 1: cannot fetch https://github.com/ada.keys (network unreachable); refusing (fail closed)",
                      bad[0])

    def test_a_hardware_key_is_listed_the_same_way(self):
        c = founded()
        new = fake_sk_key("token")
        rekey(c, "ada", new)
        self.assertEqual(self.problems(c, {"ada": [new]}), [])
        self.assertIn("not listed", self.problems(c, {"ada": [fake_key("token")]})[0])

    def test_the_actor_must_open_the_pull_request_and_older_entries_are_not_looked_up(self):
        c = self.chain()
        bad = self.problems(c, {"ada": [c.key("ada-2")]}, author="hiram")
        self.assertIn(f"entry 1 (rekey): ada is the GitHub account with id {gid('ada')}, but the pull request is by the "
                      f"account with id {gid('hiram')}", bad[0])
        switch(c, "ada", c.key("ada-2"))
        c.add("work", "ada", {"ref": URL})
        self.assertEqual(self.problems(c, OSError("down"), since=2), [])


# ---------------------------------------------------------------- D: key types in the ledger ----

class KeyTypes(unittest.TestCase):
    def sk_chain(self):
        c = Fast()
        for name in (*FOUNDERS, "tyler"):
            switch(c, name, fake_sk_key(name))
        c.add("genesis", "hiram", genesis_body(c, FOUNDERS, ["tyler"]))
        return c

    def test_the_grammar_names_both_types(self):
        self.assertIsNotNone(ledger.KEY_RE.fullmatch(fake_key("a")))
        self.assertIsNotNone(ledger.KEY_RE.fullmatch(fake_sk_key("a")))
        self.assertEqual((len(fake_key("a")), len(fake_sk_key("a"))), (80, 127))
        for bad in (fake_sk_key("a")[:-1], fake_sk_key("a") + "=", fake_key("a") + "=", "sk-" + fake_key("a"),
                    fake_sk_key("a").replace("@openssh.com", "@openssh_com")):
            self.assertIsNone(ledger.KEY_RE.fullmatch(bad), bad)
            self.assertFalse(ledger.ed25519(bad), bad)

    def test_founders_witnesses_and_candidates_may_hold_hardware_keys(self):
        c = self.sk_chain()
        st = c.state()
        self.assertEqual(st.members["ada"].key, fake_sk_key("ada"))
        self.assertEqual(st.witnesses["tyler"], fake_sk_key("tyler"))
        switch(c, "alice", fake_sk_key("alice"))
        admit(c, "alice")
        self.assertEqual(c.state().members["alice"].key, fake_sk_key("alice"))
        switch(c, "node2", fake_sk_key("node2"))
        c.add("ballot_open", "hiram", {"id": "w", "kind": "witness",
                                       "subject": witness_subject(c, "node2")})
        c.vote("w", {f: "yes" for f in FOUNDERS})
        self.assertEqual(c.state().witnesses["node2"], fake_sk_key("node2"))
        c.add("ballot_close", "node2", {"id": "w"})
        c.refused(self, "no open ballot")                           # …signed by the new witness's own key

    def test_one_point_is_one_key_whatever_its_type(self):
        c = Fast()
        body = genesis_body(c)
        body["founders"][1]["key"] = fake_sk_key("hiram")
        c.add("genesis", "hiram", body)
        c.refused(self, "founders and witnesses must use distinct keys")
        c = founded(witnesses=("tyler",))
        st = c.state()
        self.assertEqual(st.key_holders(fake_sk_key("ada"), c.now), [("member", "ada")])
        self.assertEqual(st.key_owner(fake_sk_key("tyler"), c.now), "tyler")
        invite(c, "alice")
        c.add("petition", "alice", {"key": fake_sk_key("ada"), "declaration_sha256": DECL})
        c.entries[-1]["sig"] = fake_sk_key("ada")
        c.refused(self, "this key is already used by ada")
        c.add("ballot_open", "hiram", {"id": "w", "kind": "witness",
                                       "subject": {"action": "add", "name": "node2", "key": fake_sk_key("tyler"),
                                                   "proof": fake_sk_key("tyler")}})
        c.refused(self, "this key is already used by tyler")

    def test_the_refusal_names_both_types(self):
        c = founded()
        invite(c, "alice")
        for bad in ("ssh-rsa AAAA", fake_sk_key("alice")[:-1], sk_keyline(point_of("alice"), b"ssh:x")):
            c.add("petition", "alice", {"key": bad, "declaration_sha256": DECL})
            c.refused(self, r"keys must be ssh-ed25519 or sk-ssh-ed25519@openssh\.com \(application ssh:\)")


# ---------------------------------------------------------------- C: the command ----

class RekeyCommand(OmHarness):
    def new_key(self, who="hiram", name="new") -> Path:
        home = Path(self.env(who)["OM_HOME"])
        path = home / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(path)], check=True)
        return path

    def bare(self, path: Path) -> str:
        return " ".join(Path(f"{path}.pub").read_text().split()[:2])

    def test_the_draft_signs_nothing_and_the_dialog_shows_both_fingerprints(self):
        path = self.new_key()
        d = self.draft("rekey", "--new-key", str(path), day=1)
        old, new = self.c.key("hiram"), self.bare(path)
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"], d["entry"]["body"]["key"]), ("rekey", "hiram", new))
        self.assertEqual(d["entry"]["body"]["proof"], actions.REKEY_PROOF_PENDING)       # no key was used yet
        self.assertFalse(entry_path(self.led, 1).exists())
        text = actions.describe(self.c.state(), d["entry"])
        self.assertIn("REPLACE your signing key", text)
        for key in (old, new):
            fp = "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(key.split()[1])).digest()).decode().rstrip("=")
            self.assertEqual(actions.fingerprint(key), fp)
            self.assertIn(fp, text)
        self.assertIn(actions.fingerprint(old), d["summary"])
        self.assertIn(actions.fingerprint(new), d["summary"])

    def test_approving_proves_signs_and_points_the_config_to_the_new_key(self):
        path = self.new_key()
        env = self.env()
        d = self.draft("rekey", "--new-key", str(path), day=1)
        self.approve(d["digest"], day=1)
        signed = json.loads(entry_path(self.led, 1).read_text())
        old, new = self.c.key("hiram"), self.bare(path)
        self.assertEqual(signed["body"]["key"], new)
        self.assertTrue(crypto.signature_valid(ledger.rekey_message("hiram", old, new), signed["body"]["proof"], new))
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], old))
        self.assertEqual(replay(self.c.entries + [signed]).members["hiram"].key, new)
        config = json.loads((Path(env["OM_HOME"]) / "config.json").read_text())
        self.assertEqual((config["key"], config["previous_key"]), (str(path), env["OM_KEY"]))
        # Without OM_KEY the configured key signs from now on…
        later = {k: v for k, v in env.items() if k != "OM_KEY"}
        r = self.run_om("work", URL, "--ledger", str(self.led), "--time", self.T(2), "--json", env=later)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        r = self.run_om("approve", json.loads(r.stdout)["digest"][:16], "--no-submit", env=later)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        work = json.loads(entry_path(self.led, 2).read_text())
        self.assertTrue(crypto.signature_valid(signed_payload(work), work["sig"], new))
        # …and the retired key is told so, when the act is drafted (with the way out, and a pointer to doctor).
        r = self.run_om("work", "https://example.org/again", "--ledger", str(self.led), "--time", self.T(4), env=env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("is not the key the ledger holds for hiram", r.stdout)
        self.assertIn("bin/om doctor", r.stdout)

    def test_what_the_ledger_would_refuse_is_refused_at_the_draft(self):
        shutil.copy2(self.c.keys["ada"][0], Path(self.env()["OM_HOME"]) / "adas")
        shutil.copy2(f"{self.c.keys['ada'][0]}.pub", Path(self.env()["OM_HOME"]) / "adas.pub")
        r = self.run_om("rekey", "--new-key", str(Path(self.env()["OM_HOME"]) / "adas"), "--ledger", str(self.led),
                        "--time", self.T(1), env=self.env())
        self.assertEqual(r.returncode, 1)
        self.assertIn("WOULD BE REFUSED", r.stdout)
        self.assertIn("this key is already used by ada", r.stdout)
        r = self.run_om("rekey", "--new-key", str(Path(self.env()["OM_HOME"]) / "absent"), "--ledger", str(self.led),
                        "--time", self.T(1), env=self.env())
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found", r.stdout)

    def test_a_stranger_is_told_they_are_not_a_member(self):
        self.c.key("alice")
        path = self.new_key("alice")
        r = self.run_om("rekey", "--new-key", str(path), "--ledger", str(self.led), "--time", self.T(1),
                        env=self.env("alice"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("alice is not a member", r.stdout)


class Doctor(unittest.TestCase):
    def test_it_explains_rekey_when_the_configured_key_is_not_the_ledgers(self):
        st = founded().state()
        self.assertIsNone(actions.key_advice(st, "ada", fake_key("ada")))
        self.assertIsNone(actions.key_advice(st, "nobody", fake_key("x")))
        self.assertIsNone(actions.key_advice(None, "ada", fake_key("x")))
        text = actions.key_advice(st, "ada", fake_sk_key("token"))
        for part in (actions.fingerprint(fake_key("ada")), actions.fingerprint(fake_sk_key("token")),
                     "bin/om rekey --new-key", "github.com/ada.keys"):
            self.assertIn(part, text)

    def run_doctor(self, configured: str) -> tuple[int, str]:
        """`om doctor` in this process, for the member ada, with every program and the ledger replaced."""
        import contextlib
        import io
        import tempfile
        st = founded().state()
        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "key"
            Path(f"{key}.pub").write_text(configured + " a comment\n")
            a = argparse.Namespace(login="ada", key=str(key), ledger=Path(d) / "led")
            out = io.StringIO()
            with mock.patch.object(actions, "state_of", return_value=st), \
                    mock.patch("openmasonry.onboard.doctor_checks", return_value=[]), \
                    mock.patch.object(actions.shutil, "which", lambda name, *x, **k: None if name == "curl" else "/bin/x"), \
                    mock.patch.object(actions.subprocess, "run",
                                      return_value=subprocess.CompletedProcess([], 1, "", "")), \
                    contextlib.redirect_stdout(out):
                code = actions.cmd_doctor(a)
        return code, out.getvalue()

    def test_om_doctor_accepts_both_key_types_and_explains_a_key_the_ledger_does_not_hold(self):
        code, text = self.run_doctor(fake_key("ada"))
        self.assertEqual(code, 0, text)
        self.assertIn("✔ Ed25519 key\n", text)
        self.assertNotIn("rekey", text)
        code, text = self.run_doctor(fake_sk_key("token"))
        self.assertEqual(code, 1, text)
        self.assertIn("✔ Ed25519 key held by a hardware token\n", text)
        self.assertIn("every signature asks for a touch", text)
        self.assertIn("✘ your configured key (" + actions.fingerprint(fake_sk_key("token")), text)
        self.assertIn("bin/om rekey --new-key", text)
        code, text = self.run_doctor("ssh-rsa AAAAB3NzaC1yc2E")
        self.assertEqual(code, 1, text)
        self.assertIn("✘ keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com", text)

    def test_both_key_types_pass_the_key_check(self):
        self.assertEqual(actions.key_kind(fake_key("a")), "Ed25519 key")
        self.assertEqual(actions.key_kind(fake_sk_key("a")), "Ed25519 key held by a hardware token")
        for bad in ("ssh-rsa AAAA", fake_sk_key("a")[:-1], sk_keyline(point_of("a"), b"ssh:x")):
            self.assertIsNone(actions.key_kind(bad))

    def test_the_configured_key_comes_after_the_flag_and_the_environment(self):
        with mock.patch.object(actions, "CONFIG", Path("/nonexistent/config.json")), mock.patch.dict("os.environ"):
            actions.os.environ.pop("OM_KEY", None)
            self.assertEqual(actions.key_path(None), Path.home() / ".ssh" / "id_ed25519")
        with mock.patch.object(actions, "_read_json", return_value={"key": "/k/configured"}), mock.patch.dict("os.environ"):
            actions.os.environ.pop("OM_KEY", None)
            self.assertEqual(actions.key_path(None), Path("/k/configured"))
            self.assertEqual(actions.key_path("/k/flag"), Path("/k/flag"))
            actions.os.environ["OM_KEY"] = "/k/env"
            self.assertEqual(actions.key_path(None), Path("/k/env"))


if __name__ == "__main__":
    unittest.main()
