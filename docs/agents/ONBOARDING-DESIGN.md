# Design: `om onboard`, `om apply` and the Guide's steps for an outsider

Status: **implemented** in `src/openmasonry/onboard.py` (with `actions.py` and `guide.onboarding_steps`), tested in `tests/test_onboard.py`. Section 7 states the details of the build that sections 1 to 4 leave open or state otherwise; where they disagree, section 7 and the code are right. The `om-onboard` skill ([skills/om-onboard/SKILL.md](../../skills/om-onboard/SKILL.md)) and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) describe the commands as built.

## Goal and constraints

A person with only a GitHub account logged in on their computer, and an agent, must reach membership with the agent doing every technical step. Two commands close the gaps the person cannot be expected to bridge alone:

- `om onboard`: checks the machine, the GitHub login and the member key, creates the key in the person's own terminal, uploads its public half after a dialog approval, records which key `om` signs with, and says the next step.
- `om apply`: publishes the person's own application text as the public application, after a dialog approval.

Constraints, inherited from the rest of `om`:

1. **Outside the pinned core.** Both commands live in the command line (`onboard.py`, beside `actions.py`), never in a file of `src/openmasonry/protocol.manifest`, and nothing in the core imports them. They add no rule: what the ledger accepts is unchanged.
2. **Standard library and OpenSSH only**, plus `git`, `gh` and `curl` through `subprocess`, like the rest of `actions.py`. Every external call goes through one seam (`_run(argv, **kw)`) that the tests replace; the tests never use the network.
3. **No secret passes through `om`.** It never reads a private key, never sees a passphrase, token or 2FA code, and never pipes one. `ssh-keygen` runs with the person's own terminal attached, or not at all.
4. **Outward acts need the dialog.** Uploading a key and publishing an application each go through `_ask` (the same native dialog or typed code as `om approve`). The test-mode bypass is the existing one (`_test_mode`), and nothing new can enable it.
5. **Idempotent.** Running `om onboard` again changes nothing that is already right, and each run reports the same checks in the same order.

## 1. `om onboard`

### Synopsis

```
bin/om onboard [--json] [--login LOGIN] [--key PATH]
               [--create-key [PATH]] [--hardware]
               [--use-key PATH]
               [--upload]
```

| Flag | Effect |
|---|---|
| (none) | run every check, change nothing, print the next step |
| `--create-key [PATH]` | create the member key at PATH (default `~/.ssh/openmasonry_ed25519`, or `~/.ssh/openmasonry_ed25519_sk` with `--hardware`), interactively in the person's terminal, then record it (below) |
| `--hardware` | with `--create-key`: `-t ed25519-sk` |
| `--use-key PATH` | record an existing key as the member key (checked first: Ed25519, `PATH.pub` present) |
| `--upload` | upload the public key to the active GitHub account as an authentication key, after a dialog approval |
| `--key PATH` | the key to check, as for every member command (does not record it) |
| `--json` | print `om.onboard/1` |

Flags combine: `bin/om onboard --create-key --upload` creates, records, asks, uploads and checks, in that order, stopping at the first step that fails or that needs the person.

### The checks, in order

Each check has an `id`, a `status` (`ok`, `warn`, `fail`, `skip`) and, unless `ok`, a `fix`. A `fail` blocks the stages after it; a `warn` never does. A check whose inputs are missing is `skip` with the `id` of the check it waits for.

| # | `id` | How | `fail` / `warn` when | `fix` |
|---|---|---|---|---|
| 1 | `platform` | `sys.platform`; WSL when `/proc/version` contains `microsoft`; the approval channel `_ask` would use: `macos` (darwin with `osascript` and a desktop session: `launchctl managername` prints `Aqua`), `zenity`, `kdialog`, `terminal` (`/dev/tty` opens), else `none` | `fail` only when the channel is `none`; `warn` on macOS without a desktop session (approvals then use the typed code, fix F1). Native Windows is supported: channel `windows` (PowerShell) or `console` (see "Native Windows" in section 4) | `none`: "run bin/om in a terminal of your own" |
| 2 | `python` | `sys.version_info` | `fail` below 3.11 (unreachable through `bin/om`, kept for direct runs) | install hint per platform |
| 3 | `git` | `git --version` | `fail` when missing or below 2.23 (`git switch`) | install hint |
| 4 | `git_identity` | `git config user.name`, `git config user.email` in the clone | `fail` when either is unset; `warn` when the e-mail is not a `users.noreply.github.com` address (it is published in the commit) | `git config user.name LOGIN`, `git config user.email ID+LOGIN@users.noreply.github.com` (argv, run only after the person agrees) |
| 5 | `git_signing` | `git config --get commit.gpgsign` | `warn` when `true` | `git config commit.gpgsign false` in the clone |
| 6 | `openssh` | `ssh -V` (stderr), parsed `OpenSSH_X.Y`; then the throwaway test: a key made with `ssh-keygen -q -t ed25519 -N '' -C test -f TMP/k` in a fresh temporary directory signs `TMP/m` with `ssh-keygen -q -Y sign -f TMP/k -n openmasonry TMP/m`; the directory is removed | `fail` when `ssh-keygen` or `ssh-add` is missing, below 8.2, or the test does not write `m.sig` | install hint |
| 7 | `gh` | `gh --version` | `fail` when missing; `warn` below 2.40 | install hint (official repository on Linux) |
| 8 | `gh_token_env` | `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN` in the environment | `warn` when one is set (it overrides the login) | "unset GH_TOKEN GITHUB_TOKEN, and remove it from your shell profile" |
| 9 | `gh_login` | `gh api user --jq '[.login, (.id|tostring)] \| join(" ")'` | `fail` when it fails | person command: `gh auth login --hostname github.com --git-protocol https --web --scopes admin:public_key` |
| 10 | `account` | the login against `ledger.LOGIN_RE` | `fail` when it does not match (a managed account's `_`) | "use a personal GitHub account" |
| 11 | `gh_scopes` | `gh api -i user`, header `X-OAuth-Scopes` | `fail` without `repo` or `public_repo`; `warn` without `admin:public_key` or `write:public_key` while the key is not listed; `skip` when the header is absent (a token type without scopes) | person command: `gh auth refresh --hostname github.com --scopes admin:public_key` |
| 12 | `git_credentials` | `git config --get-all credential.https://github.com.helper` contains `gh auth git-credential` | `fail` when not | `gh auth setup-git` |
| 13 | `clone` | inside a clone (`canon.ROOT/.git`); `canonical_remote()` | `fail` without the canonical remote | `git remote add upstream https://github.com/openmasonry/openmasonry.git` |
| 14 | `clean` | `git diff --cached --quiet`; `git status --porcelain -- ledger/` | `fail` when something is staged or `ledger/` is dirty | `git restore --staged .`; "never edit ledger/entries" |
| 15 | `clock` | the `Date` header of `https://api.github.com` against `now_utc()` | `fail` when this clock is more than 90 seconds ahead or 30 minutes behind; `warn` above 30 seconds either way; `skip` offline | per platform: automatic time (macOS settings, `sudo timedatectl set-ntp true`, `sudo hwclock -s` in WSL) |
| 16 | `key` | `key_path(--key)`, its source (`flag`, `env`, `config`, `default`), `PATH.pub` exists, `key_kind` | `fail` when missing or not Ed25519 | `bin/om onboard --create-key`, or `--use-key PATH` |
| 17 | `key_mode` | `os.stat(PATH)` mode (never opens it) | `warn` when group or others can read it | `chmod 600 PATH` |
| 18 | `key_agent` | `ssh-add -L` holds the public blob | `warn` when not (signing will ask for the passphrase) | person command per platform: `ssh-add --apple-use-keychain PATH` (macOS), `ssh-add PATH` |
| 19 | `key_listed` | `curl -fsS --max-time 10 https://github.com/LOGIN.keys` holds the blob | `fail` when not listed; `skip` offline | `bin/om onboard --upload` |
| 20 | `key_ledger` | `State.key_holders(key)` and `State.known_keys` | `fail` when another login holds it or the ledger ever held it; for a member, `fail` when the ledger holds another key for them (the `key_advice` text) | a new key; for a member, `bin/om rekey` (never done by onboard) |
| 21 | `ledger` | `state_of`, `canonical_status` | `fail` on `invalid`, a `BLOCKING` verdict, `behind`, `diverged`, `no_remote`; `warn` on `offline` | the message of `canonical_status` |

### Creating the key (`--create-key`)

1. Refuse when `PATH` or `PATH.pub` exists: `PATH already exists: om never overwrites a key. Use it with --use-key PATH, or choose another path with --create-key PATH`.
2. The argv is exactly `["ssh-keygen", "-t", "ed25519", "-C", "openmasonry", "-f", PATH]` (with `--hardware`, `-t ed25519-sk`). Never `-N`, never `-O no-touch-required`, never `-P`.
3. Run it only when `sys.stdin.isatty()` and `sys.stdout.isatty()` are both true and `/dev/tty` opens, with the terminal inherited (no pipes): `ssh-keygen` then asks for the passphrase on the person's terminal. Otherwise do not run it: status `needs_person`, exit 1, and print `no terminal to ask for a passphrase: run this in your own terminal, then run bin/om onboard again:` followed by the shell-quoted argv.
4. After it: check `PATH.pub` (`key_kind` must accept it), `chmod 600 PATH` when its mode is wider, and record it (below). Print the fingerprint (`fingerprint()`).

### Recording the key

`om` already reads `CONFIG["key"]` (`key_path`). `om onboard` writes it with `_write_private`, keeping every other field, under these rules:

- `CONFIG` has no `key`, or its `key` names a file that does not exist: write it.
- `CONFIG["key"]` names another existing key: write it only with `--use-key` or `--create-key`, and only when the person is not a member. A member's key is changed only by `om rekey` or a recovery; `om onboard` refuses with `you are a member and the ledger holds another key for you: om onboard never changes your key (that is bin/om rekey)`. When the new key equals the ledger's key for the member, writing it is allowed (it repairs a configuration).
- Never write `previous_key` or `recovery_key`.
- When `OM_KEY` is set and names another key, print `note: OM_KEY still names X; unset it, or point it to Y` (as `om approve` does after a rekey).

### Uploading the public key (`--upload`)

1. Preconditions, each with its message: a login (check 9), a valid key (check 16), not already listed (check 19: then nothing to do, status `ok`), the scope (check 11: `uploading a key needs the admin:public_key scope: run, in your own terminal: gh auth refresh --hostname github.com --scopes admin:public_key`).
2. The dialog, through `_ask("OpenMasonry: add this key to GitHub?", text, ["Add the key"], ledger)`, with `text`:

   ```
   Add this public key to the GitHub account LOGIN as an authentication key?

     TYPE  FINGERPRINT
     from PATH.pub

   GitHub then lists it publicly at https://github.com/LOGIN.keys, which is
   what OpenMasonry's judge reads. An authentication key can also open SSH
   sessions to your repositories: keep its private half to yourself.
   You can remove it later in GitHub's settings (SSH and GPG keys).
   ```

3. On approval: `gh ssh-key add PATH.pub --type authentication --title OpenMasonry`. On failure: `GitHub refused the key: FIRST-LINE-OF-STDERR` (and, for `key is already in use`: `… it is on another GitHub account already; create a new key for this one`).
4. Then fetch `.keys` every 5 seconds for at most 60 seconds. Listed: `ok`. Not yet: status `warn`, `the key was added but is not listed at https://github.com/LOGIN.keys yet: run bin/om onboard again in a minute`.
5. Canceled: `Canceled. Nothing was uploaded.`, exit 1.

### Stage and next step

After the checks, `om onboard` names one stage, the first that holds:

| `stage` | When | `next` |
|---|---|---|
| `tools` | a `fail` among checks 1–8, 12–14 | the first failing check's fix |
| `login` | check 9 or 10 fails | the login command (person) |
| `no_key` | check 16 fails | `bin/om onboard --create-key` (or `--hardware` if the person chose a token) |
| `key_not_on_github` | check 19 fails | `bin/om onboard --upload` |
| `not_applied` | not a member, no live invitation, no application found | `bin/om apply --text FILE` |
| `applied` | an application by this account exists (open or closed), no live invitation | wait; nothing to run |
| `invited` | a live invitation for this login | `bin/om join` (due by the invitation's lapse) |
| `petitioned` | a petition is pending or waiting in the outbox | hand over to the Guide (`bin/om me`) |
| `member` | a member record | hand over to the Guide |

`applied` and `not_applied` come from `gh issue list --repo openmasonry/openmasonry --author @me --state all --search 'in:title "Application:"' --json number,url,state,createdAt,title --limit 5`, keeping issues whose title starts with `Application:`. When GitHub cannot be reached, the stage is `not_applied` with `"application_checked": false`.

### Exit status

0 when no check is `fail` (warnings allowed); 1 otherwise, also when a step needs the person; 2 for a malformed command line. Never 3 (`om onboard` makes no draft).

### Text output

The same marks as `doctor` (✔, ·, ✘), one line per check, then:

```
Stage: key_not_on_github
Next:  bin/om onboard --upload   (adds your key to GitHub after you approve in a dialog)
```

When the next step is the person's: `Next (in your own terminal): …`.

### `om.onboard/1`

```json
{
  "schema": "om.onboard/1",
  "stage": "key_not_on_github",
  "login": "LOGIN",
  "github_id": 123456,
  "platform": {"os": "linux", "wsl": false, "dialog": "zenity"},
  "key": {"path": "~/.ssh/openmasonry_ed25519", "source": "config", "type": "ssh-ed25519",
          "fingerprint": "SHA256:…", "in_agent": true, "listed": false},
  "application": null,
  "application_checked": true,
  "invitation": null,
  "checks": [
    {"id": "openssh", "status": "ok", "message": "OpenSSH 9.7, ssh-keygen -Y works", "fix": null},
    {"id": "key_listed", "status": "fail", "message": "the key is not listed at https://github.com/LOGIN.keys",
     "fix": {"kind": "command", "argv": ["bin/om", "onboard", "--upload"], "person": false, "public": true,
             "text": "adds the key to GitHub after the person approves in a dialog"}}
  ],
  "next": {"action": "upload_key", "why": "…", "argv": ["bin/om", "onboard", "--upload"], "person": false,
           "public": true, "due_by": null},
  "changed": []
}
```

- `checks[]` is in the order of the table, every check present (`skip` when not reached).
- `fix.kind` is `command` (the agent may run `argv`, after asking when `public` is true), `person_command` (the person runs `argv` in their own terminal: logins, `ssh-keygen`, `ssh-add`, installs that need an administrator password), `setting` (a change in a system settings screen, in `text`) or `read` (a page to read, in `text`).
- `argv` is always a list, never a shell string.
- `changed[]` lists what this run changed: `key_created`, `config_written`, `key_uploaded`.
- `key.listed` and `key.in_agent` are `null` when not checked.
- `application` is `{"url", "number", "state", "created_at"}` of the newest application by this account, or null.
- `invitation` is the `invitation` object of `om.me/2`.

## 2. `om apply`

### Issue or Discussion: the recommendation

**Keep the application an issue**, opened from the existing form (`.github/ISSUE_TEMPLATE/application.yml`) or by `om apply` with `gh issue create`.

- The form exists, is versioned in the repository, applies the `application` label, and makes the three statements (adult, public roll, no personal data) required checkboxes. Discussion categories, and the forms of `.github/DISCUSSION_TEMPLATE/`, depend on categories that are created in the web settings and cannot be reproduced from the repository.
- `gh` creates issues natively (`gh issue create`); it has no command to create a discussion, which would need the GraphQL `createDiscussion` mutation with the repository's and the category's node ids.
- The Guide (`guide.APPLY_URL`), the README, START.md, the wiki and the form's own links already point to the issue form; changing the channel would change all of them for no gain.
- Issues have what moderation needs here: closing, locking, labels, interaction limits (LAUNCH.md) and search by author (`--author`), which the Guide uses to tell `applied` from `not_applied`.
- Discussions stay what LAUNCH.md says they are for: getting to know applicants and debating. A member may start a discussion with an applicant and link it from the issue.

One limit: an account without triage rights cannot set labels, through `gh` or through a URL. An issue opened by `om apply` therefore carries no label; it is recognized by its title, `Application: @LOGIN`, and its author. A maintainer may add the label. `--web` (below) opens the form itself, which applies the label.

### Synopsis

```
bin/om apply --text FILE [--check] [--web] [--json] [--login LOGIN]
```

| Flag | Effect |
|---|---|
| `--text FILE` | the person's own text, UTF-8 (required) |
| `--check` | validate and print the exact title and body, open nothing, ask nothing (exit 0 when valid). The agent shows this to the person before anything else |
| `--web` | instead of the dialog and `gh issue create`, open the application form in the browser with the text prefilled (`?template=application.yml&title=…&introduction=…`); the person ticks the statements and submits it themselves |
| `--json` | print `om.apply/1` |

### Order of checks, with their messages

1. Login (`need_login`); the login matches `LOGIN_RE`.
2. Not a member: `LOGIN is a member already: there is nothing to apply for`.
3. No live invitation: `LOGIN is invited already (by BY, until DATE): petition with bin/om join`.
4. Before genesis (the ledger is empty): a warning, `the fraternity has not been founded yet: nobody can invite you until it is`.
5. No open application by this account (`gh issue list … --author @me --state open`): `you already have an open application: URL. Add to it there, or close it first`. A closed one gives a warning with its URL.
6. The text:
   - readable UTF-8, not empty: `cannot read FILE: …`, `FILE is empty`;
   - at most 1,200 characters after trimming, so that the whole text shows in the dialog: `the application is N characters; keep it under 1200 (a few sentences are enough)`;
   - no control characters other than line feed and tab: `the application holds a control character: it must be plain text`;
   - no e-mail address (`[^\s@]+@[^\s@]+\.[A-Za-z]{2,}`): `the application holds an e-mail address: give no personal data`;
   - no phone-like number (nine or more digits, optionally separated by spaces, dots, dashes or parentheses, with an optional `+`): `the application holds what looks like a phone number: give no personal data`;
   - no `@mention` of another account (`(?<![\w/])@[A-Za-z0-9-]+` other than the person's own login): `the application mentions @X: an application speaks for its author and calls on no one`.
   Each refusal names the line. `om apply` never edits the text: the person does.
7. `gh` can create issues (check 11 of `om onboard`: `repo` or `public_repo`).

### The dialog

`_ask("OpenMasonry: publish your application?", text, ["Publish my application"], ledger)`, with `_ask` gaining a `limit` parameter (default 1500) so that this dialog shows the whole text (limit 3000). `text`:

```
This opens a PUBLIC issue on github.com/openmasonry/openmasonry as LOGIN,
with your text below. It stays public; you may close it, but it is not erased.

By publishing you state that:
 • you are an adult: 18 years old, or the age of majority where you live,
   whichever is higher;
 • you understand that membership is a public roll under the name
   OpenMasonry, and that this issue is public;
 • you have put no personal data in it.

Where any association with Freemasonry or a fraternal order is dangerous,
think before you publish. An application gives no right to an invitation.

--- your text ---
TEXT
```

Canceled: `Canceled. Nothing was published.`, exit 1.

### Publishing

The body mirrors the form, so that an application looks the same whichever way it came:

```
### Introduce yourself, in your own words

TEXT

### Before you submit

- [X] I am an adult (18 years old, or the age of majority where I live, whichever is higher).
- [X] I understand that membership is a public roll under the name OpenMasonry, and that this issue is public.
- [X] I have put no personal data in this issue.

<sub>Opened with `om apply` after the author approved it in a dialog.</sub>
```

The command is `gh issue create --repo openmasonry/openmasonry --title "Application: @LOGIN" --body-file TMP` (the body in a private temporary file, removed afterwards; never on the command line). The statement lines are copied from `application.yml` when the command runs, so that a change of the form changes them too (a test holds the two equal).

`--web` builds the URL with `urllib.parse.urlencode({"template": "application.yml", "title": "Application: @LOGIN", "introduction": TEXT})` and opens it with `webbrowser.open`; it refuses when the URL is longer than 8,000 characters, and prints the URL when no browser opens.

### Exit status and `om.apply/1`

0 when published (or opened in the browser, or valid under `--check`); 1 when refused, canceled or when `gh` failed; 2 for a malformed command line.

```json
{
  "schema": "om.apply/1",
  "status": "published",
  "login": "LOGIN",
  "title": "Application: @LOGIN",
  "body_sha256": "…",
  "characters": 412,
  "issue": {"number": 42, "url": "https://github.com/openmasonry/openmasonry/issues/42"},
  "warnings": [],
  "refused": null
}
```

`status` is one of `checked` (`--check`), `published`, `opened_in_browser`, `canceled`, `refused` (with `refused` holding the message) or `failed` (with `refused` holding `gh`'s first line of error). `issue` is null unless `published`.

## 3. The Guide's steps for an outsider (`om me`)

`om.me/2` gains, additively, `onboarding` (null for a member): `{"stage", "key": {"path", "fingerprint", "listed"}, "application", "application_checked"}`, with `stage` and `application` as in `om.onboard/1`. The key listing is fetched only for a person who is not a member. The steps, by stage, with their exact `why`:

| Stage | `action` | `why` | `argv` / `needs` | `public` |
|---|---|---|---|---|
| no key (looked for PATH) | `setup` | `You have no signing key yet (om looked for PATH). You need one only to petition, once invited; set it up now or later.` | `["bin/om", "onboard", "--create-key"]` | false |
| key not on GitHub | `setup` | `Your key FINGERPRINT is not listed at https://github.com/LOGIN.keys: the judge refuses a petition whose key is not listed there. Adding it asks you first.` | `["bin/om", "onboard", "--upload"]` | true |
| not applied | `apply` | `OpenMasonry admits by invitation. Introduce yourself, in your own words, in a public application: write it in a file and publish it (you approve it in a dialog), or use the form at APPLY_URL. Membership is a public roll under the name OpenMasonry; adults only; no personal data.` | `["bin/om", "apply", "--text"]`, needs `["FILE"]` | true |
| not applied, GitHub not reached | `apply` | the same, preceded by `Could not check GitHub for an earlier application of yours. ` | as above | true |
| applied | `wait` | `You applied on DATE (URL). An application gives no right to an invitation: a Master Builder who comes to answer for you may invite you. Meanwhile you may take part in the public work.` | `[]` | false |
| invited | `join` | `Invited by BY — join before EXPIRES_AT. Read the Declaration; if you agree, petition for admission.` | `["bin/om", "join"]`, `due_by` the lapse | true |
| invited, key not ready | `setup` first, then `join` | the `setup` text of its case, then the `join` text | as above | as above |
| petitioned, member | unchanged | the existing steps (`find_sponsors`, `wait`, the ballot) | | |

The existing texts for a lapsed invitation, a refused ballot and a lapsed petition stay, prefixed to the `apply` step as today. When a `setup` step comes before a `join` and the invitation lapses within 24 hours, the `setup` step's `why` ends with `Your invitation lapses at EXPIRES_AT.`

Errors `om me` already raises stay as they are: `cannot tell your GitHub login: run gh auth login, or pass --login / set OM_LOGIN`, and before genesis `The ledger is empty: the fraternity has not been founded yet.`

## 4. Fixes that came with these commands

Problems of the command line that these commands needed solved; each is outside the pinned core, and each is implemented as section 7 states.

- **MacOS without a desktop session.** `_ask` treats any `osascript` failure as Cancel, so approving over SSH on a Mac returns `Canceled` at once. Distinguish the user's Cancel (`osascript` error -128) from "no user interaction allowed" (-1713) and other failures, and fall back to `/dev/tty` for the latter.
- **Native Windows.** `_ask` has no Windows path and `/dev/tty` does not exist there. Add a dialog (PowerShell with `System.Windows.Forms.MessageBox` and a per-run code in the button text, or `msvcrt` reading from `CONIN$` for the typed code), or refuse early with a message that names WSL. `bin/om` is a POSIX shell script and does not try `python` or `py`.
- **The fork's name.** `_push_target` assumes the fork is `LOGIN/openmasonry`. `gh repo fork` with a repository argument adds no remote, and when the account already has an unrelated repository of that name GitHub names the fork `openmasonry-1`; `om` then adds a remote to the unrelated repository and pushes the branch there. Find the fork from `gh api repos/LOGIN/NAME --jq .parent.full_name` (or `gh repo list LOGIN --fork --json nameWithOwner,parent`), accept a `fork` remote whose repository's parent is the canonical one, and never push to a repository that is not a fork of it.
- **The fork's owner after a rename.** `_submit` uses the entry's actor as the fork owner. A person renamed after the invitation petitions as the old login (`--login`), so the fork remote and `--head` name the old login. Use the active `gh` account (`detect_login`) as the fork owner, as is already done for custodian entries.
- **A failed push.** When a git step of `_submit` fails, `om` switches back and the committed entry file leaves the working tree; `om submit` then finds nothing, and the branch `om/LOGIN/SEQ` stays and blocks the next attempt at that seq (`git switch -c` fails). Add `om pending --publish SEQ` (push the existing branch, open the pull request) or make `om submit` recognize the outbox entry and its branch; reuse or replace the branch when it exists.
- **Git identity and credentials.** `doctor` checks neither `user.name`/`user.email` (the commit fails without them, and a personal e-mail becomes public), nor the HTTPS credential helper (the push prompts for a password). `om onboard` checks both; `doctor` should at least say so.
- **`doctor` and OpenSSH.** `doctor` crashes with `FileNotFoundError` when `ssh-add` is missing, does not check the OpenSSH version, and does not prove `ssh-keygen -Y sign` works. Guard the `ssh-add` call; reuse check 6.
- **A renamed account and `om join`.** The local check `st.invited(login)` uses the active account's login, so a person renamed after the invitation gets `no live invitation`. Fall back to the invitation whose `github_id` is the active account's id (`gh api user --jq .id`) and use that login as the actor, which the judge already accepts (SPEC section 9.3).
- **The clock.** Nothing on the client warns that this machine's clock is ahead: an entry stamped more than 2 minutes ahead of the judge is refused only after the pull request is opened. `om approve` (or `propose`) should compare with GitHub's `Date` header when online and refuse to sign beyond 90 seconds ahead.
- **The PR body.** `_submit` writes "a maintainer merges it", but a ledger-only pull request merges itself when the judge passes: say "the judge checks it; it merges itself when the judge passes".

## 5. Tests

- Every external call through `_run`, replaced in tests by a table of argv → (code, stdout, stderr); no network, no real `gh`, no real `ssh-keygen` except check 6 in a temporary directory (skipped when OpenSSH is missing).
- `om onboard`: each check's statuses; the stage table; idempotence (two runs, same report, `changed` empty the second time); `--create-key` refuses an existing path and never runs without a terminal; `--upload` cancels on `None` from `_ask` and never calls `gh ssh-key add` then; recording rules for a member and a non-member; the `om.onboard/1` contract field by field.
- `om apply`: every refusal of section 2 with its message; the body equals the form's statements; `--check` opens nothing; cancel publishes nothing; the temporary body file is removed.
- `om me`: the steps of section 3 for each stage; `onboarding` is null for a member; no network call for a member.
- `tests/test_cli_custodian.py`-style guard: none of the new steps is an objection, a co-signature, a removal or a correction.

## 6. Documents that describe these commands

`skills/om-onboard/SKILL.md` (the key, upload and application steps), `docs/agents/TROUBLESHOOTING.md`, `docs/agents/START.md` (sections 2 and 4), `skills/om/SKILL.md` (the outsider's steps), the README's command list, and the application form (`.github/ISSUE_TEMPLATE/application.yml`), whose statements `om apply` copies. A change of these commands changes them too.

## 7. As built

- **Native Windows is supported** (see "Native Windows" in section 4): `bin/om.cmd` finds Python 3.11+ through `OM_PYTHON`, `py -3` or `python`; `_ask` shows a Windows Forms window through PowerShell (title, text and buttons passed in the environment, Cancel first and default) and falls back to a code typed in the console (`CONIN$`/`CONOUT$`, never stdin). The `platform` check fails only when no channel exists.
- **macOS without a desktop session**: only `osascript`'s error -128 is Cancel; any other failure falls back to `/dev/tty`.
- **The seam** is `onboard._run(argv, capture=True)`: a missing program answers exit code 127. `doctor` and `approve` reuse `openssh`, `git_identity`, `git_credentials`, `check_gh_token_env` and `github_clock_skew` (`onboard.doctor_checks`).
- **Applications** are looked up with `--author LOGIN` (not `@me`), so `om me --login L` asks about L. `om me` asks GitHub (the `.keys` listing, the application) only about the repository's own ledger, never a scratch one; asked about a login by name without `--key`, it leaves the key out (`onboarding.key` is null) and adds no `setup` step.
- **`next`** of `om.onboard/1` also carries `text` (the fix's words when there is no command). Progress lines of `--create-key` and `--upload` go to stderr, so `--json` prints only the report.
- **The `setup` step before `join`** always ends with `Your invitation lapses at EXPIRES_AT.` (not only in the last 24 hours), and carries the invitation's `due_by`.
- **The fork's name**: the fork is found from the remotes whose repository GitHub names as a fork of the canonical one (`.parent.full_name`), else from `repos/openmasonry/openmasonry/forks` filtered by owner; after `gh repo fork` (no remote) it is looked up again for half a minute. Its remote is `fork`, or `fork-2` when `fork` points elsewhere. Nothing is pushed to a repository that is not a fork of the canonical one.
- **The fork's owner after a rename**: the publishing account is the active `gh` account (`detect_login`), for every entry.
- **A failed push**: `om pending --publish SEQ` pushes the branch of a signed entry whose push or pull request failed and opens the pull request (or says it is open); without the branch it writes the entry back from the outbox (a correction, whose reason travels with it, is dropped and drafted again). `_submit` reuses a branch `om/LOGIN/SEQ` that holds exactly the entry's files and replaces one that does not; every failure message names `--publish`.
- **Git identity and credentials**: `approve` refuses before signing when git has no name or e-mail, or no credentials for github.com (`gh auth setup-git`); a personal e-mail is a note. `doctor` shows the same checks.
- **`doctor` and OpenSSH**: `doctor` never crashes without `ssh-add` or `curl`, checks OpenSSH's version and `-Y sign`, and says "could not read …keys" instead of "add this key" when the listing cannot be read.
- **A renamed account and `om join`**: `om join` without `--login`/`OM_LOGIN`, when the active login holds no invitation, takes the live invitation whose `github_id` is the active account's id, and says so.
- **The clock**: `approve` reads GitHub's clock (the `Date` header of api.github.com, through `curl`) and refuses a draft stamped more than 90 seconds ahead of it (the judge's limit is 2 minutes), and one too old by GitHub's clock; it warns above 30 seconds of skew; offline it decides nothing.
- **The PR body**: the pull request body says the judge checks the entry and that it merges itself when the judge passes.
- **A token in the environment**: `detect_login` prints one note when `GH_TOKEN`, `GITHUB_TOKEN` or `GH_ENTERPRISE_TOKEN` is set.
- **A wrong configured key** is refused when a member's act is drafted (with the `key_advice` text and a pointer to `bin/om doctor`), not only at approval.
