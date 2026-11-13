"""Custodians and corrections: who they are, how long their keys live, the immediate acts, the effective
clock, objections and limits (SPEC sections 6.19 to 6.23 and 7.8).

Landmark VI: a wrong is repaired only by a new public record, and a repair may undo, freeze or pause but
never grant. Every test here uses `Fast` (tests.test_strict): the "signature" of an entry is the public key
that signed it, so the signer rule is exercised without OpenSSH. One class checks real signatures with the
pure-Python signer of tests.test_signatures. Nothing touches the network.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from openmasonry import actions, crypto, govern, identity, ledger
from openmasonry.__main__ import state_report
from openmasonry.guide import next_steps
from openmasonry.ledger import (Ballot, Correction, Custodian, Exam, Invalid, apply, commitment, custodian_message,
                                custodian_revoke_message, entry_hash, iso, load, objections_needed, replay,
                                signed_payload)
import tests.test_core as core
from tests.test_protocol import (witness_subject, FOUNDERS, T0, Chain, checkpoint, copy_governed, custodian_record, genesis_body, gid, initiate, invite,
                                 petition, salt_of)
from tests.test_signatures import keyline, keypair, sign_entry, sk_keyline
from tests.test_strict import DAY, SEC, Fast, by_key, draw_exam, fake_key, hand_state, mk, open_exam, tmpdir, write_ledger

REPO = Path(__file__).resolve().parents[1]
URL = "https://example.org/work"
HOUR = timedelta(hours=1)
SEVEN = ["hiram", "ada", "carol", "dan", "eve", "fay", "gus"]
REASON_TEXT = b"The key of ada was published by mistake on 2027-01-02.\n"
REASON = hashlib.sha256(REASON_TEXT).hexdigest()


def lodge(custodians=("warden",), founders=FOUNDERS, witnesses=(), **over) -> Fast:
    """A ledger founded with custodians: `warden` is linked to the first founder (hiram)."""
    c = Fast()
    c.add("genesis", founders[0], genesis_body(c, founders, witnesses, custodians=custodians, **over))
    return c


def correct(c, act, target=None, ground="protocol_defect", by="warden", days=0.0, reason=REASON, **over) -> int:
    """The custodian `by` signs a correction; returns its seq."""
    if act == "note" and ground == "protocol_defect":
        ground = "moderation"                    # the one ground of a note
    body = {"act": act, "target": {} if target is None else target, "ground": ground, "reason_sha256": reason} | over
    return c.add("correction", by, body, days=days)["seq"]


def freeze(c, login, days=0.0, by="warden") -> int:
    return correct(c, "freeze_key", {"login": login}, "key_compromised", by=by, days=days)


def halt(c, days=0.0, by="warden") -> int:
    return correct(c, "halt", {}, "attack_in_progress", by=by, days=days)


def withdraw(c, seq, by="warden", days=0.0):
    return c.add("correction_withdraw", by, {"seq": seq}, days=days)


def objection(c, seq, by, days=0.0):
    return c.add("correction_object", by, {"seq": seq}, days=days)


def open_ballot(c, bid="am", by="ada", kind="amendment", subject=None, **windows):
    subject = subject or {"path": "README.md", "new_sha256": "ab" * 32}
    return c.add("ballot_open", by, {"id": bid, "kind": kind, "subject": subject} | windows)


def sanction(c, bid="s", member="carol", by="ada", measure="admonish"):
    return open_ballot(c, bid, by, "sanction", {"member": member, "measure": measure})


def commit(c, bid, who, vote="yes"):
    return c.add("ballot_commit", who, {"id": bid, "commitment": commitment(bid, who, vote, salt_of(who))})


def reveal(c, bid, who, vote="yes"):
    return c.add("ballot_reveal", who, {"id": bid, "vote": vote, "salt": salt_of(who)})


def sk_twin(name: str) -> str:
    """The hardware-backed spelling of `fake_key(name)`: the same point under the other key type."""
    scalar = int.from_bytes(hashlib.sha512(name.encode()).digest(), "little") % crypto._L
    return sk_keyline(crypto._encode(crypto._mul(scalar, crypto._B)))


# ---------------------------------------------------------------- 1: custodians in the genesis ----

class Genesis(unittest.TestCase):
    def test_a_genesis_names_its_custodians(self):
        c = lodge(witnesses=("tyler",))
        st = c.state()
        w = st.custodians["warden"]
        self.assertEqual((w.name, w.key, w.revoke_key, w.member, w.alive, w.genesis, w.revoked),
                         ("warden", fake_key("warden"), fake_key("warden-revoke"), "hiram", T0, True, None))
        self.assertEqual(st.custodian_threshold, 1)
        self.assertEqual(st.custodian_status(w, T0), "live")
        self.assertNotIn("warden", st.members)                           # a custodian is not a member
        self.assertEqual(st.name_holders("WARDEN", T0), [("custodian", "warden")])
        self.assertEqual(st.key_holders(fake_key("warden"), T0), [("custodian", "warden")])
        self.assertEqual(st.key_holders(sk_twin("warden-revoke"), T0), [("custodian", "warden")])
        for name in ("warden", "warden-revoke"):
            self.assertIn(ledger.point(fake_key(name)), st.known_keys)
        self.assertEqual(st.login_taken("Warden"), "warden")

    def test_a_genesis_without_custodians_has_threshold_zero(self):
        st = lodge(custodians=()).state()
        self.assertEqual((st.custodians, st.custodian_threshold, st.corrections, st.sunset), ({}, 0, {}, None))

    def test_the_threshold_fits_the_number_of_custodians(self):
        pairs = (("warden", "hiram"), ("keeper", "ada"), ("porter", "carol"))
        for names, threshold, ok in (((), 0, True), ((), 1, False), (pairs[:1], 1, True), (pairs[:1], 0, False),
                                     (pairs[:1], 2, False), (pairs, 2, True), (pairs, 3, True), (pairs, 4, False),
                                     (pairs, 0, False), (pairs, -1, False)):
            c = Fast()
            c.add("genesis", "hiram", genesis_body(c, custodians=names, custodian_threshold=threshold))
            if ok:
                self.assertEqual(c.state().custodian_threshold, threshold)
            else:
                c.refused(self, "custodian_threshold is 0 without custodians, and otherwise 1 to the number of custodians")

    def test_at_most_three_custodians(self):
        seven = [(f"c{i}", f) for i, f in enumerate(SEVEN[:4])]
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, SEVEN, custodians=seven))
        c.refused(self, "entry 0: 0..3 custodians")

    def test_the_two_fields_are_required_and_the_records_exact(self):
        c = Fast()
        good = custodian_record(c, "warden", "hiram")
        for over, pattern in (({"custodians": [good | {"role": "boss"}]}, "malformed genesis entry: custodian: unknown field 'role'"),
                              ({"custodians": [{k: v for k, v in good.items() if k != "revoke_proof"}]},
                               "malformed genesis entry: custodian: missing field 'revoke_proof'"),
                              ({"custodians": [good | {"member": 7}]}, "custodian: field 'member' must be a string"),
                              ({"custodians": ["warden"]}, "malformed genesis entry: custodian: not an object"),
                              ({"custodians": {"warden": good}}, "field 'custodians' must be an array"),
                              ({"custodian_threshold": "1"}, "field 'custodian_threshold' must be an integer"),
                              ({"custodian_threshold": True}, "field 'custodian_threshold' must be an integer")):
            d = Fast()
            d.add("genesis", "hiram", genesis_body(d, custodians=("warden",)) | over)
            d.refused(self, pattern)
        for missing in ("custodians", "custodian_threshold"):
            d = Fast()
            body = genesis_body(d)
            del body[missing]
            d.add("genesis", "hiram", body)
            d.refused(self, f"malformed genesis entry: missing field '{missing}'")

    def test_a_custodian_name_is_a_login_that_nobody_else_holds(self):
        for name, witnesses, pattern in (("-warden", (), "custodian names follow login rules"),
                                         ("war den", (), "custodian names follow login rules"),
                                         ("Hiram", (), "a custodian name must differ from every founder login"),
                                         ("ada", (), "it is never a member login"),
                                         ("TYLER", ("tyler",), "a custodian name must differ from every founder login, witness name")):
            c = Fast()
            c.add("genesis", "hiram", genesis_body(c, witnesses=witnesses, custodians=(name,)))
            c.refused(self, pattern)
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, custodians=(("warden", "hiram"), ("Warden", "ada"))))
        c.refused(self, "and other custodian name")

    def test_custodian_keys_are_valid_and_held_by_nobody_else(self):
        def body(change):
            c = Fast()
            b = genesis_body(c, witnesses=("tyler",), custodians=("warden",))
            change(c, b["custodians"][0])
            c.add("genesis", "hiram", b)
            return c
        body(lambda c, r: r.update(key="ssh-rsa AAAA")).refused(self, "keys must be ssh-ed25519 or sk-ssh-ed25519")
        body(lambda c, r: r.update(revoke_key=r["key"] + " note")).refused(self, "keys must be ssh-ed25519")
        distinct = "a custodian key and its revoke key must differ from each other and from every other key of the genesis"
        body(lambda c, r: r.update(revoke_key=r["key"], revoke_proof=r["key"])).refused(self, distinct)
        body(lambda c, r: r.update(key=c.key("ada"), proof=c.key("ada"))).refused(self, distinct)
        body(lambda c, r: r.update(revoke_key=c.key("tyler"), revoke_proof=c.key("tyler"))).refused(self, distinct)
        twin = sk_twin("hiram")                                           # the first founder's point, as a hardware key
        body(lambda c, r: r.update(key=twin, proof=twin)).refused(self, distinct)
        c = Fast()
        b = genesis_body(c, custodians=(("warden", "hiram"), ("keeper", "ada")))
        b["custodians"][1].update(revoke_key=b["custodians"][0]["key"], revoke_proof=b["custodians"][0]["key"])
        c.add("genesis", "hiram", b)
        c.refused(self, distinct)

    def test_the_member_is_a_founder_of_the_same_genesis_and_one_person_holds_one_custodian_key(self):
        for member in ("nobody", "Hiram", "tyler", "warden"):
            c = Fast()
            c.add("genesis", "hiram", genesis_body(c, witnesses=("tyler",), custodians=(("warden", member),)))
            c.refused(self, "a custodian's member must be the login of a founder of this genesis")
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, custodians=(("warden", "ada"), ("keeper", "ada"))))
        c.refused(self, "custodians must be linked to distinct members")
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, custodians=(("warden", "carol"),)))        # any founder, not only the first
        self.assertEqual(c.state().custodians["warden"].member, "carol")

    def test_each_key_proves_possession_over_its_own_message(self):
        c = lodge()
        key, revoke = c.key("warden"), c.key("warden-revoke")
        seen = []

        def verifier(payload, sig, actor, k):
            seen.append((payload, sig, actor, k))
            return sig == k
        replay(c.entries, verifier=verifier)
        self.assertEqual(seen[0][0], signed_payload(c.entries[0]))                         # first the entry itself
        self.assertEqual([x[2] for x in seen[1:3]], ["ada", "carol"])                      # then the founders after the first
        self.assertEqual(seen[3], (f"openmasonry custodian v1\nwarden\nhiram\n{key}\n".encode(), key, "warden", key))
        self.assertEqual(seen[4], (f"openmasonry custodian-revoke v1\nwarden\n{key}\n{revoke}\n".encode(), revoke,
                                   "warden", revoke))
        self.assertEqual(custodian_message("warden", "hiram", key), seen[3][0])
        self.assertEqual(custodian_revoke_message("warden", key, revoke), seen[4][0])
        for field, bad, pattern in (("proof", revoke, "bad custodian proof: the custodian key must sign the custodian message"),
                                    ("proof", "", "bad custodian proof"),
                                    ("revoke_proof", key, "bad custodian revoke proof: the revoke key must sign the revoke message")):
            d = Fast()
            b = genesis_body(d, custodians=("warden",))
            b["custodians"][0][field] = bad
            d.add("genesis", "hiram", b)
            d.refused(self, "entry 0: " + pattern)

    def test_the_proof_messages_are_never_an_entry_payload_and_match_the_specification(self):
        key, revoke = fake_key("old"), sk_twin("new")
        one, two = custodian_message("warden", "hiram", key), custodian_revoke_message("warden", key, revoke)
        self.assertFalse(one.startswith(b"{") or two.startswith(b"{"))
        self.assertNotEqual(one.split(b"\n")[0], two.split(b"\n")[0])
        self.assertNotEqual(one.split(b"\n")[0], ledger.REKEY_DOMAIN.encode())
        spec = (REPO / "docs/whitepaper/SPEC.md").read_text(encoding="utf-8")
        for part in ('message = "openmasonry custodian v1" LF name LF member LF key LF',
                     'message = "openmasonry custodian-revoke v1" LF name LF key LF revoke-key LF',
                     hashlib.sha256(one).hexdigest(), hashlib.sha256(two).hexdigest()):
            self.assertIn(part, spec)

    def test_a_custodian_name_never_becomes_a_member_or_a_witness(self):
        c = lodge()
        invite(c, "Warden")
        c.refused(self, "login 'Warden' collides with the custodian 'warden'")
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness",
                                     "subject": witness_subject(c, "WARDEN", "n2")})
        c.refused(self, "a new witness name cannot equal a member login, a witness, a custodian")
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness",
                                     "subject": witness_subject(c, "node2", "warden-revoke")})
        c.refused(self, "this key is already used by warden")
        c.add("rekey", "ada", {"key": c.key("warden"), "proof": c.key("warden")})
        c.refused(self, "this key is already used by warden")
        invite(c, "alice")
        c.add("petition", "alice", {"key": c.key("warden"), "declaration_sha256": ledger.canon.declaration_digest()},
              key_of="warden")
        c.refused(self, "this key is already used by warden")


class GenesisWithRealSignatures(unittest.TestCase):
    """The whole path with `crypto.verify`: the custodian key and its revoke key each sign their message."""

    SEEDS = {"hiram": b"1" * 32, "warden": b"4" * 32, "revoke": b"5" * 32, "other": b"6" * 32}

    def chain(self, proof_seed=None, proof_over=None, revoke_seed=None, revoke_over=None):
        pub = {n: keyline(keypair(s)[2]) for n, s in self.SEEDS.items()}
        c = Fast()
        c.keys["hiram"] = (None, pub["hiram"])
        body = genesis_body(c, ["hiram"])
        body["custodians"] = [{
            "name": "warden", "key": pub["warden"], "revoke_key": pub["revoke"], "member": "hiram",
            "proof": sign_entry(proof_seed or self.SEEDS["warden"],
                                proof_over or custodian_message("warden", "hiram", pub["warden"]))[1],
            "revoke_proof": sign_entry(revoke_seed or self.SEEDS["revoke"],
                                       revoke_over or custodian_revoke_message("warden", pub["warden"], pub["revoke"]))[1]}]
        body["custodian_threshold"] = 1
        e = c.add("genesis", "hiram", body)
        e["sig"] = sign_entry(self.SEEDS["hiram"], signed_payload(e))[1]
        return c, pub

    def test_a_custodian_signs_with_its_key_and_is_revoked_with_the_other(self):
        with mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
            c, pub = self.chain()
            self.assertEqual(replay(c.entries).custodians["warden"].key, pub["warden"])
            e = c.add("custodian_alive", "warden", {}, days=1)
            e["sig"] = sign_entry(self.SEEDS["revoke"], signed_payload(e))[1]
            with self.assertRaisesRegex(Invalid, "entry 1: bad signature"):
                replay(c.entries)
            e["sig"] = sign_entry(self.SEEDS["warden"], signed_payload(e))[1]
            self.assertEqual(replay(c.entries).custodians["warden"].alive, T0 + DAY)
            r = c.add("custodian_revoke", "warden", {"name": "warden"})
            r["sig"] = sign_entry(self.SEEDS["warden"], signed_payload(r))[1]
            with self.assertRaisesRegex(Invalid, "entry 2: bad signature"):
                replay(c.entries)
            r["sig"] = sign_entry(self.SEEDS["revoke"], signed_payload(r))[1]
            self.assertEqual(replay(c.entries).custodians["warden"].revoked, T0 + DAY)

    def test_a_proof_over_anything_else_or_by_another_key_is_refused(self):
        pub = {n: keyline(keypair(s)[2]) for n, s in self.SEEDS.items()}
        good = custodian_message("warden", "hiram", pub["warden"])
        with mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
            for name, kw, pattern in (
                    ("another name", {"proof_over": custodian_message("keeper", "hiram", pub["warden"])}, "bad custodian proof"),
                    ("another member", {"proof_over": custodian_message("warden", "ada", pub["warden"])}, "bad custodian proof"),
                    ("another key", {"proof_over": custodian_message("warden", "hiram", pub["other"])}, "bad custodian proof"),
                    ("the revoke message", {"proof_over": custodian_revoke_message("warden", pub["warden"], pub["revoke"])},
                     "bad custodian proof"),
                    ("by the revoke key", {"proof_seed": self.SEEDS["revoke"]}, "bad custodian proof"),
                    ("revoke: the custodian message", {"revoke_over": good}, "bad custodian revoke proof"),
                    ("revoke: by the custodian key", {"revoke_seed": self.SEEDS["warden"]}, "bad custodian revoke proof")):
                c, _ = self.chain(**kw)
                with self.subTest(name), self.assertRaisesRegex(Invalid, "entry 0: " + pattern):
                    replay(c.entries)


# ---------------------------------------------------------------- 2: signers ----

class Signers(unittest.TestCase):
    def test_a_custodian_entry_is_signed_by_the_custodian_key_under_the_custodian_name(self):
        c = lodge(witnesses=("tyler",))
        c.add("custodian_alive", "warden", {}, key_of="hiram")
        c.refused(self, "entry 1: bad signature")
        c.add("custodian_alive", "warden", {}, key_of="warden-revoke")
        c.refused(self, "entry 1: bad signature")
        for who in ("hiram", "tyler", "stranger", "Warden"):
            c.add("custodian_alive", who, {})
            c.refused(self, f"entry 1: {who} is not a custodian")
            correct(c, "halt", {}, "attack_in_progress", by=who)
            c.refused(self, f"entry 1: {who} is not a custodian")
        c.add("custodian_alive", "warden", {}, days=2)
        self.assertEqual(c.state().custodians["warden"].alive, T0 + 2 * DAY)

    def test_the_revoke_key_signs_the_revocation_and_nothing_else(self):
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "ada")))
        c.add("custodian_revoke", "warden", {"name": "warden"})                # signed by the custodian key
        c.refused(self, "entry 1: bad signature")
        c.add("custodian_revoke", "warden", {"name": "keeper"}, key_of="keeper-revoke")
        c.refused(self, "the actor of a custodian_revoke is the custodian whose key it removes")
        c.add("custodian_revoke", "keeper", {"name": "keeper"}, key_of="warden-revoke")
        c.refused(self, "entry 1: bad signature")
        c.add("custodian_revoke", "ada", {"name": "ada"})
        c.refused(self, "ada is not a custodian")
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke")
        self.assertEqual(c.state().custodian_status(c.state().custodians["warden"], c.now), "revoked")

    def test_custodian_entries_credit_nobody(self):
        c = lodge()
        before = copy.deepcopy(c.state().members)
        c.add("custodian_alive", "warden", {}, days=3)
        seq = correct(c, "hold_room", {"login": "carol"}, days=1)
        withdraw(c, seq, days=1)
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke", days=1)
        self.assertEqual(c.state().members, before)                           # no activity, nothing else

    def test_where_no_custodian_exists_no_correction_exists(self):
        c = lodge(custodians=())
        for typ, body in (("correction", {"act": "halt", "target": {}, "ground": "attack_in_progress", "reason_sha256": REASON}),
                          ("correction", {"act": "note", "target": {"action": "hide", "target": "issue:1", "rule": "ROOMS.md"},
                                          "ground": "protocol_defect", "reason_sha256": REASON}),
                          ("correction_withdraw", {"seq": 0}), ("custodian_alive", {}),
                          ("custodian_revoke", {"name": "hiram"})):
            for who in ("hiram", "warden"):
                c.add(typ, who, body | ({"name": who} if typ == "custodian_revoke" else {}))
                c.refused(self, "entry 1: no custodian exists, so no correction exists")
        objection(c, 0, "ada")
        c.refused(self, "entry 1: no such correction")
        self.assertEqual(c.state().seq, 0)


# ---------------------------------------------------------------- 3: the life of a custodian key ----

class Life(unittest.TestCase):
    def test_a_key_lapses_more_than_180_days_after_its_last_sign_of_life(self):
        c = lodge()
        c.now = T0 + 180 * DAY
        c.add("custodian_alive", "warden", {})                                # the last second of the first 180 days
        st = c.state()
        self.assertEqual(st.custodians["warden"].alive, T0 + 180 * DAY)
        self.assertEqual(st.custodian_end(st.custodians["warden"]), T0 + 360 * DAY + SEC)
        c.now = T0 + 360 * DAY + SEC
        c.add("custodian_alive", "warden", {})
        c.refused(self, "the custodian key of warden is lapsed and signs nothing")

    def test_a_correction_and_a_note_are_not_signs_of_life(self):
        c = lodge()
        correct(c, "hold_room", {"login": "carol"}, days=100)
        correct(c, "note", {"action": "hide", "target": "issue:4", "rule": "ROOMS.md"}, days=70)
        self.assertEqual(c.state().custodians["warden"].alive, T0)
        c.now = T0 + 180 * DAY + SEC
        correct(c, "note", {"action": "hide", "target": "issue:5", "rule": "ROOMS.md"})
        c.refused(self, "the custodian key of warden is lapsed")

    def test_a_lapse_is_permanent_and_a_lapsed_key_signs_nothing(self):
        c = lodge()
        c.now = T0 + 400 * DAY
        for typ, body in (("custodian_alive", {}), ("correction_withdraw", {"seq": 1}),
                          ("correction", {"act": "halt", "target": {}, "ground": "attack_in_progress", "reason_sha256": REASON})):
            c.add(typ, "warden", body)
            c.refused(self, "the custodian key of warden is lapsed and signs nothing "
                            r"\(a lapsed, revoked or removed key never signs again\)")
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke")
        c.refused(self, "the custodian key of warden is lapsed")
        st = c.state()
        self.assertEqual(st.custodian_status(st.custodians["warden"], c.now), "lapsed")

    def test_the_revoke_key_removes_the_key_at_once_and_ends_what_it_had_in_force(self):
        c = lodge()
        f = freeze(c, "ada", days=1)
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the key of ada is frozen")
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke", days=2)
        st = c.state()
        self.assertEqual(st.custodians["warden"].revoked, T0 + 3 * DAY)
        self.assertEqual(st.span(st.corrections[f]), (T0 + DAY, T0 + 3 * DAY))
        self.assertEqual(st.correction_status(st.corrections[f], c.now), "ended")
        c.add("work", "ada", {"ref": URL})                                    # in the same second: unfrozen
        for typ, body in (("custodian_alive", {}), ("correction_withdraw", {"seq": f})):
            c.add(typ, "warden", body)
            c.refused(self, "the custodian key of warden is revoked and signs nothing")
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke")
        c.refused(self, "the custodian key of warden is revoked")
        self.assertEqual(c.state().seq, 3)

    def sunset_state(self, masters=7, witnesses=4, founders=0):
        people = [mk(f"m{i}") for i in range(masters)] + [mk(f"f{i}", founder=True) for i in range(founders)]
        st = hand_state(mk("hiram", founder=True), mk("app", 1), *people, seq=0, head="11" * 32, time=T0,
                        witnesses={f"w{i}": fake_key(f"w{i}") for i in range(witnesses)},
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("warden-revoke"), "hiram", T0)})
        st.corrections[0] = Correction(0, "warden", "freeze_key", {"login": "m0"}, "key_compromised", REASON, T0,
                                       until=T0 + 30 * DAY, subject="m0")
        return st

    def entry(self, st, typ, actor, body, at):
        return {"seq": st.seq + 1, "prev": st.head, "time": iso(at), "type": typ, "actor": actor, "body": body,
                "sig": fake_key(actor)}

    def test_the_sunset_lapses_every_genesis_custodian(self):
        st = self.sunset_state()
        self.assertTrue(ledger.sunset_reached(st, T0 + DAY))
        self.assertEqual(st.custodian_status(st.custodians["warden"], T0 + DAY), "live")   # nothing is recorded yet
        apply(st, self.entry(st, "work", "app", {"ref": URL}, T0 + DAY), by_key)             # any applied entry records it
        self.assertEqual(st.sunset, T0 + DAY)
        self.assertEqual(st.custodian_status(st.custodians["warden"], T0 + DAY), "lapsed")
        self.assertEqual(st.span(st.corrections[0]), (T0, T0 + DAY))                         # its freeze ended there
        self.assertIsNone(st.frozen("m0", T0 + DAY))
        with self.assertRaisesRegex(Invalid, "the custodian key of warden is lapsed and signs nothing"):
            apply(st, self.entry(st, "custodian_alive", "warden", {}, T0 + DAY), by_key)

    def test_the_sunset_is_recorded_once_and_never_undone(self):
        st = self.sunset_state()
        apply(st, self.entry(st, "work", "app", {"ref": URL}, T0 + DAY), by_key)
        for i in range(7):
            st.members[f"m{i}"].status = "departed"                                           # the condition stops holding
        self.assertFalse(ledger.sunset_reached(st, T0 + 3 * DAY))
        apply(st, self.entry(st, "work", "app", {"ref": URL}, T0 + 3 * DAY), by_key)
        self.assertEqual(st.sunset, T0 + DAY)
        self.assertEqual(st.custodian_status(st.custodians["warden"], T0 + 3 * DAY), "lapsed")

    def test_the_sunset_needs_seven_masters_who_are_not_founders_and_four_witnesses(self):
        for kw in ({"masters": 6}, {"witnesses": 3}, {"masters": 6, "founders": 5}):
            st = self.sunset_state(**kw)
            apply(st, self.entry(st, "work", "app", {"ref": URL}, T0 + DAY), by_key)
            self.assertIsNone(st.sunset, kw)
            apply(st, self.entry(st, "custodian_alive", "warden", {}, T0 + DAY), by_key)
        st = self.sunset_state(masters=7)
        st.members["m3"].activity = [T0 - 400 * DAY]                                          # dormant: not an active Master
        apply(st, self.entry(st, "work", "app", {"ref": URL}, T0 + DAY), by_key)
        self.assertIsNone(st.sunset)

    def test_a_lapse_is_computed_the_same_whenever_it_is_asked(self):
        """Eager and lazy agree: no entry marks a lapse, so a state replayed long ago and a state replayed
        today answer every question about any time identically."""
        c = lodge()
        f = freeze(c, "ada", days=170)                        # the key lapses 10 days later, the freeze would last 30
        early = c.state()
        c.add("work", "carol", {"ref": URL}, days=1)
        c.add("work", "carol", {"ref": URL}, days=30)
        late = c.state()
        lapse = T0 + 180 * DAY + SEC
        for t in (T0 + 170 * DAY, lapse - SEC, lapse, lapse + DAY, T0 + 200 * DAY, T0 + 400 * DAY):
            for st in (early, late):
                w = st.custodians["warden"]
                self.assertEqual(st.custodian_status(w, t), "live" if t < lapse else "lapsed", t)
                self.assertEqual(st.frozen("ada", t) is not None, t < lapse, t)
                self.assertEqual(st.correction_status(st.corrections[f], t), "active" if t < lapse else "ended", t)
            self.assertEqual(early.span(early.corrections[f]), late.span(late.corrections[f]))
        d = Fast()
        d.keys, d.entries, d.now = c.keys, list(c.entries[:2]), lapse - SEC
        d.add("work", "ada", {"ref": URL})
        d.refused(self, "the key of ada is frozen until 2027-06-30T00:00:01Z")
        d.now = lapse
        d.add("work", "ada", {"ref": URL})                    # no entry ended the freeze: the lapse of the key did
        self.assertEqual(d.state().seq, 2)


# ---------------------------------------------------------------- 4: corrections ----

class Corrections(unittest.TestCase):
    def test_a_correction_is_recorded_with_its_act_ground_and_reason(self):
        c = lodge()
        seq = freeze(c, "ada", days=2)
        k = c.state().corrections[seq]
        self.assertEqual((k.seq, k.by, k.act, k.target, k.ground, k.reason_sha256, k.time, k.class_, k.until, k.subject,
                          k.objections, k.void, k.withdrawn),
                         (1, "warden", "freeze_key", {"login": "ada"}, "key_compromised", REASON, T0 + 2 * DAY, "immediate",
                          T0 + 32 * DAY, "ada", (), None, None))

    def test_the_body_is_exact(self):
        c = lodge()
        base = {"act": "hold_room", "target": {"login": "carol"}, "ground": "identity_fraud", "reason_sha256": REASON}
        for body, pattern in ((base | {"note": "x"}, "malformed correction entry: unknown field 'note'"),
                              ({k: v for k, v in base.items() if k != "ground"}, "malformed correction entry: missing field 'ground'"),
                              ({k: v for k, v in base.items() if k != "reason_sha256"},
                               "malformed correction entry: missing field 'reason_sha256'"),
                              (base | {"target": "carol"}, "field 'target' must be an object"),
                              (base | {"act": 7}, "field 'act' must be a string"),
                              (base | {"act": "grant_degree"}, r"act must be one of \['freeze_key', 'freeze_witness', 'halt', "
                                                               r"'hold_room', 'note', 'stay', 'undo_ballot', 'void_ballot'\]"),
                              (base | {"act": "admit", "target": {"login": "x"}}, "act must be one of"),
                              (base | {"act": "void_ballot", "target": {"ballot": "x"}},
                               "malformed correction entry: void_ballot target: unknown field 'ballot'"),
                              (base | {"act": "undo_ballot", "target": {}},
                               "malformed correction entry: undo_ballot target: missing field 'id'"),
                              (base | {"ground": "disagreement"}, r"ground must be one of \['attack_in_progress', 'identity_fraud', "
                                                                  r"'key_compromised', 'moderation', 'protocol_defect'\]"),
                              (base | {"reason_sha256": "AB" * 32}, "reason_sha256 is the sha256"),
                              (base | {"reason_sha256": "https://example.org/issue/1"}, "archived as ledger/reasons/<sha256>.md"),
                              (base | {"target": {"login": "carol", "why": "x"}},
                               "malformed correction entry: hold_room target: unknown field 'why'"),
                              (base | {"target": {}}, "malformed correction entry: hold_room target: missing field 'login'"),
                              (base | {"target": {"login": 3}}, "hold_room target: field 'login' must be a string"),
                              (base | {"act": "halt", "ground": "attack_in_progress"}, "halt target: unknown field 'login'"),
                              (base | {"act": "freeze_key", "target": {"login": "carol"}},
                               "freeze_key takes one ground only: key_compromised"),
                              (base | {"act": "halt", "target": {}, "ground": "key_compromised"},
                               "halt takes one ground only: attack_in_progress")):
            c.add("correction", "warden", body)
            c.refused(self, pattern)
        for typ in ("correction_withdraw", "correction_object", "correction_cosign", "correction_apply"):
            c.add(typ, "ada" if typ == "correction_object" else "warden", {"seq": "1"})
            c.refused(self, f"malformed {typ} entry: field 'seq' must be an integer")
            c.add(typ, "ada" if typ == "correction_object" else "warden", {"seq": 1, "why": "x"})
            c.refused(self, f"malformed {typ} entry: unknown field 'why'")
        c.add("custodian_alive", "warden", {"note": "here"})
        c.refused(self, "malformed custodian_alive entry: unknown field 'note'")
        c.add("custodian_revoke", "warden", {}, key_of="warden-revoke")
        c.refused(self, "malformed custodian_revoke entry: missing field 'name'")

    def test_the_backstop_is_five_restricting_corrections_in_any_thirty_days(self):
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "ada")), witnesses=("tyler", "tiler"))
        sanction(c, "s", member="carol", by="hiram")
        first = correct(c, "hold_room", {"login": "carol"}, days=1)            # 1, at T0 + 1 d
        withdraw(c, first, by="keeper")                       # a withdrawal does not count, and a withdrawn act still does
        for i in range(3):
            correct(c, "note", {"action": "lock", "target": f"issue:{i}", "rule": "ROOMS.md"}, by="keeper")
        c.add("custodian_alive", "warden", {})
        freeze(c, "carol", by="keeper", days=1)                                # 2
        correct(c, "freeze_witness", {"name": "tyler"}, days=1)                # 3
        correct(c, "stay", {"ballot": "s"}, by="keeper", days=1)               # 4
        correct(c, "freeze_witness", {"name": "nobody"})
        c.refused(self, "no such witness")                    # a refused correction counts for nothing
        halt(c, days=1)                                                         # 5
        self.assertEqual(len([k for k in c.state().corrections.values() if k.class_ != "note"]), 5)
        for by in ("warden", "keeper"):
            correct(c, "hold_room", {"login": "carol"}, by=by)
            c.refused(self, r"at most 5 corrections in any 30 days, all custodians together \(notes aside\)")
        correct(c, "note", {"action": "lock", "target": "issue:9", "rule": "ROOMS.md"})          # a note is no restriction
        c.now = T0 + 31 * DAY - SEC                           # the first correction was at T0 + 1 day
        correct(c, "hold_room", {"login": "carol"})
        c.refused(self, "at most 5 corrections in any 30 days")
        c.now = T0 + 31 * DAY
        correct(c, "hold_room", {"login": "carol"})
        self.assertEqual(c.state().room_hold("carol", c.now).by, "warden")

    def test_a_custodian_never_holds_their_own_member_out_of_the_rooms(self):
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "ada")))
        correct(c, "hold_room", {"login": "hiram"})
        c.refused(self, r"recusal: the custodian warden never corrects their own member \(hiram\)")
        correct(c, "hold_room", {"login": "ada"}, by="keeper")
        c.refused(self, r"recusal: the custodian keeper never corrects their own member \(ada\)")
        correct(c, "hold_room", {"login": "ada"})            # another custodian may
        self.assertIsNotNone(c.state().room_hold("ada", c.now))

    def test_a_custodian_may_freeze_the_key_of_their_own_member(self):
        """It restricts nobody but the person who holds the custodian key, whose own key may be the stolen one."""
        c = lodge(founders=SEVEN)
        f = freeze(c, "hiram")
        st = c.state()
        self.assertEqual((st.frozen("hiram", c.now).seq, st.corrections[f].subject), (f, "hiram"))
        c.add("work", "hiram", {"ref": URL})
        c.refused(self, "the key of hiram is frozen")
        objection(c, f, "hiram")
        c.refused(self, "the key of hiram is frozen")        # neither as the linked member nor as the target
        objection(c, f, "ada", days=1)                       # E = 6 (everyone but hiram): two are needed
        self.assertIsNone(c.state().corrections[f].void)
        objection(c, f, "carol")
        self.assertIsNone(c.state().frozen("hiram", c.now))

    def test_no_correction_changes_a_degree_admits_anyone_or_changes_a_vote(self):
        c = lodge(witnesses=("tyler", "tiler"))
        initiate(c, "alice")
        sanction(c, "s", member="alice")
        commit(c, "s", "ada", "no")

        def facts(st):
            return ({l: (m.degree, m.status, m.key, dict(m.since), m.sponsors, m.seat_until) for l, m in st.members.items()},
                    {b.id: (b.kind, b.subject, b.electors, dict(b.commits), dict(b.reveals), b.result, b.commit_until,
                            b.reveal_until) for b in st.ballots.values()},
                    dict(st.witnesses), dict(st.pins), dict(st.petitions), dict(st.invitations))
        before = facts(c.state())
        correct(c, "stay", {"ballot": "s"})
        freeze(c, "ada")
        correct(c, "hold_room", {"login": "alice"})
        correct(c, "freeze_witness", {"name": "tyler"})
        halt(c)
        correct(c, "note", {"action": "block", "target": "user:mallory", "rule": "CODE_OF_CONDUCT.md"})
        self.assertEqual(facts(c.state()), before)
        self.assertEqual((len(c.state().corrections), len(c.state().notes)), (5, 1))


class FreezeKey(unittest.TestCase):
    def test_a_frozen_member_signs_nothing_but_what_the_rule_lists(self):
        c = lodge(witnesses=("tyler",))
        sanction(c, "s", member="carol", by="hiram")
        freeze(c, "ada", days=1)
        body = {"id": "b", "kind": "sanction", "subject": {"member": "carol", "measure": "admonish"}}
        for typ, b in (("work", {"ref": URL}), ("ballot_open", body), ("vouch", {"candidate": "x"}),
                       ("invite", {"login": "zed", "github_id": gid("zed")}), ("council_call", {"beacon_round": 1}),
                       ("ballot_close", {"id": "s"}),
                       ("exam_draw", {"candidate": "x", "degree": 2, "beacon": "ab" * 32})):
            c.add(typ, "ada", b)
            c.refused(self, "entry 3: the key of ada is frozen until 2027-02-01T00:00:00Z "
                            r"\(correction 2\): a frozen member may only depart, rekey, vote \(commit and reveal\), "
                            "take part in an amendment ballot or the ballot that removes a custodian, or object to a "
                            "recovery of their own key")
        hold = correct(c, "hold_room", {"login": "carol"})
        objection(c, hold, "ada")                            # not an objection either: the cap on freezes protects objectors
        c.refused(self, "the key of ada is frozen")
        c.add("work", "carol", {"ref": URL})                 # nobody else is touched
        self.assertTrue(c.state().members["ada"].is_active(c.now))          # frozen is not a status

    def test_a_freeze_does_not_stop_the_member_from_departing(self):
        c = lodge()
        freeze(c, "ada")
        c.add("depart", "ada", {}, days=1)
        self.assertEqual(c.state().members["ada"].status, "departed")

    def test_a_freeze_does_not_stop_the_member_from_rekeying_and_the_freeze_stays_until_it_ends(self):
        c = lodge()
        f = freeze(c, "ada")
        new = c.key("ada-2")
        c.add("rekey", "ada", {"key": new, "proof": new}, days=1)
        self.assertEqual(c.state().members["ada"].key, new)
        c.keys["ada"] = (None, new)
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the key of ada is frozen")
        withdraw(c, f)                                       # the custodian lifts it once the new key is in place
        c.add("work", "ada", {"ref": URL})
        self.assertEqual(c.state().seq, 4)

    def test_a_frozen_member_cannot_object_to_a_correction(self):
        c = lodge()
        freeze(c, "ada")
        hold = correct(c, "hold_room", {"login": "carol"}, days=1)
        objection(c, hold, "ada")
        c.refused(self, "the key of ada is frozen until 2027-01-31T00:00:00Z")
        self.assertNotIn("correction_object", ledger.FREEZE_ALLOWED)
        self.assertEqual(ledger.FREEZE_ALLOWED, {"depart", "rekey", "rekey_object", "ballot_commit", "ballot_reveal"})
        c.now = T0 + 30 * DAY                                # the freeze has run its time: the objection is hers again
        objection(c, hold, "ada")
        self.assertEqual(c.state().corrections[hold].objections, ("ada",))

    def test_a_freeze_does_not_stop_the_reveal_of_a_commitment_made_before_it(self):
        c = lodge()
        sanction(c, "s", member="carol", by="hiram", measure="suspend")
        commit(c, "s", "ada", "no")
        commit(c, "s", "hiram", "yes")
        freeze(c, "ada", days=6)
        c.now = T0 + 7 * DAY + ledger.REVEAL_GAP + SEC
        reveal(c, "s", "ada", "no")
        reveal(c, "s", "hiram", "yes")
        st = c.state()
        self.assertEqual(st.ballots["s"].reveals, {"ada": "no", "hiram": "yes"})

    def test_a_frozen_member_commits_and_reveals_after_the_freeze_too(self):
        """A freeze never changes who decides a ballot: the frozen key votes in every ballot it is an elector of."""
        c = lodge()
        sanction(c, "s", member="carol", by="hiram", measure="suspend")
        freeze(c, "ada", days=1)
        commit(c, "s", "ada", "no")                          # committed after the freeze
        commit(c, "s", "hiram", "yes")
        c.now = T0 + 7 * DAY + ledger.REVEAL_GAP
        reveal(c, "s", "ada", "no")
        reveal(c, "s", "hiram", "yes")
        st = c.state()
        self.assertEqual(st.ballots["s"].reveals, {"ada": "no", "hiram": "yes"})
        c.add("ballot_close", "ada", {"id": "s"})            # …and closes none
        c.refused(self, "the key of ada is frozen")

    def test_a_freeze_lasts_thirty_days_flat(self):
        c = lodge()
        f = freeze(c, "ada", days=1)
        st = c.state()
        self.assertEqual(st.span(st.corrections[f]), (T0 + DAY, T0 + 31 * DAY))
        c.now = T0 + 31 * DAY - SEC
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the key of ada is frozen until 2027-02-01T00:00:00Z")
        c.now = T0 + 31 * DAY
        c.add("work", "ada", {"ref": URL})                   # no entry ended it
        st = c.state()
        self.assertEqual(st.correction_status(st.corrections[f], c.now), "lapsed")
        withdraw(c, f)
        c.refused(self, "correction 1 is not in force")

    def test_the_freeze_needs_the_ground_key_compromised_and_a_member(self):
        c = lodge(witnesses=("tyler",))
        for ground in ("protocol_defect", "identity_fraud", "attack_in_progress"):
            correct(c, "freeze_key", {"login": "ada"}, ground)
            c.refused(self, "freeze_key takes one ground only: key_compromised")
        for login in ("nobody", "Ada", "tyler", "warden"):
            freeze(c, login)
            c.refused(self, "entry 1: no such member")
        c.add("depart", "carol", {})
        freeze(c, "carol")
        c.refused(self, "no such member")

    def test_the_same_key_is_frozen_again_only_ninety_days_after_the_last_freeze_began(self):
        c = lodge()
        f = freeze(c, "ada", days=1)
        withdraw(c, f, days=1)                               # withdrawn or lapsed: the 90 days still run
        c.now = T0 + 91 * DAY - SEC
        freeze(c, "ada")
        c.refused(self, r"the key of ada was frozen less than 90 days ago \(the same key is frozen again only 90 days "
                        r"after the previous freeze began, unless other custodians withdrew that freeze\)")
        other = freeze(c, "carol")                           # another key is another matter
        withdraw(c, other)
        c.now = T0 + 91 * DAY
        freeze(c, "ada")
        self.assertEqual(c.state().frozen("ada", c.now).seq, c.state().seq)

    def test_a_freeze_voided_by_objection_is_not_posted_again_for_ninety_days(self):
        c = lodge(founders=SEVEN)
        first = freeze(c, "ada", days=1)
        objection(c, first, "carol", days=2)                 # voided while in force
        self.assertEqual(c.state().corrections[first].void, T0 + 3 * DAY)
        freeze(c, "ada")
        c.refused(self, "the key of ada was frozen less than 90 days ago")
        c.now = T0 + 91 * DAY                                # 90 days after the freeze began, not yet after it was voided
        freeze(c, "ada")
        c.refused(self, f"correction {first}, the same act on the same target, was voided by objections less than 90 days ago")
        c.now = T0 + 93 * DAY
        freeze(c, "ada")
        self.assertIsNotNone(c.state().frozen("ada", c.now))

    def test_five_freezes_cannot_silence_the_masters(self):
        """With fewer than twenty active members one key is frozen at a time: a custodian cannot freeze the
        Masters who would object."""
        c = lodge(founders=SEVEN)
        first = freeze(c, "ada")
        for other in ("carol", "dan", "eve", "fay", "gus"):
            freeze(c, other)
            c.refused(self, r"too many keys are frozen at once: at most 1 \(a tenth of the 7 active members, never fewer than 1\)")
        for other in ("carol", "dan", "eve", "fay", "gus"):
            c.add("work", other, {"ref": URL})
        objection(c, first, "carol", days=1)                 # E = 5: one objection ends it
        self.assertIsNone(c.state().frozen("ada", c.now))
        freeze(c, "dan")                                     # the place is free again
        self.assertEqual(len(c.state().acting("freeze_key", c.now)), 1)

    def test_the_cap_is_a_tenth_of_the_active_members(self):
        def state(n):
            st = hand_state(*(mk(f"m{i}") for i in range(n)),
                            custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "m0", T0)})
            return st, st.custodians["warden"]
        for n, cap in ((2, 1), (19, 1), (20, 2), (29, 2), (30, 3)):
            st, w = state(n)
            for i in range(1, cap + 1):
                self.assertEqual(ledger._act_freeze_key(st, w, {"login": f"m{i}"}, "key_compromised", T0, 9), f"m{i}")
                st.corrections[i] = Correction(i, "warden", "freeze_key", {"login": f"m{i}"}, "key_compromised", REASON, T0,
                                               until=T0 + 30 * DAY, subject=f"m{i}")
            if n > cap + 1:
                with self.assertRaisesRegex(Invalid, f"at most {cap} "):
                    ledger._act_freeze_key(st, w, {"login": f"m{cap + 1}"}, "key_compromised", T0, 9)

    def test_a_frozen_examiner_counts_as_recused(self):
        c = lodge(founders=SEVEN[:4])
        initiate(c, "erin")
        rnd = open_exam(c, "erin", 2, days=31)
        ex = draw_exam(c, "erin", 2, rnd)                    # two examiners out of a pool of two (hiram and ada sponsor)
        frozen, other = ex.examiners
        self.assertEqual(sorted(ex.pool), ["carol", "dan"])
        freeze(c, frozen)
        ex = c.state().exams[("erin", 2)]
        self.assertEqual((ex.examiners, ex.recused, ex.lapsed), ((other,), (frozen,), True))   # nobody is left in the lot's order
        open_exam(c, "erin", 2)                              # lapsed without penalty: a new exam at once
        self.assertEqual(len(c.state().exams[("erin", 2)].pool), 2)

    def test_a_frozen_examiner_is_replaced_by_the_next_in_the_lots_order(self):
        st = hand_state(mk("dave", 1), *(mk(f) for f in SEVEN), seq=3, head="33" * 32, time=T0,
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "hiram", T0)})
        st.exams[("dave", 2)] = Exam("dave", 2, ("ada", "carol"), opened=T0, k=2, ranking=("ada", "carol", "dan", "eve"),
                                     reports={"carol": "pass"}, pool=("ada", "carol", "dan", "eve"))
        st.exams[("dave", 3)] = Exam("dave", 3, ("ada", "eve"), opened=T0, k=2, ranking=("ada", "eve"),
                                     reports={"ada": "pass", "eve": "pass"}, pool=("ada", "eve"))
        e = {"seq": 4, "prev": st.head, "time": iso(T0 + DAY), "type": "correction", "actor": "warden", "sig": fake_key("warden"),
             "body": {"act": "freeze_key", "target": {"login": "ada"}, "ground": "key_compromised", "reason_sha256": REASON}}
        apply(st, e, by_key)
        ex = st.exams[("dave", 2)]
        self.assertEqual((ex.examiners, ex.recused, ex.lapsed), (("carol", "dan"), ("ada",), False))
        decided = st.exams[("dave", 3)]
        self.assertEqual((decided.examiners, decided.recused), (("ada", "eve"), ()))        # a decided exam is left alone

    def test_a_member_frozen_before_the_draw_is_not_seated(self):
        c = lodge(founders=SEVEN[:5])
        initiate(c, "erin")
        rnd = open_exam(c, "erin", 2, days=31)
        pool = c.state().exams[("erin", 2)].pool
        self.assertEqual(sorted(pool), ["carol", "dan", "eve"])
        order = ledger.draw(list(pool), 3, f"{rnd:064x}", f"exam:erin:2:{rnd}")
        freeze(c, order[0])
        ex = draw_exam(c, "erin", 2, rnd)
        self.assertEqual((ex.examiners, ex.recused, ex.lapsed), ((order[1], order[2]), (order[0],), False))

    def test_a_frozen_member_stays_in_the_electorates_already_frozen(self):
        c = lodge()
        sanction(c, "s", member="carol", by="hiram", measure="suspend")
        commit(c, "s", "ada", "yes")
        freeze(c, "ada", days=7)                             # frozen through the whole reveal window
        c.now = T0 + 7 * DAY + ledger.REVEAL_GAP + SEC
        self.assertEqual(c.state().ballots["s"].electors, frozenset({"hiram", "ada"}))
        c.add("ballot_close", "hiram", {"id": "s"}, days=4)
        b = c.state().ballots["s"]
        self.assertEqual((b.result, b.reveals), ("lapsed", {}))               # an unrevealed vote abstains: no quorum


class FreezeWitness(unittest.TestCase):
    def test_a_frozen_witness_signs_nothing_for_thirty_days(self):
        c = lodge(witnesses=("tyler", "tiler"))
        f = correct(c, "freeze_witness", {"name": "tyler"}, "key_compromised", days=1)
        head = checkpoint(c.state())
        c.add("witness", "tyler", head)
        c.refused(self, r"entry 2: the witness tyler is frozen until 2027-02-01T00:00:00Z \(correction 1\)")
        c.add("ballot_close", "tyler", {"id": "x"})
        c.refused(self, "the witness tyler is frozen")
        c.add("witness", "tiler", head)                      # the other witness works on
        c.now = T0 + 31 * DAY - SEC
        c.add("witness", "tyler", head)
        c.refused(self, "the witness tyler is frozen")
        c.now = T0 + 31 * DAY
        c.add("witness", "tyler", checkpoint(c.state()))
        st = c.state()
        self.assertEqual((st.correction_status(st.corrections[f], c.now), st.history["checkpoints"][0]), ("lapsed", 2))

    def test_the_last_unfrozen_witness_is_frozen_only_under_attack(self):
        c = lodge(witnesses=("tyler", "tiler"))
        correct(c, "freeze_witness", {"name": "nobody"})
        c.refused(self, "no such witness")
        correct(c, "freeze_witness", {"name": "hiram"})
        c.refused(self, "no such witness")
        correct(c, "freeze_witness", {"name": "tyler"})
        correct(c, "freeze_witness", {"name": "tyler"})
        c.refused(self, "the witness tyler is already frozen")
        for ground in ("key_compromised", "protocol_defect", "identity_fraud"):
            correct(c, "freeze_witness", {"name": "tiler"}, ground)
            c.refused(self, "the last unfrozen witness is frozen only on the ground attack_in_progress")
        correct(c, "freeze_witness", {"name": "tiler"}, "attack_in_progress")
        self.assertEqual(len(c.state().acting("freeze_witness", c.now)), 2)
        sanction(c, "s", member="carol")
        c.add("ballot_close", "ada", {"id": "s"}, days=11)   # a member can still close a ballot
        self.assertEqual(c.state().ballots["s"].result, "lapsed")


class Stay(unittest.TestCase):
    def test_a_stayed_ballot_takes_no_commit_no_reveal_and_no_close(self):
        c = lodge(witnesses=("tyler",))
        sanction(c, "s", member="carol")
        commit(c, "s", "ada")
        s = correct(c, "stay", {"ballot": "s"}, days=1)
        refusal = r"ballot s is stayed until 2027-01-16T00:00:00Z \(correction 3\)"
        commit(c, "s", "hiram")
        c.refused(self, "entry 4: " + refusal)
        c.now = T0 + 8 * DAY
        reveal(c, "s", "ada")
        c.refused(self, refusal)
        c.now = T0 + 14 * DAY
        for who in ("ada", "tyler"):
            c.add("ballot_close", who, {"id": "s"})
            c.refused(self, refusal)
        self.assertEqual(ledger.due_actions(c.state(), c.now), [])
        st = c.state()
        self.assertEqual((st.stayed("s", c.now).seq, st.corrections[s].subject), (s, "carol"))

    def test_a_stay_extends_the_windows_by_exactly_the_stayed_time(self):
        c = lodge()
        sanction(c, "s", member="carol")                     # commit until T0 + 7 d; reveal from + 6 h 15 min, for 3 d
        s = correct(c, "stay", {"ballot": "s"}, days=2)
        withdraw(c, s, days=3)                               # stayed for exactly 3 days: [T0 + 2 d, T0 + 5 d)
        b = c.state().ballots["s"]
        self.assertEqual((b.commit_until, b.reveal_until), (T0 + 7 * DAY, T0 + 10 * DAY + ledger.REVEAL_GAP))   # never rewritten
        st = c.state()
        self.assertEqual(st.effective(T0, T0 + 9 * DAY, "s"), 6 * DAY)
        self.assertEqual(st.effective(T0, T0 + 9 * DAY), 9 * DAY)                     # another ballot's clock did not stop
        self.assertEqual(st.ballot_due(b, b.commit_until), T0 + 10 * DAY)
        c.now = T0 + 10 * DAY
        commit(c, "s", "ada")                                # the last second of the extended commit window
        c.now = T0 + 10 * DAY + SEC
        commit(c, "s", "hiram")
        c.refused(self, "commit window closed")
        opens = T0 + 10 * DAY + ledger.REVEAL_GAP
        c.now = opens - SEC
        reveal(c, "s", "ada")
        c.refused(self, r"not in the reveal window \(2027-01-11T06:15:00Z to 2027-01-14T06:15:00Z, both included\)")
        c.now = opens + 3 * DAY
        reveal(c, "s", "ada")                                # the last second of the extended reveal window
        c.add("ballot_close", "ada", {"id": "s"})
        c.refused(self, "ballot still open")
        c.now += SEC
        c.add("ballot_close", "ada", {"id": "s"})
        self.assertIsNotNone(c.state().ballots["s"].result)

    def test_a_stay_that_runs_its_time_extends_them_by_fourteen_days(self):
        c = lodge()
        sanction(c, "s", member="carol")
        correct(c, "stay", {"ballot": "s"}, days=6)
        c.now = T0 + 20 * DAY - SEC
        commit(c, "s", "ada")
        c.refused(self, "ballot s is stayed until 2027-01-21T00:00:00Z")
        c.now = T0 + 21 * DAY
        commit(c, "s", "ada")
        c.now += SEC
        commit(c, "s", "hiram")
        c.refused(self, "commit window closed")

    def test_a_ballot_is_stayed_once(self):
        c = lodge()
        sanction(c, "s", member="carol")
        s = correct(c, "stay", {"ballot": "s"})
        correct(c, "stay", {"ballot": "s"})
        c.refused(self, r"ballot s was stayed once already \(a ballot is stayed at most once\)")
        withdraw(c, s, days=1)
        correct(c, "stay", {"ballot": "s"}, days=1)
        c.refused(self, "ballot s was stayed once already")

    def test_what_is_never_stayed(self):
        c = lodge()
        correct(c, "stay", {"ballot": "nope"})
        c.refused(self, "entry 1: no open ballot")
        open_ballot(c, "am", "ada")
        correct(c, "stay", {"ballot": "am"})
        c.refused(self, "a ballot of kind amendment is never stayed")
        self.assertIn("custodian", ledger.STAY_EXEMPT)        # reserved for the ballot that removes a custodian
        sanction(c, "s", member="carol")
        c.vote("s", {"ada": "yes", "hiram": "yes"})
        correct(c, "stay", {"ballot": "s"})
        c.refused(self, "no open ballot")                     # closed

    def test_a_custodian_never_stays_a_ballot_their_member_is_party_to(self):
        c = lodge(witnesses=("tyler",))
        recusal = (r"recusal: the custodian warden never stays a ballot whose subject, opener or sponsor is their own "
                   r"member \(hiram\)")
        sanction(c, "opened", member="carol", by="hiram")
        correct(c, "stay", {"ballot": "opened"})
        c.refused(self, recusal)
        sanction(c, "subject", member="hiram", by="ada")
        correct(c, "stay", {"ballot": "subject"})
        c.refused(self, recusal)
        invite(c, "alice")                                    # hiram invites: the first sponsor
        c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": ledger.canon.declaration_digest()})
        c.add("vouch", "ada", {"candidate": "alice"})
        open_ballot(c, "adm", "ada", "admission", {"candidate": "alice"})
        correct(c, "stay", {"ballot": "adm"})
        c.refused(self, recusal)
        invite(c, "bob", by="ada")
        c.add("petition", "bob", {"key": c.key("bob"), "declaration_sha256": ledger.canon.declaration_digest()})
        c.add("vouch", "carol", {"candidate": "bob"})
        open_ballot(c, "adm2", "carol", "admission", {"candidate": "bob"})
        correct(c, "stay", {"ballot": "adm2"})                # hiram is neither subject, opener nor sponsor here
        self.assertIsNotNone(c.state().stayed("adm2", c.now))


class Halt(unittest.TestCase):
    def test_while_halted_only_the_listed_entries_are_accepted(self):
        c = lodge(witnesses=("tyler",))
        sanction(c, "s", member="carol")
        invite(c, "alice")
        h = halt(c, days=1)
        refusal = (r"the ledger is halted until 2027-01-16T00:00:00Z \(correction 3\): only custodian entries, "
                   "custodian_revoke, correction_object, depart, rekey, the entries of a key recovery, a witness "
                   "checkpoint, an amendment ballot and the ballot that removes a custodian are accepted")
        st = c.state()
        for who, typ, body in (("ada", "work", {"ref": URL}), ("ada", "ballot_commit", {"id": "s", "commitment": "ab" * 32}),
                               ("ada", "ballot_open", {"id": "b", "kind": "sanction", "subject": {"member": "carol", "measure": "admonish"}}),
                               ("ada", "invite", {"login": "bob", "github_id": gid("bob")}),
                               ("alice", "petition", {"key": c.key("alice"), "declaration_sha256": ledger.canon.declaration_digest()}),
                               ("tyler", "ballot_close", {"id": "s"}), ("ada", "ballot_close", {"id": "s"}),
                               ("tyler", "exam_draw", {"candidate": "ada", "degree": 4, "beacon": "ab" * 32}),
                               ("tyler", "council_draw", {"beacon": "ab" * 32}),
                               ("ada", "exam_open", {"candidate": "ada", "degree": 4, "work_ref": URL, "beacon_round": 1}),
                               ("ada", "council_call", {"beacon_round": 1})):
            c.add(typ, who, body)
            c.refused(self, "entry 4: " + refusal)
        self.assertEqual(ledger.due_actions(c.state(), c.now + 20 * DAY - DAY * 7), [])   # still halted: nothing to close or draw
        c.add("witness", "tyler", checkpoint(st))                                 # a checkpoint is evidence, and is accepted
        self.assertEqual((c.entries[-1]["body"]["upto_seq"], c.state().history["checkpoints"][0]), (st.seq, 1))
        c.add("custodian_alive", "warden", {}, days=1)
        hold = correct(c, "hold_room", {"login": "carol"})
        objection(c, hold, "ada")
        new = c.key("carol-2")
        c.add("rekey", "carol", {"key": new, "proof": new})
        c.add("depart", "ada", {})
        withdraw(c, h, days=1)
        c.add("work", "hiram", {"ref": URL})                  # resumed
        st = c.state()
        self.assertEqual((st.members["ada"].status, st.members["carol"].key, st.halted(c.now)), ("departed", new, None))
        self.assertEqual(ledger.HALT_ALLOWED, ledger.CUSTODIAN_SIGNED | ledger.RECOVERY_TYPES | {
            "correction_object", "depart", "rekey", "rekey_object", "rekey_cosign", "rekey_oppose", "witness"})
        self.assertFalse(ledger.HALT_ALLOWED & {"ballot_close", "exam_draw", "council_draw"})

    def test_a_halt_needs_an_attack_and_lasts_fourteen_days(self):
        c = lodge()
        for ground in ("key_compromised", "protocol_defect", "identity_fraud"):
            correct(c, "halt", {}, ground)
            c.refused(self, "halt takes one ground only: attack_in_progress")
        correct(c, "halt", {"ledger": "all"}, "attack_in_progress")
        c.refused(self, "malformed correction entry: halt target: unknown field 'ledger'")
        h = halt(c, days=1)
        st = c.state()
        self.assertEqual(st.span(st.corrections[h]), (T0 + DAY, T0 + 15 * DAY))
        c.now = T0 + 15 * DAY - SEC
        c.add("work", "ada", {"ref": URL})
        c.refused(self, "the ledger is halted until 2027-01-16T00:00:00Z")
        c.now = T0 + 15 * DAY
        c.add("work", "ada", {"ref": URL})                    # it ended by itself

    def test_at_most_one_halt_in_ninety_days_start_to_start(self):
        c = lodge()
        h = halt(c, days=1)
        halt(c, days=1)
        c.refused(self, r"the ledger was halted less than 90 days ago \(at most one halt in 90 days, start to start\)")
        withdraw(c, h)
        c.now = T0 + 91 * DAY - SEC
        halt(c)
        c.refused(self, "the ledger was halted less than 90 days ago")
        c.now = T0 + 91 * DAY
        halt(c)
        self.assertEqual(c.state().halted(c.now).seq, 3)

    def test_a_halt_does_not_let_a_ballot_close_or_its_reveal_window_run_out(self):
        c = lodge(witnesses=("tyler",))
        sanction(c, "s", member="carol", measure="suspend")   # commit until T0 + 7 d; reveal until T0 + 10 d 6 h 15 min
        commit(c, "s", "ada")
        commit(c, "s", "hiram")
        c.now = T0 + 7 * DAY + ledger.REVEAL_GAP + HOUR
        reveal(c, "s", "ada")                                 # one vote is out: an attacker would like the close now
        h = halt(c)                                           # halted for 14 days, through the whole reveal window
        halted_at = c.now
        c.now = T0 + 12 * DAY
        c.add("ballot_close", "tyler", {"id": "s"})
        c.refused(self, "the ledger is halted")
        c.now = halted_at + 14 * DAY                          # the halt is over, and the window is where it was
        b = c.state().ballots["s"]
        self.assertEqual(c.state().ballot_due(b, b.reveal_until), b.reveal_until + 14 * DAY)
        c.add("ballot_close", "tyler", {"id": "s"})
        c.refused(self, "ballot still open")
        self.assertEqual(ledger.due_actions(c.state(), c.now), [])
        c.now = b.reveal_until + 14 * DAY
        c.add("ballot_close", "tyler", {"id": "s"})
        c.refused(self, "ballot still open")
        reveal(c, "s", "hiram")                               # the second elector still reveals, in the last second
        c.now += SEC
        self.assertEqual(ledger.due_actions(c.state(), c.now), [("ballot_close", {"id": "s"})])
        c.add("ballot_close", "tyler", {"id": "s"})
        st = c.state()
        self.assertEqual((st.ballots["s"].result, st.members["carol"].status, st.corrections[h].void), ("passed", "suspended", None))

    def test_a_halt_stops_the_clock_of_invitations_petitions_and_exams(self):
        c = lodge()
        invite(c, "alice")                                    # lapses 30 effective days after T0
        initiate(c, "erin")
        rnd = open_exam(c, "erin", 2, days=31)
        opened = c.now
        h = halt(c, days=1)
        withdraw(c, h, days=4)                                # halted for exactly 4 days
        st = c.state()
        self.assertEqual(st.effective(opened, opened + 64 * DAY), 60 * DAY)
        ex = draw_exam(c, "erin", 2, rnd, days=0)             # drawn after the halt, inside the 7 days of its round
        c.now = opened + 64 * DAY                             # day 60 on the effective clock: still open
        self.assertFalse(ex.expired(c.now, c.state()))
        self.assertTrue(ex.expired(c.now))                    # on the wall it would be over
        c.add("exam_report", ex.examiners[0], {"candidate": "erin", "degree": 2, "verdict": "pass"})
        c.now += SEC
        c.add("exam_report", ex.examiners[1], {"candidate": "erin", "degree": 2, "verdict": "pass"})
        c.refused(self, "the exam has expired")
        st = c.state()
        ex = st.exams[("erin", 2)]
        self.assertEqual((ex.failed(c.now, st), ex.timed_out(c.now, st)), (False, True))   # no verdict: no penalty
        self.assertFalse(ex.timed_out(c.now - SEC, st))
        open_exam(c, "erin", 2)                               # at once
        self.assertEqual(c.state().exams[("erin", 2)].opened, c.now)

    def test_an_invitation_and_a_petition_lapse_on_the_effective_clock(self):
        c = lodge()
        invite(c, "alice")
        h = halt(c, days=10)
        withdraw(c, h, days=5)                                # 5 halted days
        c.now = T0 + 35 * DAY
        self.assertTrue(c.state().invited("alice", c.now))    # day 30 on the effective clock
        self.assertFalse(c.state().invited("alice", c.now + SEC))
        c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": ledger.canon.declaration_digest()})
        filed = c.now
        st = c.state()
        self.assertTrue(st.live("alice", filed + 180 * DAY))
        self.assertFalse(st.live("alice", filed + 180 * DAY + SEC))             # no halt since: wall time and effective time agree
        h2 = halt(c, days=90)
        st = c.state()
        self.assertTrue(st.live("alice", filed + 194 * DAY))                    # as things stand, 14 more days
        self.assertFalse(st.live("alice", filed + 194 * DAY + SEC))
        self.assertEqual(st.corrections[h2].act, "halt")

    def test_everything_else_stays_on_wall_time(self):
        c = lodge()
        new = c.key("ada-2")
        c.add("rekey", "ada", {"key": new, "proof": new})
        c.keys["ada"] = (None, new)
        c.add("depart", "carol", {})
        h = halt(c, days=1)                                   # 14 halted days, to T0 + 15 d
        st = c.state()
        self.assertEqual(st.effective(T0, T0 + 30 * DAY), 16 * DAY)
        newer = c.key("ada-3")
        c.now = T0 + 30 * DAY                                 # rekey interval: 30 wall days
        c.add("rekey", "ada", {"key": newer, "proof": newer})
        c.keys["ada"] = (None, newer)
        c.now = T0 + 90 * DAY                                 # rejoin wait: 90 wall days
        invite(c, "carol")
        st = c.state()
        self.assertEqual(st.members["ada"].key, newer)
        self.assertTrue(st.members["hiram"].dormant(T0 + 365 * DAY + 91 * DAY))  # dormancy: 365 wall days after the invite
        self.assertEqual(st.custodian_end(st.custodians["warden"]), T0 + 180 * DAY + SEC)   # silence: wall time
        self.assertEqual(st.span(st.corrections[h])[1], T0 + 15 * DAY)


class HoldRoom(unittest.TestCase):
    def test_a_hold_is_in_force_for_fourteen_days_or_until_it_is_ended(self):
        c = lodge()
        h = correct(c, "hold_room", {"login": "carol"}, "identity_fraud", days=1)
        st = c.state()
        m = st.members["carol"]
        self.assertTrue(ledger.room_held(st, m, T0 + DAY))
        self.assertTrue(ledger.room_held(st, m, T0 + 15 * DAY - SEC))
        self.assertFalse(ledger.room_held(st, m, T0 + 15 * DAY))
        self.assertFalse(ledger.room_held(st, m, T0))
        self.assertFalse(ledger.room_held(st, st.members["ada"], T0 + DAY))
        self.assertEqual(ledger.room_hold_until(st, m, T0 + DAY), T0 + 15 * DAY)
        self.assertIsNone(ledger.room_hold_until(st, m, T0 + 15 * DAY))
        c.add("work", "carol", {"ref": URL})                  # a hold stops no entry
        correct(c, "hold_room", {"login": "carol"})
        c.refused(self, "carol is already under a room hold")
        withdraw(c, h, days=2)
        st = c.state()
        self.assertFalse(ledger.room_held(st, st.members["carol"], c.now))
        self.assertEqual(st.corrections[h].subject, "carol")

    def test_a_hold_names_a_member(self):
        c = lodge()
        for login in ("nobody", "warden", "Carol"):
            correct(c, "hold_room", {"login": login})
            c.refused(self, "no such member")
        c.add("depart", "carol", {})
        correct(c, "hold_room", {"login": "carol"})
        c.refused(self, "no such member")


class Notes(unittest.TestCase):
    def note(self, c, action="hide", target="degree-07#12", rule="ROOMS.md#5", **kw):
        return correct(c, "note", {"action": action, "target": target, "rule": rule}, **kw)

    def test_a_note_records_an_act_outside_the_ledger_and_changes_nothing(self):
        c = lodge()
        before = c.state()
        n = self.note(c, days=1)
        st = c.state()
        self.assertEqual(st.notes, [{"seq": n, "by": "warden", "action": "hide", "target": "degree-07#12",
                                     "rule": "ROOMS.md#5", "reason_sha256": REASON, "time": c.now}])
        self.assertEqual(st.corrections, {})                 # a note is recorded, and is no correction
        self.assertEqual((st.members, st.ballots, st.custodians), (before.members, before.ballots, before.custodians))
        withdraw(c, n)
        c.refused(self, "no such correction")
        objection(c, n, "ada")
        c.refused(self, "no such correction")

    def test_the_fields_of_a_note_are_enumerated_and_strict(self):
        c = lodge()
        for action in ledger.NOTE_ACTIONS:
            self.note(c, action=action)
        c.now += DAY
        self.assertEqual(sorted(ledger.NOTE_ACTIONS), ["block", "hide", "limit", "lock", "other", "unblock"])
        self.note(c, action="delete")
        c.refused(self, r"note action must be one of \['block', 'hide', 'limit', 'lock', 'other', 'unblock'\]")
        for bad in ("", " issue", "issue 4", "a" * 121, "x\ny", "https://example.org/?q=1", "-x"):
            self.note(c, target=bad)
            c.refused(self, "note target: 1..120 of letters, digits and")
        for bad in ("", "see the rules", "r" * 65, "#5", "Art. X"):
            self.note(c, rule=bad)
            c.refused(self, "note rule: 1..64 of letters, digits and")
        for good in ("openmasonry/degree-07#12", "user:some-login", "discussion/4", "a" * 120, "org@team"):
            self.note(c, target=good)
        c.now += DAY
        c.add("correction", "warden", {"act": "note", "target": {"action": "hide", "target": "x"}, "ground": "protocol_defect",
                                       "reason_sha256": REASON})
        c.refused(self, "malformed correction entry: note target: missing field 'rule'")
        c.add("correction", "warden", {"act": "note", "target": {"action": "hide", "target": "x", "rule": "y"},
                                       "ground": "because", "reason_sha256": REASON})
        c.refused(self, "ground must be one of")               # a note needs a ground and a reason like any correction

    def test_notes_are_capped_at_ten_per_custodian_per_utc_day(self):
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "ada")))
        c.now = T0 + 12 * HOUR
        for i in range(10):
            self.note(c, target=f"issue:{i}")
        self.note(c, target="issue:10")
        c.refused(self, "at most 10 notes per custodian per UTC day")
        self.note(c, target="issue:10", by="keeper")            # the cap is per custodian
        c.now = T0 + DAY - SEC
        self.note(c, target="issue:11")
        c.refused(self, "at most 10 notes per custodian per UTC day")
        c.now = T0 + DAY                                        # the next UTC day
        self.note(c, target="issue:11")
        self.assertEqual((len(c.state().notes), c.state().corrections), (12, {}))


class Withdraw(unittest.TestCase):
    def test_any_live_custodian_ends_an_act_in_force(self):
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "ada")), witnesses=("tyler", "tiler"))
        sanction(c, "s", member="carol", by="carol")
        c.refused(self, "a member cannot open a sanction ballot on themselves")
        sanction(c, "s", member="carol", by="hiram")         # keeper, linked to ada, stays it; each custodian has a share of 3
        acts = [freeze(c, "carol"), correct(c, "freeze_witness", {"name": "tyler"}, by="keeper"),
                correct(c, "stay", {"ballot": "s"}, by="keeper"), correct(c, "hold_room", {"login": "carol"}), halt(c)]
        for i, seq in enumerate(acts):
            withdraw(c, seq, by="keeper" if i % 2 else "warden", days=1)
        st = c.state()
        for i, seq in enumerate(acts):
            k = st.corrections[seq]
            self.assertEqual((k.withdrawn, k.withdrawn_by, st.correction_status(k, c.now), st.span(k)[1]),
                             (T0 + (i + 1) * DAY, "keeper" if i % 2 else "warden", "withdrawn", T0 + (i + 1) * DAY))
        self.assertEqual((st.frozen("carol", c.now), st.witness_frozen("tyler", c.now), st.stayed("s", c.now),
                          st.room_hold("carol", c.now), st.halted(c.now)), (None,) * 5)

    def test_only_a_custodian_withdraws_and_only_what_is_in_force(self):
        c = lodge()
        withdraw(c, 5)
        c.refused(self, "entry 1: no such correction")
        f = freeze(c, "ada")
        withdraw(c, f, by="hiram")
        c.refused(self, "hiram is not a custodian")
        withdraw(c, f, days=1)
        withdraw(c, f)
        c.refused(self, "correction 1 is not in force")
        withdraw(c, 0)
        c.refused(self, "no such correction")


# ---------------------------------------------------------------- 6: objections ----

class Objections(unittest.TestCase):
    def test_the_number_that_voids_a_correction(self):
        self.assertEqual([objections_needed(e) for e in range(0, 17)], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4])
        for e in range(0, 200):
            self.assertEqual(objections_needed(e), max(1, -(-e // 5)))
            self.assertTrue(e == 0 or 5 * objections_needed(e) >= e)

    def test_one_objection_ends_a_freeze_when_e_is_at_most_five(self):
        c = lodge(founders=SEVEN)                            # E = 7 Masters − the linked member − the target = 5
        f = freeze(c, "ada", days=1)
        objection(c, f, "carol", days=2)
        st = c.state()
        k = st.corrections[f]
        self.assertEqual((k.objections, k.void, st.correction_status(k, c.now)), (("carol",), T0 + 3 * DAY, "void"))
        self.assertEqual(st.span(k), (T0 + DAY, T0 + 3 * DAY))                # it ended at that entry's time
        c.add("work", "ada", {"ref": URL})                   # in the same second
        objection(c, f, "dan")
        c.refused(self, "correction 1 is already void")
        withdraw(c, f)
        c.refused(self, "correction 1 is not in force")

    def test_two_objections_are_needed_when_e_is_six(self):
        st = hand_state(*(mk(f"m{i}") for i in range(8)), seq=5, head="44" * 32, time=T0,
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "m0", T0)})
        st.corrections[3] = Correction(3, "warden", "freeze_key", {"login": "m1"}, "key_compromised", REASON, T0,
                                       until=T0 + 30 * DAY, subject="m1")
        ledger._correction_object(st, {}, T0 + DAY, 6, "m2", {"seq": 3})
        self.assertEqual((st.corrections[3].objections, st.corrections[3].void), (("m2",), None))
        self.assertIsNotNone(st.frozen("m1", T0 + DAY))
        ledger._correction_object(st, {}, T0 + 2 * DAY, 7, "m3", {"seq": 3})
        self.assertEqual((st.corrections[3].objections, st.corrections[3].void), (("m2", "m3"), T0 + 2 * DAY))
        self.assertIsNone(st.frozen("m1", T0 + 2 * DAY))

    def test_e_counts_active_masters_without_the_linked_member_and_the_target(self):
        people = [mk(f"m{i}") for i in range(7)] + [mk("app", 1), mk("fellow", 2), mk("gone", status="departed"),
                                                     mk("asleep", activity=[T0 - 400 * DAY])]
        st = hand_state(*people, seq=5, head="44" * 32, time=T0,
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "m0", T0)})
        st.corrections[3] = Correction(3, "warden", "hold_room", {"login": "m1"}, "identity_fraud", REASON, T0,
                                       until=T0 + 14 * DAY, subject="m1")
        ledger._correction_object(st, {}, T0, 6, "m2", {"seq": 3})            # E = 5 (m2..m6): one is enough
        self.assertEqual(st.corrections[3].void, T0)

    def test_who_may_object(self):
        c = lodge(founders=SEVEN)
        initiate(c, "alice")
        f = freeze(c, "ada")
        objection(c, 99, "carol")
        c.refused(self, "no such correction")
        objection(c, f, "alice")
        c.refused(self, "only Master Builders may object to a correction")
        objection(c, f, "hiram")
        c.refused(self, "hiram is the member of the custodian who made correction")
        objection(c, f, "ada")
        c.refused(self, "the key of ada is frozen")           # the target of a freeze signs no objection at all
        hold = correct(c, "hold_room", {"login": "dan"})
        objection(c, hold, "dan")
        c.refused(self, f"dan is the target of correction {hold} and cannot object to it")
        objection(c, f, "warden")
        c.refused(self, "warden is not an active member")
        objection(c, f, "carol", days=1)
        self.assertEqual(c.state().corrections[f].void, c.now)

    def test_each_master_objects_once(self):
        st = hand_state(*(mk(f"m{i}") for i in range(13)), seq=5, head="44" * 32, time=T0,
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "m0", T0)})
        st.corrections[3] = Correction(3, "warden", "halt", {}, "attack_in_progress", REASON, T0, until=T0 + 14 * DAY)
        ledger._correction_object(st, {}, T0, 6, "m2", {"seq": 3})            # E = 12: three are needed
        with self.assertRaisesRegex(Invalid, "already objected to correction 3"):
            ledger._correction_object(st, {}, T0, 7, "m2", {"seq": 3})
        ledger._correction_object(st, {}, T0, 7, "m3", {"seq": 3})
        self.assertIsNone(st.corrections[3].void)
        ledger._correction_object(st, {}, T0 + DAY, 8, "m4", {"seq": 3})
        self.assertEqual((st.corrections[3].void, st.halted(T0 + DAY)), (T0 + DAY, None))

    def test_objections_are_accepted_until_ninety_days_after_the_correction(self):
        c = lodge()
        h = correct(c, "hold_room", {"login": "carol"}, days=1)
        c.now = T0 + 91 * DAY + SEC
        objection(c, h, "ada")
        c.refused(self, "objections to correction 1 closed 90 days after it")
        c.now = T0 + 91 * DAY                                  # long lapsed, still open to an objection: void for good
        objection(c, h, "ada")
        st = c.state()
        k = st.corrections[h]
        self.assertEqual((k.void, st.correction_status(k, c.now), st.span(k)[1]), (c.now, "void", T0 + 15 * DAY))

    def test_an_objection_ends_a_halt_and_a_stay(self):
        c = lodge()
        sanction(c, "s", member="carol")
        s = correct(c, "stay", {"ballot": "s"}, days=1)
        h = halt(c)
        objection(c, h, "ada", days=1)                         # accepted during the halt, and ends it
        objection(c, s, "carol")
        c.refused(self, f"carol is the target of correction {s}")
        objection(c, s, "ada")
        st = c.state()
        self.assertEqual((st.halted(c.now), st.stayed("s", c.now)), (None, None))
        self.assertEqual(st.effective(T0, T0 + 5 * DAY, "s"), 4 * DAY)         # the two pauses overlapped: counted once


# ---------------------------------------------------------------- 5: the effective clock ----

class EffectiveClock(unittest.TestCase):
    def state(self, *spans, stays=()):
        """A hand-built state with halts (and stays of ballot `b`) given as (start, days, withdrawn-after-days)."""
        st = hand_state(mk("hiram"), custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "hiram",
                                                                     T0 + 1000 * DAY)})
        for i, (act, (start, days, cut)) in enumerate([("halt", s) for s in spans] + [("stay", s) for s in stays]):
            st.corrections[i] = Correction(i, "warden", act, {"ballot": "b"} if act == "stay" else {}, "attack_in_progress",
                                           REASON, T0 + start * DAY, until=T0 + (start + days) * DAY,
                                           withdrawn=None if cut is None else T0 + (start + cut) * DAY)
        return st

    def test_without_pauses_it_is_wall_time(self):
        st = self.state()
        self.assertEqual(st.effective(T0, T0 + 9 * DAY), 9 * DAY)
        self.assertEqual(st.effective(T0, T0), timedelta(0))
        self.assertEqual(st.due(T0, 7 * DAY), T0 + 7 * DAY)
        self.assertTrue(st.waited(T0, T0 + 90 * DAY, 90) and not st.expired(T0, T0 + 90 * DAY, 90))
        self.assertTrue(st.expired(T0, T0 + 90 * DAY + SEC, 90) and not st.waited(T0, T0 + 90 * DAY - SEC, 90))

    def test_the_worked_example_of_the_specification(self):
        """A ballot opens at T0 with seven days to commit. The ledger is halted from day 3 for 14 days, and the
        halt is withdrawn on day 5; ballot b is stayed from day 4 for 14 days. Halt: [3, 5). Stay: [4, 18)."""
        st = self.state((3, 14, 2), stays=[(4, 14, None)])
        self.assertEqual(st.pauses(), [(T0 + 3 * DAY, T0 + 5 * DAY)])
        self.assertEqual(st.pauses("b"), [(T0 + 3 * DAY, T0 + 18 * DAY)])       # the two overlap: one interval
        self.assertEqual(st.effective(T0, T0 + 20 * DAY), 18 * DAY)             # every other clock lost two days
        self.assertEqual(st.effective(T0, T0 + 20 * DAY, "b"), 5 * DAY)          # the ballot's clock lost fifteen
        self.assertEqual(st.effective(T0, T0 + 4 * DAY, "b"), 3 * DAY)
        self.assertEqual(st.effective(T0 + 10 * DAY, T0 + 20 * DAY, "b"), 2 * DAY)
        self.assertEqual(st.due(T0, 7 * DAY), T0 + 9 * DAY)
        self.assertEqual(st.due(T0, 7 * DAY, "b"), T0 + 22 * DAY)
        self.assertEqual(st.due(T0 + 6 * DAY, 7 * DAY), T0 + 13 * DAY)           # after the halt: untouched
        self.assertEqual(st.due(T0, 2 * DAY), T0 + 2 * DAY)                      # before it: untouched
        spec = (REPO / "docs/whitepaper/SPEC.md").read_text(encoding="utf-8")
        for part in ("effective(T0, T0 + 20 d) = 18 d", "effective(T0, T0 + 20 d, b) = 5 d", "T0 + 22 d"):
            self.assertIn(part, spec)

    def test_only_the_time_inside_the_span_counts(self):
        st = self.state((10, 14, None))                                          # halted on [10, 24)
        for start, now, want in ((0, 10, 10), (0, 12, 10), (0, 24, 10), (0, 30, 16), (11, 13, 0), (12, 30, 6),
                                 (24, 30, 6), (30, 40, 10)):
            self.assertEqual(st.effective(T0 + start * DAY, T0 + now * DAY), want * DAY, (start, now))

    def test_due_is_the_last_second_within_the_span(self):
        st = self.state((7, 14, None))                                           # the halt begins on the deadline itself
        self.assertEqual(st.due(T0, 7 * DAY), T0 + 21 * DAY)
        for span in (DAY, 7 * DAY, 30 * DAY):
            due = st.due(T0, span)
            self.assertLessEqual(st.effective(T0, due), span)
            self.assertGreater(st.effective(T0, due + SEC), span)

    def test_a_pause_ends_at_the_earliest_of_its_lapse_its_withdrawal_its_voiding_and_the_end_of_its_key(self):
        st = self.state((0, 14, None))
        k, w = st.corrections[0], st.custodians["warden"]
        self.assertEqual(st.span(k)[1], T0 + 14 * DAY)
        k.withdrawn = T0 + 9 * DAY
        self.assertEqual(st.span(k)[1], T0 + 9 * DAY)
        k.void = T0 + 6 * DAY
        self.assertEqual(st.span(k)[1], T0 + 6 * DAY)
        w.revoked = T0 + 4 * DAY
        self.assertEqual(st.span(k)[1], T0 + 4 * DAY)
        st.sunset = T0 + 2 * DAY
        self.assertEqual(st.span(k)[1], T0 + 2 * DAY)
        w.alive = T0 - 180 * DAY                                                 # silent since: lapsed one second after T0
        self.assertEqual(st.span(k), (T0, T0 + SEC))
        w.alive = T0 - 200 * DAY                                                 # an end before the start is an empty span
        self.assertEqual(st.span(k), (T0, T0))
        self.assertEqual(st.pauses(), [])

    def test_no_deadline_is_ever_rewritten(self):
        c = lodge()
        sanction(c, "s", member="carol")
        invite(c, "alice")
        before = c.state()
        h = halt(c, days=1)
        s_ = c.state()
        withdraw(c, h, days=2)
        after = c.state()
        for st in (s_, after):
            self.assertEqual((st.ballots["s"].commit_until, st.ballots["s"].reveal_until, st.ballots["s"].opened,
                              st.invitations["alice"]["time"], st.corrections[h].until),
                             (before.ballots["s"].commit_until, before.ballots["s"].reveal_until, T0, T0, T0 + 15 * DAY))

    def test_what_an_earlier_replay_answered_no_later_entry_changes(self):
        """Eager and lazy agree: every answer a prefix of the ledger gave about its own time is the answer the
        whole ledger gives about that time, though later entries end pauses early."""
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "ada")), witnesses=("tyler",))
        sanction(c, "s", member="carol", by="ada")
        invite(c, "alice")
        s = correct(c, "stay", {"ballot": "s"}, days=1)
        h = halt(c, days=1)
        c.add("custodian_alive", "keeper", {}, days=1)
        withdraw(c, h, by="keeper", days=1)
        commit(c, "s", "hiram")
        c.refused(self, "ballot s is stayed")
        c.add("work", "carol", {"ref": URL}, days=1)
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke", days=1)   # ends the stay too
        commit(c, "s", "hiram", "yes")
        f = freeze(c, "carol", by="keeper", days=1)
        objection(c, f, "hiram", days=1)
        c.add("work", "carol", {"ref": URL}, days=30)
        whole = c.state()

        def answers(st, t):
            b = st.ballots.get("s")
            return (st.effective(T0, t), st.effective(T0, t, "s"), st.halted(t) is not None, st.stayed("s", t) is not None,
                    st.frozen("carol", t) is not None, st.invited("alice", t),
                    b is not None and st.ballot_time(b, t),
                    {n: st.custodian_status(k, t) for n, k in st.custodians.items()},
                    {n: st.correction_status(k, t) for n, k in st.corrections.items() if n in whole.corrections
                     and st.seq >= n})
        for i in range(3, len(c.entries) + 1):                # from the entry after which the ballot and the invitation exist
            prefix = replay(c.entries[:i], verifier=by_key)
            t = prefix.time
            got, want = answers(prefix, t), answers(whole, t)
            self.assertEqual(got[:7], want[:7], i)
            self.assertEqual(got[7], want[7], i)
            self.assertEqual(got[8], {n: v for n, v in want[8].items() if n in got[8]}, i)
        self.assertEqual(whole.span(whole.corrections[s]), (T0 + DAY, T0 + 6 * DAY))
        self.assertEqual(whole.span(whole.corrections[h]), (T0 + 2 * DAY, T0 + 4 * DAY))


# ---------------------------------------------------------------- gates ----

class IdentityGate(unittest.TestCase):
    def test_any_pull_request_author_may_carry_custodian_entries(self):
        c = lodge()
        f = freeze(c, "ada")
        c.add("custodian_alive", "warden", {}, days=1)
        withdraw(c, f)
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke")
        no_net = mock.Mock(side_effect=AssertionError("no lookup for a custodian entry"))
        for author in ("hiram", "carol", "somebody-else"):
            self.assertEqual(identity.pr_problems(c.entries, 1, author, fetch=no_net, fetch_user=no_net), [])

    def test_an_objection_and_a_custodian_type_by_a_stranger_are_still_bound_to_their_author(self):
        c = lodge()
        f = freeze(c, "ada")
        objection(c, f, "carol")
        no_net = mock.Mock(side_effect=AssertionError("no lookup"))
        bad = identity.pr_problems(c.entries, 2, "mallory", fetch=no_net, fetch_user=no_net, author_id=gid("mallory"))
        self.assertEqual(bad, [f"entry 2 (correction_object): carol is the GitHub account with id {gid('carol')}, but the "
                               f"pull request is by the account with id {gid('mallory')}"])
        self.assertEqual(identity.pr_problems(c.entries, 2, "Carol", fetch=no_net, fetch_user=no_net, author_id=gid("carol")), [])
        d = lodge()
        d.add("custodian_alive", "mallory", {})               # not a custodian: replay refuses it, and the author rule holds
        bad = identity.pr_problems(d.entries, 1, "ada", fetch=no_net, fetch_user=no_net, author_id=gid("ada"))
        self.assertIn("entry 1 (custodian_alive) has actor mallory, but the pull request is by ada", bad)
        self.assertIn("entry 1: mallory is not a custodian", bad)

    def rekeyed(self):
        c = lodge()
        new = c.key("ada-2")
        c.add("rekey", "ada", {"key": new, "proof": new})
        return c, (lambda login: [new + " laptop"])

    def test_a_rekey_comes_from_the_members_own_github_account(self):
        c, keys = self.rekeyed()
        no_user = mock.Mock(side_effect=AssertionError("the id of the pull request event is enough"))
        self.assertEqual(identity.pr_problems(c.entries, 1, "ada", fetch=keys, fetch_user=no_user, author_id=gid("ada")), [])
        bad = identity.pr_problems(c.entries, 1, "ada", fetch=keys, fetch_user=no_user, author_id=gid("ada") + 1)
        self.assertEqual(bad, [f"entry 1 (rekey): ada is the GitHub account with id {gid('ada')}, but the pull request is by "
                               f"the account with id {gid('ada') + 1}"])

    def test_without_the_event_id_the_author_is_looked_up_and_a_failure_fails_closed(self):
        c, keys = self.rekeyed()
        self.assertEqual(identity.pr_problems(c.entries, 1, "ada", fetch=keys,
                                              fetch_user=lambda login: {"id": gid("ada"), "login": "ada"}), [])
        bad = identity.pr_problems(c.entries, 1, "ada", fetch=keys, fetch_user=lambda login: {"id": 5, "login": "ada"})
        self.assertIn("but the pull request is by the account with id 5", bad[0])

        def down(login):
            raise OSError("network unreachable")
        bad = identity.pr_problems(c.entries, 1, "ada", fetch=keys, fetch_user=down)
        self.assertEqual(len(bad), 1)
        self.assertIn("cannot fetch https://api.github.com/users/ada (network unreachable); refusing (fail closed)", bad[0])


class ReasonsGate(unittest.TestCase):
    def tree(self):
        root = copy_governed(tmpdir(self) / "tree")
        (root / "ledger" / "reasons").mkdir(parents=True)
        return root

    def chain(self):
        c = lodge()
        correct(c, "hold_room", {"login": "carol"})
        correct(c, "note", {"action": "hide", "target": "issue:1", "rule": "ROOMS.md"},
                reason=hashlib.sha256(b"second\n").hexdigest())
        return c

    def test_the_tree_holds_the_reason_of_every_correction_under_its_digest(self):
        root, st = self.tree(), self.chain().state()
        (root / "ledger" / "reasons" / f"{REASON}.md").write_bytes(REASON_TEXT)
        (root / "ledger" / "reasons" / f"{hashlib.sha256(b'second' + chr(10).encode()).hexdigest()}.md").write_bytes(b"second\n")
        self.assertEqual(govern.check_tree(st, root), [])
        (root / "ledger" / "reasons" / ".gitkeep").write_text("")
        self.assertEqual(govern.check_tree(st, root), [])

    def test_the_directory_holds_nothing_but_the_reasons_of_corrections(self):
        """A pull request that adds entries may add reason files with no review: the gate lets in only a text
        that a signed correction pins, so the directory cannot be used to publish anything else."""
        root, st = self.tree(), self.chain().state()
        second = hashlib.sha256(b"second\n").hexdigest()
        other = hashlib.sha256(b"anything\n").hexdigest()
        reasons = root / "ledger" / "reasons"
        (reasons / f"{REASON}.md").write_bytes(REASON_TEXT)
        (reasons / f"{second}.md").write_bytes(b"second\n")
        (reasons / f"{other}.md").write_bytes(b"anything\n")                      # hashes to its name, but nobody pinned it
        (reasons / "README.md").write_text("notes")
        (reasons / "sub").mkdir()
        tail = ": no correction of the ledger pins this file (ledger/reasons/ holds only the public reasons of corrections, " \
               "each named after its sha256)"
        self.assertEqual(govern.check_tree(st, root),
                         [f"ledger/reasons/{name}{tail}" for name in sorted(["README.md", "sub", f"{other}.md"])])
        self.assertEqual(govern.stray_reasons(st, root), sorted(f"ledger/reasons/{n}" for n in ("README.md", "sub", f"{other}.md")))
        quiet = lodge(custodians=()).state()                                       # no custodian: no reason at all
        self.assertEqual(len(govern.check_tree(quiet, root)), 5)
        self.assertEqual(govern.stray_reasons(quiet, tmpdir(self)), [])            # no directory: nothing to refuse

    def test_a_missing_reason_makes_the_tree_of_its_own_pull_request_unlawful(self):
        root, st = self.tree(), self.chain().state()
        second = hashlib.sha256(b"second\n").hexdigest()
        (root / "ledger" / "reasons" / f"{second}.md").write_bytes(b"second\n")
        missing = [f"correction 1: ledger/reasons/{REASON}.md is missing (the public reason of a correction is "
                   "archived under its sha256)"]
        self.assertEqual(govern.check_tree(st, root, since=1), missing)          # the pull request that adds correction 1
        self.assertEqual(govern.check_tree(st, root, since=2), [])               # a later one: the reason is not asked again
        self.assertEqual((govern.check_tree(st, root), govern.tree_warnings(st, root)), ([], missing))    # the audit warns
        shutil.rmtree(root / "ledger")
        self.assertEqual((len(govern.check_tree(st, root, since=0)), len(govern.tree_warnings(st, root))), (2, 2))

    def test_a_reason_that_does_not_hash_to_its_name_makes_the_tree_unlawful(self):
        root, st = self.tree(), self.chain().state()
        second = hashlib.sha256(b"second\n").hexdigest()
        (root / "ledger" / "reasons" / f"{second}.md").write_bytes(b"second\n")
        path = root / "ledger" / "reasons" / f"{REASON}.md"
        path.write_bytes(REASON_TEXT + b"edited later\n")
        edited = hashlib.sha256(REASON_TEXT + b"edited later\n").hexdigest()
        self.assertEqual(govern.check_tree(st, root),
                         [f"correction 1: ledger/reasons/{REASON}.md has sha256 {edited[:12]}…, which is not its name"])
        path.unlink()
        path.symlink_to(root / "ledger" / "reasons" / f"{second}.md")
        self.assertIn("symlink", govern.check_tree(st, root)[0])
        path.unlink()
        path.write_bytes(b"x" * (govern.REASON_MAX_BYTES + 1))
        self.assertEqual(govern.check_tree(st, root),
                         [f"correction 1: ledger/reasons/{REASON}.md is larger than {govern.REASON_MAX_BYTES} bytes"])

    def test_replay_never_reads_the_reason(self):
        c = self.chain()
        with mock.patch("builtins.open", side_effect=AssertionError("replay opened a file")), \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("replay read a file")):
            st = replay(c.entries, verifier=by_key)
            self.assertEqual((len(st.corrections), len(st.notes)), (1, 1))

    def test_the_loader_reads_the_entries_directory_and_nothing_beside_it(self):
        c = self.chain()
        led = tmpdir(self) / "ledger"
        write_ledger(led / "entries", c.entries)
        (led / "reasons").mkdir()
        (led / "reasons" / f"{REASON}.md").write_bytes(REASON_TEXT)
        (led / "reasons" / ".gitkeep").write_text("")
        (led / "anchors").mkdir()
        self.assertEqual([e["seq"] for e in load(led / "entries")], [0, 1, 2])
        (led / "entries" / f"{REASON}.md").write_bytes(REASON_TEXT)               # inside the entries directory: refused
        with self.assertRaisesRegex(Invalid, "the directory holds only the entries"):
            load(led / "entries")

    def test_the_repository_has_the_directory(self):
        self.assertTrue((REPO / "ledger" / "reasons").is_dir())
        self.assertEqual(govern.REASONS_DIR, "ledger/reasons")

    def test_the_judge_lets_reasons_in_beside_entries_and_nothing_else(self):
        """The ledger-only rule of judge.yml, run as the workflow runs it: with entries a pull request may add
        reason files named after a sha256, and may not change or remove one."""
        text = (REPO / ".github/workflows/judge.yml").read_text(encoding="utf-8")
        m = re.search(r"awk -F'\\t' -v genesis=\"\$genesis\" '\n(.*?)'\)\n", text, re.S)
        self.assertIsNotNone(m, "the ledger-only rule is gone")
        program = m.group(1)
        self.assertIn(r'$1 == "A" && length($2) == 82 && $2 ~ /^ledger\/reasons\/[0-9a-f]+\.md$/ { next }', program)
        sha = "ab" * 32
        diff = "\n".join(["A\tledger/entries/0000/000007.json", f"A\tledger/reasons/{sha}.md", "A\tledger/anchors/000007.root.ots",
                          f"M\tledger/reasons/{sha}.md", f"D\tledger/reasons/{sha}.md", "A\tledger/reasons/readme.md",
                          f"A\tledger/reasons/{sha}.txt", f"A\tledger/reasons/{'AB' * 32}.md", f"A\tledger/reasons/x/{sha}.md",
                          f"A\tledger/reasons/{sha}0.md", "M\tREADME.md"]) + "\n"
        out = subprocess.run(["awk", "-F\t", "-v", "genesis=0", program], input=diff, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.splitlines(),
                         [f"M\tledger/reasons/{sha}.md", f"D\tledger/reasons/{sha}.md", "A\tledger/reasons/readme.md",
                          f"A\tledger/reasons/{sha}.txt", f"A\tledger/reasons/{'AB' * 32}.md", f"A\tledger/reasons/x/{sha}.md",
                          f"A\tledger/reasons/{sha}0.md", "M\tREADME.md"])


# ---------------------------------------------------------------- 8: reads ----

class Reads(unittest.TestCase):
    def test_the_state_report_lists_custodians_corrections_and_the_halt(self):
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "ada")))
        f = freeze(c, "carol", days=1)
        objection(c, f, "ada")
        c.add("custodian_revoke", "keeper", {"name": "keeper"}, key_of="keeper-revoke", days=1)
        n = correct(c, "note", {"action": "lock", "target": "issue:3", "rule": "ROOMS.md"})
        h = halt(c, days=1)
        hold = correct(c, "hold_room", {"login": "carol"})
        rep = state_report(c.state(), c.now + DAY)
        json.dumps(rep)                                       # plain data
        self.assertEqual(rep["schema"], "om.state/2")
        self.assertEqual(rep["custodians"], [
            {"name": "warden", "member": "hiram", "status": "live", "last_alive": iso(T0),
             "silence_deadline": iso(T0 + 180 * DAY), "removal_ballot": None, "ended_at": None},
            {"name": "keeper", "member": "ada", "status": "revoked", "last_alive": iso(T0),
             "silence_deadline": iso(T0 + 180 * DAY), "removal_ballot": None, "ended_at": iso(T0 + 2 * DAY)}])
        self.assertEqual((rep["custodian_threshold"], rep["sunset"]), (1, None))
        self.assertEqual(rep["halt"], {"halted": True, "correction": h, "since": iso(T0 + 3 * DAY), "until": iso(T0 + 17 * DAY)})
        rows = {r["seq"]: r for r in rep["corrections"]}
        self.assertEqual(rows[f], {"seq": f, "by": "warden", "act": "freeze_key", "class": "immediate",
                                   "target": {"login": "carol"}, "ground": "key_compromised", "reason_sha256": REASON,
                                   "time": iso(T0 + DAY), "status": "void", "objections": ["ada"], "ends": iso(T0 + DAY),
                                   "signers": [], "signers_needed": None, "notice_until": None, "apply_until": None,
                                   "applied": None})
        self.assertEqual((rows[n]["class"], rows[n]["status"], rows[n]["ends"]), ("note", "recorded", None))
        self.assertEqual((rows[h]["status"], rows[h]["ends"]), ("active", iso(T0 + 17 * DAY)))
        carol = next(m for m in rep["members"] if m["login"] == "carol")
        self.assertEqual((carol["frozen_until"], carol["room_hold_until"], carol["recovering"]),
                         (None, iso(T0 + 17 * DAY), False))
        self.assertEqual(rows[hold]["status"], "active")
        quiet = state_report(lodge(custodians=()).state(), T0)
        self.assertEqual((quiet["custodians"], quiet["corrections"], quiet["recoveries"], quiet["halt"]),
                         ([], [], [], {"halted": False, "correction": None, "since": None, "until": None}))

    def test_open_ballots_show_where_their_windows_fall_as_things_stand(self):
        c = lodge()
        sanction(c, "s", member="carol")
        s = correct(c, "stay", {"ballot": "s"}, days=1)
        withdraw(c, s, days=2)
        (row,) = state_report(c.state(), c.now)["open_ballots"]
        self.assertEqual((row["commit_until"], row["reveal_until"], row["stayed_until"]),
                         (iso(T0 + 9 * DAY), iso(T0 + 12 * DAY + ledger.REVEAL_GAP), None))

    def test_every_new_entry_type_has_its_own_line_in_the_dialog(self):
        c = lodge()
        st = c.state()
        base = {"seq": 9, "time": "2027-01-01T00:00:00Z", "actor": "warden"}
        cases = (
            ("correction", {"act": "freeze_key", "target": {"login": "ada"}, "ground": "key_compromised", "reason_sha256": REASON},
             ("FREEZE the key of ada for 30 days", "key_compromised", f"ledger/reasons/{REASON}.md", "depart, rekey",
              "It takes effect at once")),
            ("correction", {"act": "freeze_witness", "target": {"name": "tyler"}, "ground": "protocol_defect", "reason_sha256": REASON},
             ("FREEZE the witness tyler for 30 days",)),
            ("correction", {"act": "stay", "target": {"ballot": "s"}, "ground": "identity_fraud", "reason_sha256": REASON},
             ("STAY ballot s for up to 14 days", "identity_fraud")),
            ("correction", {"act": "halt", "target": {}, "ground": "attack_in_progress", "reason_sha256": REASON},
             ("HALT the ledger for up to 14 days", "attack_in_progress")),
            ("correction", {"act": "hold_room", "target": {"login": "carol"}, "ground": "identity_fraud", "reason_sha256": REASON},
             ("HOLD carol out of the rooms for up to 14 days",)),
            ("correction", {"act": "note", "target": {"action": "hide", "target": "issue:4", "rule": "ROOMS.md#5"},
                            "ground": "protocol_defect", "reason_sha256": REASON},
             ("NOTE a moderation act outside the ledger: hide issue:4 under ROOMS.md#5", "It changes nothing in the ledger")),
            ("correction", {"act": "void_ballot", "target": {"id": "s"}, "ground": "identity_fraud", "reason_sha256": REASON},
             ("VOID ballot s", "Nothing changes for 14 days", "within 7 days", "identity_fraud")),
            ("correction", {"act": "undo_ballot", "target": {"id": "adm"}, "ground": "identity_fraud", "reason_sha256": REASON},
             ("UNDO ballot adm", "Nothing changes for 14 days", "last 90 days")),
            ("correction_withdraw", {"seq": 4}, ("WITHDRAW correction 4",)),
            ("correction_cosign", {"seq": 4}, ("CO-SIGN correction 4", "changes nothing until it is applied")),
            ("correction_apply", {"seq": 4}, ("APPLY correction 4", "14 days of notice", "does not reverse it")),
            ("rekey_recover", {"key": fake_key("new"), "proof": "x"},
             ("recover your membership with a NEW key", "Master Builders co-sign it (2 after a freeze", "21 days after a freeze or 30 without one", "45 whenever",
              "whoever holds the old key can stop it")),
            ("rekey_oppose", {"login": "ada"}, ("OPPOSE the key recovery of ada",)),
            ("rekey_cosign", {"login": "ada"}, ("CO-SIGN the key recovery of ada",)),
            ("rekey_object", {}, ("STOP the recovery of your key", "90 days")),
            ("rekey_recover_apply", {}, ("COMPLETE the recovery of your key", "the old one is retired for good")),
            ("correction_object", {"seq": 4}, ("OBJECT to correction 4",)),
            ("custodian_alive", {}, ("SIGN OF LIFE of the custodian key warden", "180 days")),
            ("custodian_revoke", {"name": "warden"}, ("REVOKE the custodian key of warden", "for good")),
            ("custodian_claim", {"name": "keeper", "key": fake_key("keeper"), "revoke_key": fake_key("keeper-revoke"),
                                 "proof": "x", "revoke_proof": "x"}, ("CLAIM the office of Custodian again", "30 days")),
            ("custodian_claim_object", {"seq": 4}, ("OBJECT to the claim of the Custodian office of entry 4",)),
            ("custodian_claim_apply", {"seq": 4}, ("APPLY your claim of the Custodian office of entry 4",)),
            ("succession_claim", {}, ("CLAIM the succession", "90 days")),
        )
        for typ, body, parts in cases:
            text = actions.describe(st, base | {"type": typ, "body": body})
            for part in parts:
                self.assertIn(part, text, typ)
            self.assertNotIn('{"', text, typ)                 # never the raw JSON fallback
            self.assertIn("entry #9", text)
        self.assertEqual({t for t, _, _ in cases}, set(ledger.HANDLERS) - {
            "genesis", "invite", "petition", "vouch", "ballot_open", "ballot_commit", "ballot_reveal", "ballot_close",
            "exam_open", "exam_draw", "exam_report", "exam_recuse", "council_call", "council_draw", "work", "depart",
            "witness", "rekey"})

    def test_the_dialog_of_an_objection_names_what_it_objects_to(self):
        c = lodge()
        f = freeze(c, "ada")
        text = actions.describe(c.state(), {"seq": 2, "time": "2027-01-01T00:00:00Z", "actor": "carol",
                                            "type": "correction_object", "body": {"seq": f}})
        self.assertIn("freeze_key", text)
        self.assertIn("by the custodian warden", text)
        hostile = actions.describe(None, {"seq": 2, "time": "2027-01-01T00:00:00Z", "actor": "warden", "type": "correction",
                                          "body": {"act": "note\x1b[2J", "target": "x", "ground": 7}})
        self.assertNotIn("\x1b", hostile)

    def test_the_dialog_of_a_genesis_names_the_custodians(self):
        c = lodge()
        text = actions.describe(None, c.entries[0])
        self.assertIn("Custodians: warden (the member hiram)", text)
        self.assertIn("Custodians: none", actions.describe(None, lodge(custodians=()).entries[0]))


class GuideUnderCorrections(unittest.TestCase):
    """The Guide reads the same clock as the ledger, so what it lists is what the ledger would accept."""

    def steps(self, c, who, at=None):
        return [(s.action, s.why, s.due_by) for s in next_steps(c.state(), who, at or c.now)]

    def test_a_halted_ledger_offers_only_what_it_accepts(self):
        c = lodge()
        sanction(c, "s", member="carol")
        halt(c, days=1)
        for who in ("ada", "hiram"):
            steps = self.steps(c, who)
            self.assertEqual([a for a, _, _ in steps], ["wait", "depart"])
            self.assertIn("The ledger is halted until 2027-01-16T00:00:00Z (correction 2)", steps[0][1])
        self.assertEqual([a for a, _, _ in self.steps(c, "stranger")], ["wait"])
        self.assertIn("vote", [a for a, _, _ in self.steps(c, "ada", T0 + 15 * DAY)])       # it ended by itself

    def test_a_frozen_member_is_told_what_is_left_to_them(self):
        c = lodge()
        sanction(c, "s", member="carol", by="hiram")
        commit(c, "s", "ada")
        freeze(c, "ada", days=6)
        steps = self.steps(c, "ada")
        self.assertEqual([a for a, _, _ in steps], ["wait", "depart"])
        self.assertIn("Your key is frozen until 2027-02-06T00:00:00Z (correction 3, ground key_compromised)", steps[0][1])
        c.now = T0 + 7 * DAY + ledger.REVEAL_GAP + SEC
        self.assertEqual([a for a, _, _ in self.steps(c, "ada")], ["wait", "reveal", "depart"])
        reveal(c, "s", "ada")
        self.assertEqual(c.state().ballots["s"].reveals, {"ada": "yes"})

    def test_a_stayed_ballot_waits_and_its_deadlines_move_with_it(self):
        c = lodge()
        sanction(c, "s", member="carol")
        s = correct(c, "stay", {"ballot": "s"}, days=1)
        steps = self.steps(c, "hiram")
        self.assertNotIn("vote", [a for a, _, _ in steps])
        self.assertTrue(any("it is stayed until 2027-01-16T00:00:00Z (correction 2)" in why for _, why, _ in steps))
        withdraw(c, s, days=3)
        vote = next(x for x in self.steps(c, "hiram") if x[0] == "vote")
        self.assertEqual(vote[2], iso(T0 + 10 * DAY))                    # seven days to commit, three of them stayed
        c.now = T0 + 10 * DAY
        commit(c, "s", "hiram")
        self.assertIn("hiram", c.state().ballots["s"].commits)


class WitnessNode(unittest.TestCase):
    """The witness node (node/witness.py) signs nothing while the protocol would refuse its entries."""

    node, written = core.Witness.node, core.Witness.written

    def found(self, act, target, ground):
        c = Chain(tmpdir(self))
        now = datetime.now(timezone.utc).replace(microsecond=0)
        c.now = now - timedelta(days=20)
        c.add("genesis", "hiram", genesis_body(c, ["hiram", "ada"], ["tyler", "tiler"], custodians=("warden",)))
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness",
                                     "subject": witness_subject(c, "node2")})
        c.now = now - timedelta(hours=1)                      # the ballot has ended: a witness would close it now
        c.add("correction", "warden", {"act": act, "target": target, "ground": ground, "reason_sha256": REASON})
        self.chain = c
        w = self.node()
        reasons = w.LEDGER.parent / "reasons"
        reasons.mkdir(parents=True, exist_ok=True)
        (reasons / f"{REASON}.md").write_bytes(REASON_TEXT)
        return w

    def test_it_closes_nothing_while_the_ledger_is_halted_and_still_checkpoints(self):
        w = self.found("halt", {}, "attack_in_progress")
        w.cycle()
        self.assertEqual((self.written(w), self.alarms), (["witness"], []))        # the ended ballot waits; the checkpoint does not
        self.assertTrue(any("the ledger is halted until" in line and "(correction 2)" in line and "checkpoints go on" in line
                            for line in self.logs), self.logs)

    def test_it_signs_nothing_while_it_is_frozen_and_works_when_it_is_not(self):
        w = self.found("freeze_witness", {"name": "tyler"}, "key_compromised")
        w.cycle()
        self.assertEqual((self.written(w), self.alarms), ([], []))
        self.assertTrue(any("signing nothing: this witness is frozen until" in line for line in self.logs), self.logs)
        w = self.found("freeze_witness", {"name": "tiler"}, "key_compromised")     # the other witness is frozen
        w.cycle()
        self.assertEqual(self.written(w), ["ballot_close", "witness"])

    def test_it_raises_the_alarm_on_a_tree_whose_reason_was_altered(self):
        w = self.found("freeze_witness", {"name": "tiler"}, "key_compromised")
        (w.LEDGER.parent / "reasons" / f"{REASON}.md").write_bytes(REASON_TEXT + b"edited later\n")
        w.cycle()
        self.assertEqual(self.written(w), [])
        self.assertIn(f"correction 2: ledger/reasons/{REASON}.md has sha256", str(self.alarms[0]))

    def test_a_reason_the_tree_no_longer_holds_is_no_alarm(self):
        w = self.found("freeze_witness", {"name": "tiler"}, "key_compromised")
        (w.LEDGER.parent / "reasons" / f"{REASON}.md").unlink()
        w.cycle()
        self.assertEqual((self.written(w), self.alarms), (["ballot_close", "witness"], []))


# ---------------------------------------------------------------- 9: noticed acts ----

def quarry(**kw) -> Fast:
    """Seven founders and the custodian `warden`, linked to gus, who takes no part in the ballots below."""
    return lodge(custodians=(("warden", "gus"),), founders=SEVEN, **kw)


def fork(c: Fast) -> Fast:
    """The same chain so far, to be continued another way."""
    d = Fast()
    d.keys, d.entries, d.now = c.keys, list(c.entries), c.now
    return d


def void(c, bid, ground="identity_fraud", **kw) -> int:
    return correct(c, "void_ballot", {"id": bid}, ground, **kw)


def undo(c, bid, ground="identity_fraud", **kw) -> int:
    return correct(c, "undo_ballot", {"id": bid}, ground, **kw)


def cosign(c, seq, by, days=0.0):
    return c.add("correction_cosign", by, {"seq": seq}, days=days)


def apply_(c, seq, by="warden", days=0.0):
    return c.add("correction_apply", by, {"seq": seq}, days=days)


def advance(c, who, degree, days=31.0, close=True) -> str:
    """A whole advancement: the exam, passed by every examiner, and the ballot (closed unless `close` is false)."""
    c.exam(who, degree, days=days)
    bid = f"adv-{who}-{degree}"
    open_ballot(c, bid, who, "advancement", {"member": who, "degree": degree})
    if close:
        c.vote(bid, {x: "yes" for x in FOUNDERS})
    return bid


class Noticed(unittest.TestCase):
    """The life of a noticed act (SPEC section 6.19.9): pending, then applied, or never."""

    def test_a_noticed_act_changes_nothing_when_it_is_posted(self):
        c = quarry()
        sanction(c, "s", member="carol", by="ada", measure="suspend")
        commit(c, "s", "dan")
        before = c.state()
        v = void(c, "s", days=1)
        st = c.state()
        k = st.corrections[v]
        self.assertEqual((k.class_, k.act, k.target, k.ground, k.until, k.signers, k.applied, k.applied_by, k.subject),
                         ("noticed", "void_ballot", {"id": "s"}, "identity_fraud", None, ("warden",), None, "", "carol"))
        self.assertEqual((st.in_force(k, c.now), st.noticed_status(k, c.now), st.correction_status(k, c.now)),
                         (False, "pending", "pending"))
        self.assertEqual((st.notice_end(k), st.apply_end(k)), (T0 + 15 * DAY, T0 + 22 * DAY))
        self.assertEqual((st.ballots, st.members, st.exams), (before.ballots, before.members, before.exams))
        commit(c, "s", "eve", "no")                          # the ballot is paused under notice: nobody reads a vote meanwhile
        c.refused(self, "ballot s is paused while the correction that would void it is pending")
        self.assertEqual(sorted(c.state().ballots["s"].commits), ["dan"])
        self.assertEqual((ledger.NOTICE_DAYS, ledger.APPLY_WINDOW_DAYS, ledger.NOTICED_ACTS), (14, 7, ("void_ballot", "undo_ballot")))

    def test_it_is_applied_after_fourteen_days_of_wall_time_and_within_the_seven_that_follow(self):
        c = quarry()
        sanction(c, "s", member="carol", by="ada")
        v = void(c, "s")                                     # posted at T0
        for t in (T0, T0 + 14 * DAY - SEC):
            c.now = t
            apply_(c, v)
            c.refused(self, r"correction 2 is under notice until 2027-01-15T00:00:00Z \(14 days after it was posted\)")
        st = c.state()
        k = st.corrections[v]
        self.assertEqual([st.noticed_status(k, T0 + d * DAY + s * SEC) for d, s in ((13, 86399), (14, 0), (21, 0), (21, 1))],
                         ["pending", "ready", "ready", "expired"])
        late = fork(c)
        late.now = T0 + 21 * DAY + SEC
        apply_(late, v)
        late.refused(self, "correction 2 is expired: nothing to apply")
        last = fork(c)
        last.now = T0 + 21 * DAY                             # the last second
        apply_(last, v)
        self.assertEqual(last.state().ballots["s"].result, "voided")
        c.now = T0 + 14 * DAY                                # the first second
        apply_(c, v)
        st = c.state()
        k, b = st.corrections[v], st.ballots["s"]
        self.assertEqual((k.applied, k.applied_by, st.correction_status(k, c.now), b.result, b.corrected),
                         (c.now, "warden", "applied", "voided", v))
        apply_(c, v)
        c.refused(self, r"correction 2 was already applied \(a correction is applied once\)")
        withdraw(c, v)
        c.refused(self, "correction 2 is not in force or pending")
        self.assertEqual(c.state().correction_status(k, c.now + 400 * DAY), "applied")

    def test_a_halt_does_not_stretch_the_notice(self):
        c = quarry()
        sanction(c, "s", member="carol", by="ada")
        v = void(c, "s")
        halt(c, days=1)                                      # halted on [T0 + 1 d, T0 + 15 d)
        c.now = T0 + 14 * DAY
        apply_(c, v)                                         # a custodian entry, accepted during the halt, on wall time
        self.assertEqual(c.state().ballots["s"].result, "voided")

    def test_only_a_noticed_act_is_co_signed_or_applied(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN)
        f = freeze(c, "ada")
        n = correct(c, "note", {"action": "hide", "target": "issue:1", "rule": "ROOMS.md"})
        for typ in ("correction_cosign", "correction_apply"):
            c.add(typ, "keeper", {"seq": f})
            c.refused(self, rf"correction {f} is not a noticed act \(an immediate act is the act of one custodian key")
        for typ in ("correction_cosign", "correction_apply"):
            for seq in (n, 9):                               # a note is no correction: there is nothing to sign or apply
                c.add(typ, "keeper", {"seq": seq})
                c.refused(self, "no such correction")
            c.add(typ, "ada", {"seq": f})
            c.refused(self, "ada is not a custodian")

    def test_the_threshold_of_signers(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay"), ("porter", "eve")), founders=SEVEN, custodian_threshold=2)
        sanction(c, "s", member="carol", by="ada")
        v = void(c, "s")
        cosign(c, v, "warden")
        c.refused(self, f"warden already signed correction {v}")
        c.now = T0 + 14 * DAY
        apply_(c, v)
        c.refused(self, rf"correction {v} has 1 of the 2 custodian signature\(s\) it needs")
        cosign(c, v, "keeper")
        self.assertEqual(c.state().corrections[v].signers, ("warden", "keeper"))
        cosign(c, v, "porter")
        c.refused(self, rf"correction {v} already has the 2 custodian signature\(s\) it needs")
        gone = fork(c)
        gone.add("custodian_revoke", "keeper", {"name": "keeper"}, key_of="keeper-revoke")
        apply_(gone, v)                                      # a signer whose key is gone no longer counts
        gone.refused(self, rf"correction {v} has 1 of the 2 custodian signature\(s\) it needs")
        cosign(gone, v, "porter")                            # …and another may take the place
        apply_(gone, v)
        self.assertEqual(gone.state().ballots["s"].result, "voided")
        apply_(c, v, by="porter")                            # any live custodian applies, a signer or not
        k = c.state().corrections[v]
        self.assertEqual((k.applied_by, k.signers), ("porter", ("warden", "keeper")))

    def test_an_immediate_act_stays_the_act_of_one_key_whatever_the_threshold(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN, custodian_threshold=2)
        f = freeze(c, "ada")
        self.assertIsNotNone(c.state().frozen("ada", c.now))
        self.assertEqual(c.state().corrections[f].signers, ())

    def test_recusal_binds_the_author_every_co_signer_and_the_one_who_applies(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay"), ("porter", "eve")), founders=SEVEN, custodian_threshold=2)
        recusal = (r"recusal: the custodian {0} never voids or undoes a ballot whose subject, opener or sponsor is "
                   r"their own member \({1}\)")
        sanction(c, "by-fay", member="carol", by="fay")
        sanction(c, "on-eve", member="eve", by="ada")
        void(c, "by-fay", by="keeper")
        c.refused(self, recusal.format("keeper", "fay"))
        void(c, "on-eve", by="porter")
        c.refused(self, recusal.format("porter", "eve"))
        one, two = void(c, "by-fay"), void(c, "on-eve")
        cosign(c, one, "keeper")
        c.refused(self, recusal.format("keeper", "fay"))
        cosign(c, one, "porter")
        cosign(c, two, "keeper")
        c.now = T0 + 14 * DAY
        apply_(c, one, by="keeper")
        c.refused(self, recusal.format("keeper", "fay"))
        apply_(c, two, by="porter")
        c.refused(self, recusal.format("porter", "eve"))
        apply_(c, one)
        apply_(c, two, by="keeper")
        self.assertEqual([c.state().ballots[x].result for x in ("by-fay", "on-eve")], ["voided", "voided"])

    def test_no_correction_touches_an_amendment_or_the_removal_of_a_custodian(self):
        c = quarry()
        open_ballot(c, "am", "ada")
        open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"})
        for bid, kind in (("am", "amendment"), ("rm", "custodian")):
            void(c, bid)
            c.refused(self, f"a ballot of kind {kind} is never voided or undone by a correction")
            undo(c, bid)
            c.refused(self, "only an admission or an advancement is undone by a correction "
                            rf"\(ballot {bid} is of kind {kind}\)")
        void(c, "nope")
        c.refused(self, "no open ballot")
        undo(c, "nope")
        c.refused(self, "no such ballot")

    def test_the_grounds_are_the_closed_list_and_never_disagreement(self):
        for ground in ledger.GROUNDS:
            c = quarry()
            sanction(c, "s", member="carol", by="ada")
            v = void(c, "s", ground)
            if ground == "moderation":
                c.refused(self, "the ground moderation is the ground of a note, and of no other act")
                continue
            self.assertEqual(c.state().corrections[v].ground, ground)
        c = quarry()
        sanction(c, "s", member="carol", by="ada")
        for ground in ("disagreement", "wrong_outcome", ""):
            void(c, "s", ground)
            c.refused(self, "ground must be one of")
        self.assertNotIn("void_ballot", ledger.ACT_GROUND)
        self.assertNotIn("undo_ballot", ledger.ACT_GROUND)

    def test_noticed_acts_count_in_the_backstop_when_they_are_posted(self):
        c = quarry()
        for i in range(5):
            sanction(c, f"s{i}", member=SEVEN[i + 1], by="hiram" if i < 3 else "ada")     # three open ballots per opener
            void(c, f"s{i}")
        sanction(c, "w", member="ada", by="carol", measure="suspend")
        for act, target in (("void_ballot", {"id": "w"}), ("hold_room", {"login": "ada"})):
            correct(c, act, target)
            c.refused(self, "at most 5 corrections in any 30 days")
        c.now = T0 + 30 * DAY                                # counted from the day they were posted, not applied
        open_ballot(c, "w2", "carol", "sanction", {"member": "dan", "measure": "suspend"})
        void(c, "w2")
        self.assertEqual(c.state().corrections[c.state().seq].act, "void_ballot")

    def test_a_ballot_is_the_target_of_each_noticed_act_at_most_once(self):
        c = quarry()
        sanction(c, "s", member="carol", by="ada", measure="suspend")
        v = void(c, "s")
        void(c, "s")
        c.refused(self, rf"ballot s was the target of a void_ballot once already \(correction {v}\): a ballot is the "
                        "target of a void_ballot at most once")
        withdraw(c, v, days=1)
        self.assertEqual(c.state().correction_status(c.state().corrections[v], c.now), "withdrawn")
        void(c, "s")
        c.refused(self, "ballot s was the target of a void_ballot once already")
        apply_(c, v, days=14)
        c.refused(self, f"correction {v} is withdrawn: nothing to apply")
        cosign(c, v, "warden")
        c.refused(self, f"correction {v} is withdrawn: nothing to co-sign")

    def test_a_pending_act_dies_with_the_key_of_the_custodian_who_posted_it(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN)
        sanction(c, "s", member="carol", by="ada")
        v = void(c, "s")
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke", days=3)
        st = c.state()
        self.assertEqual((st.noticed_status(st.corrections[v], c.now), st.pending(st.corrections[v], c.now)), ("ended", False))
        self.assertEqual(st.noticed_status(st.corrections[v], T0 + 2 * DAY), "pending")      # earlier answers stand
        c.now = T0 + 14 * DAY
        apply_(c, v, by="keeper")
        c.refused(self, f"correction {v} is ended: nothing to apply")
        withdraw(c, v, by="keeper")
        c.refused(self, f"correction {v} is not in force or pending")


class NoticedObjections(unittest.TestCase):
    def test_one_objection_voids_a_pending_act_for_good_when_e_is_at_most_five(self):
        c = quarry()                                         # E = 7 Masters − gus − carol = 5
        sanction(c, "s", member="carol", by="ada")
        v = void(c, "s")
        objection(c, v, "carol", days=1)
        c.refused(self, f"carol is the target of correction {v} and cannot object to it")
        objection(c, v, "gus")
        c.refused(self, f"gus is the member of the custodian who made correction {v} and cannot object to it")
        objection(c, v, "dan")
        st = c.state()
        k = st.corrections[v]
        self.assertEqual((k.objections, k.void, st.noticed_status(k, c.now)), (("dan",), c.now, "void"))
        c.now = T0 + 14 * DAY
        apply_(c, v)
        c.refused(self, f"correction {v} is void: nothing to apply")
        self.assertIsNone(c.state().ballots["s"].result)

    def test_two_are_needed_when_e_is_six_and_the_member_of_a_co_signer_cannot_object(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN, custodian_threshold=2,
                  witnesses=("tyler",))
        open_ballot(c, "w", "ada", "witness", {"action": "remove", "name": "tyler"})
        v = void(c, "w")                                     # no subject: E = 7 − gus = 6, two are needed
        objection(c, v, "ada", days=1)
        self.assertIsNone(c.state().corrections[v].void)
        cosign(c, v, "keeper")
        objection(c, v, "fay")
        c.refused(self, f"fay is the member of a custodian who co-signed correction {v} and cannot object to it")
        objection(c, v, "carol")
        self.assertEqual(c.state().corrections[v].void, c.now)

    def test_an_objection_after_the_act_was_applied_is_on_the_record_and_reverses_nothing(self):
        c = quarry()
        sanction(c, "s", member="carol", by="ada")
        v = void(c, "s")
        apply_(c, v, days=14)
        objection(c, v, "dan", days=90)                      # the last second: 90 days after it was applied
        objection(c, v, "eve", days=1)
        c.refused(self, f"objections to correction {v} closed 90 days after it was applied")
        st = c.state()
        k = st.corrections[v]
        self.assertEqual((k.objections, k.void, st.noticed_status(k, c.now), st.ballots["s"].result),
                         (("dan",), None, "applied", "voided"))

    def test_a_noticed_act_that_was_never_applied_is_answerable_for_ninety_days(self):
        c = quarry()
        sanction(c, "s", member="carol", by="ada")
        v = void(c, "s")
        c.now = T0 + 90 * DAY
        objection(c, v, "dan")                               # long expired, still on the record: void
        self.assertEqual(c.state().corrections[v].void, c.now)
        d = fork(c)
        d.entries.pop()
        d.now = T0 + 90 * DAY + SEC
        objection(d, v, "dan")
        d.refused(self, f"objections to correction {v} closed 90 days after it")


class VoidBallot(unittest.TestCase):
    def test_a_ballot_is_paused_while_the_correction_that_would_void_it_is_pending(self):
        c = quarry(witnesses=("tyler",))
        sanction(c, "s", member="carol", by="ada", measure="suspend")
        for who in ("dan", "eve", "fay"):
            commit(c, "s", who)
        v = void(c, "s", days=1)                             # posted at T0 + 1 d, before any vote can be revealed
        paused = (rf"ballot s is paused while the correction that would void it is pending \(correction {v}, "
                  r"until 2027-01-23T00:00:00Z at the latest\)")
        commit(c, "s", "hiram")
        c.refused(self, paused)
        c.now = T0 + 11 * DAY                                # past its stored windows: its clock stands still
        reveal(c, "s", "dan")
        c.refused(self, paused)
        for who in ("ada", "tyler"):
            c.add("ballot_close", who, {"id": "s"})
            c.refused(self, paused)
        self.assertEqual(ledger.due_actions(c.state(), c.now), [])
        self.assertEqual(c.state().void_pending("s", c.now).seq, v)
        objected = fork(c)
        objection(objected, v, "dan")                        # the members say no: the ballot goes its way, ten days later
        st = objected.state()
        b = st.ballots["s"]
        self.assertEqual(st.ballot_due(b, b.reveal_until), b.reveal_until + 10 * DAY)
        objected.now = st.ballot_due(b, b.commit_until + ledger.REVEAL_GAP)
        for who in ("dan", "eve", "fay"):
            reveal(objected, "s", who)
        objected.now = st.ballot_due(b, b.reveal_until) + SEC
        self.assertEqual(ledger.due_actions(objected.state(), objected.now), [("ballot_close", {"id": "s"})])
        objected.add("ballot_close", "tyler", {"id": "s"})
        st = objected.state()
        self.assertEqual((st.ballots["s"].result, st.members["carol"].status), ("passed", "suspended"))
        expired = fork(c)
        expired.now = T0 + 22 * DAY + SEC                    # nobody applied it: it pauses the ballot no longer
        commit(expired, "s", "hiram")
        self.assertEqual(expired.state().pauses("s"), [(T0 + DAY, T0 + 22 * DAY + SEC)])
        apply_(c, v, days=4)
        st = c.state()
        self.assertEqual((st.ballots["s"].result, st.members["carol"].status), ("voided", "active"))
        c.add("ballot_close", "tyler", {"id": "s"})
        c.refused(self, "no open ballot")

    def test_a_stay_and_a_notice_compose(self):
        """The typical use: stay at once, void after notice. Both last fourteen days, so the stay has lapsed
        when the notice ends, and the ballot is voided all the same if it is still open."""
        c = quarry(witnesses=("tyler",))
        sanction(c, "s", member="carol", by="ada", measure="expel")
        for who in ("dan", "eve", "fay"):
            commit(c, "s", who)
        s = correct(c, "stay", {"ballot": "s"}, days=2)
        v = void(c, "s")                                     # the same second
        c.now = T0 + 16 * DAY - SEC
        apply_(c, v)
        c.refused(self, "is under notice until 2027-01-17T00:00:00Z")
        c.now = T0 + 16 * DAY
        st = c.state()
        self.assertIsNone(st.stayed("s", c.now))             # the stay lapsed in this very second
        self.assertEqual(st.correction_status(st.corrections[s], c.now), "lapsed")
        apply_(c, v)
        self.assertEqual(c.state().ballots["s"].result, "voided")

    def test_a_ballot_that_has_ended_is_neither_stayed_nor_voided(self):
        c = quarry(witnesses=("tyler",))
        sanction(c, "s", member="carol", by="ada", measure="expel")
        c.vote("s", {"dan": "yes", "eve": "yes", "fay": "yes"})
        c.entries.pop()                                      # everything but the close: the ballot has ended, and would pass
        for act, target in (("stay", {"ballot": "s"}), ("void_ballot", {"id": "s"})):
            correct(c, act, target)
            c.refused(self, "the reveal window of ballot s opened at 2027-01-08T06:15:00Z: a ballot is stayed, or its "
                            "voiding posted, only before any vote can be revealed")
        c.add("ballot_close", "tyler", {"id": "s"})
        self.assertEqual(c.state().members["carol"].status, "expelled")

    def test_a_voided_advancement_gives_the_exam_back_passed_and_unused(self):
        c = quarry()
        initiate(c, "alice")
        bid = advance(c, "alice", 2, close=False)
        commit(c, bid, "dan", "no")
        self.assertTrue(c.state().exams[("alice", 2)].consumed)
        v = void(c, bid, "protocol_defect")
        apply_(c, v, days=14)
        st = c.state()
        ex, b = st.exams[("alice", 2)], st.ballots[bid]
        self.assertEqual((ex.consumed, ex.passed(), ex.lapsed, ex.ballot_failed, st.members["alice"].degree),
                         (False, True, False, False, 1))
        self.assertEqual((b.result, b.commits, b.undo), ("voided", {"dan": commitment(bid, "dan", "no", salt_of("dan"))}, {}))
        open_ballot(c, "again", "alice", "advancement", {"member": "alice", "degree": 2})   # the same exam, a new ballot
        c.vote("again", {x: "yes" for x in FOUNDERS})
        self.assertEqual(c.state().members["alice"].degree, 2)

    def test_a_voided_admission_leaves_the_petition_live_with_its_sponsors(self):
        c = quarry()
        invite(c, "alice")
        c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": ledger.canon.declaration_digest()})
        c.add("vouch", "ada", {"candidate": "alice"})
        open_ballot(c, "adm", "ada", "admission", {"candidate": "alice"})
        v = void(c, "adm")
        apply_(c, v, days=14)
        st = c.state()
        self.assertEqual((st.ballots["adm"].result, st.petitions["alice"]["vouches"], st.live("alice", c.now)),
                         ("voided", ["hiram", "ada"], True))
        self.assertNotIn("alice", st.members)
        c.add("vouch", "carol", {"candidate": "alice"})     # the petition is as it was before the ballot: a third sponsor may join
        open_ballot(c, "adm-2", "hiram", "admission", {"candidate": "alice"})
        c.vote("adm-2", {x: "yes" for x in FOUNDERS})
        self.assertEqual(c.state().members["alice"].sponsors, ("hiram", "ada", "carol"))

    def test_a_voided_sanction_and_a_voided_witness_removal_vanish_as_decisions(self):
        c = quarry(witnesses=("tyler",))
        sanction(c, "s", member="carol", by="ada", measure="expel")
        open_ballot(c, "w", "ada", "witness", {"action": "remove", "name": "tyler"})
        one, two = void(c, "s"), void(c, "w", "attack_in_progress")
        apply_(c, one, days=14)
        apply_(c, two)
        st = c.state()
        self.assertEqual((st.ballots["s"].result, st.ballots["w"].result, st.members["carol"].status, sorted(st.witnesses)),
                         ("voided", "voided", "active", ["tyler"]))
        sanction(c, "s2", member="carol", by="ada", measure="expel")           # and the subject may be balloted again
        open_ballot(c, "s", "ada", "sanction", {"member": "dan", "measure": "admonish"})
        c.refused(self, "ballot id 's' is already used")
        for seq in (one, two):
            self.assertEqual(st.corrections[seq].applied, c.now)

    def test_only_an_open_ballot_is_voided_and_it_is_checked_again_when_the_act_is_applied(self):
        c = quarry()
        sanction(c, "s", member="carol", by="ada")
        c.vote("s", {"dan": "yes", "eve": "yes", "fay": "yes"})
        void(c, "s")
        c.refused(self, "no open ballot")
        sanction(c, "t", member="carol", by="ada")
        v = void(c, "t")
        objection(c, v, "dan")                               # voided by objection: the ballot closes in its own time
        c.vote("t", {"dan": "yes", "eve": "yes", "fay": "yes"})
        self.assertEqual(c.state().ballots["t"].result, "passed")


class UndoBallot(unittest.TestCase):
    """Compare-and-swap undo (SPEC section 6.19.8): all of what the ballot set, or nothing, and nothing else."""

    def admitted(self):
        c = quarry(witnesses=("tyler",))
        initiate(c, "alice")                                 # hiram invites and opens, ada vouches: gus has no part
        return c, c.now

    def test_a_passed_ballot_records_what_it_set(self):
        c, closed = self.admitted()
        bid = advance(c, "alice", 2)
        open_ballot(c, "w", "ada", "witness", witness_subject(c, "node2"))
        c.vote("w", {x: "yes" for x in FOUNDERS})
        sanction(c, "s", member="carol", by="ada")
        c.vote("s", {"dan": "yes", "eve": "yes", "fay": "yes"})
        st = c.state()
        adm, adv, wit = st.ballots["adm-alice"], st.ballots[bid], st.ballots["w"]
        self.assertEqual((wit.result, wit.undo), ("passed", {}))             # the addition of a witness is never undone
        self.assertEqual(adm.undo, {"member.admitted": ["", iso(closed)], "member.status": ["", "active"],
                                    "member.degree": [0, 1]})
        self.assertEqual(adv.undo, {"member.degree": [1, 2], "member.since": ["", iso(adv.closed)]})
        self.assertEqual((adm.closed, st.ballots["s"].undo, st.ballots["s"].closed), (closed, {}, c.now))
        json.dumps([adm.undo, adv.undo])                     # plain data
        spec = (REPO / "docs/whitepaper/SPEC.md").read_text(encoding="utf-8")
        self.assertIn("`undo = " + json.dumps(adm.undo) + "`", spec)       # the vector of section 6.7
        failed = fork(c)
        sanction(failed, "f", member="dan", by="ada")
        failed.add("ballot_close", "ada", {"id": "f"}, days=11)
        self.assertEqual((failed.state().ballots["f"].result, failed.state().ballots["f"].undo), ("lapsed", {}))

    def test_an_undone_admission_leaves_a_voided_record_that_may_be_invited_again_after_ninety_days(self):
        c, closed = self.admitted()
        u = undo(c, "adm-alice", days=1)
        st = c.state()
        self.assertEqual((st.corrections[u].class_, st.corrections[u].subject, st.members["alice"].status),
                         ("noticed", "alice", "active"))
        c.add("work", "alice", {"ref": URL})                 # nothing changes under notice
        apply_(c, u, days=14)
        st = c.state()
        m, b = st.members["alice"], st.ballots["adm-alice"]
        self.assertEqual((m.status, m.status_since, m.degree, m.since, m.sponsors, b.result, b.corrected),
                         ("voided", c.now, 1, {1: closed}, ("hiram", "ada"), "undone", u))
        self.assertEqual((m.is_active(c.now), st.active(c.now, 1) == sorted(SEVEN)), (False, True))
        for typ, body, refusal in (("work", {"ref": URL}, "alice is not an active member"),
                                   ("depart", {}, r"not a member who can depart \(not a member, already departed, expelled or voided\)"),
                                   ("rekey", {"key": c.key("a2"), "proof": c.key("a2")}, "not a member who can replace their key")):
            c.add(typ, "alice", body)
            c.refused(self, refusal)
        sanction(c, "x", member="alice", by="ada", measure="expel")
        c.refused(self, "no such member")                    # not a sanction, and out of the reach of one
        freeze(c, "alice")
        c.refused(self, "no such member")
        invite(c, "alice")
        c.refused(self, "alice is already a member")         # the ordinary wait of a login that left
        c.now += 90 * DAY
        petition(c, "alice")                                 # invited again, by the same account
        c.add("vouch", "ada", {"candidate": "alice"})
        open_ballot(c, "again", "hiram", "admission", {"candidate": "alice"})
        c.vote("again", {x: "yes" for x in FOUNDERS})
        again = c.state().members["alice"]
        self.assertEqual((again.status, again.degree, again.since, "adm-alice" in c.state().retired),
                         ("active", 1, {1: c.now}, True))     # the undone ballot ended over 111 days ago: retired

    def test_an_undone_advancement_takes_the_degree_and_its_date_and_marks_the_exam_void(self):
        c, _ = self.admitted()
        bid = advance(c, "alice", 2)
        u = undo(c, bid, "protocol_defect")
        apply_(c, u, days=14)
        st = c.state()
        m, ex = st.members["alice"], st.exams[("alice", 2)]
        self.assertEqual((m.degree, sorted(m.since), m.status, st.ballots[bid].result), (1, [1], "active", "undone"))
        self.assertEqual((ex.lapsed, ex.passed(), ex.failed(c.now, st), ex.consumed), (True, False, False, True))
        open_ballot(c, "again", "alice", "advancement", {"member": "alice", "degree": 2})
        c.refused(self, "examination not passed")            # the old exam supports nothing more
        rnd = open_exam(c, "alice", 2)                       # a new one at once: no retry wait
        self.assertEqual(c.state().exams[("alice", 2)].beacon_round, rnd)

    def test_the_addition_of_a_witness_is_never_undone(self):
        c = quarry(witnesses=("tyler",))
        open_ballot(c, "w", "ada", "witness", witness_subject(c, "node2"))
        c.vote("w", {x: "yes" for x in FOUNDERS})
        c.add("witness", "node2", checkpoint(c.state()))
        undo(c, "w", "key_compromised")
        c.refused(self, r"only an admission or an advancement is undone by a correction \(ballot w is of kind witness\)")
        correct(c, "freeze_witness", {"name": "node2"}, "key_compromised")     # what a custodian may do about a witness key
        self.assertIsNotNone(c.state().witness_frozen("node2", c.now))

    def test_the_undo_is_refused_when_what_the_ballot_set_was_changed_since(self):
        c, _ = self.admitted()
        u = undo(c, "adm-alice")
        suspended = fork(c)
        sanction(suspended, "s", member="alice", by="ada", measure="suspend")
        suspended.vote("s", {"dan": "yes", "eve": "yes", "fay": "yes"})
        suspended.now = c.now + 14 * DAY
        apply_(suspended, u)
        suspended.refused(self, r"the undo of ballot adm-alice no longer applies: member.status is 'suspended', not 'active' "
                                r"as the ballot left it \(nothing is undone unless everything the ballot changed still stands\)")
        left = fork(c)
        left.add("depart", "alice", {}, days=14)
        apply_(left, u)
        left.refused(self, "member.status is 'departed', not 'active'")
        self.assertEqual(left.state().members["alice"].status, "departed")

    def test_undoing_goes_newest_first(self):
        c, _ = self.admitted()
        bid = advance(c, "alice", 2)                         # closed about 52 days after the genesis
        first, second = undo(c, "adm-alice"), undo(c, bid)
        apply_(c, first, days=14)
        c.refused(self, "the undo of ballot adm-alice no longer applies: member.degree is 2, not 1 as the ballot left it")
        apply_(c, second)
        apply_(c, first)
        m = c.state().members["alice"]
        self.assertEqual((m.status, m.degree, sorted(m.since)), ("voided", 1, [1]))

    def test_an_advancement_is_not_undone_once_the_member_advanced_again(self):
        st = hand_state(mk("alice", 3), *(mk(f) for f in SEVEN), seq=9, head="55" * 32, time=T0 + 200 * DAY,
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "gus", T0 + 190 * DAY)},
                        custodian_threshold=1)
        st.members["alice"].since = {1: T0, 2: T0 + 40 * DAY, 3: T0 + 180 * DAY}
        st.ballots["adv2"] = Ballot("adv2", "advancement", {"member": "alice", "degree": 2}, frozenset(SEVEN), T0 + 37 * DAY,
                                    T0 + 40 * DAY, "alice", result="passed", frozen={"admitted": iso(T0)},
                                    opened=T0 + 30 * DAY, closed=T0 + 40 * DAY,
                                    undo={"member.degree": [1, 2], "member.since": ["", iso(T0 + 40 * DAY)]})
        st.corrections[5] = Correction(5, "warden", "undo_ballot", {"id": "adv2"}, "identity_fraud", REASON, T0 + 130 * DAY,
                                       class_="noticed", subject="alice", signers=("warden",))
        e = {"seq": 10, "prev": st.head, "time": iso(T0 + 200 * DAY), "type": "correction_apply", "actor": "warden",
             "body": {"seq": 5}, "sig": fake_key("warden")}
        with self.assertRaisesRegex(Invalid, "is expired"):
            apply(copy.deepcopy(st), e, by_key)
        st.corrections[5].time = T0 + 185 * DAY
        with self.assertRaisesRegex(Invalid, "the undo of ballot adv2 no longer applies: member.degree is 3, not 2 as the ballot left it"):
            apply(copy.deepcopy(st), e, by_key)
        st.members["alice"].degree, st.members["alice"].since = 2, {1: T0, 2: T0 + 41 * DAY}       # another date: another advancement
        with self.assertRaisesRegex(Invalid, "member.since is '2027-02-11T00:00:00Z', not '2027-02-10T00:00:00Z'"):
            apply(copy.deepcopy(st), e, by_key)
        st.members["alice"].since = {1: T0, 2: T0 + 40 * DAY}
        st.members["alice"].status = "suspended"             # a suspension did not touch what the ballot set
        apply(st, e, by_key)
        self.assertEqual((st.members["alice"].degree, st.members["alice"].since, st.members["alice"].status),
                         (1, {1: T0}, "suspended"))

    def test_only_a_ballot_that_passed_in_the_last_ninety_days_is_undone(self):
        c, closed = self.admitted()
        sanction(c, "s", member="carol", by="ada")
        c.vote("s", {"dan": "yes", "eve": "yes", "fay": "yes"})
        open_ballot(c, "w", "ada", "witness", {"action": "remove", "name": "tyler"})
        c.vote("w", {x: "yes" for x in FOUNDERS})
        for bid, kind in (("s", "sanction"), ("w", "witness")):
            undo(c, bid)
            c.refused(self, "only an admission or an advancement is undone by a correction "
                            rf"\(ballot {bid} is of kind {kind}\)")
        petition(c, "bob")
        c.add("vouch", "ada", {"candidate": "bob"})
        open_ballot(c, "adm-bob", "hiram", "admission", {"candidate": "bob"})
        undo(c, "adm-bob")
        c.refused(self, r"only a ballot that passed is undone \(ballot adm-bob is still open\)")
        c.vote("adm-bob", {"hiram": "yes", "ada": "yes", "carol": "no"})
        undo(c, "adm-bob")
        c.refused(self, r"only a ballot that passed is undone \(ballot adm-bob failed\)")
        c.now = closed + 90 * DAY + SEC
        undo(c, "adm-alice")
        c.refused(self, r"ballot adm-alice closed more than 90 days ago \(a ballot is undone only by a correction posted "
                        r"within 90 days of its close\)")
        c.now = closed + 90 * DAY                            # the last second; it is applied after the ninety days
        u = undo(c, "adm-alice")
        undo(c, "adm-alice")
        c.refused(self, rf"ballot adm-alice was the target of a undo_ballot once already \(correction {u}\)")
        apply_(c, u, days=14)
        self.assertEqual((c.state().members["alice"].status, ledger.UNDO_WINDOW_DAYS), ("voided", 90))

    def test_no_ballot_is_voided_or_undone_twice(self):
        c, _ = self.admitted()
        u = undo(c, "adm-alice")
        apply_(c, u, days=14)
        apply_(c, u)
        c.refused(self, rf"correction {u} was already applied \(a correction is applied once\)")
        void(c, "adm-alice")
        c.refused(self, "no open ballot")
        st = hand_state(*(mk(f) for f in SEVEN), seq=9, head="55" * 32, time=T0,
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "gus", T0)})
        st.ballots["w"] = Ballot("w", "admission", {"candidate": "n"}, frozenset(SEVEN), T0, T0,
                                 "ada", result="voided", opened=T0, corrected=4)
        with self.assertRaisesRegex(Invalid, r"ballot w was already voided or undone \(correction 4\)"):
            ledger._act_undo_ballot(st, st.custodians["warden"], {"id": "w"}, "identity_fraud", T0, 10)
        st.ballots["w"].result = "undone"
        with self.assertRaisesRegex(Invalid, r"ballot w was already voided or undone \(correction 4\)"):
            ledger._act_undo_ballot(st, st.custodians["warden"], {"id": "w"}, "identity_fraud", T0, 10)
        with self.assertRaisesRegex(Invalid, "no open ballot"):
            ledger._act_void_ballot(st, st.custodians["warden"], {"id": "w"}, "identity_fraud", T0, 10)

    def test_a_custodian_never_undoes_a_ballot_their_member_sponsored(self):
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "ada"), ("porter", "gus")), founders=SEVEN)
        initiate(c, "alice")
        for by, member in (("warden", "hiram"), ("keeper", "ada")):
            undo(c, "adm-alice", by=by)
            c.refused(self, rf"recusal: the custodian {by} never voids or undoes a ballot whose subject, opener or sponsor "
                            rf"is their own member \({member}\)")
        u = undo(c, "adm-alice", by="porter")
        self.assertEqual(c.state().corrections[u].by, "porter")

    def test_an_undone_admission_takes_the_member_out_of_what_is_still_open_but_not_out_of_an_electorate(self):
        """Hand-built: a member of the 1st degree is seldom an elector, a sponsor or an examiner, but an undo
        may follow the undo of her advancements."""
        now = T0 + 50 * DAY
        st = hand_state(mk("alice", 1, T0 + 10 * DAY), mk("bob", 1), *(mk(f) for f in SEVEN), seq=9, head="55" * 32, time=now,
                        custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("w-r"), "gus", T0)},
                        custodian_threshold=1)
        adm = Ballot("adm", "admission", {"candidate": "alice"}, frozenset(SEVEN), T0 + 7 * DAY, T0 + 10 * DAY, "hiram",
                     result="passed", opened=T0, closed=T0 + 10 * DAY, frozen={"key": fake_key("alice"), "vouches": ["hiram"],
                                                                                "github_id": 5},
                     undo={"member.admitted": ["", iso(T0 + 10 * DAY)], "member.status": ["", "active"], "member.degree": [0, 1]})
        vote = Ballot("s", "sanction", {"member": "bob", "measure": "admonish"}, frozenset({"alice", "ada", "carol", "dan"}),
                      now - 9 * DAY, now - DAY, "ada", opened=now - 16 * DAY, frozen={"admitted": iso(T0)},
                      commits={x: "c" for x in ("alice", "ada", "carol", "dan")},
                      reveals={"alice": "no", "ada": "yes", "carol": "yes", "dan": "no"})
        done = Ballot("old", "sanction", {"member": "bob", "measure": "admonish"}, frozenset({"alice", "ada"}), T0, T0, "ada",
                      result="failed", reveals={"alice": "no"})
        st.ballots = {"adm": adm, "s": vote, "old": done}
        st.petitions = {"zed": {"key": fake_key("zed"), "vouches": ["alice", "ada"], "time": now, "github_id": 9}}
        st.invitations = {"yan": {"by": "alice", "github_id": 8, "time": now}, "xi": {"by": "ada", "github_id": 7, "time": now}}
        st.exams[("bob", 2)] = Exam("bob", 2, ("alice", "carol"), opened=now, k=2, ranking=("alice", "carol", "dan"),
                                    pool=("alice", "carol", "dan"))
        st.corrections[5] = Correction(5, "warden", "undo_ballot", {"id": "adm"}, "identity_fraud", REASON, now - 14 * DAY,
                                       class_="noticed", subject="alice", signers=("warden",))
        apply(st, {"seq": 10, "prev": st.head, "time": iso(now), "type": "correction_apply", "actor": "warden",
                   "body": {"seq": 5}, "sig": fake_key("warden")}, by_key)
        self.assertEqual(st.members["alice"].status, "voided")
        self.assertEqual((vote.electors, vote.reveals["alice"], vote.commits["alice"]),
                         (frozenset({"alice", "ada", "carol", "dan"}), "no", "c"))    # no electorate shrinks: her vote stands…
        self.assertEqual(done.electors, frozenset({"alice", "ada"}))                   # …and a closed ballot is not touched
        self.assertEqual((st.petitions["zed"]["vouches"], sorted(st.invitations)), (["ada"], ["xi"]))
        ex = st.exams[("bob", 2)]
        self.assertEqual((ex.examiners, ex.recused), (("carol", "dan"), ("alice",)))
        ledger._ballot_close(st, {}, now, 11, "ada", {"id": "s"})
        self.assertEqual(vote.result, "failed")                                        # …and is counted: 2 yes and 2 no of 4


class FounderFollowsTheLogin(unittest.TestCase):
    def test_a_founder_who_returns_is_still_a_founder_and_never_one_of_the_seven(self):
        c = lodge(founders=["hiram", "ada", "carol"])
        c.add("depart", "carol", {})
        c.now = T0 + 90 * DAY
        petition(c, "carol")
        c.add("vouch", "ada", {"candidate": "carol"})
        open_ballot(c, "back", "hiram", "admission", {"candidate": "carol"})
        c.vote("back", {"hiram": "yes", "ada": "yes"})
        m = c.state().members["carol"]
        self.assertEqual((m.degree, m.founder, m.since), (1, True, {1: c.now}))
        people = [mk(f"m{i}") for i in range(6)] + [mk("back", founder=True)]
        st = hand_state(mk("hiram", founder=True), *people, witnesses={f"w{i}": fake_key(f"w{i}") for i in range(4)})
        self.assertFalse(ledger.sunset_reached(st, T0))      # six Masters who are not founders, and one who is
        st.members["back"].founder = False
        self.assertTrue(ledger.sunset_reached(st, T0))


class NeverGrant(unittest.TestCase):
    """Landmark VI: a repair may undo, freeze or pause but never grant. Property-style: random runs of every
    entry a custodian can sign, with objections in between, over a ledger with members, open and closed
    ballots, exams, a petition, an invitation and witnesses. After each accepted entry the state is compared
    with the one before it."""

    @classmethod
    def setUpClass(cls):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN, witnesses=("tyler",), custodian_threshold=1)
        initiate(c, "alice")
        advance(c, "alice", 2)
        initiate(c, "bob")
        open_ballot(c, "w", "ada", "witness", witness_subject(c, "node2"))
        c.vote("w", {x: "yes" for x in FOUNDERS})
        sanction(c, "sus", member="dan", by="ada", measure="suspend")
        c.vote("sus", {"hiram": "yes", "carol": "yes", "eve": "yes"})
        petition(c, "zoe")
        c.add("vouch", "ada", {"candidate": "zoe"})
        open_ballot(c, "adm-zoe", "hiram", "admission", {"candidate": "zoe"})
        commit(c, "adm-zoe", "carol", "no")
        invite(c, "yan", by="ada")
        advance(c, "bob", 2, days=22.0, close=False)
        commit(c, "adv-bob-2", "carol")
        sanction(c, "open", member="eve", by="ada", measure="expel")
        commit(c, "open", "carol")
        open_ballot(c, "w2", "ada", "witness", witness_subject(c, "node3"))
        cls.chain = c

    @staticmethod
    def facts(st):
        return {
            "members": {l: (m.degree, m.status, m.key, m.sponsors, tuple(sorted(m.since)), m.seat_until, m.founder)
                        for l, m in st.members.items()},
            "witnesses": dict(st.witnesses), "pins": dict(st.pins),
            "petitions": {l: (p["key"], tuple(p["vouches"]), p["time"]) for l, p in st.petitions.items()},
            "invitations": {l: (i["by"], i["time"]) for l, i in st.invitations.items()},
            "ballots": {b.id: (dict(b.commits), dict(b.reveals), b.electors, b.result, b.kind, b.subject, b.commit_until,
                               b.reveal_until) for b in st.ballots.values()},
            "exams": {k: (ex.passed(), dict(ex.reports)) for k, ex in st.exams.items()},
            "custodians": {n: (k.key, k.revoked) for n, k in st.custodians.items()},
            "retired": set(st.retired),
        }

    def never_granted(self, old, new, what):
        self.assertEqual(set(new["members"]), set(old["members"]), what)                 # nobody is admitted
        for login, (degree, status, key, sponsors, since, seat, founder) in new["members"].items():
            d0, s0, k0, sp0, since0, seat0, f0 = old["members"][login]
            self.assertLessEqual(degree, d0, what)                                        # no degree rises
            self.assertTrue(status == s0 or (s0 == "active" and status == "voided"), what)   # no status is restored
            self.assertEqual((key, sponsors, seat, founder), (k0, sp0, seat0, f0), what)
            self.assertLessEqual(set(since), set(since0), what)
        self.assertLessEqual(set(new["witnesses"].items()), set(old["witnesses"].items()), what)   # no witness is added
        self.assertEqual(new["pins"], old["pins"], what)
        self.assertLessEqual(set(new["petitions"]), set(old["petitions"]), what)
        for login, (key, vouches, time) in new["petitions"].items():
            self.assertEqual((key, time), (old["petitions"][login][0], old["petitions"][login][2]), what)
            self.assertLessEqual(set(vouches), set(old["petitions"][login][1]), what)    # no sponsor is added
        self.assertLessEqual(set(new["invitations"].items()), set(old["invitations"].items()), what)
        gone = new["retired"] - old["retired"]                                          # what left the state (C14r)…
        self.assertTrue(all(old["ballots"][bid][3] is not None for bid in gone), what)  # …had ended
        self.assertEqual(set(new["ballots"]), set(old["ballots"]) - gone, what)         # no ballot is opened
        for bid, (commits, reveals, electors, result, *frozen) in new["ballots"].items():
            c0, r0, e0, res0, *frozen0 = old["ballots"][bid]
            self.assertEqual((commits, reveals, frozen), (c0, r0, frozen0), what)         # no vote is added, removed or changed
            self.assertLessEqual(electors, e0, what)                                      # no elector is added
            self.assertIn((res0, result), {(None, None), (None, "voided"), ("passed", "passed"), ("passed", "undone"),
                                           ("failed", "failed"), ("lapsed", "lapsed"), ("voided", "voided"),
                                           ("undone", "undone")}, what)
        self.assertEqual(set(new["exams"]), set(old["exams"]), what)
        for k, (passed, reports) in new["exams"].items():
            self.assertTrue(old["exams"][k][0] or not passed, what)                       # no exam becomes passed
            self.assertEqual(reports, old["exams"][k][1], what)
        for name, (key, revoked) in new["custodians"].items():
            self.assertEqual(key, old["custodians"][name][0], what)
            self.assertTrue(old["custodians"][name][1] in (None, revoked), what)          # no removed key comes back

    def run_one(self, seed: int) -> dict:
        import random
        rng = random.Random(seed)
        st = self.chain.state()
        now, done = self.chain.now, {}
        ballots, logins = sorted(st.ballots) + ["nope"], sorted(st.members) + ["nobody"]
        for _ in range(220):
            now += rng.choice((0, 0, 3600, 86400, 86400, 2 * 86400)) * SEC
            seqs = sorted(st.corrections) + [0]
            waiting = [k.seq for k in st.corrections.values() if k.class_ == "noticed" and k.applied is None]
            roll = rng.random()
            if roll < 0.45:
                act = rng.choice(("void_ballot",) * 3 + ("undo_ballot",) * 4 + ("stay",) * 4 + ("freeze_key", "hold_room", "halt",
                                                                                               "freeze_witness", "note"))
                passed = ["adv-alice-2", "adm-bob", "w"] * 3 + ballots
                still = ["adm-zoe", "adv-bob-2", "open"] * 3 + ballots       # open, and not yet in their reveal window
                target = {"void_ballot": lambda: {"id": rng.choice(still)}, "undo_ballot": lambda: {"id": rng.choice(passed)},
                          "stay": lambda: {"ballot": rng.choice(still)}, "freeze_key": lambda: {"login": rng.choice(logins)},
                          "hold_room": lambda: {"login": rng.choice(logins)}, "halt": dict,
                          "freeze_witness": lambda: {"name": rng.choice(("tyler", "node2"))},
                          "note": lambda: {"action": "hide", "target": "issue:1", "rule": "ROOMS.md"}}[act]()
                ground = "attack_in_progress" if act == "halt" else "key_compromised" if act == "freeze_key" \
                    else "moderation" if act == "note" and rng.random() < 0.9 else rng.choice(ledger.GROUNDS)
                typ, actor, body = "correction", rng.choice(("warden", "keeper")), \
                    {"act": act, "target": target, "ground": ground, "reason_sha256": REASON}
            elif roll < 0.75:
                typ = rng.choice(("correction_apply", "correction_apply", "correction_apply", "correction_cosign",
                                  "correction_withdraw"))
                seq = rng.choice(waiting) if waiting and rng.random() < 0.8 else rng.choice(seqs)
                if typ == "correction_apply" and seq in waiting and rng.random() < 0.6:
                    now = max(now, st.corrections[seq].time + 14 * DAY)       # wait for the end of its notice
                actor, body = rng.choice(("warden", "keeper")), {"seq": seq}
            elif roll < 0.9:
                typ, actor, body = "correction_object", rng.choice(SEVEN), {"seq": rng.choice(seqs)}
            elif roll < 0.99:
                typ, actor, body = "custodian_alive", rng.choice(("warden", "keeper")), {}
            else:
                typ, actor, body = "custodian_revoke", "keeper", {"name": "keeper"}
            e = {"seq": st.seq + 1, "prev": st.head, "time": iso(now), "type": typ, "actor": actor, "body": body,
                 "sig": fake_key(actor + "-revoke" if typ == "custodian_revoke" else actor)}
            nxt = copy.deepcopy(st)
            try:
                apply(nxt, e, by_key)
            except Invalid:
                continue
            what = f"seed {seed}: {typ} {body} by {actor} at {iso(now)}"
            self.never_granted(self.facts(st), self.facts(nxt), what)
            self.assertLessEqual(len(nxt.masters(now)), len(st.masters(now)), what)
            key = body["act"] if typ == "correction" else typ
            if typ == "correction_apply":
                key = "applied " + nxt.corrections[body["seq"]].act
            done[key] = done.get(key, 0) + 1
            st = nxt
        return done

    def test_no_run_of_corrections_grants_anything(self):
        total = {}
        for seed in range(5):
            for k, n in self.run_one(seed).items():
                total[k] = total.get(k, 0) + n
        for must in ("void_ballot", "undo_ballot", "applied void_ballot", "applied undo_ballot", "correction_object",
                     "correction_withdraw", "freeze_key", "stay", "halt"):
            self.assertGreater(total.get(must, 0), 0, (must, total))                      # the runs were not vacuous

    def test_every_undo_and_void_in_turn_only_takes_away(self):
        """The same check, deterministic: every ballot of the ledger is voided or undone as far as the rules allow."""
        c = fork(self.chain)
        posted = []
        for bid in ("adv-alice-2", "adm-bob"):
            posted.append(undo(c, bid))
        undo(c, "w")
        c.refused(self, "only an admission or an advancement is undone by a correction")
        void(c, "adm-zoe", "protocol_defect")
        c.refused(self, "the reveal window of ballot adm-zoe opened at")     # its votes can be revealed: it is not voided
        for bid in ("open", "adv-bob-2"):
            posted.append(void(c, bid, "protocol_defect", by="keeper"))      # each custodian has a share of three
        before = self.facts(c.state())
        c.now += 14 * DAY
        for seq in posted:
            old = self.facts(c.state())
            apply_(c, seq)
            self.never_granted(old, self.facts(c.state()), seq)
        st = c.state()
        self.assertEqual([st.ballots[b].result for b in ("adv-alice-2", "adm-bob", "w", "adm-zoe", "open", "adv-bob-2")],
                         ["undone", "undone", "passed", None, "voided", "voided"])
        self.assertEqual((st.members["alice"].degree, st.members["bob"].status, sorted(st.witnesses)),
                         (1, "voided", ["node2", "tyler"]))
        self.never_granted(before, self.facts(st), "all")
        self.assertNotEqual(before, self.facts(st))


class RemoveCustodian(unittest.TestCase):
    """The one ballot about a custodian removes its key (SPEC section 6.4.6). Nothing appoints one."""

    def test_the_master_builders_remove_a_custodian_by_simple_majority(self):
        c = lodge(founders=SEVEN, witnesses=("tyler",))      # warden is linked to hiram
        f = freeze(c, "ada")
        sanction(c, "s", member="carol", by="dan")
        v = void(c, "s")
        open_ballot(c, "rm", "dan", "custodian", {"remove": "warden"}, )
        b = c.state().ballots["rm"]
        self.assertEqual((b.electors, b.commit_until, b.reveal_until, b.frozen),
                         (frozenset(SEVEN) - {"hiram"}, c.now + 7 * DAY, c.now + 10 * DAY + ledger.REVEAL_GAP, {}))
        commit(c, "rm", "hiram")
        c.refused(self, "not an elector")
        c.vote("rm", {"dan": "yes", "eve": "yes", "fay": "yes", "carol": "no", "gus": "no"})   # 3 to 2: not two thirds
        st = c.state()
        w = st.custodians["warden"]
        self.assertEqual((st.ballots["rm"].result, w.revoked, w.removed, st.custodian_status(w, c.now)),
                         ("passed", c.now, "rm", "removed"))
        self.assertEqual(st.span(st.corrections[f])[1], c.now)                # what it had in force ended…
        self.assertEqual(st.noticed_status(st.corrections[v], c.now), "ended")   # …and what it had pending died
        self.assertIsNone(st.frozen("ada", c.now))
        for typ, body in (("custodian_alive", {}), ("correction_apply", {"seq": v}),
                          ("correction", {"act": "halt", "target": {}, "ground": "attack_in_progress", "reason_sha256": REASON})):
            c.add(typ, "warden", body)
            c.refused(self, r"the custodian key of warden is removed and signs nothing \(a lapsed, revoked or removed key "
                            r"never signs again\)")
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke")
        c.refused(self, "the custodian key of warden is removed")
        open_ballot(c, "rm2", "dan", "custodian", {"remove": "warden"})
        c.refused(self, "the custodian key of warden is already removed")

    def test_the_decision_is_a_simple_majority_of_the_votes_cast_with_the_usual_quorum(self):
        for yes, no, n, want in ((3, 2, 6, True), (2, 2, 6, False), (2, 0, 6, False), (2, 1, 6, True), (1, 0, 1, True),
                                 (0, 1, 1, False), (4, 3, 21, True), (4, 2, 21, False), (0, 0, 0, False), (1, 0, 0, False)):
            self.assertEqual(ledger.decide("custodian", yes, no, n), want, (yes, no, n))
        self.assertFalse(ledger.decide("witness", 3, 2, 6))                   # the two-thirds kinds would refuse 3 to 2
        self.assertIn("custodian", ledger.KINDS)

    def test_who_may_open_it_and_on_what(self):
        c = lodge(founders=SEVEN)
        initiate(c, "alice")
        for by, subject, pattern in (
                ("hiram", {"remove": "warden"}, "hiram is the member of the custodian warden and cannot open the ballot that removes it"),
                ("alice", {"remove": "warden"}, "only Master Builders may open the ballot that removes a custodian"),
                ("ada", {"remove": "nobody"}, "no such custodian"), ("ada", {"remove": "Warden"}, "no such custodian"),
                ("ada", {"remove": "hiram"}, "no such custodian"),
                ("ada", {"remove": "warden", "why": "x"}, r"custodian subject has exactly the keys \['remove'\]"),
                ("ada", {"add": "keeper"}, r"custodian subject has exactly the keys \['remove'\]"),
                ("ada", {"appoint": "keeper", "key": "k"}, r"custodian subject has exactly the keys \['remove'\]"),
                ("ada", {"remove": 7}, "custodian subject: 'remove' must be a string")):
            open_ballot(c, "rm", by, "custodian", subject)
            c.refused(self, pattern)
        for windows in ({"commit_days": 7}, {"reveal_days": 3}, {"commit_days": 30, "reveal_days": 14}):
            open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"}, **windows)
            c.refused(self, r"a custodian ballot has fixed windows \(7 days to commit, 3 to reveal\): it takes no commit_days "
                            "and no reveal_days")
        open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"})
        open_ballot(c, "rm2", "carol", "custodian", {"remove": "warden"})
        c.refused(self, "a ballot on this subject is already open")
        open_ballot(c, "x", "ada", "election", {"custodian": "keeper"})
        c.refused(self, r"kind must be one of \['admission', 'advancement', 'amendment', 'custodian', 'sanction', 'witness'\]")
        self.assertEqual(ledger.SUBJECT_FIELDS["custodian"], {"remove": str})    # to remove is all a ballot decides

    def test_where_only_the_linked_member_is_a_master_nobody_can_remove_the_custodian(self):
        c = lodge(founders=["hiram"])
        open_ballot(c, "rm", "hiram", "custodian", {"remove": "warden"})
        c.refused(self, "hiram is the member of the custodian warden")
        d = lodge(founders=["hiram", "ada"])
        open_ballot(d, "rm", "ada", "custodian", {"remove": "warden"})
        d.vote("rm", {"ada": "yes"})                           # the electorate is ada alone: one vote decides
        self.assertEqual(d.state().custodian_status(d.state().custodians["warden"], d.now), "removed")

    def test_no_correction_pauses_stops_or_reverses_it(self):
        c = lodge(custodians=(("warden", "hiram"), ("keeper", "gus")), founders=SEVEN, witnesses=("tyler",))
        open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"})
        for by in ("warden", "keeper"):
            correct(c, "stay", {"ballot": "rm"}, by=by)
            c.refused(self, "a ballot of kind custodian is never stayed")
            void(c, "rm", by=by)
            c.refused(self, "a ballot of kind custodian is never voided or undone by a correction")
        for who in ("ada", "carol", "dan"):
            commit(c, "rm", who)
        h = halt(c, days=6)                                    # halted for 14 days from the sixth day
        commit(c, "rm", "eve")                                 # accepted during the halt…
        st = c.state()
        self.assertEqual((st.ballot_time(st.ballots["rm"], T0 + 9 * DAY), st.pauses("rm"), st.pauses()),
                         (T0 + 9 * DAY, [], [(T0 + 6 * DAY, T0 + 20 * DAY)]))      # …and its clock is the wall clock
        c.now = T0 + 7 * DAY + SEC
        commit(c, "rm", "fay")
        c.refused(self, "commit window closed")
        sanction(c, "s", member="carol", by="ada")
        c.refused(self, "the ledger is halted")                # every other ballot waits
        c.now = T0 + 7 * DAY + ledger.REVEAL_GAP + SEC
        for who in ("ada", "carol", "dan", "eve"):
            reveal(c, "rm", who)
        c.now = T0 + 10 * DAY + ledger.REVEAL_GAP + SEC
        self.assertEqual(ledger.due_actions(c.state(), c.now), [("ballot_close", {"id": "rm"})])
        c.add("ballot_close", "tyler", {"id": "rm"})           # a witness closes it during the halt
        st = c.state()
        self.assertEqual((st.ballots["rm"].result, st.custodian_status(st.custodians["warden"], c.now), st.halted(c.now)),
                         ("passed", "removed", None))          # the halt was the removed custodian's: it ended too
        self.assertEqual(st.span(st.corrections[h]), (T0 + 6 * DAY, c.now))
        undo(c, "rm", by="keeper")
        c.refused(self, "only an admission or an advancement is undone by a correction")

    def test_frozen_members_open_it_vote_in_it_and_close_it(self):
        c = lodge(founders=["hiram", "ada"], witnesses=("tyler",))
        open_ballot(c, "s", "ada", "witness", {"action": "remove", "name": "tyler"})   # an ordinary ballot beside it
        freeze(c, "ada")
        open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"})
        commit(c, "rm", "ada")
        commit(c, "s", "ada")                                 # a frozen elector votes in every ballot…
        c.add("ballot_close", "ada", {"id": "s"}, days=11)
        c.refused(self, "the key of ada is frozen")           # …and closes only the one that removes a custodian
        c.now = T0 + 7 * DAY + ledger.REVEAL_GAP + SEC
        reveal(c, "rm", "ada")
        c.now = T0 + 10 * DAY + ledger.REVEAL_GAP + SEC
        self.assertIsNotNone(c.state().frozen("ada", c.now))
        c.add("ballot_close", "ada", {"id": "rm"})
        st = c.state()
        self.assertEqual((st.ballots["rm"].result, st.frozen("ada", c.now)), ("passed", None))
        c.add("work", "ada", {"ref": URL})                    # the freeze was the removed custodian's

    def test_a_removal_that_passes_after_the_key_already_ended_closes_as_failed(self):
        c = lodge(founders=SEVEN)
        open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"})
        for who in ("ada", "carol", "dan"):
            commit(c, "rm", who)
        c.add("custodian_revoke", "warden", {"name": "warden"}, key_of="warden-revoke", days=1)
        c.now = T0 + 7 * DAY + ledger.REVEAL_GAP + SEC
        for who in ("ada", "carol", "dan"):
            reveal(c, "rm", who)
        c.add("ballot_close", "ada", {"id": "rm"}, days=4)
        st = c.state()
        w = st.custodians["warden"]
        self.assertEqual((st.ballots["rm"].result, w.revoked, w.removed, st.custodian_status(w, c.now)),
                         ("failed", T0 + DAY, "", "revoked"))

    def test_after_the_last_custodian_is_gone_no_correction_exists(self):
        c = lodge(founders=SEVEN)
        open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"})
        c.vote("rm", {"ada": "yes", "carol": "yes", "dan": "yes"})
        for typ, actor, body, key in (("correction", "warden", {"act": "halt", "target": {}, "ground": "attack_in_progress",
                                                                 "reason_sha256": REASON}, "warden"),
                                      ("custodian_alive", "warden", {}, "warden"),
                                      ("correction", "ada", {"act": "halt", "target": {}, "ground": "attack_in_progress",
                                                             "reason_sha256": REASON}, "ada")):
            c.add(typ, actor, body, key_of=key)
            c.refused(self, "signs nothing" if actor == "warden" else "ada is not a custodian")
        self.assertEqual(set(ledger.OPENERS), ledger.KINDS)
        # Nothing but a founder's claim names a custodian after the genesis (tests.test_liveness).
        self.assertFalse([t for t in ledger.HANDLERS if "custodian" in t and t not in (
            "custodian_alive", "custodian_revoke", "custodian_claim", "custodian_claim_object", "custodian_claim_apply")])


class ReadsOfPending(unittest.TestCase):
    def test_the_state_report_shows_pending_corrections_and_open_removals(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN, witnesses=("tyler",))
        open_ballot(c, "w", "ada", "witness", {"action": "remove", "name": "tyler"})
        v = void(c, "w", days=1)
        objection(c, v, "dan", days=1)                        # one of the two it takes: still pending
        open_ballot(c, "rm", "ada", "custodian", {"remove": "keeper"})
        rep = state_report(c.state(), c.now)
        json.dumps(rep)
        row = next(r for r in rep["corrections"] if r["seq"] == v)
        self.assertEqual(row, {"seq": v, "by": "warden", "act": "void_ballot", "class": "noticed", "target": {"id": "w"},
                               "ground": "identity_fraud", "reason_sha256": REASON, "time": iso(T0 + DAY), "status": "pending",
                               "objections": ["dan"], "ends": None, "signers": ["warden"], "signers_needed": 1,
                               "notice_until": iso(T0 + 15 * DAY), "apply_until": iso(T0 + 22 * DAY), "applied": None})
        self.assertEqual([(k["name"], k["status"], k["removal_ballot"]) for k in rep["custodians"]],
                         [("warden", "live", None), ("keeper", "live", "rm")])
        self.assertIn({"remove": "keeper"}, [b["subject"] for b in rep["open_ballots"]])
        ready = state_report(c.state(), T0 + 16 * DAY)
        self.assertEqual(next(r for r in ready["corrections"] if r["seq"] == v)["status"], "ready")
        apply_(c, v, days=14)
        done = next(r for r in state_report(c.state(), c.now)["corrections"] if r["seq"] == v)
        self.assertEqual((done["status"], done["applied"]), ("applied", iso(c.now)))


# ---------------------------------------------------------------- the documents ----

class Documents(unittest.TestCase):
    def test_the_specification_states_every_constant_and_refusal(self):
        spec = (REPO / "docs/whitepaper/SPEC.md").read_text(encoding="utf-8")
        for name in ("CUSTODIANS_MAX", "CUSTODIAN_SILENCE_DAYS", "SUNSET_MASTERS", "SUNSET_WITNESSES", "FREEZE_DAYS",
                     "REFREEZE_AFTER_DAYS", "FREEZE_CAP_DIVISOR", "STAY_DAYS", "HALT_DAYS", "HALT_INTERVAL_DAYS", "HOLD_DAYS",
                     "NOTES_PER_DAY", "CORRECTIONS_PER_30_DAYS", "CORRECTION_WINDOW_DAYS", "OBJECTION_DAYS",
                     "OBJECTION_DIVISOR", "GROUNDS", "NOTE_ACTIONS", "CUSTODIAN_DOMAIN", "CUSTODIAN_REVOKE_DOMAIN",
                     "HALT_ALLOWED", "FREEZE_ALLOWED", "STAY_EXEMPT", "CUSTODIAN_TYPES", "CUSTODIAN_SIGNED", "NOTE_TARGET_RE",
                     "NOTE_RULE_RE", "REASON_MAX_BYTES", "REASONS_DIR", "NOTICE_DAYS", "APPLY_WINDOW_DAYS",
                     "UNDO_WINDOW_DAYS", "RECOVER_NOTICE_DAYS", "RECOVER_EXPIRY_DAYS", "RECOVER_INTERVAL_DAYS",
                     "RECOVER_COSIGNERS", "NOTICED_ACTS", "UNDO_KINDS", "GONE", "BALLOT_TYPES", "RECOVERY_TYPES",
                     "ENTRIES_PER_DAY", "DAILY_EXEMPT", "OPEN_BALLOTS_PER_OPENER", "REOPEN_AFTER_DAYS", "REOPEN_KINDS",
                     "OPENER_WINDOWS", "CHECKPOINT_INTERVAL", "ALIVE_INTERVAL", "CUSTODIAN_TERM_DAYS", "NOTES_KEPT",
                     "REPOST_AFTER_DAYS", "VOIDED_FRAUD_DAYS", "RECOVER_OPEN_COSIGNERS", "RECOVER_FINAL_COSIGNERS",
                     "RECOVER_OPEN_NOTICE_DAYS", "NOTE_GROUND", "WITNESS_DOMAIN", "FOUNDER_DOMAIN", "JUDGE_FUTURE_TOLERANCE",
                     "RESULTS", "CANON_MAX_BYTES", "ANCHOR_MAX_BYTES", "BALLOT_RETIRE_DAYS", "HISTORY", "STATE_VERSION"):
            self.assertIn(f"`{name}`", spec, name)
        for typ in ("correction", "correction_withdraw", "correction_object", "custodian_alive", "custodian_revoke",
                    "correction_cosign", "correction_apply", "rekey_recover", "rekey_cosign", "rekey_object",
                    "rekey_recover_apply", "rekey_oppose"):
            self.assertRegex(spec, rf"### 6\.\d+ `{typ}`")
        for message in ("no custodian exists, so no correction exists",
                        "the custodian key of {actor} is {status} and signs nothing (a lapsed, revoked or removed key never "
                        "signs again)",
                        "the actor of a custodian_revoke is the custodian whose key it removes",
                        "freeze_key takes one ground only: key_compromised",
                        "the last unfrozen witness is frozen only on the ground attack_in_progress",
                        "a ballot of kind {kind} is never stayed",
                        "at most 10 notes per custodian per UTC day",
                        "only Master Builders may object to a correction",
                        "custodian_threshold is 0 without custodians, and otherwise 1 to the number of custodians",
                        "bad custodian proof: the custodian key must sign the custodian message (name, member, key)",
                        "a frozen member may only depart, rekey, vote (commit and reveal), take part in an amendment "
                        "ballot or the ballot that removes a custodian, or object to a recovery of their own key",
                        "only custodian entries, custodian_revoke, correction_object, depart, rekey, the entries of a key "
                        "recovery, a witness checkpoint, an amendment ballot and the ballot that removes a custodian are "
                        "accepted",
                        "correction {seq} is under notice until {T + 14 d} (14 days after it was posted)",
                        "correction {seq} was already applied (a correction is applied once)",
                        "correction {seq} has {n} of the {threshold} custodian signature(s) it needs",
                        "correction {seq} already has the {threshold} custodian signature(s) it needs",
                        "correction {seq} is not in force or pending (nothing to withdraw)",
                        "ballot {id} is paused while the correction that would void it is pending (correction {seq}, "
                        "until {apply_end} at the latest)",
                        "a ballot of kind {kind} is never voided or undone by a correction",
                        "only an admission or an advancement is undone by a correction (ballot {id} is of kind {kind})",
                        "ballot {id} closed more than 90 days ago (a ballot is undone only by a correction posted within 90 "
                        "days of its close)",
                        "ballot {id} ended more than 111 days ago and left the state (no rule reads a ballot after that)",
                        "the undo of ballot {id} no longer applies: {field} is {found!r}, not {after!r} as the ballot left it "
                        "(nothing is undone unless everything the ballot changed still stands)",
                        "recusal: the custodian {C.name} never voids or undoes a ballot whose subject, opener or sponsor is "
                        "their own member ({C.member})",
                        "{actor} is the member of a custodian who co-signed correction {seq} and cannot object to it",
                        "objections to correction {seq} closed 90 days after it was applied",
                        "only Master Builders may open the ballot that removes a custodian",
                        "{actor} is the member of the custodian {remove} and cannot open the ballot that removes it",
                        "ballot has fixed windows (7 days to commit, 3 to reveal): it takes no commit_days and "
                        "no reveal_days (only an amendment ballot does)",
                        "the same key is frozen again only 90 days after the previous freeze began, unless other custodians "
                        "withdrew that freeze"):
            self.assertIn(message, spec, message)
        # The refusals of the bounds and guards (SPEC sections 5.4, 6 and 9): the words of each that hold no value.
        for words in (
                " entries per actor per UTC day; a vote, a close, a lot, a departure, a key replacement or recovery, an "
                "objection, the entries of an amendment ballot or of the ballot that removes a custodian, and "
                "custodian_revoke are not counted)",
                "the first founder signs the genesis itself and carries no proof; every other founder carries one",
                "must sign the founder message (login, github_id, key)",
                "must sign the witness message (name, key)",
                "only the candidate, or an examiner of the passed examination, may open the advancement ballot",
                "only Master Builders may open an amendment ballot", "only Master Builders may open a witness ballot",
                "before opening this ballot (in an earlier pull request, or in the pull request that opens it)",
                "is malformed (33 degrees with exact fields): it can never be ratified",
                "(a voided record is expelled for fraud only by a ballot opened before 90 days have passed since the "
                "undo; from then on the login may be invited again)",
                "a member cannot open a sanction ballot on themselves",
                "only an Arbiter (7th degree or higher) may open a sanction ballot while three or more active Arbiters exist",
                "only Master Builders may open a sanction ballot (an Arbiter where three or more active Arbiters exist)",
                "a witness subject has action, name, key and proof to add a witness, and action and name only to remove one",
                "bad witness proof: the proposed key must sign the witness message (name, key)",
                "(the same member opens a ballot on the same subject again only 90 days after that close; another member "
                "may open one)",
                "(a member has at most 3 open ballots of their own at once, and apart from them at most 3 amendment ballots",
                ", both included)",
                "a recovery never needs a custodian",
                "(a recovery reverses a departure only when it is asked before it or within 30 days of it, or follows one "
                "so asked within 150 days of that one's request, or of the old key's stop of it)",
                "cannot be stopped by the old key and needs",
                "and cannot co-sign it",
                "follows one the old key stopped, and the old key cannot stop this one",
                "a Master Builder objects to that correction instead (correction_object)",
                "only Master Builders may oppose a key recovery",
                "a member stops the recovery of their own key with rekey_object, signed by the old key",
                "and cannot oppose it", "already opposed the recovery of the key of",
                "co-signatures of active Master Builders that start its notice",
                "days after its notice began)",
                "a Master Builder who is not one must co-sign too",
                "(a witness posts a checkpoint only when an entry that is not a checkpoint was added since its last one)",
                "is less than 1 hour old (at most one checkpoint per witness per hour)",
                "recusal: a ballot that adds a witness, or that advances a member to the 3rd degree, is never stayed, voided "
                "or undone by a correction",
                ": a ballot is stayed, or its voiding posted, only before any vote can be revealed",
                "at most once, unless other custodians withdrew it",
                "is not applied while a sanction ballot on",
                "the ground moderation is the ground of a note, and of no other act",
                "the same act on the same target, was voided by objections less than 90 days ago",
                " corrections per custodian in any 30 days while ",
                "already signed the withdrawal of correction",
                "gave a sign of life less than 24 hours ago (at most one custodian_alive per custodian in 24 hours)",
                "(departed members, and members whose admission was undone, may petition again once 90 days have passed, expelled "
                "members once 365 have)",
                "(a departed member, or one whose admission was undone, may be invited again once 90 days have passed, an expelled "
                "member once 365 have)"):
            self.assertIn(words, spec, words)
        for word in ("pending", "ready", "applied", "void", "withdrawn", "ended", "expired", "voided", "undone", "removed",
                     "released"):
            self.assertIn(f"`{word}`", spec)
        for heading in ("#### 6.4.6 Kind `custodian`", "#### 6.19.7 Act `void_ballot`", "#### 6.19.8 Act `undo_ballot`",
                        "#### 6.19.9 The life of a noticed act", "### 4.10 `Recovery`"):
            self.assertIn(heading, spec)
        for invariant in ("**Corrections never grant.**", "**An applied correction is never applied twice.**",
                          "**A removed, revoked or lapsed custodian key never signs again.**"):
            self.assertIn(invariant, spec)
        self.assertIn(inspect.getsource(ledger.decide).split('"""', 2)[2].strip(), spec)       # the code quoted in section 6.4
        self.assertIn("thirty-four types", spec)
        self.assertNotIn("twenty-nine types", spec)
        self.assertNotIn("the thirty types", spec)
        for gone in ("signer_key", "State.council", "cut_short", "commit_seq", "old_key", "canon_digest", "file_digest"):
            self.assertNotIn(gone, spec, gone)                 # what the code no longer has, the specification no longer names

    def test_the_whitepaper_appendix_lists_the_new_entry_types(self):
        paper = (REPO / "docs/whitepaper/WHITEPAPER.md").read_text(encoding="utf-8")
        appendix = paper[paper.index("## Appendix A: ledger entry specification"):]
        for typ in ("`correction`", "`correction_withdraw`", "`correction_object`", "`custodian_alive`", "`custodian_revoke`",
                    "`correction_cosign`", "`correction_apply`", "`rekey_recover`", "`rekey_cosign`", "`rekey_object`",
                    "`rekey_recover_apply`", "`rekey_oppose`", "`void_ballot`", "`undo_ballot`"):
            self.assertIn(typ, appendix)


if __name__ == "__main__":
    unittest.main()
