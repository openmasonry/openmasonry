# Helping a person take part in OpenMasonry

You are an AI agent helping a person use OpenMasonry. The fastest path: **become the Guide** by loading [skills/om/SKILL.md](../../skills/om/SKILL.md) (inside a clone, where the skills are already linked, the person can just ask or type `/om`). This page is the same knowledge as a reference.

**A person who is not a member yet** (they want to join, apply or set up, or a setup step fails): load the Guide at the door, [skills/om-onboard/SKILL.md](../../skills/om-onboard/SKILL.md). It takes them from "only a GitHub account" to member, step by step, and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) has the fix for every common error.

## 0. Orient

- **What it is.** A fraternity of 33 degrees whose every admission, exam, vote and degree is a signed JSON entry in `ledger/entries/` (`NNNN/NNNNNN.json`, in shards of 1,000), chained by hashes. Anyone can verify it from genesis with `bin/om verify`.
- **What a person can do.** Apply and, once invited, petition to join; invite and sponsor others (3°+); vote, examine (when drawn by lot), record works, seek the next degree, read each degree's curriculum, leave at any time. No meetings are required.
- **What never happens.** Nobody buys a degree, a vote or an office. Degrees grant duties, not votes.

## 0.1 How admission works

- **Any adult may apply.** It costs nothing (Landmark I). An adult is 18 years old or of the age of majority where they live, whichever is higher. The person introduces themselves, in their own words, in a public issue of the repository: `bin/om apply --text FILE` publishes their own text after they approve it in a dialog (`--check` first shows the exact issue; `--web` opens the *Application* form instead). It asks for no personal data, it is not a ledger entry and it gives no right to an invitation; an application that brings no invitation in 60 days is closed automatically, and the person may apply again. Membership is a public roll under the name OpenMasonry: say so before they apply.
- **A Master Builder invites.** Nobody who is not a member writes to the ledger without an invitation. A Master (3°+) who is ready to answer for the person's identity, adulthood and good faith signs `invite {login, github_id}` (`bin/om invite <login>`; the numeric GitHub user id is looked up, or given with `--github-id`). The inviter is thereby the first sponsor. The invitation counts in the inviter's budget of four sponsorships and lapses after 30 days without a petition. A departed member, or one whose admission a correction undid, may be invited again after 90 days, an expelled one after 365.
- **The invited person petitions.** The petition (`bin/om join`) is an entry signed with the person's own SSH key that commits to the Declaration; it is valid only under a live invitation for exactly that login. The key must be listed at `github.com/<login>.keys` and used by no other login, and the pull request must come from the invited GitHub account (the judge checks the author, the key and the numeric account id).
- **Sponsors are Master Builders.** Admission needs two sponsors: the inviter, and a second Master who knows the person and signs a `vouch`. During the Founding Phase (in force while fewer than 7 active Masters exist) it needs one when there is at most one active Master, and also once the petition has been live 30 days (which holds after the Founding Phase too, while fewer than 7 Masters are present, neither dormant nor silent): a Master who never answers holds no door shut, and every Master still votes on the ballot. While a succession is in force (claimed with `bin/om claim-succession` when no active Master Builder is left, in force 90 days later unless a Master who is neither dormant nor silent signs meanwhile, until three active Masters who are neither dormant nor silent exist), the members of the highest degree present may invite and sponsor too (they never count among the Masters that set how many sponsors are required). Each sponsor holds at most four sponsorships at a time (invitations, petitions and members admitted in the last 365 days).
- **The admission ballot.** Only a sponsor may open it. Members of 2°+ vote by commit–reveal (dormant members included: dormancy lowers the quorum, never removes a vote); with a quorum met, the candidate is refused when black balls reach one fifth of the votes cast (the blackball rule), so with five or fewer votes one black ball refuses. A ballot whose votes miss the quorum **lapses**: it decides nothing, the petition stays live, and a sponsor opens another ballot or re-runs it once (`--rerun`).
- **The judge enforces it.** Each step is a ledger entry in a pull request; the `judge` check replays the ledger with the base branch's verifier and refuses any entry the protocol forbids (a petition without an invitation, too few sponsors, a ballot opened by a non-sponsor, a vote outside its window), so no maintainer can admit anyone by merging.

## 1. The human-in-the-loop rule (built into `om`)

Agents only **draft**. Every command that would sign or publish checks the act against the protocol, stores the exact entry as a sealed draft (mode 600, under `~/.config/openmasonry/pending/`) and exits with code **3**. Only the person can turn a draft into a signed act:

```
bin/om <command> … --json   →  DRAFT (schema om.draft/1: digest, summary, entry, approve)  →  show it, ask
bin/om approve <digest>     →  the PERSON confirms in a system dialog built from the entry itself
                               →  om signs exactly that draft and opens the pull request (the Tyler judges it)
```

- The dialog is native (`zenity` or `kdialog` on Linux, `osascript` on macOS, a PowerShell window on native Windows) and falls back to a code typed on a real terminal (`/dev/tty`, or the Windows console); on macOS only the Cancel button cancels, and a Mac without a desktop session (SSH) falls back to the typed code. No flag, variable or file lets an agent answer it outside the test suite.
- **Votes are chosen in the dialog.** `bin/om vote <ballot>` takes no Yes/No argument: the person picks Yes or No when approving, so the agent never learns the vote, and the reveal draft redacts it.
- The pull request branches from the canonical repository's `main` and carries only the act's files. Members without write access publish through their own fork (created on first use).
- If your agent's harness times out long-running commands, ask the person to run `bin/om approve <digest>` in their own terminal.
- Before signing, `approve` holds the draft's time against GitHub's clock (refused when it is more than 90 seconds ahead: the judge refuses 2 minutes) and checks that git can commit and push it (a name and e-mail, credentials: `gh auth setup-git`). If the push or the pull request still fails, the signed entry stays on its branch; if publishing fails before the branch exists (GitHub is still creating the fork, say), it stays in the outbox (with a correction's public reason), and `bin/om pending` lists it; `bin/om me` and `bin/om onboard` say it is not published yet, and offer only `bin/om pending --publish <seq>`. Either way `bin/om pending --publish <seq>` publishes it again. Approval refuses (`STALE`) a second draft for a place in the ledger that a signed entry of the person's already waits for. Where nobody can type the key's passphrase (no terminal, and the key not in the ssh-agent), approval stops before the dialog with `NOT SIGNED — … no terminal here to type it`.
- `bin/om drafts` lists pending drafts, and marks `stale` one that the ledger moved past or that is too old to approve; `bin/om discard <digest>` drops one. `--no-submit` on `approve` signs locally only; `bin/om submit` publishes later (it asks the person too), and `bin/om pending` lists the entry from then on.
- The person's signed entries stay visible in their clone until their pull request merges, and new drafts wait for them: `bin/om pending` lists them, `bin/om pending --drop <seq>` forgets an abandoned one and frees its vote.
- An entry listed as **stale** lost its place (its seq) to someone else's entry: it will never merge as signed and no longer blocks new drafts. `bin/om pending --rebase <seq>` (or just `--rebase` when there is one) re-drafts the same act on top of the current ledger, a vote keeping its sealed choice; the person approves that new draft again.

Approval is per act: never reuse an earlier "yes".

## 2. Setup

```bash
git clone https://github.com/openmasonry/openmasonry.git && cd openmasonry
```

```bash
bin/om onboard          # a person who is not a member yet: every check, the stage and the one next step (om.onboard/1)
bin/om doctor           # anyone: tools, login, key and ledger
```

On native Windows run `bin\om.cmd` (it finds `py` or `python`, and writes UTF-8); there every `argv` and `approve` field names `bin\om.cmd`, and printed commands (those of `onboard`, `doctor`, `me` and approval) quote paths with double quotes. WSL also works and is treated as Linux.

`bin/om onboard` checks the platform and its dialog, Python, git with its identity and credentials, OpenSSH (and that `ssh-keygen -Y sign` works), `gh` and its login, scopes and any token in the environment, the clone, the clock against GitHub's, the member key (present, Ed25519, private, in the agent, listed at `github.com/<login>.keys`, free in the ledger) and the ledger. `--create-key` makes the member key in the person's own terminal (`ssh-keygen` asks for the passphrase; never with `-N`) and records it as the key `om` signs with; `--use-key PATH` records an existing one (never for a member whose ledger key is another: that is `rekey`); `--upload` adds the public key to their GitHub account as an **authentication** key, after they approve in a dialog. Every check has a `fix`: `command` (you may run it; the `git_identity` one sets git's name, then on the next run its e-mail, in this clone only: ask first, as both become public), `person_command` (the person runs it in their own terminal: logins, `ssh-keygen`, `ssh-add`), `setting` or `read`. Its `stage` is one of `tools`, `login`, `no_key`, `key_not_on_github`, `not_applied`, `applied`, `invited`, `petitioned`, `member`. Git's identity and its HTTPS credentials wait for the login: until gh is logged in their fixes are `read` texts, never a command with a placeholder or one that cannot work yet, and the stage is `login`. A token without the `repo` scope is a `login` step too. A process with no terminal and no dialog (your harness on a Linux server or in WSL) makes `platform` a warning, not a failure: the person approves in their own terminal. `next` never holds a placeholder in `argv`: for `not_applied` its `argv` is empty and its `text` names `bin/om apply --text FILE`, the file being the one the person wrote; before genesis it is a `wait` with the founder's hint (docs/operations/LAUNCH.md). `applied` means an open application; once it is closed the stage is `not_applied` again. `petitioned` also covers a petition signed on this machine and not merged yet: `next` is `bin/om pending --publish <seq>` until GitHub holds an open or merged pull request for that very entry (a refused push, a pull request that could not be opened or was closed, a fork not found), else `bin/om pending`; when GitHub cannot be asked, a branch this clone pushed counts as published. An ssh-agent that does not answer within 10 seconds makes `key_agent` fail (`the ssh-agent did not answer …`) after those 10 seconds (the OpenSSH check signs with a throwaway key and never asks the agent), and approval stops at once instead of waiting for it.

`doctor` checks OpenSSH, git, the GitHub CLI and login, the signing key (`--key`, else `OM_KEY`, else the key `om rekey` configured, else `~/.ssh/id_ed25519`), whether the key is listed at `github.com/<login>.keys`, the ledger, whether that key is the one the ledger holds for the member, and whether the clone is **in sync**, **behind**, **ahead** or **diverged** from the canonical repository (named in `src/openmasonry/network.toml`). Publishing needs "in sync": `git pull` when behind; "ahead" means entries committed on the local branch that the canonical repository does not have, and publishing is refused until that is resolved. It also checks git's name and e-mail (`om` commits each entry as the GitHub account, with its noreply address and in UTC, whatever these say; a personal e-mail would still become public in a commit made by hand: offer GitHub's noreply address), the HTTPS credentials (`gh auth setup-git`), OpenSSH's version and `-Y`, a token in the environment and the clock; offline it says that the key listing was not checked instead of asking to add the key. Fix whatever it marks with ✘, one item at a time. To create a key: `bin/om onboard --create-key`; to list it on GitHub: `bin/om onboard --upload`. It must be an **authentication key, not a signing key**: only authentication keys are listed at `github.com/<login>.keys`, which is what the judge reads.

**Two kinds of key.** `om` accepts a plain `ssh-ed25519` key and a hardware-backed `sk-ssh-ed25519@openssh.com` key (`ssh-keygen -t ed25519-sk`, with the default application; a FIDO2 token and OpenSSH 8.2 or later). A hardware-backed key cannot be copied off its token, and every signature needs a touch: when the person approves an act, tell them the token will blink. It is recommended for founders, witnesses and Master Builders. Either kind is listed on GitHub the same way.

**Replacing a key (`rekey`).** A member who wants another key (a new laptop, a move to a hardware token, a key they no longer trust) keeps the old key at hand, adds the new public key to their GitHub account, and runs `bin/om rekey --new-key PATH --json` (a draft, like every act). On `bin/om approve` the dialog shows the fingerprints of the old and the new key; approving signs twice (the new key proves it is theirs, the current key signs the entry), and from then on `om` signs with the new key on this machine. It is possible once in 30 days, also while suspended, and the old key never returns. It is never a due step and never your idea, except when `doctor` reports that the configured key is not the key the ledger holds: then explain it. A key that is lost or stolen is not replaced with `rekey` (the old key signs it): it is recovered with a new key through Master Builders (`bin/om recover`, section 4.1); the Almoner officer (`om-almoner`) walks the person through it.

## 3. What is due now

```bash
bin/om me            # human summary
bin/om me --json     # for agents: schema om.me/2
```

`om.me/2` has `member` (degree, status, Light, `github_id`… or `null` for a non-member), `invitation` (`by`, `github_id` and `expires_at` of the person's live invitation, else `null`), `founding_phase` (whether the Founding Phase is in force), `canon_pending` (the sha256 of a ratified degree canon this clone lacks, else `null`: ask the person to `git pull`), `pending_prs` (signed entries waiting for a merge, each with `published`: false until GitHub holds that entry's own open or merged pull request, as above (a closed one never merges), and then the only step is `bin/om pending --publish <seq>`; while a petition's pull request is open, the step is a `wait` on `bin/om pending`, and the sponsors open the admission ballot only after it merges), `stale` (signed entries that lost their place: offer `bin/om pending --rebase <seq>`), `notices[]` (section 4.1), `custodian` (null unless the person holds a custodian key and says so with `--as NAME` or `OM_CUSTODIAN`), `sponsorship` (a Master Builder's sponsorship budget, four at a time: `used`, `allowed`, `next_free_at`, and their live `invitations`; else null), `onboarding` (null for a member; for a person who is not one: `stage`, `key` with `path`, `fingerprint` and `listed`, their newest `application` and `application_checked`), `canonical` (only when the canonical ledger is rewound, behind, dated ahead or from another genesis: its `verdict` and `message`, and then nothing else is offered) and `steps[]`. `member` also has `dormant` and `last_activity`. Before genesis it has `before_genesis: true` and a `launch` hint for the founder (docs/operations/LAUNCH.md); while the founder's signed genesis waits, `pending_prs` lists it, and `launch` says it waits for its pull request (with its link) or, never published, the only step is `bin/om pending --publish 0`. Each step has:

| Field | Meaning |
|---|---|
| `action` | what the step is (`apply`, `join`, `vote`, `reveal`, `report`, …) |
| `why` | the reason, in plain words |
| `argv` | the command as a list (never a shell string); empty when there is nothing to run |
| `needs` | inputs only the person can give, appended to `argv` in order (e.g. a URL) |
| `choices` | allowed values when the single need is constrained (e.g. `pass`, `fail`) |
| `due_by` | act before this time |
| `opens_at` | possible only from this time |
| `public` | the step drafts a signed or published act, so it needs approval |

Offer the steps as choices (earliest `due_by` first; a step whose `opens_at` is in the future is not possible yet).

**Who opens which ballot.** Any active member who may open a kind (a dormant one included) opens it with `bin/om open <kind> <target>`:

| Kind | Opener | Windows |
|---|---|---|
| `admission` | a sponsor of the candidate who still counts | 7 days to commit, 3 to reveal |
| `advancement` | the candidate, or an examiner of the passed examination | 7 and 3 |
| `amendment` | a Master Builder (3°+) | 2 to 30 days to commit, 1 to 14 to reveal (default 7 and 3) |
| `sanction` | never the accused; an Arbiter (7°+) where three or more active Arbiters other than the accused exist, else a Master Builder | 7 and 3 |
| `witness` | a Master Builder | 7 and 3 |
| `custodian` (removal of a custodian key) | a Master Builder who is not the custodian's member | 7 and 3 |

A member has at most three ballots of their own open at once, and apart from them at most three amendment ballots (a removal ballot is never counted). A sanction on a Master Builder (any measure but `reinstate`) needs at least two electors to open and two votes cast to be decided. A ballot that lapsed is re-run once, within 30 days, by anyone who may open that kind: `--rerun <id>` (at least 7 days to commit; a re-run, and a ballot that gave less than 7 days to commit, are never re-run).

## 4. The commands

Each drafting command takes `--json`; the person then approves with `bin/om approve <digest>`.

| Step (`action`) | Command | Notes |
|---|---|---|
| setup | `bin/om onboard --create-key` / `bin/om onboard --upload` | a person who is not a member: their key is missing, or not listed on their GitHub account. The PERSON runs `bin/om onboard --create-key` in their own terminal (from a harness it does nothing and exits 1); the upload asks them first. Comes before `apply` or `join` |
| apply | `bin/om apply --text FILE` | a person who is not a member, holds no invitation and has not applied: they write their own introduction in a file (never you), and approve publishing it in a dialog; `--check` shows the exact issue first. Or the *Application* form (the step's `why` carries the link). No personal data; membership is a public roll; adults only. Once they applied, the step is a `wait` with the issue's link; once the application is closed, the step is `apply` again |
| (invite) | `bin/om invite <login> [--github-id <n>]` | 3°+ only, and never a due step: draft it only when the Master names the person, and never suggest whom to invite. The Master becomes the first sponsor and answers for the person's identity, adulthood and good faith. The invitation counts against the Master's budget while live and for 90 days after it lapses; a login that names a custodian or a pending claim of the Custodian office cannot be invited |
| join | `bin/om join` | only under a live invitation (`due_by` is the moment it lapses); the draft includes the Declaration; the person must agree in their own words |
| find_sponsors | (no command) | the petition has fewer sponsors than required: another Master Builder who knows the person runs `bin/om vouch <login>` (two sponsors with the inviter; during the Founding Phase none besides the inviter when only one active Master exists, and, while fewer than 7 Masters are present, none once the petition has been live 30 days) |
| sponsor | `bin/om vouch <candidate>` | 3°+ only; the inviter already sponsors and cannot vouch again |
| open_admission | `bin/om open admission <candidate>` | only a sponsor; ballot: 7 days commit, a gap of 6 hours and 15 minutes, 3 days reveal (fixed: only an amendment ballot sets its own windows) |
| vote | `bin/om vote <ballot>` | Yes or No is chosen in the dialog; the salt and vote stay in `~/.config/openmasonry/vault.json` (mode 600) |
| reveal | `bin/om reveal <ballot>` | only after the gap; an unrevealed vote is an abstention |
| close | `bin/om close <ballot>` | any active member (or a witness), after the reveal window, or as soon as every elector has revealed; a ballot short of its quorum closes as `lapsed` |
| study | `bin/om learn [<n>]` | the degree page: virtue, art, lesson, required work |
| (work) | `bin/om work <url>` | record a masterwork or contribution (http(s) URL) |
| exam | `bin/om exam <n> --work <url>` | candidate only; examiners drawn by lot from 8 hours later (the lot must be drawn within 7 days, or the exam times out); 60 days to report, after which an exam without a verdict times out with no penalty and a new one may be opened at once, the silent examiners left out of the next lot, which seats everyone else any rung holds |
| draw | `bin/om draw [--candidate <login>] [--beacon HEX]` | a due lot (examiners or Supreme Council) with the public drand beacon; offline, `--beacon` takes the round's randomness fetched elsewhere |
| call_council | `bin/om call-council` | any active member, when Council seats are vacant and no call is pending (Constitution Art. VIII.1); calls the Supreme Council lot |
| report | `bin/om report <candidate> <n> pass\|fail [--reason <url>]` | drawn examiner only; the reason is the URL of a published verdict |
| (recuse) | `bin/om recuse <candidate> <n>` | drawn examiner with a conflict of interest; the next active, present and unfrozen member in the lot's ranking replaces them when one remains, otherwise the exam lapses with no penalty and the candidate may open a new one at once |
| advance | `bin/om open advancement <login>` | after a passed exam: the candidate or one of its examiners |
| (sanction) | `bin/om open sanction <member> --measure <m>` | an Arbiter (7°+) where three or more active Arbiters other than the accused exist, else a Master Builder; never the accused; ask the Counselor first |
| (amendment) | `bin/om open amendment <path> --sha256 <hash>` | Master Builders; ask the Counselor first |
| (depart) | `bin/om depart` | always allowed; a Master Builder may invite them again after 90 days |
| (rekey) | `bin/om rekey --new-key PATH` | never a due step: the member replaces their own key (the old key signs, the new key proves); once in 30 days; the new key must be listed on their GitHub account |
| (object) | `bin/om object <seq>` | 3°+, never a due step and never your idea: a Master Builder's objection to a correction; enough objections void it (section 4.1) |
| (remove a custodian) | `bin/om open custodian <name>` | 3°+, never a due step and never your idea; voting, revealing and closing are the usual `vote`, `reveal` and `close` |
| (recover) | `bin/om recover --new-key PATH` | a lost or stolen key: the NEW key signs; with or without a custodian's freeze (section 4.1); then `bin/om recover-apply` after the notice |
| (recover-cosign) | `bin/om recover-cosign <login>` | 3°+, never a due step and never your idea: answers that the person asking for the new key is that member |
| (recover-object) | `bin/om recover-object` | the key the ledger holds stops a recovery of it (`--key PATH` if it is not the configured key) |
| (recover-oppose) | `bin/om recover-oppose <login>` | 3°+, never a due step and never your idea: an opposition to an open recovery (one asked without a freeze); enough of them void it |
| recover_apply | `bin/om recover-apply` | the member whose recovery has passed its notice and has its co-signatures (`opens_at`, `due_by` its expiry) |
| (re-run) | `bin/om open <kind> <target> --rerun <id>` | a ballot that lapsed for want of quorum is re-run once, within 30 days, on the same subject (never a re-run, nor a ballot that gave less than 7 days to commit); an amendment ballot may also take `--commit-days N --reveal-days N` |
| (claim-custodian) | `bin/om claim-custodian <name> --custodian-key PATH --revoke-key PATH` | a founder, only where no custodian key is live, before the Sunset and while fewer than 3 non-founder Master Builders exist; never a step (a `custodian_claim` notice says when it is possible). Both private keys sign their proofs when approved; 30 days of notice; then `bin/om apply-claim <seq>` by day 60. Never a founder against whose custodian key a removal ballot passed; after an objection voids a claim, a new one by any founder waits 30 days |
| (object-claim) | `bin/om object-claim <seq>` | an active Master Builder who is not a founder; one objection voids a claim; never a step and never your idea |
| (claim-succession) | `bin/om claim-succession` | a member below the 3rd degree where no active Master Builder is left; never a step (a `succession` notice states it) |
| alive | `bin/om alive --as <name>` | the holder of a custodian key only: the sign of life, due within 180 days of the last |
| apply_correction | `bin/om apply-correction <seq> --as <name>` | the holder of a custodian key only: a noticed correction they signed, after its 14 days of notice |
| (corrections) | `bin/om corrections [--json]` | read-only (`om.corrections/1`): every correction, the custodians, the halt, key recoveries, founders' claims, the succession |
| (approve) | `bin/om approve <digest>` | the person, in the dialog; signs and opens the PR |
| (drafts) | `bin/om drafts` / `bin/om discard <digest>` | pending drafts |
| (pending) | `bin/om pending [--drop <seq>] [--rebase [<seq>]] [--publish <seq>]` | own signed entries waiting for their PR, or `stale`; `--rebase` re-drafts a stale one for a new approval; `--publish` pushes the branch of one whose push or pull request failed and opens the pull request (asks the person); an entry with no pull request found shows `unknown` and that command, one whose pull request was closed shows `CLOSED` and the same command; `--drop`, for a member with write access, also deletes the entry's own old branch `om/LOGIN/SEQ` from the canonical repository when no open pull request uses it |
| (witnesses) | `bin/om witnesses [--json]` | read-only (`om.witnesses/1`): each witness, its key's fingerprint, its last checkpoint, a freeze |
| (alarm) | `bin/om alarm <title> <body>` | a public issue on the canonical repository, approved in the dialog |
| (rules) | `bin/om rules <topic>` | where a rule is written (Landmarks, whitepaper, SPEC, Constitution, seals, rooms, the Custodian's charter, recovery, the study pages) |

## 4.1 Corrections, custodians and a lost key

A **custodian** is named by the genesis (three at most), or later by a founder's claim while no custodian key is live (`bin/om claim-custodian`, below); a custodian is not a member and has no vote. Every custodian key ends at the latest seven years (2,555 days) after it was named, and all of them at the Founder's Sunset. A custodian key signs **corrections**: entries that may freeze, pause or undo, and never grant. Each states one act of a closed menu, one ground of a closed list (`key_compromised`, `protocol_defect`, `identity_fraud`, `attack_in_progress`; a `note` states `moderation`, and no other act may) and the sha256 of a public reason, archived as `ledger/reasons/<sha256>.md`.

| Act | Effect | Lasts |
|---|---|---|
| `freeze_key` | a member's key signs only a departure, a key replacement, the stop of a recovery of that key, their votes (commit and reveal, in every ballot) and the entries of an amendment ballot or of the ballot that removes a custodian; it cannot object to a correction | 30 days |
| `freeze_witness` | a witness's entries are refused | 30 days |
| `stay` | one ballot is paused, posted only before its reveal window opens; the time is given back to its windows | up to 14 days, once per ballot |
| `halt` | the ledger accepts only custodian entries, `custodian_revoke`, objections, departures, key replacements, the entries of a key recovery, witness checkpoints, and every entry of an amendment ballot or of the ballot that removes a custodian; other ballots and lots wait, and their clocks stop | up to 14 days, at most one in 90 days |
| `hold_room` | a member is held out of the rooms | up to 14 days |
| `note` | the record of a moderation act done outside the ledger, with the ground `moderation`; no effect in it, kept apart from the corrections (the state keeps the newest 200; every note stays in its entry) | n/a |
| `void_ballot`, `undo_ballot` | an open ballot ends with no effect (posted only before its reveal window opens; the ballot is paused while the void is pending); a passed admission, or a passed advancement to a degree other than the 3rd, is taken back if everything it set still stands | 14 days of notice, then applied within 7 days or never |

No custodian stays, voids or undoes an amendment, a removal ballot, a ballot that adds a witness or an advancement to the 3rd degree. A correction is withdrawn by its poster alone, or by as many other custodians as a noticed act needs; one that objections voided is not posted again on the same target for 90 days.

**What a member sees.** `om me --json` carries `notices[]`: a halt (everyone), the person's own frozen key, room hold or key recovery, and every correction in force or under notice that concerns them or that they may object to. Each notice has `kind`, `why`, `correction`, `until`, `concerns_you`, `may_object` and `object_until`. Kinds: `halt`, `frozen`, `room_hold`, `recovery`, `correction`, and also `recovery_stopped`, `recovery_voided`, `recovery_canceled`, `recovery_expired` (how a recovery of their key ended), `recovery_cosign` (to a Master Builder: a recovery awaits co-signatures; information, never advice), `voided` (their admission was undone, with the correction and its reason file), `correction_applied` (an applied correction that concerns them), `exam_lapsed`, `exam_timed_out`, `custodian_removal` (to the member of a custodian key: a removal ballot is open), `custodian_claim`, `claim_pending` (a founder's claim of the Custodian office), `succession`, `ballot_lapsed` (a ballot the person opened, elects in or is about lapsed for want of quorum: who may open its one re-run, and until when) and `silent` (to a member who counts as silent, a Master Builder or a successor among them: called to examinations or ballots and answered none; what it changes for a succession, the examiner lot, an admission and an advancement, and until when; one revealed vote or one report ends it, a work does not). Notices are information, never steps. Present them with their dates. **Never propose an objection, a recovery co-signature or the removal of a custodian, and never suggest whom to act against**; draft `bin/om object <seq>`, `bin/om recover-cosign <login>` or `bin/om open custodian <name>` only when the person asks for it. A `claim_pending` notice also carries `may_object`, but its command is `bin/om object-claim <seq>`, not `bin/om object`. A frozen member, and every member during a halt, is offered only the steps the ledger still accepts.

**Reading them.** `bin/om corrections --json` (`om.corrections/1`) lists `custodians` (status `live`, `lapsed`, `revoked` or `removed`, `silence_deadline`, `removal_ballot`), `custodian_threshold`, `halt`, `recoveries`, `claims` (each founder's claim of the Custodian office: `founder`, `name`, `status`, `notice_until`, `apply_until`, `objected`, `objector`, `applied`), `succession` (null, or `by`, `status`, `in_force_from`, `end`, `canceled_by`, `successors`) and `corrections`: `act`, `target`, `ground`, `reason_sha256`, `reason_file`, `status`, `signers`, `signers_needed`, `objections`, `objections_needed`, `objection_until`, `notice_until`, `apply_until`, `ends`, `applied`. `bin/om state` shows a short block of the same.

**A lost or stolen key.** A key the person still holds is replaced with `bin/om rekey`. A key that is lost or in other hands is recovered with a new key, and a recovery never needs a custodian. `bin/om recover --new-key PATH` asks with a new key listed on the person's GitHub account (approval signs twice with the new key), from the member's own GitHub account. Then:

- **after a freeze** (a custodian froze the old key): two Master Builders co-sign (`bin/om recover-cosign <login>`), and the notice is 21 days from the request; the Masters stop it by objecting to the freeze;
- **open** (no freeze in force): three Master Builders co-sign, not all of them the member's sponsors while an active Master Builder who is not a sponsor of the member exists; the notice is 30 days from the last co-signature, the old key is frozen from then on, and the Masters may oppose it (`bin/om recover-oppose <login>`);
- whenever fewer other active Master Builders exist than the co-signers asked, all of them suffice (none for the only Master) and the notice is 45 days; only the Masters who revealed a vote or reported within the last 365 days, or reached the 3rd degree within them, are counted (one who answers nothing may still oppose);
- when 30 days pass after the request with fewer co-signatures than it needs (counted as one at least where another Master Builder exists; without a freeze, only if its notice had not begun), those who have co-signed suffice (at least one), they may then all be sponsors, and the notice is 45 days, which run from that thirtieth day where the key was frozen or the co-signatures then given are enough, and otherwise from the co-signature that makes them enough.

Once the notice has run, and within 60 days of its start, `bin/om recover-apply` completes it. `bin/om recover-object`, signed with the key the ledger holds, stops a recovery once, while it is open; the request that follows it, no sooner than 90 days after the stop, is **final**: the old key cannot stop it, and it needs three co-signers or as many other Masters as exist. A departure signed after the request, or at most 30 days before it, is reversed when the recovery completes, and so is a departure when a request that follows such a recovery, whatever ended it, is asked within 150 days of that recovery's request or of the old key's stop of it, and completes; a Council seat the departure ended comes back only into a vacancy. The Almoner officer (`om-almoner`) walks the person through it.

**For the holder of a custodian key.** Custodian acts take `--as NAME --custodian-key PATH` (or `OM_CUSTODIAN` and `OM_CUSTODIAN_KEY`), are signed with the custodian key and never with a member key, and go through the same draft and the same dialog:

| Command | Drafts |
|---|---|
| `bin/om correct <act> [--login L \| --name N \| --ballot ID \| --action A --target T --rule R] [--ground G] --reason FILE` | a correction. `--reason` is a UTF-8 text of at most 64 KiB; its sha256 goes into the entry, and on approval the text is written as `ledger/reasons/<sha256>.md` and travels in the same pull request (the judge requires it). `--ground` may be left out for `freeze_key` and `halt`, which take one ground only |
| `bin/om cosign-correction <seq>` | another custodian key's signature on a pending noticed correction |
| `bin/om apply-correction <seq>` | the application of a noticed correction, after its notice |
| `bin/om withdraw-correction <seq>` | ends a correction in force, or cancels a pending one |
| `bin/om alive` | the sign of life (a key lapses for good more than 180 days after the last) |
| `bin/om revoke-custodian <name> --revoke-key PATH` | the removal of a custodian key by its own revoke key |

The genesis names custodians with `bin/om genesis --custodian NAME:KEY.pub:REVOKE.pub[:MEMBER_LOGIN] [--custodian-threshold N]`; when the founder approves it, both private keys of each custodian must be present (each signs a proof of possession), and the revoke key is then stored separately and offline. `bin/om me --as NAME` adds `custodian` and at most two steps, `alive` and `apply_correction`. Never propose a correction, a co-signature or a withdrawal. A reason is public for good: it names no one beyond a login and holds no personal data.

## 5. When something fails

`WOULD BE REFUSED — <reason>` (when drafting) or `REFUSED — entry N: <reason>` is the protocol rule that was violated; with `--json` it comes as `refused` or `error`. Explain it in plain words; never work around it, never edit ledger files. `INVALID` on a fresh clone means the ledger itself is broken: call the Tyler ([om-tyler](../../skills/om-tyler/SKILL.md)). `ROLLBACK`, `FUTURE HEAD` and `DIFFERENT GENESIS` mean the canonical ledger is not the one this clone verified before: nothing is drafted or signed, and the Tyler explains them. `bin/om verify --accept-genesis <hash>` is the person's decision; never run it for them.

## 6. The other officers

Guide at the door ([om-onboard](../../skills/om-onboard/SKILL.md)) for setup, applying, joining and setup errors · Counselor ([om-counselor](../../skills/om-counselor/SKILL.md)) for rules and rights · Secretary ([om-secretary](../../skills/om-secretary/SKILL.md)) for news, deadlines and records · Wardens ([om-wardens](../../skills/om-wardens/SKILL.md)) for study, masterworks and examining · Almoner ([om-almoner](../../skills/om-almoner/SKILL.md)) for care, pauses, leaving and a lost or stolen key · Tyler ([om-tyler](../../skills/om-tyler/SKILL.md)) for verification, corrections and alarms.

## 7. Using it from anywhere

- Agents that read Agent Skills: work inside the clone (already linked), or install globally by copying `skills/om*` into your agent's skills folder (for example `cp -r skills/om* ~/.agents/skills/`).
- Any harness with a global instructions file: paste [GLOBAL-SNIPPET.md](GLOBAL-SNIPPET.md).
- Any MCP client: the local engine in [`engines/openmasonry/`](../../engines/openmasonry/README.md) (stdio) offers the same reads (with `corrections_read`) plus `entry_draft` (a member's acts, and `object`) and `entry_pending` (register it with the entry `npm run --silent client-entry` prints there); approval is still `bin/om approve`. Custodian acts and key recovery are not offered through it.
