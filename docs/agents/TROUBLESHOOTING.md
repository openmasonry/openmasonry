# Troubleshooting: setup, approval, pull requests and the judge

For agents helping a person set up, join or act in OpenMasonry. Start with `bin/om onboard --json` (a person who is not a member yet) or `bin/om doctor`: each failing check of `om onboard` carries its own fix. Then find the symptom here, read the cause, apply the fix: each fix is a command or a setting. The step-by-step setup is the `om-onboard` skill ([skills/om-onboard/SKILL.md](../../skills/om-onboard/SKILL.md)); the rules for every act are in [START.md](START.md).

Three rules hold for every fix below:

- **The person types every secret** (passphrase, password, token, 2FA code) and every approval, in their own terminal, browser or dialog. Commands marked *(person)* are theirs to run.
- **Never work around a refusal of the protocol** (`WOULD BE REFUSED`, `REFUSED`, `INVALID`): explain the rule. Never edit `ledger/entries/` or files under `~/.config/openmasonry/`, never set `OM_CONFIRM`.
- **Ask before anything outward-facing**: uploading a key, opening an issue or a pull request, closing a pull request.

## 0. Reading a failure

| What you see | Meaning |
|---|---|
| exit code 0 | done |
| exit code 3 and `DRAFT …` (or `om.draft/1` with `--json`) | a draft was stored; nothing was signed. The person approves it with `bin/om approve DIGEST` |
| exit code 1 and a line starting with `✘` (or `{"error": …}` with `--json`) | a problem the person can fix: this page |
| `WOULD BE REFUSED — entry N: …` (`{"refused": …}`) | the protocol forbids this act now: explain the rule in plain words (call the Counselor, `om-counselor`, if unsure) |
| `REFUSED — entry N: …` at approval | the signed entry would break a rule (the ledger moved, or a rule changed): draft again |
| `Canceled. Nothing was signed.` | the person pressed Cancel, or the dialog failed to show (section 4) |
| `✘ unexpected error: …` | a fault in `om` itself: run again with `OM_DEBUG=1` for the traceback, and report it (CONTRIBUTING.md) |
| exit code 130, `interrupted; nothing was signed` | Ctrl-C, or the harness killed the command |
| exit code 2 and a usage text | a flag or argument is wrong: `bin/om COMMAND --help` |

## 1. Tools and platform

| Symptom | Cause | Fix |
|---|---|---|
| `om needs Python 3.11 or newer …` | `bin/om` found no Python 3.11+ on the PATH. On macOS the `python3` of the command-line tools is 3.9; Ubuntu 22.04 ships 3.10 | install one (`brew install python@3.12`; `sudo apt install python3.11`; python.org), or point to it: `OM_PYTHON=/path/to/python3.12 bin/om doctor` |
| `bin/om: Permission denied` | the executable bit was lost (a copy, a zip, a Windows checkout) | `chmod +x bin/om`, or `sh bin/om doctor` |
| `✘ ssh-keygen and ssh-add not found` (or `✘ ssh-keygen not found`), `✘ OpenSSH X.Y is too old (8.1 or later)`, or `ssh-keygen: unknown option -- Y` | no OpenSSH, or one older than 8.1 (`ssh-keygen -Y sign` appeared in 8.1) | install the OpenSSH client (`sudo apt install openssh-client`, `sudo dnf install openssh-clients`; Windows: section 10); check with `ssh -V` |
| `✘ ssh-add not found` (`onboard`) / `· ssh-add not found: the ssh-agent was not checked` (`doctor`), or `✘ ssh-keygen cannot sign (-Y sign) …` | an incomplete or old OpenSSH | install the full OpenSSH client, 8.1 or later (8.2 for a hardware key) |
| `✘ git is not installed` (`doctor`: `✘ git is not installed (install git …)`; `onboard`: `✘ git is not installed  → install git …`) | no git on the PATH | install git (`xcode-select --install` or `brew install git`; `sudo apt install git`; `winget install Git.Git`); the checks that need git wait for it |
| a hardware key fails with `unknown key type` or `device not found` | OpenSSH older than 8.2, built without FIDO support, or the token is not plugged in | update OpenSSH (hardware keys need 8.2 or later); plug the token in; on Linux install `libfido2` (`sudo apt install libfido2-1`) |
| `git: 'switch' is not a git command` when publishing | git older than 2.23 | update git |
| `gh: unknown command "switch"` or `unknown flag: --type` | an old GitHub CLI from a distribution package | install a current one from the official repository of cli.github.com |
| `· curl not found: the key listing was not checked …` | `curl` is not installed | install `curl`, or check by hand in a browser: `https://github.com/LOGIN.keys` |
| `git clone` says `Repository not found` | a mistyped URL, or a fork that does not exist yet | clone `https://github.com/openmasonry/openmasonry.git` exactly; for a fork, wait a minute after creating it |

## 2. GitHub login and account

| Symptom | Cause | Fix |
|---|---|---|
| `✘ no GitHub login (gh auth login, or --login)` or `cannot tell your GitHub login: …` | `gh` is not logged in (`gh api user` fails) | *(person)* `gh auth login --hostname github.com --git-protocol https --web --scopes admin:public_key`; on a machine without a browser it prints a code for https://github.com/login/device, usable from any device |
| `gh auth status` lists several accounts; `doctor` shows the wrong login | the active account is not the one the person applies with | `gh auth switch --hostname github.com --user LOGIN` |
| `NOT PUBLISHED — an entry signed by the founder LOGIN is published only from the GitHub account with id N, but gh is logged in as OTHER (id M)`, or `… and gh cannot tell which account it is logged in as` (also for a custodian linked to a founder, for the genesis, which only the founding account of `src/openmasonry/network.toml` publishes, and for a petition: `a petition of LOGIN (by the account its invitation names) … with id N`, the id the invitation records, whatever record the login held before) | `approve`, `submit` and `pending --publish` publish a founder's entry only from the account the ledger records for that founder: a pull request from another account would tie the two accounts together in public, for good. Nothing was signed or published | *(person)* point gh at the right account: `gh auth switch --hostname github.com --user LOGIN`, or the separate configuration that holds it (`export GH_CONFIG_DIR=…`), and check with `gh api user --jq '[.login, .id]'`; then approve again, or `bin/om pending --publish SEQ` for an entry already signed. Never publish it from the other account by hand |
| `gh auth status` says the token comes from `GH_TOKEN` or `GITHUB_TOKEN` | a token in the environment overrides the login (wrong account, missing scopes) | `unset GH_TOKEN GITHUB_TOKEN`, and *(person)* remove it from the shell profile |
| `gh auth status` shows an old name; `gh api user --jq .login` shows another | the account was renamed and gh cached the old name | `gh auth logout --hostname github.com --user OLD-NAME`, then *(person)* log in again |
| `HTTP 404` or `This API operation needs the "admin:public_key" scope` from `gh ssh-key add` | the token lacks the key scope | *(person)* `gh auth refresh --hostname github.com --scopes admin:public_key` |
| `HTTP 403` / `Resource not accessible by personal access token` when forking or opening a pull request | a fine-grained token, or a classic token without `repo` / `public_repo` | *(person)* log in with the browser flow (`gh auth login --web`), or a classic token with `repo` |
| `Resource protected by organization SAML enforcement` | the token is not authorized for an organization's single sign-on. The canonical repository belongs to a user account, so this never concerns it | ignore it for OpenMasonry; for that organization, *(person)* `gh auth refresh` and authorize it in the browser |
| the login contains `_`; issues and forks of public repositories are refused | a managed (enterprise) account, which cannot act outside its enterprise; `om` refuses such a login | the person applies with a personal GitHub account |
| a 2FA prompt or a security key prompt in the browser | normal sign-in | *(person)* completes it; you never see the code |
| `gh auth login` hangs in your harness | it waits for a browser or a code | *(person)* runs it in their own terminal |

## 3. Keys and the ssh-agent

| Symptom | Cause | Fix |
|---|---|---|
| `✘ no key at PATH: bin/om onboard --create-key (or --use-key PATH)` | `om` looks for `--key`, else `OM_KEY`, else the configured key, else `~/.ssh/id_ed25519`; the member key is not named | `bin/om onboard --use-key PATH` (records an existing key for a person who is not a member), or *(person)* `bin/om onboard --create-key` |
| `public key PATH.pub not found …` (`doctor`: `✘ public key PATH.pub not found: ssh-keygen -y -f PATH > PATH.pub`) | the `.pub` file beside the key is missing | *(person)* `ssh-keygen -y -f PATH > PATH.pub` (it may ask for the passphrase; it works for a hardware key's handle too) |
| `✘ keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com …` | an RSA or ECDSA key | *(person)* `ssh-keygen -t ed25519 -C openmasonry -f ~/.ssh/openmasonry_ed25519` |
| `✘ the key is not listed at https://github.com/LOGIN.keys: bin/om onboard --upload (asks you first)` | not listed at `github.com/LOGIN.keys` | `bin/om onboard --upload`: the person approves in a dialog, then it adds the key as an authentication key |
| `· could not read https://github.com/LOGIN.keys (…): the key listing was not checked` | offline, throttled, or no such account: nothing is known yet | check again when online (section 9) |
| still not listed right after adding it | GitHub's public key list can take a minute or more to show a new key | wait, then `curl -fsS https://github.com/LOGIN.keys` |
| listed in `gh ssh-key list` but not at `.keys` | it was added as a **signing** key | `bin/om onboard --upload` adds it as an authentication key (the signing entry may stay) |
| `key is already in use` from GitHub | the key is on another GitHub account (perhaps another account of the person) | a new dedicated key for this account |
| `WOULD BE REFUSED — entry N: this key is already used by OTHER …` | one key per login in the ledger | a new key |
| `WOULD BE REFUSED — entry N: this key was used in this ledger before …` | a key the ledger ever held is never registered again | a new key |
| `· key not in ssh-agent: signing will ask for its passphrase` | the key is not loaded | *(person)* macOS `ssh-add --apple-use-keychain KEY`; Linux `ssh-add KEY` (first `eval "$(ssh-agent -s)"` if there is no agent); native Windows `ssh-add KEY`, once the OpenSSH Authentication Agent service runs (administrator PowerShell, once: `Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent`) |
| `Could not open a connection to your authentication agent` | no agent in that shell | *(person)* `eval "$(ssh-agent -s)" && ssh-add KEY` |
| `ssh-add -L` shows the key in the person's terminal but not in your harness | the harness has another `SSH_AUTH_SOCK` (or none) | fine: the person runs `bin/om approve` in their own terminal |
| `NOT SIGNED — ssh-keygen could not sign: … incorrect passphrase …` | wrong passphrase, or no terminal to ask it on | *(person)* `ssh-add KEY` first, then `bin/om approve DIGEST` in their own terminal |
| `NOT SIGNED — the key PATH asks for its passphrase and is not in the ssh-agent, and there is no terminal here to type it …` at approval | `bin/om approve` ran where nobody can type the passphrase (your harness; on native Windows, a process without a console of the person's own); it stops before the dialog | *(person)* `ssh-add KEY` (the command it prints), or runs `bin/om approve DIGEST` in their own terminal. Nothing was signed |
| `the ssh-agent did not answer within 10 seconds …` (`onboard`'s `key_agent`, `doctor`), or `NOT SIGNED — the ssh-agent did not answer …` at approval | `SSH_AUTH_SOCK` names a socket that never replies, often an agent forwarded over an SSH connection that closed. `onboard` and `doctor` say so after about 10 seconds (their OpenSSH check signs with a throwaway key and never asks the agent); approval stops before the dialog; a proof signed with a key file (`bin/om proof`) skips the agent and asks for the passphrase on the terminal | *(person)* opens a new SSH session (or starts a new agent), or runs `unset SSH_AUTH_SOCK` in the shell that runs `om`, so that signing asks for the passphrase; then approves again. Nothing was signed |
| `NOT SIGNED — ssh-keygen did not finish within 300 seconds …`, or `✘ ssh-keygen did not finish its test signature within 20 seconds …` (`onboard`'s `openssh`, `doctor`) | a passphrase never typed, a hardware key never touched, or an agent that stopped answering while it signed; for the test signature, an OpenSSH that hangs on a throwaway key | *(person)* approves again and types the passphrase or touches the token when asked; if the test signature hangs, reinstall the OpenSSH client (section 1). Nothing was signed |
| a command hangs on `Enter passphrase` | a passphrase prompt in a harness that cannot answer | stop it; *(person)* loads the key or runs the command in their own terminal. Your own `ssh` checks: always `-o BatchMode=yes` |
| `NOT SIGNED — … device not found` / `confirm user presence` timed out | hardware key: token missing, or not touched | plug it in, *(person)* approves again and touches it when it blinks |
| `NOT SIGNED — ssh-keygen wrote a signature this protocol does not accept …` | a hardware key made without user presence (`no-touch-required`) or for another application | create a new key without that option, with the default application |
| `Permission denied (publickey)` from `ssh -T git@github.com` | that key is not an authentication key of the account, or another key was offered | `ssh -T -o BatchMode=yes -o IdentitiesOnly=yes -i KEY git@github.com`; check `gh ssh-key list`. The judge reads only `.keys`: this test is optional |
| `Too many authentication failures` | the agent offers many keys before the right one | `-o IdentitiesOnly=yes -i KEY` |
| `WARNING: UNPROTECTED PRIVATE KEY FILE!` | the key file is readable by others (often a key on `/mnt/c` in WSL, or a copied file) | `chmod 600 KEY && chmod 700 ~/.ssh`; in WSL keep keys in the Linux home |
| `Host key verification failed` / first-time host prompt | GitHub's host key is not known yet | *(person)* compares the fingerprint with the one GitHub publishes in its documentation, then accepts |
| `ssh: connect to host github.com port 22: Connection timed out` | port 22 blocked by the network | `ssh -T -p 443 -o IdentitiesOnly=yes -i KEY git@ssh.github.com`; `om` itself needs no SSH connection (git uses HTTPS) |
| `doctor`: `your configured key (…) is not the key the ledger holds for LOGIN …` | a member signs with another key than the ledger's | use the ledger's key (`--key`, `OM_KEY`); to change keys, the Guide's "Replacing a key" (`bin/om rekey`); a lost key: the Almoner |
| a member's key is lost or in other hands, and no custodian exists, or none froze it | a recovery never needs a custodian: without a freeze it is an **open** recovery | `bin/om recover --new-key PATH` (a new key listed on the member's GitHub account, from that account); three Master Builders co-sign, or as many others as exist among those who answered within the last year (none for the only Master, or where no other Master answered); 30 days of notice from the last co-signature, 45 when fewer co-signers than three exist or when, 30 days after the request, those who have co-signed (at least one) suffice; then `bin/om recover-apply`. The Almoner (`om-almoner`) walks the person through it |

## 4. The approval dialog, terminals and harnesses

`bin/om approve DIGEST` (and the dialogs of `om onboard --upload`, `om apply`, `om submit`, `om pending --publish`, `om alarm`) asks the person, in this order: native Windows shows a PowerShell window, else (PowerShell missing, or the window cannot open) a code typed in the console; macOS uses `osascript` (only its Cancel button cancels; any other failure, such as no desktop session, falls back to the terminal); Linux with `DISPLAY` or `WAYLAND_DISPLAY` uses `zenity`, else `kdialog`; otherwise a code typed on the terminal (`/dev/tty`): it prints `Type one of: approve and sign-XXXX …` and only that exact text approves.

| Symptom | Cause | Fix |
|---|---|---|
| the command waits and nothing appears | the dialog opened behind other windows, or on another screen or desktop | *(person)* looks for it (macOS: the Dock or Mission Control) |
| your harness cut the command (timeout) while the dialog was open | harnesses limit long-running commands | *(person)* cancels any leftover dialog, then runs `bin/om approve DIGEST` in their own terminal, inside the clone. The draft stays until it is signed (`bin/om drafts`) |
| `no way to ask the person: approve from a desktop session or a real terminal` (Windows: `… or a console window of your own`) | no dialog and no terminal: a harness without a terminal, or a background job | *(person)* runs `bin/om approve DIGEST` in a terminal of their own |
| `bin/om onboard`: `· linux: no dialog and no terminal here: approvals are typed by the person in their own terminal` (or `WSL: …`) | your harness has no terminal; the person's has | a warning, not a failure: go on with the stage and its `Next`; the person approves in their own terminal |
| macOS over SSH (no desktop session) | `osascript` cannot show a dialog there | the terminal fallback asks for the typed code: *(person)* types it in that SSH session |
| Linux server, WSL or a container | no desktop: the terminal fallback asks for the typed code | *(person)* runs it in an interactive terminal (an SSH session is fine) and types the code |
| `zenity` is installed but `DISPLAY` points to a display nobody watches (remote session) | the dialog opens there | *(person)* runs `env -u DISPLAY -u WAYLAND_DISPLAY bin/om approve DIGEST` to use the typed code instead |
| `a draft digest is 12 to 64 lowercase hex characters` / `no single pending draft matches …` | a wrong or partial digest, or the draft was made under another `OM_HOME` | `bin/om drafts` lists them; copy the digest from there |
| `drafts can only be approved into this repository's ledger` | the draft was made with `--ledger` pointing elsewhere | draft again without `--ledger` |
| `the key PATH is not the one this act must be signed with` | the draft's key is not the ledger's (or the petition's) key | draft again with the right key (`OM_KEY` or `--key`) |
| `TAMPERED — this draft does not match its digest …` | the stored draft was changed | `bin/om discard DIGEST`, draft again; if nobody changed it, call the Tyler |

## 5. Git, the fork and the pull request

Approval signs, then: refuses to publish unless the clone is in sync; creates the fork on first use (`gh repo fork`, remote `fork`) unless the account can push to the canonical repository; commits only the new files on a branch `om/LOGIN/SEQ` from the canonical `main`; pushes it; opens the pull request from the person's account.

| Symptom | Cause | Fix |
|---|---|---|
| `you have staged changes; commit or unstage them before publishing an entry` | something is staged in the clone | `git restore --staged .` (keeps the edits in the working tree) |
| `… N entries behind …: git pull REMOTE main; then draft again` | the clone is behind | `git pull`, then draft again (the old draft is now `STALE`) |
| `… committed entries not in openmasonry/openmasonry yet …; publish only from a clone whose ledger matches the canonical one` | entries committed on the local branch (a manual merge, or an old flow) | `git log --oneline origin/main..HEAD -- ledger/entries` to see them; the person decides; usually `git switch main && git reset --keep origin/main` after checking nothing else is lost |
| `no git remote points to openmasonry/openmasonry: git remote add upstream …` | a clone of a fork | the command it prints, then `git fetch upstream` |
| `could not reach openmasonry/openmasonry` | offline, a proxy, or an outage | section 8 |
| `note: this clone's git identity is NAME <MAIL>; om commits each entry as LOGIN <ID+LOGIN@users.noreply.github.com> in UTC instead` at approval | the clone's git name or e-mail differs from the publishing account's, or is unset | nothing for the entry: `om` commits it as the account gh reports, with GitHub's private address, author and committer dates in UTC (`+0000`), whatever git's configuration or environment says. For commits made by hand in the clone, `git config user.name LOGIN && git config user.email ID+LOGIN@users.noreply.github.com` (`ID` from `gh api user --jq .id`); once gh is logged in, the `git_identity` check of `bin/om onboard` gives these with the real values, one command per run (the name, then the e-mail) |
| `gh cannot tell which GitHub account publishes …; nothing was signed` at approval, or `…; nothing was committed` | `gh api user` fails: the commit of an entry is made in the publishing account's name, so `om` must know it | *(person)* `gh auth status`; log in (section 2), or set `GH_CONFIG_DIR` to the configuration that holds the account; then approve again, or `bin/om pending --publish SEQ` |
| `NOT PUBLISHED — the commit of this entry carries … not LOGIN <ID+LOGIN@users.noreply.github.com> in UTC: nothing was pushed, and the branch om/LOGIN/SEQ was deleted`, or `NOT PUBLISHED — the commit on the branch om/LOGIN/SEQ carries …` | for the genesis, an entry of a founder or of a Custodian, and a petition, `om` reads the commit back before pushing; it carried another name, e-mail or time zone (a git wrapper, or a branch made by hand) | `bin/om pending --publish SEQ` commits it again; for a branch made by hand, with the person's yes, `git branch -D om/LOGIN/SEQ` first (the command says so). Never push it by hand |
| `git commit failed: … gpg failed to sign` / an SSH signing prompt | commit signing is on globally and cannot prompt | in the clone: `git config commit.gpgsign false` (entries carry their own signatures) |
| `git has no credentials for github.com: a push would ask for a password. Fix it first (gh auth setup-git: …)` at approval, or `git push failed: … could not read Username for 'https://github.com'` | git has no credentials for HTTPS | `gh auth setup-git` once gh is logged in (before the login, `bin/om onboard` says to log in first), then publish again (below). On the founding machine, never `gh auth setup-git` (it writes the global configuration): set the helper in the ceremony clone only, the reset first, as [LAUNCH.md](../operations/LAUNCH.md) "The pre-flight of the founding machine" step 5 says: `git config --local credential.https://github.com.helper ''`, then `git config --local --add credential.https://github.com.helper '!gh auth git-credential'` |
| `git push failed: … GH007: Your push would publish a private email address` | GitHub's e-mail privacy setting blocks the commit's e-mail | set the noreply e-mail above, then publish again (below) |
| `git push failed: … Repository not found` right after the fork was created, or `could not find your fork of openmasonry/openmasonry on GitHub (it may still be being created) …` | GitHub creates forks asynchronously | wait a minute, then `bin/om pending --publish SEQ`. When publishing failed before the branch existed, the signed entry waits in the outbox, not in `ledger/entries/`: `bin/om pending` lists it, and the invitation's 30 days keep running |
| `could not create your fork …`, `could not add the git remote …` or `git switch failed: …`, followed by `(the signed entry is kept: fix the cause, then bin/om pending --publish SEQ)` | publishing failed before the entry's branch existed | fix the cause, then `bin/om pending --publish SEQ`. The entry (and a correction's public reason) waits in the outbox, outside `ledger/`; `bin/om me` and `bin/om onboard` say it is not published yet |
| a branch `om/LOGIN/SEQ` of an earlier attempt exists, here, on the fork, or on the canonical repository for a person with write access (an entry dropped and drafted again takes the same SEQ when nothing merged in between) | `om` reuses the local branch when it holds exactly this entry and replaces it otherwise. The push to the person's own fork replaces the fork's old branch as well (`--force-with-lease` on what the fork holds just before). The canonical repository is never force-pushed: when it rejects the push of the person's own branch as non-fast-forward, `om` deletes that old branch there, only when no open pull request uses it and under a lease on what it held just before, then pushes again; `bin/om pending --drop SEQ` deletes it the same way. Another login's branch is never touched. `bin/om pending` shows only this entry's own pull request, never the closed one of the dropped entry | nothing; if the old pull request is still open, close it first (with the person's yes), as the push would move it on the fork and is refused on the canonical repository |
| `git push failed: … ! [rejected] om/LOGIN/SEQ -> om/LOGIN/SEQ (non-fast-forward) … (the signed entry is kept on the branch om/LOGIN/SEQ: …)`, with write access to the canonical repository | the canonical repository holds the old branch of an entry dropped at the same SEQ, and its pull request is still open (or GitHub could not be asked whether it is) | with the person's yes, `gh pr close OLD-URL`; then `bin/om pending --publish SEQ`: it deletes the person's own old branch there (under a lease) and pushes the new one |
| `the git remote fork fetches from your fork LOGIN/openmasonry but pushes to OTHER: nothing was pushed …` | `remote.fork.pushurl`, or a `pushInsteadOf`, sends the pushes of that remote to the canonical repository or to another account's fork; `om` forces only the person's own fork | with the person's yes, `git remote set-url --push fork https://github.com/LOGIN/openmasonry.git` (or remove the pushurl or `pushInsteadOf`), then `bin/om pending --publish SEQ` |
| `git switch failed: … Your local changes … would be overwritten` | uncommitted edits in files the canonical `main` changed | `git stash`, publish, `git stash pop` |
| a remote named `fork` points elsewhere | `om` adds the real fork under another name (`fork-2`) and pushes only to a repository GitHub lists as a fork of the canonical one | nothing |
| the person already has an unrelated repository named `openmasonry`, and the fork became `LOGIN/openmasonry-1` | `om` finds the fork through the canonical repository's forks, whatever its name | nothing |
| `could not create your fork of openmasonry/openmasonry: …` | no `repo`/`public_repo` scope, a managed account, or the repository is not public | section 2 |
| `✘ could not open the pull request: … (branch om/LOGIN/SEQ is pushed; open it with bin/om pending --publish SEQ)` | `gh pr create` failed after the push | fix the cause, then `bin/om pending --publish SEQ` (it asks the person) |
| `git push failed: … (the signed entry is kept on the branch om/LOGIN/SEQ: fix the cause, then bin/om pending --publish SEQ)` | the push failed after the commit; the working tree went back to where it was | fix the cause, then `bin/om pending --publish SEQ` within 5 hours 30 minutes of the entry's time; if that is past (`… is too old for the judge now`), `bin/om pending --drop SEQ` and draft again |
| the pull request shows "This branch has conflicts" / not mergeable | another entry merged with the same seq (both add `SEQ.json`) | `git pull`; `bin/om pending` lists the entry as `stale`; `bin/om pending --rebase SEQ`, the person approves the new draft, and, with their yes, `gh pr close OLD-URL` |
| a pull request opened from the wrong account | gh's active account was another | with the person's yes, `gh pr close URL`; `gh auth switch --user LOGIN`; `bin/om pending --drop SEQ`; draft again |
| checks "waiting for approval" | first-time contributor rules hold the `tyler` jobs | nothing: only `judge` is required, and it is not held |
| `judge` passed but nothing merges | the pull request is a draft, or auto-merge is not on in the repository | `gh pr ready URL`; otherwise wait for a maintainer (`docs/operations/LAUNCH.md`) |

## 6. The judge's refusals

Read the message on the pull request: `gh pr checks URL`, then the failing `judge` job's log (`gh run view RUN-ID --log-failed`). The first word says which gate refused.

| Message | Cause | Fix |
|---|---|---|
| `STALE OR FUTURE TIME — entry N claims TIME` | the entry's time is more than 2 minutes ahead of the judge's clock (this machine's clock runs fast) or more than 6 hours behind it (approved late, or the pull request waited) | fix the clock (section 7); `git pull`; `bin/om pending --drop SEQ`, close the pull request (with the person's yes) and draft again: approving replaces the old branch `om/LOGIN/SEQ` (on the fork; on the canonical repository, for a person with write access, it deletes the old one once its pull request is closed, section 5) and opens a new pull request, even at the same SEQ |
| `WRONG AUTHOR OR KEY — entry N: the invitation is for the GitHub account with id X, but the pull request is by the account with id Y` | the petition was opened from another account | close it; `gh auth switch --user LOGIN`; `bin/om pending --drop SEQ` and draft again (a new pull request, even at the same SEQ: the old branch is replaced, section 5) |
| `WRONG AUTHOR OR KEY — entry N (TYPE): LOGIN is the GitHub account with id X, but the pull request is by the account with id Y` | a member's entry opened from another account | as above |
| `WRONG AUTHOR OR KEY — entry N (TYPE) has actor A, but the pull request is by B` | an entry by a login the ledger does not know, from another account | the actor is the active gh account: switch accounts, draft again |
| `WRONG AUTHOR OR KEY — entry N: the petition key is not listed at https://github.com/LOGIN.keys` (or `the new key …`) | the key was removed, added as a signing key, or added to another account | add it as an authentication key to that account, then re-run the judge: with the person's yes, `gh pr close URL && gh pr reopen URL` (within the 6 hours) |
| `WRONG AUTHOR OR KEY — entry N: cannot fetch URL (…); refusing (fail closed)` | GitHub did not answer the judge (outage, rate limit) | wait, then `gh pr close URL && gh pr reopen URL` (with the person's yes). Gates fail closed by design: never look for a way around |
| `INVALID — entry N: …` | the entry breaks a rule on the canonical ledger (often: the invitation lapsed, or another entry changed the state first) | `git pull`, `bin/om me`, explain the rule; draft again only if the act is still possible |
| `A pull request that adds ledger entries must change nothing else …` | other files are in the pull request | close it; `bin/om pending --drop SEQ`; draft again (never add files to an `om/…` branch): approving replaces the old branch, on the fork or, with write access, on the canonical repository (section 5), even at the same SEQ |
| `Ledger entries may only be added, never modified, renamed or deleted` | an existing entry file was touched | close it; never edit entries; `git restore ledger/entries` |
| `Only entry files, each in the shard of its seq (ledger/entries/NNNN/NNNNNN.json), may be added to ledger/entries/:` | a file was added by hand, or in the wrong place (entry 1000 belongs in `ledger/entries/0001/001000.json`, not beside entry 999) | close it; `bin/om pending --drop SEQ`; draft again: `bin/om approve` writes the file where it belongs and replaces the old branch, even at the same SEQ (section 5) |
| `INVALID — entry N: ledger file … is in the wrong shard` (or `is not in its shard`, `is not an entry`, `is missing`) | the working copy holds a file `om` did not write, or one moved out of its shard (`ledger/entries/NNNN/`, 1,000 entries each) | never move entries by hand: `git status -- ledger/`, then, with the person's yes, `git restore ledger/entries` and `git clean -n ledger/entries` (show first) |
| `UNRATIFIED — …` on a ledger-only pull request | a governed file of `main` is unratified (an alarm, not the person's fault) | call the Tyler (`om-tyler`) |

## 7. Time and the machine's clock

The entry's time comes from this machine's clock when the draft is made. The judge accepts it from 6 hours behind to **2 minutes ahead** of its own clock; `om approve` refuses a draft older than 5 hours 30 minutes (`STALE — this draft is too old to be accepted by the Tyler; draft it again`), and, when GitHub's clock can be read, one stamped more than 90 seconds ahead of it (`this draft is stamped N seconds ahead of GitHub's clock …`: fix the clock, then draft again). `bin/om onboard` checks the clock too (`clock`).

- Compare: `date -u; curl -sI https://api.github.com | grep -i '^date:'`.
- macOS: System Settings → General → Date & Time → "Set time and date automatically"; or `sudo sntp -sS time.apple.com`.
- Linux: `sudo timedatectl set-ntp true`, then `timedatectl status` shows "System clock synchronized: yes".
- WSL: the clock drifts after the host sleeps: `sudo hwclock -s` (or `wsl --shutdown` from Windows and reopen).
- Windows: Settings → Time & language → Date & time → "Set time automatically", then "Sync now".
- `FUTURE HEAD — …` means the ledger's last entry is dated ahead of this clock: fix the clock first; if the clock is right, call the Tyler.

## 8. Drafts, pending entries and the canonical ledger

| Message | Cause | Fix |
|---|---|---|
| `your entry #N is still waiting for its pull request to be merged; draft again after it merges and you git pull …` | one signed entry at a time | `bin/om pending` (its pull request and state); once merged, `git pull`; if abandoned, `bin/om pending --drop N` |
| `bin/om pending` shows `stale` | another entry took that seq | `bin/om pending --rebase N`; the person approves the new draft; close the old pull request with their yes |
| `bin/om pending` shows `#N TYPE: unknown  → no pull request found: bin/om pending --publish N …` | no pull request exists for this entry (publishing failed, or GitHub could not be asked); a closed pull request of an earlier entry dropped at the same SEQ is not this entry's | `bin/om pending --publish N` (it looks for the pull request first, and asks the person) |
| `bin/om pending` shows `#N TYPE: CLOSED URL  → its pull request was closed: bin/om pending --publish N opens a new one …` | this entry's pull request was closed (by hand, or by GitHub when its head branch was deleted): it never merges; `bin/om me` and `bin/om onboard` say the entry is not published | `bin/om pending --publish N` (it asks the person) opens a new pull request; or, if the act is abandoned, `bin/om pending --drop N` |
| `bin/om drafts` marks a draft `→ stale: bin/om discard DIGEST, then draft it again` | the ledger moved past the draft, or it is too old to approve | `bin/om discard DIGEST`, then draft the act again |
| `entry #N (TYPE) is not signed with your member key and is not re-sequenced …` | a key recovery or custodian entry | `bin/om pending --drop N` and draft it again |
| `STALE — the ledger moved since this draft; draft it again` | another entry merged after drafting | `git pull`, draft again |
| `STALE — your signed entry #N (TYPE) is waiting for its pull request at this place in the ledger …` at approval | two drafts were made for the same place, and the first is signed and waiting | once #N merges, `git pull` and draft the other act again; if #N was abandoned, `bin/om pending --drop N` first |
| `bin/om pending` says nothing waits right after `bin/om approve --no-submit` | entries signed with `--no-submit` stay in `ledger/entries/` until published | `bin/om submit` publishes them (it asks the person); from then on `bin/om pending` lists them |
| `the ledger is empty: the fraternity has not been founded yet` | before genesis | nothing to do yet |
| `the Declaration in this clone's canon/eternal.toml is not the one this fraternity recorded at genesis …` | an old or modified clone | `git pull`; `git status canon/` must be clean |
| `ROLLBACK — …`, `BEHIND — …`, `DIFFERENT GENESIS — …`, `FUTURE HEAD — …`, `INVALID — the canonical ledger does not verify …` | the canonical ledger is not the history this clone verified | nothing is drafted or signed: `BEHIND` may resolve after `git fetch` later; for the others call the Tyler (`om-tyler`) and [RECOVERY.md](../operations/RECOVERY.md), section 8. `bin/om verify --accept-genesis HASH` is the person's own decision, never yours |
| `your ledger DIVERGES from … at entry N` | the clone follows a fork | the Tyler explains; the person decides on `git reset --hard REMOTE/main` (it discards local commits) |

## 9. Networks, proxies, rate limits and outages

| Symptom | Cause | Fix |
|---|---|---|
| `· could not reach openmasonry/openmasonry`, `gh` or `git` time out behind a company proxy | the proxy is not configured for the tools | `export HTTPS_PROXY=http://PROXY:PORT` (used by `gh`, `curl`, Python and git); or `git config --global http.proxy http://PROXY:PORT` |
| `SSL certificate problem` / `CERTIFICATE_VERIFY_FAILED` | a proxy that re-signs TLS with a company certificate | `export SSL_CERT_FILE=/path/to/company-ca.pem` (Python, gh on Linux); `git config --global http.sslCAInfo /path/to/company-ca.pem`; with python.org's Python on macOS, run its "Install Certificates" command once. Never turn verification off |
| `API rate limit exceeded` from `gh` | too many calls (5,000 an hour logged in) | wait for the hour to reset: `gh api rate_limit --jq .rate.reset` |
| `You have exceeded a secondary rate limit` when opening issues or pull requests | GitHub's anti-abuse limit on creating content | wait several minutes; do not retry in a loop |
| `curl` to `github.com/LOGIN.keys` answers `429` | a shared address (VPN, office) is throttled | wait, or check from another network |
| GitHub is down (status page red), the judge cannot fetch, pushes fail | an outage | wait. The gates fail closed on purpose: an entry that misses its 6 hours is dropped and drafted again afterwards |
| `verify --online` cannot reach drand | the public randomness relays are blocked | allow HTTPS to the drand relays, or verify offline (`bin/om verify --tree`) |

## 10. Windows

- **Native Windows works**: run `bin\om.cmd` from cmd.exe or PowerShell (it finds Python 3.11+ through `OM_PYTHON`, the `py` launcher or `python`; `om needs Python 3.11 or newer …` when none). It writes UTF-8, also into a pipe. Approval shows a PowerShell window; where no window can open (an SSH session) or PowerShell is missing, it asks for a code typed in the console. Install Git for Windows, `gh` and Python (`winget install Git.Git GitHub.cli Python.Python.3.12`). Keys live in `$HOME\.ssh`.
- **OpenSSH on Windows.** The client built into Windows is enough when `ssh -V` says 8.1 or later (`OpenSSH_for_Windows_8.1p1` or newer): `om` needs `ssh-keygen -Y sign`, which appeared in 8.1, and a hardware key needs 8.2. An older built-in client (7.7, on early Windows 10 builds) is refused: install the current release of github.com/PowerShell/Win32-OpenSSH. The ssh-agent is a Windows service: section 3.
- **Commands on Windows.** On native Windows every `argv` and `approve` field of the JSON names `bin\om.cmd`, and printed commands (those of `onboard`, `doctor`, `me` and approval) quote paths with double quotes, as cmd.exe and PowerShell read them.
- **WSL 2** remains an alternative, treated as Linux: *(person)* `wsl --install -d Ubuntu` in an administrator PowerShell, restart, open Ubuntu, and follow the Linux steps inside it.
- In WSL, keep the clone and the keys in the Linux home (`~`), never under `/mnt/c`: permissions there are not kept (`UNPROTECTED PRIVATE KEY FILE`), and files cross line-ending conversions. Run `gh auth login` and create the key inside WSL; keys and logins of Windows are separate.
- **Line endings.** The repository's `.gitattributes` keeps text in LF and ledger entries byte for byte. A clone made with `core.autocrlf=true` before that file applied may show every file changed: `git config core.autocrlf false && git rm --cached -r -q . && git reset --hard` (it discards uncommitted edits; ask first).
- Git Bash runs `bin/om` (the POSIX script) too; with the python.org installer `python3` may be missing or a Store stub: `OM_PYTHON=py bin/om me`, or use `bin\om.cmd`.
- Paths: `om` takes `~/.ssh/...` in WSL and Git Bash; in PowerShell use `$HOME\.ssh\...`.
- The dialogs fall back to the typed code in a WSL terminal (WSLg rarely has `zenity`): that is the expected way to approve there.

## 11. `om onboard` and `om apply`

| Message | Cause | Fix |
|---|---|---|
| `Stage: tools` / `login` / `no_key` / `key_not_on_github` … and `Next: …` | the first thing missing, and its one fix | run the `Next` command; *(in your own terminal)* marks the person's; words instead of a command (`read`) are for you to explain. Git's identity and credentials wait for the login: until gh is logged in the stage is `login` |
| `Stage: not_applied` and `Next: bin/om apply --text FILE, FILE being the introduction the person wrote …` | the person has not applied | the person writes the file; then `bin/om apply --text FILE --check`, then without `--check` (section 5 of the `om-onboard` skill) |
| `Stage: petitioned` and `Next: bin/om pending --publish N` | the petition is signed but GitHub holds no pull request for it (the push or the pull request failed, or the fork was not found) | `bin/om pending --publish N` (it asks the person); with `Next: bin/om pending`, its pull request is open and waits for the judge and the merge (`bin/om pending` shows its state). A closed pull request (closed by hand, or by GitHub when its branch was deleted) never merges and does not count: `Next` is `bin/om pending --publish N` again, which opens a new one |
| `Next: The ledger is empty: the fraternity has not been founded yet …` | before genesis | nothing to apply for yet; founding is the founder's act (docs/operations/LAUNCH.md) |
| `✘ this clock is N seconds behind GitHub's: every draft is already that old when it is made …` | the clock runs slow | section 7 |
| `PATH already exists: om never overwrites a key …` | `--create-key` on a path that holds a key | `--use-key PATH`, or `--create-key OTHER-PATH` |
| `no terminal to ask for a passphrase: run this in your own terminal …` | `--create-key` from a harness | *(person)* runs the printed `ssh-keygen` command, then `bin/om onboard --use-key PATH` |
| `you are a member and the ledger holds another key for you: om onboard never changes your key (that is bin/om rekey)` | `--use-key`/`--create-key` for a member | the Guide's "Replacing a key" |
| `note: OM_KEY still names X; unset it, or point it to Y` | `OM_KEY` overrides the recorded key | *(person)* `unset OM_KEY`, and remove it from the shell profile |
| `uploading a key needs the admin:public_key scope: run, in your own terminal: …` | the gh token cannot add keys | *(person)* the printed `gh auth refresh …` |
| `GitHub refused the key: …` (`… it is on another GitHub account already …`) | the key is on another account | a new key for this account |
| `· the key was added but is not listed at … yet` | GitHub lists new keys after a while | `bin/om onboard` again in a minute |
| `line N: the application holds an e-mail address` / `… what looks like a phone number` / `… mentions @X` / `… a control character`, or `the application is N characters; keep it under 1200` | personal data, a call on someone, or too long | the person edits the text (never you), then `bin/om apply --text FILE --check` |
| `you already have an open application: URL …` | one open application per account | add to it there, or close it first |
| `LOGIN is a member already …` / `LOGIN is invited already (by BY, until DATE): petition with bin/om join` | nothing to apply for | the Guide (`bin/om me`) |
| `GitHub did not open the issue: …` | `gh issue create` failed (scope, rate limit, the repository not public) | section 2 or 9; `--web` opens the form instead |
| `Canceled. Nothing was published.` / `Canceled. Nothing was uploaded.` | the person pressed Cancel | nothing |
