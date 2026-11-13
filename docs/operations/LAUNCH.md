# Launch checklist (GitHub settings and the Founding Ceremony)

The Tyler's workflows only bind if the canonical repository is configured to obey them. Apply every item below before the Founding Ceremony, and re-check after any change of administrator. Nothing here is enforced by the verifier: a wrong setting is visible to anyone who looks, and the daily `audit` still re-judges `main`, but the gate is only as strong as these settings.

Who applies these settings, and under what limits, is the [Custodian's charter](../governance/CUSTODIAN.md). What to do when a key, a token or the host itself is lost is in the [recovery runbooks](RECOVERY.md).

## Accounts

- **`@openmasonry` is a user account**, not an organization or a team. `.github/CODEOWNERS` names it as the owner of everything except `ledger/entries/`, `ledger/anchors/` and `ledger/reasons/`. It also owns `canon/history/`, the archive of every degree table the ledger pins, which the judge lets grow and never change. A user account cannot approve its own pull request, so a change authored by `@openmasonry` needs another code owner's approval; until one is named, such a change waits, and the emergency bypass (below) is kept for emergencies. After the Founder's Sunset, CODEOWNERS is changed, by a reviewed pull request, to the witness operators' team.
- **Witness token.** Each witness uses a **dedicated machine user or a GitHub App**, never a personal token of a member. Fine-grained, limited to this one repository, with **Contents: read and write, Pull requests: read and write, Issues: read and write** and nothing else, with an **expiry** (90 days or less) and a written rotation procedure. Revoke it at once if the host is compromised. The witness never needs admin rights or ruleset bypass.

## Repository (Settings → General)

| Setting | Value | Why |
|---|---|---|
| Visibility | **Public** | outsiders must be able to read, verify, apply and, once invited, fork and petition |
| Issues | **on** | applications, amendments, capture alarms |
| Discussions | **on** | getting to know applicants, debating amendments |
| Allow merge commits | **on** | `admit` and the witness merge with `--merge`, which keeps each entry's commit intact |
| Allow squash / rebase merging | off (recommended) | one merge method keeps history simple |
| **Allow auto-merge** | **on** | required by the `admit` job and the witness; without it ledger PRs wait for a human |
| Automatically delete head branches | on (recommended) | witness branches are one-use |

## Ruleset on `main` (Settings → Rules → Rulesets → New branch ruleset)

- **Target:** the default branch (`main`). **Enforcement:** Active.
- **Bypass list:** empty, or only the founder for emergencies. Every bypass is visible in the ruleset's insights; use it only for a documented emergency, and record each use in the ledger as a `note` while a custodian key is live, and otherwise in a public issue ([CUSTODIAN.md](../governance/CUSTODIAN.md)). No use of the bypass is planned: even a change in how the `@protocol` digest is computed is done by two ordinary upgrades ([RECOVERY.md](RECOVERY.md), section 6.1).
- **Restrict deletions:** on.
- **Block force pushes:** on.
- **Require a pull request before merging:** on, with **required approvals: 0** and **Require review from Code Owners: on**. Ledger paths have no owner, so ledger PRs need no review; every other path needs a code owner's approval. Dismiss stale approvals on new commits: on.
- **Require status checks to pass:** on, with the single required check **`judge`** (source: GitHub Actions). The `candidate` check (in `tyler.yml`) replays the ledger of `main` with the pull request's own protocol core and fails when the head or the state digest differs. It is **not** a required check: it runs on `pull_request`, whose runs from first-time contributors wait for an approval, and a required check that waits would hold their petitions. It binds the other way: a pull request that changes the core is never ledger-only, so it needs a code owner's review, and the code owner approves it only with a green `candidate` run; electors check the same before voting the amendment: on that `candidate` run, or with `om verify --candidate-root DIR` only inside a disposable container or VM that holds no keys, since that command executes the candidate tree's code as the user who runs it (it asks first, or takes `--i-trust-this-code`; [RECOVERY.md](RECOVERY.md) section 6). Leave **"Require branches to be up to date before merging" off**: it would force every ledger PR to be rebased and re-judged whenever another merges. It is not needed for safety: two PRs that append the same `seq` add the same file name, so the second cannot merge (an add/add conflict), and its author drafts again on the new `main`.
- **Require signed commits:** off. Entries carry their own SSH signatures, which the verifier checks; requiring commit signatures would add a hurdle for every candidate and agent without adding anything the judge relies on.
- **Require merge queue:** off. The `judge` runs on `pull_request_target`, not on `merge_group`, so a queue would never get its check.
- **Require linear history:** off (it forbids merge commits).

No job other than `judge.yml`'s may be named `judge`. A PR could add a workflow with a job of that name, so the set of workflows is closed: the repository holds three, `judge.yml`, `pages.yml` and `tyler.yml`, all part of the pinned core (`@protocol`), and the judge refuses any pull request whose tree holds a file under `.github/workflows/` that its manifest (`src/openmasonry/protocol.manifest`) does not list (its own gate, and `verify --tree`: `a workflow outside the pinned core`); a manifest that lists a new workflow changes the `@protocol` digest. A change to any of them, or a new workflow, therefore needs a ratified amendment of `@protocol`, not only a review. `judge.yml` runs on pull requests into `main` only, and runs nothing of the repository but `python3 -P -m openmasonry.verify` (no third-party action, no fixed Python version: the checkout is plain git and the runner's `python3` is enough); `tyler.yml` and `pages.yml` have no job named `judge` and no `pull_request_target` trigger. The other files under `.github/` (issue forms, CODEOWNERS) are guarded by the code-owner review; the judge refuses any ledger PR that touches anything else, and workflow runs from outside contributors need approval (below). **The closed set alone does not stop a pull request from posting its own `judge` check.** `tyler.yml` runs on `pull_request`, which runs the pull request's own version of the file: a pull request that edits it to add a job named `judge` gets that job's check on its head commit, beside the real judge's refusal. The real barrier is the required **code-owner review**: every path under `.github/` has an owner in `.github/CODEOWNERS`, so such a pull request never merges without a code owner's approval, and the ruleset above must keep **Require review from Code Owners** on. A code owner approves a change under `.github/workflows/` only when it is the tree of a passed amendment of `@protocol`. The required check must keep **GitHub Actions** as its source, so that no other app can report a status named `judge`.

## Actions (Settings → Actions → General)

- **Workflow permissions:** **Read repository contents and packages permissions** (the default `GITHUB_TOKEN` is read-only). Each job asks for what it needs: `admit` asks for `contents: write` and `pull-requests: write`, `alarm` for `issues: write` and `actions: read`, `applications` for `issues: write` and `contents: read`.
- **Allow GitHub Actions to create and approve pull requests:** off.
- **Fork pull request workflows from outside collaborators:** **Require approval for first-time contributors** at least (recommended: for all outside collaborators). This only affects `tyler.yml` (`pull_request`); the judge runs from the base branch on `pull_request_target` either way.
- **Actions permissions:** allow only actions by GitHub. The law-bearing jobs use none at all; the one used (`setup-node`, in the `engine` job) is pinned to a full commit SHA, with its tag in a comment.

Merges made by `admit` use the `GITHUB_TOKEN`, and GitHub does not start new workflow runs for events caused by it, so those merges do not trigger the `push` run of `tyler.yml`. The daily `audit` re-judges `main` within 24 hours, and every later PR replays the whole ledger anyway.

## Security (Settings → Code security)

- **Private vulnerability reporting:** on (SECURITY.md sends reporters there).
- Dependabot alerts and security updates: on (the engine in `engines/openmasonry/` has npm dependencies).

## Labels (Issues → Labels)

Create these labels before the first application: `application`, `amendment`, `masterwork`, `witness`, `capture-alarm`, `appeal` (appeals against moderation, see [CUSTODIAN.md](../governance/CUSTODIAN.md)), `spam` (triage of obvious spam, below). The issue templates and the workflows use them; the witness and the `alarm` job create `witness` and `capture-alarm` if missing, which needs Issues: write.

## Interaction limits (Settings → Moderation options)

Keep **Interaction limits** available for floods: "Limit to prior contributors" for 24 hours stops spam applications without closing the door for good (a stranger cannot write to the ledger at all: a petition needs a Master Builder's invitation). Turn it off again once the flood ends; the door must stay open (Landmark I). The runbook is the next section.

## An application flood

A flood of applications cannot reach the ledger: an application is a public issue, not an entry, and nobody writes to the ledger without a Master Builder's invitation. What a flood threatens is the issue tracker. The Custodian ([CUSTODIAN.md](../governance/CUSTODIAN.md), section 10):

1. **Limit interactions.** Settings → Moderation options → Interaction limits → **"Limit to prior contributors"**, for **24 hours**. Choose the shortest limit that stops the flood, and never a longer one than needed.
2. **Triage.** An application carries the `application` label (the issue form adds it; `om apply` from the command line opens it titled `Application: @<login>` without a label). Label obvious spam `spam`, close it with a short comment ("Closed as spam under section 10 of docs/governance/CUSTODIAN.md; if this is a mistake, open an issue labeled `appeal`."), and block the account only if it repeats and is not a member. A real application, however brief, is left open: the Custodian does not choose who is invited.
3. **Record every moderation act.** A limit, a close as spam, a hide, a lock or a block is done on GitHub, outside the ledger, so it is recorded in the ledger as a `note` correction, whose ground is always `moderation`:

   ```sh
   bin/om correct note --action limit --target openmasonry/openmasonry --rule docs/governance/CUSTODIAN.md#10 --reason reason.md --as NAME --custodian-key PATH
   bin/om correct note --action other --target issue#123 --rule docs/governance/CUSTODIAN.md#10 --reason reason.md --as NAME --custodian-key PATH
   ```

   `NAME` is the Custodian's name and `PATH` the custodian key (or set `OM_CUSTODIAN` and `OM_CUSTODIAN_KEY`). `--action` is one of `hide`, `lock`, `block`, `unblock`, `limit`, `other` (a close is `other`). `--target` names what was touched (a thread, an account) and `--rule` the published rule applied. The reason file is public: for a limit it states the end date; it names no person beyond a login. A custodian records at most ten notes in a UTC day, so record a batch of spam closes as one note whose reason lists the issues.
4. **Lift the limit.** When the 24 hours end, check that the limit has lapsed (or remove it by hand), so the door stays open (Landmark I).

Applications that nobody takes up do not pile up: the `applications` job of `tyler.yml` runs daily and closes each open application older than **60 days**, at most 50 a run, with a courteous comment that the application closed without an invitation, that an application gives no right to one, and how to apply again. It reads `main`'s ledger with the pinned core and never closes the application of a member, of a login that holds or ever held an invitation, or of a petitioner. It is a published rule, not a moderation act, so it needs no `note`. Before the genesis nobody can be invited, and only the age decides.

## Before the genesis: the founding account

The identity gate lets the genesis in only from one GitHub account: the one whose numeric id is `founder_github_id` in `src/openmasonry/network.toml`, a file of the pinned core. It is set in the repository's first commit to **355316448**, the numeric id of the account `openmasonry` that founds the canonical repository (a login can change, the id never does: `curl -s https://api.github.com/users/openmasonry` shows it as `id`). Nothing is changed before the ceremony; check it:

1. `grep founder_github_id src/openmasonry/network.toml` shows `355316448`.
2. The archived degree table (`canon/history/<sha256>.toml`) is in `main`; if it is not, merge it first by an ordinary reviewed pull request, so that the genesis pull request holds entry `000000` and nothing else.
3. `bin/om digest` prints the `@protocol` digest the genesis will pin; it covers `network.toml`.

The first founder of the genesis must state that same id, and the pull request that carries it must come from that account. The field names the founding account and is read for the genesis entry alone: it gives that account no power over any later entry, which the judge holds to the GitHub id the ledger records for its signer, a founder's included. A mistake in it can only be repaired by a new genesis.

## The pre-flight of the founding machine

`bin/om approve`, `bin/om submit` and `bin/om pending --publish` refuse to publish an entry a founder signs (or one of a Custodian linked to a founder) from a GitHub account whose numeric id is not the one the ledger records for that founder, and, before the genesis, refuse to publish the genesis from any account but the one whose id is `founder_github_id` (the message starts `NOT PUBLISHED —`; nothing is signed or published, [TROUBLESHOOTING.md](../agents/TROUBLESHOOTING.md) section 2). The guard asks `gh` which account is active; it is a safety net, not the plan. Before drafting, in the shell of the ceremony:

1. **An isolated gh configuration, logged in as `openmasonry`.** `export GH_CONFIG_DIR=` a directory of its own (the one the account was first logged in with, or a new one with `gh auth login --hostname github.com --git-protocol ssh --web`, in a browser profile signed in as `openmasonry`). Never `gh auth setup-git` here: it writes the global git configuration, for every repository of the machine (step 5 sets the same helper in the clone only). Check: `gh api user --jq '[.login, .id]'` shows `["openmasonry",355316448]`, `gh api repos/openmasonry/openmasonry --jq .permissions.push` shows `true`, and neither `GH_TOKEN` nor `GITHUB_TOKEN` is set (a token in the environment overrides the login).
2. **The login and the key.** `export OM_LOGIN=openmasonry` and `export OM_KEY=<path to the new member key>`, the key generated for the ceremony (step 1 below), listed at `https://github.com/openmasonry.keys`.
3. **The clock.** `export TZ=UTC`, and the machine's clock synchronized (`bin/om doctor` checks it against GitHub's).
4. **The agent.** `ssh-add -L` prints nothing, or only the public half of `$OM_KEY` (`ssh-add -D` empties it, then `ssh-add "$OM_KEY"`); no other key is loaded while the genesis is signed.
5. **The clone.** Run the ceremony in the clone that is set up to push as the account, and check its configuration:
   - `origin` is `git@github.com:openmasonry/openmasonry.git`, and `core.sshCommand` is `ssh -F /dev/null -i <the account's push key> -o IdentitiesOnly=yes`. The push goes over SSH with a key that only `openmasonry` lists, so it cannot authenticate as another account. Over HTTPS, git asks its credential helpers in order, and a helper of the system or global configuration (a keychain) answers before gh, possibly with another account's credentials, unless a later empty `helper` line resets the list.
   - `git config user.name` is `openmasonry` and `git config user.email` is `355316448+openmasonry@users.noreply.github.com`. `bin/om` commits every entry as the account gh reports, with GitHub's private address and in UTC, whatever these say, and reads back the commit of the genesis before it pushes; these keep a commit made by hand in this clone right as well.
   - `bin/om approve` signs only when git also has gh's HTTPS credentials. Set them in this clone only, the reset first, so that no other helper answers before gh:

     ```sh
     git config --local credential.https://github.com.helper ''
     git config --local --add credential.https://github.com.helper '!gh auth git-credential'
     ```

   Check: `printf 'protocol=https\nhost=github.com\n\n' | git credential fill | grep '^username='` prints `username=openmasonry` (the `grep` keeps the token off the screen), and `bin/om doctor` shows `git pushes to github.com with the gh login`. The clone is clean and exactly `main` (`git pull --ff-only`, then `git status --porcelain` prints nothing and `HEAD` equals `origin/main`).
6. **The command.** Draft with exactly these founder flags:

   ```sh
   scripts/genesis.sh --name "OpenMasonry" --login openmasonry --github-id 355316448 --key "$OM_KEY" \
     --custodian NAME:custodian.pub:revoke.pub --custodian-threshold 1
   ```

## The Founding Ceremony (three keys)

The genesis entry names the founders, the witnesses and the Custodians. It is entry 0, and nothing in it can be corrected afterwards: no entry, ballot or lot ever replaces a Custodian's key or changes the member it is linked to. The one way a Custodian is added later is the founder's fallback: while no custodian key is live, the Sunset has not come and fewer than three active Master Builders who are not founders exist, a founder may take up the office again with new keys, after 30 days of public notice that one Master Builder who is not a founder can stop ([RECOVERY.md](RECOVERY.md), section 2.6); after an objection, no founder claims again for 30 days, and never a founder against whose custodian key a removal ballot passed. A genesis that names no Custodian founds a ledger on which no correction exists until a founder claims the office. Rehearse the whole ceremony in a throwaway copy of the repository first ([below](#rehearsing-the-ceremony)).

The founder who also holds the office of Custodian has **three keys**, generated and stored apart ([CUSTODIAN.md](../governance/CUSTODIAN.md)):

| Key | What it signs | Where it lives |
|---|---|---|
| **Member key** | the founder's acts as a member: the genesis entry itself, then votes, invitations and the rest | the founder's working device or, better, a hardware token; listed on the founder's GitHub account |
| **Custodian key** | corrections and the sign of life, and nothing else | offline, on a medium of its own (a hardware token is recommended); listed on no GitHub account |
| **Revoke key** | one entry only: the removal of the custodian key | offline, on another medium, kept in another place than the custodian key |

1. **Generate the three keys separately.** Each is an Ed25519 key, plain (`ssh-keygen -t ed25519`) or hardware-backed (`ssh-keygen -t ed25519-sk`, default application). They must be three different keys: the genesis is refused when a custodian key or a revoke key equals another key of the genesis. Generate the custodian key and the revoke key on their own media, and never copy the two onto the same medium. `bin/om approve` signs the genesis with the member key and the two proofs of possession with the two other keys in one process, so all three private keys must be readable by the machine that runs it, once, at the ceremony: use a hardware token for the member key (and, better, for all three), or an offline ceremony machine, and take the custodian and revoke media away as soon as the approval ends.
2. **List only the member key on GitHub** (`github.com/<login>.keys`), and load it (`ssh-add`). A custodian key and a revoke key belong to no GitHub account.
3. **Choose the Custodian's name.** It follows the rules of a login and is never a member login or a witness name. It is held for good: no member, witness or other Custodian can ever take it.
4. **Draft the genesis** with `scripts/genesis.sh`, which refuses to draft without a Custodian, or on a checkout that is not exactly `main`:

   ```sh
   scripts/genesis.sh --name "OpenMasonry" --login openmasonry --github-id 355316448 --key "$OM_KEY" \
     --custodian NAME:custodian.pub:revoke.pub \
     --custodian-threshold 1 \
     [--cofounder LOGIN:KEY.pub:ID --cofounder-proof LOGIN:FILE] \
     [--witness NAME:witness.pub --witness-proof NAME:FILE]
   ```

   `355316448` is the founding account's numeric GitHub id (the one in `network.toml`), and the shell is the one the pre-flight (above) prepared. A cofounder sends their public key and a proof made with `bin/om proof founder LOGIN --github-id ID --key PATH --out FILE`; a witness operator sends `witness.pub` and a proof made on the node with `bin/om proof witness NAME --key PATH --out FILE` ([node/README.md](../../node/README.md)). See `bin/om genesis --help` for every argument. The draft records, for each Custodian, the name, the two public keys, the founder's login as its member, and two proofs of possession: the custodian key signs the custodian message and the revoke key signs the revoke message. Both keys are therefore needed once, at the ceremony, each on its own medium.
5. **Read the draft before approving it.** Draft and check the genesis only on a clean checkout that is exactly `main` (no local change, no untracked file, `HEAD` equal to `origin/main`): the genesis pins the governed files of that tree, and the genesis pull request is accepted only if the tree it lands on holds exactly the pinned texts. Check the six pins (`bin/om digest` for `@protocol`; the SHA-256 of the Constitution, the degree canon, the Landmarks, the Custodian's charter and the rules of the rooms), the hash of the Declaration, every founder's login and numeric GitHub id, the witnesses, and for the Custodian the name, the two keys, the member and the number of custodian keys a noticed act needs (1 with a single Custodian). A draft can be approved for 5 hours 30 minutes, and the judge accepts entry 0 only if it is stamped at most 6 hours behind its clock: draft, check and approve in one sitting.
6. **Approve it** with `bin/om approve <digest>`: the member key signs entry 0, and the pull request carries it alone (the archived canon was merged before, above).
7. **Put the two offline keys away, apart,** as soon as the genesis has merged and `bin/om verify --tree` passes. Publish nothing about where they are kept.
8. **Keep the office alive, on purpose.** A custodian key lapses, for good, after 180 days without a signed sign of life (`bin/om alive`); the genesis is the first one, and a correction is not one. `bin/om state` shows the date by which the next is due. Sign one on a fixed rhythm well inside the limit (every 90 days, for example), or let the key lapse knowingly.
9. **Know the way out before it is needed.** The revoke key ends a stolen custodian key at once; a lost custodian key ends by silence; the Master Builders can remove the key by ballot; and while few Masters exist a founder can take up the office again with new keys ([RECOVERY.md](RECOVERY.md)). A founder against whose custodian key a removal ballot passed never can, and after an objection voids a claim, a new claim by any founder waits 30 days.

## Rehearsing the ceremony

`bin/om approve` signs only into the ledger of the repository it runs from, and it is the one command that makes the custodian proofs of a genesis. Rehearse the whole ceremony, three keys included, in a **throwaway copy of the repository**, with throwaway keys and never the keys of the ceremony:

1. **Make the copy and a home for it.** Export the repository's tree, without its git history and remotes, to a scratch directory (`mkdir /tmp/om-rehearsal && git archive HEAD | tar -x -C /tmp/om-rehearsal`, run in your clone), and use a fresh `OM_HOME` (`export OM_HOME=$(mktemp -d)`) so that nothing the rehearsal verifies is remembered by your real clone. In the copy, set `founder_github_id` in `src/openmasonry/network.toml` to the throwaway id you draft with.
2. **Make three throwaway keys** with `ssh-keygen -t ed25519` (member, custodian, revoke).
3. **Draft** in the copy with `OM_REHEARSAL=1 scripts/genesis.sh --login LOGIN --github-id N --key MEMBER --custodian NAME:custodian.pub:revoke.pub …` (`OM_REHEARSAL=1` skips the check of the checkout, which only a real clone of `main` passes).
4. **Approve** with `bin/om approve --no-submit <digest>`: the dialog is the real one, the three keys sign, and nothing is pushed or published.
5. **Replay and read** in the copy: `bin/om verify --tree`, `bin/om state` and `bin/om corrections`. Go on with the acts the Custodian will need (a `bin/om correct …` with `--as NAME --custodian-key PATH`, `bin/om revoke-custodian NAME --revoke-key PATH` last), each approved with `--no-submit`. A sign of life (`bin/om alive --as NAME --custodian-key PATH`) is refused within 24 hours of the last one, and the genesis counts as one: rehearse it the next day, or leave it out.
6. **Delete the copy, its `OM_HOME` and the throwaway keys.**

The operator's tools also work on a bare scratch ledger (`--ledger SCRATCH --json` to draft, `bin/om append TYPE --actor LOGIN --key PATH --body JSON --ledger SCRATCH` to sign, `bin/om verify --ledger SCRATCH`), but only for entries whose draft carries no pending proof: a genesis that names a Custodian cannot be signed that way. With `--tree`, a scratch ledger's reasons are read from `reasons/` beside its entries.

The approval bypass of the automated tests is not a rehearsal mode: it works only with a marker file in an `OM_HOME` under the system temporary directory (`TMPDIR`), with the signing key inside that `OM_HOME`, and never for the repository's own ledger ([SECURITY.md](../../SECURITY.md)).

## The rooms

The rooms of study live apart from the canonical repository, in the GitHub organization **`openmasonry-org`**: 33 private repositories, one per degree, each read by its own closed team, with Actions off. They are closed but never secret: their existence, their rules ([ROOMS.md](../governance/ROOMS.md)) and the roll of each room are public. Access is set from the ledger by a published program ([`ops/rooms/sync.py`](../../ops/rooms/sync.py)), which runs once the rooms open at the public launch; until it runs, no room is operating and nobody is added to a team by hand. Set up the room sync (its GitHub App, the private `ops` repository, its variables and secrets, the rehearsal) as [ops/rooms/README.md](../../ops/rooms/README.md) describes.

## The Observatory

The public Observatory is built by `bin/om observatory --out DIR` from the ledger (and, for the rooms, from the access the room sync publishes). Its workflow, `.github/workflows/pages.yml`, is part of the pinned core from the genesis; publishing it takes only the settings in [ops/observatory/README.md](../../ops/observatory/README.md).

## Keeping the schedule alive

GitHub disables scheduled workflows in public repositories after **60 days without repository activity**. The witness's checkpoint PRs keep the repository active. If no witness runs for two months, check Actions → Tyler and re-enable the workflow, or run it by hand (`workflow_dispatch`).

## After launch

- Open a test PR that adds a non-entry file in `ledger/entries/` (or an entry file outside its shard, such as `ledger/entries/000001.json`) and confirm the `judge` check fails and the merge button is blocked.
- Confirm the ruleset shows `judge` as required and that a docs-only PR asks for a code-owner review.
- Confirm that the genesis PR (entry `000000` alone, as `ledger/entries/0000/000000.json`) gets the `admit` job and merges by itself once `judge` passes.
- Confirm that a pull request that changes a file of the core shows a green `candidate` check when it replays `main` to the same head and state, and a red one when it does not.
- Confirm that `bin/om state` lists the Custodian as `live`, with the date by which its next sign of life is due, and that `bin/om corrections` is empty.
