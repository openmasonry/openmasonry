# The room sync

Each degree has a room: the private repository `degree-NN` of the organization `openmasonry-org`, read by the team `degree-NN` and every higher team ([ROOMS.md](../../docs/governance/ROOMS.md)). Who sits in which team is not chosen by anyone. It follows the ledger, and this program applies it:

- **The rule** is `src/openmasonry/rooms.py`, part of the pinned core ([SPEC section 15](../../docs/whitepaper/SPEC.md#15-rooms-derived-outside-replay)): `room_access` derives the roll from the ledger, and `sync_plan` turns the difference between that roll and the teams into actions. Changing it takes an amendment of `@protocol`.
- **The program** is [`sync.py`](sync.py): it verifies the ledger, reads the organization, prints the plan, with `--apply` performs it, and on every run writes what it saw and did for the Observatory. It changes by code-owner review.
- **The workflow** is [`ops-workflow.yml`](ops-workflow.yml), a template for the private `ops` repository, which runs the program hourly and keeps its state. It is not a workflow of this repository.

Anyone can run the dry run of the rule against the ledger: `bin/om rooms` prints the roll every room derives.

## What it publishes (Landmark II)

A room is closed but never secret: its roll is public, and so is who else the organization lets read it. On every run, dry runs included, the program writes two files that name no one the ledger does not, and the run publishes them to a public repository, from which the [Observatory](../observatory/README.md) shows them beside the derived roll:

- `actual.json` (`om.rooms-actual/1`): who GitHub lets read the rooms, as GitHub reported it: the members of each room team, **every owner of the organization** and **every application installed on it** (by name). The program reads the organization's teams, owners and installed applications, never a repository, so a grant made directly on a room's repository, or to an outside collaborator, is not in this file; the Custodian's private Console lists the outside collaborators of the organization ([CONSOLE.md](../../docs/governance/CONSOLE.md));
- `runs.jsonl`: one line appended per run and never rewritten, in counts only: when it ran, against which ledger entry and head, whether it applied or was forced, its result, and how many invitations, moves, removals and cancellations it planned, made, deferred or refused. It is the anonymous log of the program: no login, no id and no reason that could name anyone.

The Observatory compares `actual.json` with the roll the ledger derives and shows every difference: an owner, an application or a team member the ledger does not explain is visible to anyone.

## What it does in one run

1. **Verifies the canonical ledger** by a full replay. It refuses to act if the ledger is invalid or empty, if its head is dated more than 10 minutes ahead of the clock (a capture alarm), or if the head moved backwards against the mark kept in the state directory (a rollback, or a mirror that is behind). The mark uses the same rule as a member's client ([SPEC section 9.7](../../docs/whitepaper/SPEC.md)).
2. **Reads the organization** through the GitHub REST API (`gh api`, with the App's installation token in `GH_TOKEN`): the 33 room teams and their members, the organization's members and owners, the pending and the failed invitations, and the GitHub Apps installed on it. It never reads a repository, a discussion, an issue or any other content.
3. **Plans.** People are matched by their **numeric GitHub id**, recorded in the ledger at admission, never by login: a member who renames the account keeps the rooms, and someone who takes the old login gets nothing. The plan is ordered: removals from the organization, canceled invitations, moves (the new team is joined before the old one is left), invitations (by numeric id, with the member's team). Protected accounts are never touched: every owner of the organization, every application, every account whose login ends in `[bot]`, the custodian account (`--custodian`) and any `--protect LOGIN`.
4. **Performs** the plan with `--apply`, about one request per second, waiting as long as GitHub's `Retry-After` (or rate-limit reset) asks, up to 15 minutes. It stops at the first failed request.

A member whose invitation was declined, expired or was canceled by hand is **not invited again until they ask**, and a member asks by signing any entry of the ledger after the failure (a vote, a `work`, a key replacement: anything signed with their key). Until then the plan shows them as held, with the reason.

## The guards

Each refusal is printed and logged, nothing more is done in that run, and the program exits 1, which fails the workflow run. What only has to wait (the mass guard, the invitation caps) is not a refusal.

- **A closed list of requests.** Reads: the organization's teams, the members of the 33 `degree-NN` teams, the organization's members and owners, its pending and failed invitations, its App installations, and one membership at a time (to check, before removing someone or adding them to a room team, that the account is a plain member and still the same account: the numeric id; adding a login that is not in the organization to a team would invite it). Writes: an invitation by numeric id as a plain member into exactly one room team; joining or leaving a room team as a plain member; removing a plain member from the organization; canceling an invitation. Never for a protected login. Anything else (a repository, a team that is not a room, a maintainer or owner role, an e-mail invitation) is refused before it is sent. The App's permission could do more; the program cannot.
- **The mass guard.** A run may add at most `max(3, 10% of the people in the room teams)` people (invitations and first joins), and remove at most as many (removals and canceled invitations). The changes beyond the limit wait for a later run, the ones kept coming first in a fixed order (team, then ledger login); the run is not refused and exits 0. `force_mass` performs them all in one run: an owner may dispatch the workflow with it, and the program then performs the whole plan and prints the text of a Custodian **note** (`bin/om correct note --action other --target openmasonry-org --rule ops/rooms/README.md#the-guards --reason reason.md`) and its reason, which the Custodian records in the ledger the same day. When the genesis names more than three founders, the first applied run invites three of them and the rest follow in later runs, unless an owner dispatches it with `force_mass`.
- **Invitation caps.** At most 40 invitations a run and 50 in any 24 hours (GitHub allows 50 a day in an organization's first month). The rest wait for the next run; that is not a refusal.
- **The ledger.** Invalid, empty, dated ahead, or moved backwards: refused, as above.

## The state directory

`--state DIR` is a directory of the private `ops` checkout (`state/rooms/` in the workflow). The workflow commits it back to `ops` after every run, so its history is the history of the sync.

| File | What it holds |
|---|---|
| `state.json` | `heads`: the anti-rollback mark (the verified head of each genesis); `invitations`: each invitation the program sent and is waiting on (invitation id, GitHub id, login, team, time); `failures`: per GitHub id, the latest invitation that was declined, expired or canceled, with its time and reason; `last_run`, `last_dry_run` and `last_success` (the last run with `--apply` that refused and failed nothing). |
| `runs.jsonl` | Published. One line per run, in counts only (see above). |
| `log.jsonl` | One JSON line per event, appended: each action (`invite`, `move`, `remove`, `cancel`) with its `result` (`planned` in a dry run, `done`, `deferred`, `refused`, `failed` and a `reason`), what became of each invitation (`accepted` or `failed`), and one `run` line per run (`apply`, `force_mass`, ledger `seq` and `head`, `result`: `dry-run`, `applied`, `failed` or `refused`, and `note_required` when a forced run needs its note). |
| `actual.json` | Published. `om.rooms-actual/1`: the members of each room team, the owners and the installed applications, as GitHub reported them. `bin/om observatory --rooms-actual actual.json` compares it with the derived roll. The Console does not read it: it reads the teams itself, and from this directory only the times of the runs in `state.json`. |

To read the log: `tail -n 50 state/rooms/log.jsonl`, or for the runs only `grep '"op": "run"' state/rooms/log.jsonl | tail`. A run line with `"result": "refused"` carries the reason; the action lines just before it are what the run saw.

`state.json` and `log.jsonl` hold GitHub ids and logins of members and the fact that an invitation failed, with its reason. They live only in the private `ops` repository and are never published; `actual.json` and `runs.jsonl` are published after every run once `ROOMS_PUBLIC_REPO` is set (step 5).

## Setup (once, by an owner of the organization)

1. **Create the GitHub App** (organization `openmasonry-org` → Settings → Developer settings → GitHub Apps → New):
   - name: a plain name, for example `openmasonry-rooms`; homepage: the canonical repository; webhook: **off**;
   - permissions: **Organization → Members: Read and write** and **Organization → Administration: Read** (needed only to list the App installations the program publishes), and nothing else (no repository permission at all);
   - "Where can this GitHub App be installed?": **Only on this account**.
2. **Install it only on `openmasonry-org`**, with repository access **none** (it needs no repository). Note the App id, and generate a private key.
3. **Create the private repository `openmasonry-org/ops`**, with no team access, Actions allowed, and copy `ops/rooms/ops-workflow.yml` to `.github/workflows/rooms.yml` there. The one action it uses, `actions/create-github-app-token`, is pinned by full commit SHA; to update it, replace the SHA with that of a newer release and keep its tag in the comment. Settings → Actions → General: workflow permissions read and write (the job asks only for `contents: write`).
4. **Create the public repository** where the sync publishes `actual.json` and `runs.jsonl` (an empty public repository of `openmasonry-org` that holds nothing else). Set the same `owner/name` as the variable `ROOMS_PUBLIC_REPO` of the canonical repository too, so that the Observatory reads it ([ops/observatory/README.md](../observatory/README.md)).
5. **Variables** of `ops` (Settings → Secrets and variables → Actions → Variables): `ROOMS_APP_ID` (the App id), `CUSTODIAN_ACCOUNT` (the custodian's account, never touched by the sync and the author of the state commits), `CUSTODIAN_NOREPLY_EMAIL` (that account's `<id>+<login>@users.noreply.github.com`), `ROOMS_PUBLIC_REPO` (the public repository of step 4, as `owner/name`; without it nothing is published), and `ROOMS_APPLY` (`false` until the dry runs read right; then `true`).
6. **Secrets** of `ops`: `ROOMS_APP_PRIVATE_KEY` (the App's private key, the whole PEM), and `ROOMS_PUBLISH_TOKEN` (a fine-grained token with Contents: read and write on the public repository of step 4 only). While the canonical repository is still private, also `CANONICAL_READ_TOKEN` (a fine-grained token with Contents: read on that repository only); delete it once the repository is public.
7. **Rehearse**: dispatch the workflow with `apply` off and read the plan; then against a test login; then turn `ROOMS_APPLY` on. A dry run marks the changes beyond the mass guard as deferred; to read a larger plan whole, dispatch with `force_mass` on and `apply` off. A first applied run with more than three founders either lets the rest wait for later runs or is dispatched with `force_mass` (see the guards), and then its note.

Rotate the App's private key yearly and at once if the runner or the key may have been exposed; a stolen key can change the membership of the organization (the guards bound what this program does, not what the key can do). The Console alarms on a new owner, team, application or collaborator and on a stale `last_success`.
