"""Extended protocol tests: edge cases of the lifecycle, lots and ballots."""
import copy, json, os, subprocess, sys, tempfile, unittest, importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
from tests.test_protocol import (canon_digest, witness_subject, Chain, checkpoint, copy_governed, founded, genesis_body, initiate, invite, petition, salt_of,
                                 FOUNDERS, T0, DECL, entry_file, entry_path)
from openmasonry import canon
from openmasonry.ledger import (Invalid, State, Member, replay, electors_for, examiner_pool, entry_hash,
                                _council_draw, drand_round, BEACON_DELAY_ROUNDS)
from openmasonry.crypto import merkle_root

def fresh(test):
    t = tempfile.TemporaryDirectory(); test.addCleanup(t.cleanup); return Path(t.name)

def founded_with_witness(tmp, start=T0):
    c = Chain(tmp); c.now = start
    c.add("genesis", "hiram", genesis_body(c, FOUNDERS, ["tyler"], name="L"))
    return c

class Extended(unittest.TestCase):
    # 1 envelope / malformed body really go through the malformed path
    def test_malformed_body_is_invalid_with_reason(self):
        c = founded(fresh(self)); c.add("vouch", "hiram", {})
        with self.assertRaisesRegex(Invalid, r"entry 1: malformed vouch entry: missing field 'candidate'"): c.state()
    def test_extra_envelope_field_rejected(self):
        c = founded(fresh(self)); e = copy.deepcopy(c.entries); e[0]["x"] = 1
        with self.assertRaisesRegex(Invalid, "exactly the fields"): replay(e)
    # 2 time format pinned to UTC 'Z'
    def test_offset_or_naive_time_rejected(self):
        for bad in ("2027-01-01T00:00:00+00:00", "2027-01-01T00:00:00", "2027-01-01T00:00:00.5Z"):
            c = Chain(fresh(self)); c.add("genesis", "hiram", {})
            c.entries[0]["time"] = bad
            with self.assertRaisesRegex(Invalid, "time must be"): c.state()
    def test_time_cannot_go_backwards(self):
        c = founded(fresh(self)); c.add("work", "ada", {"ref": "https://example.org/pr/1"}, days=-1)
        with self.assertRaisesRegex(Invalid, "time goes backwards"): c.state()
    # 3 witness: close, checkpoint, root mismatch, unknown witness
    def test_witness_closes_ballot_and_checkpoints(self):
        c = founded_with_witness(fresh(self))
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness", "subject": witness_subject(c, "node2")})
        for f in FOUNDERS:  # vote without Chain.vote so the witness, not a member, closes
            from openmasonry.ledger import commitment
            c.add("ballot_commit", f, {"id": "w", "commitment": commitment("w", f, "yes", salt_of(f))})
        c.now += timedelta(days=7.3)
        for f in FOUNDERS: c.add("ballot_reveal", f, {"id": "w", "vote": "yes", "salt": salt_of(f)}, days=0.01)
        c.add("ballot_close", "tyler", {"id": "w"}, days=3)
        st = c.state(); hs = st.hashes
        c.add("witness", "tyler", checkpoint(st, root=merkle_root(hs)))
        st = c.state()
        self.assertEqual(st.ballots["w"].result, "passed"); self.assertIn("node2", st.witnesses)
        self.assertEqual((c.entries[-1]["body"]["root"], st.history["checkpoints"][0]), (merkle_root(hs), 1))
        self.assertNotIn("tyler", st.members)  # witness activity must not create a member
        c.entries.pop(); c.add("witness", "tyler", checkpoint(c.state(), root="0" * 64))
        with self.assertRaisesRegex(Invalid, "Merkle root mismatch"): c.state()
    def test_unknown_witness_and_member_cannot_checkpoint(self):
        c = founded(fresh(self)); c.add("witness", "ada", checkpoint(c.state()))
        with self.assertRaisesRegex(Invalid, "unknown witness"): c.state()
    # 4 sanction: suspended member can no longer act; accused is not an elector
    def test_suspension_silences_member_and_excludes_accused(self):
        c = founded(fresh(self))
        c.add("ballot_open", "hiram", {"id": "s", "kind": "sanction", "subject": {"member": "carol", "measure": "suspend"}})
        self.assertNotIn("carol", c.state().ballots["s"].electors)
        c.vote("s", {"hiram": "yes", "ada": "yes"})
        self.assertEqual(c.state().members["carol"].status, "suspended")
        c.add("work", "carol", {"ref": "https://example.org/pr/2"})
        with self.assertRaisesRegex(Invalid, "carol is not an active member"): c.state()
    # 5 dormancy lowers the quorum and keeps the vote (pure, no ssh)
    def test_dormant_members_keep_the_vote_and_leave_the_quorum(self):
        from openmasonry.ledger import electorate
        now = T0 + timedelta(days=400)
        st = State(members={l: Member(l, "k", 3, {1: T0, 3: T0}, activity=[T0 if l == "old" else now]) for l in ("a", "b", "old")})
        self.assertEqual(electors_for(st, "amendment", {}, now), frozenset({"a", "b", "old"}))
        self.assertEqual(electorate(st, "amendment", {}, now), (frozenset({"a", "b", "old"}), 2))
    # 6 examiner_pool ladder rungs (pure)
    def test_examiner_pool_ladder(self):
        mk = lambda l, d, sp=(): Member(l, "k", d, {i: T0 for i in range(1, d + 1)}, sponsors=sp, activity=[T0])
        cand = mk("cand", 3, ("s1", "s2"))
        st = State(members={m.login: m for m in [cand, mk("s1", 4), mk("s2", 4), mk("p4", 4), mk("p4b", 4), mk("m3", 3)]},
                   pins={"canon/degrees.toml": canon_digest()})
        k = canon.degrees()[4].examiners
        self.assertEqual(examiner_pool(st, cand, 4, T0), ["m3", "p4", "p4b"][:3] if k > 2 else ["p4", "p4b"])  # rung 1 or 2
        st.members.pop("m3"); st.members.pop("p4b")
        self.assertEqual(examiner_pool(st, cand, 4, T0), ["p4", "s1", "s2"])   # rung 3: sponsors as last resort
        self.assertNotIn("cand", examiner_pool(st, cand, 4, T0))
    # 7 exam failure, retry after 90 days, expiry
    def test_failed_exam_retry_after_90_days(self):
        c = founded(fresh(self)); initiate(c, "frank")
        c.exam("frank", 2, days=31, verdict="fail")
        rnd = lambda d: drand_round(c.now + timedelta(days=d)) + BEACON_DELAY_ROUNDS
        c.add("exam_open", "frank", {"candidate": "frank", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd(10)}, days=10)
        with self.assertRaisesRegex(Invalid, "retry only after"): c.state()
        c.entries.pop(); c.now -= timedelta(days=10)
        c.add("exam_open", "frank", {"candidate": "frank", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd(91)}, days=91)
        self.assertIsNone(c.state().exams[("frank", 2)].examiners)
    def test_report_after_expiry_rejected(self):
        c = founded(fresh(self)); initiate(c, "hal")
        rnd = drand_round(c.now + timedelta(days=31)) + BEACON_DELAY_ROUNDS
        c.add("exam_open", "hal", {"candidate": "hal", "degree": 2, "work_ref": "https://example.org/work", "beacon_round": rnd}, days=31)
        c.add("exam_draw", "hal", {"candidate": "hal", "degree": 2, "beacon": f"{rnd:064x}"}, days=0.34)
        x = c.state().exams[("hal", 2)].examiners[0]
        c.add("exam_report", x, {"candidate": "hal", "degree": 2, "verdict": "pass"}, days=61)
        with self.assertRaisesRegex(Invalid, "expired"): c.state()
    # 8 failed admission frees the sponsors' budget
    def test_failed_admission_releases_sponsor_budget(self):
        c = founded(fresh(self))
        for i in range(5):
            w = f"r{i}"; petition(c, w)                      # hiram invites, and so sponsors
            c.add("vouch", "ada", {"candidate": w})
            c.add("ballot_open", "hiram", {"id": f"a{i}", "kind": "admission", "subject": {"candidate": w}})
            c.vote(f"a{i}", {"hiram": "no", "ada": "no", "carol": "no"})
        st = c.state(); self.assertFalse(st.petitions); self.assertEqual(st.ballots["a4"].result, "failed")
    # 9 council draw (pure): vacancies, sitting excluded, once per life
    def test_council_draw_once_per_life(self):
        now = T0 + timedelta(days=10000); need = canon.degrees()[33].wait_days
        mk = lambda l, seats=0: Member(l, "k", 32, {1: T0, 32: now - timedelta(days=need)}, activity=[now], past_seats=seats)
        st = State(members={m.login: m for m in [mk("a"), mk("b"), mk("vet", 1)]}, council_call=drand_round(now),
                   council_pool=("a", "b"), pins={"canon/degrees.toml": canon_digest()})
        _council_draw(st, {}, now, 9, "tyler", {"beacon": "ab" * 32})
        self.assertEqual(st.seats(now), ["a", "b"]); self.assertEqual(st.members["vet"].degree, 32)
        self.assertIsNone(st.council_call)
    # 10 a departed member can be invited again, petition and be readmitted (the next test checks that "once per life" history survives)
    def test_rejoin_preserves_past_seats(self):
        c = founded(fresh(self)); initiate(c, "ivy")
        c.add("depart", "ivy", {})
        self.assertEqual(c.state().members["ivy"].status, "departed")
        petition(c, "ivy", days=91)
        c.add("vouch", "ada", {"candidate": "ivy"})
        c.add("ballot_open", "hiram", {"id": "re", "kind": "admission", "subject": {"candidate": "ivy"}})
        c.vote("re", {f: "yes" for f in FOUNDERS})
        m = c.state().members["ivy"]
        self.assertEqual(m.status, "active"); self.assertIn(1, m.since)

    def test_rejoin_keeps_once_per_life_council_history(self):
        from openmasonry.ledger import _ballot_close, Ballot
        now = T0 + timedelta(days=500)
        st = State(members={"vet": Member("vet", "k", 33, {1: T0}, status="departed", status_since=T0, activity=[T0], past_seats=1,
                                          github_id=7)},
                   petitions={"vet": {"key": "k2", "vouches": ["a", "b"], "time": now, "github_id": 7}})
        st.ballots["re"] = Ballot("re", "admission", {"candidate": "vet"}, frozenset({"a", "b", "c"}), now, now, "a",
                                  reveals={"a": "yes", "b": "yes", "c": "yes"},
                                  frozen={"key": "k2", "vouches": ["a", "b"], "github_id": 7})
        _ballot_close(st, {}, now + timedelta(days=1), 9, "a", {"id": "re"})
        self.assertEqual((st.members["vet"].degree, st.members["vet"].past_seats, st.members["vet"].github_id), (1, 1, 7))

    def test_departed_member_cannot_be_invited_before_90_days(self):
        c = founded(fresh(self)); initiate(c, "jo"); c.add("depart", "jo", {})
        invite(c, "jo", days=10)
        with self.assertRaisesRegex(Invalid, "may be invited again once 90 days have passed"): c.state()

    def test_petition_lapses_and_frees_sponsor_budget(self):
        c = founded(fresh(self))
        for i in range(4):
            petition(c, f"p{i}")                             # four petitions under hiram's invitations: the whole budget
        petition(c, "late", days=181)
        self.assertEqual(c.state().petitions["late"]["vouches"], ["hiram"])

    def test_bad_logins_keys_and_amendment_paths(self):
        c = founded(fresh(self))
        bad = copy.deepcopy(c.entries); bad[0]["actor"] = "hiram\nx"
        with self.assertRaisesRegex(Invalid, "valid GitHub login"): replay(bad)
        invite(c, "kim")
        c.add("petition", "kim", {"key": c.key("kim") + " comment", "declaration_sha256": DECL})
        with self.assertRaisesRegex(Invalid, "ssh-ed25519"): c.state()
        c.entries.pop()
        c.add("ballot_open", "ada", {"id": "x", "kind": "amendment", "subject": {"path": "../outside", "new_sha256": "ab" * 32}})
        with self.assertRaisesRegex(Invalid, "amendment path|inside the repository"): c.state()

    def test_stub_verifier_makes_core_pure(self):
        c = founded(fresh(self)); e = copy.deepcopy(c.entries); e[0]["sig"] = "garbage"
        with self.assertRaisesRegex(Invalid, "bad signature"): replay(e)
        self.assertEqual(replay(e, verifier=lambda *a: True).seq, 0)

    def test_due_actions_is_what_the_witness_executes(self):
        from openmasonry.ledger import due_actions
        c = founded_with_witness(fresh(self))
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness", "subject": witness_subject(c, "node2")})
        st = c.state()
        self.assertEqual(due_actions(st, st.time), [])
        self.assertEqual(due_actions(st, st.time + timedelta(days=11)), [("ballot_close", {"id": "w"})])

    def test_online_audit_detects_forged_beacon(self):
        from openmasonry.beacon import audit
        recorded = [{"round": 7, "beacon": "ab" * 32}]
        self.assertEqual(audit(recorded, fetcher=lambda r: "ab" * 32), [])
        self.assertEqual(len(audit(recorded, fetcher=lambda r: "cd" * 32)), 1)

    def test_check_tree_detects_missing_and_changed_files(self):
        from openmasonry.govern import check_tree
        tmp = fresh(self); (tmp / "A.md").write_text("x")
        st = State(pins={"A.md": __import__("hashlib").sha256(b"x").hexdigest(), "B.md": "00" * 32})
        probs = check_tree(st, root=tmp)
        self.assertEqual(len(probs), 1); self.assertIn("B.md", probs[0]); self.assertIn("missing", probs[0])

    def test_heraldry_is_deterministic_svg(self):
        from openmasonry import heraldry
        import xml.dom.minidom
        a = heraldry.personal_arms("ada", "ssh-ed25519 AAAA", 3)
        self.assertEqual(a, heraldry.personal_arms("ada", "ssh-ed25519 AAAA", 3))
        xml.dom.minidom.parseString(a)
        for d in canon.degrees().values():
            xml.dom.minidom.parseString(heraldry.degree_arms(d))

    def test_every_degree_has_its_own_arms(self):
        """The charge tells degrees apart that share a field and an ordinary (2 and 26, 9 and 10, ...)."""
        import re
        from openmasonry import heraldry
        ds = canon.degrees().values()
        self.assertTrue(all(d.charge in heraldry.CHARGES for d in ds))
        drawn = {re.sub(r'aria-label="[^"]*"|<title>.*?</title>', "", heraldry.degree_arms(d)) for d in ds}
        self.assertEqual(len(drawn), 33)
    # 11 CLI end-to-end: append genesis, verify, tamper, clock-since, state --json
    def test_cli_end_to_end(self):
        tmp = fresh(self); led = tmp / "led"; c = Chain(tmp); pub = c.key("hiram")
        body = json.dumps(genesis_body(c, ["hiram"], name="L"))
        run = lambda *a: subprocess.run([sys.executable, "-m", "openmasonry", *a, "--ledger", str(led)] if a[0] != "x" else [],
                                        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")})
        r = run("append", "genesis", "--actor", "hiram", "--key", str(c.keys["hiram"][0]), "--body", body, "--time", "2027-01-01T00:00:00Z")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VALID", run("verify", "--tree").stdout)
        r = run("verify", "--clock-since", "0"); self.assertEqual(r.returncode, 1); self.assertIn("STALE OR FUTURE", r.stdout)
        self.assertEqual(json.loads(run("state", "--json").stdout)["members"][0]["login"], "hiram")
        f = entry_path(led, 0); e = json.loads(f.read_text()); e["body"]["name"] = "X"; f.write_text(json.dumps(e))
        r = run("verify"); self.assertEqual(r.returncode, 1); self.assertIn("INVALID — entry 0: bad signature", r.stdout)
        f.write_text(json.dumps(json.loads(f.read_text()) | {"body": json.loads(body)}))  # untamper
        r = run("append", "work", "--actor", "hiram", "--key", str(c.keys["hiram"][0]), "--body", "{}")
        self.assertEqual(r.returncode, 1); self.assertIn("REFUSED", r.stdout); self.assertFalse(entry_path(led, 1).exists())
    # 12 witness cycle: closes expired ballot and checkpoints, no push
    def test_witness_cycle(self):
        tmp = fresh(self); repo = copy_governed(tmp / "repo"); (repo / "ledger" / "entries").mkdir(parents=True)
        c = founded_with_witness(tmp, start=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=30))
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness", "subject": witness_subject(c, "node2")})
        for e in c.entries: entry_file(repo / "ledger" / "entries", e["seq"]).write_text(json.dumps(e))
        os.environ.update(OM_WITNESS_REPO=str(repo), OM_WITNESS_NAME="tyler", OM_WITNESS_KEY=str(c.keys["tyler"][0]), OM_WITNESS_PUSH="none")
        sys.path.insert(0, str(REPO / "node")); w = importlib.reload(importlib.import_module("witness"))
        w.git = lambda *a, **k: ""
        w.cycle()
        st = replay(w.load(w.LEDGER))
        self.assertEqual(st.ballots["w"].result, "lapsed")            # no votes -> no quorum: it lapsed
        self.assertEqual([e["type"] for e in w.load(w.LEDGER)][-2:], ["ballot_close", "witness"])
        w.cycle(); self.assertEqual(len(w.load(w.LEDGER)), st.seq + 1)  # idempotent: nothing new
if __name__ == "__main__": unittest.main()
