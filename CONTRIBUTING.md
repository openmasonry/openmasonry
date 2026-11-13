# Contributing

Everyone may contribute; contributions by members also count as *masterworks* for their degrees.

## Kinds of contribution

| You want to… | Do this |
|---|---|
| fix code or docs | open a PR; the Tyler runs tests and verifies the ledger, and a code owner reviews it (code and docs PRs never auto-merge) |
| apply for membership | open an *Application* issue and introduce yourself in your own words (no personal data; an application is not a ledger entry). Once a Master Builder has invited you, ask your agent (it acts as the Guide, [skills/om/SKILL.md](skills/om/SKILL.md)), or run `bin/om join` and approve the draft with `bin/om approve <digest>` |
| record a masterwork | publish it, then `bin/om work <url>` and approve the draft |
| propose a rule change | open an *Amendment* issue; after discussion, a Master Builder opens an amendment ballot (`bin/om open amendment PATH --sha256 HASH`) |
| report a vulnerability | see [SECURITY.md](SECURITY.md) |
| recover from a lost key, a lost host or a flaw in the protocol | follow the runbooks in [RECOVERY.md](docs/operations/RECOVERY.md) |
| object to a correction (Master Builders) | read it with `bin/om corrections`, then `bin/om object` and approve the draft (Constitution Art. XVI.9) |
| add knowledge to the wiki | drop a source in `raw/sources/` and follow [wiki/README.md](wiki/README.md) |

## Ledger entries

- Never edit, move or delete an existing file in `ledger/entries/` (each entry is `NNNN/NNNNNN.json`: its seq, in the shard `seq // 1000` of 1,000 entries). The Tyler rejects it, and no one is exempt: a wrong entry is repaired only by a new entry (Landmark VI; corrections, Constitution Art. XVI).
- Create entries with the member commands (`bin/om join`, `bin/om vote`, `bin/om work`, …; see `bin/om --help`). Each one only drafts the act and checks it against the protocol; you approve it with `bin/om approve <digest>` in a system dialog, which signs exactly that draft with your SSH key and opens the PR (from the canonical repository's `main`, through your fork if you lack write access). `openmasonry append` is a low-level tool for witnesses and tests.
- Entry times are UTC (`YYYY-MM-DDTHH:MM:SSZ`, set automatically) and must be at most 6 hours behind and 2 minutes ahead of the judge's clock when the PR is judged; `approve` refuses a draft that is too old, so draft again.
- While your PR is open, your entry stays visible in your clone and new drafts wait for it (`bin/om pending`); `bin/om pending --drop <seq>` forgets one whose PR was closed. If another entry took its seq first, it is listed as `stale` and no longer blocks new drafts: `bin/om pending --rebase <seq>` re-drafts the same act on top of the ledger (a vote keeps its sealed choice), and you approve it again.
- **Every entry in your PR must be yours.** The judge runs `verify --pr-author <your login> --since <base length> --pr-author-id <your numeric id>`: each new entry of a member must come from the GitHub account the ledger records for that member, compared by numeric id, never by login (the exceptions, which anyone may carry in a pull request, are the entries a registered witness signs with its witness key, the entries a custodian signs with a custodian key or a revoke key, and a member's `depart` and `rekey_object`; the genesis comes only from the account named by `founder_github_id` in `src/openmasonry/network.toml`), and a petition's key, or the new key of a rekey or of a key recovery, must be listed at `github.com/<login>.keys` when the PR is judged. A rekey and a key recovery must also come from the GitHub account the ledger records for the member. The judge also binds admission to a GitHub account: the login of an `invite` must be the account with the numeric id the entry states, and a petition's PR must come from the account its invitation names (`--pr-author-id`). A network failure refuses the PR; re-run the check. One key per login: a key already used by a member, a witness or a live petition is refused. One GitHub account per member: an invitation is refused when its account already belongs to a member, an invitation or a petition under another login.
- **Nobody who is not a member writes to the ledger without an invitation.** A `petition` is valid only under a live `invite` for exactly that login, signed by a Master Builder (`bin/om invite <login>`) within the last 30 days.
- Your SSH key must be a bare `ssh-ed25519` key or a hardware-backed `sk-ssh-ed25519@openssh.com` key (`ssh-keygen -t ed25519-sk`, default application; each signature then needs a touch); logins are compared case-insensitively. To replace your key, run `bin/om rekey --new-key PATH` (your current key signs the entry, the new key signs a proof; once in 30 days), after adding the new key to your GitHub account. If the key is lost or in other hands, follow [RECOVERY.md](docs/operations/RECOVERY.md): you ask with a new key (`bin/om recover`), Master Builders co-sign (two after a Custodian froze the old key, three without a freeze, never more than the other active Masters), and a notice runs (21 days after a freeze, 30 without one, 45 whenever fewer co-signers suffice).
- One PR per entry (or per coherent batch, such as the reveals of one ballot) keeps ordering simple.
- **Ledger PRs are ledger-only.** A PR that adds entries must change nothing else (the judge refuses mixed PRs; the only exceptions are the witness's `ledger/anchors/` proofs, an added `ledger/reasons/<sha256>.md` (the public reason of a correction, which must travel with the correction that pins it and holds no personal data) and, in the genesis PR, the archived canon in `canon/history/`). Once the `judge` check passes, the `admit` job turns on auto-merge, and no code-owner review is needed.

## Governed files

Genesis pins six governed paths (Whitepaper §6.4, Constitution Art. VII.1). Each changes only through a passed `amendment` ballot whose subject is `{"path": …, "new_sha256": …}`, and the PR that applies it must contain exactly the pinned bytes. Only a Master Builder opens an amendment ballot; its opener may set the windows (2 to 30 days to commit, 1 to 14 to reveal; every other ballot has 7 and 3), and the Master Builders decide it by two thirds of the votes cast:

| Path | How to compute `new_sha256` | Also required |
|---|---|---|
| `CONSTITUTION.md`, `docs/governance/CUSTODIAN.md`, `docs/governance/ROOMS.md` | `sha256sum <file>` (Linux) or `shasum -a 256 <file>` (macOS) | nothing else |
| `canon/degrees.toml` | `sha256sum canon/degrees.toml` (Linux) or `shasum -a 256 canon/degrees.toml` (macOS) | archive `canon/history/<new sha256>.toml` (a byte-for-byte copy) in a PR that merges **before** the ballot is opened (the opening is refused without it), so replay never depends on today's file; then apply the text and regenerate `openmasonry arms` and `openmasonry docs` |
| `@protocol` (the pinned core, below) | `bin/om digest` on the final tree (`bin/om digest --root DIR` for another tree) | witness operators rebuild their image after the PR merges; until they do, their witness signs nothing |
| `canon/eternal.toml` | never: the Landmarks and the Declaration can never change (a change means a fork); an amendment that targets it is refused, and a tree whose bytes differ from its genesis pin is reported unratified | not applicable |

Until the applying PR merges, the tree may keep the previously ratified text (for at most 30 days); any other content fails `verify --tree`. Because the Tyler judges PRs with the base branch's code, a change to the verifier or the judge only takes effect after it is ratified and merged. Amendment paths must be plain repository paths (letters, digits, `_ . -` and `/`) or `@protocol`, never under `ledger/` or `canon/eternal.toml`.

- **One slot per text.** At most one amendment ballot is open on a path with one proposed digest; two texts for the same path may be open together, and the first to pass wins.
- **The base pin.** An amendment records the pin it replaces when it opens; if another amendment changed that pin first, it fails at its close.
- **Two readings.** An amendment that alters the decision function, the electorates, the sponsorship rules or Constitution Art. VII needs two passed ballots at least 90 days apart (Art. VII.3). The first ballot goes on `first-reading/<governed path>` (for `@protocol`, `first-reading/protocol.patch`, the patch that makes the change), never on the governed path itself, because the verifier pins whatever path a passed amendment names and does not tell a first reading from any other amendment. The second pins the governed path to exactly the text the first reading ratified. The first-reading pin stays governed until an amendment removes it (64 zeros, below).
- **Removing a pin.** An amendment whose `new_sha256` is 64 zeros removes the pin of a path a passed amendment made governed; the six genesis pins are never removed.
- Each opener holds at most three open amendment ballots, counted apart from their other ballots. Every entry of an amendment ballot passes a halt and the daily cap, and its windows run on wall time.

### What needs an amendment, and what needs a review

`@protocol` is the digest of a short, explicit list of files, the manifest `src/openmasonry/protocol.manifest`: the code that decides what is valid, the manifest itself, and the three workflows of the repository. The manifest is data: one repository-relative path per line, in sorted order, with no blank line and no comment, and it is read from the tree being judged.

| You change… | It needs |
|---|---|
| a file of the pinned core: `src/openmasonry/__init__.py`, `ledger.py`, `crypto.py`, `canon.py`, `lot.py`, `govern.py`, `identity.py`, `beacon.py`, `verify.py`, `rooms.py`, `src/openmasonry/network.toml`, `src/openmasonry/protocol.manifest`, `.github/workflows/judge.yml`, `.github/workflows/pages.yml` or `.github/workflows/tyler.yml` | a passed amendment of `@protocol`, then the PR with exactly those bytes (and a code-owner review, given only with the `candidate` check green: the new core must replay the ledger already merged to the same head and state digest, so a rule change applies from a fixed future time or `seq` stated in the voted text, never from the epoch alone) |
| another governed file (the table above) | a passed amendment of that path, then the PR |
| anything else: the command line (`__main__.py`, `actions.py`, `guide.py`, `heraldry.py`), `bin/`, `scripts/`, `node/`, the other files of `.github/` (issue forms, CODEOWNERS), `engines/`, `skills/`, tests, docs, wiki | an ordinary PR with a code-owner review (`.github/CODEOWNERS`); no amendment |
| a new workflow (any file under `.github/workflows/` besides the three above) | not possible by review: the set of workflows is closed, and the judge refuses a tree that holds one its manifest does not list. It needs an amendment of `@protocol` for a tree whose manifest lists the file (next row) |
| the manifest itself (a new file in the core, a new workflow, or a file taken out of the core) | an amendment of `@protocol`, **first**: see "Changing the manifest" below |

### Changing the manifest: amendment first

The judge runs the base branch's code on your pull request's tree, and that code reads the manifest of **your** tree. So the digest it computes for your tree is the same one your own code computes, and a change of the list goes through the judge like any other change of the core:

1. Prepare the final tree on a branch: the new or changed files, and `src/openmasonry/protocol.manifest` with the path added or removed. Keep the file strictly sorted (`LC_ALL=C sort -c src/openmasonry/protocol.manifest`), one path per line, LF line ends, no blank line, no comment; it must list itself and `src/openmasonry/govern.py`. A malformed manifest makes the tree unlawful whatever the pins say.
2. Compute the digest of that tree: `bin/om digest` (or `bin/om digest --root DIR`).
3. Open the amendment ballot on `@protocol` with that digest (`bin/om open amendment @protocol --sha256 <digest>`) and let it pass. Do not open the pull request before: until the ballot closes, the judge refuses it (`UNRATIFIED — @protocol: tree sha256 …`), and a byte changed after the vote needs a new vote.
4. Open the pull request with exactly that tree. The judge of the base branch accepts it, the new workflow included, because your manifest lists it and the ledger pins your digest. A code owner still reviews it.
5. Witness operators rebuild their image (it copies exactly the files the manifest lists).

Taking a file **off** the list is a change of the list too: it needs the same amendment, so no file leaves the core quietly to be changed afterward by review. Two things do not work this way and cannot pass the judge: a change of how the digest itself is computed, or of where the manifest lives ([SPEC.md](docs/whitepaper/SPEC.md), section 12, point 18). They are still ratified by amendment first; the one merge then needs the ruleset's bypass ([LAUNCH.md](docs/operations/LAUNCH.md)), under the written procedure of [RECOVERY.md](docs/operations/RECOVERY.md).

Four rules keep a change made by review alone from ever deciding a verdict; the tests in `tests/test_core.py` hold them:

- **The core imports only the core and the Python standard library.** If a pinned module needs something from `actions.py` or any other file, move it into the core (an amendment); never import it.
- **The judge runs only `python -P -m openmasonry.verify`.** `om verify` is the same code, called from the command line.
- **No workflow outside the core.** A file under `.github/workflows/` that the manifest does not list could define a job named `judge` and answer to the required check. `verify --tree` reports it (`a workflow outside the pinned core`), and the judge's own gate refuses the pull request.
- **Nothing may shadow the core.** Under `src/` only files directly in `src/openmasonry/` are allowed: no other package or loose module in `src/`, and no directory inside the package. The judge also refuses PRs that add `.pyc`, `.pth`, `__pycache__/`, `sitecustomize.py` or a root-level `.py` file, and any symlink or submodule (including a type change of an existing file).

The digest is one SHA-256 over the listed files in the order of the manifest; for each file it takes the length of the path, the path, the length of the content and the content (lengths as 8 bytes, big-endian). The manifest is one of the listed files, so the list itself is hashed. It reads the files and nothing else: no git, no directory listing. A listed file that is missing or is a symlink is an error, not a different digest.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .
PYTHONPATH=src python3 -m openmasonry arms && PYTHONPATH=src python3 -m openmasonry docs
```

Code and docs are written in English.

Tests that sign run in test mode: the approval dialog is bypassed only when `OM_CONFIRM` is set to the test value, a `.test-mode` marker exists in `OM_HOME`, `OM_HOME` lies under the system temporary directory, the signing key lives inside that `OM_HOME` (never under `~/.ssh`) and the ledger is a scratch one, not the repository's. The online identity check is tested by replacing `identity.fetch_github_keys` and `identity.fetch_github_user`; the tests never use the network.

Python standard library only. Discuss larger changes in an issue first, and send small pull requests with tests. Sign your commits with your SSH key:

```bash
git config gpg.format ssh && git config user.signingkey ~/.ssh/id_ed25519.pub && git config commit.gpgsign true
```
