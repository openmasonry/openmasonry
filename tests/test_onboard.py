"""The door: `om onboard`, `om apply`, the Guide's steps for an outsider, and the fixes on the candidate's path
(the approval dialog on macOS and Windows, the fork, a failed push, a renamed account, the clock, doctor).

Every program goes through a seam the tests replace (`onboard._run`, `actions.subprocess.run`); nothing here
touches the network or a real GitHub account. Only the OpenSSH check runs the real `ssh-keygen`, on a throwaway
key in a temporary directory, and is skipped when OpenSSH is missing.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

from openmasonry import actions, canon, guide, onboard
from openmasonry.ledger import iso, ts
from tests.test_guide import tmpdir
from tests.test_protocol import entry_file, founded, gid, invite

NOW = "2027-01-01T00:00:00Z"
CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("OM_KEY", "OM_LOGIN", "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "OM_CUSTODIAN")}


def done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class FakeRun:
    """The programs of this machine, as a table: the first rule whose text is in the command line answers."""

    def __init__(self, login="dora", gid_=5, listing="", agent="", apps="[]", scopes="admin:public_key, repo",
                 clock_skew=0.0, gh_ok=True):
        self.calls: list[list[str]] = []
        now = actions.now_utc() - timedelta(seconds=clock_skew)
        self.rules = [
            ("git --version", done(0, "git version 2.45.1\n")),
            ("config --get user.name", done(0, f"{login}\n")),
            ("config --get user.email", done(0, f"{gid_}+{login}@users.noreply.github.com\n")),
            ("config --get commit.gpgsign", done(1)),
            ("credential.https://github.com.helper", done(0, "!/usr/bin/gh auth git-credential\n")),
            ("diff --cached --quiet", done(0)), ("status --porcelain", done(0, "")),
            ("ssh -V", done(0, "", "OpenSSH_9.7p1, LibreSSL 3.3.6\n")),
            ("ssh-keygen -q -Y sign", self.sign), ("ssh-keygen -q -t ed25519", done(0)),
            ("gh --version", done(0, "gh version 2.60.1 (2024-10-01)\n")),
            ("gh api user --jq", done(0, f"{login} {gid_}\n") if gh_ok else done(1, "", "not logged in")),
            ("gh api -i user", done(0, f"HTTP/2.0 200 OK\nX-Oauth-Scopes: {scopes}\n\n{{}}") if gh_ok else done(1)),
            ("curl -sSI", done(0, f"HTTP/2 200\ndate: {format_datetime(now, usegmt=True)}\n\n")),
            (".keys", done(0, listing)), ("ssh-add -L", done(0 if agent else 1, agent)),
            ("launchctl managername", done(0, "Aqua\n")),
            ("gh issue list", done(0, apps)), ("gh issue create", done(0, "https://github.com/openmasonry/openmasonry/issues/42\n")),
            ("gh ssh-key add", done(0)),
        ]

    @staticmethod
    def sign(argv):
        Path(argv[-1] + ".sig").write_text("sig")
        return done(0)

    def __call__(self, argv, capture=True, **kw):
        self.calls.append(list(argv))
        self.capture = capture
        line = " ".join(argv)
        for text, answer in self.rules:
            if text in line:
                return answer(argv) if callable(answer) else answer
        return done(127, "", f"{argv[0]}: not found")

    def ran(self, text: str) -> list[list[str]]:
        return [c for c in self.calls if text in " ".join(c)]


class Door(unittest.TestCase):
    """A scratch ledger founded by hiram, ada and carol; a person `dora` with a key of her own."""

    def setUp(self):
        self.tmp = tmpdir(self)
        self.c = founded(self.tmp)
        self.led = self.tmp / "led"
        self.write()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.c.key("dora")
        self.key = self.home / "dora"
        shutil.copy2(self.c.keys["dora"][0], self.key)
        shutil.copy2(f"{self.c.keys['dora'][0]}.pub", f"{self.key}.pub")
        os.chmod(self.key, 0o600)
        self.blob = self.c.key("dora").split()[1]
        for p in (mock.patch.dict(os.environ, CLEAN_ENV, clear=True),
                  mock.patch.object(actions, "CONFIG", self.home / "config.json"),
                  mock.patch.object(onboard, "check_clone", lambda: onboard.check("clone", "ok", "a clone")),
                  mock.patch.object(onboard.shutil, "which", lambda name, *x, **k: f"/usr/bin/{name}"),
                  mock.patch.object(onboard, "UPLOAD_POLL", (2, 0))):
            p.start()
            self.addCleanup(p.stop)

    def write(self):
        self.led.mkdir(exist_ok=True)
        for e in self.c.entries:
            if not (f := entry_file(self.led, e["seq"])).exists():
                f.write_text(json.dumps(e))

    def args(self, **kw):
        base = dict(ledger=self.led, login=None, key=str(self.key), json=True, create_key=None, hardware=False,
                    use_key=None, upload=False, time=None, text=None, check=False, web=False)
        return argparse.Namespace(**(base | kw))

    def onboard(self, fake: FakeRun, repo=False, **kw) -> tuple[int, dict]:
        out = io.StringIO()
        with mock.patch.object(onboard, "_run", fake), contextlib.redirect_stdout(out), \
                mock.patch.object(actions, "is_repo_ledger", lambda led: repo), \
                mock.patch.object(actions, "canonical_status", lambda known=(): ("in_sync", "ledger in sync")):
            code = onboard.cmd_onboard(self.args(**kw))
        return code, json.loads(out.getvalue()) if kw.get("json", True) else out.getvalue()


class OnboardStages(Door):
    def test_every_check_is_reported_in_order_and_a_second_run_changes_nothing(self):
        fake = FakeRun(listing=f"ssh-ed25519 {self.blob}\n", agent=f"ssh-ed25519 {self.blob}\n")
        code, rep = self.onboard(fake, repo=True)
        self.assertEqual(rep["schema"], "om.onboard/1")
        self.assertEqual([c["id"] for c in rep["checks"]], list(onboard.ORDER))
        self.assertEqual({c["id"]: c["status"] for c in rep["checks"] if c["status"] != "ok"}, {})
        self.assertEqual((code, rep["stage"], rep["next"]["argv"]), (0, "not_applied", []))
        self.assertEqual((rep["login"], rep["github_id"], rep["key"]["listed"], rep["key"]["in_agent"]), ("dora", 5, True, True))
        self.assertTrue(rep["application_checked"])
        again = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n", agent=f"ssh-ed25519 {self.blob}\n"), repo=True)[1]
        self.assertEqual((again["checks"], again["changed"]), (rep["checks"], []))
        self.assertTrue(all(isinstance(c["fix"]["argv"], list) for c in rep["checks"] if c["fix"]))

    def test_the_stage_follows_the_first_thing_missing(self):
        code, rep = self.onboard(FakeRun(gh_ok=False))
        self.assertEqual((code, rep["stage"], rep["next"]["argv"], rep["next"]["person"]), (1, "login", onboard.LOGIN_COMMAND, True))
        self.assertEqual(rep["checks"][onboard.ORDER.index("account")]["status"], "skip")
        code, rep = self.onboard(FakeRun(), key=str(self.home / "absent"))
        self.assertEqual((rep["stage"], rep["next"]["argv"], rep["next"]["person"]), ("no_key", [onboard.OM, "onboard", "--create-key"], True))
        code, rep = self.onboard(FakeRun(listing="ssh-ed25519 AAAAother\n"))
        self.assertEqual((rep["stage"], rep["next"]["argv"], rep["next"]["public"]), ("key_not_on_github", [onboard.OM, "onboard", "--upload"], True))
        apps = json.dumps([{"number": 7, "url": "https://github.com/openmasonry/openmasonry/issues/7", "state": "OPEN",
                            "createdAt": "2027-01-01T00:00:00Z", "title": "Application: @dora"}])
        rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n", apps=apps), repo=True)[1]
        self.assertEqual((rep["stage"], rep["application"]["number"], rep["next"]["argv"]), ("applied", 7, []))
        invite(self.c, "dora", "hiram")
        self.write()
        rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n"))[1]
        self.assertEqual((rep["stage"], rep["next"]["argv"], rep["invitation"]["by"]), ("invited", [onboard.OM, "join"], "hiram"))
        self.assertEqual(rep["next"]["due_by"], rep["invitation"]["expires_at"])

    def test_offline_checks_are_skipped_never_failed(self):
        fake = FakeRun()
        fake.rules = [r for r in fake.rules if r[0] not in (".keys", "curl -sSI")]
        code, rep = self.onboard(fake)
        statuses = {c["id"]: c["status"] for c in rep["checks"]}
        self.assertEqual((statuses["key_listed"], statuses["clock"]), ("skip", "skip"))
        self.assertIsNone(rep["key"]["listed"])

    def test_a_token_in_the_environment_a_fast_clock_and_a_personal_email_are_named(self):
        fake = FakeRun(clock_skew=200)
        fake.rules.insert(0, ("config --get user.email", done(0, "dora@example.org\n")))
        with mock.patch.dict(os.environ, {"GH_TOKEN": "x"}):
            rep = self.onboard(fake)[1]
        statuses = {c["id"]: c for c in rep["checks"]}
        self.assertEqual(statuses["gh_token_env"]["status"], "warn")
        self.assertEqual(statuses["clock"]["status"], "fail")
        self.assertIn("ahead of GitHub's", statuses["clock"]["message"])
        self.assertEqual(statuses["git_identity"]["status"], "warn")
        self.assertIn("5+dora@users.noreply.github.com", statuses["git_identity"]["fix"]["text"])

    def test_a_key_the_ledger_holds_for_another_login_is_refused(self):
        shutil.copy2(f"{self.c.keys['ada'][0]}.pub", f"{self.key}.pub")
        rep = self.onboard(FakeRun())[1]
        c = next(x for x in rep["checks"] if x["id"] == "key_ledger")
        self.assertEqual(c["status"], "fail")
        self.assertIn("already used by the member ada", c["message"])
        self.assertEqual(rep["stage"], "no_key")


class OnboardKeys(Door):
    def test_create_key_never_overwrites_and_never_runs_without_a_terminal(self):
        with self.assertRaises(actions.UserError) as err:
            self.onboard(FakeRun(), create_key=str(self.key))
        self.assertIn("om never overwrites a key", str(err.exception))
        fake = FakeRun()
        with mock.patch.object(onboard, "interactive", lambda: False), contextlib.redirect_stderr(io.StringIO()) as err:
            code, text = self.onboard(fake, create_key=str(self.home / "new"), json=False)
        self.assertEqual(code, 1)
        self.assertIn("no terminal to ask for a passphrase", err.getvalue())
        self.assertIn(f"ssh-keygen -t ed25519 -C openmasonry -f {self.home / 'new'}", err.getvalue())
        self.assertEqual(fake.ran("-f " + str(self.home / "new")), [])
        self.assertFalse((self.home / "config.json").exists())

    def test_create_key_runs_ssh_keygen_in_the_terminal_with_no_passphrase_flag(self):
        new = self.home / "new"

        def keygen(argv):
            self.assertFalse(fake.capture)                    # the person's terminal, never a pipe
            self.assertNotIn("-N", argv)
            shutil.copy2(self.c.keys["carol"][0], new)
            shutil.copy2(f"{self.c.keys['carol'][0]}.pub", f"{new}.pub")
            return done(0)
        fake = FakeRun()
        fake.rules.insert(0, ("-C openmasonry -f", keygen))
        with mock.patch.object(onboard, "interactive", lambda: True), contextlib.redirect_stderr(io.StringIO()):
            code, rep = self.onboard(fake, create_key=str(new))
        self.assertEqual(rep["changed"], ["key_created", "config_written"])
        self.assertEqual(json.loads((self.home / "config.json").read_text()), {"key": str(new)})

    def test_use_key_records_the_key_only_for_a_person_who_is_not_a_member(self):
        rep = self.onboard(FakeRun(), use_key=str(self.key) + ".pub")[1]
        self.assertEqual(json.loads((self.home / "config.json").read_text()), {"key": str(self.key)})
        self.assertIn("config_written", rep["changed"])
        self.assertEqual(self.onboard(FakeRun(), use_key=str(self.key))[1]["changed"], [])     # idempotent
        with self.assertRaises(actions.UserError) as err:
            self.onboard(FakeRun(login="ada", gid_=2), use_key=str(self.key))
        self.assertIn("om onboard never changes your key", str(err.exception))
        self.assertNotIn("previous_key", json.loads((self.home / "config.json").read_text()))

    def test_upload_asks_first_and_adds_an_authentication_key(self):
        fake = FakeRun(listing="")
        with mock.patch.object(actions, "_ask", return_value=None), contextlib.redirect_stderr(io.StringIO()) as err:
            code, text = self.onboard(fake, upload=True, json=False)
        self.assertEqual(code, 1)
        self.assertIn("Canceled. Nothing was uploaded.", err.getvalue())
        self.assertEqual(fake.ran("gh ssh-key add"), [])
        fake = FakeRun(listing="")
        listings = iter(["", f"ssh-ed25519 {self.blob}\n", f"ssh-ed25519 {self.blob}\n"])
        fake.rules.insert(0, (".keys", lambda argv: done(0, next(listings, f"ssh-ed25519 {self.blob}\n"))))
        asked = []
        with mock.patch.object(actions, "_ask", lambda title, text, *x, **k: asked.append(text) or "Add the key"), \
                contextlib.redirect_stderr(io.StringIO()):
            code, rep = self.onboard(fake, upload=True)
        self.assertEqual(fake.ran("gh ssh-key add"), [["gh", "ssh-key", "add", f"{self.key}.pub", "--type", "authentication",
                                                       "--title", "OpenMasonry"]])
        self.assertIn("as an authentication key", asked[0])
        self.assertIn("https://github.com/dora.keys", asked[0])
        self.assertIn("key_uploaded", rep["changed"])

    def test_a_missing_key_scope_is_named_before_any_dialog(self):
        with mock.patch.object(actions, "_ask", side_effect=AssertionError("no dialog")), \
                self.assertRaises(actions.UserError) as err:
            self.onboard(FakeRun(scopes="repo"), upload=True)
        self.assertIn("gh auth refresh --hostname github.com --scopes admin:public_key", str(err.exception))


@unittest.skipUnless(shutil.which("ssh-keygen"), "OpenSSH is not installed")
class RealOpenSSH(unittest.TestCase):
    def test_ssh_keygen_signs_a_throwaway_message(self):
        self.assertEqual(onboard.openssh()["status"], "ok")


class Apply(Door):
    TEXT = "I build tools for public records and would like to learn the Craft.\nI write in my free time.\n"

    def apply(self, text=TEXT, fake=None, answer="Publish my application", **kw):
        (self.tmp / "app.txt").write_text(text, encoding="utf-8")
        fake = fake or FakeRun()
        out = io.StringIO()
        asked = []
        with mock.patch.object(onboard, "_run", fake), contextlib.redirect_stdout(out), \
                mock.patch.object(actions, "_ask", lambda title, text, *x, **k: asked.append((text, k)) or answer):
            code = onboard.cmd_apply(self.args(login="dora", text=str(self.tmp / "app.txt"), **kw))
        return code, json.loads(out.getvalue()), fake, asked

    def test_personal_data_and_mentions_are_refused_with_their_line(self):
        cases = {"mail me at dora@example.org": "e-mail address", "call +1 (555) 123-4567 any time": "phone number",
                 "hello\n@hiram knows me": "line 2: the application mentions @hiram", "x" * 1201: "keep it under 1200",
                 "bell \x07": "control character"}
        for text, why in cases.items():
            code, rep, fake, asked = self.apply(text)
            self.assertEqual((code, rep["status"]), (1, "refused"), text)
            self.assertIn(why, rep["refused"])
            self.assertEqual((fake.ran("gh issue create"), asked), ([], []))
        self.assertEqual(onboard.application_problems("I am @dora, hello.", "dora"), [])
        self.assertEqual(onboard.application_problems("Since 2019 I have built 12 tools.", "dora"), [])

    def test_check_prints_the_exact_body_and_asks_nothing(self):
        code, rep, fake, asked = self.apply(check=True)
        self.assertEqual((code, rep["status"], rep["title"], asked), (0, "checked", "Application: @dora", []))
        self.assertEqual(fake.calls, [])

    def test_the_body_states_what_the_form_states(self):
        body = onboard.application_body("hello")
        statements = onboard.form_statements()
        self.assertEqual(len(statements), 3)
        for s in statements:
            self.assertIn(f"- [X] {s}", body)
        self.assertIn("I am an adult", statements[0])

    def test_publishing_asks_then_opens_the_issue_from_a_private_file_removed_afterwards(self):
        seen = []
        fake = FakeRun()
        fake.rules.insert(0, ("gh issue create", lambda argv: seen.append(Path(argv[argv.index("--body-file") + 1]).read_text())
                              or done(0, "https://github.com/openmasonry/openmasonry/issues/42\n")))
        code, rep, fake, asked = self.apply(fake=fake)
        self.assertEqual((code, rep["status"], rep["issue"]["number"]), (0, "published", 42))
        (call,) = fake.ran("gh issue create")
        self.assertEqual(call[call.index("--title") + 1], "Application: @dora")
        self.assertFalse(Path(call[call.index("--body-file") + 1]).exists())
        self.assertIn(self.TEXT.strip(), seen[0])
        self.assertIn("This opens a PUBLIC issue", asked[0][0])
        self.assertIn(self.TEXT.strip(), asked[0][0])
        self.assertEqual(asked[0][1]["limit"], 3000)

    def test_cancel_publishes_nothing_and_an_open_application_is_refused(self):
        code, rep, fake, asked = self.apply(answer=None)
        self.assertEqual((code, rep["status"], fake.ran("gh issue create")), (1, "canceled", []))
        apps = json.dumps([{"number": 7, "url": "https://github.com/openmasonry/openmasonry/issues/7", "state": "OPEN",
                            "createdAt": "2027-01-01T00:00:00Z", "title": "Application: @dora"}])
        code, rep, fake, asked = self.apply(fake=FakeRun(apps=apps))
        self.assertEqual((code, rep["status"], asked), (1, "refused", []))
        self.assertIn("you already have an open application", rep["refused"])

    def test_a_member_and_an_invited_person_have_nothing_to_apply_for(self):
        (self.tmp / "app.txt").write_text(self.TEXT)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(onboard.cmd_apply(self.args(login="ada", text=str(self.tmp / "app.txt"))), 1)
        self.assertIn("ada is a member already", json.loads(out.getvalue())["refused"])
        invite(self.c, "dora", "hiram")
        self.write()
        code, rep, fake, asked = self.apply()
        self.assertIn("dora is invited already (by hiram", rep["refused"])
        self.assertIn("bin/om join", rep["refused"])


class GuideAtTheDoor(Door):
    def test_the_steps_of_an_outsider_by_stage(self):
        st = self.c.state()
        base = guide.next_steps(st, "dora", st.time)
        steps = guide.onboarding_steps(base, {"key": {"path": "/k", "fingerprint": None}, "application_checked": True}, "dora")
        self.assertEqual([s.action for s in steps], ["setup", "apply"])
        self.assertEqual((steps[0].argv, steps[0].public), ([guide.OM, "onboard", "--create-key"], False))
        self.assertEqual((steps[1].argv, steps[1].needs, steps[1].public), ([guide.OM, "apply", "--text"], ["FILE"], True))
        steps = guide.onboarding_steps(base, {"key": {"fingerprint": "SHA256:x", "listed": False}, "application_checked": False}, "dora")
        self.assertEqual(steps[0].argv, [guide.OM, "onboard", "--upload"])
        self.assertTrue(steps[1].why.startswith("Could not check GitHub for an earlier application of yours. "))
        app = {"url": "https://github.com/openmasonry/openmasonry/issues/7", "created_at": "2027-01-01T00:00:00Z"}
        steps = guide.onboarding_steps(base, {"key": {"fingerprint": "SHA256:x", "listed": True}, "application": app}, "dora")
        self.assertEqual([s.action for s in steps], ["wait"])
        self.assertIn("An application gives no right to an invitation", steps[0].why)
        invite(self.c, "dora", "hiram")
        st = self.c.state()
        steps = guide.onboarding_steps(guide.next_steps(st, "dora", st.time),
                                       {"key": {"fingerprint": "SHA256:x", "listed": False}}, "dora")
        self.assertEqual([s.action for s in steps], ["setup", "join"])
        self.assertTrue(steps[1].why.startswith("Invited by hiram — join before "))
        self.assertIn("Your invitation lapses at", steps[0].why)

    def test_om_me_adds_onboarding_only_for_an_outsider_and_asks_github_only_about_the_repository_ledger(self):
        st = self.c.state()
        self.assertIsNone(actions.me_report(st, "ada", st.time)["onboarding"])
        a = self.args()
        with mock.patch.object(onboard, "_run", side_effect=AssertionError("no program for a scratch ledger")):
            info = onboard.onboarding_info(a, st, "dora", st.time)
        self.assertEqual((info["stage"], info["application_checked"], info["key"]["listed"]), ("not_applied", False, None))
        rep = actions.me_report(st, "dora", st.time, onboarding=info)
        self.assertEqual(rep["onboarding"]["stage"], "not_applied")
        self.assertEqual([s["action"] for s in rep["steps"]], ["apply"])
        self.assertFalse(rep["steps"][0]["why"].startswith("Could not check"))

    def test_no_step_at_the_door_is_an_objection_a_cosignature_a_removal_or_a_correction(self):
        st = self.c.state()
        for info in ({"key": {}}, {"key": {"fingerprint": "f", "listed": False}}, {"key": {"fingerprint": "f"}, "application": {"url": "u"}}):
            for s in guide.onboarding_steps(guide.next_steps(st, "dora", st.time), info, "dora"):
                self.assertNotRegex(" ".join(s.argv), r"object|cosign|custodian|correct|oppose")
                self.assertNotRegex(s.why, r"(?i)\b(should|recommend|suggest|advise|ought)")


# ---------------------------------------------------------------- the fixes on the candidate's path ----

class Dialogs(unittest.TestCase):
    def ask(self, platform, run, which=lambda name, *x, **k: f"/usr/bin/{name}", tty=None):
        opener = tty or mock.Mock(side_effect=OSError("no tty"))
        with mock.patch.object(actions.sys, "platform", platform), mock.patch.object(actions.shutil, "which", which), \
                mock.patch.object(actions.subprocess, "run", run), mock.patch("builtins.open", opener), \
                mock.patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
            return actions._ask("T", "text", ["Approve and sign"], None)

    def test_on_macos_only_cancel_is_cancel(self):
        self.assertIsNone(self.ask("darwin", lambda *a, **k: done(1, "", "execution error: User canceled. (-128)")))
        with self.assertRaises(actions.UserError):          # no desktop session: the terminal, and here there is none
            self.ask("darwin", lambda *a, **k: done(1, "", "execution error: No user interaction allowed. (-1713)"))
        written = []
        handle = mock.MagicMock()
        handle.__enter__.return_value = handle
        handle.write.side_effect = written.append
        handle.readline.side_effect = lambda: written[0].split("Type one of: ")[1].split(" (anything")[0] + "\n"
        tty = mock.Mock(return_value=handle)
        self.assertEqual(self.ask("darwin", lambda *a, **k: done(1, "", "(-1713)"), tty=tty), "Approve and sign")

    def test_native_windows_asks_in_a_dialog_then_in_the_console(self):
        seen = {}

        def ps(argv, **kw):
            seen.update(argv=argv, env=kw["env"])
            return done(0, "Approve and sign")
        self.assertEqual(self.ask("win32", ps), "Approve and sign")
        self.assertIn("System.Windows.Forms", seen["argv"][-1])
        self.assertEqual((seen["env"]["OM_DIALOG_TITLE"], seen["env"]["OM_DIALOG_TEXT"]), ("T", "text"))
        self.assertEqual(seen["env"]["OM_DIALOG_BUTTONS"].split("\n"), ["Cancel", "Approve and sign"])
        self.assertIsNone(self.ask("win32", lambda *a, **k: done(0, "")))      # closed or Cancel
        console = []

        def conin(name, *a, **k):
            console.append(name)
            f = mock.MagicMock()
            f.__enter__.return_value = f
            f.readline.return_value = "nope\n"
            return f
        self.assertIsNone(self.ask("win32", lambda *a, **k: done(1, "", "no desktop"), tty=conin))
        self.assertEqual(console, ["CONIN$", "CONOUT$"])

    def test_the_windows_launcher_finds_py_or_python(self):
        text = (canon.ROOT / "bin" / "om.cmd").read_bytes()
        self.assertIn(b"\r\n", text)
        for part in (b"py -3 -m openmasonry %*", b"python -m openmasonry %*", b"OM_PYTHON", b"version_info >= (3, 11)"):
            self.assertIn(part, text)
        self.assertIn("bin/om.cmd text eol=crlf", (canon.ROOT / ".gitattributes").read_text())


class Forks(unittest.TestCase):
    def gh(self, answers):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            line = " ".join(argv)
            return next((done(0, out) for text, out in answers if text in line), done(1, "", "no"))
        return run, calls

    def test_the_fork_is_found_by_its_parent_and_a_non_fork_is_never_used(self):
        run, calls = self.gh([(".permissions.push", "false"), ("repos/dora/openmasonry --jq", ""),
                              ("forks?per_page", "dora/openmasonry-1\n"), ("repos/dora/openmasonry-1 --jq", "openmasonry/openmasonry\n")])
        remotes = "upstream\thttps://github.com/openmasonry/openmasonry.git (fetch)\nfork\thttps://github.com/dora/openmasonry.git (fetch)\n"
        git = []
        with mock.patch.object(actions.subprocess, "run", run), \
                mock.patch.object(actions, "_git", lambda *a: git.append(a) or done(0, remotes if a[0] == "remote" and a[1] == "-v" else "")):
            self.assertEqual(actions._push_target("upstream", "dora"), ("fork-2", "dora"))
        self.assertIn(("remote", "add", "fork-2", "https://github.com/dora/openmasonry-1.git"), git)
        run, calls = self.gh([(".permissions.push", "false"), ("forks?per_page", ""), ("repo fork", "")])
        with mock.patch.object(actions.subprocess, "run", run), mock.patch.object(actions, "_git", lambda *a: done(0, "")), \
                mock.patch("time.sleep"), self.assertRaises(actions.UserError) as err:
            actions._push_target("upstream", "dora")
        self.assertIn("pending --publish", str(err.exception))
        self.assertTrue(any(c[:3] == ["gh", "repo", "fork"] for c in calls))

    def test_the_fork_owner_is_the_active_account_and_the_body_says_the_judge_merges(self):
        entry = {"type": "petition", "actor": "dora-old", "seq": 9}
        with mock.patch.object(actions, "detect_login", lambda x: "dora"):
            self.assertEqual(actions._publish_login(entry, None), "dora")
        self.assertIn("it merges itself when the judge passes", actions.PR_BODY)
        self.assertNotIn("maintainer", actions.PR_BODY)

    def test_a_failed_push_keeps_the_branch_and_says_how_to_publish_again(self):
        git = []

        def fake_git(*a, **k):
            git.append(a)
            if a[0] == "push":
                return done(1, "", "fatal: could not read Username")
            if a[0] == "rev-parse" and "--verify" in a:
                return done(1)
            return done(0, "main\n")
        root = Path(actions.canon.ROOT)
        with mock.patch.object(actions, "_git", fake_git), \
                mock.patch.object(actions, "_push_target", lambda r, l, seq=None: ("fork", "dora")), \
                mock.patch.object(onboard, "gh_user", lambda: ("dora", 5)), \
                self.assertRaises(actions.UserError) as err:
            actions._submit([root / "README.md"], {"type": "petition", "actor": "dora", "seq": 9}, "upstream", "dora")
        self.assertIn("bin/om pending --publish 9", str(err.exception))
        self.assertIn(("switch", "main"), git)                          # back where the person was
        self.assertFalse(any(a[:2] == ("branch", "-D") for a in git))


class Resumable(Door):
    def test_publish_pushes_the_branch_of_the_first_attempt_and_opens_the_pull_request(self):
        entry = {"type": "work", "actor": "ada", "seq": 4, "time": iso(actions.now_utc()), "body": {"ref": "https://x"}}
        ada = f"ada <{gid('ada')}+ada@users.noreply.github.com>"
        made = f"{ada}\0" "1794528000 +0000\0" f"{ada}\0" "1794528000 +0000\n"    # a founder's kept branch is read back
        git, gh = [], []
        out = io.StringIO()
        with mock.patch.object(actions, "is_repo_ledger", lambda led: True), \
                mock.patch.object(actions, "_require_in_sync", lambda known=(): "upstream"), \
                mock.patch.object(actions, "_ask", return_value="Publish"), \
                mock.patch.object(actions, "_push_target", lambda r, l, seq=None: ("fork", "ada")), \
                mock.patch.object(actions, "detect_login", lambda x: "ada"), \
                mock.patch.object(onboard, "gh_user", lambda: ("ada", gid("ada"))), \
                mock.patch.object(actions, "_git", lambda *a, **k: git.append(a) or done(0, made if a[0] == "log" else "")), \
                mock.patch.object(actions, "_gh", lambda *a: gh.append(a) or done(0, "https://github.com/o/r/pull/9\n"
                                                                           if a[:2] == ("pr", "create") else "")), \
                contextlib.redirect_stdout(out):
            code = actions.publish_pending(argparse.Namespace(ledger=self.led, json=False), self.c.state(), entry)
        self.assertEqual(code, 0)
        self.assertIn(("push", "--force-with-lease=refs/heads/om/ada/000004:", "-u", "fork", "om/ada/000004"), git)
        self.assertTrue(any(a[:2] == ("pr", "create") and "ada:om/ada/000004" in a for a in gh))
        self.assertIn("pull/9", out.getvalue())

    def test_drafting_on_another_history_than_the_canonical_ledger_is_refused(self):
        other = founded(tmpdir(self))                    # another genesis: the same founders, other keys
        with mock.patch.object(actions, "is_repo_ledger", lambda led: True), \
                mock.patch.object(actions, "canonical_guard", lambda known=(), **k: ("ok", "")), \
                mock.patch.object(actions, "canonical_ledger", lambda: other.entries), \
                mock.patch.object(actions, "canonical_remote", lambda: "upstream"), \
                self.assertRaises(actions.UserError) as err:
            actions._require_canonical(self.c.state(), self.led)
        self.assertIn("follows another history than the canonical ledger (entry 0 differs)", str(err.exception))
        with mock.patch.object(actions, "is_repo_ledger", lambda led: True), \
                mock.patch.object(actions, "canonical_guard", lambda known=(), **k: ("ok", "")), \
                mock.patch.object(actions, "canonical_ledger", lambda: self.c.entries[:-1]):
            actions._require_canonical(self.c.state(), self.led)         # behind is not another history


class RenamedAndClock(Door):
    def test_a_renamed_account_joins_under_the_login_of_its_invitation(self):
        invite(self.c, "dora-old", "hiram")
        self.write()
        st = self.c.state()
        with mock.patch.object(onboard, "_run", FakeRun(login="dora", gid_=gid("dora-old"))):
            self.assertEqual(actions.invitation_by_id(st, st.time), "dora-old")
        with mock.patch.object(onboard, "_run", FakeRun(login="dora", gid_=1)):
            self.assertIsNone(actions.invitation_by_id(st, st.time))

    def test_approval_refuses_an_entry_stamped_ahead_of_githubs_clock(self):
        entry = {"time": iso(actions.now_utc())}
        with mock.patch.object(onboard, "_run", FakeRun(clock_skew=150)), self.assertRaises(actions.UserError) as err:
            actions.clock_gate(entry)
        self.assertIn("ahead of GitHub's clock", str(err.exception))
        with mock.patch.object(onboard, "_run", FakeRun(clock_skew=5)):
            actions.clock_gate(entry)
        fake = FakeRun()
        fake.rules = [r for r in fake.rules if r[0] != "curl -sSI"]
        with mock.patch.object(onboard, "_run", fake):
            actions.clock_gate({"time": iso(actions.now_utc() + timedelta(minutes=30))})     # offline: no verdict

    def test_publishing_needs_the_account_and_credentials_before_anything_is_signed(self):
        fake = FakeRun(gh_ok=False)
        with mock.patch.object(onboard, "_run", fake), self.assertRaises(actions.UserError) as err:
            actions.publish_preflight()
        self.assertIn("nothing was signed", str(err.exception))
        fake = FakeRun()
        fake.rules.insert(0, ("config --get user", done(1)))      # no git identity: om commits as the account anyway
        with mock.patch.object(onboard, "_run", fake), contextlib.redirect_stderr(io.StringIO()) as note:
            actions.publish_preflight()
        self.assertIn("5+dora@users.noreply.github.com", note.getvalue())
        fake = FakeRun()
        fake.rules.insert(0, ("credential", done(1)))
        with mock.patch.object(onboard, "_run", fake), self.assertRaises(actions.UserError) as err:
            actions.publish_preflight()
        self.assertIn("gh auth setup-git", str(err.exception))

    def test_a_token_in_the_environment_is_named_once(self):
        err = io.StringIO()
        actions._TOKEN_WARNED.clear()
        with mock.patch.dict(os.environ, {"GH_TOKEN": "x"}), mock.patch.object(actions.shutil, "which", lambda n: "/x"), \
                mock.patch.object(actions.subprocess, "run", return_value=done(0, "dora\n")), contextlib.redirect_stderr(err):
            self.assertEqual(actions.detect_login(None), "dora")
            actions.detect_login(None)
        self.assertEqual(err.getvalue().count("GH_TOKEN is set"), 1)


class Doctor(Door):
    def doctor(self, run, which=lambda name, *x, **k: None if name == "curl" else f"/usr/bin/{name}"):
        out = io.StringIO()
        a = argparse.Namespace(login="dora", key=str(self.key), ledger=self.led)
        with mock.patch.object(actions.shutil, "which", which), mock.patch.object(actions.subprocess, "run", run), \
                mock.patch.object(onboard, "doctor_checks", return_value=[]), contextlib.redirect_stdout(out):
            code = actions.cmd_doctor(a)
        return code, out.getvalue()

    def test_offline_never_says_add_the_key_and_missing_tools_never_crash(self):
        code, text = self.doctor(lambda argv, **kw: done(6, "", "Could not resolve host") if argv[0] == "curl" else done(1),
                                 which=lambda name, *x, **k: f"/usr/bin/{name}")
        self.assertIn("· could not read https://github.com/dora.keys", text)
        self.assertNotIn("onboard --upload", text)
        code, text = self.doctor(lambda argv, **kw: done(1), which=lambda name, *x, **k: None if name in ("curl", "ssh-add") else "/x")
        self.assertIn("· curl not found", text)
        self.assertIn("· ssh-add not found", text)
        code, text = self.doctor(lambda argv, **kw: done(0, "ssh-ed25519 AAAAother\n") if argv[0] == "curl" else done(1),
                                 which=lambda name, *x, **k: "/x")
        self.assertIn("✘ the key is not listed at https://github.com/dora.keys: bin/om onboard --upload", text)


if __name__ == "__main__":
    unittest.main()
