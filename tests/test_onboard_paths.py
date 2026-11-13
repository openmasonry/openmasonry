"""The candidate's path, end to end where it can be: the typed code on a real pseudo-terminal, the git identity
fix, a publish that fails before its branch exists, two drafts for one place in the ledger, a petitioner's own
key, a machine without git, and the commands printed on Windows.

Nothing here touches the network, a real GitHub account or a browser: programs go through the seams the tests
replace, and the few subprocesses run with a PATH of stubs and a temporary HOME.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from openmasonry import actions, canon, guide, onboard
from openmasonry.ledger import drand_round, iso
from tests.test_guide import tmpdir
from tests.test_onboard import Door, FakeRun, done
from tests.test_protocol import DECL, founded, gid, initiate, invite, petition

SRC = str(Path(__file__).resolve().parents[1] / "src")


def on_a_pty(code: str, answer=None, timeout: float = 20.0) -> str:
    """Run `code` in a child Python whose controlling terminal is a new pseudo-terminal; `answer(seen)` returns
    what the person types once the text seen so far asks for it (or None to keep reading). Returns all output."""
    import pty
    env = {"PATH": os.environ.get("PATH", ""), "HOME": tempfile.gettempdir(), "PYTHONPATH": SRC,
           "OM_HOME": tempfile.mkdtemp(), "TERM": "dumb"}
    pid, fd = pty.fork()
    if pid == 0:                                   # the child: exec at once, nothing else in the forked image
        os.execve(sys.executable, [sys.executable, "-c", code], env)
    seen, typed, deadline = b"", False, time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:                    # the child closed the terminal
                    break
                if not chunk:
                    break
                seen += chunk
            if answer and not typed:
                text = answer(seen.decode(errors="replace"))
                if text is not None:
                    os.write(fd, text.encode())
                    typed = True
            if b"DONE" in seen:
                break
    finally:
        os.close(fd)
        os.waitpid(pid, 0)
    return seen.decode(errors="replace")


CHILD = """
import os, sys
from openmasonry import actions, onboard
sys.platform = "linux"                      # no dialog program: only the terminal is left
os.environ.pop("DISPLAY", None); os.environ.pop("WAYLAND_DISPLAY", None)
print("CHANNEL", onboard.dialog_channel(), onboard.interactive(), onboard.check_platform()["status"], flush=True)
print("CHOICE", actions._ask("OpenMasonry: approve this act?", "a test act", ["Approve and sign"], None), flush=True)
print("DONE", flush=True)
"""


@unittest.skipIf(sys.platform == "win32" or not hasattr(os, "openpty"), "needs a POSIX pseudo-terminal")
class TypedCodeOnATerminal(unittest.TestCase):
    def test_the_terminal_fallback_asks_and_reads_the_typed_code(self):
        def answer(seen):
            m = re.search(r"Type one of: (approve and sign-[0-9a-f]{4})", seen)
            return m.group(1) + "\n" if m else None
        out = on_a_pty(CHILD, answer)
        self.assertIn("CHANNEL terminal True ok", out)
        self.assertIn("CHOICE Approve and sign", out)

    def test_anything_else_typed_cancels(self):
        out = on_a_pty(CHILD, lambda seen: "approve and sign-zzzz\n" if "Type one of:" in seen else None)
        self.assertIn("CHOICE None", out)

    def test_the_key_is_created_only_where_the_person_can_type_its_passphrase(self):
        code = ("import sys\nfrom openmasonry import onboard\nprint('INTERACTIVE', onboard.interactive(), flush=True)\n"
                "print('DONE', flush=True)\n")
        self.assertIn("INTERACTIVE True", on_a_pty(code))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env={**os.environ, "PYTHONPATH": SRC}, start_new_session=True)
        self.assertIn("INTERACTIVE False", r.stdout)


class GitConfig:
    """A git that keeps user.name and user.email in a dict, for the fix commands to change."""

    def __init__(self, **config):
        self.config = dict(config)

    def __call__(self, argv, capture=True, **kw):
        if argv[-2:-1] == ["--get"] or (len(argv) >= 2 and argv[-2] == "--get"):
            v = self.config.get(argv[-1])
            return done(0, v + "\n") if v else done(1)
        if "config" in argv and argv[-2] in ("user.name", "user.email"):
            self.config[argv[-2]] = argv[-1]
            return done(0)
        return done(1)


class GitIdentity(unittest.TestCase):
    def test_running_the_fix_until_it_passes_sets_the_name_and_the_email_and_ends(self):
        git = GitConfig()
        with mock.patch.object(onboard, "_run", git):
            for _ in range(3):
                c = onboard.git_identity("dora", 5)
                if c["status"] == "ok":
                    break
                self.assertEqual(c["fix"]["kind"], "command")
                git(c["fix"]["argv"])
        self.assertEqual(c["status"], "ok")
        self.assertEqual(git.config, {"user.name": "dora", "user.email": "5+dora@users.noreply.github.com"})

    def test_without_the_account_the_fix_is_words_never_a_command_with_a_placeholder(self):
        with mock.patch.object(onboard, "_run", GitConfig()):
            c = onboard.git_identity(None, None)
        self.assertEqual((c["status"], c["fix"]["kind"], c["fix"]["argv"]), ("fail", "read", []))


class Stages(Door):
    def no_identity(self, **kw) -> FakeRun:
        fake = FakeRun(**kw)
        fake.rules = [r for r in fake.rules if "config --get user" not in r[0]]
        fake.rules.insert(0, ("config --get user", done(1)))
        return fake

    def test_the_login_comes_before_the_git_identity_and_no_command_holds_a_placeholder(self):
        rep = self.onboard(self.no_identity(gh_ok=False))[1]
        self.assertEqual((rep["stage"], rep["next"]["argv"]), ("login", onboard.LOGIN_COMMAND))
        self.assertNotIn("ID+LOGIN", json.dumps([c["fix"]["argv"] for c in rep["checks"] if c["fix"]]))
        rep = self.onboard(self.no_identity())[1]
        self.assertEqual((rep["stage"], rep["next"]["argv"][-3:]), ("tools", ["config", "user.name", "dora"]))

    def test_a_token_without_the_repo_scope_is_a_login_step(self):
        rep = self.onboard(FakeRun(scopes="gist", listing=f"ssh-ed25519 {self.blob}\n"))[1]
        self.assertEqual((rep["stage"], rep["next"]["argv"]), ("login", onboard.LOGIN_COMMAND))

    def test_a_closed_application_lets_the_person_apply_again(self):
        apps = json.dumps([{"number": 7, "url": "https://github.com/openmasonry/openmasonry/issues/7", "state": "CLOSED",
                            "createdAt": "2027-01-01T00:00:00Z", "title": "Application: @dora"}])
        rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n", apps=apps), repo=True)[1]
        self.assertEqual((rep["stage"], rep["next"]["action"]), ("not_applied", "apply"))
        st = self.c.state()
        app = {"url": "u", "created_at": "2027-01-01T00:00:00Z", "state": "closed"}
        steps = guide.onboarding_steps(guide.next_steps(st, "dora", st.time),
                                       {"key": {"fingerprint": "f", "listed": True}, "application": app}, "dora")
        self.assertEqual([s.action for s in steps], ["apply"])

    def test_a_petitioner_s_own_key_is_never_a_key_used_before(self):
        petition(self.c, "dora")
        self.write()
        rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n"))[1]
        key = next(c for c in rep["checks"] if c["id"] == "key_ledger")
        self.assertEqual(key["status"], "ok")
        self.assertFalse(any(c["status"] == "fail" for c in rep["checks"]))

    def test_without_git_nothing_crashes_and_the_fix_installs_git(self):
        fake = FakeRun()
        fake.rules = [r for r in fake.rules if not r[0].startswith(("git ", "config", "credential", "diff", "status"))]
        code, rep = self.onboard(fake, repo=True)
        checks = {c["id"]: c for c in rep["checks"]}
        self.assertEqual((code, rep["stage"], rep["next"]["text"]), (1, "tools", onboard.INSTALL["git"]))
        self.assertEqual(checks["ledger"]["status"], "skip")

    def test_the_fix_of_a_ledger_that_is_not_in_sync_does_not_repeat_its_message(self):
        with mock.patch.object(onboard, "_run", FakeRun()), \
                mock.patch.object(actions, "is_repo_ledger", lambda led: True), \
                mock.patch.object(actions, "canonical_status", lambda known=(): ("behind", "your clone is 1 entry behind")):
            rep = onboard.Report()
            onboard.ledger_checks(self.args(), rep)
        c = rep.checks["ledger"]
        self.assertEqual(c["status"], "fail")
        self.assertNotEqual(c["fix"]["text"], c["message"])

    def test_a_key_on_another_account_is_named_from_the_second_line_of_gh_s_error(self):
        fake = FakeRun(listing="ssh-ed25519 AAAAother\n")
        fake.rules.insert(0, ("gh ssh-key add", done(1, "", "HTTP 422: Validation Failed (https://api.github.com/user/keys)\n"
                                                    "key is already in use\n")))
        with mock.patch.object(actions, "_ask", lambda *a, **k: "Add the key"), self.assertRaises(actions.UserError) as err:
            self.onboard(fake, upload=True)
        self.assertIn("it is on another GitHub account already", str(err.exception))

    def test_a_plain_count_is_not_a_phone_number(self):
        self.assertEqual(onboard.application_problems("I have read 123456789 lines of code.", "dora"), [])
        self.assertTrue(onboard.application_problems("call +1 (555) 123-4567", "dora"))


class OpenSSHFloor(unittest.TestCase):
    def check(self, version: str) -> dict:
        fake = FakeRun()
        fake.rules.insert(0, ("ssh -V", done(0, "", version)))
        with mock.patch.object(onboard, "_run", fake), mock.patch.object(onboard.shutil, "which", lambda n: "/x"):
            return onboard.openssh()

    def test_the_openssh_of_windows_10_is_enough_and_older_ones_are_refused(self):
        self.assertEqual(self.check("OpenSSH_for_Windows_8.1p1, LibreSSL 3.0.2\n")["status"], "ok")
        old = self.check("OpenSSH_for_Windows_7.7p1, LibreSSL 2.6.5\n")
        self.assertEqual((old["status"], old["message"]), ("fail", "OpenSSH 7.7 is too old (8.1 or later)"))


REAL_RUN = subprocess.run


def only_openssh(argv, *a, **k):
    """OpenSSH signs for real (a throwaway key); gh, git and curl answer that they failed."""
    return REAL_RUN(argv, *a, **k) if argv[0] in ("ssh-keygen", "ssh-add") else done(1)


class Outbox(unittest.TestCase):
    """A scratch ledger standing in for the repository's own (`is_repo_ledger`), with git and GitHub replaced."""

    def setUp(self):
        self.tmp = tmpdir(self)
        self.c = founded(self.tmp)
        self.led = self.tmp / "ledger" / "entries"
        self.write()
        home = self.tmp / "home"
        patches = [mock.patch.object(actions, n, home / f) for n, f in
                   (("HOME", ""), ("PENDING", "pending"), ("VAULT", "vault.json"), ("CONFIG", "config.json"),
                    ("HEADS", "heads.json"))]
        patches += [mock.patch.object(canon, "ROOT", self.tmp),
                    mock.patch.object(actions, "is_repo_ledger", lambda led: Path(led).resolve() == self.led.resolve()),
                    mock.patch.object(actions, "_require_canonical", lambda st, led: None),
                    mock.patch.object(actions, "_require_in_sync", lambda known=(): "upstream"),
                    mock.patch.object(actions, "publish_preflight", lambda: None),
                    mock.patch.object(actions, "clock_gate", lambda e: None),
                    mock.patch.object(actions, "_ask", lambda *a, **k: a[2][-1]),
                    mock.patch.object(actions.subprocess, "run", only_openssh),
                    mock.patch.object(onboard, "gh_user", lambda: ("ada", gid("ada"))),   # the founder's own account
                    mock.patch.dict(os.environ, {"OM_LOGIN": "ada"})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.home = home

    def write(self):
        from tests.test_protocol import entry_file
        self.led.mkdir(parents=True, exist_ok=True)
        for e in self.c.entries:
            if not (f := entry_file(self.led, e["seq"])).exists():
                f.write_text(json.dumps(e))

    def a(self, **kw):
        base = dict(ledger=self.led, login="ada", key=str(self.c.keys["ada"][0]), json=True, time=None, no_submit=False,
                    digest=None, rebase=None, publish=None, drop=None)
        return argparse.Namespace(**(base | kw))

    def draft(self, ref: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(actions.propose(self.a(), "work", {"ref": ref}, "Record a work"), actions.NEEDS_APPROVAL)
        return json.loads(out.getvalue())["digest"]

    def run_(self, fn, **kw) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fn(self.a(**kw))
        return code, out.getvalue()

    def test_a_publish_that_fails_before_its_branch_exists_keeps_the_entry_for_pending_publish(self):
        digest = self.draft("https://example.org/w1")

        def no_fork(*a, **k):
            raise actions.UserError("could not find your fork of openmasonry/openmasonry on GitHub")
        git = lambda *a: done(1)                    # no branch was made, and the entry file is not tracked
        with mock.patch.object(actions, "_push_target", no_fork), mock.patch.object(actions, "_git", git), \
                self.assertRaises(actions.UserError) as err:
            self.run_(actions.cmd_approve, digest=digest)
        seq = self.c.state().seq + 1
        self.assertIn(f"pending --publish {seq}", str(err.exception))
        self.assertEqual(list(self.led.rglob(f"{seq:06d}.json")), [])          # out of the working tree…
        code, out = self.run_(actions.cmd_pending)
        self.assertEqual([i["seq"] for i in json.loads(out)["pending"]], [seq])  # …and in the outbox
        with mock.patch.object(actions, "publish_pending", lambda a, st, e: e["seq"]):
            self.assertEqual(self.run_(actions.cmd_pending, publish=seq)[0], seq)
        self.assertEqual(os.stat(self.home / "outbox").st_mode & 0o777, 0o700)

    def test_a_second_draft_for_the_place_a_signed_entry_waits_for_is_stale(self):
        first, second = self.draft("https://example.org/w1"), self.draft("https://example.org/w2")
        signed = json.loads((actions.PENDING / f"{first}.json").read_text())["entry"]
        actions._keep_in_outbox(self.c.state(), signed)      # as approval leaves it while its pull request is open
        with self.assertRaises(actions.UserError) as err:
            self.run_(actions.cmd_approve, digest=second)
        self.assertIn(f"STALE — your signed entry #{signed['seq']} (work) is waiting", str(err.exception))
        self.assertTrue((actions.PENDING / f"{second}.json").exists())          # nothing was signed

    def test_a_signed_genesis_waiting_for_its_pull_request_is_listed(self):
        genesis = self.c.entries[0]
        shutil.rmtree(self.led)
        self.led.mkdir(parents=True)
        actions._keep_in_outbox(self.c.state(), genesis)
        code, out = self.run_(actions.cmd_pending)
        self.assertEqual(json.loads(out)["pending"][0]["seq"], 0)
        self.run_(actions.cmd_pending, drop=0)
        self.assertEqual(json.loads(self.run_(actions.cmd_pending)[1])["pending"], [])


class CouncilCall(unittest.TestCase):
    def setUp(self):
        self.c = founded(tmpdir(self))
        initiate(self.c, "dora")
        self.st = self.c.state()

    def steps(self, lapsed: bool):
        with mock.patch.object(guide, "_council_pool", lambda st, now: ["x"]), \
                mock.patch.object(guide, "council_lapsed", lambda st, now: lapsed):
            return [s.action for s in guide.next_steps(self.st, "dora", self.st.time)]

    def test_any_member_may_call_the_lot_and_a_lapsed_call_is_made_again_never_drawn(self):
        self.assertIn("call_council", self.steps(lapsed=False))              # a member of the 1st degree
        self.st.council_call = drand_round(self.st.time) - 10
        self.assertEqual((("draw" in self.steps(False)), ("call_council" in self.steps(False))), (True, False))
        self.assertEqual((("draw" in self.steps(True)), ("call_council" in self.steps(True))), (False, True))


class Windows(unittest.TestCase):
    def test_commands_are_quoted_for_cmd_and_powershell(self):
        argv = ["ssh-keygen", "-f", r"C:\Users\Dora Q\.ssh\openmasonry_ed25519"]
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(onboard.cmdline(argv), r'ssh-keygen -f "C:\Users\Dora Q\.ssh\openmasonry_ed25519"')
        self.assertEqual(onboard.cmdline(["a b"]), "'a b'")

    def test_machine_readable_commands_name_the_windows_launcher(self):
        code = ("import importlib, sys\nfrom openmasonry import actions, guide, onboard\nsys.platform = 'win32'\n"
                "for m in (onboard, guide, actions):\n    importlib.reload(m)\n"
                "print(actions.OM, guide.OM, onboard.OM, onboard.STAGE_NEXT['invited'][2][0])")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": SRC})
        self.assertEqual(r.stdout.split(), [r"bin\om.cmd"] * 4, r.stderr)

    def test_the_windows_launcher_writes_utf_8(self):
        text = (canon.ROOT / "bin" / "om.cmd").read_text()
        self.assertLess(text.index('set "PYTHONUTF8=1"'), text.index("-m openmasonry"))


@unittest.skipIf(sys.platform == "win32", "POSIX stubs")
class NoGit(unittest.TestCase):
    """`om doctor` as a person runs it, with no git on the PATH (stubs for the rest, no network)."""

    def doctor(self, key: Path, listing: str = "") -> subprocess.CompletedProcess:
        tmp = tmpdir(self)
        bin_ = tmp / "bin"
        bin_.mkdir()
        for tool in ("ssh", "ssh-keygen", "ssh-add"):
            if shutil.which(tool):
                (bin_ / tool).symlink_to(shutil.which(tool))
        (bin_ / "gh").write_text("#!/bin/sh\nexit 1\n")
        (bin_ / "curl").write_text(f"#!/bin/sh\nprintf '%s' '{listing}'\n")
        for f in ("gh", "curl"):
            os.chmod(bin_ / f, 0o755)
        env = {"PATH": str(bin_), "HOME": str(tmp), "OM_HOME": str(tmp / "om"), "OM_LOGIN": "dora", "PYTHONPATH": SRC}
        return subprocess.run([sys.executable, "-m", "openmasonry", "doctor", "--key", str(key)], capture_output=True,
                              text=True, env=env, cwd=tmp)

    @unittest.skipIf(shutil.which("ssh-keygen") is None, "needs OpenSSH")
    def test_doctor_says_install_git_and_never_crashes(self):
        tmp = tmpdir(self)
        rsa = tmp / "rsa"
        subprocess.run(["ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", "", "-f", str(rsa)], check=True)
        r = self.doctor(rsa)
        self.assertNotIn("unexpected error", r.stdout + r.stderr)
        self.assertIn("✘ git is not installed (install git", r.stdout)
        self.assertNotIn("onboard --upload", r.stdout)                         # an RSA key: listing is moot
        (tmp / "lone").write_text("not a key")
        self.assertIn(f"public key {tmp / 'lone'}.pub not found: ssh-keygen -y -f", self.doctor(tmp / "lone").stdout)



# ------------------------------------------------- a fresh machine, a harness without a terminal, the outbox ----

def no_helper(fake: FakeRun) -> FakeRun:
    """git with no credential helper at all (a fresh Debian or Ubuntu)."""
    fake.rules = [r for r in fake.rules if "credential" not in r[0]]
    return fake


class BeforeTheLogin(Door):
    def test_without_a_login_and_a_credential_helper_the_stage_is_login_and_nothing_runnable_fails(self):
        rep = self.onboard(no_helper(FakeRun(gh_ok=False)))[1]
        self.assertEqual((rep["stage"], rep["next"]["argv"]), ("login", onboard.LOGIN_COMMAND))
        creds = next(c for c in rep["checks"] if c["id"] == "git_credentials")
        self.assertEqual((creds["status"], creds["fix"]["kind"], creds["fix"]["argv"]), ("fail", "read", []))
        rep = self.onboard(no_helper(FakeRun(listing=f"ssh-ed25519 {self.blob}\n")))[1]
        self.assertEqual((rep["stage"], rep["next"]["argv"]), ("tools", ["gh", "auth", "setup-git"]))

    def test_gh_s_helper_is_recognized_in_every_form_it_is_written(self):
        for line in ("!/usr/bin/gh auth git-credential", "!gh auth git-credential",
                     "!'C:\\Program Files\\GitHub CLI\\gh.exe' auth git-credential",
                     '!"C:\\Program Files\\GitHub CLI\\gh.exe" auth git-credential'):
            fake = no_helper(FakeRun())
            fake.rules.insert(0, ("credential.https://github.com.helper", done(0, line + "\n")))
            with mock.patch.object(onboard, "_run", fake):
                self.assertEqual(onboard.git_credentials()["status"], "ok", line)


class Headless(Door):
    def test_a_linux_harness_without_a_terminal_is_a_warning_and_gets_the_real_stage(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.object(onboard.sys, "platform", "linux"), mock.patch.object(onboard, "tty_opens", lambda: False), \
                mock.patch.object(onboard, "is_wsl", lambda: False), mock.patch.dict(os.environ, env, clear=True):
            code, rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n"))
        plat = next(c for c in rep["checks"] if c["id"] == "platform")
        self.assertEqual((plat["status"], plat["fix"]["kind"]), ("warn", "read"))
        self.assertEqual((code, rep["stage"], rep["next"]["action"]), (0, "not_applied", "apply"))

    @unittest.skipIf(sys.platform == "win32", "POSIX sessions")
    def test_in_a_process_with_no_controlling_terminal_the_platform_only_warns(self):
        code = ("import os, sys\nfrom openmasonry import onboard\nsys.platform = 'linux'\n"
                "os.environ.pop('DISPLAY', None); os.environ.pop('WAYLAND_DISPLAY', None)\n"
                "print(onboard.check_platform()['status'])\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env={**os.environ, "PYTHONPATH": SRC}, start_new_session=True)
        self.assertEqual(r.stdout.strip(), "warn", r.stderr)


class SignedNotMerged(Door):
    """dora is invited and has signed her petition; it waits in the outbox, published or not."""

    def setUp(self):
        super().setUp()
        invite(self.c, "dora", "hiram")
        self.write()
        self.entry = self.c.add("petition", "dora", {"key": self.c.key("dora"), "declaration_sha256": DECL})
        self.c.entries.pop()                       # signed, not in the ledger
        om_home = self.tmp / "om"
        for p in (mock.patch.object(actions, "HOME", om_home), mock.patch.object(actions, "VAULT", om_home / "vault.json"),
                  mock.patch.object(actions, "is_repo_ledger", lambda led: Path(led) == self.led)):   # for `om me`
            p.start()
            self.addCleanup(p.stop)
        actions._keep_in_outbox(self.c.state(), self.entry)

    @contextlib.contextmanager
    def git(self, pushed: bool):
        """git as it answers for the entry's branch: pushed to the fork (its upstream), or never pushed (none).
        GitHub cannot be asked here, so git's answer stands."""
        def run(*a):
            if a[:2] == ("rev-parse", "--symbolic-full-name"):
                return done(0, f"refs/remotes/fork/{actions.entry_branch(self.entry)}\n") if pushed else done(128)
            return done(0, "origin\nfork\n") if a == ("remote",) else done(1)
        with mock.patch.object(actions, "_git", run), mock.patch.object(actions, "_gh", lambda *a: done(1, "", "offline")):
            yield

    def test_onboard_offers_to_publish_a_petition_that_never_reached_github(self):
        seq = str(self.entry["seq"])
        with self.git(pushed=False):
            rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n"), repo=True)[1]
        self.assertEqual((rep["stage"], rep["next"]["action"], rep["next"]["argv"], rep["next"]["public"]),
                         ("petitioned", "publish", [onboard.OM, "pending", "--publish", seq], True))
        with self.git(pushed=True):
            rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n"), repo=True)[1]
        self.assertEqual((rep["stage"], rep["next"]["action"], rep["next"]["argv"]),
                         ("petitioned", "wait", [onboard.OM, "pending"]))

    def test_while_the_pull_request_is_open_no_sponsor_is_told_to_open_the_ballot(self):
        later = iso(self.c.now + timedelta(days=31))   # one sponsor suffices by then: the ballot may follow the merge
        with self.git(pushed=True):
            text, rep = self.me(False, later), json.loads(self.me(True, later))
        self.assertNotIn("can now open", text)
        self.assertEqual([(s["action"], s["argv"]) for s in rep["steps"]], [("wait", [onboard.OM, "pending"])])
        self.assertIn("waits for its pull request to merge", rep["steps"][0]["why"])
        self.assertIn("can open your admission ballot", rep["steps"][0]["why"])
        self.c.entries.append(self.entry)              # merged
        self.write()
        with self.git(pushed=True):
            self.assertIn("one of your sponsors can now open your admission ballot", self.me(False, later))

    def me(self, as_json: bool, time: str | None = None) -> str:
        out = io.StringIO()
        a = argparse.Namespace(ledger=self.led, login="dora", key=str(self.key), json=as_json,
                               time=time or iso(self.c.now))
        with mock.patch.object(onboard, "_run", FakeRun(listing=f"ssh-ed25519 {self.blob}\n")), \
                mock.patch.object(actions, "canonical_guard", lambda known=(): ("in_sync", "")), \
                contextlib.redirect_stdout(out):
            actions.cmd_me(a)
        return out.getvalue()

    def test_me_says_not_published_yet_and_offers_only_the_publish_step(self):
        seq = self.entry["seq"]
        with self.git(pushed=False):
            text, rep = self.me(False), json.loads(self.me(True))
        self.assertIn(f"your petition #{seq} is signed but not published yet: {onboard.OM} pending --publish {seq}", text)
        self.assertNotIn("sponsor", text)
        self.assertEqual(rep["pending_prs"], [{"seq": seq, "type": "petition", "published": False}])
        self.assertEqual([(s["action"], s["argv"]) for s in rep["steps"]],
                         [("publish", [onboard.OM, "pending", "--publish", str(seq)])])
        with self.git(pushed=True):
            text, rep = self.me(False), json.loads(self.me(True))
        self.assertIn(f"your petition #{seq} is waiting for its pull request to merge", text)
        self.assertNotIn("publish", [s["action"] for s in rep["steps"]])


class Leftovers(Door):
    def test_the_apply_step_has_no_placeholder_in_a_runnable_command(self):
        rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n"), repo=True)[1]
        self.assertEqual((rep["stage"], rep["next"]["argv"]), ("not_applied", []))
        self.assertIn(f"{onboard.OM} apply --text FILE", rep["next"]["text"])
        for c in rep["checks"]:
            self.assertNotIn("FILE", (c["fix"] or {}).get("argv") or [])

    def test_before_genesis_nobody_is_told_to_apply(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        rep = self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n"), ledger=empty)[1]
        self.assertEqual((rep["next"]["action"], rep["next"]["argv"]), ("wait", []))
        self.assertIn("not been founded yet", rep["next"]["why"])
        self.assertIn("LAUNCH.md", rep["next"]["why"])

    def test_a_clock_behind_names_the_rule_for_a_clock_behind(self):
        c = next(x for x in self.onboard(FakeRun(clock_skew=-2000))[1]["checks"] if x["id"] == "clock")
        self.assertEqual(c["status"], "fail")
        self.assertIn("behind GitHub's", c["message"])
        self.assertIn("6 hours behind", c["message"])
        self.assertNotIn("ahead of its clock", c["message"])

    def test_a_petitioner_s_key_is_named_as_the_key_of_the_petition(self):
        petition(self.c, "dora")
        self.write()
        c = next(x for x in self.onboard(FakeRun(listing=f"ssh-ed25519 {self.blob}\n"))[1]["checks"] if x["id"] == "key_ledger")
        self.assertEqual(c["message"], "the ledger holds this key for your petition")


class QuotedCommands(Door):
    def test_doctor_quotes_the_paths_of_the_commands_it_prints(self):
        folder = self.tmp / "my keys"
        folder.mkdir()
        key = folder / "om key"
        shutil.copy2(self.key, key)
        out = io.StringIO()
        a = argparse.Namespace(login="dora", key=str(key), ledger=self.led)
        run = lambda argv, **kw: done(1)
        with mock.patch.object(actions.shutil, "which", lambda n, *x, **k: None if n == "curl" else f"/usr/bin/{n}"), \
                mock.patch.object(actions.subprocess, "run", run), mock.patch.object(onboard, "doctor_checks", return_value=[]), \
                contextlib.redirect_stdout(out):
            actions.cmd_doctor(a)
        self.assertIn(f"not found: ssh-keygen -y -f '{key}' > '{key}.pub'", out.getvalue())
        shutil.copy2(f"{self.key}.pub", f"{key}.pub")
        out = io.StringIO()
        with mock.patch.object(actions.shutil, "which", lambda n, *x, **k: None if n == "curl" else f"/usr/bin/{n}"), \
                mock.patch.object(actions.subprocess, "run", run), mock.patch.object(onboard, "doctor_checks", return_value=[]), \
                contextlib.redirect_stdout(out):
            actions.cmd_doctor(a)
        self.assertIn(f"(or: ssh-add '{key}')", out.getvalue())

    def test_the_ssh_add_tip_of_a_failed_signature_is_quoted(self):
        err = actions.SigningError("ssh-keygen could not sign: x. Tip: load the key once with `ssh-add /a b/k` and sign "
                                   "through the agent.")
        self.assertIn("`ssh-add '/a b/k'`", actions._tip(err))


class WindowsDialogFailure(unittest.TestCase):
    def test_a_dialog_that_cannot_open_exits_3_and_the_console_asks_instead(self):
        script = actions.WINDOWS_DIALOG
        self.assertLess(script.index("$ErrorActionPreference = 'Stop'"), script.index("Add-Type"))
        self.assertLess(script.index("try {"), script.index("Add-Type"))
        self.assertLess(script.index("ShowDialog()"), script.index("} catch { exit 3 }"))
        asked = []

        def conin(name, *a, **k):
            asked.append(name)
            f = mock.MagicMock()
            f.__enter__.return_value = f
            f.readline.return_value = "nope\n"
            return f
        with mock.patch.object(actions.shutil, "which", lambda n, *x, **k: f"C:/{n}.exe"), \
                mock.patch.object(actions.subprocess, "run", lambda *a, **k: done(3)), mock.patch("builtins.open", conin):
            self.assertIsNone(actions._ask_windows("T", "text", ["Approve and sign"]))
        self.assertEqual(asked, ["CONIN$", "CONOUT$"])


@unittest.skipIf(sys.platform == "win32" or shutil.which("ssh-keygen") is None, "needs OpenSSH on POSIX")
class PassphraseWithoutATerminal(unittest.TestCase):
    def key(self, passphrase: str) -> Path:
        k = tmpdir(self) / "k"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", passphrase, "-C", "test", "-f", str(k)], check=True,
                       stdin=subprocess.DEVNULL)
        return k

    def blocks(self, key: Path, tty: bool = False, agent: str = "") -> bool:
        with mock.patch.object(onboard, "tty_opens", lambda: tty), mock.patch.object(onboard, "agent_keys", lambda: agent):
            started = time.monotonic()
            answer = onboard.passphrase_blocks(key)
        self.assertLess(time.monotonic() - started, 15)
        return answer

    def test_a_protected_key_with_no_terminal_and_no_agent_is_named_at_once(self):
        protected = self.key("a passphrase nobody types")
        self.assertTrue(self.blocks(protected))
        self.assertFalse(self.blocks(protected, tty=True))
        self.assertFalse(self.blocks(protected, agent=Path(f"{protected}.pub").read_text()))
        self.assertFalse(self.blocks(self.key("")))



class OutboxLeftovers(Outbox):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(actions, "DEFAULT_LEDGER", self.led)
        p.start()
        self.addCleanup(p.stop)

    def test_a_failed_correction_publish_keeps_its_reason_in_the_outbox_and_publish_puts_it_back(self):
        reason = b"A public reason.\n"
        sha = actions.sha256(reason)
        st = self.c.state()
        entry = {"seq": st.seq + 1, "prev": st.head, "time": iso(actions.now_utc()), "type": "correction",
                 "actor": "keeper", "body": {"act": "note", "reason_sha256": sha}, "sig": "x"}
        out = actions.entry_path(self.led, entry["seq"])
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(entry))
        archived = actions.reasons_dir(self.led) / f"{sha}.md"
        archived.parent.mkdir()
        archived.write_bytes(reason)
        actions._keep_in_outbox(st, entry)

        def no_fork(*a, **k):
            raise actions.UserError("could not find your fork of openmasonry/openmasonry on GitHub")
        with mock.patch.object(actions, "_submit", no_fork), mock.patch.object(actions, "_git", lambda *a: done(1)), \
                self.assertRaises(actions.UserError) as err:
            actions._publish_kept([out, archived], entry, "upstream", None, st)
        self.assertIn(f"pending --publish {entry['seq']}", str(err.exception))
        self.assertEqual((out.exists(), archived.exists()), (False, False))    # ledger/ is as clean as before
        kept = actions._outbox_reason(st, entry)
        self.assertEqual((kept.read_bytes(), os.stat(kept).st_mode & 0o777), (reason, 0o600))
        seen = {}

        def publish(paths, e, remote, login, st_):
            seen["reason"] = paths[1].read_bytes()
            return 0, "https://github.com/openmasonry/openmasonry/pull/9"
        with mock.patch.object(actions, "_publish_kept", publish), mock.patch.object(actions, "_git", lambda *a: done(1)), \
                mock.patch.object(actions, "_gh", lambda *a: done(1)), mock.patch.object(actions, "entry_text", json.dumps), \
                mock.patch.object(actions, "describe", lambda st, e: "a correction"):
            self.assertEqual(self.run_(actions.cmd_pending, publish=entry["seq"])[0], 0)
        self.assertEqual(seen["reason"], reason)
        self.assertFalse(kept.exists())
        out.unlink()                               # the real publish takes it back out of the working tree
        kept.write_bytes(reason)
        self.run_(actions.cmd_pending, drop=entry["seq"])
        self.assertFalse(kept.exists())

    def test_pending_names_the_publish_command_for_an_entry_with_no_pull_request(self):
        digest = self.draft("https://example.org/w1")
        signed = json.loads((actions.PENDING / f"{digest}.json").read_text())["entry"]
        actions._keep_in_outbox(self.c.state(), signed)
        text = self.run_(actions.cmd_pending, json=False)[1]
        self.assertIn(f"#{signed['seq']} work: unknown", text)
        self.assertIn(f"no pull request found: {onboard.OM} pending --publish {signed['seq']}", text)

    def test_a_draft_the_ledger_moved_past_is_marked_stale(self):
        digest = self.draft("https://example.org/w1")
        self.assertEqual([d["stale"] for d in json.loads(self.run_(actions.cmd_drafts)[1])["drafts"]], [False])
        self.c.add("work", "hiram", {"ref": "https://example.org/other"})
        self.write()
        self.assertEqual([d["stale"] for d in json.loads(self.run_(actions.cmd_drafts)[1])["drafts"]], [True])
        self.assertIn(f"stale: {onboard.OM} discard {digest[:16]}", self.run_(actions.cmd_drafts, json=False)[1])

    def test_approval_with_a_passphrase_nobody_can_type_here_stops_before_the_dialog(self):
        digest = self.draft("https://example.org/w1")
        asked = []
        with mock.patch.object(onboard, "passphrase_blocks", lambda key: True), \
                mock.patch.object(actions, "_ask", lambda *a, **k: asked.append(a)), \
                self.assertRaises(actions.UserError) as err:
            self.run_(actions.cmd_approve, digest=digest)
        self.assertIn("asks for its passphrase", str(err.exception))
        self.assertIn(f"{onboard.OM} approve {digest[:16]} in a terminal of their own", str(err.exception))
        self.assertEqual(asked, [])
        self.assertTrue((actions.PENDING / f"{digest}.json").exists())          # nothing was signed


if __name__ == "__main__":
    unittest.main()
