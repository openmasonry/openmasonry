# Witness node

A witness is an independent machine that keeps the fraternity running without anyone being awake. Every cycle (by default every hour) it:

1. pulls the canonical repository;
2. replays the entire ledger from genesis (if it fails, it opens a **capture alarm** issue and stops). It also stops with a capture alarm when the last entry is dated more than ten minutes ahead of its clock (`FUTURE HEAD`), and when the canonical `main` no longer holds the entry it verified in an earlier cycle (`ROLLBACK`): it remembers the head it verified in `witness-heads.json`, beside its clone in the `data` volume, never inside the repository. A `main` that is only shorter than what it verified (`BEHIND`, a mirror that lags) makes it wait without an alarm;
3. refuses to sign if governed files differ from their ratified versions (capture alarm), or if the code in its own image is not the pinned core the ledger ratified (it compares its own `@protocol` digest with the ledger's pin; it keeps verifying and raising alarms, and signs again once rebuilt);
4. does what the protocol says is due (`ledger.due_actions`): closes ended ballots and performs pending lots with the public drand beacon;
5. when an entry other than a checkpoint was added since its own last checkpoint, and that checkpoint is at least an hour old (`ledger.checkpoint_due`; the ledger refuses any other), signs a `witness` checkpoint that covers every entry so far: the hash of the last one, the digest of the state they leave and the version of the state document it was computed on (`state_version` 2), so that any verifier whose state differs refuses the checkpoint, and the Merkle root of all entries, which it anchors on Bitcoin through OpenTimestamps;
6. pushes a branch and opens an auto-merging PR, which the Tyler (CI) judges again (it creates the `witness` and `capture-alarm` labels on first use, and logs when auto-merge is unavailable). While one of its PRs is open (any open PR from a branch of this repository named `witness/<name>/…`), or if it cannot sync with GitHub, it only verifies, so it never forks the chain. One case is handled without a human: if that PR can no longer merge because another entry took its place in the sequence (GitHub reports a conflict, or its branch no longer only adds entries on top of `main`), the witness closes it, deletes the branch and does the work again on the new head.

A drand outage is not an alarm: a lot that cannot fetch its beacon is skipped and retried next cycle. The witness raises a capture alarm when the ledger fails to replay, when governed files differ from the ratified versions, when the last entry is dated ahead of its clock, and when `main` was rewound or starts from another genesis than the one it verified. Its checkpoint PRs also keep the repository active, so GitHub does not disable the Tyler's daily schedule after 60 days of inactivity.

The verifier is **baked into the image** at build time: code merged later never runs with the witness key. After a ratified `@protocol` amendment, operators rebuild (`docker compose build`) from the tree that holds the ratified code; until then the witness logs `refusing to sign` every cycle. For a canon amendment, rebuild as soon as the new table is archived in `canon/history/` and before its ballot opens: an image without the archived table fails to replay the `ballot_open` and raises a false capture alarm. `witness.py` itself is not part of the pinned core: it imports only pinned modules, and a change to it needs a code-owner review and a rebuild, not an amendment. A fraternity may also be founded with no witness and add one later by witness ballot.

The witness is a single Docker container: any small VPS (1 vCPU, 512 MB RAM) can run one. Byzantine tolerance needs at least four independent witnesses (Whitepaper §8.2); anyone may run an uncertified one to audit.

## Deploy (any Linux VPS with Docker)

```bash
git clone https://github.com/openmasonry/openmasonry.git && cd openmasonry/node   # compose builds from the repository root
```

```bash
mkdir -p keys data && ssh-keygen -t ed25519 -N "" -C witness-1 -f keys/witness
```

The ledger also accepts a hardware-backed witness key (`sk-ssh-ed25519@openssh.com`), but every signature of such a key needs a touch of its token, so a node that signs unattended uses a plain key on a dedicated machine. The image holds exactly the files of the pinned core, copied from `src/openmasonry/protocol.manifest` at build time; rebuild it after every ratified change of the core.

```bash
sudo chown -R 1000:1000 keys data && chmod 600 keys/witness
```

```bash
cp .env.example .env
```

Edit `.env`: set `OM_WITNESS_NAME=witness-1` and a **fine-grained GitHub token** limited to this one repository (Contents: read/write, Pull requests: read/write, Issues: read/write). Then:

```bash
docker compose up -d --build
```

```bash
docker logs -f openmasonry-witness
```

The private key stays on the node. Whether the witness enters at the genesis or later, the operator first signs, on the node, a proof that it holds the key:

```bash
bin/om proof witness witness-1 --key keys/witness --out witness-1.proof
```

and sends `keys/witness.pub` and `witness-1.proof` (both public) to the founder or to a Master Builder:

- **At the Founding Ceremony**, the founder adds `--witness witness-1:witness.pub --witness-proof witness-1:witness-1.proof` to the genesis command of the [launch checklist](../docs/operations/LAUNCH.md#the-founding-ceremony-three-keys), which also names the Custodian. There is no genesis command to copy from here: a genesis drafted with only a witness founds a ledger with no Custodian.
- **Later**, a Master Builder drafts `bin/om open witness witness-1 --measure add --witness-key "<bare key>" --witness-proof witness-1.proof` and approves it; the witness ballot decides.

## Security notes

- The container runs as an unprivileged user, read-only root filesystem, all capabilities dropped, 256 MB / 0.5 CPU.
- The private key never leaves `keys/` and is mounted read-only. Back it up offline: losing it means the witness must be re-certified.
- The GitHub token can only touch this repository, and it can never forge a signed entry: every replay checks every signature. Its blast radius depends on how `main` is protected. With a ruleset that requires the `judge` check, a stolen token can only open PRs (which the Tyler verifies), close them, delete branches, and open or label issues. **Without protection, it can push to `main` directly**: a bad entry would still be refused by any replay and caught by the daily re-verification and other witnesses, but it could disrupt the repository until someone reverts it.
- Use a dedicated machine user or a GitHub App rather than a personal token, set an expiry, and write down how to rotate it (see [docs/operations/LAUNCH.md](../docs/operations/LAUNCH.md)). Revoke it at once if the host is compromised.
- Known limitations today: until the canonical repository is public with a protected `main` branch, outsiders cannot fork or take part and auto-merge is unavailable: a maintainer must merge the witness's PRs. The Custodian is the sole administrator of the repository until the Sunset (Whitepaper §8.3, §9.2).
- `OM_WITNESS_PUSH=none` never pushes and never opens a pull request, but a named witness with its key still signs its due entries and checkpoints into its own local clone, which then no longer matches `main`. To audit without a witness key, run `bin/om verify --tree --online` on a clone of your own on a schedule instead; anyone may.
- The verified head: `OM_WITNESS_HEADS` names the file (default `witness-heads.json` beside the clone; keep it on the persistent volume, and back it up with the key). Deleting it makes the node trust the next `main` it verifies. To follow another history on purpose (a fork the fraternity chose, or another fraternity), set `OM_WITNESS_ACCEPT_GENESIS` to the entry hash of its genesis for one cycle, then remove it: the alarm text gives the hash.

## Environment

| Variable | Meaning | Default |
|---|---|---|
| `OM_WITNESS_REMOTE` | the canonical repository the container clones on first start (`entrypoint.sh`) | required |
| `OM_WITNESS_NAME` | the witness name, as the ledger holds it | required |
| `OM_WITNESS_KEY` | the private witness key | `/keys/witness` |
| `OM_WITNESS_REPO` | the clone | `/data/openmasonry` |
| `OM_WITNESS_INTERVAL` | seconds between cycles (0 = run once) | `3600` |
| `OM_WITNESS_PUSH` | `pr` (a branch and an auto-merging PR), `direct` (push to `main`, only where `main` is not protected) or `none` (publishes nothing, but still signs into its own clone: see above) | `pr` |
| `OM_WITNESS_HEADS` | where the verified head is remembered | `witness-heads.json` beside the clone |
| `OM_WITNESS_ACCEPT_GENESIS` | the entry hash of a genesis to follow from now on, for one cycle | unset |
| `GH_TOKEN` | the fine-grained token of the repository | required to publish |

## Running once, locally

Run it on a throwaway clone, never on a clone you work in: it signs into the clone it is given.

```bash
OM_WITNESS_REPO=/tmp/om-witness-clone OM_WITNESS_NAME=witness-1 OM_WITNESS_KEY=keys/witness OM_WITNESS_INTERVAL=0 OM_WITNESS_PUSH=none python3 witness.py
```
