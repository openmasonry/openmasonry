---
title: "Tyler"
type: concept
tags: [protocol, ci, automation, tradition, witnesses]
sources:
  - raw/sources/sym-landmarks-anderson-mackey-pound.md
  - raw/sources/sym-haywood-symbolical-masonry-1923.md
  - .github/workflows/judge.yml
  - .github/workflows/tyler.yml
  - node/witness.py
  - src/openmasonry/ledger.py
  - docs/whitepaper/WHITEPAPER.md
---

# Tyler

The Tyler guards the door. In the tradition it is an officer with a sword; in OpenMasonry it is the automation that judges every proposed change to the ledger, and that anyone can read.

**In the tradition.** The Tyler is the officer who guards the door of the lodge from the outside, sword in hand, so that no unqualified person enters while the lodge is at work. A lodge in session must be "tyled", and that is Mackey's 11th landmark. The etymology is debated; the most common reading links the word to the tiler, the craftsman who "covers" a building. Some moral interpretations see in the Tyler the watch kept over one's own inner door.

## In OpenMasonry
The Tyler is **automation that anyone can read**, not a person with discretionary power (whitepaper §9.1). (The officer-agent `om-tyler` plays the same role when a member checks the ledger from their own clone.)

**1. GitHub CI**, in two workflows (`judge.yml` and `tyler.yml`), with a third that publishes the Observatory (`pages.yml`). All three belong to the pinned core (`@protocol`, the files listed in `src/openmasonry/protocol.manifest`), and the set is closed: a tree that holds anything under `.github/workflows/` that its manifest does not list is unlawful, because another workflow could define a job named `judge` and answer to the required check. Every change to any of them, and any new workflow, needs a ratified amendment of `@protocol`.

`.github/workflows/judge.yml` runs on every PR via `pull_request_target` (opened, synchronize, reopened, ready for review):
- **`judge`** (the gate; the required check on `main`). It runs the **base branch** code (checked out into `base/`) and reads the PR's files only as data (a `pr/` worktree that is never executed). So a PR can never change the code that judges it. It checks:
  - **append-only:** it fails if any past entry is modified, renamed or deleted, and only entry files `NNNN/NNNNNN.json`, each in the shard of its seq, may be added to `ledger/entries/`;
  - **ledger-only:** a PR that adds entries may change nothing else (the witness's `ledger/anchors/` proofs, an added `ledger/reasons/<sha256>.md` holding the public reason of a correction, and the archived canon in the genesis PR, are the only exceptions);
  - **no implicit code, no links:** no `.pyc`, `.pth`, `__pycache__/`, `sitecustomize.py` or root `.py` file; no symlink or submodule, whether added or made by a type change;
  - **no new workflow:** the PR's tree may hold nothing under `.github/workflows/` besides the files its own manifest lists (today `judge.yml`, `tyler.yml` and `pages.yml`); whether a tree with that manifest is ratified is decided by the `@protocol` digest;
  - `verify --tree` replays the ledger (with the strict loader: regular `NNNN/NNNNNN.json` files of at most 8 KiB, 32 KiB for the genesis), checks every pinned file against its ratified hash (see [[eternal-landmarks-of-openmasonry]]), reports any workflow outside the pinned core (`govern.stray_workflows`), and requires the public reason of every correction to be in `ledger/reasons/` under its own SHA-256, with nothing else in that directory (`govern.missing_reasons`, `govern.stray_reasons`);
  - **identity:** `verify --pr-author --since --pr-author-id` holds every new entry a member signs to the GitHub account the ledger records for that member, by its **numeric id**, never by the login, which can be renamed or taken over. Witness and Custodian entries are excepted (their keys belong to no GitHub account), and so are a `depart` and a `rekey_object`, which anyone may carry, so that a member whose account is in other hands can still leave or stop a recovery of their key. A petition's key, or the new key of a `rekey` or of a recovery, must be listed at `github.com/<login>.keys`. For an `invite`, the invited login must today be the GitHub account with the stated numeric id; for a `petition`, the PR's author must be that same account. A genesis is accepted only from the founder's account, the `founder_github_id` of `src/openmasonry/network.toml` (`identity.pr_problems`). A network failure fails closed;
  - **honest timestamps:** `verify --clock-since` refuses new entries dated outside [now − 6 hours, now + 2 minutes] (`CLOCK_TOLERANCE`, `JUDGE_FUTURE_TOLERANCE`); a reader raises the alarm only for a head more than 10 minutes ahead of its own clock (`FUTURE_TOLERANCE`);
  - **authentic beacons:** `verify --online` compares every drand beacon used in a lot with the public chain (see [[verifiable-lottery]]);
  - it writes the "state of the fraternity" to the job summary.
  - **The judge is a convenience; `verify` is the law.** A merge made without the judge is lawful when the resulting `main` passes the pinned `verify --tree`, and each such merge is recorded as a `note` while a custodian key is live, and otherwise in a public issue (`docs/operations/RECOVERY.md`).
- **`admit`**: once `judge` passes on a ledger-only PR, it turns on auto-merge. Code, docs and governed files never auto-merge; they need a code-owner review.

`.github/workflows/tyler.yml` runs on PRs (`pull_request`), every push to `main`, daily (`0 0 * * *`, 00:00 UTC) and on demand:
- **`audit`** judges `main` itself, offline (`verify --tree`) and then online (`--online`), which also refuses a `main` whose last entry is dated more than ten minutes ahead of the clock (`FUTURE HEAD`). An offline failure opens a capture alarm at once; an online-only failure (a drand or network outage) only after three failed audits in a row.
- **`tests`** (feedback for developers, not the gate): it runs the PR's own test suite and requires coats of arms and the catalog to be regenerated from the canon.
- **`candidate`**: on a PR, it replays `main`'s ledger with the PR's own protocol core (`verify --candidate-root`) and requires the same entries, head and state digest, so a rule that changes applies from a fixed future time or entry number written in the voted text (never from the protocol epoch alone) and never changes the replay of entries already merged. It runs the PR's code, so it lives here and never in the judge; a code owner approves a change of the core only with this check green.
- **`applications`**: daily, it closes public applications older than 60 days that no invitation followed, with a courteous notice of how to apply again; it never touches the issue of a member, an invited login or a petitioner.

**2. Witness node** (`node/witness.py`), the "Tyler that never sleeps". On each cycle (3,600 s by default):
- it runs `pull --ff-only` and replays the ledger with the verifier built into the image (not the freshly pulled code); if replay fails, it raises a **capture alarm** and opens an issue (`witness.alarm`);
- it holds the canonical ledger against the head it last verified: a ledger that no longer contains that head (a rollback), that starts from another genesis, or whose last entry is dated ahead of the clock is a capture alarm, and the node signs nothing (`witness.verified_head`, `ledger.head_verdict`);
- it refuses to sign if the governed files differ from what was ratified (`govern.check_tree`);
- it carries out what `ledger.due_actions` says is due: `ballot_close` for expired ballots and the pending lots (`exam_draw`, `council_draw`) with the drand beacon of the round;
- it signs a `witness` checkpoint that states the digest of the whole state it covers and the version of the state document, with the RFC 6962 root and the OpenTimestamps anchor, at most once an hour and only when some other entry was added since its last one (`ledger.checkpoint_due`);
- it publishes via a PR with auto-merge, which CI verifies again. While that PR is open, or if it cannot sync, it only verifies.

**In the protocol.** A registered witness may sign `witness`, `ballot_close`, `exam_draw` and `council_draw` instead of a member (`ledger.WITNESS_TYPES`, `ledger._signer`). A witness key can be frozen for 30 days by a correction; while it is frozen it signs nothing, and members may still close ballots and draw lots (see [[custodian-and-corrections]]). It closes ballots and carries out lots already requested, but it cannot vote, admit, promote or call lots: `exam_open` belongs to the candidate, `council_call` to an active member, and `exam_recuse` to a drawn examiner. Members, for their part, sign only what they themselves approve: the member CLI drafts each act and the person confirms it in a system dialog (`om approve`).

"No human needs to be awake for the fraternity to keep its records, close its ballots and prove its history."

**What the Tyler is not.** It is not the Custodian. The Tyler is code that judges; the Custodian is a person who holds an interim office, administers the repository under a public charter and may sign corrections, each of which the Tyler judges like any other entry. No past entry is ever edited or deleted, by the Tyler or by anyone else: Landmark VI allows a repair only as a new public record.

See [[byzantine-fault-tolerance]], [[commit-reveal]], [[chained-ledger]], [[opentimestamps]], [[custodian-and-corrections]].
