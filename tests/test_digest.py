"""The state digest (SPEC section 4.11): one serialization of the stored facts, and the checkpoint that states it.

The digest must be the same wherever the same entries are replayed (in one pass or continued from a prefix,
from files or from memory, under any hash seed, whatever the order in which a map was filled) and must
change when any single stored fact changes. A `witness` entry states it, and replay refuses a wrong one.

Run: PYTHONPATH=src python3 -m unittest tests.test_digest -v
"""
from __future__ import annotations

import copy
import dataclasses
import json
import os
import random
import subprocess
import sys
import unittest
from datetime import datetime, timedelta

from openmasonry import canon, ledger
from openmasonry.crypto import canonical, merkle_root, sha256
from openmasonry.ledger import (Ballot, Claim, Correction, Custodian, Exam, Invalid, Member, Recovery, State,
                                Succession, apply, load, replay)
from tests.test_custodian import (REASON, SEVEN, advance, commit, correct, freeze, lodge, open_ballot, sanction)
from tests.test_protocol import FOUNDERS, T0, checkpoint, initiate, invite, petition
from tests.test_recovery import ask, co
from tests.test_strict import DAY, SEC, Fast, by_key, founded, tmpdir, write_ledger

REPO = ledger.canon.ROOT
LATER = T0 + 5000 * DAY             # a time no test chain reaches


def rich_chain() -> Fast:
    """A ledger that fills every kind of record: members of several kinds, closed and open ballots, an exam,
    an amendment, a petition, an invitation, custodians, corrections, a recovery and a checkpoint."""
    c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN, witnesses=("tyler",),
              custodian_threshold=1)
    initiate(c, "alice")
    advance(c, "alice", 2)
    open_ballot(c, "am", "ada", "amendment", {"path": "CONSTITUTION.md", "new_sha256": "ab" * 32})
    c.vote("am", {x: "yes" for x in FOUNDERS})
    sanction(c, "sus", member="dan", by="ada", measure="suspend")
    c.vote("sus", {"hiram": "yes", "carol": "yes", "eve": "yes"})
    petition(c, "zoe")
    invite(c, "yan", by="ada")
    c.add("work", "eve", {"ref": "https://example.org/work"})
    correct(c, "note", {"action": "hide", "target": "issue:1", "rule": "ROOMS.md"})
    freeze(c, "carol")
    ask(c, "carol", days=1)
    co(c, "carol", "hiram")
    sanction(c, "open", member="eve", by="ada", measure="admonish")
    commit(c, "open", "hiram")
    st = c.state()
    c.add("witness", "tyler", checkpoint(st, root=merkle_root(st.hashes), anchor="ledger/anchors/000001.root.ots"))
    return c


def shuffled(st: State, rng: random.Random) -> State:
    """The same facts with every map and set filled in another order."""
    def mix(v):
        if isinstance(v, dict):
            items = list(v.items())
            rng.shuffle(items)
            return {k: mix(x) for k, x in items}
        if isinstance(v, frozenset):
            items = list(v)
            rng.shuffle(items)
            return frozenset(items)
        if isinstance(v, set):
            items = list(v)
            rng.shuffle(items)
            return set(items)
        if dataclasses.is_dataclass(v):
            return dataclasses.replace(v, **{f.name: mix(getattr(v, f.name)) for f in dataclasses.fields(v)})
        if isinstance(v, list):
            return [mix(x) for x in v]                        # a list is ordered: its order is a fact
        return v
    return mix(copy.deepcopy(st))


def bump(v, annotation: str):
    """Another value of the same kind: the smallest change of one stored fact."""
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return v + 1
    if isinstance(v, str):
        return v + "x"
    if isinstance(v, datetime):
        return v + SEC
    if isinstance(v, (set, frozenset)):
        return v | {"zz"}
    if isinstance(v, tuple):
        return v + ((LATER,) if "datetime" in annotation else ("zz",))
    if isinstance(v, list):
        return v + [LATER]
    if isinstance(v, dict):
        return {**v, (99 if "int," in annotation else "zz"): LATER if "datetime" in annotation else 1 if "int]" in annotation else "x"}
    if v is None:
        return LATER if "datetime" in annotation else 7 if "int" in annotation else ("zz",) if "tuple" in annotation else "x"
    raise AssertionError(f"no bump for {v!r}")


def walk(v):
    yield v
    if isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from walk(x)


def with_liveness_records(st: State) -> State:
    """The records a rich chain cannot reach while its custodians are live, added by hand: a founder's claim of
    the Custodian office, a succession claim, and a protocol epoch."""
    st.claims[900] = Claim(900, "hiram", "porter", "k" * 20, "r" * 20, T0, objected=T0 + DAY, objector="dan")
    st.succession = Succession(901, "alice", T0, end=T0 + DAY, canceled_by="ada")
    st.epoch = 1
    return st


EMPTY_ROOT = sha256(b"")
EMPTY_DIGEST = "abfb86b1c6152bcc676a96ac0ee9a378050879d467f7800ea3ac820e87b19ac9"     # SPEC section 4.11


def records(st: State) -> dict:
    """Every section of `st` as the digest writes it: name -> [[key, record], ...]."""
    return {name: ledger.section_records(st, name) for name in ledger.SECTIONS}


def both(test, st: State) -> str:
    """The digest of `st`, which the incremental path and the path from nothing must agree on."""
    got = st.digest()
    test.assertEqual(got, ledger.state_digest(st))
    return got


class Document(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain = rich_chain()
        cls.state = with_liveness_records(cls.chain.state())

    def test_the_empty_state_has_a_document_and_a_digest(self):
        doc = State().document()
        self.assertEqual(sorted(doc), ["history", "scalars", "sections", "v"])
        self.assertEqual((doc["v"], doc["scalars"]["seq"], doc["scalars"]["head"]), (2, -1, canon.ZERO_HASH))
        self.assertNotIn("time", doc["scalars"])
        self.assertEqual(doc["sections"], {name: EMPTY_ROOT for name in ledger.SECTIONS})
        self.assertEqual(doc["history"], {h: {"count": 0, "acc": canon.ZERO_HASH} for h in ledger.HISTORY})
        self.assertEqual(State().digest(), sha256(canonical(doc)))
        self.assertEqual((State().digest(), ledger.state_digest(State())), (EMPTY_DIGEST, EMPTY_DIGEST))

    def test_every_stored_field_reaches_exactly_one_section_or_scalar(self):
        fields = {f.name for f in dataclasses.fields(State)}
        parts = [set(ledger.SECTIONS), set(ledger.SCALARS), set(ledger.NOT_SECTIONS)]
        self.assertEqual(set.union(*parts), fields)            # a field added to State must be placed, and tested here
        self.assertEqual(sum(map(len, parts)), len(fields))    # …in one place only
        self.assertEqual(set(self.state.document()["scalars"]) | {"sunset", "council_call"}, set(ledger.SCALARS))

    def test_it_holds_only_json_values_and_no_null(self):
        doc = self.state.document()
        for v in walk([doc, records(self.state)]):
            self.assertIn(type(v), (dict, list, str, int, bool), v)             # no float, no null, no time object
        self.assertEqual(json.loads(canonical(doc)), doc)

    def test_a_section_root_is_the_rfc6962_root_of_its_sorted_leaves(self):
        doc = self.state.document()
        for name, recs in records(self.state).items():
            self.assertEqual([k for k, _ in recs], sorted(k for k, _ in recs), name)
            self.assertEqual(doc["sections"][name], merkle_root([sha256(canonical(r)) for r in recs]), name)
        self.assertGreater(len(records(self.state)["members"]), 7)

    def test_records_are_written_as_in_the_state_and_absent_values_are_left_out(self):
        recs = records(self.state)
        self.assertEqual([k for k, _ in recs["members"]], sorted(self.state.members))
        self.assertEqual([k for k, _ in recs["ballots"]], sorted(self.state.ballots))
        self.assertEqual([k for k, _ in recs["corrections"]], sorted(self.state.corrections))
        self.assertEqual([k for k, _ in recs["exams"]], [["alice", 2]])
        self.assertEqual(recs["known_keys"], [[k, True] for k in sorted(self.state.known_keys)])
        ada = dict(recs["members"])["ada"]
        self.assertEqual(ada["since"], [[1, "2027-01-01T00:00:00Z"], [2, "2027-01-01T00:00:00Z"], [3, "2027-01-01T00:00:00Z"]])
        self.assertNotIn("seat_until", ada)                                      # null: left out
        self.assertEqual((ada["sponsors"], ada["fraud_history"], ada["founder"]), ([], [], True))   # empty: present
        dan = dict(recs["members"])["dan"]
        self.assertEqual(dan["status"], "suspended")                             # the stored status, not a standing
        self.assertRegex(dan["suspended_until"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
        ballot = dict(recs["ballots"])["sus"]
        self.assertEqual(ballot["electors"], sorted(self.state.ballots["sus"].electors))
        self.assertEqual(ballot["reveals"], [["carol", "yes"], ["eve", "yes"], ["hiram", "yes"]])
        self.assertNotIn("result", dict(recs["ballots"])["open"])
        self.assertEqual([k for k, _ in recs["notes"]], [n["seq"] for n in self.state.notes])
        self.assertEqual(dict(recs["pins"])["CONSTITUTION.md"], "ab" * 32)
        self.assertEqual([p for p, _ in recs["prior_until"]], ["CONSTITUTION.md"])
        sc = self.state.document()["scalars"]
        self.assertEqual((sc["head"], sc["seq"]), (self.state.hashes[-1], len(self.state.hashes) - 1))
        self.assertEqual(sc["succession"], {"seq": 901, "by": "alice", "time": "2027-01-01T00:00:00Z",
                                            "end": "2027-01-02T00:00:00Z", "canceled_by": "ada"})

    def test_the_history_is_a_count_and_a_hash_chain(self):
        st = self.state
        self.assertEqual({h: n for h, (n, _) in st.history.items()},
                         {"amendments": 1, "ballots": 0, "beacons": 1, "checkpoints": 1, "notes": 0})
        (cp,) = [e for e in self.chain.entries if e["type"] == "witness"]
        leaf = sha256(canonical({"witness": "tyler"} | cp["body"]))            # null members left out: none here
        self.assertEqual(st.history["checkpoints"][1], sha256(bytes(32) + bytes.fromhex(leaf)))
        am = {"ballot": "am", "path": "CONSTITUTION.md", "new_sha256": "ab" * 32,
              "time": next(e["time"] for e in self.chain.entries if e["type"] == "ballot_close" and e["body"]["id"] == "am")}
        self.assertEqual(st.history["amendments"][1], sha256(bytes(32) + bytes.fromhex(sha256(canonical(am)))))
        self.assertEqual(st.degree_tables, [])                   # the index of degree tables: none was amended here

    def test_no_view_that_depends_on_time_is_in_it(self):
        st = copy.deepcopy(self.state)
        before = st.digest()
        for days in (0, 1, 40, 400, 4000):                    # asking about any time changes nothing that is stored
            now = st.time + days * DAY
            st.active(now), st.masters(now), st.halted(now), st.frozen("carol", now), st.recovering("carol", now)
            st.effective(T0, now), st.effective(T0, now, "open"), st.invited("yan", now), st.live("zoe", now)
            [st.correction_status(k, now) for k in st.corrections.values()]
            self.assertEqual(both(self, st), before)
        text = canonical(records(st)).decode()
        for word in ("dormant", "light", "standing", "live", "lapsed\":\"", "expires", "stayed"):
            self.assertNotIn(f'"{word}', text.replace('"lapsed":', ""), word)

    def changes(self, mutate, name):
        """`mutate` changes the digest, on a copy hashed from nothing and on a copy whose leaves were cached."""
        cold = copy.deepcopy(self.state)
        mutate(cold)
        warm = copy.deepcopy(self.state)
        warm.digest()                                         # every leaf cached: the change must reach the cache
        mutate(warm)
        self.assertEqual(warm.digest(), cold.digest(), name)
        self.assertEqual(cold.digest(), ledger.state_digest(cold), name)
        self.assertNotEqual(cold.digest(), self.state.digest(), name)
        return cold.digest()

    def test_every_field_of_the_state_changes_the_digest(self):
        bump_history = lambda h: lambda s: s.history.update({h: (s.history[h][0], "1" * 64)})
        change = {
            "name": lambda s: setattr(s, "name", s.name + "x"),
            "head": lambda s: setattr(s, "head", "f" * 64),
            "seq": lambda s: setattr(s, "seq", s.seq + 1),
            "time": lambda s: setattr(s, "time", s.time + SEC),
            "members": lambda s: s.members.pop("alice"),
            "witnesses": lambda s: s.witnesses.update(tyler=s.witnesses["tyler"] + "x"),
            "invitations": lambda s: s.invitations["yan"].update(github_id=1),
            "petitions": lambda s: s.petitions["zoe"]["vouches"].append("ada"),
            "ballots": lambda s: s.ballots.pop("sus"),
            "exams": lambda s: s.exams.pop(("alice", 2)),
            "pins": lambda s: s.pins.update({"README.md": "0" * 64}),
            "prior_pins": lambda s: s.prior_pins.update({"CONSTITUTION.md": "0" * 64}),
            "prior_until": lambda s: s.prior_until.update({"CONSTITUTION.md": LATER}),
            "council_call": lambda s: setattr(s, "council_call", 7),
            "council_pool": lambda s: setattr(s, "council_pool", ("ada",)),
            "declaration_sha256": lambda s: setattr(s, "declaration_sha256", "0" * 64),
            "known_keys": lambda s: s.known_keys.add("0" * 64),
            "custodians": lambda s: s.custodians.pop("keeper"),
            "custodian_threshold": lambda s: setattr(s, "custodian_threshold", 2),
            "corrections": lambda s: s.corrections.pop(min(s.corrections)),
            "sunset": lambda s: setattr(s, "sunset", LATER),
            "recoveries": lambda s: s.recoveries.pop("carol"),
            "notes": lambda s: s.notes[0].update(target="x"),
            "day": lambda s: setattr(s, "day", "2099-01-01"),
            "day_entries": lambda s: s.day_entries.update(zed=1),
            "acts": lambda s: setattr(s, "acts", s.acts + 1),
            "witness_marks": lambda s: s.witness_marks["tyler"].update(acts=0),
            "claims": lambda s: s.claims.pop(900),
            "succession": lambda s: setattr(s, "succession", None),
            "epoch": lambda s: setattr(s, "epoch", s.epoch + 1),
        } | {f"history.{h}": bump_history(h) for h in ledger.HISTORY} \
          | {f"history.{h}.count": (lambda h: lambda s: s.history.update({h: (s.history[h][0] + 1, s.history[h][1])}))(h)
             for h in ledger.HISTORY}
        fields = {f.name for f in dataclasses.fields(State)}
        self.assertEqual({k.split(".")[0] for k in change} | {"hashes", "retired", "degree_tables"}, fields)
        seen = {self.state.digest()}
        for name, mutate in change.items():
            got = self.changes(mutate, name)
            self.assertNotIn(got, seen, name)                  # …and no two changes give the same digest
            seen.add(got)

    def test_what_the_digest_leaves_out_is_committed_elsewhere(self):
        """`hashes` through `head` and `seq`; the two indexes of the history through the history itself."""
        base = self.state.digest()
        for mutate in (lambda s: s.hashes.append("0" * 64), lambda s: s.retired.add("gone"),
                       lambda s: s.degree_tables.append("0" * 64)):
            st = copy.deepcopy(self.state)
            mutate(st)
            self.assertEqual(both(self, st), base)

    def test_every_field_of_every_record_changes_the_digest(self):
        records_of = {
            Member: lambda s: s.members["alice"], Ballot: lambda s: s.ballots["adm-alice"],
            Exam: lambda s: s.exams[("alice", 2)], Custodian: lambda s: s.custodians["warden"],
            Correction: lambda s: s.corrections[max(s.corrections)], Recovery: lambda s: s.recoveries["carol"],
            Claim: lambda s: s.claims[900], Succession: lambda s: s.succession,
        }
        count = 0
        for cls, pick in records_of.items():
            self.assertIsInstance(pick(self.state), cls)
            for f in dataclasses.fields(cls):
                def mutate(s, pick=pick, f=f):
                    rec = pick(s)
                    setattr(rec, f.name, bump(getattr(rec, f.name), str(f.type)))
                self.changes(mutate, f"{cls.__name__}.{f.name}")
                count += 1
        self.assertEqual(count, sum(len(dataclasses.fields(k)) for k in records_of))
        for name, fld, value in (("invitations", "by", "x"), ("invitations", "time", LATER), ("petitions", "key", "x"),
                                 ("petitions", "time", LATER), ("petitions", "github_id", 1)):
            def mutate(s, name=name, fld=fld, value=value):
                next(iter(getattr(s, name).values()))[fld] = value
            self.changes(mutate, f"{name}.{fld}")

    def test_one_vote_one_sponsor_or_one_elector_changes_it(self):
        """A change made in place to a list or a map of a record reaches the digest once the record is touched."""
        def touched(pick, change):
            return lambda s: (change(pick(s)), pick(s).touch())
        for mutate in (touched(lambda s: s.ballots["sus"], lambda b: b.reveals.update(hiram="no")),
                       touched(lambda s: s.ballots["open"], lambda b: b.commits.update(hiram="0" * 64)),
                       lambda s: setattr(s.ballots["open"], "electors", s.ballots["open"].electors - {"hiram"}),
                       touched(lambda s: s.ballots["adm-alice"], lambda b: b.frozen["vouches"].reverse()),
                       touched(lambda s: s.members["alice"], lambda m: m.since.update({2: LATER})),
                       touched(lambda s: s.members["alice"], lambda m: m.activity.pop()),
                       touched(lambda s: s.exams[("alice", 2)],
                               lambda x: x.reports.update({x.examiners[0]: "fail"})),
                       lambda s: setattr(s.corrections[max(s.corrections)], "objections", ("ada",))):
            self.changes(mutate, mutate)

    def test_the_incremental_digest_equals_the_digest_from_nothing_after_every_entry(self):
        st = State()
        for e in self.chain.entries:
            apply(st, e, verifier=by_key)
            self.assertEqual(st.digest(), ledger.state_digest(st), e["seq"])


class SameEverywhere(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain = rich_chain()
        cls.state = cls.chain.state()

    def test_one_pass_equals_a_prefix_then_the_rest(self):
        entries = self.chain.entries
        want = self.state.digest()
        for cut in (1, 7, len(entries) // 2, len(entries) - 1):
            st = replay(entries[:cut], verifier=by_key)
            for e in entries[cut:]:
                apply(st, e, verifier=by_key)
            self.assertEqual(st.digest(), want, cut)
        st = State()
        for i, e in enumerate(entries):                         # and at every step: the prefix replayed from nothing
            apply(st, e, verifier=by_key)
            if i % 9 == 0:
                self.assertEqual(st.digest(), replay(entries[: i + 1], verifier=by_key).digest(), i)

    def test_entries_from_disk_equal_entries_in_memory(self):
        led = write_ledger(tmpdir(self) / "led", self.chain.entries)
        self.assertEqual(replay(load(led), verifier=by_key).digest(), self.state.digest())

    def test_the_order_in_which_maps_and_sets_were_filled_does_not_matter(self):
        want = self.state.digest()
        for seed in range(5):
            other = shuffled(self.state, random.Random(seed))
            self.assertEqual(other.digest(), want, seed)
            self.assertEqual(ledger.state_digest(other), want, seed)
            self.assertEqual(canonical(records(other)), canonical(records(self.state)))
        self.assertNotEqual(list(shuffled(self.state, random.Random(1)).members), list(self.state.members))

    def test_two_processes_with_different_hash_seeds_agree(self):
        code = "from tests.test_digest import rich_chain; print(rich_chain().state().digest())"
        got = set()
        for seed in ("1", "4242"):
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO, timeout=600,
                               env={**os.environ, "PYTHONPATH": str(REPO / "src"), "PYTHONHASHSEED": seed})
            self.assertEqual(r.returncode, 0, r.stderr)
            got.add(r.stdout.strip())
        self.assertEqual(got, {self.state.digest()})

    def test_a_copy_of_the_state_has_the_same_digest(self):
        self.assertEqual(copy.deepcopy(self.state).digest(), self.state.digest())


class Checkpoint(unittest.TestCase):
    def test_a_checkpoint_states_the_digest_of_the_state_before_it(self):
        c = founded(witnesses=["tyler"])
        c.add("work", "ada", {"ref": "https://example.org/a"})
        st = c.state()
        c.add("witness", "tyler", checkpoint(st))
        after = c.state()
        record = {"witness": "tyler", "upto_seq": 1, "head": st.head, "state_sha256": st.digest(), "state_version": 2}
        self.assertEqual(after.history["checkpoints"],             # the record, absorbed: root and anchor left out
                         (1, sha256(bytes(32) + bytes.fromhex(sha256(canonical(record))))))
        self.assertNotEqual(after.digest(), st.digest())            # the checkpoint itself is a fact of the next state
        c.add("work", "carol", {"ref": "https://example.org/b"}, days=1)
        after = c.state()
        c.add("witness", "tyler", checkpoint(after))                # and the next checkpoint covers it
        self.assertEqual(c.entries[-1]["body"]["state_sha256"], after.digest())
        self.assertEqual(c.state().history["checkpoints"][0], 2)

    def test_a_wrong_digest_is_refused(self):
        c = founded(witnesses=["tyler"])
        genesis = c.state()
        c.add("work", "ada", {"ref": "https://example.org/a"})
        st = c.state()
        for wrong in ("0" * 64, genesis.digest(), st.digest().upper(), st.digest()[:-1], ""):
            c.add("witness", "tyler", checkpoint(st, state_sha256=wrong))
            c.refused(self, "entry 2: witness state digest mismatch")
        c.add("witness", "tyler", {k: v for k, v in checkpoint(st).items() if k != "state_sha256"})
        c.refused(self, "entry 2: malformed witness entry: missing field 'state_sha256'")
        c.add("witness", "tyler", checkpoint(st, state_sha256=7))
        c.refused(self, "field 'state_sha256' must be a string")
        c.add("witness", "tyler", checkpoint(st))
        c.state()

    def test_a_checkpoint_covers_every_entry_before_it(self):
        c = founded(witnesses=["tyler"])
        genesis = c.state()
        c.add("work", "ada", {"ref": "https://example.org/a"})
        st = c.state()
        for upto in (0, 2, -1):
            c.add("witness", "tyler", checkpoint(genesis if upto == 0 else st, upto_seq=upto))
            c.refused(self, r"entry 2: witness upto_seq must be 1 \(a checkpoint covers every entry before it\)")
        c.add("witness", "tyler", checkpoint(st, head=genesis.head))
        c.refused(self, "entry 2: witness head mismatch")
        c.add("witness", "tyler", checkpoint(st, root="0" * 64))
        c.refused(self, "witness Merkle root mismatch")
        c.add("witness", "tyler", checkpoint(st, root=merkle_root(st.hashes)))
        self.assertEqual((c.state().history["checkpoints"][0], st.entries_root()), (1, merkle_root(st.hashes)))

    def test_a_state_that_differs_in_one_fact_fails_the_checkpoint(self):
        """What the rule is for: a verifier whose state went wrong anywhere is stopped at the next checkpoint."""
        c = founded(witnesses=["tyler"])
        c.add("work", "ada", {"ref": "https://example.org/a"})
        st = c.state()
        c.add("witness", "tyler", checkpoint(st))
        entry = c.entries[-1]
        drifted = copy.deepcopy(st)
        drifted.members["ada"].last_work = None                     # one fact another implementation got wrong
        with self.assertRaisesRegex(Invalid, "entry 2: witness state digest mismatch"):
            apply(drifted, entry, verifier=by_key)
        apply(copy.deepcopy(st), entry, verifier=by_key)


class Retirement(unittest.TestCase):
    """A ballot no rule reads any more leaves `ballots` for the history, BALLOT_RETIRE_DAYS after it ended."""

    def admitted(self):
        c = lodge(custodians=(("warden", "carol"),))
        initiate(c, "alice")                          # hiram opens, ada sponsors: carol's custodian is no party
        return c, c.now                               # the close of adm-alice

    def test_the_horizon_covers_every_rule_that_reads_a_ballot_that_ended(self):
        self.assertEqual(ledger.BALLOT_RETIRE_DAYS, 111)
        self.assertEqual(ledger.BALLOT_RETIRE_DAYS,
                         ledger.UNDO_WINDOW_DAYS + ledger.NOTICE_DAYS + ledger.APPLY_WINDOW_DAYS)
        self.assertGreaterEqual(ledger.BALLOT_RETIRE_DAYS, max(ledger.RERUN_DAYS, ledger.REOPEN_AFTER_DAYS))

    def test_a_ballot_leaves_the_state_one_second_after_the_horizon(self):
        c, closed = self.admitted()
        c.now = closed + ledger.BALLOT_RETIRE_DAYS * DAY
        c.add("work", "ada", {"ref": "https://example.org/a"})
        st = c.state()
        self.assertIn("adm-alice", st.ballots)                                   # the last second: still read
        record = ledger.section_records(st, "ballots")[0]
        c.add("work", "carol", {"ref": "https://example.org/b"}, days=1 / 86400)
        after = c.state()
        self.assertNotIn("adm-alice", after.ballots)
        self.assertEqual(after.retired, {"adm-alice"})
        self.assertEqual(after.history["ballots"],
                         (1, sha256(bytes(32) + bytes.fromhex(sha256(canonical(record))))))
        both(self, after)
        warm = State()                                                           # its leaf, cached by earlier digests
        for e in c.entries:
            apply(warm, e, verifier=by_key)
            warm.digest()
        self.assertEqual(warm.history, after.history)
        self.assertEqual(after.members["alice"].status, "active")                # what the ballot did stays done
        open_ballot(c, "adm-alice", "ada", "amendment", {"path": "README.md", "new_sha256": "ab" * 32})
        c.refused(self, "ballot id 'adm-alice' is already used")                 # its id is never used again

    def test_the_longest_reader_still_finds_it_an_undo_posted_on_day_90_and_applied_on_day_111(self):
        from tests.test_custodian import apply_, undo
        c, closed = self.admitted()
        c.now = closed + ledger.UNDO_WINDOW_DAYS * DAY
        u = undo(c, "adm-alice")
        apply_(c, u, days=ledger.NOTICE_DAYS + ledger.APPLY_WINDOW_DAYS)
        st = c.state()
        self.assertEqual((c.now - closed, st.ballots["adm-alice"].result, st.members["alice"].status),
                         (ledger.BALLOT_RETIRE_DAYS * DAY, "undone", "voided"))
        c.add("work", "ada", {"ref": "https://example.org/a"}, days=1 / 86400)
        self.assertNotIn("adm-alice", c.state().ballots)

    def test_a_correction_that_names_a_retired_ballot_is_refused_with_its_own_message(self):
        from tests.test_custodian import undo
        c, closed = self.admitted()
        c.now = closed + (ledger.BALLOT_RETIRE_DAYS + 1) * DAY
        c.add("work", "ada", {"ref": "https://example.org/a"})
        undo(c, "adm-alice")
        c.refused(self, "ballot adm-alice ended more than 111 days ago and left the state")

    def test_a_refused_entry_retires_nothing(self):
        c, closed = self.admitted()
        st = c.state()
        late = copy.deepcopy(c)
        late.now = closed + 200 * DAY
        late.add("work", "nobody", {"ref": "https://example.org/a"})
        with self.assertRaises(Invalid):
            apply(st, late.entries[-1], verifier=by_key)
        self.assertIn("adm-alice", st.ballots)
        self.assertEqual(st.history["ballots"][0], 0)

    def test_a_voided_ballot_retires_after_the_void_and_a_state_edited_by_hand_follows(self):
        from tests.test_custodian import apply_, void
        c = lodge(founders=SEVEN)
        sanction(c, "s", member="dan", by="ada")
        v = void(c, "s")
        apply_(c, v, days=ledger.NOTICE_DAYS)
        voided = c.now
        c.now = voided + ledger.BALLOT_RETIRE_DAYS * DAY + SEC
        c.add("work", "ada", {"ref": "https://example.org/a"})
        st = c.state()
        self.assertEqual((st.retired, list(st.ballots)), ({"s"}, []))
        hand = replay(c.entries[:-1], verifier=by_key)
        hand._ended = None                                       # the order of ends, rebuilt from the stored facts
        apply(hand, c.entries[-1], verifier=by_key)
        self.assertEqual(hand.digest(), st.digest())


class EntriesRoot(unittest.TestCase):
    def test_the_frontier_gives_the_root_from_nothing_for_every_size(self):
        from openmasonry.crypto import merkle_append, merkle_frontier_root
        sizes = set(range(1, 2001)) | {2 ** k + d for k in range(1, 15) for d in (-1, 0, 1)}
        leaves = [sha256(str(i)) for i in range(max(sizes))]
        frontier = []
        self.assertEqual(merkle_frontier_root(frontier), merkle_root([]))
        for n, leaf in enumerate(leaves, 1):
            merkle_append(frontier, bytes.fromhex(leaf))
            self.assertLessEqual(len(frontier), n.bit_length())
            if n in sizes:
                self.assertEqual(merkle_frontier_root(frontier), merkle_root(leaves[:n]), n)

    def test_the_state_follows_its_hashes(self):
        st = State()
        self.assertEqual(st.entries_root(), merkle_root([]))
        for i in range(70):
            st.hashes.append(sha256(str(i)))
            if i % 9 == 0:
                self.assertEqual(st.entries_root(), merkle_root(st.hashes), i)
        del st.hashes[5:]                                        # a state edited by hand: read again from nothing
        self.assertEqual(st.entries_root(), merkle_root(st.hashes))


class Bounded(unittest.TestCase):
    """What left the state because no rule reads it, and the scan the effective clock no longer makes."""

    def test_activity_keeps_one_point_per_day_and_nothing_older_than_the_window(self):
        m = Member("ada", "k", 3, {1: T0}, activity=[T0])
        window = canon.LIGHT_WINDOW_DAYS
        self.assertEqual(window, 10 * canon.LIGHT_HALF_LIFE_DAYS)
        for day in range(1, window + 400):
            m.credit(T0 + day * DAY)
            m.credit(T0 + day * DAY + 3600 * SEC)                     # the same UTC day: one point, at the later time
        newest = T0 + (window + 399) * DAY + 3600 * SEC
        self.assertEqual(m.activity[-1], newest)
        self.assertEqual(len(m.activity), window + 1)
        self.assertTrue(all(newest - t <= window * DAY for t in m.activity))
        self.assertEqual(m.activity, sorted(m.activity))
        self.assertFalse(m.dormant(newest + 365 * DAY))
        self.assertTrue(m.dormant(newest + 365 * DAY + SEC))          # dormancy reads the newest point alone
        full = sum(0.5 ** ((newest - (T0 + d * DAY + 3600 * SEC)).total_seconds() / 86400 / 180) for d in range(1, window + 400))
        self.assertAlmostEqual(m.light(newest), full, delta=0.3)      # what was dropped weighed less than 0.001 a point

    def test_dormancy_and_the_sunset_give_what_the_scans_gave(self):
        """`dormant` reads the newest point alone (the list is ascending), and the Sunset stops counting at the
        seventh Master Builder: both equal the scans they replaced, at every time asked."""
        st = with_liveness_records(rich_chain().state())
        for m in st.members.values():
            self.assertEqual(m.activity, sorted(m.activity))
        for days in (0, 200, 364, 366, 800):
            now = st.time + days * DAY
            for m in st.members.values():
                self.assertEqual(m.dormant(now), ledger.expired(max(m.activity, default=m.since[1]), now, 365))
            for witnesses in (3, 4):
                other = copy.deepcopy(st)
                other.witnesses = {f"w{i}": "k" for i in range(witnesses)}
                for m in list(other.members.values())[:9]:
                    m.founder, m.degree = False, max(m.degree, 3)
                old = len(other.witnesses) >= 4 and sum(1 for x in other.masters(now)
                                                        if not other.members[x].founder) >= 7
                self.assertEqual(ledger.sunset_reached(other, now), old, (days, witnesses))
                self.assertEqual(other.non_founder_masters(now),
                                 sum(1 for x in other.masters(now) if not other.members[x].founder))

    def test_a_point_exactly_at_the_edge_of_the_window_is_kept(self):
        m = Member("ada", "k", 3, {1: T0}, activity=[T0])
        m.credit(T0 + canon.LIGHT_WINDOW_DAYS * DAY)
        self.assertEqual(m.activity, [T0, T0 + canon.LIGHT_WINDOW_DAYS * DAY])
        m.credit(T0 + canon.LIGHT_WINDOW_DAYS * DAY + SEC)
        self.assertEqual(m.activity, [T0 + canon.LIGHT_WINDOW_DAYS * DAY + SEC])

    @staticmethod
    def scanned(st: State, ballot):
        """`pauses` as it was defined: over every correction."""
        if ballot is not None and ballot in st.ballots and st.ballots[ballot].kind == "custodian":
            return []
        spans = sorted(st.span(c) for c in st.corrections.values()
                       if c.act == "halt" or (ballot is not None and c.act == "stay" and c.target["ballot"] == ballot))
        merged = []
        for a, b in spans:
            if b <= a:
                continue
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        return merged

    def test_the_index_of_pauses_gives_what_a_scan_of_every_correction_gives(self):
        c = lodge(founders=SEVEN)
        sanction(c, "s", member="carol")
        sanction(c, "t", member="dan")
        self.assertEqual(c.state().pauses("s"), [])
        correct(c, "halt", {}, "attack_in_progress", days=1)
        st = c.state()
        self.assertEqual(st.pauses(), self.scanned(st, None))
        c.add("correction_withdraw", "warden", {"seq": st.seq}, days=2)
        correct(c, "stay", {"ballot": "s"}, days=1)
        correct(c, "note", {"action": "hide", "target": "issue:1", "rule": "ROOMS.md"})
        correct(c, "halt", {}, "attack_in_progress", days=95)
        st = c.state()
        for ballot in (None, "s", "t", "nope"):
            self.assertEqual(st.pauses(ballot), self.scanned(st, ballot), ballot)
        self.assertEqual(len(st.pauses()), 2)
        self.assertEqual(len(st.pauses("s")), 3)
        self.assertEqual(st.effective(T0, c.now + 30 * DAY, "s"),
                         (c.now + 30 * DAY - T0) - sum((b - a for a, b in self.scanned(st, "s")), timedelta(0)))

    def test_the_index_follows_a_state_that_grows_after_it_was_first_read(self):
        c = lodge(founders=SEVEN)
        st = c.state()
        self.assertEqual(st.pauses(), [])                                 # the index has been read once, empty
        st.corrections[3] = Correction(3, "warden", "halt", {}, "attack_in_progress", REASON, T0 + DAY, until=T0 + 15 * DAY)
        self.assertEqual(st.pauses(), [(T0 + DAY, T0 + 15 * DAY)])
        st.corrections[4] = Correction(4, "warden", "stay", {"ballot": "b"}, "protocol_defect", REASON, T0 + 20 * DAY,
                                       until=T0 + 34 * DAY)
        self.assertEqual(st.pauses("b"), [(T0 + DAY, T0 + 15 * DAY), (T0 + 20 * DAY, T0 + 34 * DAY)])
        self.assertEqual(copy.deepcopy(st).pauses("b"), st.pauses("b"))
        del st.corrections[4], st.corrections[3]                          # a state edited by hand: read again from nothing
        self.assertEqual(st.pauses("b"), [])

    def test_replay_does_not_scan_the_corrections_for_the_clock(self):
        c = lodge(founders=SEVEN)
        for i in range(12):
            correct(c, "note", {"action": "hide", "target": f"issue:{i}", "rule": "ROOMS.md"}, days=1)
        st = c.state()
        seen = []
        real = State.span
        try:
            State.span = lambda self, k: (seen.append(k.seq), real(self, k))[1]
            for _ in range(50):
                st.effective(T0, c.now)
                st.invited("nobody", c.now)
        finally:
            State.span = real
        self.assertEqual(seen, [])                                        # twelve corrections, none a pause: none is read


if __name__ == "__main__":
    unittest.main()
