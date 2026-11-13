"""Publishing a signed entry with real git: a refused push, an entry dropped and drafted again at the same seq, a
fresh clone, a pull request that could not be opened, and an ssh-agent that never answers.

The canonical repository and the person's fork are bare repositories in a temporary directory, reached as
`https://github.com/...` through git's `insteadOf`, with a temporary global git config. GitHub (`gh`) is a table
in memory; nothing here touches the network, a real GitHub account or a browser.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from openmasonry import actions, canon, crypto, onboard
from openmasonry.ledger import iso
from tests.test_guide import tmpdir
from tests.test_onboard import Door, FakeRun, done
from tests.test_onboard_paths import Outbox


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


class FakeGitHub:
    """`gh` for pull requests: `pr create` records one (its head read from the bare fork), `pr list` filters them
    by state and head branch, as GitHub's search does."""

    def __init__(self, repos: Path):
        self.repos, self.prs, self.refuse_create = repos, [], False

    def __call__(self, *args: str) -> subprocess.CompletedProcess:
        args = list(args)
        if args[:2] == ["pr", "create"]:
            if self.refuse_create:
                return done(1, "", "GraphQL: something went wrong")
            owner, branch = args[args.index("--head") + 1].split(":")
            if any(p["headRefName"] == branch and p["state"] == "OPEN" for p in self.prs):
                return done(1, "", f'a pull request for branch "{owner}:{branch}" into branch "main" already exists')
            sha = git(self.repos / owner / "openmasonry.git", "rev-parse", f"refs/heads/{branch}").stdout.strip()
            url = f"https://github.com/openmasonry/openmasonry/pull/{len(self.prs) + 1}"
            self.prs.append({"url": url, "state": "OPEN", "headRefName": branch, "headRefOid": sha,
                             "body": args[args.index("--body") + 1]})
            return done(0, url + "\n")
        if args[:2] == ["pr", "list"]:
            state = args[args.index("--state") + 1].upper()
            head = args[args.index("--search") + 1].removeprefix("head:")
            found = [p for p in self.prs if p["headRefName"] == head and state in ("ALL", p["state"])]
            return done(0, json.dumps(found))
        return done(1, "", "unknown gh command")

    def head_of_fork(self, branch: str) -> str:
        r = git(self.repos / "dora" / "openmasonry.git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                check=False)
        return r.stdout.strip()


@unittest.skipIf(shutil.which("git") is None, "needs git")
class RealGit(unittest.TestCase):
    """A canonical repository, dora's fork of it, and dora's clone of the canonical one."""

    def setUp(self):
        self.tmp = tmpdir(self)
        self.repos = self.tmp / "github.com"
        config = self.tmp / "gitconfig"
        config.write_text(f'[url "file://{self.repos}/"]\n\tinsteadOf = https://github.com/\n'
                          "[user]\n\tname = dora\n\temail = 5+dora@users.noreply.github.com\n"
                          "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n[advice]\n\tdetachedHead = false\n")
        env = {"GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
               "HOME": str(self.tmp / "home"), "OM_LOGIN": "dora"}           # never asks gh who is logged in
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            os.environ.pop(k, None)
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        seed = self.tmp / "seed"
        (seed / "ledger" / "entries" / "0000").mkdir(parents=True)
        (seed / "README.md").write_text("OpenMasonry\n")
        (seed / "ledger" / "entries" / "0000" / ".keep").write_text("")
        git(self.tmp, "init", "-q", str(seed))
        git(seed, "add", ".")
        git(seed, "commit", "-q", "-m", "seed")
        (self.repos / "openmasonry").mkdir(parents=True)
        (self.repos / "dora").mkdir()
        git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.repos / "openmasonry" / "openmasonry.git"))
        git(self.tmp, "clone", "-q", "--bare", str(self.repos / "openmasonry" / "openmasonry.git"),
            str(self.repos / "dora" / "openmasonry.git"))
        self.gh = FakeGitHub(self.repos)
        self.clone = self.fresh_clone("clone")
        self.target = ("fork", "dora")
        for p in (mock.patch.object(actions, "_gh", self.gh),
                  mock.patch.object(actions, "_push_target", lambda remote, login, seq=None: self.target),
                  mock.patch.object(actions, "is_repo_ledger", lambda led: True),
                  mock.patch.object(actions, "_require_in_sync", lambda known=(): "origin"),
                  mock.patch.object(actions, "_ask", lambda *a, **k: a[2][-1]),
                  *([] if self.gh_on_path else [mock.patch.object(onboard, "gh_user", lambda: self.account)])):
            p.start()
            self.addCleanup(p.stop)

    account = ("dora", 5)          # the account gh reports…
    gh_on_path = False             # …unless a stub `gh` on PATH answers instead

    def fresh_clone(self, name: str) -> Path:
        """A clone of the canonical repository with dora's fork as the remote `fork`, where `om` runs."""
        where = self.tmp / name
        git(self.tmp, "clone", "-q", "https://github.com/openmasonry/openmasonry.git", str(where))
        git(where, "remote", "add", "fork", "https://github.com/dora/openmasonry.git")
        for p in (mock.patch.object(canon, "ROOT", where),
                  mock.patch.object(actions, "DEFAULT_LEDGER", where / "ledger" / "entries")):
            p.start()
            self.addCleanup(p.stop)
        return where

    def entry(self, ref: str, seq: int = 6) -> dict:
        return {"seq": seq, "prev": "0" * 64, "time": iso(actions.now_utc()), "type": "work", "actor": "dora",
                "body": {"ref": ref}, "sig": "x"}

    def place(self, entry: dict) -> Path:
        f = actions.entry_path(canon.ROOT / "ledger" / "entries", entry["seq"])
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(entry))
        return f

    def submit(self, entry: dict):
        f = self.place(entry)
        try:
            return actions._submit([f], entry, "origin", "dora")
        finally:
            f.unlink(missing_ok=True)                  # a publish leaves it out of the working tree once merged

    def publish(self, entry: dict) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = actions.publish_pending(argparse.Namespace(ledger=actions.DEFAULT_LEDGER, json=False), None, entry)
        return code, out.getvalue()

    def refuse_pushes(self):
        hook = self.repos / "dora" / "openmasonry.git" / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'GH007: Your push would publish a private email address.' >&2\nexit 1\n")
        hook.chmod(0o755)
        return hook


class RefusedPush(RealGit):
    def test_a_refused_push_is_not_published_until_the_branch_reaches_the_fork(self):
        e = self.entry("https://example.org/w1")
        branch = actions.entry_branch(e)
        hook = self.refuse_pushes()
        with self.assertRaises(actions.UserError) as err:
            self.submit(e)
        self.assertIn("git push failed", str(err.exception))
        self.assertIn(f"pending --publish {e['seq']}", str(err.exception))
        self.assertEqual(git(self.clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), "main")   # back
        self.assertEqual(git(self.clone, "config", f"branch.{branch}.merge", check=False).returncode, 1)  # no upstream
        self.assertFalse(actions.published(e))
        self.assertFalse(actions.published(e, github=True))
        hook.unlink()
        code, out = self.publish(e)
        self.assertEqual(code, 0)
        self.assertIn("/pull/1", out)
        self.assertTrue(actions.published(e))
        self.assertTrue(actions.published(e, github=True))
        self.assertEqual(self.gh.head_of_fork(branch), git(self.clone, "rev-parse", branch).stdout.strip())

    def test_a_pushed_branch_whose_pull_request_failed_is_not_published_when_github_is_asked(self):
        e = self.entry("https://example.org/w1")
        self.gh.refuse_create = True
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.submit(e), (1, None))
        self.assertIn(f"pending --publish {e['seq']}", out.getvalue())
        self.assertTrue(actions.published(e))                  # the branch is on the fork…
        self.assertFalse(actions.published(e, github=True))    # …and no pull request is: publishing opens it
        self.gh.refuse_create = False
        self.assertEqual(self.publish(e)[0], 0)
        self.assertTrue(actions.published(e, github=True))

    def test_a_branch_tracking_the_canonical_main_is_not_published(self):
        e = self.entry("https://example.org/w1")
        git(self.clone, "branch", "--track", actions.entry_branch(e), "origin/main")   # what older versions left
        self.assertFalse(actions.published(e))


class DroppedAndDraftedAgain(RealGit):
    def drafted_again(self) -> tuple[dict, dict]:
        first = self.entry("https://example.org/first")
        self.assertEqual(self.submit(first)[0], 0)
        self.gh.prs[0]["state"] = "CLOSED"             # refused by the judge, dropped and closed
        return first, self.entry("https://example.org/second")

    def test_the_new_entry_replaces_the_old_branch_on_the_fork(self):
        first, second = self.drafted_again()
        branch = actions.entry_branch(second)
        code, url = self.submit(second)
        self.assertEqual((code, url), (0, "https://github.com/openmasonry/openmasonry/pull/2"))
        head = git(self.clone, "rev-parse", branch).stdout.strip()
        self.assertEqual(self.gh.head_of_fork(branch), head)
        shown = git(self.repos / "dora" / "openmasonry.git", "show", f"{head}:ledger/entries/0000/000006.json").stdout
        self.assertEqual(json.loads(shown)["body"]["ref"], "https://example.org/second")
        self.assertEqual(actions.entry_pr(second), (True, {"url": self.gh.prs[1]["url"], "state": "OPEN"}))
        self.assertEqual(actions.entry_pr(first), (True, {"url": self.gh.prs[0]["url"], "state": "CLOSED"}))
        for pr in self.gh.prs:
            pr["body"] = ""                                    # the head alone: only the branch's own entry matches
        self.assertEqual(actions.entry_pr(second)[1]["url"], self.gh.prs[1]["url"])
        self.assertEqual(actions.entry_pr(first), (True, None))

    def test_the_closed_pull_request_of_the_dropped_entry_is_never_this_entry_s(self):
        first, second = self.drafted_again()
        self.gh.refuse_create = True
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.submit(second), (1, None))
        self.assertEqual(actions.entry_pr(second), (True, None))
        self.assertFalse(actions.published(second, github=True))
        self.gh.refuse_create = False
        code, out = self.publish(second)
        self.assertEqual((code, out.strip()), (0, "https://github.com/openmasonry/openmasonry/pull/2"))

    def test_a_fresh_clone_replaces_a_branch_the_fork_kept_from_an_earlier_attempt(self):
        first, second = self.drafted_again()
        self.clone = self.fresh_clone("again")         # no remote-tracking branch of the fork here
        self.assertEqual(self.submit(second)[0], 0)
        self.assertEqual(self.gh.head_of_fork(actions.entry_branch(second)),
                         git(self.clone, "rev-parse", actions.entry_branch(second)).stdout.strip())

    def test_a_branch_deleted_on_the_fork_by_hand_is_pushed_again(self):
        first, second = self.drafted_again()
        git(self.clone, "push", "-q", "fork", "--delete", actions.entry_branch(first))
        self.assertEqual(self.submit(second)[0], 0)

    def test_the_canonical_repository_is_never_force_pushed(self):
        first, second = self.drafted_again()
        self.target = ("origin", "openmasonry")        # a member with write access pushes to the canonical one
        branch = actions.entry_branch(first)
        git(self.clone, "push", "-q", "origin", f"{git(self.clone, 'rev-parse', 'fork/' + branch).stdout.strip()}:"
            f"refs/heads/{branch}")
        self.gh.prs[0]["state"] = "OPEN"               # its pull request is still open: the branch is left alone
        before = git(self.repos / "openmasonry" / "openmasonry.git", "rev-parse", branch).stdout.strip()
        with self.assertRaises(actions.UserError) as err:
            self.submit(second)
        self.assertIn("git push failed", str(err.exception))
        self.assertEqual(git(self.repos / "openmasonry" / "openmasonry.git", "rev-parse", branch).stdout.strip(), before)


class CommitIdentity(RealGit):
    """Every commit `om` makes for an entry carries the publishing account's name and GitHub's private address, in
    UTC, whatever name, e-mail and time zone the clone's git configuration and environment hold."""

    NOREPLY = "dora <5+dora@users.noreply.github.com>"

    def setUp(self):
        super().setUp()
        personal = {"GIT_CONFIG_GLOBAL": os.environ["GIT_CONFIG_GLOBAL"], "TZ": "<+0530>-5:30"}    # a zone ahead of UTC
        config = Path(personal["GIT_CONFIG_GLOBAL"])
        config.write_text(config.read_text().replace("name = dora", "name = Pat Example")
                          .replace("5+dora@users.noreply.github.com", "pat@example.org"))
        git(self.clone, "config", "user.name", "Pat Local")
        git(self.clone, "config", "user.email", "pat.local@example.org")
        p = mock.patch.dict(os.environ, personal | {"GIT_AUTHOR_NAME": "Pat Env", "GIT_AUTHOR_EMAIL": "pat.env@example.org"})
        p.start()
        self.addCleanup(p.stop)

    def commit_of(self, branch: str) -> list[str]:
        fork = self.repos / "dora" / "openmasonry.git"
        return git(fork, "log", "-1", "--date=raw", "--format=%an <%ae>|%ad|%cn <%ce>|%cd", branch).stdout.strip().split("|")

    def test_the_commit_carries_the_noreply_identity_and_utc_whatever_the_clone_says(self):
        e = self.entry("https://example.org/w1")
        self.assertEqual(self.submit(e)[0], 0)
        author, adate, committer, cdate = self.commit_of(actions.entry_branch(e))
        self.assertEqual((author, committer), (self.NOREPLY, self.NOREPLY))
        self.assertTrue(adate.endswith(" +0000") and cdate.endswith(" +0000"), (adate, cdate))
        shown = git(self.repos / "dora" / "openmasonry.git", "cat-file", "-p", actions.entry_branch(e)).stdout
        self.assertNotIn("example.org>", shown)
        self.assertNotIn("+0530", shown)

    def test_without_the_account_nothing_is_committed(self):
        self.account = None
        e = self.entry("https://example.org/w1")
        with self.assertRaises(actions.UserError) as err:
            self.submit(e)
        self.assertIn("cannot tell which GitHub account", str(err.exception))
        self.assertEqual(git(self.clone, "rev-parse", "--verify", "--quiet", actions.entry_branch(e), check=False).returncode, 1)

    def test_a_founder_entry_whose_commit_carries_another_identity_is_not_pushed(self):
        e = {**self.entry("https://example.org/w1", seq=0), "type": "genesis"}
        real = actions.commit_env
        with mock.patch.object(actions, "commit_env", lambda user: {**real(user), "GIT_COMMITTER_EMAIL": "x@example.org"}), \
                self.assertRaises(actions.UserError) as err:
            self.submit(e)
        self.assertIn("NOT PUBLISHED", str(err.exception))
        self.assertIn("x@example.org", str(err.exception))
        self.assertEqual(self.gh.head_of_fork(actions.entry_branch(e)), "")              # nothing was pushed
        self.assertEqual(git(self.clone, "rev-parse", "--verify", "--quiet", actions.entry_branch(e), check=False).returncode, 1)
        self.assertEqual(self.submit(e)[0], 0)                                           # made again, with the right one
        author, adate, committer, cdate = self.commit_of(actions.entry_branch(e))
        self.assertEqual((author, committer, adate[-5:], cdate[-5:]), (self.NOREPLY, self.NOREPLY, "+0000", "+0000"))

    def test_a_kept_founder_branch_with_another_identity_is_not_pushed_again(self):
        e = {**self.entry("https://example.org/w1", seq=0), "type": "genesis"}
        f = self.place(e)
        git(self.clone, "switch", "-q", "-c", actions.entry_branch(e))
        git(self.clone, "add", "--", str(f))
        git(self.clone, "commit", "-q", "-m", "by hand")                                # personal name, local zone
        git(self.clone, "switch", "-q", "main")                                         # the file leaves with it
        with mock.patch.object(canon, "FOUNDER_GITHUB_ID", 5), self.assertRaises(actions.UserError) as err:
            self.publish(e)                                                             # the founding account itself
        self.assertIn("NOT PUBLISHED", str(err.exception))
        self.assertIn("+0530", str(err.exception))
        self.assertEqual(self.gh.head_of_fork(actions.entry_branch(e)), "")

    def test_a_differing_git_identity_is_one_note_never_a_refusal(self):
        fake = FakeRun()
        fake.rules.insert(0, ("config --get user.email", done(0, "dora@example.org\n")))
        err = io.StringIO()
        with mock.patch.object(onboard, "_run", fake), contextlib.redirect_stderr(err):
            actions.publish_preflight()
        self.assertEqual(err.getvalue().count("\n"), 1, err.getvalue())
        self.assertIn("5+dora@users.noreply.github.com", err.getvalue())
        self.assertIn("UTC", err.getvalue())


class WriteAccess(RealGit):
    """A member who can push to the canonical repository (the founder at launch): an entry refused by the judge,
    dropped and drafted again at the same seq, finds its own old branch there."""

    def setUp(self):
        super().setUp()
        self.target = ("origin", "openmasonry")
        self.canonical = self.repos / "openmasonry" / "openmasonry.git"

    def on_canonical(self, branch: str) -> str:
        return git(self.canonical, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).stdout.strip()

    def refused_once(self, close: bool = True) -> tuple[dict, dict]:
        first = self.entry("https://example.org/first")
        self.assertEqual(self.submit(first)[0], 0)
        self.assertEqual(self.on_canonical(actions.entry_branch(first)), git(self.clone, "rev-parse",
                                                                             actions.entry_branch(first)).stdout.strip())
        if close:
            self.gh.prs[0]["state"] = "CLOSED"
        return first, self.entry("https://example.org/second")

    def pending(self, entry: dict, **kw) -> str:
        out = io.StringIO()
        args = dict(ledger=actions.DEFAULT_LEDGER, json=False, rebase=None, publish=None, drop=None) | kw
        with mock.patch.object(actions, "HOME", self.tmp / "om"), \
                mock.patch.object(actions, "outbox", lambda st, led: ([entry], [])), \
                mock.patch.object(actions, "state_of", lambda led: None), contextlib.redirect_stdout(out):
            actions.cmd_pending(argparse.Namespace(**args))
        return out.getvalue()

    def test_drafting_again_replaces_the_own_old_branch_once_its_pull_request_is_closed(self):
        first, second = self.refused_once()
        branch = actions.entry_branch(second)
        code, url = self.submit(second)
        self.assertEqual((code, url), (0, "https://github.com/openmasonry/openmasonry/pull/2"))
        head = git(self.clone, "rev-parse", branch).stdout.strip()
        self.assertEqual(self.on_canonical(branch), head)
        shown = git(self.canonical, "show", f"{head}:ledger/entries/0000/000006.json").stdout
        self.assertEqual(json.loads(shown)["body"]["ref"], "https://example.org/second")
        self.assertEqual(self.on_canonical("main"), git(self.clone, "rev-parse", "origin/main").stdout.strip())

    def test_publish_succeeds_once_the_old_pull_request_is_closed(self):
        first, second = self.refused_once(close=False)
        branch = actions.entry_branch(second)
        old = self.on_canonical(branch)
        with self.assertRaises(actions.UserError) as err:
            self.submit(second)                        # the old pull request is open: its branch is never touched
        self.assertIn("[rejected]", str(err.exception))
        self.assertIn(f"pending --publish {second['seq']}", str(err.exception))
        self.assertEqual(self.on_canonical(branch), old)
        self.gh.prs[0]["state"] = "CLOSED"
        code, out = self.publish(second)
        self.assertEqual((code, out.strip()), (0, "https://github.com/openmasonry/openmasonry/pull/2"))
        self.assertEqual(self.on_canonical(branch), git(self.clone, "rev-parse", branch).stdout.strip())

    def test_drop_deletes_the_own_old_branch_when_no_open_pull_request_uses_it(self):
        first, _ = self.refused_once(close=False)
        branch = actions.entry_branch(first)
        self.pending(first, drop=first["seq"])
        self.assertTrue(self.on_canonical(branch))     # its pull request is open: kept
        self.gh.prs[0]["state"] = "CLOSED"
        out = self.pending(first, drop=first["seq"])
        self.assertEqual(self.on_canonical(branch), "")
        self.assertIn(f"deleted its branch {branch}", out)

    def test_another_login_s_branch_is_never_touched(self):
        theirs = {**self.entry("https://example.org/theirs"), "actor": "ada"}
        branch = actions.entry_branch(theirs)
        self.assertEqual(self.submit(theirs)[0], 0)    # a branch om/ada/… on the canonical repository
        self.gh.prs[0]["state"] = "CLOSED"
        before = self.on_canonical(branch)
        again = {**self.entry("https://example.org/again"), "actor": "ada"}
        with self.assertRaises(actions.UserError):
            self.submit(again)                         # published by dora: never deletes ada's branch
        self.pending(theirs, drop=theirs["seq"])
        self.assertEqual(self.on_canonical(branch), before)

    def test_the_delete_never_removes_a_push_made_in_between(self):
        first, second = self.refused_once()
        branch = actions.entry_branch(second)
        other = self.tmp / "other"                     # another clone, which pushes while om runs here
        git(self.tmp, "clone", "-q", "https://github.com/openmasonry/openmasonry.git", str(other))
        (other / "x.txt").write_text("x\n")
        git(other, "add", "x.txt")
        git(other, "commit", "-q", "-m", "x")
        between = git(other, "rev-parse", "HEAD").stdout.strip()
        asked = self.gh.__call__

        def gh(*args):
            if args[:2] == ("pr", "list") and "open" in args:          # after the lease is read, before the delete
                git(other, "push", "-q", "-f", "origin", f"{between}:refs/heads/{branch}")
            return asked(*args)
        with mock.patch.object(actions, "_gh", gh), self.assertRaises(actions.UserError):
            self.submit(second)
        self.assertEqual(self.on_canonical(branch), between)


class ClosedPullRequest(RealGit):
    """A pull request closed by hand, or by GitHub when its head branch was deleted, will never merge."""

    def closed(self) -> dict:
        e = self.entry("https://example.org/w1")
        self.assertEqual(self.submit(e)[0], 0)
        self.gh.prs[0]["state"] = "CLOSED"
        return e

    def test_an_entry_whose_only_pull_request_is_closed_is_not_published(self):
        e = self.closed()
        self.assertEqual(actions.entry_pr(e)[1]["state"], "CLOSED")
        self.assertFalse(actions.published(e, github=True))

    def test_the_entry_s_pull_request_is_the_open_one_then_the_merged_one_then_a_closed_one(self):
        e = self.closed()
        tag = actions.entry_tag(e)
        branch = actions.entry_branch(e)
        for state in ("MERGED", "OPEN"):              # gh lists them in either order
            self.gh.prs.append({"url": f"https://github.com/openmasonry/openmasonry/pull/{state}", "state": state,
                                "headRefName": branch, "headRefOid": "0" * 40, "body": tag})
            for order in (self.gh.prs, self.gh.prs[::-1]):
                with mock.patch.object(self.gh, "prs", order):
                    self.assertEqual(actions.entry_pr(e)[1]["state"], state)
            self.assertTrue(actions.published(e, github=True))

    def test_pending_offers_to_publish_again_and_publishing_opens_a_new_pull_request(self):
        e = self.closed()
        out = io.StringIO()
        with mock.patch.object(actions, "HOME", self.tmp / "om"), \
                mock.patch.object(actions, "outbox", lambda st, led: ([e], [])), \
                mock.patch.object(actions, "state_of", lambda led: None), contextlib.redirect_stdout(out):
            actions.cmd_pending(argparse.Namespace(ledger=actions.DEFAULT_LEDGER, json=False, rebase=None, publish=None,
                                                   drop=None))
        self.assertIn("#6 work: CLOSED https://github.com/openmasonry/openmasonry/pull/1", out.getvalue())
        self.assertIn(f"its pull request was closed: {onboard.OM} pending --publish 6 opens a new one (it asks you "
                      f"first), or {onboard.OM} pending --drop 6", out.getvalue())
        code, text = self.publish(e)
        self.assertEqual((code, text.strip()), (0, "https://github.com/openmasonry/openmasonry/pull/2"))
        self.assertEqual(actions.entry_pr(e)[1]["state"], "OPEN")


class PushFailureMessages(RealGit):
    def refuse_loudly(self):
        hook = self.refuse_pushes()
        hook.write_text("#!/bin/sh\necho 'remote: " + "x" * 900 + "' >&2\nexit 1\n")

    def test_publish_again_keeps_the_suffix_when_git_s_message_is_long(self):
        e = self.entry("https://example.org/w1")
        self.refuse_loudly()
        suffix = (f"(the signed entry is kept on the branch {actions.entry_branch(e)}: fix the cause, then "
                  f"{onboard.OM} pending --publish {e['seq']})")
        for attempt in (lambda: self.submit(e), lambda: self.publish(e)):
            with self.assertRaises(actions.UserError) as err:
                attempt()
            self.assertTrue(str(err.exception).endswith(suffix), str(err.exception)[-200:])
            self.assertLess(len(str(err.exception)), 300 + len(suffix) + 40)


REAL_PUSH_TARGET = actions._push_target


class PushURL(RealGit):
    """A remote that fetches from the person's fork but pushes elsewhere (remote.NAME.pushurl, pushInsteadOf)."""

    def setUp(self):
        super().setUp()
        (self.repos / "ada").mkdir()
        git(self.tmp, "clone", "-q", "--bare", str(self.repos / "openmasonry" / "openmasonry.git"),
            str(self.repos / "ada" / "openmasonry.git"))
        asked = self.gh

        def gh(*args):
            line = " ".join(args)
            if ".permissions.push" in line:
                return done(0, "false\n")
            if args[0] == "api" and args[1] in ("repos/dora/openmasonry", "repos/ada/openmasonry"):
                return done(0, "openmasonry/openmasonry\n")
            return asked(*args)
        p = mock.patch.object(actions, "_gh", gh)
        p.start()
        self.addCleanup(p.stop)

    def test_a_fork_remote_that_pushes_to_the_canonical_repository_or_another_fork_is_refused(self):
        self.assertEqual(REAL_PUSH_TARGET("origin", "dora", 6), ("fork", "dora"))
        for where in ("openmasonry/openmasonry", "ada/openmasonry"):
            git(self.clone, "config", "remote.fork.pushurl", f"https://github.com/{where}.git")
            with self.assertRaises(actions.UserError) as err:
                REAL_PUSH_TARGET("origin", "dora", 6)
            self.assertIn(f"pushes to {where}", str(err.exception))
            self.assertIn("pending --publish 6", str(err.exception))
        git(self.clone, "config", "--unset", "remote.fork.pushurl")
        git(self.clone, "config", "url.https://github.com/ada/.pushInsteadOf", "https://github.com/dora/")
        with self.assertRaises(actions.UserError):
            REAL_PUSH_TARGET("origin", "dora", 6)

    def test_a_push_whose_url_is_the_canonical_repository_is_never_forced(self):
        first = self.entry("https://example.org/first")
        branch = actions.entry_branch(first)
        self.assertEqual(self.submit(first)[0], 0)
        git(self.clone, "push", "-q", "origin", f"{branch}:refs/heads/{branch}")
        before = git(self.repos / "openmasonry" / "openmasonry.git", "rev-parse", branch).stdout.strip()
        git(self.clone, "config", "remote.fork.pushurl", "https://github.com/openmasonry/openmasonry.git")
        f = self.place(self.entry("https://example.org/second"))
        git(self.clone, "switch", "-q", "-C", branch, "origin/main")
        git(self.clone, "add", str(f))
        git(self.clone, "commit", "-q", "-m", "second")
        f.unlink()
        r = actions._push("fork", branch, "origin", "dora")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(git(self.repos / "openmasonry" / "openmasonry.git", "rev-parse", branch).stdout.strip(), before)


class FreshClone(RealGit):
    def test_an_open_pull_request_counts_as_published_in_a_clone_without_the_branch(self):
        e = self.entry("https://example.org/w1")
        self.assertEqual(self.submit(e)[0], 0)
        self.clone = self.fresh_clone("again")
        self.assertFalse(actions.published(e))                 # git alone cannot tell…
        self.assertTrue(actions.published(e, github=True))     # …GitHub can, by the entry's digest
        code, out = self.publish(e)
        self.assertEqual(code, 0)
        self.assertIn("its pull request is open already", out)

    def test_when_github_cannot_be_asked_git_s_answer_stands(self):
        e = self.entry("https://example.org/w1")
        self.assertEqual(self.submit(e)[0], 0)
        with mock.patch.object(actions, "_gh", lambda *a: done(1, "", "error connecting to api.github.com")):
            self.assertTrue(actions.published(e, github=True))
        with mock.patch.object(actions, "_gh", mock.Mock(side_effect=FileNotFoundError("gh"))):
            self.assertEqual(actions.entry_pr(e), (False, None))


class PendingMatchesThePullRequest(RealGit):
    def test_pending_shows_no_pull_request_for_an_entry_whose_branch_name_an_old_one_used(self):
        old = self.entry("https://example.org/first")
        self.assertEqual(self.submit(old)[0], 0)
        self.gh.prs[0]["state"] = "CLOSED"
        new = self.entry("https://example.org/second")
        home = self.tmp / "om"
        with mock.patch.object(actions, "HOME", home), mock.patch.object(actions, "outbox",
                                                                          lambda st, led: ([new], [])), \
                mock.patch.object(actions, "state_of", lambda led: None), contextlib.redirect_stdout(io.StringIO()) as out:
            actions.cmd_pending(argparse.Namespace(ledger=actions.DEFAULT_LEDGER, json=False, rebase=None, publish=None,
                                                   drop=None))
        self.assertIn("#6 work: unknown", out.getvalue())
        self.assertNotIn("CLOSED", out.getvalue())
        self.assertIn("pending --publish 6", out.getvalue())


class SilentAgent:
    """An ssh-agent socket that accepts every connection and never answers: an agent forwarded over an SSH
    connection that died."""

    def __init__(self, test: unittest.TestCase):
        d = tempfile.mkdtemp(prefix="om", dir="/tmp" if len(tempfile.gettempdir()) > 60 else None)
        test.addCleanup(shutil.rmtree, d, True)
        self.path = os.path.join(d, "agent.sock")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(8)
        self.held: list[socket.socket] = []
        threading.Thread(target=self.serve, daemon=True).start()
        test.addCleanup(self.close)

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.held.append(conn)                     # read nothing, answer nothing

    def close(self):
        self.server.close()
        for c in self.held:
            c.close()


@unittest.skipIf(sys.platform == "win32" or shutil.which("ssh-add") is None or not hasattr(socket, "AF_UNIX"),
                 "needs ssh-add and a Unix socket")
class AgentThatNeverAnswers(unittest.TestCase):
    def setUp(self):
        self.agent = SilentAgent(self)
        for p in (mock.patch.dict(os.environ, {"SSH_AUTH_SOCK": self.agent.path}),
                  mock.patch.object(crypto, "AGENT_TIMEOUT", 1)):
            p.start()
            self.addCleanup(p.stop)

    def quickly(self, fn, *args):
        started = time.monotonic()
        answer = fn(*args)
        self.assertLess(time.monotonic() - started, 8)
        return answer

    def test_the_agent_query_gives_up_and_says_the_agent_is_not_readable(self):
        self.assertEqual(self.quickly(onboard.agent_listing), (None, True))
        self.assertIsNone(self.quickly(onboard.agent_keys))
        self.assertFalse(self.quickly(crypto._agent_has, "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIexample test"))

    def test_the_openssh_self_test_never_asks_the_agent(self):
        found = self.quickly(onboard.openssh)
        self.assertEqual(found["status"], "ok", found["message"])

    def test_a_key_file_signs_without_waiting_for_the_agent(self):
        key = tmpdir(self) / "k"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(key)], check=True,
                       stdin=subprocess.DEVNULL, env={k: v for k, v in os.environ.items() if k != "SSH_AUTH_SOCK"})
        sig = self.quickly(crypto.sign, b"payload", key)
        self.assertTrue(crypto.signature_valid(b"payload", sig, " ".join(Path(f"{key}.pub").read_text().split()[:2])))


class SigningTimeouts(unittest.TestCase):
    """ssh-keygen that never finishes (a dead agent, a token never touched) is stopped and named."""

    def test_signing_is_stopped_and_named_after_its_timeout(self):
        seen = []

        def run(argv, **kw):
            seen.append((argv[:3], kw.get("timeout"), "SSH_AUTH_SOCK" in (kw.get("env") or os.environ)))
            if argv[0] == "ssh-add":
                return done(0, "")
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        key = tmpdir(self) / "k"
        key.write_text("private")
        Path(f"{key}.pub").write_text("ssh-ed25519 AAAA test\n")
        with mock.patch.dict(os.environ, {"SSH_AUTH_SOCK": "/nowhere"}), \
                mock.patch.object(crypto.subprocess, "run", run), mock.patch.object(crypto.shutil, "which", lambda n: "/x"), \
                self.assertRaises(crypto.SigningError) as err:
            crypto.sign(b"payload", key)
        self.assertIn(f"did not finish within {crypto.SIGN_TIMEOUT} seconds", str(err.exception))
        self.assertEqual(seen[-1], (["ssh-keygen", "-q", "-Y"], crypto.SIGN_TIMEOUT, False))   # a key file: no agent

    def test_the_self_test_is_stopped_and_named_after_its_timeout(self):
        seen = []

        def run(argv, capture=True, **kw):
            if argv[:2] == ["ssh", "-V"]:
                return done(0, "", "OpenSSH_9.7p1\n")
            seen.append((kw.get("timeout"), "SSH_AUTH_SOCK" in kw.get("env", os.environ)))
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        with mock.patch.dict(os.environ, {"SSH_AUTH_SOCK": "/nowhere"}), mock.patch.object(onboard, "_run", run), \
                mock.patch.object(onboard.shutil, "which", lambda n, *a, **k: "/x"):
            found = onboard.openssh()
        self.assertEqual(found["status"], "fail")
        self.assertIn(f"within {onboard.SELF_TEST_TIMEOUT} seconds", found["message"])
        self.assertEqual(seen, [(onboard.SELF_TEST_TIMEOUT, False)])

@unittest.skipIf(sys.platform == "win32" or shutil.which("ssh-add") is None or not hasattr(socket, "AF_UNIX"),
                 "needs ssh-add and a Unix socket")
class ApprovalWithASilentAgent(Outbox):
    def test_approval_stops_before_the_dialog_instead_of_waiting_for_the_agent(self):
        digest = self.draft("https://example.org/w1")
        agent = SilentAgent(self)
        asked = []
        with mock.patch.dict(os.environ, {"SSH_AUTH_SOCK": agent.path}), mock.patch.object(crypto, "AGENT_TIMEOUT", 1), \
                mock.patch.object(actions, "_ask", lambda *a, **k: asked.append(a)), \
                self.assertRaises(actions.UserError) as err:
            started = time.monotonic()
            self.run_(actions.cmd_approve, digest=digest)
        self.assertLess(time.monotonic() - started, 8)
        self.assertIn("NOT SIGNED — the ssh-agent did not answer within", str(err.exception))
        self.assertIn("SSH_AUTH_SOCK", str(err.exception))
        self.assertEqual(asked, [])
        self.assertTrue((actions.PENDING / f"{digest}.json").exists())          # nothing was signed


class AgentWait(unittest.TestCase):
    def test_an_agent_is_given_ten_seconds_to_answer(self):
        self.assertEqual(crypto.AGENT_TIMEOUT, 10)
        seen = []
        with mock.patch.object(crypto.subprocess, "run", lambda argv, **kw: seen.append(kw.get("timeout")) or done(1)), \
                mock.patch.object(onboard.shutil, "which", lambda name: "/x"):
            crypto._agent_has("ssh-ed25519 AAAA test")
            onboard.agent_listing()
        self.assertEqual(seen, [10, 10])


class SilentAgentAtTheDoor(Door):
    @staticmethod
    def silent(argv):
        raise subprocess.TimeoutExpired(argv, crypto.AGENT_TIMEOUT)

    def test_onboard_names_an_agent_that_does_not_answer(self):
        fake = FakeRun(listing="")
        fake.rules.insert(0, ("ssh-add -L", self.silent))
        code, rep = self.onboard(fake)
        agent = next(c for c in rep["checks"] if c["id"] == "key_agent")
        self.assertEqual(agent["status"], "fail")
        self.assertIn("did not answer within 10 seconds", agent["message"])
        self.assertIn("SSH_AUTH_SOCK", agent["fix"]["text"])
        self.assertIsNone(rep["key"]["in_agent"])

    def test_doctor_names_an_agent_that_does_not_answer(self):
        out = io.StringIO()
        a = argparse.Namespace(login="dora", key=str(self.key), ledger=self.led)

        def run(argv, **kw):
            if argv[:2] == ["ssh-add", "-L"]:
                self.assertEqual(kw.get("timeout"), crypto.AGENT_TIMEOUT)
                self.silent(argv)
            return done(1)
        with mock.patch.object(actions.shutil, "which", lambda name, *x, **k: None if name == "curl" else "/x"), \
                mock.patch.object(actions.subprocess, "run", run), \
                mock.patch.object(onboard, "doctor_checks", return_value=[]), contextlib.redirect_stdout(out):
            code = actions.cmd_doctor(a)
        self.assertEqual(code, 1)
        self.assertIn("✘ the ssh-agent did not answer within 10 seconds", out.getvalue())


class ForkNotFound(unittest.TestCase):
    def test_the_message_names_the_real_seq(self):
        answers = [(".permissions.push", "false"), ("forks?per_page", ""), ("repo fork", "")]

        def run(argv, **kw):
            return next((done(0, out) for text, out in answers if text in " ".join(argv)), done(1, "", "no"))
        with mock.patch.object(actions.subprocess, "run", run), mock.patch.object(actions, "_git", lambda *a: done(0, "")), \
                mock.patch("time.sleep"), self.assertRaises(actions.UserError) as err:
            actions._push_target("upstream", "dora", 7)
        self.assertIn(f"{onboard.OM} pending --publish 7", str(err.exception))
        self.assertNotIn("SEQ", str(err.exception))


class FounderBeforeTheGenesisMerges(unittest.TestCase):
    genesis = {"seq": 0, "type": "genesis", "actor": "hiram", "prev": "0" * 64, "time": "2027-01-01T00:00:00Z",
               "body": {}, "sig": "x"}

    def me(self, pr: dict | None, as_json: bool = False) -> str:
        out = io.StringIO()
        with mock.patch.object(actions, "state_of", lambda led: None), \
                mock.patch.object(actions, "outbox", lambda st, led: ([self.genesis], [])), \
                mock.patch.object(actions, "is_repo_ledger", lambda led: True), \
                mock.patch.object(actions, "entry_pr", lambda e, state="all": (True, pr)), \
                contextlib.redirect_stdout(out):
            actions.cmd_me(argparse.Namespace(ledger=Path("ledger/entries"), login="hiram", json=as_json, time=None))
        return out.getvalue()

    def test_the_founder_is_told_the_genesis_waits_for_its_pull_request(self):
        url = "https://github.com/openmasonry/openmasonry/pull/1"
        text = self.me({"url": url, "state": "OPEN"})
        self.assertIn("your signed genesis is waiting for its pull request to merge", text)
        self.assertIn(url, text)
        rep = json.loads(self.me({"url": url, "state": "OPEN"}, as_json=True))
        self.assertEqual(rep["pending_prs"], [{"seq": 0, "type": "genesis", "published": True}])
        self.assertTrue(rep["before_genesis"])
        self.assertIn(url, rep["launch"])

    def test_a_genesis_that_never_reached_github_is_published_first(self):
        text = self.me(None)
        self.assertIn(f"your signed genesis is not published yet: {onboard.OM} pending --publish 0", text)
        rep = json.loads(self.me(None, as_json=True))
        self.assertEqual([(s["action"], s["argv"]) for s in rep["steps"]],
                         [("publish", [onboard.OM, "pending", "--publish", "0"])])


class FoundingAccount(RealGit):
    """An entry a founder signs, or a custodian linked to a founder, is published only from the account the ledger
    records for that founder, and the genesis only from the founding account of network.toml. `gh` is a stub
    script on PATH that answers `gh api user` with GH_STUB_USER and logs every call."""

    gh_on_path = True

    def setUp(self):
        super().setUp()
        from openmasonry.ledger import Custodian
        from tests.test_strict import fake_key, hand_state, mk
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        self.log = self.tmp / "gh.log"
        stub = bin_ / "gh"
        stub.write_text('#!/bin/sh\necho "$*" >> "$GH_STUB_LOG"\n'
                        'if [ "$1 $2" = "api user" ] && [ -n "$GH_STUB_USER" ]; then echo "$GH_STUB_USER"; exit 0; fi\n'
                        'echo "not logged in" >&2\nexit 1\n')
        stub.chmod(0o755)
        p = mock.patch.dict(os.environ, {"PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
                                         "GH_STUB_LOG": str(self.log), "GH_STUB_USER": "dora 5"})
        p.start()
        self.addCleanup(p.stop)
        self.st = hand_state(mk("dora", founder=True, github_id=5), mk("eli", github_id=9),
                             custodians={"warden": Custodian("warden", fake_key("warden"), fake_key("warden-revoke"),
                                                             "dora", actions.now_utc())})

    def refused(self, st, entry, pattern: str):
        with self.assertRaisesRegex(actions.UserError, pattern):
            actions.publish_pending(argparse.Namespace(ledger=actions.DEFAULT_LEDGER, json=False), st, entry)
        self.assertEqual(self.gh.prs, [])                  # nothing was published

    def test_a_founders_entry_is_never_published_from_another_account(self):
        os.environ["GH_STUB_USER"] = "dora-personal 6"
        self.refused(self.st, self.entry("https://example.org/w1"),
                     r"NOT PUBLISHED — an entry signed by the founder dora is published only from the GitHub account "
                     r"with id 5, but gh is logged in as dora-personal \(id 6\)")
        os.environ["GH_STUB_USER"] = ""
        self.refused(self.st, self.entry("https://example.org/w1"), "gh cannot tell which account it is logged in as")
        os.environ["GH_STUB_USER"] = "dora 5"
        code, out = self.publish(self.entry("https://example.org/w1"))
        self.assertEqual((code, "/pull/1" in out), (0, True))

    def test_an_entry_of_a_custodian_linked_to_a_founder_too(self):
        os.environ["GH_STUB_USER"] = "helper 7"
        entry = {**self.entry("https://example.org/w1"), "type": "correction", "actor": "warden"}
        self.refused(self.st, entry, r"the custodian warden \(linked to the founder dora\) is published only from "
                                     "the GitHub account with id 5")

    def test_the_genesis_only_from_the_founding_account(self):
        genesis = {**self.entry("https://example.org/w1", seq=0), "type": "genesis", "actor": "dora", "body": {}}
        with mock.patch.object(canon, "FOUNDER_GITHUB_ID", 355316448):
            self.refused(None, genesis, r"the genesis is published only from the GitHub account with id 355316448, "
                                        r"but gh is logged in as dora \(id 5\)")
            os.environ["GH_STUB_USER"] = "openmasonry 355316448"
            actions.account_guard(None, genesis, "Nothing was published")          # passes
        with mock.patch.object(canon, "FOUNDER_GITHUB_ID", 0):
            self.refused(None, genesis, "founder_github_id is not set")

    def test_submit_checks_every_entry_before_it_asks(self):
        genesis = {**self.entry("https://example.org/w1", seq=0), "type": "genesis", "actor": "dora", "body": {}}
        f = self.place(genesis)
        self.addCleanup(f.unlink, missing_ok=True)
        with mock.patch.object(canon, "FOUNDER_GITHUB_ID", 355316448), \
                mock.patch.object(actions, "state_of", lambda ledger: None), \
                mock.patch.object(actions, "_ask", mock.Mock(side_effect=AssertionError("asked"))), \
                self.assertRaisesRegex(actions.UserError, "the genesis is published only from"):
            actions.cmd_submit(argparse.Namespace(ledger=actions.DEFAULT_LEDGER, json=False))

    def test_a_petition_comes_from_the_account_its_invitation_names_not_a_departed_founders(self):
        from tests.test_strict import hand_state, mk
        departed = mk("dora", founder=True, github_id=5, status="departed")      # the login now names another person
        st = hand_state(departed, mk("ada", github_id=7),
                        invitations={"dora": {"by": "ada", "github_id": 9, "time": actions.now_utc()}})
        petition = {**self.entry("https://example.org/w1"), "type": "petition", "actor": "dora"}
        os.environ["GH_STUB_USER"] = "dora 9"                                    # the newcomer the invitation names
        self.assertEqual(actions.founding_account(st, petition)[0], 9)
        actions.account_guard(st, petition, "")
        os.environ["GH_STUB_USER"] = "dora 5"                                    # not the departed founder's account
        with self.assertRaisesRegex(actions.UserError, r"NOT PUBLISHED — a petition of dora \(by the account its "
                                                       r"invitation names\) is published only from the GitHub account "
                                                       r"with id 9, but gh is logged in as dora \(id 5\)"):
            actions.account_guard(st, petition, "")
        os.environ["GH_STUB_USER"] = "dora-renamed 9"                           # a renamed account: the id decides
        actions.account_guard(st, petition, "")
        st.invitations.clear()                                                   # no invitation: nothing to hold it to
        self.assertIsNone(actions.founding_account(st, petition))

    def test_any_account_publishes_the_entry_of_a_member_who_is_no_founder(self):
        os.environ["GH_STUB_USER"] = "someone 8"
        entry = {**self.entry("https://example.org/w1"), "actor": "eli"}
        self.assertIsNone(actions.founding_account(self.st, entry))
        actions.account_guard(self.st, entry, "")
        self.assertFalse(self.log.exists())                # gh was not even asked


@unittest.skipIf(shutil.which("ssh-keygen") is None, "needs OpenSSH")
class PassphraseOnWindows(unittest.TestCase):
    """Native Windows has no /dev/tty: the console of one's own stands for it, and the same probe runs."""

    def key(self, passphrase: str) -> Path:
        k = tmpdir(self) / "k"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", passphrase, "-C", "test", "-f", str(k)], check=True,
                       stdin=subprocess.DEVNULL)
        return k

    def blocks(self, key: Path, console: bool) -> bool:
        with mock.patch.object(onboard.sys, "platform", "win32"), \
                mock.patch.object(onboard, "console_opens", lambda: console), \
                mock.patch.object(onboard, "tty_opens", mock.Mock(side_effect=AssertionError("no /dev/tty on Windows"))), \
                mock.patch.object(onboard, "agent_keys", lambda: ""):
            started = time.monotonic()
            answer = onboard.passphrase_blocks(key)
        self.assertLess(time.monotonic() - started, 15)
        return answer

    def test_a_protected_key_with_no_console_of_one_s_own_is_named_at_once(self):
        protected = self.key("a passphrase nobody types")
        self.assertTrue(self.blocks(protected, console=False))
        self.assertFalse(self.blocks(protected, console=True))
        self.assertFalse(self.blocks(self.key(""), console=False))

    def test_the_console_of_one_s_own_needs_a_console_on_standard_input(self):
        with mock.patch.object(onboard.sys, "stdin", io.StringIO("")):
            self.assertFalse(onboard.console_opens())


if __name__ == "__main__":
    unittest.main()
