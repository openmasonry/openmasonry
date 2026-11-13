"""The member commands for custodians, corrections and key recovery, and what the Guide says about them.

The commands only draft; `om approve` signs. Every test that runs `om` uses a scratch ledger under a temporary
directory, real OpenSSH keys made there, and the test-mode approval bypass (keys inside the temporary OM_HOME).
The Guide tests are pure and use `Fast` (the "signature" of an entry is the public key that signed it).
Nothing touches the network.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import unittest
from datetime import timedelta
from pathlib import Path

from openmasonry import actions, canon, crypto, govern, ledger
from openmasonry.__main__ import corrections_report
from openmasonry.guide import custodian_steps, next_steps, notices
from openmasonry.ledger import custodian_message, custodian_revoke_message, iso, load, replay, signed_payload, ts
from tests.test_custodian import (SEVEN, apply_, commit, correct, cosign, freeze, halt, lodge, objection, open_ballot,
                                  sanction, void)
from tests.test_guide import OmHarness, tmpdir
from tests.test_protocol import FOUNDERS, T0, Chain, genesis_body, entry_file, entry_path
from tests.test_strict import DAY, SEC

REASON_TEXT = "The key of ada was published by mistake on 2027-01-02.\nSee the public issue 12.\n"
REASON_SHA = hashlib.sha256(REASON_TEXT.encode()).hexdigest()
ADVICE = r"(?i)\b(should|recommend|suggest|advise|ought)"


def bare(path: Path) -> str:
    return " ".join(Path(f"{path}.pub").read_text().split()[:2])


class Lodge(OmHarness):
    """A scratch ledger at <tmp>/ledger/entries founded with custodians, driven through `om`."""

    founders = FOUNDERS
    custodians = (("warden", "hiram"),)
    threshold = 1

    def setUp(self):
        self.tmp = tmpdir(self)
        self.led = self.tmp / "ledger" / "entries"
        self.c = Chain(self.tmp)
        self.c.add("genesis", self.founders[0], genesis_body(self.c, self.founders, custodians=self.custodians,
                                                             custodian_threshold=self.threshold))
        self.led.mkdir(parents=True)
        self.t0 = self.c.now
        self.sync()
        self.reason = self.tmp / "reason.md"
        self.reason.write_text(REASON_TEXT, encoding="utf-8")

    def sync(self):
        for e in self.c.entries:
            p = entry_path(self.led, e["seq"])
            if not p.exists():
                entry_file(self.led, e["seq"]).write_text(json.dumps(e))

    def reload(self):
        """Take the entries `om approve` wrote into the in-memory chain."""
        self.c.entries = load(self.led)
        self.c.now = max(self.c.now, ts(self.c.entries[-1]["time"]))
        return self.c.entries[-1]

    def chain(self, typ, actor, body, day, key_of=None):
        self.c.now = self.t0 + timedelta(days=day)
        e = self.c.add(typ, actor, body, key_of=key_of)
        self.sync()
        return e

    def cenv(self, name="warden", login=None, key_of=None):
        """The environment of the person who holds the custodian key `name`: a custodian is no GitHub login."""
        home = self.tmp / f"home-custodian-{name}"
        home.mkdir(exist_ok=True)
        (home / ".test-mode").write_text("tests only")
        key = home / "custodian"
        self.c.key(key_of or name)
        shutil.copy2(self.c.keys[key_of or name][0], key)
        shutil.copy2(f"{self.c.keys[key_of or name][0]}.pub", f"{key}.pub")
        env = {"OM_CUSTODIAN": name, "OM_CUSTODIAN_KEY": str(key), "OM_HOME": str(home),
               "OM_CONFIRM": "insecure-auto-approve-for-tests", "OM_CACHE": str(self.tmp / "cache"), "OM_LOGIN": ""}
        return env | ({"OM_LOGIN": login} if login else {})

    def om(self, *args, env, day=0.0, code=None):
        r = self.run_om(*args, "--ledger", str(self.led), "--time", self.T(day), env=env)
        if code is not None:
            self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r

    def cdraft(self, *args, name="warden", day=0.0):
        return json.loads(self.om(*args, "--json", env=self.cenv(name), day=day, code=3).stdout)

    def capprove(self, digest, name="warden", ok=True):
        r = self.run_om("approve", digest[:16], "--no-submit", env=self.cenv(name))
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r

    def act(self, *args, who="hiram", day=0.0):
        """Draft and approve a member act; return the signed entry."""
        self.approve(self.draft(*args, who=who, day=day)["digest"], who=who)
        return self.reload()

    def cact(self, *args, name="warden", day=0.0):
        self.capprove(self.cdraft(*args, name=name, day=day)["digest"], name=name)
        return self.reload()

    def state(self):
        return replay(load(self.led))


# ---------------------------------------------------------------- 1: the genesis names custodians ----

class GenesisWithCustodians(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.led = self.tmp / "ledger" / "entries"
        self.home = self.tmp / "home"
        self.home.mkdir()
        (self.home / ".test-mode").write_text("tests only")
        for name in ("key", "warden", "warden-revoke", "keeper", "keeper-revoke", "ada"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(self.home / name)], check=True)
        self.env = {"OM_LOGIN": "hiram", "OM_KEY": str(self.home / "key"), "OM_HOME": str(self.home),
                    "OM_CONFIRM": "insecure-auto-approve-for-tests", "OM_CACHE": str(self.tmp / "cache")}

    def om(self, *args):
        return OmHarness.run_om(self, *args, env=self.env)

    def genesis(self, *args):
        return self.om("genesis", "--ledger", str(self.led), "--github-id", "7", "--time", "2027-01-01T00:00:00Z", *args)

    def spec(self, name, member=None):
        return f"{name}:{self.home / name}.pub:{self.home / name}-revoke.pub" + (f":{member}" if member else "")

    def test_the_draft_carries_placeholders_and_approval_signs_both_proofs(self):
        r = self.genesis("--custodian", self.spec("warden"), "--json")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        d = json.loads(r.stdout)
        key, revoke = bare(self.home / "warden"), bare(self.home / "warden-revoke")
        self.assertEqual(d["entry"]["body"]["custodians"], [
            {"name": "warden", "key": key, "revoke_key": revoke, "member": "hiram",
             "proof": actions.CUSTODIAN_PROOF_PENDING, "revoke_proof": actions.CUSTODIAN_PROOF_PENDING}])
        self.assertEqual(d["entry"]["body"]["custodian_threshold"], 1)
        self.assertIn("warden", d["summary"])
        self.assertFalse(self.led.exists() and any(self.led.iterdir()))
        text = actions.describe(None, d["entry"])                # the dialog: name, both fingerprints, the member
        self.assertIn("Custodians: warden (the member hiram)", text)
        self.assertIn(actions.fingerprint(key), text)
        self.assertIn(actions.fingerprint(revoke), text)
        # Never written into the repository by a test: the ratified canon is archived there already.
        self.assertTrue((canon.CANON / "history" / f"{d['entry']['body']['pins']['canon/degrees.toml']}.toml").exists())
        r = self.om("approve", d["digest"][:16], "--no-submit")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        signed = json.loads(entry_path(self.led, 0).read_text())
        (c,) = signed["body"]["custodians"]
        self.assertTrue(crypto.signature_valid(custodian_message("warden", "hiram", key), c["proof"], key))
        self.assertTrue(crypto.signature_valid(custodian_revoke_message("warden", key, revoke), c["revoke_proof"], revoke))
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], bare(self.home / "key")))
        st = replay(load(self.led))                              # real signatures, the real verifier
        self.assertEqual((st.custodians["warden"].member, st.custodian_threshold), ("hiram", 1))

    def test_a_mistyped_github_id_is_named_and_the_pinned_network_toml_is_never_to_be_edited(self):
        import tomllib                                           # `om` runs apart: it reads the file itself
        pinned = tomllib.loads((canon.ROOT / "src" / "openmasonry" / "network.toml").read_text())["founder_github_id"]
        r = self.genesis("--custodian", self.spec("warden"), "--json")
        self.assertIn(f"the GitHub id given (7) does not match founder_github_id ({pinned}) of "
                      "src/openmasonry/network.toml", r.stderr)
        self.assertIn("typo", r.stderr)
        self.assertNotIn("set founder_github_id", r.stderr)

    def test_both_private_keys_must_be_there_when_the_person_approves(self):
        d = json.loads(self.genesis("--custodian", self.spec("warden"), "--json").stdout)
        (self.home / "warden-revoke").unlink()                   # only the public half is left
        r = self.om("approve", d["digest"][:16], "--no-submit")
        self.assertEqual(r.returncode, 1)
        self.assertIn("revoke key", r.stdout)
        self.assertIn("both private keys", r.stdout)
        self.assertFalse(entry_path(self.led, 0).exists())

    def test_the_member_and_the_threshold_are_stated(self):
        ada = f"ada:{self.home / 'ada'}.pub:8"
        two = ("--cofounder", ada, "--custodian", self.spec("warden"), "--custodian", self.spec("keeper", "ada"))
        r = self.genesis(*two, "--json")
        self.assertEqual(r.returncode, 1)                        # two custodians: the threshold is a decision
        self.assertIn("--custodian-threshold", r.stdout)
        r = self.genesis(*two, "--custodian-threshold", "2", "--json")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        body = json.loads(r.stdout)["entry"]["body"]
        self.assertEqual([(c["name"], c["member"]) for c in body["custodians"]], [("warden", "hiram"), ("keeper", "ada")])
        self.assertEqual(body["custodian_threshold"], 2)

    def test_what_the_protocol_refuses_is_refused_at_the_draft(self):
        r = self.genesis("--custodian", self.spec("warden", "stranger"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("WOULD BE REFUSED", r.stdout)
        self.assertIn("must be the login of a founder", r.stdout)
        r = self.genesis("--custodian", "warden:only-one-key.pub")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NAME:KEY.pub:REVOKE.pub", r.stdout)
        r = self.genesis("--custodian", f"warden:{self.home / 'warden'}.pub:{self.home / 'absent'}.pub")
        self.assertEqual(r.returncode, 1)
        self.assertIn("absent.pub", r.stdout)


# ---------------------------------------------------------------- 2: who signs a custodian act ----

class CustodianIdentity(Lodge):
    def test_a_custodian_act_says_who_and_with_which_key(self):
        anonymous = {k: v for k, v in self.cenv().items() if not k.startswith("OM_CUSTODIAN")}
        r = self.om("alive", env=anonymous, day=1, code=1)
        self.assertIn("--as NAME", r.stdout)
        self.assertIn("OM_CUSTODIAN", r.stdout)
        r = self.om("alive", env=anonymous | {"OM_CUSTODIAN": "warden"}, day=1, code=1)
        self.assertIn("--custodian-key", r.stdout)
        member = self.cenv(key_of="hiram")                       # the member key is never a custodian key
        r = self.om("alive", env=member, day=1, code=1)
        self.assertIn("is not the custodian key the ledger holds for warden", r.stdout)
        r = self.om("alive", env=self.cenv("nobody", key_of="warden"), day=1, code=1)
        self.assertIn("WOULD BE REFUSED", r.stdout)
        self.assertIn("nobody is not a custodian", r.stdout)

    def test_a_sign_of_life_is_signed_with_the_custodian_key(self):
        env = self.cenv()
        flags = {k: v for k, v in env.items() if not k.startswith("OM_CUSTODIAN")}
        r = self.om("alive", "--as", "warden", "--custodian-key", env["OM_CUSTODIAN_KEY"], "--json", env=flags, day=100, code=3)
        d = json.loads(r.stdout)
        self.assertEqual((d["schema"], d["entry"]["type"], d["entry"]["actor"], d["entry"]["body"]),
                         ("om.draft/1", "custodian_alive", "warden", {}))
        self.assertFalse(entry_path(self.led, 1).exists())
        self.capprove(d["digest"])
        signed = self.reload()
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], self.c.key("warden")))
        self.assertFalse(crypto.signature_valid(signed_payload(signed), signed["sig"], self.c.key("hiram")))
        self.assertEqual(self.state().custodians["warden"].alive, self.t0 + 100 * DAY)

    def test_the_revoke_key_removes_the_custodian_key(self):
        home = Path(self.cenv()["OM_HOME"])
        for suffix in ("", ".pub"):
            shutil.copy2(f"{self.c.keys['warden-revoke'][0]}{suffix}", f"{home / 'revoke'}{suffix}")
        env = {k: v for k, v in self.cenv().items() if not k.startswith("OM_CUSTODIAN")}
        r = self.om("revoke-custodian", "warden", "--revoke-key", str(home / "custodian"), env=env, day=2, code=1)
        self.assertIn("is not the revoke key the ledger holds for warden", r.stdout)
        r = self.om("revoke-custodian", "warden", "--revoke-key", str(home / "revoke"), "--json", env=env, day=2, code=3)
        d = json.loads(r.stdout)
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"], d["entry"]["body"]),
                         ("custodian_revoke", "warden", {"name": "warden"}))
        self.capprove(d["digest"])
        signed = self.reload()
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], self.c.key("warden-revoke")))
        st = self.state()
        self.assertEqual(st.custodian_status(st.custodians["warden"], st.time), "revoked")


    def test_a_stale_custodian_entry_is_dropped_and_drafted_again(self):
        self.cact("alive", day=1)
        box = Path(self.env("hiram")["OM_HOME"]) / "outbox" / ledger.entry_hash(self.c.entries[0])[:16]
        box.mkdir(parents=True)
        shutil.move(str(entry_path(self.led, 1)), str(box / "000001.json"))      # its pull request never merged…
        self.c.entries.pop()
        self.act("work", "https://example.org/a", who="ada", day=1)                 # …and another entry took its place
        r = self.om("pending", "--rebase", "1", env=self.env("hiram"), day=2, code=1)
        self.assertIn("is not signed with your member key", r.stdout)
        self.assertIn("pending --drop 1", r.stdout)


# ---------------------------------------------------------------- 3: corrections ----

class CorrectionTargets(unittest.TestCase):
    def test_each_act_takes_exactly_its_own_target_flags(self):
        t = actions.correction_target
        self.assertEqual(t("freeze_key", login="ada"), {"login": "ada"})
        self.assertEqual(t("freeze_witness", name="tyler"), {"name": "tyler"})
        self.assertEqual(t("stay", ballot="s"), {"ballot": "s"})
        self.assertEqual(t("halt"), {})
        self.assertEqual(t("hold_room", login="carol"), {"login": "carol"})
        self.assertEqual(t("note", action="hide", target="issue:4", rule="ROOMS.md#5"),
                         {"action": "hide", "target": "issue:4", "rule": "ROOMS.md#5"})
        self.assertEqual(t("void_ballot", ballot="s"), {"id": "s"})
        self.assertEqual(t("undo_ballot", ballot="adm"), {"id": "adm"})
        self.assertEqual(set(actions.CORRECTION_FLAGS), set(ledger.ACTS))
        for act, flags in actions.CORRECTION_FLAGS.items():      # the flags fill exactly the target the protocol reads
            target = t(act, **{f: "x" for f in flags})
            self.assertEqual(set(target), set(ledger.TARGET_FIELDS[act]), act)
        with self.assertRaisesRegex(actions.UserError, "freeze_key needs --login"):
            t("freeze_key")
        with self.assertRaisesRegex(actions.UserError, "halt takes no --ballot"):
            t("halt", ballot="s")
        with self.assertRaisesRegex(actions.UserError, "stay needs --ballot"):
            t("stay", login="ada")

    def test_the_reason_is_a_text_of_at_most_64_kib(self):
        read = actions.read_reason
        tmp = tmpdir(self)
        good = tmp / "r.md"
        good.write_text("Why: a key was published.\n✓ → ≥ 日本\n", encoding="utf-8")
        data, sha = read(good)
        self.assertEqual((data, sha), (good.read_bytes(), hashlib.sha256(good.read_bytes()).hexdigest()))
        cases = ((b"", "is empty"), (b"x" * (govern.REASON_MAX_BYTES + 1), "larger than 65536 bytes"),
                 (b"\xff\xfe binary", "not UTF-8 text"), (b"a\x00b", "control character"))
        for raw, why in cases:
            bad = tmp / "bad.md"
            bad.write_bytes(raw)
            with self.assertRaisesRegex(actions.UserError, why):
                read(bad)
        (tmp / "exact.md").write_bytes(b"x" * govern.REASON_MAX_BYTES)
        self.assertEqual(len(read(tmp / "exact.md")[0]), govern.REASON_MAX_BYTES)
        with self.assertRaisesRegex(actions.UserError, "cannot read the reason"):
            read(tmp / "absent.md")

    def test_the_dialog_states_when_an_act_lapses_and_what_the_reason_says(self):
        base = {"seq": 3, "time": "2027-01-02T00:00:00Z", "actor": "warden", "type": "correction"}
        body = {"act": "freeze_key", "target": {"login": "ada"}, "ground": "key_compromised", "reason_sha256": REASON_SHA}
        text = actions.describe(None, base | {"body": body})
        self.assertIn("It lapses by itself at 2027-02-01T00:00:00Z", text)
        self.assertIn(f"ledger/reasons/{REASON_SHA}.md", text)
        noticed = actions.describe(None, base | {"body": body | {"act": "void_ballot", "target": {"id": "s"}}})
        self.assertIn("Its notice ends at 2027-01-16T00:00:00Z", noticed)
        self.assertIn("2027-01-23T00:00:00Z", noticed)
        note = actions.describe(None, base | {"body": body | {
            "act": "note", "target": {"action": "hide", "target": "issue:4", "rule": "ROOMS.md"}}})
        self.assertNotIn("lapses", note)
        hostile = actions.describe(None, base | {"time": "soon\x1b[2J", "body": body})
        self.assertNotIn("\x1b", hostile)
        excerpt = actions.reason_excerpt(("line one\x1b[2J\n" + "line\n" * 40).encode())
        self.assertIn("line one", excerpt)
        self.assertNotIn("\x1b", excerpt)
        self.assertLessEqual(len(excerpt), 420)
        self.assertLessEqual(excerpt.count("\n"), 6)


class Correct(Lodge):
    def test_the_reason_is_staged_and_written_beside_the_entry_when_the_person_approves(self):
        d = self.cdraft("correct", "freeze_key", "--login", "ada", "--reason", str(self.reason), day=1)
        self.assertEqual(d["schema"], "om.draft/1")
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"]), ("correction", "warden"))
        self.assertEqual(d["entry"]["body"], {"act": "freeze_key", "target": {"login": "ada"}, "ground": "key_compromised",
                                              "reason_sha256": REASON_SHA})
        self.assertEqual(d["reason"], {"sha256": REASON_SHA, "path": f"ledger/reasons/{REASON_SHA}.md",
                                       "bytes": len(REASON_TEXT.encode())})
        reasons = self.tmp / "ledger" / "reasons"
        self.assertFalse(reasons.exists())                       # nothing is written by a draft
        self.assertFalse(entry_path(self.led, 1).exists())
        self.reason.write_text("another text, written after the draft\n")
        done = json.loads(self.run_om("approve", d["digest"][:16], "--no-submit", "--json", env=self.cenv()).stdout)
        self.assertEqual((done["schema"], done["type"], done["reason_file"]),
                         ("om.approved/1", "correction", str((reasons / f"{REASON_SHA}.md").resolve())))
        signed = self.reload()
        self.assertEqual({k: v for k, v in signed.items() if k != "sig"}, d["entry"])
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], self.c.key("warden")))
        self.assertEqual((reasons / f"{REASON_SHA}.md").read_text(encoding="utf-8"), REASON_TEXT)   # exactly what was staged
        self.assertEqual([p.name for p in reasons.iterdir()], [f"{REASON_SHA}.md"])
        st = self.state()
        self.assertEqual(govern.missing_reasons(st, self.tmp, since=0), ([], []))    # what the judge asks of the pull request
        self.assertEqual(govern.stray_reasons(st, self.tmp), [])
        self.assertIsNotNone(st.frozen("ada", st.time))

    def test_a_staged_reason_that_was_changed_is_refused(self):
        d = self.cdraft("correct", "halt", "--reason", str(self.reason), day=1)
        self.assertEqual(d["entry"]["body"]["ground"], "attack_in_progress")
        p = Path(self.cenv()["OM_HOME"]) / "pending" / f"{d['digest']}.json"
        data = json.loads(p.read_text())
        data["secret"]["reason"] = "QW5vdGhlciByZWFzb24K"
        p.write_text(json.dumps(data))
        r = self.capprove(d["digest"], ok=False)
        self.assertIn("TAMPERED", r.stdout)
        self.assertFalse(entry_path(self.led, 1).exists())
        self.assertFalse((self.tmp / "ledger" / "reasons").exists())

    def test_a_ground_is_asked_for_when_the_act_has_more_than_one(self):
        r = self.om("correct", "hold_room", "--login", "carol", "--reason", str(self.reason), env=self.cenv(), day=1, code=1)
        self.assertIn("--ground", r.stdout)
        for ground in ledger.GROUNDS:
            self.assertIn(ground, r.stdout)
        r = self.om("correct", "hold_room", "--reason", str(self.reason), "--ground", "identity_fraud", env=self.cenv(),
                    day=1, code=1)
        self.assertIn("hold_room needs --login", r.stdout)

    def test_a_refusal_of_the_protocol_is_shown_as_today(self):
        r = self.om("correct", "hold_room", "--login", "hiram", "--ground", "identity_fraud", "--reason", str(self.reason),
                    env=self.cenv(), day=1, code=1)
        self.assertIn("WOULD BE REFUSED", r.stdout)
        self.assertIn("recusal", r.stdout)
        r = self.om("correct", "freeze_key", "--login", "ada", "--ground", "protocol_defect", "--reason", str(self.reason),
                    "--json", env=self.cenv(), day=1, code=1)
        self.assertIn("freeze_key takes one ground only", json.loads(r.stdout)["refused"])

    def test_a_note_and_a_withdrawal(self):
        note = self.cact("correct", "note", "--action", "lock", "--target", "issue:3", "--rule", "ROOMS.md",
                         "--reason", str(self.reason), day=1)       # a note takes its one ground by itself
        self.assertEqual(note["body"]["target"], {"action": "lock", "target": "issue:3", "rule": "ROOMS.md"})
        f = self.cact("correct", "freeze_key", "--login", "carol", "--reason", str(self.reason), day=2)   # the same reason
        d = self.cdraft("withdraw-correction", str(f["seq"]), day=3)
        self.assertEqual((d["entry"]["type"], d["entry"]["body"]), ("correction_withdraw", {"seq": f["seq"]}))
        self.capprove(d["digest"])
        self.reload()
        st = self.state()
        self.assertEqual(st.correction_status(st.corrections[f["seq"]], st.time), "withdrawn")
        r = self.om("withdraw-correction", str(f["seq"]), env=self.cenv(), day=4, code=1)
        self.assertIn("WOULD BE REFUSED", r.stdout)
        self.assertEqual(govern.missing_reasons(st, self.tmp, since=0), ([], []))

    def test_a_master_objects(self):
        f = self.cact("correct", "freeze_key", "--login", "carol", "--reason", str(self.reason), day=1)
        d = self.draft("object", str(f["seq"]), who="ada", day=2)
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"], d["entry"]["body"]),
                         ("correction_object", "ada", {"seq": f["seq"]}))
        self.approve(d["digest"], who="ada")
        self.reload()
        st = self.state()
        self.assertEqual(st.correction_status(st.corrections[f["seq"]], st.time), "void")     # one of one who may object
        r = self.om("object", str(f["seq"]), env=self.env("hiram"), day=3, code=1)
        self.assertIn("WOULD BE REFUSED", r.stdout)

    def test_the_ballot_that_removes_a_custodian_opens_like_any_other(self):
        r = self.om("open", "custodian", "warden", env=self.env("hiram"), day=1, code=1)
        self.assertIn("WOULD BE REFUSED", r.stdout)
        self.assertIn("is the member of the custodian warden", r.stdout)
        d = self.draft("open", "custodian", "warden", "--id", "rm", who="ada", day=1)
        self.assertEqual(d["entry"]["body"], {"id": "rm", "kind": "custodian", "subject": {"remove": "warden"}})
        self.assertIn("remove the custodian key of warden", d["summary"])
        self.approve(d["digest"], who="ada")
        self.reload()
        self.assertEqual(self.state().ballots["rm"].electors, frozenset({"ada", "carol"}))
        vote = self.draft("vote", "rm", who="carol", day=2)       # voting is the existing command
        self.assertEqual(vote["entry"]["type"], "ballot_commit")


class Noticed(Lodge):
    founders = SEVEN
    custodians = (("warden", "gus"), ("keeper", "fay"))
    threshold = 2

    def test_a_noticed_act_is_posted_co_signed_and_applied_after_its_notice(self):
        self.chain("ballot_open", "ada", {"id": "s", "kind": "sanction", "subject": {"member": "carol", "measure": "admonish"}}, 0)
        v = self.cact("correct", "void_ballot", "--ballot", "s", "--ground", "identity_fraud", "--reason", str(self.reason), day=1)
        self.assertEqual(v["body"]["target"], {"id": "s"})
        n = v["seq"]
        r = self.om("cosign-correction", str(n), env=self.cenv("warden"), day=2, code=1)
        self.assertIn("warden already signed correction", r.stdout)
        d = self.cdraft("cosign-correction", str(n), name="keeper", day=2)
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"], d["entry"]["body"]), ("correction_cosign", "keeper", {"seq": n}))
        self.capprove(d["digest"], name="keeper")
        self.reload()
        r = self.om("corrections", "--json", env=self.env("ada"), day=3, code=0)
        rep = json.loads(r.stdout)
        (row,) = rep["corrections"]
        self.assertEqual((rep["schema"], rep["custodian_threshold"]), ("om.corrections/1", 2))
        self.assertEqual((row["status"], row["signers"], row["signers_needed"], row["notice_until"], row["apply_until"]),
                         ("pending", ["warden", "keeper"], 2, self.T(15), self.T(22)))
        r = self.om("apply-correction", str(n), env=self.cenv("warden"), day=10, code=1)
        self.assertIn("WOULD BE REFUSED", r.stdout)
        self.assertIn("under notice until", r.stdout)
        d = self.cdraft("apply-correction", str(n), day=16)
        self.assertEqual((d["entry"]["type"], d["entry"]["body"]), ("correction_apply", {"seq": n}))
        self.capprove(d["digest"])
        self.reload()
        self.assertEqual(self.state().ballots["s"].result, "voided")


# ---------------------------------------------------------------- 4: a lost or stolen key ----

class Recovery(Lodge):
    def new_key(self, who="ada", name="new") -> Path:
        path = Path(self.env(who)["OM_HOME"]) / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(path)], check=True)
        return path

    def test_a_recovery_from_the_request_to_the_new_key(self):
        path = self.new_key()
        old, new = self.c.key("ada"), bare(path)
        # A recovery never needs a custodian: without the freeze below it would be an open one, with three
        # co-signers (tests.test_liveness). Here it follows the freeze.
        self.cact("correct", "freeze_key", "--login", "ada", "--reason", str(self.reason), day=1)
        d = self.draft("recover", "--new-key", str(path), who="ada", day=2)
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"]), ("rekey_recover", "ada"))
        self.assertEqual(d["entry"]["body"], {"key": new, "proof": actions.REKEY_PROOF_PENDING})
        self.assertIn(actions.fingerprint(new), d["summary"])
        self.approve(d["digest"], who="ada")
        signed = self.reload()
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], new))       # the NEW key signs
        self.assertTrue(crypto.signature_valid(ledger.rekey_message("ada", old, new), signed["body"]["proof"], new))
        for who in ("hiram", "carol"):
            d = self.draft("recover-cosign", "ada", who=who, day=3)
            self.assertEqual((d["entry"]["type"], d["entry"]["body"]), ("rekey_cosign", {"login": "ada"}))
            self.approve(d["digest"], who=who)
            self.reload()
        r = self.om("recover-apply", env=self.env("ada"), day=10, code=1)
        self.assertIn("under notice until", r.stdout)
        d = self.draft("recover-apply", who="ada", day=24)         # the new key is remembered from the request
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"], d["entry"]["body"]), ("rekey_recover_apply", "ada", {}))
        self.approve(d["digest"], who="ada")
        signed = self.reload()
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], new))
        self.assertEqual(self.state().members["ada"].key, new)
        config = json.loads((Path(self.env("ada")["OM_HOME"]) / "config.json").read_text())
        self.assertEqual(config["key"], str(path))                 # this machine signs with the new key from now on
        self.assertNotIn("recovery_key", config)

    def test_the_old_key_stops_a_recovery(self):
        path = self.new_key()
        self.cact("correct", "freeze_key", "--login", "ada", "--reason", str(self.reason), day=1)
        self.act("recover", "--new-key", str(path), who="ada", day=2)
        d = self.draft("recover-object", who="ada", day=3)         # signed with the key the ledger holds
        self.assertEqual((d["entry"]["type"], d["entry"]["actor"], d["entry"]["body"]), ("rekey_object", "ada", {}))
        self.approve(d["digest"], who="ada")
        signed = self.reload()
        self.assertTrue(crypto.signature_valid(signed_payload(signed), signed["sig"], self.c.key("ada")))
        st = self.state()
        self.assertEqual(st.recovery_status(st.recoveries["ada"], st.time), "objected")

    def test_a_recovery_is_only_of_a_member_and_needs_its_new_key(self):
        self.c.key("alice")
        r = self.om("recover", "--new-key", str(self.new_key("alice")), env=self.env("alice"), day=1, code=1)
        self.assertIn("alice is not a member", r.stdout)
        r = self.om("recover-apply", env=self.env("carol"), day=1, code=1)
        self.assertIn("--new-key", r.stdout)


# ---------------------------------------------------------------- 5: reads ----

class Reads(Lodge):
    def test_om_corrections_lists_everything_about_them(self):
        f = self.cact("correct", "freeze_key", "--login", "carol", "--reason", str(self.reason), day=1)["seq"]
        rep = json.loads(self.om("corrections", "--json", env=self.env("ada"), day=2, code=0).stdout)
        self.assertEqual((rep["schema"], rep["entries"], rep["time"]), ("om.corrections/1", 2, self.T(2)))
        self.assertEqual(rep["custodians"], [{"name": "warden", "member": "hiram", "status": "live",
                                              "last_alive": self.T(0), "silence_deadline": self.T(180),
                                              "removal_ballot": None, "ended_at": None}])
        self.assertEqual(rep["halt"], {"halted": False, "correction": None, "since": None, "until": None})
        self.assertEqual(rep["corrections"], [{
            "seq": f, "by": "warden", "act": "freeze_key", "class": "immediate", "target": {"login": "carol"},
            "ground": "key_compromised", "reason_sha256": REASON_SHA, "reason_file": f"ledger/reasons/{REASON_SHA}.md",
            "time": self.T(1), "status": "active", "ends": self.T(31), "signers": [], "signers_needed": None,
            "notice_until": None, "apply_until": None, "applied": None, "objections": [], "objections_needed": 1,
            "objection_until": self.T(91)}])
        self.assertEqual(rep["recoveries"], [])
        text = self.om("corrections", env=self.env("ada"), day=2, code=0).stdout
        for part in ("custodian warden", "freeze_key", "carol", "key_compromised", REASON_SHA[:12], "objections 0 of 1",
                     self.T(31)):
            self.assertIn(part, text)
        quiet = self.om("state", env=self.env("ada"), day=2, code=0).stdout
        self.assertIn("Custodians and corrections", quiet)
        self.assertIn("custodian warden", quiet)
        self.assertIn(f"correction {f}", quiet)

    def test_a_ledger_without_custodians_says_so(self):
        tmp = tmpdir(self)
        c = Chain(tmp)
        c.add("genesis", "hiram", genesis_body(c))
        (tmp / "led").mkdir()
        entry_file(tmp / "led", 0).write_text(json.dumps(c.entries[0]))
        r = self.run_om("corrections", "--ledger", str(tmp / "led"), env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no custodian", r.stdout.lower())
        self.assertNotIn("Custodians and corrections", self.run_om("state", "--ledger", str(tmp / "led"), env=self.env()).stdout)

    def test_the_report_counts_who_may_still_object(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN, custodian_threshold=2)
        sanction(c, "s", member="carol")
        v = void(c, "s", days=1)
        cosign(c, v, "keeper")
        objection(c, v, "dan", days=1)
        (row,) = corrections_report(c.state(), c.now)["corrections"]
        # Seven Masters; the subject (carol) and the members of both signers (gus, fay) never object: 4, so 1.
        self.assertEqual((row["objections"], row["objections_needed"], row["status"]), (["dan"], 1, "void"))
        f = freeze(c, "ada", days=1)
        row = next(r for r in corrections_report(c.state(), c.now)["corrections"] if r["seq"] == f)
        self.assertEqual((row["objections_needed"], row["objection_until"]), (1, iso(c.now + 90 * DAY)))
        n = correct(c, "note", {"action": "lock", "target": "issue:3", "rule": "ROOMS.md"})
        row = next(r for r in corrections_report(c.state(), c.now)["corrections"] if r["seq"] == n)
        self.assertEqual((row["objections_needed"], row["objection_until"]), (None, None))


# ---------------------------------------------------------------- 6: the Guide ----

class GuideNotices(unittest.TestCase):
    """The Guide states what exists and what the person may do. It never proposes an objection, a recovery
    co-signature or the removal of a custodian."""

    def kinds(self, c, who, at=None):
        return [n.kind for n in notices(c.state(), who, at or c.now)]

    def steps(self, c, who, at=None):
        return [s.action for s in next_steps(c.state(), who, at or c.now)]

    def test_a_halt_is_a_notice_for_everyone(self):
        c = lodge()
        h = halt(c, days=1)
        for who in ("ada", "hiram", "stranger"):
            (n,) = notices(c.state(), who, c.now)
            self.assertEqual((n.kind, n.correction, n.until), ("halt", h, iso(T0 + 15 * DAY)))
            self.assertIn("halted", n.why)
        (n,) = notices(c.state(), "ada", c.now)
        self.assertTrue(n.may_object)                            # a Master Builder may; it is stated, not proposed
        self.assertEqual(n.object_until, iso(T0 + 91 * DAY))
        self.assertIn("bin/om object", n.why)
        self.assertFalse(notices(c.state(), "hiram", c.now)[0].may_object)       # the custodian's own member
        self.assertNotIn("bin/om object", notices(c.state(), "stranger", c.now)[0].why)
        self.assertEqual(self.kinds(c, "ada", T0 + 16 * DAY), [])                 # it ended by itself

    def test_a_frozen_member_reads_their_freeze_and_gets_only_what_it_allows(self):
        c = lodge()
        sanction(c, "s", member="carol", by="hiram")
        commit(c, "s", "ada")
        f = freeze(c, "ada", days=6)
        (n,) = notices(c.state(), "ada", c.now)
        self.assertEqual((n.kind, n.correction, n.until, n.concerns_you, n.may_object),
                         ("frozen", f, iso(T0 + 36 * DAY), True, False))
        for part in ("key_compromised", "bin/om rekey", "bin/om recover"):
            self.assertIn(part, n.why)
        self.assertEqual(self.steps(c, "ada"), ["wait", "depart"])
        open_ballot(c, "rm", "carol", "custodian", {"remove": "warden"})
        steps = next_steps(c.state(), "ada", c.now)
        self.assertEqual([s.action for s in steps], ["wait", "vote", "depart"])   # the removal ballot is still theirs
        self.assertEqual(steps[1].argv, ["bin/om", "vote", "rm"])
        self.assertIn("removal of the custodian key of warden", steps[1].why)
        (other,) = notices(c.state(), "carol", c.now)             # another Master: may object, and is told so
        self.assertEqual((other.kind, other.correction, other.concerns_you, other.may_object), ("correction", f, False, True))
        self.assertIn("1 objection", other.why)

    def test_a_hold_and_a_correction_on_ones_own_ballot_concern_the_member(self):
        c = lodge()
        sanction(c, "s", member="carol")
        hold = correct(c, "hold_room", {"login": "carol"}, "identity_fraud", days=1)
        stay = correct(c, "stay", {"ballot": "s"})
        found = {n.correction: n for n in notices(c.state(), "carol", c.now)}
        self.assertEqual((found[hold].kind, found[hold].until, found[hold].may_object),
                         ("room_hold", iso(T0 + 15 * DAY), False))
        self.assertEqual((found[stay].kind, found[stay].concerns_you, found[stay].may_object), ("correction", True, False))
        self.assertIn("cannot object", found[stay].why)
        objection(c, hold, "ada")                                 # void now: nothing is left to tell
        self.assertNotIn(hold, [n.correction for n in notices(c.state(), "carol", c.now)])
        mine = {n.correction: n for n in notices(c.state(), "ada", c.now)}
        self.assertEqual(set(mine), {stay})
        objection(c, stay, "ada")
        self.assertEqual(notices(c.state(), "ada", c.now), [])

    def test_a_noticed_act_is_told_with_its_dates(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN)
        sanction(c, "s", member="carol")
        v = void(c, "s", days=1)
        (n,) = notices(c.state(), "dan", c.now)
        self.assertEqual((n.kind, n.correction, n.until, n.may_object), ("correction", v, iso(T0 + 15 * DAY), True))
        self.assertIn(iso(T0 + 22 * DAY), n.why)
        self.assertIn("under notice", n.why)
        self.assertEqual(self.kinds(c, "gus"), [])                # the member of the custodian who posted it
        (ready,) = notices(c.state(), "dan", T0 + 16 * DAY)       # past its notice: what is left is the time to apply it
        self.assertEqual((ready.until, ready.may_object), (iso(T0 + 22 * DAY), True))
        self.assertIn("has passed its notice", ready.why)
        self.assertEqual(self.kinds(c, "dan", T0 + 23 * DAY), [])  # expired: nothing is in force or under notice
        # The ballot is paused while the voiding is pending: no vote is taken and it is not closed.
        steps = {s.action: s for s in next_steps(c.state(), "ada", T0 + 11 * DAY)}
        self.assertNotIn("close", steps)
        self.assertNotIn("vote", steps)
        self.assertIn(f"correction {v}", steps["wait"].why)
        self.assertIn("vote", [s.action for s in next_steps(c.state(), "ada", T0 + 23 * DAY)])     # it went its way again
        objection(c, v, "dan")
        self.assertEqual(self.kinds(c, "dan"), [])                # void: one objection of the five who may was enough

    def test_ones_own_recovery_is_stated_from_both_sides(self):
        c = lodge()
        f = freeze(c, "ada", days=1)
        c.add("rekey_recover", "ada", {"key": c.key("ada-new"), "proof": c.key("ada-new")}, key_of="ada-new", days=1)
        found = {n.kind: n for n in notices(c.state(), "ada", c.now)}
        self.assertEqual(set(found), {"frozen", "recovery"})
        r = found["recovery"]
        self.assertEqual((r.until, r.concerns_you), (iso(c.now + 60 * DAY), True))
        for part in ("0 of the 2", "bin/om recover-apply", "bin/om recover-object", iso(c.now + 21 * DAY)):
            self.assertIn(part, r.why)
        self.assertEqual(found["frozen"].correction, f)
        self.assertEqual(self.kinds(c, "carol"), ["correction", "recovery_cosign"])   # stated, never a step
        self.assertNotIn("recover", notices(c.state(), "carol", c.now)[0].why)

    def test_no_notice_and_no_step_ever_advises(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN)
        sanction(c, "s", member="carol")
        void(c, "s", days=1)
        freeze(c, "ada")
        c.add("rekey_recover", "ada", {"key": c.key("ada-new"), "proof": c.key("ada-new")}, key_of="ada-new")
        halt(c)
        open_ballot(c, "rm", "dan", "custodian", {"remove": "keeper"})
        st = c.state()
        for who in (*SEVEN, "stranger"):
            for n in notices(st, who, c.now):
                self.assertNotRegex(n.why, ADVICE, who)
            actions_ = [s.action for s in next_steps(st, who, c.now)]
            for never in ("object", "recover_cosign", "open_custodian", "correct", "cosign_correction"):
                self.assertNotIn(never, actions_, who)
        self.assertIn("vote", [s.action for s in next_steps(st, "eve", c.now)])    # halted, and still an elector
        self.assertNotIn("vote", [s.action for s in next_steps(st, "fay", c.now)])  # keeper's own member is no elector

    def test_the_removal_ballot_is_voted_revealed_and_closed_like_any_other(self):
        c = lodge()
        open_ballot(c, "rm", "ada", "custodian", {"remove": "warden"})
        self.assertIn("vote", self.steps(c, "carol"))
        self.assertNotIn("vote", self.steps(c, "hiram"))
        commit(c, "rm", "carol")
        self.assertIn("reveal", self.steps(c, "carol", T0 + 7 * DAY + ledger.REVEAL_GAP + SEC))
        self.assertIn("close", self.steps(c, "ada", T0 + 11 * DAY))


class GuideForCustodians(unittest.TestCase):
    def test_a_sign_of_life_is_due_in_the_last_thirty_days(self):
        c = lodge()
        st = c.state()
        self.assertEqual(custodian_steps(st, "warden", T0 + 150 * DAY), [])
        (s,) = custodian_steps(st, "warden", T0 + 150 * DAY + SEC)
        self.assertEqual((s.action, s.argv, s.due_by, s.public),
                         ("alive", ["bin/om", "alive", "--as", "warden"], iso(T0 + 180 * DAY), True))
        self.assertEqual(custodian_steps(st, "warden", T0 + 181 * DAY), [])       # lapsed: it signs nothing more
        self.assertEqual(custodian_steps(st, "nobody", T0), [])

    def test_a_ready_correction_of_theirs_is_theirs_to_apply_and_nothing_else_is_offered(self):
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN, custodian_threshold=2)
        sanction(c, "s", member="carol")
        v = void(c, "s", days=1)
        freeze(c, "ada")
        st = c.state()
        self.assertEqual(custodian_steps(st, "keeper", c.now), [])               # never: co-sign this, withdraw that
        self.assertEqual(custodian_steps(st, "warden", T0 + 16 * DAY), [])       # ready, but one signature of two
        cosign(c, v, "keeper", days=1)
        st = c.state()
        self.assertEqual(custodian_steps(st, "warden", T0 + 14 * DAY), [])       # under notice
        for name in ("warden", "keeper"):
            (s,) = custodian_steps(st, name, T0 + 16 * DAY)
            self.assertEqual((s.action, s.argv, s.due_by),
                             ("apply_correction", ["bin/om", "apply-correction", str(v), "--as", name], iso(T0 + 22 * DAY)))
        self.assertEqual(custodian_steps(st, "warden", T0 + 23 * DAY), [])       # expired
        apply_(c, v, days=15)
        self.assertEqual(custodian_steps(c.state(), "warden", c.now), [])

    def test_the_report_of_om_me_carries_notices_and_the_custodian(self):
        c = lodge()
        freeze(c, "ada", days=1)
        rep = actions.me_report(c.state(), "carol", c.now)
        json.dumps(rep)
        self.assertEqual((rep["schema"], rep["custodian"]), ("om.me/2", None))
        (n,) = rep["notices"]
        self.assertEqual(sorted(n), ["concerns_you", "correction", "kind", "may_object", "object_until", "until", "why"])
        late = T0 + 170 * DAY
        rep = actions.me_report(c.state(), "hiram", late, custodian="warden")
        self.assertEqual(rep["custodian"], {"name": "warden", "member": "hiram", "status": "live", "last_alive": iso(T0),
                                            "silence_deadline": iso(T0 + 180 * DAY)})
        plain = actions.me_report(c.state(), "hiram", late)["steps"]
        self.assertEqual(rep["steps"][:len(plain)], plain)       # the member's own steps stay, and one is added
        self.assertEqual([s["action"] for s in rep["steps"][len(plain):]], ["alive"])
        unknown = actions.me_report(c.state(), "hiram", late, custodian="nobody")
        self.assertEqual(unknown["custodian"]["status"], "unknown")
        self.assertNotIn("alive", [s["action"] for s in unknown["steps"]])


class MeCommand(Lodge):
    def test_om_me_shows_notices_and_knows_a_custodian_by_flag_or_environment(self):
        self.cact("correct", "freeze_key", "--login", "carol", "--reason", str(self.reason), day=1)
        me = json.loads(self.om("me", "--json", env=self.env("ada"), day=2, code=0).stdout)
        self.assertEqual((me["schema"], me["custodian"]), ("om.me/2", None))
        self.assertEqual([(n["kind"], n["may_object"]) for n in me["notices"]], [("correction", True)])
        text = self.om("me", env=self.env("carol"), day=2, code=0).stdout
        self.assertIn("Your key is frozen until", text)
        by_flag = json.loads(self.om("me", "--json", "--as", "warden", env=self.env("hiram"), day=170, code=0).stdout)
        self.assertEqual(by_flag["custodian"]["name"], "warden")
        self.assertIn(["bin/om", "alive", "--as", "warden"], [s["argv"] for s in by_flag["steps"]])
        by_env = json.loads(self.om("me", "--json", env=self.env("hiram") | {"OM_CUSTODIAN": "warden"}, day=170,
                                    code=0).stdout)
        self.assertEqual(by_env["custodian"], by_flag["custodian"])


if __name__ == "__main__":
    unittest.main()
