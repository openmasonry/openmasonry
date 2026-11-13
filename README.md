<div align="center">

<img src="docs/assets/logo.svg" width="112" alt="OpenMasonry logo: three blocks rising, the last one lit">

# OpenMasonry

**The Open Craft: a verifiable, tokenless, self-governing fraternity of 33 degrees, built on Git.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Text: CC BY-SA 4.0](https://img.shields.io/badge/Text-CC_BY--SA_4.0-lightgrey.svg)](LICENSE-TEXT.md)
![Tokens](https://img.shields.io/badge/tokens-none-black.svg)
![Dependencies](https://img.shields.io/badge/runtime_deps-Python_stdlib_%2B_OpenSSH-blue.svg)
![Status](https://img.shields.io/badge/status-v0.1_Genesis-orange.svg)

[Whitepaper](docs/whitepaper/WHITEPAPER.md) · [Specification](docs/whitepaper/SPEC.md) · [Constitution](CONSTITUTION.md) · [The 33 Degrees](docs/degrees/README.md) · [Architecture](docs/architecture/ARCHITECTURE.md) · [Roadmap](ROADMAP.md) · [Patron Seals](docs/whitepaper/SEALS.md) · [For agents](AGENTS.md) · [Wiki](wiki/index.md) · [Contributing](CONTRIBUTING.md) · [Custodian's charter](docs/governance/CUSTODIAN.md) · [Launch checklist](docs/operations/LAUNCH.md) · [Recovery](docs/operations/RECOVERY.md)

</div>

---

> *"The royal secret is that no one should hold it alone."* (Lesson of the 32nd degree)

OpenMasonry keeps what made Freemasonry endure for three centuries (degrees as a curriculum of character, sponsorship, the ballot, the lodge as a school, the builder's allegory) and removes what lets fraternities be captured: **secret government, discretionary rules and permanent power.**

- **Open door.** No one is refused for sex, origin, belief or unbelief.
- **Everything verifiable.** Every admission, exam, ballot and degree since genesis is a signed, hash-chained entry that anyone can replay offline. No entry is ever rewritten or erased: a wrong is repaired only by a new public entry.
- **One member, one vote.** Degrees grant duties, never extra votes.
- **No permanent power.** Every office has a term, the Supreme Council is filled by verifiable lot, and a member who stops taking part stops being counted, and keeps the vote.
- **Nothing for sale.** No token, no fee, no purchasable rank or access.
- **Runs itself.** GitHub is the social layer, CI is the Tyler, witness nodes checkpoint and anchor the ledger.
- **One bounded exception, stated openly.** As a member, no founder has any power another Master Builder lacks. Until the Sunset a founder named Custodian (by the genesis, which at the founding ceremony names the first founder, or by a founder's claim) also holds that office, with the powers of the Corrections article and no others ([below](#the-custodian-and-corrections)).

## How it works

```
  GitHub (issues · PRs · discussions)  ──►  ledger/entries/NNNN/*.json  ──►  witness nodes  ──►  OpenTimestamps / mirrors
        social layer                         hash chain + SSH sigs       checkpoints          permanence
                                             replayed by the Tyler       close ballots
```

| Concept | In one line |
|---|---|
| **Tracing Board** | the ledger: one signed JSON file per event, each committing to the previous one |
| **The Tyler** | CI whose `judge` check replays the whole ledger of every PR with the base branch's verifier (the PR is read as data, never run) and refuses anything the protocol forbids |
| **Ballot** | commit–reveal (7 days to commit, then 3 to reveal after a gap of 6 hours and 15 minutes; only an amendment chooses other windows, 2 to 30 (at least 7 while an elector is dormant) and 1 to 14 days); it closes early once every elector has revealed, lapses without penalty when too few vote, and an admission or an advancement is rejected when black balls reach ⅕ of votes cast |
| **Lot** | verifiable sortition from a drand beacon about 8 hours in the future, over a pool frozen in advance; draws examiners and the Supreme Council |
| **Light** | a public, decaying score of service (half-life 180 days); never a vote weight |
| **Landmarks** | seven principles pinned at genesis that no ballot can ever change |
| **Governed files** | the Constitution, the degree canon, the charters of the Custodian and of the rooms, and the protocol core (`@protocol`: the verifier and the judge), pinned at genesis and changed only by amendment |
| **Correction** | a signed, public entry by which a Custodian repairs damage without rewriting anything: it may undo, freeze or pause, and never grant; Master Builders stop it by objection |

## The 33 degrees in six houses

| House | Degrees | Purpose |
|---|---|---|
| The Craft Lodge | 1–3 | Self-knowledge and the tools of the work. **3° Master Builder is full membership.** |
| The Lodge of Perfection | 4–14 | Duty, stewardship and justice inside the community |
| The Chapter of the Rose | 15–18 | Rebuilding, liberty of conscience and active charity |
| The Council of Kadosh | 19–30 | Philosophy, law, and the defense of the commons against capture |
| The Consistory | 31–32 | Audit, judgment and the balance of powers |
| The Supreme Council | 33 | Guardianship of the Constitution. 33 seats by lot, once per lifetime |

Every degree requires a public *masterwork* that improves the commons, so the fraternity builds its own infrastructure as its members learn. Full catalog with coats of arms: [`docs/degrees/`](docs/degrees/README.md).

## Rooms

Each degree has a **room**: a closed place where those who study it talk, ask questions, share drafts and mentor one another. A room is closed but never secret (Landmark II): its existence, its rules and its roll are public; its door opens by rule, to the members of that degree and of every higher one, as the ledger shows; nothing said in it has force; and no one owes silence about it. The teaching of every degree, and everything a member is examined on, stays public in [`docs/study/`](docs/study/README.md). The 33 rooms are private repositories of a separate GitHub organization, `openmasonry-org`, for conversation only; a published program sets their readers from the ledger and, on every run, writes, and its workflow publishes to the public repository named by `ROOMS_PUBLIC_REPO`, the access the host actually grants (the readers of each room, the owners of the organization and every installed application) and an anonymous log of its runs. The program is built, not running yet: the rooms open at the public launch; their rules are already law: [Constitution Art. XV](CONSTITUTION.md#article-xv-rooms) and the [rules of the rooms](docs/governance/ROOMS.md).

## The Custodian and corrections

OpenMasonry never rewrites its ledger. When something goes wrong (a stolen key, a ballot captured by fraud, an attack), the repair is a **correction**: a new signed entry of a closed kind, on one of four closed grounds (`key_compromised`, `protocol_defect`, `identity_fraud`, `attack_in_progress`), with a public reason archived under its SHA-256 in `ledger/reasons/`; the public record of a moderation act (a `note`) states a fifth ground of its own, `moderation`. Corrections are made by a **Custodian**: an office outside the 33 degrees, named in the genesis entry, or later by a founder's claim, with a custodian key, a separate revoke key and the login of the founder who holds them.

| A correction can | A correction can never |
|---|---|
| freeze a member's key or a witness key for 30 days | admit, advance, appoint, reinstate or sanction anyone |
| stay one ballot for 14 days, once, before its reveal window opens | change a vote, a key, a governed file, a Landmark or the Corrections article |
| halt the ledger for 14 days under attack, at most once in 90 days | touch an amendment ballot, the ballot that removes a Custodian, a ballot that adds a witness or an advancement to the 3rd degree |
| hold a member out of the rooms for 14 days | keep a member from departing, from replacing their own key or from voting to remove a Custodian |
| after 14 days of public notice, void an open ballot (posted before its reveal window opens; the ballot is paused meanwhile), or undo an admission or an advancement below the 3rd degree closed within 90 days | take effect in secret: every act is an entry anyone can read (`bin/om corrections`) |

Master Builders stop a correction by signed **objection** (`bin/om object`): it is void for good when the objections reach one fifth of the eligible Masters, and never fewer than one. They remove a Custodian by simple majority (`bin/om open custodian NAME`), in a ballot that no halt and no correction can touch. The office also ends without a vote: after 180 days without a signed sign of life, on revocation by its own revoke key, at the end of a seven-year term (2,555 days), and at the **Sunset**, the first entry after which the ledger shows seven active Master Builders who are not founders and four witnesses. While no custodian key is live, before the Sunset and with fewer than three active Master Builders who are not founders, a founder may take up the office again (`bin/om claim-custodian`): the claim waits 30 days of public notice, one objection by a Master Builder who is not a founder voids it (`bin/om object-claim`), after which no founder claims the office again for 30 days, and otherwise the founder applies it (`bin/om apply-claim`); a founder against whose custodian key a removal ballot passed never claims again. Otherwise no ballot and no lot appoints a Custodian; where none is live, no correction exists, and nothing else stops: key recovery never needs a Custodian.

**The honest warning.** While few Master Builders exist, corrections are checked above all by publicity and the right to fork, and only by as many members as can object. While the Custodian's member is the only Master Builder, no one can object to a correction or remove the Custodian; where no Master Builder who is not a founder exists, no one can stop a founder's claim of the office. The rules are [Constitution Art. XVI](CONSTITUTION.md#article-xvi-corrections-interim-guardianship) and the [Custodian's charter](docs/governance/CUSTODIAN.md); the exact rules are in the [specification](docs/whitepaper/SPEC.md).

## Take part through your agent

Clone the repository and open it with your AI agent (any desktop or editor agent). Then just ask (*"I want to join"*, *"what should I do now?"*) or type `/om`. Your agent becomes **the Guide**: it shows where you stand, offers the next steps as choices, explains every rule, answers your questions and asks for your approval before anything is signed or published. When their field comes up, it calls the other officers: Counselor, Secretary, Wardens, Almoner and Tyler ([AGENTS.md](AGENTS.md)). No meetings are required.

```bash
git clone https://github.com/openmasonry/openmasonry.git && cd openmasonry && bin/om doctor
```

## Quick start

Requirements: Python ≥ 3.11, and OpenSSH ≥ 8.1 to sign, 8.2 for a hardware key (verifying needs only Python). No other dependencies.

```bash
git clone https://github.com/openmasonry/openmasonry.git && cd openmasonry
```

Verify the ledger from genesis (prints `ledger is empty (no genesis yet)` before the Founding Ceremony):

```bash
PYTHONPATH=src python3 -m openmasonry verify --tree
```

Run the protocol tests (stdlib `unittest`):

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .
```

Member commands (`bin/om`; on native Windows `bin\om.cmd`): `onboard` (for a person who is not a member yet: checks the computer, the GitHub login and the key, creates and uploads the key after approval), `apply` (publishes your application after approval), `doctor`, `me`, `learn`, `rules`, `corrections`, `witnesses`; drafting commands `genesis`, `invite`, `join`, `vouch`, `open` (`--rerun ID` re-runs a lapsed ballot; `--commit-days`/`--reveal-days` for an amendment), `vote`, `reveal`, `close`, `exam`, `report`, `recuse`, `draw`, `call-council`, `work`, `depart`, `rekey`, `recover`, `recover-cosign`, `recover-oppose`, `recover-object`, `recover-apply` (a lost key), `object` (to a correction), `claim-custodian`, `object-claim`, `apply-claim` (a founder's claim of the Custodian office), `claim-succession`, `alarm`; and `approve`, `drafts`, `discard`, `pending` (`--drop SEQ`; `--rebase [SEQ]` re-drafts a `stale` entry that lost its seq to another; `--publish SEQ` publishes one whose push or pull request failed), `submit`. Custodian commands: `correct`, `cosign-correction`, `apply-correction`, `withdraw-correction`, `alive`, `revoke-custodian`. Tool commands: `verify`, `state`, `append`, `commit`, `declaration`, `digest`, `proof`, `arms`, `docs`; and the public reads `rooms` (the roll every room derives), `metrics` (the Observatory's aggregates), `timeline` (every entry as one line) and `observatory --out DIR` (writes the Observatory page and its data). Run `bin/om --help`.

Agents only **draft**: each act is checked against the protocol and stored as a sealed draft (`--json` prints it as `om.draft/1`). The person then runs `bin/om approve <digest>` and confirms in a system dialog built from the entry itself; for a vote, they choose Yes or No there, so the agent never learns it. Approval signs exactly that draft and opens the pull request from the canonical repository's `main`, through the member's fork when they lack write access.

### How to join

All you need is a GitHub account and an AI agent: the agent does every technical step (tools, key, application, petition) with the Guide at the door ([`om-onboard`](skills/om-onboard/SKILL.md)), and asks you before anything is published. Paste this to your agent:

> Clone https://github.com/openmasonry/openmasonry and follow docs/agents/START.md to help me join.

- **Get ready.** `bin/om onboard` checks your computer, your GitHub login and your member key, and says the one next step; `bin/om onboard --create-key` makes the key in your own terminal, and `bin/om onboard --upload` adds it to your GitHub account as an authentication key after you approve in a dialog.
- **Any adult may apply.** It costs nothing (Landmark I). Introduce yourself, in your own words, in a public issue: write it in a file and run `bin/om apply --text FILE` (you approve it in a dialog), or use the *Application* form. It asks for no personal data. Membership is a public roll under the name OpenMasonry, and you must be an adult: 18 years old, or the age of majority where you live, whichever is higher. An application is not a ledger entry and gives no right to an invitation; one that brings no invitation in 60 days is closed, and you may apply again.
- **A Master Builder invites you.** A **Master Builder (3°+)** who is ready to answer for your identity, your adulthood and your good faith signs an invitation that names your GitHub login (`bin/om invite <login>`). That member is your first sponsor, and the invitation lasts 30 days. Nobody who is not a member writes to the ledger without one.
- **You petition.** Ask your agent *"I want to join"* (it follows [docs/agents/START.md](docs/agents/START.md)), or run `bin/om join` and approve the draft. Your petition is a signed entry with your SSH key (a plain `ssh-ed25519` key, or a hardware-backed `sk-ssh-ed25519@openssh.com` key that signs only when touched) and the hash of the Declaration; later you can replace your key yourself (`bin/om rekey --new-key PATH`), and a lost key is recovered with a new one that Master Builders co-sign ([RECOVERY.md](docs/operations/RECOVERY.md)); without a live invitation `bin/om join` refuses and tells you how to apply.
- **Sponsors.** Admission needs two sponsors who are Master Builders: the one who invited you and a second (`bin/om vouch <login>`). During the Founding Phase (in force while fewer than 7 active Masters exist) it needs as many as there are active Masters, at most two, so the inviter alone suffices while only one exists; and once your petition has been live 30 days the inviter alone suffices, while every other Master still votes. That 30-day waiver also holds after the Founding Phase whenever fewer than 7 Masters are present (neither dormant nor silent), so Masters who never answer hold no door shut.
- **The admission ballot.** One of your sponsors opens it; members of 2°+ vote by commit–reveal (7 days to commit, a gap of 6¼ hours, 3 days to reveal; it closes early once every elector has revealed). Enough members must vote (a quorum): a ballot that misses it lapses with no penalty, your petition stays, and the ballot may be re-run once within 30 days (`bin/om open admission <login> --rerun ID`) (at least 7 days to commit; a re-run, and a ballot that gave less than 7 days to commit, are never re-run). Then the **blackball rule** decides: you are refused if black balls reach one fifth of the votes cast, so with five or fewer votes a single black ball refuses.
- **The judge enforces it.** Every step is a ledger entry in a pull request, and the `judge` check replays the whole ledger with the base branch's verifier: a petition without an invitation, an entry without enough sponsors, from the wrong person or outside its ballot window is refused, whoever merges it. Full walkthrough: [How to join](wiki/queries/how-to-join-openmasonry.md).

### How the judge works

Every pull request is judged by the `judge` job of [`judge.yml`](.github/workflows/judge.yml), which runs only on `pull_request_target`: it checks out the **base branch** into `base/`, fetches the PR's files into `pr/` as data (never executed), and refuses any change to `ledger/entries/` other than added files, files Python could run implicitly or find in place of the verifier, symlinks or submodules, and any workflow file that the manifest of the pull request's tree does not list (today `judge.yml`, `pages.yml` and `tyler.yml`: the set of workflows is closed, so no pull request can add a second job named `judge` without an amendment that ratifies it). A PR that adds ledger entries must change nothing else (apart from the witness's anchors, the public reason of a correction and, at genesis, the archived canon). It then runs the base branch's verifier, and nothing else of the repository, as `python -P -m openmasonry.verify --tree --online --clock-since --pr-author --since --pr-author-id`: that replays the whole ledger, checks the PR author's identity (and, for an invitation or a petition, the invited GitHub account; for a new key, that the member's own account lists it), every governed file and the `@protocol` digest (over the files listed in `src/openmasonry/protocol.manifest` of the PR's own tree) against the ratified pins, checks that the public reason of every correction the PR adds is in the tree under its SHA-256, re-fetches the drand beacons of the new entries, and requires new entries to be stamped no more than 6 hours behind and 2 minutes ahead of its clock. The PR author is held to the numeric GitHub id the ledger records for the actor (anyone may carry a `depart` or a `rekey_object`), and a genesis is accepted only from the account named by `founder_github_id` in `src/openmasonry/network.toml`. When it passes on a ledger-only PR, the `admit` job turns on auto-merge; code and docs PRs always need a code-owner review.

[`tyler.yml`](.github/workflows/tyler.yml) runs the PR's own `tests` and checks that generated files are current; its `candidate` job replays `main`'s ledger with the PR's own core and requires the same head and state digest; its `audit` job re-judges `main` on every push and daily, raising a capture alarm on divergence; and its `applications` job closes application issues that brought no invitation in 60 days. The GitHub settings that make all this binding are in the [launch checklist](docs/operations/LAUNCH.md).

## Repository layout

| Path | What |
|---|---|
| [`docs/whitepaper/`](docs/whitepaper/) | the Whitepaper (intent), the [specification](docs/whitepaper/SPEC.md) (the exact rules, constants and messages) and the Patron Seals paper |
| [`CONSTITUTION.md`](CONSTITUTION.md) | the Constitution (governed file) |
| [`docs/governance/`](docs/governance/CUSTODIAN.md) | the [Custodian's charter](docs/governance/CUSTODIAN.md) (what the office does on GitHub and in the ledger, and what it never does) and the [rules of the rooms](docs/governance/ROOMS.md), both governed files; the public description of the Custodian's private [Console](docs/governance/CONSOLE.md) (built, not operating yet), a working tool that decides nothing and whose binding outputs are all public; and the [moderation log](docs/governance/MODERATION-LOG.md), which is the ledger itself |
| [`docs/operations/`](docs/operations/LAUNCH.md) | the [launch checklist](docs/operations/LAUNCH.md) (GitHub settings and the Founding Ceremony) and the [recovery runbooks](docs/operations/RECOVERY.md) (a lost or stolen key, a lost host, a flaw in the protocol, upgrading the core, the last resort) |
| [`docs/study/`](docs/study/README.md) | the public study guide of every degree |
| [`canon/`](canon/) | the degree table, the eternal Landmarks and the archive of ratified canons (`canon/history/`), pinned at genesis |
| [`src/openmasonry/`](src/openmasonry/) | the pinned core (`@protocol`): ledger, ballot, lot, pins and the verifier's entry point (`verify.py`); and, outside the pin, the CLI, the Guide (`guide.py`), member commands (`actions.py`) and heraldry |
| [`skills/`](skills/) | the officers (Guide, Counselor, Secretary, Wardens, Almoner, Tyler) as Agent Skills |
| [`bin/om`](bin/om) | the `om` command (wraps the Python CLI until the Go binary ships) |
| [`ledger/`](ledger/) | the Tracing Board: `entries/` (one signed file per event, `NNNN/NNNNNN.json`, in shards of 1,000; empty until the Founding Ceremony), `anchors/` (timestamp proofs of checkpoints) and `reasons/` (the public reason of every correction, named after its SHA-256) |
| [`tests/`](tests/) | the protocol test suite and the conformance vectors (`tests/vectors/`: small ledgers with the state digest or the refusal a verifier must reach) |
| [`heraldry/`](heraldry/) | generated coats of arms of the 33 degrees |
| [`node/`](node/) | the witness node (Docker) for VPS operators: closes ballots, draws lots, checkpoints and anchors |
| [`engines/openmasonry/`](engines/openmasonry/README.md) | the MCP engine: local stdio (reads and drafts) and a public read-only HTTP endpoint |
| [`wiki/`](wiki/index.md) | the knowledge base: history, symbols, degrees, comparisons |

## Known limitations

OpenMasonry is **tamper-evident**, not "unhackable": rewriting history is detectable by anyone, and forging it requires breaking SHA-256 or stealing members' keys.

- **The correction power is a deliberate exception** to "no one holds special power", and its bounds are the whole defense. Until the Sunset a founder named Custodian (by the genesis, which at the founding ceremony names the first founder, or by a founder's claim) also holds that office. It ends at the Sunset condition, at the end of its seven-year term, after 180 days of silence, by its revoke key, or by a simple majority of the Master Builders. While few Master Builders exist, corrections are checked above all by publicity and the right to fork, and only by as many members as can object; while the Custodian's member is the only Master Builder, no one can object or remove.
- **Without a live Custodian, no correction exists.** No lot and no ballot appoints a Custodian. The one way back is the founder's fallback: while few Masters exist, a founder may claim the office after 30 days of notice, unless a Master Builder who is not a founder objects (no founder then claims it again for 30 days), and never a founder against whose custodian key a removal ballot passed. After the Sunset, or once three active Master Builders who are not founders exist, no new Custodian can be named unless an amendment adds a way (a college of Custodians is the intended path, not built). Everything else goes on without one, key recovery included.
- **Keys.** A member replaces a key they still hold with `rekey` (the old key signs, the new key proves). A lost or stolen key is recovered through peers, with or without a Custodian: after a Custodian's freeze, two Master Builders co-sign and 21 days of notice run; without a freeze, three co-sign, not all of them sponsors while a Master Builder who is not a sponsor exists, 30 days run and the Master Builders may oppose it; where fewer Masters exist all of them suffice and the notice is 45 days (counted among those who revealed a vote or reported within the last year, or reached the 3rd degree within it: a Master who answers nothing may oppose, and is not waited for); and a request that, after 30 days, still lacks co-signers needs only those who signed (at least one), with 45 days of notice, which after a freeze start on that thirtieth day, the old key staying frozen meanwhile. Whoever holds the old key can stop a recovery once, while it is open; the recovery that follows a stopped one, asked no sooner than 90 days after the stop, is decided by the peers alone. A recovery reverses a departure when it is asked before the departure or within 30 days of it, or when it follows, within 150 days of that recovery's request or of the old key's stop of it, a recovery in time for that departure, whatever ended that recovery, so one follow-up may follow another; it does so when it completes, and a Council seat the departure ended comes back only into a vacancy ([RECOVERY.md](docs/operations/RECOVERY.md)). The ledger checks signatures, not hardware: no attestation of a hardware-backed key is recorded. One GitHub account is one member.
- **Time.** Notice periods are counted from entry times. An entry can be stamped up to 6 hours before it is merged (and at most 2 minutes ahead of the judge's clock), and a ledger whose last entry is dated more than 10 minutes ahead of the clock raises an alarm in every client; until independent witnesses exist, the judge alone holds entry times to the clock.
- **Votes are public after reveal** until encrypted ballots land (v0.3).
- **Witnesses.** The founding ceremony is expected to name one witness or none, and the verifier records checkpoints without counting them toward finality, so checkpoints are not yet Byzantine-tolerant.
- **Procedural rules.** Some rules of the Constitution bind members but are not enforced by the verifier (Whitepaper §8.5).
- **One host, one administrator.** Until the Sunset the Custodian is the sole GitHub administrator, bound by the public [Custodian's charter](docs/governance/CUSTODIAN.md); mirrors and the [recovery runbooks](docs/operations/RECOVERY.md) are the mitigation. Until the repository is public with a protected `main` branch, outsiders cannot fork or take part and the witness cannot auto-merge (Whitepaper §8.3, §9.2).

See the [threat model](docs/whitepaper/WHITEPAPER.md#8-integrity-threat-model-and-survivability).

## Independence

OpenMasonry is not affiliated with, recognized by or speaking for any grand lodge, Supreme Council or Masonic body. Historical degree names are cited as reference; no ritual of any Masonic body is reproduced.

## License

Code under [MIT](LICENSE); the conformance vectors in `tests/vectors/` under CC0 1.0. Every text that is not software (the Whitepaper, the Constitution, the canon, the governance, operations and study texts, the skills, the wiki and the rest) under [CC BY-SA 4.0](LICENSE-TEXT.md); the coats of arms in `heraldry/` under CC0 1.0.
