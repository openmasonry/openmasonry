"""`om onboard` and `om apply`: the door, for a person who has only a GitHub account and an agent.

Outside the pinned core (nothing in src/openmasonry/protocol.manifest imports this module), and adding no rule:
what the ledger accepts is unchanged. Every program this module runs goes through one seam, `_run`, that the
tests replace; it never reads a private key, never sees a passphrase, token or 2FA code, and runs `ssh-keygen`
on a private key only with the person's own terminal attached. Uploading a key and publishing an application
each ask the person first, in the same dialog as `om approve` (`actions._ask`).

`om onboard` runs the checks in a fixed order, changes nothing unless asked (`--create-key`, `--use-key`,
`--upload`), names the stage the person is at and the one next step (schema om.onboard/1). `om apply`
publishes the person's own text as their public application (schema om.apply/1). `doctor` and `approve`
reuse some of the checks (`git_identity`, `git_credentials`, `openssh`, `github_clock_skew`).
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import canon, crypto

OM = "bin\\om.cmd" if sys.platform == "win32" else "bin/om"      # the launcher, as this platform runs it
KEYS_URL = "https://github.com/{login}.keys"
FORM = canon.ROOT / ".github" / "ISSUE_TEMPLATE" / "application.yml"
APPLICATION_MAX = 1200             # characters, after trimming: the whole text shows in the dialog
UPLOAD_POLL = (12, 5)              # after an upload: look at the .keys listing this many times, this many seconds apart
CLOCK_FAIL_AHEAD, CLOCK_WARN, CLOCK_FAIL_BEHIND = 90, 30, 30 * 60    # seconds against GitHub's clock
LOGIN_COMMAND = ["gh", "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web",
                 "--scopes", "admin:public_key"]
REFRESH_COMMAND = ["gh", "auth", "refresh", "--hostname", "github.com", "--scopes", "admin:public_key"]
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN")
EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?(?:\(?\d[\d\s.\-()]*){9,}")
OPENSSH_MIN = (8, 1)               # ssh-keygen -Y sign appeared in OpenSSH 8.1; hardware keys (ed25519-sk) need 8.2
SELF_TEST_TIMEOUT = 20             # seconds for each ssh-keygen run of the OpenSSH check (a throwaway key)
MENTION_RE = re.compile(r"(?<![\w/@])@([A-Za-z0-9-]+)")


# ------------------------------------------------------------------- the seam --

def _run(argv: list[str], capture: bool = True, **kw) -> subprocess.CompletedProcess:
    """Run a program. A program that is not installed answers exit code 127, as a shell would."""
    try:
        if capture:
            return subprocess.run(argv, capture_output=True, text=True, **kw)
        return subprocess.run(argv, **kw)
    except (FileNotFoundError, PermissionError, NotADirectoryError) as err:
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: {err.strerror or err}")


def _ok(r: subprocess.CompletedProcess) -> bool:
    return r.returncode == 0


def _first(text: str) -> str:
    return next((x.strip() for x in (text or "").splitlines() if x.strip()), "")[:300]


def _git(*args: str) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(canon.ROOT), *args])


def cmdline(argv: list[str]) -> str:
    """A command line to print for the person, quoted for this platform's shell (cmd.exe and PowerShell take
    double quotes; a POSIX shell, single quotes)."""
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def tty_opens() -> bool:
    """Whether /dev/tty opens, for reading and for writing: the person's own terminal. (Opened as two files:
    a text-mode "r+" open of a terminal fails, as it is not seekable.)"""
    try:
        with open("/dev/tty", "r"), open("/dev/tty", "w"):
            return True
    except OSError:
        return False


def _version(text: str, pattern: str) -> tuple[int, ...] | None:
    m = re.search(pattern, text or "")
    return tuple(int(x) for x in m.groups()) if m else None


# --------------------------------------------------------------- one check --

def check(id_: str, status: str, message: str, fix: dict | None = None) -> dict:
    return {"id": id_, "status": status, "message": message, "fix": fix if status != "ok" else None}


def fix_command(argv: list[str], text: str, person: bool = False, public: bool = False) -> dict:
    return {"kind": "person_command" if person else "command", "argv": argv, "person": person, "public": public,
            "text": text}


def fix_text(kind: str, text: str) -> dict:
    return {"kind": kind, "argv": [], "person": kind == "setting", "public": False, "text": text}


INSTALL = {
    "git": "install git (macOS: xcode-select --install or brew install git; Debian/Ubuntu: sudo apt install git; "
           "Windows: winget install Git.Git)",
    "openssh": "install the OpenSSH client, 8.1 or later, 8.2 for a hardware key (built in on macOS; on Windows the "
               "built-in client when ssh -V says 8.1 or later, else the release of github.com/PowerShell/Win32-OpenSSH; "
               "Debian/Ubuntu: sudo apt install openssh-client; Fedora: sudo dnf install openssh-clients)",
    "gh": "install the GitHub CLI, 2.40 or later, from https://cli.github.com (brew install gh; winget install "
          "GitHub.cli; on Linux the official repository: distribution packages are often too old)",
    "python": "install Python 3.11 or later (brew install python@3.12; sudo apt install python3.12; python.org)",
}


# ---------------------------------------------------------------- the checks --

def dialog_channel() -> str:
    """How `om approve` would ask the person here: macos, windows, zenity, kdialog, console, terminal or none."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        return "macos"
    if sys.platform == "win32":
        return "windows" if shutil.which("powershell") or shutil.which("pwsh") else "console"
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        if shutil.which("zenity"):
            return "zenity"
        if shutil.which("kdialog"):
            return "kdialog"
    return "terminal" if tty_opens() else "none"


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def check_platform() -> dict:
    channel = dialog_channel()
    where = "WSL" if is_wsl() else {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, sys.platform)
    if channel == "none":                      # this process has no terminal (an agent's tool call): the person's has
        return check("platform", "warn", f"{where}: no dialog and no terminal here: approvals are typed by the person "
                     "in their own terminal", fix_text("read", f"the person runs {OM} approve in a terminal of their "
                                                       "own (an SSH session is fine)"))
    if channel == "macos" and _run(["launchctl", "managername"]).stdout.strip() not in ("Aqua", ""):
        return check("platform", "warn", "macOS without a desktop session: approvals fall back to a code typed on "
                     "the terminal", fix_text("read", "approve in a terminal of this Mac (an SSH session is fine)"))
    return check("platform", "ok", f"{where}, approvals through {channel}")


def check_python() -> dict:
    if sys.version_info >= (3, 11):
        return check("python", "ok", f"Python {sys.version.split()[0]}")
    return check("python", "fail", f"Python {sys.version.split()[0]} is too old (3.11 or later)",
                 fix_text("read", INSTALL["python"]))


def check_git() -> dict:
    r = _run(["git", "--version"])
    v = _version(r.stdout, r"(\d+)\.(\d+)")
    if not _ok(r) or v is None:
        return check("git", "fail", "git is not installed", fix_text("read", INSTALL["git"]))
    if v < (2, 23):
        return check("git", "fail", f"git {v[0]}.{v[1]} is too old (2.23 or later)", fix_text("read", INSTALL["git"]))
    return check("git", "ok", f"git {v[0]}.{v[1]}")


def git_identity(login: str | None = None, github_id: int | None = None) -> dict:
    """The name and e-mail git writes into the commit that carries an entry: they are public."""
    name, mail = (_git("config", "--get", k).stdout.strip() for k in ("user.name", "user.email"))
    if login and github_id:                     # one command at a time: the name first, then the e-mail
        noreply = f"{github_id}+{login}@users.noreply.github.com"
        both = (f"git config user.name {login} and git config user.email {noreply}, in this clone only, after the "
                "person agrees (GitHub's private address)")
        set_both = (fix_command(["git", "-C", str(canon.ROOT), "config", "user.name", login], "the name first: " + both)
                    if not name else fix_command(["git", "-C", str(canon.ROOT), "config", "user.email", noreply], both))
    else:                                       # never a command with a placeholder in it
        set_both = fix_text("read", f"log in to GitHub first (gh auth login); then {OM} onboard gives the exact "
                            "commands: git config user.name LOGIN and git config user.email "
                            "ID+LOGIN@users.noreply.github.com, in this clone only (GitHub's private address)")
    if not name or not mail:
        return check("git_identity", "fail", "git has no " + " and no ".join(
            x for x, v in (("user.name", name), ("user.email", mail)) if not v) + ": git cannot commit by hand in this clone (om commits each entry as the GitHub account)",
            set_both)
    if not mail.endswith("@users.noreply.github.com"):
        return check("git_identity", "warn", f"git commits as {name} <{mail}>: this e-mail becomes public in any "
                     "commit made by hand in this clone (om commits each entry with GitHub's private address)", set_both)
    return check("git_identity", "ok", f"git commits as {name} <{mail}>")


def check_git_signing() -> dict:
    if _git("config", "--get", "commit.gpgsign").stdout.strip().lower() == "true":
        return check("git_signing", "warn", "git signs every commit (commit.gpgsign): it may stop on a prompt",
                     fix_command(["git", "-C", str(canon.ROOT), "config", "commit.gpgsign", "false"],
                                 "in this clone only: entries carry their own signatures"))
    return check("git_signing", "ok", "git does not sign commits (entries carry their own signatures)")


def openssh() -> dict:
    """OpenSSH 8.1 or later with ssh-keygen and ssh-add, and proof that `ssh-keygen -Y sign` works (a throwaway
    key in a fresh temporary directory, removed afterwards: never the person's key)."""
    fix = fix_text("read", INSTALL["openssh"])
    missing = [p for p in ("ssh-keygen", "ssh-add") if shutil.which(p) is None]
    if missing:
        return check("openssh", "fail", f"{' and '.join(missing)} not found", fix)
    r = _run(["ssh", "-V"])
    v = _version(r.stderr + r.stdout, r"OpenSSH\S*?_(\d+)\.(\d+)")
    if v is not None and v < OPENSSH_MIN:
        return check("openssh", "fail", f"OpenSSH {v[0]}.{v[1]} is too old (8.1 or later)", fix)
    # The throwaway key never needs the agent, and ssh-keygen -Y sign would still ask one that SSH_AUTH_SOCK names:
    # a silent one (a dead forwarded socket) would hold onboard and doctor forever.
    quiet = {k: v for k, v in os.environ.items() if k != "SSH_AUTH_SOCK"}
    with tempfile.TemporaryDirectory() as t:
        k, m = Path(t) / "k", Path(t) / "m"
        m.write_text("test\n")
        try:
            made = _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(k)], env=quiet,
                        stdin=subprocess.DEVNULL, timeout=SELF_TEST_TIMEOUT)
            signed = _ok(made) and _ok(_run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(k), "-n", "openmasonry", str(m)],
                                            env=quiet, stdin=subprocess.DEVNULL, timeout=SELF_TEST_TIMEOUT))
        except subprocess.TimeoutExpired:
            return check("openssh", "fail", f"ssh-keygen did not finish its test signature within {SELF_TEST_TIMEOUT} "
                         "seconds (a throwaway key, no agent)", fix)
        if not signed or not (Path(t) / "m.sig").exists():
            return check("openssh", "fail", "ssh-keygen cannot sign (-Y sign): OpenSSH is too old or incomplete", fix)
    return check("openssh", "ok", f"OpenSSH {'.'.join(map(str, v)) if v else '(version unknown)'}, ssh-keygen -Y works")


def check_gh() -> dict:
    r = _run(["gh", "--version"])
    v = _version(r.stdout, r"gh version (\d+)\.(\d+)")
    if not _ok(r):
        return check("gh", "fail", "the GitHub CLI (gh) is not installed", fix_text("read", INSTALL["gh"]))
    if v is not None and v < (2, 40):
        return check("gh", "warn", f"gh {v[0]}.{v[1]} is old (2.40 or later)", fix_text("read", INSTALL["gh"]))
    return check("gh", "ok", f"gh {'.'.join(map(str, v)) if v else ''}".strip())


def token_vars() -> list[str]:
    return [v for v in TOKEN_VARS if os.environ.get(v)]


def check_gh_token_env() -> dict:
    found = token_vars()
    if found:
        return check("gh_token_env", "warn", f"{', '.join(found)} is set: gh uses that token, not the account you "
                     "logged in with", fix_text("read", f"unset {' '.join(found)}, and remove it from your shell profile"))
    return check("gh_token_env", "ok", "no GitHub token in the environment")


def gh_user() -> tuple[str, int] | None:
    """(login, numeric id) of the active gh account, or None."""
    r = _run(["gh", "api", "user", "--jq", '[.login, (.id|tostring)] | join(" ")'])
    parts = r.stdout.split() if _ok(r) else []
    if len(parts) == 2 and parts[1].isascii() and parts[1].isdigit():
        return parts[0], int(parts[1])
    return None


def gh_scopes() -> set[str] | None:
    """The scopes of the token gh uses (header X-OAuth-Scopes), or None when GitHub does not say."""
    r = _run(["gh", "api", "-i", "user"])
    if not _ok(r):
        return None
    for line in r.stdout.splitlines():
        if line.lower().startswith("x-oauth-scopes:"):
            return {s.strip() for s in line.split(":", 1)[1].split(",") if s.strip()}
        if not line.strip():
            break
    return None


GH_HELPER_RE = re.compile(r"""gh(\.exe)?['"]?\s+auth\s+git-credential""")   # also a quoted Windows path to gh.exe


def git_credentials(logged_in: bool = True) -> dict:
    """Whether git can push to github.com over HTTPS without asking for a password. Before the gh login its fix
    is words: `gh auth setup-git` cannot work yet (and the login itself offers to set it up)."""
    gh = _git("config", "--get-all", "credential.https://github.com.helper").stdout
    if GH_HELPER_RE.search(gh):
        return check("git_credentials", "ok", "git pushes to github.com with the gh login")
    fix = (fix_command(["gh", "auth", "setup-git"], "lets git push over HTTPS with the gh login") if logged_in else
           fix_text("read", "log in to GitHub first (gh auth login, answering Yes to 'Authenticate Git with your GitHub "
                    "credentials?'); if git still has no credentials, gh auth setup-git"))
    if _git("config", "--get-all", "credential.helper").stdout.strip():
        return check("git_credentials", "warn", "git uses another credential helper for github.com, not the gh "
                     "login: a push may ask for a password or use another account", fix)
    return check("git_credentials", "fail", "git has no credentials for github.com: a push would ask for a password",
                 fix)


def check_clone() -> dict:
    from .actions import canonical_remote
    if not (canon.ROOT / ".git").exists():
        return check("clone", "fail", f"{canon.ROOT} is not a git clone",
                     fix_command(["git", "clone", f"https://github.com/{canon.CANONICAL_REPO}.git"],
                                 "clone the repository over HTTPS"))
    if canonical_remote() is None:
        return check("clone", "fail", f"no git remote points to {canon.CANONICAL_REPO}",
                     fix_command(["git", "-C", str(canon.ROOT), "remote", "add", "upstream",
                                  f"https://github.com/{canon.CANONICAL_REPO}.git"], "adds the canonical repository"))
    return check("clone", "ok", f"a clone with a remote of {canon.CANONICAL_REPO}")


def check_clean() -> dict:
    staged = not _ok(_git("diff", "--cached", "--quiet"))
    dirty = _git("status", "--porcelain", "--", "ledger/").stdout.strip()
    if staged or dirty:
        return check("clean", "fail", "something is staged" if staged else "ledger/ has changes of its own",
                     fix_text("read", "git restore --staged . (keeps the edits); never edit ledger/entries"))
    return check("clean", "ok", "nothing staged, ledger/ unchanged")


def github_clock_skew() -> float | None:
    """Seconds this clock is ahead of GitHub's (negative: behind), from the Date header of api.github.com;
    None when GitHub cannot be reached (or curl is missing)."""
    if shutil.which("curl") is None:
        return None
    r = _run(["curl", "-sSI", "--max-time", "10", "https://api.github.com"])
    for line in r.stdout.splitlines() if _ok(r) else ():
        if line.lower().startswith("date:"):
            try:
                theirs = email.utils.parsedate_to_datetime(line.split(":", 1)[1].strip())
            except (TypeError, ValueError):
                return None
            from .actions import now_utc
            return (now_utc() - theirs).total_seconds()
    return None


CLOCK_FIX = ("turn on automatic time: macOS System Settings → General → Date & Time; Linux sudo timedatectl set-ntp "
             "true; WSL sudo hwclock -s; Windows Settings → Time & language → Date & time → Sync now")


def check_clock() -> dict:
    skew = github_clock_skew()
    if skew is None:
        return check("clock", "skip", "GitHub's clock could not be read (offline, or no curl)")
    word = f"{abs(skew):.0f} seconds {'ahead of' if skew > 0 else 'behind'} GitHub's"
    if skew > CLOCK_FAIL_AHEAD:
        return check("clock", "fail", f"this clock is {word}: the judge refuses an entry stamped more than 2 minutes "
                     "ahead of its clock", fix_text("setting", CLOCK_FIX))
    if skew < -CLOCK_FAIL_BEHIND:
        return check("clock", "fail", f"this clock is {word}: every draft is already that old when it is made, and the "
                     "judge refuses an entry stamped more than 6 hours behind its clock", fix_text("setting", CLOCK_FIX))
    if abs(skew) > CLOCK_WARN:
        return check("clock", "warn", f"this clock is {word}", fix_text("setting", CLOCK_FIX))
    return check("clock", "ok", "this clock agrees with GitHub's")


def key_source(explicit: str | None) -> str:
    from .actions import CONFIG, _read_json
    return ("flag" if explicit else "env" if os.environ.get("OM_KEY") else
            "config" if _read_json(CONFIG).get("key") else "default")


def keys_listed(login: str) -> str | None:
    """The public keys GitHub lists for `login` (what the judge reads), or None when they could not be read."""
    if shutil.which("curl") is None:
        return None
    r = _run(["curl", "-fsS", "--max-time", "10", KEYS_URL.format(login=login)])
    return r.stdout if _ok(r) else None


AGENT_SILENT = (f"the ssh-agent did not answer within {crypto.AGENT_TIMEOUT} seconds (SSH_AUTH_SOCK names a socket "
                "that never replies, often an agent forwarded over an SSH connection that closed): signing would wait "
                "for it too")
AGENT_FIX = ("the person opens a new SSH session (or starts a new agent), or unsets SSH_AUTH_SOCK in the shell that runs "
             "om, so that signing asks for the passphrase instead")


def agent_listing() -> tuple[str | None, bool]:
    """(the public keys the ssh-agent holds, whether it failed to answer in time). The keys are None when the agent
    cannot be read: no ssh-add, no agent, or an agent silent for crypto.AGENT_TIMEOUT seconds (then the second is True)."""
    if shutil.which("ssh-add") is None:
        return None, False
    try:
        r = _run(["ssh-add", "-L"], timeout=crypto.AGENT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, True
    return (r.stdout if r.returncode in (0, 1) else None), False


def agent_keys() -> str | None:
    return agent_listing()[0]


def default_key(hardware: bool = False) -> Path:
    return Path.home() / ".ssh" / ("openmasonry_ed25519_sk" if hardware else "openmasonry_ed25519")


def add_key_command(path: Path) -> list[str]:
    if sys.platform == "darwin":
        return ["ssh-add", "--apple-use-keychain", str(path)]
    return ["ssh-add", str(path)]


def console_opens() -> bool:
    """Native Windows: a console of the person's own, where ssh-keygen can ask for the passphrase. Standard input
    is that console (a harness gives a pipe) and CONIN$ opens."""
    try:
        if not (sys.stdin is not None and sys.stdin.isatty()):
            return False
        with open("CONIN$", "r"):
            return True
    except (OSError, ValueError):
        return False


def terminal_here() -> bool:
    """Where ssh-keygen would ask for a passphrase: /dev/tty, or on native Windows the console."""
    return console_opens() if sys.platform == "win32" else tty_opens()


def passphrase_blocks(key: Path) -> bool:
    """Whether signing with `key` would wait for a passphrase that nobody can type: no terminal here (on native
    Windows, no console of one's own), the key not in the ssh-agent, and protected by a passphrase. The probe asks
    ssh-keygen to open the key with an empty passphrase (`-P ""`), which never prompts, on POSIX or Windows, its
    standard input closed; this module never reads the private key itself."""
    if terminal_here() or not key.exists():
        return False
    try:
        blob = key.with_name(key.name + ".pub").read_text().split()[1]
    except (OSError, IndexError):
        blob = None
    held = agent_keys()
    if blob and held and blob in held:
        return False
    try:
        return not _ok(_run(["ssh-keygen", "-y", "-P", "", "-f", str(key)], stdin=subprocess.DEVNULL, timeout=20))
    except subprocess.TimeoutExpired:
        return True


# -------------------------------------------------------------- applications --

def applications(login: str | None = None) -> list[dict] | None:
    """The applications of `login` (default: the active gh account), open or closed, newest first, or None when
    GitHub cannot be asked. An application is an issue of the canonical repository whose title starts with
    `Application:`."""
    r = _run(["gh", "issue", "list", "--repo", canon.CANONICAL_REPO, "--author", login or "@me", "--state", "all", "--search",
              'in:title "Application:"', "--json", "number,url,state,createdAt,title", "--limit", "5"])
    if not _ok(r):
        return None
    try:
        rows = json.loads(r.stdout or "[]")
    except ValueError:
        return None
    rows = [x for x in rows if isinstance(x, dict) and str(x.get("title", "")).startswith("Application:")]
    rows.sort(key=lambda x: str(x.get("createdAt", "")), reverse=True)
    return [{"url": x.get("url"), "number": x.get("number"), "state": str(x.get("state", "")).lower(),
             "created_at": x.get("createdAt")} for x in rows]


def form_statements() -> list[str]:
    """The three statements of the application form, as the form words them (the body of `om apply` copies them)."""
    text = FORM.read_text(encoding="utf-8")
    block = text.split("id: understood", 1)[1] if "id: understood" in text else ""
    return re.findall(r"(?m)^\s+- label: (.+?)\s*$", block)


def application_body(text: str) -> str:
    ticks = "\n".join(f"- [X] {s}" for s in form_statements())
    return (f"### Introduce yourself, in your own words\n\n{text}\n\n### Before you submit\n\n{ticks}\n\n"
            "<sub>Opened with `om apply` after the author approved it in a dialog.</sub>\n")


def application_problems(text: str, login: str) -> list[str]:
    """Why a text cannot be published as an application (each with its line); empty when it can. Pure."""
    problems = []
    if not text.strip():
        return ["the application is empty"]
    if len(text.strip()) > APPLICATION_MAX:
        problems.append(f"the application is {len(text.strip())} characters; keep it under {APPLICATION_MAX} "
                        "(a few sentences are enough)")
    for n, line in enumerate(text.splitlines(), 1):
        if any((ord(c) < 32 and c not in "\t") or ord(c) == 127 or 0x80 <= ord(c) < 0xA0 for c in line):
            problems.append(f"line {n}: the application holds a control character: it must be plain text")
        if EMAIL_RE.search(line):
            problems.append(f"line {n}: the application holds an e-mail address: give no personal data")
        phone = (PHONE_RE.search(line) or re.match("", "")).group().strip()
        digits = sum(c.isdigit() for c in phone)    # 9 digits written as one plain number are not a phone number
        if digits >= 10 or (digits >= 9 and any(c in "+-.() " for c in phone)):
            problems.append(f"line {n}: the application holds what looks like a phone number: give no personal data")
        for who in MENTION_RE.findall(line):
            if who.casefold() != login.casefold():
                problems.append(f"line {n}: the application mentions @{who}: an application speaks for its author "
                                "and calls on no one")
    return problems


# -------------------------------------------------------------- `om onboard` --

ORDER = ("platform", "python", "git", "git_identity", "git_signing", "openssh", "gh", "gh_token_env", "gh_login",
         "account", "gh_scopes", "git_credentials", "clone", "clean", "clock", "key", "key_mode", "key_agent",
         "key_listed", "key_ledger", "ledger")
TOOLS = {"platform", "python", "git", "git_identity", "git_signing", "openssh", "gh", "gh_token_env",
         "git_credentials", "clone", "clean", "clock"}
LOGIN = ("gh_login", "account", "gh_scopes")    # fixed by logging in (again)


class Report:
    """The checks of one run, the facts they found, and what the run changed."""

    def __init__(self):
        self.checks: dict[str, dict] = {}
        self.changed: list[str] = []
        self.facts: dict = {"login": None, "github_id": None, "key": None, "application": None,
                            "application_checked": False, "invitation": None, "member": None, "petitioned": False,
                            "founded": True, "waiting": None}

    def add(self, c: dict) -> dict:
        self.checks[c["id"]] = c
        return c

    def skip(self, id_: str, waits: str) -> None:
        self.checks.setdefault(id_, check(id_, "skip", f"waits for {waits}"))

    def failed(self, *ids: str) -> bool:
        return any(self.checks.get(i, {}).get("status") == "fail" for i in ids)


def run_checks(a, rep: Report) -> None:
    """Every check of `om onboard`, in order; a check whose inputs are missing is `skip`."""
    from . import actions as A
    for fn in (check_platform, check_python, check_git):
        rep.add(fn())
    if rep.failed("git"):
        rep.skip("git_identity", "git")
        rep.skip("git_signing", "git")
    rep.add(openssh())
    rep.add(check_gh())
    rep.add(check_gh_token_env())
    user = gh_user() if not rep.failed("gh") else None
    explicit = getattr(a, "login", None) or os.environ.get("OM_LOGIN")
    login = explicit or (user[0] if user else None)
    rep.facts["login"], rep.facts["github_id"] = login, (user[1] if user and user[0] == login else None)
    if not rep.failed("git"):
        rep.checks["git_identity"] = git_identity(login, rep.facts["github_id"])
        rep.checks["git_signing"] = check_git_signing()
    if login is None:
        rep.add(check("gh_login", "fail", "gh is not logged in to github.com",
                      fix_command(LOGIN_COMMAND, "log in in the browser (and pass 2FA there); answer Yes to "
                                  "'Authenticate Git with your GitHub credentials?'", person=True)))
        rep.skip("account", "gh_login")
        rep.skip("gh_scopes", "gh_login")
    else:
        rep.add(check("gh_login", "ok", f"GitHub login {login}" + (f" (id {rep.facts['github_id']})"
                                                                 if rep.facts["github_id"] else "")))
        from .ledger import valid_login
        rep.add(check("account", "ok", "a personal GitHub account") if valid_login(login) and "_" not in login else
                check("account", "fail", f"{login} is not a personal GitHub login (a managed account cannot act on "
                      "public repositories)", fix_text("read", "use a personal GitHub account")))
        scopes = gh_scopes() if user else None
        if scopes is None:
            rep.skip("gh_scopes", "a token that states its scopes")
        elif not scopes & {"repo", "public_repo"}:
            rep.add(check("gh_scopes", "fail", "the gh token can neither fork nor open pull requests (no repo scope)",
                          fix_command(LOGIN_COMMAND, "log in again in the browser", person=True)))
        else:
            rep.add(check("gh_scopes", "ok", "the gh token may fork and open pull requests"
                          + ("" if scopes & {"admin:public_key", "write:public_key"} else
                             " (adding a key needs admin:public_key)")))
            rep.facts["key_scope"] = bool(scopes & {"admin:public_key", "write:public_key"})
    rep.add(git_credentials(login is not None) if not rep.failed("git") else
            check("git_credentials", "skip", "waits for git"))
    rep.add(check_clone() if not rep.failed("git") else check("clone", "skip", "waits for git"))
    rep.add(check_clean() if not rep.failed("git", "clone") else check("clean", "skip", "waits for clone"))
    rep.add(check_clock())
    key_checks(a, rep)
    ledger_checks(a, rep)


def key_checks(a, rep: Report) -> None:
    from . import actions as A
    path = A.key_path(getattr(a, "key", None))
    pub = path.with_name(path.name + ".pub")
    info = {"path": str(path), "source": key_source(getattr(a, "key", None)), "type": None, "fingerprint": None,
            "in_agent": None, "listed": None}
    rep.facts["key"] = info
    create = [OM, "onboard", "--create-key"]
    if not pub.exists():
        rep.add(check("key", "fail", f"no member key at {path}",
                      fix_command(create, f"creates the key in the person's own terminal (or {OM} onboard --use-key "
                                  "PATH for a key they have)", person=True)))
        for i in ("key_mode", "key_agent", "key_listed", "key_ledger"):
            rep.skip(i, "key")
        return
    try:
        bare = A.bare_public_key(path)
    except A.UserError as err:
        bare = ""
        rep.add(check("key", "fail", str(err), fix_command(create, "creates a new key", person=True)))
    kind = A.key_kind(bare) if bare else None
    if bare and kind is None:
        rep.add(check("key", "fail", f"{pub} is not an Ed25519 key (RSA and ECDSA keys are refused)",
                      fix_command(create, "creates an Ed25519 key", person=True)))
    if kind is None:
        for i in ("key_mode", "key_agent", "key_listed", "key_ledger"):
            rep.skip(i, "key")
        return
    info.update(type=bare.split()[0], fingerprint=A.fingerprint(bare))
    rep.facts["bare"] = bare
    rep.add(check("key", "ok", f"{kind} {info['fingerprint']} at {path} ({info['source']})"))
    try:
        loose = path.exists() and sys.platform != "win32" and os.stat(path).st_mode & (stat.S_IRWXG | stat.S_IRWXO)
    except OSError:
        loose = False
    rep.add(check("key_mode", "warn", f"{path} can be read by other users of this computer",
                  fix_command(["chmod", "600", str(path)], "makes the private key readable by its owner only"))
            if loose else check("key_mode", "ok", "only its owner can read the private key"))
    held, silent = agent_listing()
    info["in_agent"] = None if held is None else bare.split()[1] in held
    rep.add(check("key_agent", "ok", "the key is loaded in the ssh-agent") if info["in_agent"] else
            check("key_agent", "fail", AGENT_SILENT, fix_text("read", AGENT_FIX)) if silent else
            check("key_agent", "warn", "the key is not in the ssh-agent: signing will ask for its passphrase",
                  fix_command(add_key_command(path), "loads the key once (it asks the passphrase)" + (
                      "; the OpenSSH Authentication Agent service must be running (in an administrator PowerShell: "
                      "Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent)"
                      if sys.platform == "win32" else ""), person=True)))
    login = rep.facts["login"]
    if not login:
        rep.skip("key_listed", "gh_login")
    else:
        listing = keys_listed(login)
        url = KEYS_URL.format(login=login)
        if listing is None:
            rep.add(check("key_listed", "skip", f"could not read {url} (offline, or no curl): open it in a browser"))
        else:
            info["listed"] = bare.split()[1] in listing
            rep.add(check("key_listed", "ok", f"the key is listed at {url}") if info["listed"] else
                    check("key_listed", "fail", f"the key is not listed at {url}",
                          fix_command([OM, "onboard", "--upload"], "adds the key to GitHub after the person approves "
                                      "in a dialog", public=True)))


def own_petition(st, login: str | None, bare: str) -> bool:
    """The ledger registered `bare` for `login`'s own pending petition: that key is theirs, not a key used before."""
    from .ledger import point
    return bool(login) and any(x.casefold() == login.casefold() and point(p["key"]) == point(bare)
                               for x, p in st.petitions.items())


def ledger_checks(a, rep: Report) -> None:
    from . import actions as A
    from .ledger import Invalid, point
    try:
        st = A.state_of(a.ledger)
    except Invalid as err:
        rep.skip("key_ledger", "ledger")
        rep.add(check("ledger", "fail", f"the ledger does not verify: {err}", fix_text("read", "call the Tyler")))
        return
    rep.facts["state"], rep.facts["founded"] = st, st is not None
    login, bare = rep.facts["login"], rep.facts.get("bare")
    now = A.now_utc()
    if st is not None and login:
        login = A.canonical_login(st, login)
        rep.facts["login"] = login
        m = st.members.get(login)
        rep.facts["member"] = m
        rep.facts["petitioned"] = bool(st.petitions.get(login)) and st.live(login, now)
        if st.invited(login, now):
            inv = st.invitations[login]
            rep.facts["invitation"] = {"by": inv["by"], "github_id": inv["github_id"],
                                       "expires_at": A.iso(st.due(inv["time"], A.INVITE_EXPIRY_DAYS * A.DAY))}
        signed = next((e for e in A.pending_own(st, a.ledger) if e.get("type") == "petition"
                       and str(e.get("actor", "")).casefold() == login.casefold()), None)
        if signed is not None:                   # signed here, not in the ledger yet: published, or not
            rep.facts["waiting"] = {"seq": signed["seq"], "type": "petition",
                                    "published": A.published(signed, github=A.is_repo_ledger(a.ledger))}
    if bare is None:
        rep.skip("key_ledger", "key")
    elif st is None:
        rep.add(check("key_ledger", "ok", "the ledger is empty: no key is taken yet"))
    else:
        m = rep.facts["member"]
        others = [x for x in st.key_holders(bare, now) if not login or x[1].casefold() != login.casefold()]
        if m is not None and m.key != bare:
            rep.add(check("key_ledger", "fail", A.key_advice(st, login, bare), fix_text("read", f"{OM} doctor")))
        elif others:
            rep.add(check("key_ledger", "fail", f"this key is already used by the {others[0][0]} {others[0][1]}",
                          fix_command([OM, "onboard", "--create-key"], "a new key", person=True)))
        elif m is None and point(bare) in st.known_keys and not own_petition(st, login, bare):
            rep.add(check("key_ledger", "fail", "this key was used in this ledger before: a key is never registered "
                          "again", fix_command([OM, "onboard", "--create-key"], "a new key", person=True)))
        else:
            rep.add(check("key_ledger", "ok", "the ledger holds this key for you" if m else
                          "the ledger holds this key for your petition" if own_petition(st, login, bare) else
                          "no one in the ledger uses this key"))
    if A.is_repo_ledger(a.ledger) and rep.failed("git"):
        rep.add(check("ledger", "skip", "waits for git: the canonical ledger was not compared"))
    elif A.is_repo_ledger(a.ledger):
        status, msg = A.canonical_status(st.hashes if st else ())
        rep.add(check("ledger", "warn", msg, fix_text("read", "TROUBLESHOOTING.md, section 9")) if status == "offline"
                else check("ledger", "ok", msg) if status in ("in_sync", "ahead") else
                check("ledger", "fail", msg, fix_text("read", "git pull, then draft again" if status == "behind" else
                                                      "TROUBLESHOOTING.md, section 8")))
    else:
        rep.add(check("ledger", "ok", f"scratch ledger {a.ledger}" + (" (empty)" if st is None else "")))


STAGE_NEXT = {
    "no_key": ("create_key", "You have no member key yet: it is created in your own terminal, with a passphrase you "
               "choose.", [OM, "onboard", "--create-key"], True, False),
    "key_not_on_github": ("upload_key", "Your key is not listed on your GitHub account: the judge refuses a petition "
                          "whose key is not listed there. Adding it asks you first.",
                          [OM, "onboard", "--upload"], False, True),
    "not_applied": ("apply", "OpenMasonry admits by invitation: write your introduction in a file, in your own "
                    "words, and publish it as your public application (you approve it in a dialog).",
                    [], False, True),
    "applied": ("wait", "You applied. An application gives no right to an invitation: a Master Builder who comes to "
                "answer for you may invite you. Nothing to run meanwhile.", [], False, False),
    "invited": ("join", "You are invited: read the Declaration and, if you agree, petition for admission.",
                [OM, "join"], False, True),
    "petitioned": ("guide", "Your petition is in: the Guide shows the next steps.", [OM, "me"], False, False),
    "member": ("guide", "You are a member: the Guide shows what is due.", [OM, "me"], False, False),
}


APPLY_TEXT = (f"{OM} apply --text FILE, FILE being the introduction the person wrote ({OM} apply --text FILE --check "
              "first shows the exact issue)")
AFTER_LOGIN = ("git_identity", "git_credentials")    # their fixes need the account: they wait for the login


def _first_tool(rep: Report, *but: str) -> str | None:
    return next((i for i in ORDER if i in rep.checks and i in TOOLS and i not in but
                 and rep.checks[i]["status"] == "fail"), None)


def stage_of(rep: Report) -> str:
    c, f = rep.checks, rep.facts
    if f["member"] is not None and f["member"].status not in ("departed", "expelled", "voided"):
        return "member"
    if f["petitioned"] or f["waiting"]:
        return "petitioned"
    if _first_tool(rep, *AFTER_LOGIN):
        return "tools"
    if rep.failed(*LOGIN):
        return "login"
    if rep.failed(*AFTER_LOGIN):
        return "tools"
    if rep.failed("key", "key_ledger"):
        return "no_key"
    if rep.failed("key_listed"):
        return "key_not_on_github"
    if f["invitation"]:
        return "invited"
    return "applied" if is_open(f["application"]) else "not_applied"


def is_open(application: dict | None) -> bool:
    """An application that still stands: once it is closed, the person may apply again."""
    return bool(application) and application.get("state", "open") == "open"


def next_of(rep: Report, stage: str) -> dict:
    c = rep.checks
    if stage in ("tools", "login"):
        first = c[next(i for i in LOGIN if rep.failed(i))] if stage == "login" else c[
            _first_tool(rep, *AFTER_LOGIN) or next(i for i in AFTER_LOGIN if rep.failed(i))]
        fix = first["fix"] or fix_text("read", first["message"])
        return {"action": "fix", "why": first["message"], "argv": fix["argv"], "person": fix["person"],
                "public": fix["public"], "due_by": None, "text": fix["text"]}
    waiting = rep.facts["waiting"]
    if stage == "petitioned" and waiting and not waiting["published"]:
        return {"action": "publish", "why": f"Your petition #{waiting['seq']} is signed but not published yet: publishing "
                "it opens its pull request (it asks you first).", "argv": [OM, "pending", "--publish",
                str(waiting["seq"])], "person": False, "public": True, "due_by": None, "text": None}
    if stage == "petitioned" and waiting:
        return {"action": "wait", "why": f"Your petition #{waiting['seq']} is signed and waits for its pull request to "
                "merge: its state shows there.", "argv": [OM, "pending"], "person": False, "public": False,
                "due_by": None, "text": None}
    if stage == "not_applied" and not rep.facts["founded"]:
        from .actions import LAUNCH_HINT
        return {"action": "wait", "why": "The ledger is empty: the fraternity has not been founded yet, and nobody can "
                f"invite anyone until it is. {LAUNCH_HINT}", "argv": [], "person": False, "public": False,
                "due_by": None, "text": None}
    action, why, argv, person, public = STAGE_NEXT[stage]
    if stage == "no_key" and c.get("key_ledger", {}).get("status") == "fail":
        why = c["key_ledger"]["message"]
    return {"action": action, "why": why, "argv": argv, "person": person, "public": public,
            "due_by": (rep.facts["invitation"] or {}).get("expires_at") if stage == "invited" else None,
            "text": APPLY_TEXT if stage == "not_applied" else None}


def write_key(a, path: Path, rep: Report) -> None:
    """Record `path` as the key `om` signs with (config "key"), under the rules of ONBOARDING-DESIGN.md: never
    for a member whose ledger key is another key, never `previous_key` or `recovery_key`."""
    from . import actions as A
    bare = A.bare_public_key(path)
    if A.key_kind(bare) is None:
        raise A.UserError(f"{path}.pub: {A.KEY_RULE}")
    st, login = A.state_of(a.ledger), rep.facts["login"]
    m = st.members.get(A.canonical_login(st, login)) if st is not None and login else None
    if m is not None and m.status not in ("departed", "expelled", "voided") and m.key != bare:
        raise A.UserError("you are a member and the ledger holds another key for you: om onboard never changes your "
                          f"key (that is {OM} rekey)")
    config = A._read_json(A.CONFIG)
    if config.get("key") != str(path):
        A._write_private(A.CONFIG, {**config, "key": str(path)})
        rep.changed.append("config_written")
    if os.environ.get("OM_KEY") and Path(os.environ["OM_KEY"]).expanduser() != path:
        print(f"note: OM_KEY still names {os.environ['OM_KEY']}; unset it, or point it to {path}", file=sys.stderr)


def create_key(a, rep: Report) -> int:
    from . import actions as A
    hardware = getattr(a, "hardware", False)
    path = Path(a.create_key).expanduser() if isinstance(a.create_key, str) else default_key(hardware)
    if path.exists() or path.with_name(path.name + ".pub").exists():
        raise A.UserError(f"{path} already exists: om never overwrites a key. Use it with --use-key {path}, or choose "
                          "another path with --create-key PATH")
    argv = ["ssh-keygen", "-t", "ed25519-sk" if hardware else "ed25519", "-C", "openmasonry", "-f", str(path)]
    if not interactive():
        say("no terminal to ask for a passphrase: run this in your own terminal, then record the key with "
            f"{cmdline([OM, 'onboard', '--use-key', str(path)])}:\n  " + cmdline(argv))
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path.parent, 0o700)
    if not _ok(_run(argv, capture=False)) or not path.with_name(path.name + ".pub").exists():
        raise A.UserError("ssh-keygen did not create the key (nothing was recorded)")
    rep.changed.append("key_created")
    if sys.platform != "win32" and os.stat(path).st_mode & 0o077:
        os.chmod(path, 0o600)
    write_key(a, path, rep)
    say(f"✔ created {path} ({A.fingerprint(A.bare_public_key(path))})")
    return 0


def say(text: str) -> None:
    """Progress for the person: on stderr, so that --json prints only the report on stdout."""
    print(text, file=sys.stderr)


def interactive() -> bool:
    """A terminal of the person's own, where ssh-keygen can ask for the passphrase: stdin and stdout are terminals
    and /dev/tty opens (on Windows, the console)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    return sys.platform == "win32" or tty_opens()


def upload(a, rep: Report) -> int:
    from . import actions as A
    login, info = rep.facts["login"], rep.facts["key"] or {}
    if not login:
        raise A.UserError("cannot tell your GitHub login: run, in your own terminal: " + cmdline(LOGIN_COMMAND))
    if rep.checks.get("key", {}).get("status") != "ok":
        raise A.UserError(f"no valid member key to upload: {OM} onboard --create-key, or --use-key PATH")
    if info.get("listed"):
        say(f"✔ the key is listed at {KEYS_URL.format(login=login)} already: nothing to upload")
        return 0
    if rep.facts.get("key_scope") is False:
        raise A.UserError("uploading a key needs the admin:public_key scope: run, in your own terminal: "
                          + cmdline(REFRESH_COMMAND))
    path = Path(info["path"])
    pub = path.with_name(path.name + ".pub")
    text = (f"Add this public key to the GitHub account {login} as an authentication key?\n\n"
            f"  {info['type']}  {info['fingerprint']}\n  from {pub}\n\n"
            f"GitHub then lists it publicly at {KEYS_URL.format(login=login)}, which is\nwhat OpenMasonry's judge reads. "
            "An authentication key can also open SSH\nsessions to your repositories: keep its private half to yourself.\n"
            "You can remove it later in GitHub's settings (SSH and GPG keys).")
    if A._ask("OpenMasonry: add this key to GitHub?", text, ["Add the key"], a.ledger, key=path) is None:
        say("Canceled. Nothing was uploaded.")
        return 1
    r = _run(["gh", "ssh-key", "add", str(pub), "--type", "authentication", "--title", "OpenMasonry"])
    if not _ok(r):
        why, said = _first(r.stderr or r.stdout), (r.stderr + r.stdout).lower()    # gh puts GitHub's reason below
        raise A.UserError(f"GitHub refused the key: {why}" + (
            " … it is on another GitHub account already; create a new key for this one"
            if "already" in said and "use" in said else ""))
    rep.changed.append("key_uploaded")
    tries, pause = UPLOAD_POLL
    for i in range(tries):
        listing = keys_listed(login)
        if listing is not None and info["fingerprint"] and A.bare_public_key(path).split()[1] in listing:
            info["listed"] = True
            rep.checks["key_listed"] = check("key_listed", "ok", f"the key is listed at {KEYS_URL.format(login=login)}")
            say(f"✔ the key is listed at {KEYS_URL.format(login=login)}")
            return 0
        if i + 1 < tries:
            time.sleep(pause)
    say(f"· the key was added but is not listed at {KEYS_URL.format(login=login)} yet: run {OM} onboard again in "
        "a minute")
    return 0


def onboard_report(a, rep: Report) -> dict:
    stage = stage_of(rep)
    nxt = next_of(rep, stage)
    plat = {"os": sys.platform, "wsl": is_wsl(), "dialog": dialog_channel()}
    return {"schema": "om.onboard/1", "stage": stage, "login": rep.facts["login"], "github_id": rep.facts["github_id"],
            "platform": plat, "key": (rep.facts["key"] or None), "application": rep.facts["application"],
            "application_checked": rep.facts["application_checked"], "invitation": rep.facts["invitation"],
            "checks": [rep.checks[i] for i in ORDER if i in rep.checks], "next": nxt, "changed": rep.changed}


def find_application(a, rep: Report) -> None:
    from . import actions as A
    if rep.facts["login"] and not rep.failed("gh_login") and A.is_repo_ledger(a.ledger):
        found = applications(rep.facts["login"])
        rep.facts["application_checked"] = found is not None
        rep.facts["application"] = found[0] if found else None


def cmd_onboard(a) -> int:
    from . import actions as A
    rep = Report()
    run_checks(a, rep)
    code = 0
    if getattr(a, "create_key", None) is not None:
        code = create_key(a, rep)
        rep = _again(a, rep)
    elif getattr(a, "use_key", None):
        path = Path(a.use_key).expanduser()
        path = path.with_suffix("") if path.suffix == ".pub" else path
        write_key(a, path, rep)
        a.key = None
        rep = _again(a, rep)
    if code == 0 and getattr(a, "upload", False):
        code = upload(a, rep)
    find_application(a, rep)
    data = onboard_report(a, rep)
    if code == 0 and any(c["status"] == "fail" for c in data["checks"]):
        code = 1
    if getattr(a, "json", False):
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return code
    marks = {"ok": "✔", "warn": "·", "skip": "·", "fail": "✘"}
    for c in data["checks"]:
        fix = c["fix"]
        how = "" if not fix else f"  → {cmdline(fix['argv'])}" if fix["argv"] else f"  → {fix['text']}"
        print(f"{marks[c['status']]} {c['message']}{how if c['status'] in ('fail', 'warn') else ''}")
    n = data["next"]
    print(f"\nStage: {data['stage']}")
    cmd = cmdline(n["argv"]) if n["argv"] else (n["text"] or "nothing to run")
    print(f"Next{' (in your own terminal)' if n['person'] else ''}:  {cmd}   ({n['why']})"
          + (f" by {n['due_by']}" if n["due_by"] else ""))
    return code


def _again(a, rep: Report) -> Report:
    """Run the checks again after a change, keeping what this run changed."""
    fresh = Report()
    fresh.changed = rep.changed
    run_checks(a, fresh)
    return fresh


# ---------------------------------------------------------------- `om apply` --

def cmd_apply(a) -> int:
    from . import actions as A
    login = A.need_login(a)
    from .ledger import valid_login
    if not valid_login(login) or "_" in login:
        raise A.UserError(f"{login!r} is not a personal GitHub login")
    st = A.state_of(a.ledger)
    now = A.now_utc()
    warnings: list[str] = []
    title = f"Application: @{login}"

    def out(status: str, text: str, code: int, issue: dict | None = None, refused: str | None = None,
            body: str = "") -> int:
        data = {"schema": "om.apply/1", "status": status, "login": login, "title": title,
                "body_sha256": hashlib.sha256(body.encode()).hexdigest() if body else None,
                "characters": len(source.strip()) if source else 0, "issue": issue, "warnings": warnings,
                "refused": refused}
        if getattr(a, "json", False):
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            for w in warnings:
                print(f"· {w}")
            print(text)
        return code

    source = ""
    if st is not None:
        login = A.canonical_login(st, login)
        title = f"Application: @{login}"
        m = st.members.get(login)
        if m is not None and m.status not in ("departed", "expelled", "voided"):
            return out("refused", f"✘ {login} is a member already: there is nothing to apply for", 1,
                       refused=f"{login} is a member already: there is nothing to apply for")
        if st.invited(login, now):
            inv = st.invitations[login]
            msg = (f"{login} is invited already (by {inv['by']}, until "
                   f"{A.iso(st.due(inv['time'], A.INVITE_EXPIRY_DAYS * A.DAY))}): petition with {OM} join")
            return out("refused", f"✘ {msg}", 1, refused=msg)
    else:
        warnings.append("the fraternity has not been founded yet: nobody can invite you until it is")
    try:
        with open(Path(a.text).expanduser(), encoding="utf-8") as f:
            source = f.read(64 * 1024)
    except (OSError, UnicodeDecodeError) as err:
        msg = f"cannot read {a.text}: {getattr(err, 'strerror', None) or err}"
        return out("refused", f"✘ {msg}", 1, refused=msg)
    if not source.strip():
        return out("refused", f"✘ {a.text} is empty", 1, refused=f"{a.text} is empty")
    problems = application_problems(source, login)
    if problems:
        return out("refused", "✘ " + "\n✘ ".join(problems) + "\n(om apply never edits the text: the person does)", 1,
                   refused=problems[0])
    text = source.strip()
    body = application_body(text)
    if getattr(a, "check", False):
        return out("checked", f"Title: {title}\n\n{body}\nValid: nothing was opened or asked.", 0, body=body)
    if getattr(a, "web", False):
        import urllib.parse
        import webbrowser
        url = (f"https://github.com/{canon.CANONICAL_REPO}/issues/new?"
               + urllib.parse.urlencode({"template": "application.yml", "title": title, "introduction": text}))
        if len(url) > 8000:
            return out("refused", "✘ the application is too long for a link: use om apply without --web", 1,
                       refused="the application is too long for a link")
        opened = False
        try:
            opened = webbrowser.open(url)
        except webbrowser.Error:
            opened = False
        return out("opened_in_browser", ("Opened the application form in your browser: tick the three statements "
                                        "yourself and submit it." if opened else f"Open this link in your browser, "
                                        f"tick the three statements yourself and submit the form:\n{url}"), 0, body=body)
    found = applications(login)
    if found is None:
        warnings.append("could not ask GitHub for an earlier application of yours")
    else:
        open_ = next((x for x in found if x["state"] == "open"), None)
        if open_:
            msg = f"you already have an open application: {open_['url']}. Add to it there, or close it first"
            return out("refused", f"✘ {msg}", 1, refused=msg)
        if found:
            warnings.append(f"you applied before: {found[0]['url']} (closed)")
    scopes = gh_scopes()
    if scopes is not None and not scopes & {"repo", "public_repo"}:
        msg = "the gh token cannot open issues (no repo scope): run, in your own terminal: " + cmdline(LOGIN_COMMAND)
        return out("refused", f"✘ {msg}", 1, refused=msg)
    dialog = (f"This opens a PUBLIC issue on github.com/{canon.CANONICAL_REPO} as {login},\n"
              "with your text below. It stays public; you may close it, but it is not erased.\n\n"
              "By publishing you state that:\n"
              " • you are an adult: 18 years old, or the age of majority where you live,\n   whichever is higher;\n"
              " • you understand that membership is a public roll under the name\n   OpenMasonry, and that this issue "
              "is public;\n • you have put no personal data in it.\n\n"
              "Where any association with Freemasonry or a fraternal order is dangerous,\nthink before you publish. An "
              "application gives no right to an invitation,\nand it may be closed after 60 days without one.\n\n"
              f"--- your text ---\n{text}")
    if A._ask("OpenMasonry: publish your application?", dialog, ["Publish my application"], a.ledger, limit=3000) is None:
        return out("canceled", "Canceled. Nothing was published.", 1, body=body)
    fd, tmp = tempfile.mkstemp(prefix="om-apply-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        r = _run(["gh", "issue", "create", "--repo", canon.CANONICAL_REPO, "--title", title, "--body-file", tmp])
    finally:
        Path(tmp).unlink(missing_ok=True)
    if not _ok(r):
        why = _first(r.stderr or r.stdout)
        return out("failed", f"✘ GitHub did not open the issue: {why}", 1, refused=why, body=body)
    url = _first(r.stdout)
    m = re.search(r"/issues/(\d+)", url)
    return out("published", f"✔ published your application: {url}", 0,
               issue={"number": int(m.group(1)) if m else None, "url": url}, body=body)


# ------------------------------------------------- what `om me` adds for a non-member --

def onboarding_info(a, st, login: str, now: datetime) -> dict:
    """The `onboarding` field of om.me/2 for a person who is not a member: the key `om` would sign with, whether
    GitHub lists it, and their newest application. GitHub is asked only about the repository's own ledger (never
    about a scratch ledger), and nothing here changes anything."""
    from . import actions as A
    online = A.is_repo_ledger(a.ledger)
    if getattr(a, "login", None) and not getattr(a, "key", None):
        # Asked about a login by name (`om me --login L`): this machine's key need not be theirs.
        found = applications(login) if online else None
        app = found[0] if found else None
        return {"stage": "invited" if st.invited(login, now) else "applied" if is_open(app) else "not_applied", "key": None,
                "application": app, "application_checked": found is not None}
    path = A.key_path(getattr(a, "key", None))
    key = {"path": str(path), "fingerprint": None, "listed": None}
    try:
        bare = A.bare_public_key(path)
        key["fingerprint"] = A.fingerprint(bare) if A.key_kind(bare) else None
    except A.UserError:
        bare = None
    if online and key["fingerprint"]:
        listing = keys_listed(login)
        key["listed"] = None if listing is None else bare.split()[1] in listing
    found = applications(login) if online else None
    app = found[0] if found else None
    stage = ("no_key" if not key["fingerprint"] else "key_not_on_github" if key["listed"] is False else
             "invited" if st.invited(login, now) else "applied" if is_open(app) else "not_applied")
    return {"stage": stage, "key": key, "application": app, "application_checked": found is not None}


def doctor_checks(login: str | None) -> list[dict]:
    """The checks `om doctor` shares with `om onboard`: OpenSSH (and that `ssh-keygen -Y sign` works), git, its
    identity and credentials, a token in the environment, and this clock against GitHub's."""
    out = [openssh(), check_git()]
    if out[-1]["status"] == "ok":
        user = gh_user() if login and not os.environ.get("OM_LOGIN") else None
        out += [git_identity(login, user[1] if user and user[0] == login else None), git_credentials(login is not None)]
    out += [check_gh_token_env(), check_clock()]
    return [c for c in out if c["status"] != "skip"] + [
        check("clock", "warn", c["message"]) for c in out if c["status"] == "skip"]
