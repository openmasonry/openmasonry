"""The conformance vectors (SPEC section 14) are what the generator makes, and replay reaches what they state.

Two things are held here. The committed files in tests/vectors/ equal, byte for byte, what
`tests/make_vectors.py` generates today: a change of the protocol that moves a hash, a digest or a refusal
shows up as a failure of this test until the vectors are generated again, on purpose. And every committed
file, read as another implementation would read it, replays to its stated outcome with real signature
verification (`crypto.verify`, no cache, no stub).

Run: PYTHONPATH=src python3 -m unittest tests.test_vectors -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from openmasonry import crypto, ledger
from openmasonry.ledger import HANDLERS, Invalid, State, apply, entry_hash
from tests import make_vectors
from tests.make_vectors import VECTORS, outcome, run

REPO = Path(__file__).resolve().parents[1]
SPEC = (REPO / "docs" / "whitepaper" / "SPEC.md").read_text(encoding="utf-8")
# For each invalid vector, words of its refusal that the specification states: the message a second
# implementation is to give. Where the message holds a value (a login, a time), the words around it.
STATED = {
    "bad_prev": ["prev does not match head (history was altered)"],
    "time_goes_backwards": ["time goes backwards"],
    "wrong_signer": ["bad signature"],
    "signature_rewrapped": ["bad signature"],
    "signature_s_plus_l": ["bad signature"],
    "float_in_body": ["is not strict JSON: ", "a number with a fraction or an exponent is not allowed"],
    "unknown_field": ["malformed ", " entry: unknown field "],
    "integer_out_of_range": ["is not strict JSON: ", "an integer is outside ±(2^53 − 1)"],
    "oversized_entry": ["entry exceeds ", " bytes"],
    "duplicate_key": ["is not strict JSON: ", "duplicate key "],
    "petition_without_invitation": ["no live invitation for ", " (a Master Builder invites first, and an invitation lapses after "],
    "second_reveal": ["already revealed"],
    "frozen_member_acts": [": a frozen member may only depart, rekey, vote (commit and reveal), take part "
                           "in an amendment ballot or the ballot that removes a custodian, or object to a recovery of their "
                           "own key"],
    "entry_during_a_halt": ["the ledger is halted until ", ": only custodian entries, custodian_revoke, correction_object, "
                            "depart, rekey, the entries of a key recovery, a witness checkpoint, an amendment ballot and the "
                            "ballot that removes a custodian are accepted"],
    "correction_by_a_lapsed_key": ["the custodian key of ", " and signs nothing (a lapsed, revoked or removed key never signs again)"],
    "apply_before_the_notice_ends": [" is under notice until ", " days after it was posted)"],
    "undo_after_a_conflicting_change": [" no longer applies: ", " as the ballot left it (nothing is undone unless everything the "
                                        "ballot changed still stands)"],
    "checkpoint_with_a_wrong_state_digest": ["witness state digest mismatch"],
    "witness_ballot_with_a_bad_proof": ["bad witness proof: the proposed key must sign the witness message (name, key)"],
    "amendment_opened_by_an_apprentice": ["only Master Builders may open an amendment ballot"],
    "fourth_open_ballot": [" ballots open (a member has at most ", " open ballots of their own at once, and apart from them "
                           "at most "],
    "checkpoint_without_a_new_entry": ["no entry but checkpoints since the last checkpoint of ",
                                       " (a witness posts a checkpoint only when an entry that is not a checkpoint was added "
                                       "since its last one)"],
    "twenty_first_entry_in_a_day": [" entries dated ", " entries per actor per UTC day; a vote, a close, a lot, a departure, "
                                    "a key replacement or recovery, an objection, the entries of an amendment ballot or of "
                                    "the ballot that removes a custodian, and custodian_revoke are not counted)"],
    "note_on_another_ground": [" takes one ground only: "],
    "room_hold_again_within_ninety_days": [" was held less than 90 days ago (the same login is held again only 90 days "
                                           "after the previous hold began"],
    "recovery_long_after_a_departure": [" departed more than 30 days ago (a recovery reverses a departure only when it "
                                        "is asked before it or within 30 days of it"],
    "correction_after_the_term": ["the custodian key of ", " and signs nothing (a lapsed, revoked or removed key never signs again)"],
    "void_posted_after_the_reveal_opened": ["the reveal window of ballot ", ": a ballot is stayed, or its voiding posted, only "
                                            "before any vote can be revealed"],
    "claim_applied_before_its_notice": ["the claim of entry ", " is under notice until ", " (30 days after it)"],
    "sanction_on_a_master_by_one_elector": ["a sanction on a Master Builder is never decided by a single elector: this "
                                            "electorate has "],
    "successor_invites_before_ninety_days": ["only Master Builders may invite (and, while a succession is in force, the "
                                             "members of the highest degree present)"],
    "checkpoint_without_a_state_version": ["malformed ", " entry: missing field "],
    "exam_drawn_after_its_lot_lapsed": ["the lot of this exam was not drawn within 7 days of its beacon round (",
                                        "): the exam lapsed with no penalty, and a new one may be opened"],
    "second_re_run": [" re-ran ballot ", ": a ballot is re-run once, and a re-run never"],
    "frozen_key_signs_during_a_dropped_recovery": ["stays frozen while its recovery is pending (entry "],
    "short_ballot_re_run": [" gave less than 7 days to commit and is never re-run (open a new ballot, which waits for "
                            "every elector)"],
}


def verify_for_real(payload: bytes, sig: str, actor: str, key: str) -> bool:
    return crypto.verify(payload, sig, actor, key)


class Vectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.made = make_vectors.vectors()
        cls.files = {p.name: p.read_bytes() for p in sorted(VECTORS.glob("*"))}

    def test_the_committed_files_are_what_the_generator_makes(self):
        self.assertEqual(sorted(self.files), sorted(self.made),
                         "tests/vectors/ and tests/make_vectors.py differ: PYTHONPATH=src python3 -m tests.make_vectors")
        for name, vector in self.made.items():
            self.assertEqual(self.files[name], make_vectors.text(vector).encode("ascii"),
                             f"{name} is not what the generator makes today: if the protocol changed on purpose, "
                             "generate the vectors again (PYTHONPATH=src python3 -m tests.make_vectors)")
        self.assertEqual(make_vectors.vectors(), self.made)                     # and the generator is deterministic

    def test_every_committed_vector_replays_to_its_outcome_with_real_signatures(self):
        self.assertGreaterEqual(len(self.files), 31)
        checked = 0
        with mock.patch.dict("os.environ", {"OM_NO_CACHE": "1"}):
            for name, raw in self.files.items():
                vector = json.loads(raw)
                self.assertEqual(sorted(vector), ["description", "entries", "expect", "name"], name)
                got = outcome(vector["entries"], verify_for_real)
                self.assertEqual(got, vector["expect"], name)
                checked += len(vector["entries"])
        self.assertGreater(checked, 150)

    def test_each_expectation_has_its_exact_shape(self):
        for name, raw in self.files.items():
            vector = json.loads(raw)
            expect, entries = vector["expect"], vector["entries"]
            self.assertEqual(name, ("valid-" if expect["valid"] else "invalid-") + vector["name"].replace("_", "-") + ".json")
            self.assertTrue(vector["description"].strip())
            self.assertEqual(expect["seq"], len(entries) - 1, name)             # the last entry decides
            if expect["valid"]:
                self.assertEqual(sorted(expect), ["head", "seq", "state_sha256", "valid"], name)
                self.assertEqual(expect["head"], entry_hash(entries[-1]), name)
                self.assertRegex(expect["state_sha256"], "^[0-9a-f]{64}$")
                self.assertTrue(all(isinstance(e, dict) for e in entries), name)
            else:
                self.assertEqual(sorted(expect), ["error", "seq", "valid"], name)
                self.assertNotRegex(expect["error"], "^entry [0-9]+: ", name)   # the message, without its prefix
                self.assertTrue(all(isinstance(e, dict) for e in entries[:-1]), name)
            raw.decode("ascii")

    def test_the_refusals_are_the_messages_the_specification_states(self):
        invalid = {json.loads(raw)["name"]: json.loads(raw)["expect"]["error"]
                   for name, raw in self.files.items() if name.startswith("invalid-")}
        self.assertEqual(sorted(invalid), sorted(STATED))
        for name, error in invalid.items():
            for words in STATED[name]:
                self.assertIn(words, error, name)
                self.assertIn(words, SPEC, f"{name}: the specification does not state {words!r}")

    def test_the_invalid_vectors_fail_for_the_signature_alone_where_that_is_the_point(self):
        """With every signature accepted, the four signature vectors (three of an entry, one of a proof of
        possession) are lawful ledgers and the others are not."""
        trusting = lambda *_: True
        for name, raw in self.files.items():
            vector = json.loads(raw)
            if vector["name"] in ("wrong_signer", "signature_rewrapped", "signature_s_plus_l", "witness_ballot_with_a_bad_proof"):
                self.assertTrue(outcome(vector["entries"], trusting)["valid"], name)
            elif not vector["expect"]["valid"]:
                self.assertEqual(outcome(vector["entries"], trusting), vector["expect"], name)

    def test_the_valid_vectors_show_what_they_describe(self):
        state = lambda name: run(json.loads(self.files[f"valid-{name}.json"])["entries"], lambda *_: True)
        st = state("founding-with-custodians")
        self.assertEqual((sorted(st.custodians), st.custodian_threshold, sorted(st.witnesses)), (["keeper", "warden"], 2, ["tyler"]))
        self.assertGreater(st.custodians["keeper"].alive, st.custodians["warden"].alive)
        st = state("admission-passes")
        self.assertEqual((st.members["alice"].degree, st.members["alice"].sponsors, st.ballots["adm-alice"].result, st.petitions),
                         (1, ("hiram", "ada"), "passed", {}))
        st = state("admission-blackballed")
        self.assertEqual(("alice" in st.members, st.ballots["adm-alice"].result, st.petitions), (False, "failed", {}))
        st = state("exam-and-advancement")
        exam = st.exams[("alice", 2)]
        self.assertEqual((st.members["alice"].degree, len(exam.recused), len(exam.examiners), exam.passed(), exam.consumed,
                          st.history["beacons"][0]), (2, 1, 2, True, True, 1))
        self.assertNotIn(exam.recused[0], exam.examiners)
        st = state("amendment-with-prior-pin")
        self.assertEqual((st.pins["CONSTITUTION.md"], st.prior_pins, st.history["amendments"][0]),
                         (make_vectors.digest_of("amended constitution"),
                          {"CONSTITUTION.md": make_vectors.digest_of("pin of CONSTITUTION.md")}, 1))
        st = state("sanction-suspends")
        self.assertEqual((st.ballots["s-1"].result, st.members["carol"].status, "carol" in st.ballots["s-1"].electors),
                         ("passed", "departed", False))
        entries = json.loads(self.files["valid-witness-added-and-checkpoints.json"])["entries"]
        st = run(entries, lambda *_: True)
        checkpoints = [e for e in entries if e["type"] == "witness"]
        self.assertEqual((sorted(st.witnesses), [k["actor"] for k in checkpoints], ["root" not in k["body"] for k in checkpoints],
                          st.history["checkpoints"][0]), (["node2", "tyler"], ["node2", "tyler"], [False, True], 2))
        st = state("rekey-replaces-a-key")
        self.assertEqual(st.members["ada"].key, make_vectors.Ledger.key("ada-2"))
        st = state("freeze-halt-stay-and-the-effective-clock")
        b = st.ballots["s-1"]
        self.assertEqual((b.result, sorted(b.reveals), b.closed - b.reveal_until > 3 * make_vectors.DAY),
                         ("passed", ["ada", "dan", "eve", "hiram"], True))
        self.assertEqual(sorted(k.act for k in st.corrections.values()), ["freeze_key", "halt", "stay"])
        self.assertEqual(st.effective(b.opened, b.closed, "s-1"), (b.closed - b.opened) - 3 * make_vectors.DAY)
        st = state("void-of-an-open-ballot")
        self.assertEqual((st.ballots["s-1"].result, st.ballots["s-1"].closed, st.members["carol"].status), ("voided", None, "active"))
        st = state("undo-with-an-objection")
        k = st.corrections[max(st.corrections)]
        self.assertEqual((st.ballots["adm-bob"].result, st.members["bob"].status, k.objections, k.void), ("undone", "voided", ("dan",), None))
        st = state("custodian-removed-by-ballot")
        self.assertEqual((st.custodians["warden"].removed, st.custodian_status(st.custodians["warden"], st.time)), ("rm-warden", "removed"))
        st = state("key-recovery")
        self.assertEqual((st.members["carol"].key, st.recoveries["carol"].cosigners, st.recoveries["carol"].applied is not None,
                          st.members["carol"].last_work is not None),
                         (make_vectors.Ledger.key("carol-2"), ("hiram", "dan"), True, True))

    def test_the_incremental_digest_equals_the_digest_from_nothing_after_every_entry_of_every_vector(self):
        checked = 0
        for name, raw in self.files.items():
            st = State()
            for e in json.loads(raw)["entries"]:
                try:
                    apply(st, e, lambda *_: True)
                except Invalid:
                    break
                self.assertEqual(st.digest(), ledger.state_digest(st), f"{name}: entry {st.seq}")
                checked += 1
        self.assertGreater(checked, 150)

    def test_the_vectors_exercise_most_entry_types(self):
        seen = set()
        for raw in self.files.values():
            seen |= {e["type"] for e in json.loads(raw)["entries"] if isinstance(e, dict)}
        self.assertEqual(set(HANDLERS) - seen,
                         {"council_call", "council_draw", "custodian_revoke", "correction_cosign", "rekey_object",
                          "custodian_claim_object"})

    def test_these_vectors_show_what_they_describe(self):
        state = lambda name: run(json.loads(self.files[f"valid-{name}.json"])["entries"], lambda *_: True)
        st = state("frozen-elector-votes")
        b = st.ballots["am-1"]
        self.assertEqual((b.result, b.reveals["fay"], st.frozen("fay", b.closed) is not None), ("failed", "no", True))
        st = state("note-on-the-moderation-ground")
        self.assertEqual((st.corrections, [(n["action"], n["target"]) for n in st.notes]), ({}, [("hide", "discussion/42")]))
        st = state("recovery-without-a-custodian")
        r = st.recoveries["carol"]
        self.assertEqual((st.custodians, r.freeze, r.cosigners, r.opposed, r.void, st.members["carol"].key,
                          r.applied - r.notice), ({}, None, ("hiram", "dan", "eve"), ("fay",), None,
                                                  make_vectors.Ledger.key("carol-2"), 30 * make_vectors.DAY))
        st = state("sole-master-recovers-without-a-custodian")
        r = st.recoveries["hiram"]
        self.assertEqual((r.cosigners, r.notice, st.members["hiram"].key), ((), r.time, make_vectors.Ledger.key("hiram-2")))
        st = state("ballot-lapses-then-closes-early")
        a, b = st.ballots["adm-1"], st.ballots["adm-2"]
        self.assertEqual((a.result, b.result, b.closed < b.reveal_until, st.members["alice"].degree), ("lapsed", "passed", True, 1))
        st = state("custodian-key-through-its-term")
        w = st.custodians["warden"]
        self.assertEqual((st.time - w.since, st.custodian_status(w, st.time), len(st.notes)), (2555 * make_vectors.DAY, "live", 1))


if __name__ == "__main__":
    unittest.main()
