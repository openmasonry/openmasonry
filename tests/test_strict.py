"""Strict replay: one encoding, exact shapes, exact durations and no gaps between the rules.

Most tests here use `Fast`, a `Chain` that needs no OpenSSH: the "signature" of an entry is the public key
that signed it and the injected verifier compares the two, so the signer rule is still exercised.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from openmasonry import canon, crypto, govern, ledger
from openmasonry.ledger import (BEACON_DELAY_ROUNDS, Ballot, Exam, Invalid, Member, State, apply, commitment, decide,
                                drand_round, drand_time, entry_hash, load, replay, ts)
from openmasonry.lot import draw
from tests.test_protocol import (canon_digest, DECL, FOUNDERS, T0, Chain, checkpoint, entry_file, genesis_body, initiate,
                                 invite, salt_of, witness_subject)

REPO = Path(__file__).resolve().parents[1]
DAY, SEC = timedelta(days=1), timedelta(seconds=1)
URL = "https://example.org/work"


def absorbed(*records) -> tuple[int, str]:
    """The (count, accumulator) of a history that absorbed exactly `records` (SPEC section 4.11)."""
    acc = bytes(32)
    for r in records:
        acc = hashlib.sha256(acc + hashlib.sha256(crypto.canonical(r)).digest()).digest()
    return len(records), acc.hex()


def tmpdir(test) -> Path:
    t = tempfile.TemporaryDirectory()
    test.addCleanup(t.cleanup)
    return Path(t.name)


def fake_key(name: str) -> str:
    """A real Ed25519 public key (a point of order L) derived from a name, without ssh-keygen."""
    scalar = int.from_bytes(hashlib.sha512(name.encode()).digest(), "little") % crypto._L
    raw = crypto._encode(crypto._mul(scalar, crypto._B))
    return "ssh-ed25519 " + base64.b64encode(crypto._KEY_HEAD + raw).decode()


def by_key(payload, sig, actor, key) -> bool:
    return sig == key


class Fast(Chain):
    def __init__(self):
        super().__init__(None)

    def key(self, login: str) -> str:
        if login not in self.keys:
            self.keys[login] = (None, fake_key(login))
        return self.keys[login][1]

    def add(self, typ, actor, body, days=0, key_of=None):
        self.now += timedelta(days=days)
        prev = entry_hash(self.entries[-1]) if self.entries else canon.ZERO_HASH
        e = {"seq": len(self.entries), "prev": prev, "time": self.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "type": typ, "actor": actor, "body": body, "sig": self.key(key_of or actor)}
        self.entries.append(e)
        return e

    def prove(self, name, message):
        return self.key(name)

    def state(self):
        return replay(self.entries, verifier=by_key)

    def refused(self, test, pattern: str):
        """The last entry is refused with `pattern`; it is then dropped so the chain can go on."""
        with test.assertRaisesRegex(Invalid, pattern):
            self.state()
        self.entries.pop()


def founded(witnesses=(), **over) -> Fast:
    c = Fast()
    c.add("genesis", FOUNDERS[0], genesis_body(c, FOUNDERS, witnesses, **over))
    return c


def petition(c, who, key_of=None):
    """The bare `petition` entry: the invitation it needs is added by the test (`invite`)."""
    c.add("petition", who, {"key": c.key(key_of or who), "declaration_sha256": DECL}, key_of=key_of)


def open_exam(c, who, degree, days=0.0):
    rnd = drand_round(c.now + timedelta(days=days)) + BEACON_DELAY_ROUNDS
    c.add("exam_open", who, {"candidate": who, "degree": degree, "work_ref": URL, "beacon_round": rnd}, days=days)
    return rnd


def draw_exam(c, who, degree, rnd, days=0.34):
    c.add("exam_draw", who, {"candidate": who, "degree": degree, "beacon": f"{rnd:064x}"}, days=days)
    return c.state().exams[(who, degree)]


def mk(login, degree=3, t=T0, **kw) -> Member:
    kw.setdefault("activity", [t])
    return Member(login, fake_key(login), degree, {i: t for i in range(1, degree + 1)}, **kw)


def hand_state(*members, **kw) -> State:
    return State(members={m.login: m for m in members}, pins={"canon/degrees.toml": canon_digest()},
                 declaration_sha256=DECL, **kw)


def write_ledger(d: Path, entries) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for e in entries:
        entry_file(d, e["seq"]).write_text(json.dumps(e))
    return d


# ---------------------------------------------------------------- the parser and the loader ----

class StrictJson(unittest.TestCase):
    def refuse(self, text: str, pattern: str = ""):
        with self.assertRaisesRegex(ValueError, pattern):
            ledger.strict_json(text.encode("utf-8") if isinstance(text, str) else text)

    def test_floats_exponents_constants_and_null_are_refused(self):
        for bad in ('{"a": 1.0}', '{"a": 1e2}', '{"a": 1E2}', '{"a": -0.0}', '{"a": NaN}', '{"a": Infinity}',
                    '{"a": -Infinity}', '{"a": null}', '{"a": [1, null]}', "null", "1.5"):
            self.refuse(bad)

    def test_integers_are_bounded_by_the_text_before_any_conversion(self):
        top = 2 ** 53 - 1
        self.assertEqual(ledger.strict_json(f'{{"a": {top}, "b": -{top}}}'.encode()), {"a": top, "b": -top})
        self.refuse(f'{{"a": {top + 1}}}', "integer")
        self.refuse(f'{{"a": -{top + 1}}}', "integer")
        self.refuse('{"a": ' + "9" * 5000 + "}", "integer")          # far past CPython's digit limit: same refusal
        self.refuse('{"a": ' + "9" * 17 + "}", "integer")

    def test_nesting_is_limited_to_six_levels(self):
        self.assertEqual(ledger.strict_json(b'{"a": {"b": {"c": {"d": {"e": {}}}}}}'), {"a": {"b": {"c": {"d": {"e": {}}}}}})
        self.refuse('{"a": {"b": {"c": {"d": {"e": {"f": {}}}}}}}', "nest")
        self.refuse("[" * 7 + "]" * 7, "nest")
        self.refuse("[" * 5000 + "]" * 5000, "nest")                # never the runtime's recursion limit

    def test_duplicate_keys_bom_bad_utf8_and_non_ascii_strings_are_refused(self):
        self.refuse('{"a": 1, "a": 2}', "duplicate")
        self.refuse(b'\xef\xbb\xbf{"a": 1}')
        self.refuse(b'{"a": "\xff"}')
        self.refuse('{"a": "日本"}', "ASCII")
        self.refuse('{"a": "\\ud800"}', "ASCII")
        self.refuse('{"a": "tab\\there"}', "ASCII")
        self.refuse('{"Привет": 1}', "ASCII")
        self.assertEqual(ledger.strict_json(b'{"a": "line\\nfeed is the only control character"}')["a"][:5], "line\n")

    def test_strict_value_judges_values_built_in_memory_the_same_way(self):
        ledger.strict_value({"a": [1, "x", True, {"b": -5}]})
        for bad in ({"a": 1.0}, {"a": None}, {"a": 2 ** 53}, {"a": (1, 2)}, {1: "a"}, {"a": "λ"}, {"a": b"x"},
                    {"a": float("nan")}):
            with self.assertRaises(ValueError):
                ledger.strict_value(bad)


class Loader(unittest.TestCase):
    def setUp(self):
        self.c = founded()
        self.c.add("work", "ada", {"ref": URL})
        self.d = write_ledger(tmpdir(self) / "led", self.c.entries)
        self.shard = self.d / "0000"

    def refused(self, seq: int, message: str):
        with self.assertRaises(Invalid) as err:
            load(self.d)
        self.assertEqual(str(err.exception), f"entry {seq}: {message}")

    def test_a_clean_directory_loads_and_gitkeep_is_allowed(self):
        (self.d / ".gitkeep").write_text("")
        self.assertEqual(load(self.d), self.c.entries)
        self.assertEqual(load(self.d / "absent"), [])               # no directory yet: an empty ledger
        with self.assertRaises(Invalid):
            load(self.shard / "000000.json")                        # a file where the directory should be

    def test_the_path_of_an_entry_is_its_shard_and_its_seq(self):
        names = {0: "0000/000000.json", 999: "0000/000999.json", 1000: "0001/001000.json", 1001: "0001/001001.json",
                 999999: "0999/999999.json", 1000000: "1000/1000000.json", 9999999: "9999/9999999.json",
                 10000000: "10000/10000000.json", 2 ** 53 - 1: "9007199254740/9007199254740991.json"}
        for seq, name in names.items():
            self.assertEqual(ledger.entry_name(seq), name)
            self.assertEqual(ledger.entry_seq(name), seq)
            self.assertEqual(ledger.entry_path(self.d, seq), self.d / name)
        for name in ("000000.json", "0000/0.json", "000/000000.json", "00000/000000.json", "0001/000999.json",
                     "0000/001000.json", "1000/0999999.json", "01000/1000000.json", "0000/000000.JSON", "0000/000000.json/x",
                     "0000/00001a.json", "0000/.gitkeep", ".gitkeep", "0000//000000.json", "0000\\000000.json"):
            self.assertIsNone(ledger.entry_seq(name), name)
        self.assertEqual(ledger.SHARD_SIZE, 1000)

    def test_entries_fill_each_shard_and_go_on_in_the_next(self):
        def listing(seqs):
            return [ledger.entry_name(s) for s in seqs]
        self.assertEqual(ledger.entry_order(listing(reversed(range(2003)))), listing(range(2003)))
        self.assertEqual(ledger.entry_order(listing(range(1001)) + [".gitkeep"]), listing(range(1001)))
        with self.assertRaises(Invalid) as err:
            ledger.entry_order(listing(range(999)) + listing([1000]))           # 999, the last of shard 0000, is missing
        self.assertEqual(str(err.exception), "entry 999: ledger file 0000/000999.json is missing (the entries are numbered "
                                             "from 0 without a gap)")
        with self.assertRaises(Invalid) as err:
            ledger.entry_order(listing(range(1000)) + ["0000/001000.json"])     # entry 1000 in a full shard
        self.assertEqual(str(err.exception), "entry 1000: ledger file 0000/001000.json is in the wrong shard: entry 1000 is "
                                             "0001/001000.json")

    def test_a_directory_of_shards_loads_across_the_boundaries(self):
        entries = [{"seq": i} for i in range(1002)]
        d = tmpdir(self) / "led"
        for e in entries:
            entry_file(d, e["seq"]).write_text(json.dumps(e))
        self.assertEqual(sorted(os.listdir(d)), ["0000", "0001"])
        self.assertEqual(len(os.listdir(d / "0000")), 1000)
        self.assertEqual(load(d), entries)
        (d / "0001" / "001000.json").rename(d / "0000" / "001000.json")       # a full shard holds no 1001st entry
        with self.assertRaises(Invalid) as err:
            load(d)
        self.assertEqual(str(err.exception), "entry 1000: ledger file 0000/001000.json is in the wrong shard: entry 1000 "
                                             "is 0001/001000.json")

    def test_a_far_seq_is_held_to_its_shard(self):
        d = tmpdir(self) / "led"
        entry_file(d, 0).write_text(json.dumps(self.c.entries[0]))
        far = d / "9999" / "9999999.json"
        far.parent.mkdir()
        far.write_text("{}")
        with self.assertRaises(Invalid) as err:
            load(d)
        self.assertEqual(str(err.exception), "entry 1: ledger file 0000/000001.json is missing (the entries are numbered "
                                             "from 0 without a gap)")
        far.rename(d / "9999" / "9999998.json")
        with self.assertRaisesRegex(Invalid, "^entry 1: .* is missing"):
            load(d)
        (d / "9999" / "9999998.json").rename(d / "9999" / "10000000.json")
        with self.assertRaises(Invalid) as err:
            load(d)
        self.assertEqual(str(err.exception), "entry 10000000: ledger file 9999/10000000.json is in the wrong shard: entry "
                                             "10000000 is 10000/10000000.json")

    def test_an_entry_in_another_shard_is_invalid(self):
        (self.shard / "000001.json").rename(self.d / "0001")
        self.refused(1000, "ledger shard 0001 must be a directory, not a symlink or a file")
        (self.d / "0001").unlink()
        entry_file(self.d, 1001).write_text(json.dumps(self.c.entries[1]))
        self.refused(1, "ledger file 0000/000001.json is missing (the entries are numbered from 0 without a gap)")
        (self.d / "0001" / "001001.json").rename(self.d / "0001" / "000001.json")
        self.refused(1, "ledger file 0001/000001.json is in the wrong shard: entry 1 is 0000/000001.json")
        (self.d / "0001" / "000001.json").rename(self.d / "000001.json")         # the flat layout of old
        (self.d / "0001").rmdir()
        self.refused(1, "ledger file 000001.json is not in its shard: entry 1 is 0000/000001.json")
        (self.d / "000001.json").rename(self.shard / "000001.json")
        self.assertEqual(load(self.d), self.c.entries)

    def test_anything_else_at_either_level_is_invalid(self):
        not_an_entry = ("ledger file {} is not an entry (the directory holds only the entries, each named after its seq "
                        "in the shard of seq // 1000: 0000/000000.json, 0000/000001.json, …)")
        for name in ("notes.txt", ".DS_Store", "000002.json.bak", "000002.jsn", "2.json", "README.md", "0000001.json",
                     ".gitkeep", "00001a.json", "000002.JSON"):
            (self.shard / name).write_text("{}")
            self.refused(0, not_an_entry.format(f"0000/{name}"))
            (self.shard / name).unlink()
        for name in ("notes.txt", ".DS_Store", "README.md", "2.json", "0000001.json"):
            (self.d / name).write_text("{}")
            self.refused(0, not_an_entry.format(name))
            (self.d / name).unlink()
        (self.shard / "000002.json").mkdir()
        self.refused(2, "ledger file 0000/000002.json must be a regular file, not a symlink or a directory")
        (self.shard / "000002.json").rmdir()
        (self.shard / "sub").mkdir()
        self.refused(0, not_an_entry.format("0000/sub"))
        (self.shard / "sub" / "000002.json").write_text("{}")
        self.refused(0, not_an_entry.format("0000/sub"))
        with self.assertRaisesRegex(Invalid, "^entry 0: ledger file 0000/sub/000002.json is not an entry"):
            ledger.entry_order(["0000/000000.json", "0000/sub/000002.json"])      # a listing of git (ls-tree -r)
        shutil.rmtree(self.shard / "sub")
        for name in ("sub", "000", "00000", "0001x", "1"):
            (self.d / name).mkdir()
            self.refused(0, f"ledger directory {name} is not a shard (shards are named after seq // 1000, in four digits "
                            "at least: 0000, 0001, …)")
            (self.d / name).rmdir()
        (self.d / "0001").mkdir()
        self.refused(1000, "ledger shard 0001 holds no entry")
        (self.d / "0001").rmdir()
        self.assertEqual(load(self.d), self.c.entries)

    def test_links_are_refused_at_either_level(self):
        outside = write_ledger(tmpdir(self) / "elsewhere", self.c.entries)
        (self.shard / "000001.json").unlink()
        (self.shard / "000001.json").symlink_to(outside / "0000" / "000001.json")
        self.refused(1, "ledger file 0000/000001.json must be a regular file, not a symlink or a directory")
        shutil.rmtree(self.shard)
        (self.d / "0000").symlink_to(outside / "0000", target_is_directory=True)
        self.refused(0, "ledger shard 0000 must be a directory, not a symlink or a file")

    def test_seq_in_the_file_is_a_strict_integer(self):
        for bad in ("false", "0.0", '"0"'):
            raw = json.dumps(self.c.entries[0]).replace('"seq": 0', f'"seq": {bad}', 1)
            (self.shard / "000000.json").write_text(raw)
            with self.assertRaises(Invalid):
                load(self.d)

    def test_floats_and_nulls_in_a_file_are_invalid(self):
        e = copy.deepcopy(self.c.entries[1])
        for body in ('{"ref": "https://example.org/work", "n": 1.5}', '{"ref": "https://example.org/work", "n": null}'):
            (self.shard / "000001.json").write_text(json.dumps(e).replace(json.dumps(e["body"]), body))
            with self.assertRaisesRegex(Invalid, "not strict JSON"):
                load(self.d)

    def test_entries_are_capped_at_8_kib_and_the_genesis_at_32_kib(self):
        self.assertEqual((ledger.MAX_ENTRY_BYTES, ledger.MAX_GENESIS_BYTES), (8 * 1024, 32 * 1024))
        pad = lambda e, size: json.dumps(e) + " " * (size - len(json.dumps(e)))
        (self.shard / "000000.json").write_text(pad(self.c.entries[0], 32 * 1024))
        (self.shard / "000001.json").write_text(pad(self.c.entries[1], 8 * 1024))
        self.assertEqual(len(load(self.d)), 2)
        (self.shard / "000001.json").write_text(pad(self.c.entries[1], 8 * 1024 + 1))
        with self.assertRaisesRegex(Invalid, "exceeds 8192 bytes"):
            load(self.d)
        (self.shard / "000001.json").write_text(json.dumps(self.c.entries[1]))
        (self.shard / "000000.json").write_text(pad(self.c.entries[0], 32 * 1024 + 1))
        with self.assertRaisesRegex(Invalid, "exceeds 32768 bytes"):
            load(self.d)

    def test_apply_refuses_what_the_loader_refuses(self):
        for bad in (1.5, None, 2 ** 53, "∑"):
            e = copy.deepcopy(self.c.entries)
            e[1]["body"]["kind"] = bad
            with self.assertRaisesRegex(Invalid, "entry 1: not strict JSON"):
                replay(e, verifier=by_key)
        e = copy.deepcopy(self.c.entries)
        e[1]["body"]["ref"] = "https://example.org/" + "a" * 1990
        e[1]["sig"] = e[1]["sig"] + "\n" * 8000
        with self.assertRaisesRegex(Invalid, "exceeds 8192 bytes"):
            replay(e, verifier=lambda *a: True)


# ---------------------------------------------------------------- exact shapes ----

class ExactShapes(unittest.TestCase):
    def test_every_type_refuses_an_unknown_body_field(self):
        c = founded(witnesses=["tyler"])
        invite(c, "alice")
        petition(c, "alice")
        c.add("vouch", "ada", {"candidate": "alice"})
        c.add("ballot_open", "hiram", {"id": "adm", "kind": "admission", "subject": {"candidate": "alice"}})
        c.add("ballot_commit", "ada", {"id": "adm", "commitment": commitment("adm", "ada", "yes", salt_of("ada"))})
        c.add("work", "carol", {"ref": URL, "kind": "essay"})
        st = c.state()
        c.add("witness", "tyler", checkpoint(st))
        c.state()
        for i, e in enumerate(c.entries):
            bad = copy.deepcopy(c.entries[: i + 1])
            bad[i]["body"]["extra"] = "x"
            with self.assertRaisesRegex(Invalid, f"entry {i}: malformed {e['type']} entry: unknown field 'extra'"):
                replay(bad, verifier=by_key)

    def test_depart_has_an_empty_body(self):
        c = founded()
        c.add("depart", "carol", {"note": "bye"})
        c.refused(self, "malformed depart entry: unknown field 'note'")
        c.add("depart", "carol", {})
        self.assertEqual(c.state().members["carol"].status, "departed")

    def test_missing_and_mistyped_fields_are_named(self):
        c = founded()
        c.add("vouch", "hiram", {})
        c.refused(self, "entry 1: malformed vouch entry: missing field 'candidate'")
        c.add("vouch", "hiram", {"candidate": ["alice"]})
        c.refused(self, "malformed vouch entry: field 'candidate' must be a string")
        c.add("ballot_open", "hiram", {"id": "a", "kind": "amendment", "commit_days": True,
                                       "subject": {"path": "CONSTITUTION.md", "new_sha256": "ab" * 32}})
        c.refused(self, "field 'commit_days' must be an integer")
        c.add("ballot_open", "hiram", {"id": "a", "kind": "amendment", "subject": ["CONSTITUTION.md"]})
        c.refused(self, "field 'subject' must be an object")
        c.add("council_call", "hiram", {"beacon_round": "35329012"})
        c.refused(self, "field 'beacon_round' must be an integer")

    def test_genesis_records_are_exact(self):
        for over, pattern in (({"founders": [{"login": "hiram", "key": fake_key("hiram"), "role": "boss"}]}, "unknown field 'role'"),
                              ({"founders": [{"login": "hiram"}]}, "missing field 'key'"),
                              ({"founders": ["hiram"]}, "founder"),
                              ({"witnesses": [{"name": "tyler", "key": fake_key("tyler"), "url": "x"}]}, "unknown field 'url'"),
                              ({"witnesses": {"tyler": fake_key("tyler")}}, "field 'witnesses' must be an array"),
                              ({"motto": "x"}, "unknown field 'motto'")):
            c = Fast()
            c.add("genesis", "hiram", genesis_body(c) | over)
            c.refused(self, pattern)
        c = Fast()
        body = genesis_body(c, FOUNDERS)
        del body["witnesses"]
        c.add("genesis", "hiram", body)
        c.refused(self, "missing field 'witnesses'")

    def test_ballot_subjects_are_exact_per_kind(self):
        c = founded(witnesses=["tyler"])
        initiate(c, "alice")
        opens = lambda subject, kind: c.add("ballot_open", "hiram", {"id": "b", "kind": kind, "subject": subject})
        opens({"member": "alice", "degree": "2"}, "advancement")
        c.refused(self, "'degree' must be an integer")
        opens({"member": "alice", "degree": True}, "advancement")
        c.refused(self, "'degree' must be an integer")
        opens({"member": "alice", "measure": "suspend", "why": "x"}, "sanction")
        c.refused(self, "exactly the keys")
        opens({"member": "alice"}, "sanction")
        c.refused(self, "exactly the keys")
        opens({"action": "remove", "name": "tyler", "key": fake_key("tyler")}, "witness")
        c.refused(self, "a witness subject")
        opens({"action": "add", "name": "node2"}, "witness")
        c.refused(self, "a witness subject")
        opens({"action": "remove", "name": "tyler"}, "witness")
        self.assertIn("b", c.state().ballots)

    def test_work_kind_is_a_short_token(self):
        c = founded()
        for bad in (5, "Essay", "has space", "x" * 33, ""):
            c.add("work", "ada", {"ref": URL, "kind": bad})
            c.refused(self, "work")
        c.add("work", "ada", {"ref": URL, "kind": "essay"})
        c.add("work", "carol", {"ref": URL})
        c.state()

    def test_witness_anchor_and_root_have_strict_shapes(self):
        c = founded(witnesses=["tyler"])
        st = c.state()
        base = checkpoint(st)
        for bad in ("../outside", "/etc/passwd", "a b", "x" * 201, "https://example.org/a", ""):
            c.add("witness", "tyler", base | {"anchor": bad})
            c.refused(self, "anchor")
        c.add("witness", "tyler", base | {"anchor": {"path": "x"}})
        c.refused(self, "field 'anchor' must be a string")
        c.add("witness", "tyler", base | {"root": "zz"})
        c.refused(self, "Merkle root")
        c.add("witness", "tyler", base | {"anchor": "ledger/anchors/000000.root.ots", "root": crypto.merkle_root(st.hashes)})
        c.add("work", "ada", {"ref": URL}, days=1)                # a witness checkpoints again only after a new entry
        c.add("witness", "tyler", checkpoint(c.state()))
        cps = [{"witness": e["actor"]} | e["body"] for e in c.entries if e["type"] == "witness"]
        self.assertEqual((cps[0]["anchor"], "anchor" in cps[1], "root" in cps[1]), ("ledger/anchors/000000.root.ots", False, False))
        self.assertEqual(c.state().history["checkpoints"], absorbed(*cps))


# ---------------------------------------------------------------- time ----

class Time(unittest.TestCase):
    def test_only_real_utc_seconds_between_2020_and_9000(self):
        self.assertEqual(ts("2028-02-29T23:59:59Z"), datetime(2028, 2, 29, 23, 59, 59, tzinfo=timezone.utc))
        self.assertEqual(ts("2020-01-01T00:00:00Z").year, 2020)
        self.assertEqual(ts("9000-12-31T23:59:59Z").year, 9000)
        for bad in ("2027-01-01T24:00:00Z", "2027-01-01T23:60:00Z", "2027-06-30T23:59:60Z", "2027-02-29T00:00:00Z",
                    "2027-02-30T00:00:00Z", "2027-13-01T00:00:00Z", "2027-00-10T00:00:00Z", "2027-01-00T00:00:00Z",
                    "2027-04-31T00:00:00Z", "2100-02-29T00:00:00Z", "2019-12-31T23:59:59Z", "9001-01-01T00:00:00Z",
                    "0001-01-01T00:00:00Z", "2027-01-01T00:00:00Z\n", " 2027-01-01T00:00:00Z", "2027-01-01t00:00:00z",
                    "٢٠٢٧-01-01T00:00:00Z", "２027-01-01T00:00:00Z", "2027-01-01T00:00:00+00:00",
                    "2027-1-1T0:0:0Z", 20270101, None):
            with self.assertRaisesRegex(ValueError, "time must be"):
                ts(bad)
        self.assertEqual(ts("2400-02-29T00:00:00Z").day, 29)        # a leap century

    def test_an_entry_with_hour_24_is_invalid_on_every_runtime(self):
        c = founded()
        c.add("work", "ada", {"ref": URL})
        c.entries[-1]["time"] = "2027-01-01T24:00:00Z"
        c.refused(self, "time must be")

    def test_times_kept_in_state_and_reports_use_the_z_form(self):
        from openmasonry.__main__ import state_report
        c = founded()
        c.add("ballot_open", "hiram", {"id": "am", "kind": "amendment",
                                       "subject": {"path": "docs/NEW.md", "new_sha256": "ab" * 32}})
        rep = state_report(c.state(), c.now)
        self.assertEqual(rep["open_ballots"][0]["commit_until"], "2027-01-08T00:00:00Z")
        self.assertEqual(rep["open_ballots"][0]["reveal_until"], "2027-01-11T06:15:00Z")
        c.vote("am", {f: "yes" for f in FOUNDERS})
        st = c.state()
        self.assertEqual(st.history["amendments"], absorbed({"ballot": "am", "path": "docs/NEW.md", "new_sha256": "ab" * 32,
                                                             "time": st.time.strftime("%Y-%m-%dT%H:%M:%SZ")}))
        self.assertEqual(st.pins["docs/NEW.md"], "ab" * 32)


# ---------------------------------------------------------------- exact durations ----

class Durations(unittest.TestCase):
    """A wait of N days is complete when elapsed >= N days; a thing expires when elapsed > N days."""

    def test_dormancy_starts_strictly_after_365_days(self):
        m = mk("a")
        self.assertFalse(m.dormant(T0 + 365 * DAY))
        self.assertTrue(m.dormant(T0 + 365 * DAY + SEC))

    def test_suspension_is_served_at_exactly_365_days_and_a_seat_lasts_through_its_last_second(self):
        m = mk("a", status="suspended", suspended_until=T0 + 365 * DAY, seat_until=T0 + 100 * DAY)
        self.assertFalse(m.is_active(T0 + 365 * DAY - SEC))
        self.assertTrue(m.is_active(T0 + 365 * DAY))
        st = hand_state(m)
        self.assertEqual(st.seats(T0 + 100 * DAY), ["a"])
        self.assertEqual(st.seats(T0 + 100 * DAY + SEC), [])

    def test_a_petition_is_live_through_day_180_and_lapsed_after(self):
        c = founded()
        invite(c, "alice")
        petition(c, "alice")
        t = c.now
        c.now = t + 180 * DAY
        c.add("vouch", "ada", {"candidate": "alice"})
        c.state()
        c.now = t + 180 * DAY + SEC
        c.add("vouch", "carol", {"candidate": "alice"})
        c.refused(self, "lapsed")

    def test_exam_expiry_and_retry_boundaries(self):
        ex = Exam("a", 2, ("x", "y"), opened=T0)
        self.assertFalse(ex.failed(T0 + 60 * DAY + SEC))         # running out of time is no failure…
        self.assertFalse(ex.timed_out(T0 + 60 * DAY))
        self.assertTrue(ex.timed_out(T0 + 60 * DAY + SEC))       # …it times out, with no penalty
        c = founded()
        initiate(c, "alice")
        rnd = open_exam(c, "alice", 2, days=31)
        opened = c.now
        ex = draw_exam(c, "alice", 2, rnd)
        body = {"candidate": "alice", "degree": 2, "verdict": "fail"}
        c.now = opened + 60 * DAY + SEC
        c.add("exam_report", ex.examiners[0], body)
        c.refused(self, "expired")
        c.now = opened + 60 * DAY
        c.add("exam_report", ex.examiners[0], body)          # half of two examiners failing fails the exam
        self.assertTrue(c.state().exams[("alice", 2)].failed(c.now))
        c.now = opened + 90 * DAY - SEC
        open_exam(c, "alice", 2)
        c.refused(self, "retry only after")
        c.now = opened + 90 * DAY
        open_exam(c, "alice", 2)
        self.assertEqual(c.state().exams[("alice", 2)].opened, c.now)

    def test_rejoin_wait_is_complete_at_exactly_90_days(self):
        c = founded()
        initiate(c, "bob")
        c.add("depart", "bob", {})
        left = c.now
        c.now = left + 90 * DAY - SEC
        invite(c, "bob")
        c.refused(self, "may be invited again once 90 days have passed")
        c.now = left + 90 * DAY
        invite(c, "bob")
        petition(c, "bob")
        self.assertIn("bob", c.state().petitions)

    def fraud(self, elapsed: timedelta):
        now = T0 + elapsed
        fake = mk("fake", 1, sponsors=("s1", "s2"))
        st = hand_state(fake, mk("s1"), mk("s2"), mk("s3"))
        st.ballots["x"] = Ballot("x", "sanction", {"member": "fake", "measure": "expel_for_fraud"},
                                 frozenset({"s1", "s2", "s3"}), now - 2 * DAY, now - DAY, "s1",
                                 reveals={"s1": "yes", "s2": "yes", "s3": "yes"}, frozen={"admitted": ledger.iso(T0)})
        ledger._ballot_close(st, {}, now, 9, "s1", {"id": "x"})
        self.assertEqual((st.ballots["x"].result, st.members["fake"].status), ("passed", "expelled"))
        return st

    def test_the_fraud_window_is_730_days_inclusive(self):
        st = self.fraud(730 * DAY)
        self.assertEqual(st.members["s1"].sponsor_ban_until, T0 + 1460 * DAY)
        self.assertEqual(st.members["fake"].fraud_history, (T0 + 730 * DAY,))
        st = self.fraud(730 * DAY + SEC)
        self.assertIsNone(st.members["s1"].sponsor_ban_until)

    def test_the_sponsor_budget_year_is_365_days_inclusive(self):
        admitted = [mk(f"m{i}", 1, sponsors=("hiram",)) for i in range(4)]
        st = hand_state(mk("hiram"), *admitted)
        st.petitions["cand"] = {"key": fake_key("cand"), "vouches": [], "time": T0 + 365 * DAY, "github_id": 7}
        with self.assertRaisesRegex(Invalid, "budget"):
            ledger._vouch(st, {}, T0 + 365 * DAY, 9, "hiram", {"candidate": "cand"})
        ledger._vouch(st, {}, T0 + 365 * DAY + SEC, 9, "hiram", {"candidate": "cand"})
        self.assertEqual(st.petitions["cand"]["vouches"], ["hiram"])


# ---------------------------------------------------------------- names and strings ----

class Strings(unittest.TestCase):
    def test_the_fraternity_name_is_1_to_120_printable_ascii(self):
        for bad in ("", "x" * 121, "OpenMasonry — Lodge", "tab\there", "line\nbreak", "Привет", "del\x7f"):
            c = Fast()
            c.add("genesis", "hiram", genesis_body(c, FOUNDERS, name=bad))
            c.refused(self, "name: 1..120 printable ASCII|not strict JSON")
        c = founded(name="x" * 120)
        self.assertEqual(c.state().name, "x" * 120)
        self.assertEqual(founded(name="Open Lodge No. 1 ~ {test}").state().name, "Open Lodge No. 1 ~ {test}")

    def test_the_salt_is_32_to_64_lowercase_hex(self):
        c = founded()
        c.add("ballot_open", "hiram", {"id": "am", "kind": "amendment",
                                       "subject": {"path": "docs/NEW.md", "new_sha256": "ab" * 32}})
        opened = c.now
        for salt in ("salt-0123456789-hiram", "a" * 31, "A" * 32, "a" * 65, "g" * 32, "a" * 32 + "\n"):
            c.now = opened
            c.add("ballot_commit", "ada", {"id": "am", "commitment": commitment("am", "ada", "yes", salt)})
            c.add("ballot_reveal", "ada", {"id": "am", "vote": "yes", "salt": salt}, days=7.5)
            c.refused(self, "salt")
            c.entries.pop()
        import secrets
        self.assertRegex(secrets.token_hex(16), ledger.SALT_RE)      # what `om vote` generates
        for salt in ("a" * 32, "0123456789abcdef" * 4):
            c.now = opened
            c.entries = c.entries[:2]
            c.add("ballot_commit", "ada", {"id": "am", "commitment": commitment("am", "ada", "yes", salt)})
            c.add("ballot_reveal", "ada", {"id": "am", "vote": "yes", "salt": salt}, days=7.5)
            self.assertEqual(c.state().ballots["am"].reveals, {"ada": "yes"})

    def test_urls_have_no_apostrophe_and_patterns_are_ascii_only(self):
        c = founded()
        c.add("work", "ada", {"ref": "https://example.org/it's"})
        c.refused(self, "URL")
        self.assertIsNone(ledger.URL_RE.fullmatch("https://example.org/日本"))
        for pattern in (ledger.LOGIN_RE, ledger.BALLOT_ID_RE, ledger.PATH_RE, ledger.HEX64, ledger.SALT_RE,
                        ledger.KEY_RE, ledger.TIME_RE, ledger.URL_RE, ledger.NAME_RE, ledger.ANCHOR_RE,
                        ledger.WORK_KIND_RE):
            self.assertNotRegex(pattern.pattern, r"\\[dwsDWS]", pattern.pattern)
            self.assertIsNone(pattern.fullmatch("٣"))
            self.assertIsNone(pattern.fullmatch("ａ"))
        self.assertFalse(ledger.valid_login("٣abc"))
        self.assertFalse(ledger.valid_login("hiram\n"))


# ---------------------------------------------------------------- canonical JSON ----

class Canonical(unittest.TestCase):
    def test_the_spec_vector(self):
        e = {"seq": 1, "prev": "0" * 64, "time": "2027-01-01T00:00:00Z", "type": "work", "actor": "hiram",
             "body": {"ref": "https://example.org/w", "kind": "essay"}, "sig": "x"}
        self.assertEqual(crypto.canonical(e), (
            b'{"actor":"hiram","body":{"kind":"essay","ref":"https://example.org/w"},"prev":"' + b"0" * 64
            + b'","seq":1,"sig":"x","time":"2027-01-01T00:00:00Z","type":"work"}'))
        self.assertEqual(entry_hash(e), "d42607b1398ce62fdc6a42bd65d8ea4dc2e45044f18b3d21d3754f54aa4055b5")

    def test_keys_sort_by_code_point_and_only_three_escapes_occur(self):
        self.assertEqual(crypto.canonical({"b": 1, "B": 2, "a": [True, False, -3], "_": "q\"\\\n"}),
                         b'{"B":2,"_":"q\\"\\\\\\n","a":[true,false,-3],"b":1}')

    def test_values_outside_the_protocol_cannot_be_canonicalized(self):
        for bad in ({"a": 1.0}, {"a": None}, {"a": float("inf")}, {"a": 2 ** 53}, {1: "a"}, {"a": (1,)}, {"a": {2, 3}}):
            with self.assertRaises((TypeError, ValueError)):
                crypto.canonical(bad)


# ---------------------------------------------------------------- robustness ----

class Robustness(unittest.TestCase):
    def test_any_exception_in_a_handler_is_invalid(self):
        c = founded()
        c.add("work", "ada", {"ref": URL})
        for exc in (KeyError("k"), TypeError("t"), OverflowError("o"), RecursionError("r"), OSError("io"),
                    ZeroDivisionError("z"), MemoryError()):
            def boom(*a, exc=exc):
                raise exc
            with mock.patch.dict(ledger.HANDLERS, {"work": boom}):
                with self.assertRaisesRegex(Invalid, "entry 1: malformed work entry"):
                    c.state()

    def test_an_exception_in_the_verifier_is_invalid_too(self):
        c = founded()
        with self.assertRaisesRegex(Invalid, "entry 0"):
            replay(c.entries, verifier=lambda *a: 1 // 0)

    def test_a_refused_entry_changes_neither_the_state_nor_the_entry(self):
        c = founded()
        c.add("ballot_open", "hiram", {"id": "am", "kind": "amendment",
                                       "subject": {"path": "canon/degrees.toml", "new_sha256": "ee" * 32}})
        st = replay(c.entries[:-1], verifier=by_key)
        before, entry = copy.deepcopy(st), copy.deepcopy(c.entries[-1])
        with self.assertRaisesRegex(Invalid, "not archived"):
            apply(st, c.entries[-1], verifier=by_key)
        self.assertEqual(st, before)
        self.assertEqual(c.entries[-1], entry)
        for body in ({"id": "am2", "kind": "amendment", "subject": {"path": "ledger/entries/000000.json", "new_sha256": "ab" * 32}},
                     {"id": "s", "kind": "sanction", "subject": {"member": "ada", "measure": "admonish"}}):
            e = {**c.entries[-1], "type": "ballot_open", "body": body, "sig": c.key("ada"), "actor": "ada"}
            with self.assertRaises(Invalid):
                apply(st, e, verifier=by_key)
            self.assertEqual(st, before)


# ---------------------------------------------------------------- beacon rounds ----

class Rounds(unittest.TestCase):
    def test_round_arithmetic_is_integer_and_matches_the_definition(self):
        t = ts("2027-01-01T00:00:00Z")
        self.assertEqual((drand_round(t), type(drand_round(t))), (35319412, int))
        self.assertEqual(drand_time(35329012), ts("2027-01-01T08:00:00Z"))
        for s in (0, 1, 2, 3, 86399):
            u = t + timedelta(seconds=s)
            r = drand_round(u)
            self.assertTrue(drand_time(r) <= u < drand_time(r + 1))
        import calendar
        last = calendar.timegm((9000, 12, 31, 23, 59, 59))
        self.assertEqual(drand_round(ts("9000-12-31T23:59:59Z")), (last - 1692803367) // 3 + 1)
        self.assertEqual(ledger.unix(ts("9000-12-31T23:59:59Z")), last)

    def test_rounds_are_positive_integers(self):
        c = Fast()
        c.now = ts("2021-06-01T00:00:00Z")                         # before the drand genesis: no round exists
        c.add("genesis", "hiram", genesis_body(c, FOUNDERS))
        c.add("council_call", "hiram", {"beacon_round": drand_round(c.now) + BEACON_DELAY_ROUNDS})
        c.refused(self, "beacon_round")
        c = founded()
        rnd = drand_round(c.now) + BEACON_DELAY_ROUNDS
        for bad in (float(rnd), True, str(rnd)):
            c.add("council_call", "hiram", {"beacon_round": bad})
            c.refused(self, "not strict JSON|must be an integer")


# ---------------------------------------------------------------- the Declaration lives in the state ----

class Declaration(unittest.TestCase):
    def test_genesis_must_record_the_declaration_digest(self):
        c = Fast()
        body = genesis_body(c, FOUNDERS)
        del body["declaration_sha256"]
        c.add("genesis", "hiram", body)
        c.refused(self, "missing field 'declaration_sha256'")
        c.add("genesis", "hiram", genesis_body(c, FOUNDERS, declaration_sha256="xyz"))
        c.refused(self, "Declaration")

    def test_petitions_are_compared_with_the_state_not_with_the_verifiers_file(self):
        other = "ab" * 32
        c = founded(declaration_sha256=other)
        self.assertEqual(c.state().declaration_sha256, other)
        invite(c, "alice")
        c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": DECL})
        c.refused(self, "sha256 of the Declaration")
        c.add("petition", "alice", {"key": c.key("alice"), "declaration_sha256": other})
        self.assertIn("alice", c.state().petitions)
        c2 = founded()
        invite(c2, "alice")
        petition(c2, "alice")
        with mock.patch.object(canon, "declaration_digest", side_effect=AssertionError("replay read the tree")):
            self.assertIn("alice", c2.state().petitions)

    def test_the_tree_gate_compares_the_declaration_with_the_genesis(self):
        self.assertEqual(govern.check_tree(founded().state()), [])
        problems = govern.check_tree(founded(declaration_sha256="ab" * 32).state())
        self.assertEqual(len(problems), 1)
        self.assertIn("Declaration", problems[0])

    def test_om_genesis_fills_it_with_an_ascii_name(self):
        tmp = tmpdir(self)
        home = tmp / "home"
        home.mkdir()
        (home / ".test-mode").write_text("tests only")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(home / "key")], check=True)
        r = subprocess.run([sys.executable, "-m", "openmasonry", "genesis", "--ledger", str(tmp / "led"), "--json",
                            "--github-id", "7", "--time", "2027-01-01T00:00:00Z"], capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": str(REPO / "src"), "OM_LOGIN": "hiram", "OM_HOME": str(home),
                                "OM_KEY": str(home / "key"), "OM_CONFIRM": "insecure-auto-approve-for-tests"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        body = json.loads(r.stdout)["entry"]["body"]
        self.assertEqual(body["declaration_sha256"], canon.declaration_digest())
        self.assertTrue(body["name"].isascii())
        self.assertEqual([sorted(f) for f in body["founders"]], [["github_id", "key", "login"]])
        self.assertEqual(body["founders"][0]["github_id"], 7)


# ---------------------------------------------------------------- the degree table ----

class DegreeTable(unittest.TestCase):
    RAW = (canon.CANON / "degrees.toml").read_bytes()

    def variant(self, old: str, new: str, count: int = 1) -> bytes:
        text = self.RAW.decode()
        self.assertIn(old, text)
        return text.replace(old, new, count).encode()

    def test_the_current_table_is_valid(self):
        table = canon.parse_degrees(self.RAW)
        self.assertEqual(sorted(table), list(range(1, 34)))
        self.assertEqual((table[2].wait_days, table[2].examiners), (30, 2))

    def test_malformed_tables_are_refused(self):
        bad = {
            "duplicate n": self.variant("n = 2\n", "n = 3\n"),
            "missing degree": self.RAW[: self.RAW.rindex(b"[[degree]]")],
            "extra field": self.variant("n = 2\n", "n = 2\nbonus = 1\n"),
            "missing field": self.variant('wait_days = 30\n', "", 1),
            "string for an integer": self.variant("wait_days = 30\n", 'wait_days = "30"\n'),
            "boolean for an integer": self.variant("wait_days = 30\n", "wait_days = true\n"),
            "float for an integer": self.variant("wait_days = 30\n", "wait_days = 30.0\n"),
            "negative wait": self.variant("wait_days = 30\n", "wait_days = -1\n"),
            "huge wait": self.variant("wait_days = 30\n", "wait_days = 99999\n"),
            "no examiners for a degree with an exam": self.variant("examiners = 2\n", "examiners = 0\n"),
            "too many examiners": self.variant("examiners = 2\n", "examiners = 34\n"),
            "integer for a string": self.variant('house = "craft"', "house = 7"),
            "not toml": b"[[degree]\n",
            "not utf-8": b"\xff\xfe",
            "no degrees": b'title = "x"\n',
            "a top-level key": b"note = 1\n" + self.RAW,
            "a nested value in a top-level key": b"note = " + b"[" * 300 + b"]" * 300 + b"\n" + self.RAW,
            "an integer of 5000 digits": b"note = " + b"9" * 5000 + b"\n" + self.RAW,
            "another table": self.RAW + b'[[extra]]\nx = 1\n',
            "a table that is not an array": self.RAW + b'[meta]\nx = 1\n',
            "an escape in a string": self.variant('title = "', 'title = "\\u0041'),
            "a single-quoted string": self.variant('house = "craft"', "house = 'craft'"),
            "a carriage return": self.RAW.replace(b"\n", b"\r\n", 1),
            "no final line feed": self.RAW.rstrip(b"\n"),
            "a byte order mark": b"\xef\xbb\xbf" + self.RAW,
            "an inline comment": self.variant("n = 2\n", "n = 2 # two\n"),
            "a leading zero": self.variant("wait_days = 30\n", "wait_days = 030\n"),
            "a signed integer": self.variant("wait_days = 30\n", "wait_days = +30\n"),
            "a key twice": self.variant("n = 2\n", "n = 2\nn = 2\n"),
            "a malformed house": self.variant('range = [1, 3]', 'range = [1, 3, 5]'),
            "a house field missing": self.variant('purpose = "Self-knowledge and the tools of the work."\n', ""),
            "larger than the cap": self.RAW + b"#" + b"x" * canon.CANON_MAX_BYTES + b"\n",
            "34 degrees": self.RAW + self.RAW[self.RAW.rindex(b"[[degree]]"):].replace(b"n = 33", b"n = 34"),
        }
        for name, raw in bad.items():
            with self.assertRaises(canon.MalformedCanon, msg=name):
                canon.parse_degrees(raw)

    def archive(self, raw: bytes) -> str:
        root = tmpdir(self)
        (root / "history").mkdir()
        digest = hashlib.sha256(raw).hexdigest()
        (root / "history" / f"{digest}.toml").write_bytes(raw)
        shutil.copy(canon.CANON / "degrees.toml", root / "degrees.toml")
        patch = mock.patch.object(canon, "CANON", root)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(canon._degrees_for.cache_clear)
        canon._degrees_for.cache_clear()
        return digest

    def test_a_malformed_archived_canon_is_invalid_not_a_crash(self):
        digest = self.archive(self.variant("n = 2\n", "n = 2\nbonus = 1\n"))
        self.assertFalse(canon.canon_archived(digest))
        self.assertEqual(canon.canon_status(digest), "malformed")
        c = Fast()
        c.add("genesis", "hiram", genesis_body(c, FOUNDERS, pins={"canon/degrees.toml": digest}))
        c.refused(self, "entry 0: .*malformed")

    def test_the_strict_form_reads_the_table_as_toml_does(self):
        import tomllib
        self.assertEqual(canon._parse_tables(self.RAW), tomllib.loads(self.RAW.decode()))
        self.assertEqual(sorted(canon.houses()), ["consistory", "council", "craft", "kadosh", "perfection", "rose"])

    def test_an_amendment_to_a_malformed_canon_is_never_opened(self):
        digest = self.archive(self.variant("examiners = 2\n", "examiners = 0\n"))
        c = founded()
        c.add("ballot_open", "hiram", {"id": "am", "kind": "amendment",
                                       "subject": {"path": "canon/degrees.toml", "new_sha256": digest}})
        c.refused(self, "is malformed \\(33 degrees with exact fields\\): it can never be ratified")
        self.assertEqual(c.state().pins["canon/degrees.toml"], canon_digest())


# ---------------------------------------------------------------- one name, one key, one role ----

class OneNameOneKey(unittest.TestCase):
    def witness_ballot(self, c, name, key_of=None, bid="w", by="ada"):
        c.add("ballot_open", by, {"id": bid, "kind": "witness", "subject": witness_subject(c, name, key_of)})

    def test_an_open_witness_ballot_reserves_its_name_and_key(self):
        c = founded()
        self.witness_ballot(c, "Node2")
        invite(c, "node2")
        c.refused(self, "open witness ballot")
        invite(c, "eve")
        petition(c, "eve", key_of="Node2")
        c.refused(self, "already used by Node2")
        self.witness_ballot(c, "node3", key_of="Node2", bid="w3")
        c.refused(self, "already used by Node2")
        self.witness_ballot(c, "NODE2", key_of="other", bid="w4")
        c.refused(self, "cannot equal")

    def test_a_live_petition_reserves_its_name_and_key_against_witness_ballots(self):
        c = founded()
        invite(c, "Alice")
        petition(c, "Alice")
        self.witness_ballot(c, "alice")
        c.refused(self, "cannot equal")
        self.witness_ballot(c, "node2", key_of="Alice")
        c.refused(self, "already used by Alice")
        c.now += 180 * DAY + SEC                                   # lapsed: neither the name nor the key is held
        self.witness_ballot(c, "alice", bid="w1")
        self.witness_ballot(c, "node2", key_of="Alice", bid="w2")
        c.state()

    def test_members_of_any_status_keep_their_name_and_key(self):
        c = founded()
        initiate(c, "bob")
        c.add("depart", "bob", {})
        self.witness_ballot(c, "Bob")
        c.refused(self, "cannot equal")
        self.witness_ballot(c, "node2", key_of="bob")
        c.refused(self, "already used by bob")
        invite(c, "eve")
        petition(c, "eve", key_of="bob")
        c.refused(self, "already used by bob")

    def test_a_collision_found_at_close_fails_the_ballot(self):
        now = T0 + 20 * DAY
        voters = frozenset(FOUNDERS)
        yes = {f: "yes" for f in FOUNDERS}
        for clash in ("name", "key"):
            st = hand_state(*(mk(f) for f in FOUNDERS))
            st.ballots["w"] = Ballot("w", "witness", {"action": "add", "name": "node2", "key": fake_key("node2")},
                                     voters, now - 2 * DAY, now - DAY, "ada", reveals=dict(yes))
            if clash == "name":
                st.members["Node2"] = mk("Node2", 1)
            else:
                st.witnesses["old"] = fake_key("node2")
            ledger._ballot_close(st, {}, now, 9, "ada", {"id": "w"})
            self.assertEqual(st.ballots["w"].result, "failed", clash)
            self.assertNotIn("node2", st.witnesses)
            st = hand_state(*(mk(f) for f in FOUNDERS))
            st.petitions["alice"] = {"key": fake_key("alice"), "vouches": ["hiram", "ada"], "time": now - 5 * DAY,
                                     "github_id": 7}
            st.ballots["a"] = Ballot("a", "admission", {"candidate": "alice"}, voters, now - 2 * DAY, now - DAY, "ada",
                                     reveals=dict(yes),
                                     frozen={"key": fake_key("alice"), "vouches": ["hiram", "ada"], "github_id": 7})
            if clash == "name":
                st.witnesses["Alice"] = fake_key("w")
            else:
                st.witnesses["w"] = fake_key("alice")
            ledger._ballot_close(st, {}, now, 9, "ada", {"id": "a"})
            self.assertEqual(st.ballots["a"].result, "failed", clash)
            self.assertNotIn("alice", st.members)
            self.assertNotIn("alice", st.petitions)

    def test_activity_goes_to_the_member_who_signed(self):
        c = founded(witnesses=["tyler"])
        initiate(c, "bob")
        c.add("depart", "bob", {})
        before = list(c.state().members["bob"].activity)
        c.now += 90 * DAY
        invite(c, "bob")
        petition(c, "bob")                                         # signed with the petition key, not as a member
        st = c.state()
        self.assertEqual(st.members["bob"].activity, before)
        c.add("witness", "tyler", checkpoint(st))
        self.assertEqual({l: len(m.activity) for l, m in c.state().members.items()},
                         {l: len(m.activity) for l, m in st.members.items()})

    def test_a_witness_cannot_sign_as_a_member_nor_a_member_as_a_witness(self):
        c = founded(witnesses=["tyler"])
        c.add("work", "tyler", {"ref": URL})
        c.refused(self, "tyler is not an active member")
        st = c.state()
        c.add("witness", "ada", checkpoint(st))
        c.refused(self, "unknown witness")


class LapsedPetitions(unittest.TestCase):
    def test_a_lapsed_petition_blocks_neither_its_login_nor_its_key(self):
        c = founded()
        invite(c, "Alice")
        petition(c, "Alice")
        c.now += 180 * DAY + SEC
        invite(c, "alice")
        petition(c, "alice", key_of="Alice")                       # the same person, the other spelling, the same key
        st = c.state()
        self.assertEqual(list(st.petitions), ["alice"])
        invite(c, "Alice", by="ada")
        c.refused(self, "collides with the pending petition of 'alice'")

    def test_a_lapsed_petition_frees_its_login_and_never_its_key(self):
        c = founded()
        invite(c, "alice")
        petition(c, "alice")
        invite(c, "bob")
        petition(c, "bob", key_of="alice")
        c.refused(self, "already used by alice")
        c.now += 180 * DAY + SEC
        invite(c, "bob")                                           # the first invitation lapsed long ago
        petition(c, "bob", key_of="alice")
        c.refused(self, "this key was used in this ledger before")   # a key once registered is never registered again
        petition(c, "bob")
        self.assertIsNone(c.state().key_owner(c.key("alice"), c.now))


# ---------------------------------------------------------------- re-admission ----

class Readmission(unittest.TestCase):
    def test_a_returning_member_starts_clean_and_can_be_examined_again(self):
        c = founded()
        initiate(c, "ivy")
        c.exam("ivy", 2, days=31)
        self.assertTrue(c.state().exams[("ivy", 2)].passed())
        c.add("depart", "ivy", {})
        c.now += 90 * DAY
        invite(c, "ivy")
        petition(c, "ivy")
        c.add("vouch", "carol", {"candidate": "ivy"})
        c.add("ballot_open", "hiram", {"id": "re", "kind": "admission", "subject": {"candidate": "ivy"}})
        c.vote("re", {f: "yes" for f in FOUNDERS})
        st = c.state()
        self.assertEqual((st.members["ivy"].degree, st.members["ivy"].sponsors), (1, ("hiram", "carol")))
        self.assertNotIn(("ivy", 2), st.exams)
        c.exam("ivy", 2, days=31)
        c.add("ballot_open", "carol", {"id": "adv", "kind": "advancement", "subject": {"member": "ivy", "degree": 2}})
        c.vote("adv", {f: "yes" for f in FOUNDERS})
        self.assertEqual(c.state().members["ivy"].degree, 2)

    def admission(self, old: Member):
        now = T0 + 500 * DAY
        old.github_id = 7                        # the same GitHub account returns: what follows the person is kept
        st = hand_state(old, *(mk(f) for f in FOUNDERS))
        st.exams[(old.login, 2)] = Exam(old.login, 2, ("hiram", "ada"), opened=T0, reports={"hiram": "pass", "ada": "pass"})
        st.petitions[old.login] = {"key": fake_key("new"), "vouches": ["hiram", "ada"], "time": now - 20 * DAY,
                                   "github_id": 7}
        st.ballots["re"] = Ballot("re", "admission", {"candidate": old.login}, frozenset(FOUNDERS), now - 2 * DAY,
                                  now - DAY, "hiram", reveals={f: "yes" for f in FOUNDERS},
                                  frozen={"key": fake_key("new"), "vouches": ["hiram", "ada"], "github_id": 7})
        ledger._ballot_close(st, {}, now, 9, "hiram", {"id": "re"})
        return st, now

    def test_the_sponsor_ban_and_the_fraud_history_survive(self):
        ban = T0 + 900 * DAY
        old = mk("vet", 5, status="expelled", status_since=T0 + 100 * DAY, sponsor_ban_until=ban,
                 fraud_history=(T0 + 100 * DAY,), past_seats=1, founder=True)
        st, now = self.admission(old)
        m = st.members["vet"]
        self.assertEqual((st.ballots["re"].result, m.degree, m.status, m.since), ("passed", 1, "active", {1: now}))
        self.assertEqual((m.sponsor_ban_until, m.fraud_history, m.past_seats, m.founder), (ban, (T0 + 100 * DAY,), 1, True))
        self.assertEqual(st.exams, {})
        with self.assertRaisesRegex(Invalid, "sponsorship suspended"):
            st.petitions["x"] = {"key": fake_key("x"), "vouches": [], "time": now, "github_id": 8}
            m.degree = 3
            ledger._vouch(st, {}, now, 10, "vet", {"candidate": "x"})

    def test_a_login_reinstated_while_its_admission_ballot_was_open_fails_the_ballot(self):
        old = mk("vet", 5, status="active", status_since=T0 + 490 * DAY)      # reinstated by a sanction ballot
        st, now = self.admission(old)
        self.assertEqual(st.ballots["re"].result, "failed")
        self.assertIs(st.members["vet"], old)
        self.assertEqual((old.degree, old.key), (5, fake_key("vet")))
        self.assertNotIn("vet", st.petitions)
        self.assertIn(("vet", 2), st.exams)

    def test_a_ballot_opened_on_an_earlier_membership_never_touches_the_new_one(self):
        now = T0 + 500 * DAY
        new = mk("vet", 1, t=T0 + 400 * DAY)
        st = hand_state(new, *(mk(f) for f in FOUNDERS))
        st.exams[("vet", 2)] = Exam("vet", 2, ("hiram", "ada"), opened=now - 30 * DAY, reports={"hiram": "pass", "ada": "pass"})
        yes = {f: "yes" for f in FOUNDERS}
        old_membership = {"admitted": ledger.iso(T0)}
        st.ballots["adv"] = Ballot("adv", "advancement", {"member": "vet", "degree": 2}, frozenset(FOUNDERS),
                                   now - 2 * DAY, now - DAY, "hiram", reveals=dict(yes), frozen=dict(old_membership))
        st.ballots["exp"] = Ballot("exp", "sanction", {"member": "vet", "measure": "expel"}, frozenset(FOUNDERS),
                                   now - 2 * DAY, now - DAY, "hiram", reveals=dict(yes), frozen=dict(old_membership))
        for bid in ("adv", "exp"):
            ledger._ballot_close(st, {}, now, 9, "hiram", {"id": bid})
            self.assertEqual(st.ballots[bid].result, "failed")
        self.assertEqual((new.degree, new.status), (1, "active"))
        self.assertFalse(st.exams[("vet", 2)].lapsed or st.exams[("vet", 2)].ballot_failed)


# ---------------------------------------------------------------- examinations ----

class Exams(unittest.TestCase):
    def test_an_exam_with_no_examiners_never_passes(self):
        self.assertFalse(Exam("a", 2, (), opened=T0).passed())
        self.assertFalse(Exam("a", 2, None, opened=T0).passed())
        self.assertFalse(Exam("a", 2, ("x",), opened=T0, reports={"x": "pass"}, lapsed=True).passed())
        self.assertTrue(Exam("a", 2, ("x",), opened=T0, reports={"x": "pass"}).passed())

    def lapse(self):
        c = founded()
        initiate(c, "dave")
        rnd = open_exam(c, "dave", 2, days=31)
        ex = draw_exam(c, "dave", 2, rnd)                          # pool of three, two examiners
        a, b = ex.examiners
        third = next(x for x in ex.ranking if x not in ex.examiners)
        body = {"candidate": "dave", "degree": 2}
        c.add("exam_recuse", a, body)
        self.assertEqual(c.state().exams[("dave", 2)].examiners, (b, third))
        c.add("exam_recuse", third, body)                          # nobody is left in the lot's order
        return c, b

    def test_a_recusal_without_replacement_lapses_the_exam_without_penalty(self):
        c, b = self.lapse()
        ex = c.state().exams[("dave", 2)]
        self.assertTrue(ex.lapsed)
        self.assertFalse(ex.passed() or ex.failed(c.now + 100 * DAY))
        c.add("exam_report", b, {"candidate": "dave", "degree": 2, "verdict": "pass"})
        c.refused(self, "lapsed")
        c.add("exam_recuse", b, {"candidate": "dave", "degree": 2})
        c.refused(self, "no drawn exam")
        rnd = open_exam(c, "dave", 2)                              # at once: no 90-day wait
        ex = draw_exam(c, "dave", 2, rnd)
        self.assertEqual((ex.lapsed, len(ex.examiners)), (False, 2))

    def test_a_decided_exam_cannot_be_undone_by_a_recusal(self):
        st = hand_state(mk("dave", 1), *(mk(f) for f in FOUNDERS))
        body = {"candidate": "dave", "degree": 2}
        st.exams[("dave", 2)] = Exam("dave", 2, ("hiram", "ada", "carol"), opened=T0, k=3, ranking=("hiram", "ada", "carol"),
                                     reports={"hiram": "pass", "ada": "pass"})
        with self.assertRaisesRegex(Invalid, "already decided"):        # passed: carol's recusal would lapse it
            ledger._exam_recuse(st, {}, T0 + DAY, 9, "carol", body)
        st.exams[("dave", 2)].reports = {"hiram": "pass"}
        ledger._exam_recuse(st, {}, T0 + DAY, 9, "carol", body)
        self.assertTrue(st.exams[("dave", 2)].lapsed)

    def test_a_draw_after_the_exam_expired_or_its_lot_lapsed_is_refused(self):
        c = founded()
        initiate(c, "dave")
        rnd = open_exam(c, "dave", 2, days=31)
        opened = c.now
        c.now = opened + 60 * DAY + SEC
        c.add("exam_draw", "dave", {"candidate": "dave", "degree": 2, "beacon": f"{rnd:064x}"})
        c.refused(self, "expired")
        self.assertEqual(ledger.due_actions(c.state(), c.now), [])
        c.now = drand_time(rnd) + 7 * DAY + SEC                  # the lot is drawn within 7 days of its round
        c.add("exam_draw", "dave", {"candidate": "dave", "degree": 2, "beacon": f"{rnd:064x}"})
        c.refused(self, "the lot of this exam was not drawn within 7 days of its beacon round")
        self.assertEqual(ledger.due_actions(c.state(), c.now), [])
        c.now = drand_time(rnd) + 7 * DAY
        self.assertEqual([t for t, _ in ledger.due_actions(c.state(), c.now)], ["exam_draw"])
        draw_exam(c, "dave", 2, rnd, days=0)

    def advancement(self, **member):
        now = T0 + 200 * DAY
        erin = mk("erin", 1, **member)
        st = hand_state(erin, *(mk(f) for f in FOUNDERS))
        st.exams[("erin", 2)] = Exam("erin", 2, ("hiram", "ada"), opened=now - 20 * DAY, consumed=True,
                                     reports={"hiram": "pass", "ada": "pass"}, pool=tuple(FOUNDERS), k=2)
        st.ballots["adv"] = Ballot("adv", "advancement", {"member": "erin", "degree": 2}, frozenset(FOUNDERS),
                                   now - 2 * DAY, now - DAY, "hiram", frozen={"admitted": ledger.iso(T0)})
        return st, now

    def reopen(self, st, now):
        rnd = drand_round(now) + BEACON_DELAY_ROUNDS
        ledger._exam_open(st, {}, now, 10, "erin", {"candidate": "erin", "degree": 2, "work_ref": URL, "beacon_round": rnd})
        return st.exams[("erin", 2)]

    def test_no_dead_end_when_the_member_was_not_active_at_the_close(self):
        for status in ("expelled", "suspended", "departed"):
            st, now = self.advancement(status=status, status_since=T0 + 190 * DAY, suspended_until=T0 + 555 * DAY)
            st.ballots["adv"].reveals = {f: "yes" for f in FOUNDERS}
            ledger._ballot_close(st, {}, now, 9, "hiram", {"id": "adv"})
            ex = st.exams[("erin", 2)]
            self.assertEqual((st.ballots["adv"].result, st.members["erin"].degree), ("failed", 1), status)
            self.assertTrue(ex.lapsed and ex.consumed and not ex.ballot_failed and not ex.failed(now + 999 * DAY))
            st.members["erin"].status = "active"                   # reinstated later
            with self.assertRaisesRegex(Invalid, "examination not passed"):
                ledger._ballot_open(st, {}, now, 10, "hiram", {"id": "adv2", "kind": "advancement",
                                                               "subject": {"member": "erin", "degree": 2}})
            new = self.reopen(st, now)                              # at once, with no retry wait
            self.assertEqual((new.opened, new.lapsed, new.consumed), (now, False, False))

    def test_a_ballot_lost_on_the_votes_fails_the_exam_whatever_the_status(self):
        st, now = self.advancement(status="expelled", status_since=T0 + 190 * DAY)
        st.ballots["adv"].reveals = {f: "no" for f in FOUNDERS}
        ledger._ballot_close(st, {}, now, 9, "hiram", {"id": "adv"})
        ex = st.exams[("erin", 2)]
        self.assertTrue(ex.ballot_failed and ex.failed(now) and not ex.lapsed)
        st.members["erin"].status = "active"
        with self.assertRaisesRegex(Invalid, "retry only after"):
            self.reopen(st, now)
        self.assertEqual(self.reopen(st, ex.opened + 90 * DAY).opened, ex.opened + 90 * DAY)

    def test_a_changed_degree_closes_the_ballot_as_failed(self):
        st, now = self.advancement()
        st.ballots["adv"].reveals = {f: "yes" for f in FOUNDERS}
        st.members["erin"].degree = 2                              # however it happened, the subject no longer fits
        st.members["erin"].since[2] = now - DAY
        ledger._ballot_close(st, {}, now, 9, "hiram", {"id": "adv"})
        self.assertEqual((st.ballots["adv"].result, st.members["erin"].degree), ("failed", 2))


# ---------------------------------------------------------------- sanctions and departure ----

class Sanctions(unittest.TestCase):
    def opens(self, measure, **member):
        now = T0 + 100 * DAY
        st = hand_state(mk("x", 1, **member), *(mk(f, activity=[now]) for f in FOUNDERS))
        ledger._ballot_open(st, {}, now, 9, "hiram", {"id": "s", "kind": "sanction",
                                                      "subject": {"member": "x", "measure": measure}})
        return st

    def test_each_measure_has_its_precondition(self):
        soon, served = T0 + 300 * DAY, T0 + 50 * DAY
        states = {"active": {}, "suspended": {"status": "suspended", "suspended_until": soon},
                  "served": {"status": "suspended", "suspended_until": served},
                  "expelled": {"status": "expelled", "status_since": T0}, "departed": {"status": "departed", "status_since": T0}}
        lawful = {"admonish": {"active", "suspended", "served", "expelled"}, "suspend": {"active", "served"},
                  "expel": {"active", "suspended", "served"}, "expel_for_fraud": {"active", "suspended", "served"},
                  "reinstate": {"suspended", "expelled"}}
        for measure, ok in lawful.items():
            for name, member in states.items():
                if name in ok:
                    self.assertIn("s", self.opens(measure, **member).ballots, (measure, name))
                else:
                    with self.assertRaises(Invalid, msg=(measure, name)):
                        self.opens(measure, **member)

    def test_a_repeated_expulsion_does_not_restart_the_clock(self):
        c = founded()
        initiate(c, "mal")
        c.add("ballot_open", "hiram", {"id": "x1", "kind": "sanction", "subject": {"member": "mal", "measure": "expel"}})
        c.vote("x1", {f: "yes" for f in FOUNDERS})
        since = c.state().members["mal"].status_since
        c.add("ballot_open", "hiram", {"id": "x2", "kind": "sanction", "subject": {"member": "mal", "measure": "expel"}}, days=300)
        c.refused(self, "expel applies only to")
        c.now = since + 365 * DAY
        invite(c, "mal")
        petition(c, "mal")
        self.assertIn("mal", c.state().petitions)

    def test_the_precondition_is_checked_again_at_the_close(self):
        st = self.opens("suspend")
        b = st.ballots["s"]
        b.reveals = {f: "yes" for f in FOUNDERS}
        st.members["x"].status, st.members["x"].status_since = "departed", b.commit_until
        ledger._ballot_close(st, {}, b.reveal_until + SEC, 10, "hiram", {"id": "s"})
        self.assertEqual((b.result, st.members["x"].status), ("failed", "departed"))

    def test_reinstate_returns_a_suspended_or_expelled_member(self):
        for member in ({"status": "suspended", "suspended_until": T0 + 300 * DAY}, {"status": "expelled", "status_since": T0}):
            st = self.opens("reinstate", **member)
            b = st.ballots["s"]
            b.reveals = {f: "yes" for f in FOUNDERS}
            ledger._ballot_close(st, {}, b.reveal_until + SEC, 10, "hiram", {"id": "s"})
            m = st.members["x"]
            self.assertEqual((b.result, m.status, m.suspended_until, m.status_since), ("passed", "active", None, b.reveal_until + SEC))


class Departure(unittest.TestCase):
    def test_a_suspended_member_may_still_leave(self):
        c = founded()
        c.add("ballot_open", "hiram", {"id": "s", "kind": "sanction", "subject": {"member": "carol", "measure": "suspend"}})
        c.vote("s", {"hiram": "yes", "ada": "yes"})
        self.assertEqual(c.state().members["carol"].status, "suspended")
        c.add("work", "carol", {"ref": URL})
        c.refused(self, "carol is not an active member")
        c.add("depart", "carol", {}, key_of="hiram")
        c.refused(self, "bad signature")
        c.add("depart", "carol", {})
        m = c.state().members["carol"]
        self.assertEqual((m.status, m.status_since), ("departed", c.now))
        c.add("depart", "carol", {})
        c.refused(self, "carol")

    def test_an_expelled_member_and_a_stranger_cannot_depart(self):
        c = founded()
        initiate(c, "mal")
        c.add("ballot_open", "hiram", {"id": "x", "kind": "sanction", "subject": {"member": "mal", "measure": "expel"}})
        c.vote("x", {f: "yes" for f in FOUNDERS})
        c.add("depart", "mal", {})
        c.refused(self, "mal")
        c.key("nobody")
        c.add("depart", "nobody", {})
        c.refused(self, "nobody")
        self.assertEqual(c.state().members["mal"].status, "expelled")
        self.assertEqual(ledger.DEPART_BLOCKED, {"departed", "expelled", "voided"})


# ---------------------------------------------------------------- votes and sponsors ----

class VotesAndSponsors(unittest.TestCase):
    def test_an_identical_repeated_reveal_is_refused(self):
        c = founded()
        c.add("ballot_open", "hiram", {"id": "am", "kind": "amendment",
                                       "subject": {"path": "docs/NEW.md", "new_sha256": "ab" * 32}})
        c.add("ballot_commit", "ada", {"id": "am", "commitment": commitment("am", "ada", "yes", salt_of("ada"))})
        reveal = {"id": "am", "vote": "yes", "salt": salt_of("ada")}
        c.add("ballot_reveal", "ada", reveal, days=7.5)
        c.add("ballot_reveal", "ada", dict(reveal), days=0.5)
        c.refused(self, "already revealed")

    def candidate(self, vouchers=("hiram", "ada")):
        c = founded()
        invite(c, "pat", by=vouchers[0])                           # the inviter is the first sponsor
        petition(c, "pat")
        for v in vouchers[1:]:
            c.add("vouch", v, {"candidate": "pat"})
        return c

    def test_a_vouch_after_the_admission_ballot_opened_is_refused(self):
        c = self.candidate()
        c.add("ballot_open", "hiram", {"id": "adm", "kind": "admission", "subject": {"candidate": "pat"}})
        c.add("vouch", "carol", {"candidate": "pat"})
        c.refused(self, "admission ballot")

    def test_sponsors_are_validated_again_when_the_ballot_opens(self):
        open_ = {"id": "adm", "kind": "admission", "subject": {"candidate": "pat"}}
        c = self.candidate()
        c.add("depart", "ada", {})
        c.add("ballot_open", "hiram", open_)
        c.refused(self, "lacks sponsors")
        c = self.candidate(("hiram", "ada", "carol"))
        c.add("depart", "ada", {})
        c.add("ballot_open", "hiram", open_)
        self.assertEqual(c.state().ballots["adm"].frozen["vouches"], ["hiram", "carol"])
        c.vote("adm", {"hiram": "yes", "carol": "yes"})
        self.assertEqual(c.state().members["pat"].sponsors, ("hiram", "carol"))

    def test_a_banned_or_demoted_sponsor_does_not_count(self):
        now = T0 + 10 * DAY
        members = [mk(f, activity=[now]) for f in FOUNDERS]
        st = hand_state(*members)
        st.petitions["pat"] = {"key": fake_key("pat"), "vouches": ["hiram", "ada"], "time": T0, "github_id": 7}
        body = {"id": "adm", "kind": "admission", "subject": {"candidate": "pat"}}
        st.members["ada"].sponsor_ban_until = now + DAY
        with self.assertRaisesRegex(Invalid, "lacks sponsors"):
            ledger._ballot_open(st, {}, now, 9, "hiram", body)
        st.members["ada"].sponsor_ban_until = now
        st.members["hiram"].sponsor_ban_until = now + DAY
        with self.assertRaisesRegex(Invalid, "lacks sponsors|only a sponsor"):
            ledger._ballot_open(st, {}, now, 9, "hiram", body)
        st.members["hiram"].sponsor_ban_until = None
        ledger._ballot_open(st, {}, now, 9, "hiram", body)
        self.assertEqual(st.ballots["adm"].frozen, {"key": fake_key("pat"), "vouches": ["hiram", "ada"], "github_id": 7})


# ---------------------------------------------------------------- the Council ----

class Council(unittest.TestCase):
    def test_a_suspended_holder_keeps_the_seat_so_the_council_never_exceeds_33(self):
        now = T0 + 5000 * DAY
        seat = now + 100 * DAY
        sitting = [mk(f"s{i:02d}", 33, seat_until=seat, past_seats=1, activity=[now]) for i in range(33)]
        sitting[0].status, sitting[0].suspended_until = "suspended", now + 50 * DAY
        cand = Member("cand", fake_key("cand"), 32, {1: T0, 32: T0}, activity=[now])
        st = hand_state(*sitting, cand)
        self.assertEqual((len(st.seats(now)), sum(st.members[x].is_active(now) for x in st.seats(now))), (33, 32))
        rnd = drand_round(now) + BEACON_DELAY_ROUNDS
        with self.assertRaisesRegex(Invalid, "no vacancies"):
            ledger._council_call(st, {}, now, 9, "s01", {"beacon_round": rnd})
        st.council_call, st.council_pool = drand_round(now), ("cand",)   # even a pending draw seats nobody
        ledger._council_draw(st, {}, now, 10, "s01", {"beacon": "ab" * 32})
        self.assertEqual((cand.degree, len(st.seats(now)), st.council_call, st.council_pool), (32, 33, None, ()))

    def test_the_drawn_are_checked_again_and_the_ineligible_are_skipped_in_lot_order(self):
        now = T0 + 5000 * DAY
        beacon, pool, rnd = "cd" * 32, tuple(f"p{i}" for i in range(6)), drand_round(now)   # drawn in time
        ranking = draw(list(pool), len(pool), beacon, f"council:{rnd}")
        fresh = lambda: hand_state(*(Member(p, fake_key(p), 32, {1: T0, 32: T0}, activity=[now]) for p in pool),
                                   *(mk(f"s{i:02d}", 33, seat_until=now + DAY, past_seats=1, activity=[now]) for i in range(31)),
                                   council_call=rnd, council_pool=pool)
        st = fresh()
        ledger._council_draw(st, {}, now, 9, "p0", {"beacon": beacon})
        self.assertEqual(sorted(l for l in pool if st.members[l].degree == 33), sorted(ranking[:2]))
        spoil = {"dormant": lambda m: setattr(m, "activity", [T0]), "departed": lambda m: setattr(m, "status", "departed"),
                 "suspended": lambda m: (setattr(m, "status", "suspended"), setattr(m, "suspended_until", now + DAY)),
                 "seated before": lambda m: setattr(m, "past_seats", 1), "no longer 32": lambda m: setattr(m, "degree", 33)}
        for why, change in spoil.items():
            st = fresh()
            change(st.members[ranking[0]])
            ledger._council_draw(st, {}, now, 9, "p1", {"beacon": beacon})
            seated = [l for l in pool if st.members[l].seat_until is not None]
            self.assertEqual(sorted(seated), sorted(ranking[1:3]), why)
            self.assertEqual(st.history["beacons"], absorbed({"round": rnd, "beacon": beacon}))


# ---------------------------------------------------------------- amendment paths ----

class AmendmentPaths(unittest.TestCase):
    def test_paths_are_case_sensitive_but_never_differ_only_by_case(self):
        c = founded()
        opens = lambda path, bid="am": c.add("ballot_open", "hiram", {
            "id": bid, "kind": "amendment", "subject": {"path": path, "new_sha256": "ab" * 32}})
        for path in ("Constitution.md", "constitution.md", "Canon/Degrees.toml", "@PROTOCOL"):
            opens(path)
            c.refused(self, "collides with the pinned path|amendment path")
        for path in ("ledger/entries/000000.json", "ledger/anchors/x.ots", "Ledger/entries/000001.json", "LEDGER", "ledger"):
            opens(path)
            c.refused(self, "ledger")
        for path in ("canon/eternal.toml", "Canon/Eternal.toml", "canon/eternal.toml.bak"):
            opens(path)
            c.refused(self, "eternal")
        opens("docs/New.md", "am1")
        c.vote("am1", {f: "yes" for f in FOUNDERS})
        self.assertEqual(c.state().pins["docs/New.md"], "ab" * 32)
        opens("docs/new.md", "am2")
        c.refused(self, "collides with the pinned path 'docs/New.md'")
        opens("docs/New.md", "am3")
        opens("CONSTITUTION.md", "am4")
        opens("ledgers/notes.md", "am5")
        self.assertEqual(len([b for b in c.state().ballots.values() if b.result is None]), 3)


# ---------------------------------------------------------------- liveness and inflation ----

class Activity(unittest.TestCase):
    def test_one_work_entry_per_member_per_24_hours(self):
        c = founded()
        c.add("work", "ada", {"ref": URL})
        first = c.now
        c.add("work", "carol", {"ref": URL})                       # another member is not affected
        c.now = first + DAY - SEC
        c.add("work", "ada", {"ref": URL + "/2"})
        c.refused(self, "one work entry per member per 24 hours")
        c.now = first + DAY
        c.add("work", "ada", {"ref": URL + "/2"})
        self.assertEqual(c.state().members["ada"].last_work, first + DAY)

    def test_activity_counts_one_point_per_utc_day(self):
        c = founded()
        c.now = T0 + 5 * DAY + timedelta(hours=1)
        c.add("ballot_open", "ada", {"id": "a1", "kind": "amendment", "subject": {"path": "docs/A.md", "new_sha256": "ab" * 32}})
        c.add("ballot_open", "ada", {"id": "a2", "kind": "amendment", "subject": {"path": "docs/B.md", "new_sha256": "ab" * 32}},
              days=0.5)
        c.add("work", "ada", {"ref": URL}, days=0.4)                # 22:36 the same UTC day
        m = c.state().members["ada"]
        self.assertEqual(m.activity, [T0, c.now])                  # one point, at the latest time of that day
        self.assertAlmostEqual(m.light(c.now), 1 + 0.5 ** (5.9 / 180), places=3)
        self.assertFalse(m.dormant(c.now + 365 * DAY))
        c.add("ballot_open", "ada", {"id": "a3", "kind": "amendment", "subject": {"path": "docs/C.md", "new_sha256": "ab" * 32}},
              days=0.1)                                             # 01:00 the next day
        self.assertEqual(len(c.state().members["ada"].activity), 3)


# ---------------------------------------------------------------- decide and the gate ----

class DecideAndGate(unittest.TestCase):
    def test_decide_is_exhaustive(self):
        for kind in ledger.KINDS:
            self.assertIsInstance(decide(kind, 3, 0, 3), bool)
        self.assertTrue(decide("witness", 2, 1, 3))
        self.assertFalse(decide("witness", 1, 1, 3))
        for kind in ("", "election", "Admission", None):
            with self.assertRaises(ValueError):
                decide(kind, 3, 0, 3)
            with self.assertRaises(ValueError):
                decide(kind, 0, 0, 0)

    def report(self, **flags):
        from openmasonry.verify import verify_report
        c = founded()
        led = write_ledger(tmpdir(self) / "led", c.entries)
        a = argparse.Namespace(ledger=led, tree=False, online=False, clock_since=None, root=None, pr_author=None,
                               since=None, json=True)
        for k, v in flags.items():
            setattr(a, k, v)
        with mock.patch("openmasonry.verify.replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)):
            return verify_report(a)

    def test_the_future_tolerance_is_a_named_constant(self):
        self.assertEqual(ledger.FUTURE_TOLERANCE, timedelta(minutes=10))
        self.assertTrue(self.report()["valid"])
        self.assertIn("STALE OR FUTURE TIME", self.report(clock_since=0)["message"])

    def test_negative_positions_are_usage_errors(self):
        for flags in ({"clock_since": -1}, {"since": -1, "pr_author": "hiram"}):
            r = self.report(**flags)
            self.assertFalse(r["valid"])
            self.assertTrue(r["message"].startswith("USAGE"), r["message"])
            self.assertEqual(r["problems"], ["usage"])


if __name__ == "__main__":
    unittest.main()
