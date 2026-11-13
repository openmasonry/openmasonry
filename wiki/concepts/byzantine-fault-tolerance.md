---
title: "Byzantine Fault Tolerance (witnesses)"
type: concept
tags: [protocol, bft, witnesses, checkpoints, distributed-systems]
sources:
  - raw/sources/proto-pbft-1999.md
  - src/openmasonry/ledger.py
  - node/witness.py
  - docs/whitepaper/WHITEPAPER.md
---

# Byzantine Fault Tolerance (witnesses)

A system tolerates Byzantine faults when it stays correct even if some participants lie, omit messages or act arbitrarily, not merely when they crash. The classic result, made practical by Castro and Liskov's PBFT (1999), is that **n ≥ 3f + 1** replicas tolerate **f** faulty ones, with quorums of **2f + 1**: any two quorums intersect in at least one honest replica.

## In OpenMasonry
**Witnesses** are independent nodes. On each cycle, a witness:
- pulls the repository (fast-forward only) and replays the ledger with the verifier built into its image, never with freshly pulled code;
- refuses to sign if the governed files differ from what was ratified (`govern.check_tree`);
- carries out what the protocol says is due (`ledger.due_actions`): it closes expired ballots and draws pending lots with the drand beacon;
- signs `witness` checkpoints with `(upto_seq, head, state_sha256, state_version, root, anchor)`: each covers every entry before it and states the digest of the state they leave and the version of the state document. A witness posts at most one checkpoint an hour, and only when some other entry was added since its last one (`ledger.checkpoint_due`).

See whitepaper §8.2 and `witness.cycle` in `node/witness.py`. While the witness's previous PR has not been merged, or if it cannot sync with origin, it only verifies, so that it never forks the chain.

**What the code checks** (`ledger._witness`):
- `upto_seq` must be the entry just before the checkpoint, and `head` the hash of that entry;
- `state_version` must be the version of the state document this core writes (2), and `state_sha256` must equal the digest of the state as that entry left it (SPEC §4.11), so a verifier whose state differs refuses the checkpoint;
- if a `root` is given, it must equal `merkle_root(hashes)`, the RFC 6962 root of all entries up to that point.

**The witness set:**
- at genesis, witnesses are named with their keys, `ssh-ed25519` or the hardware-backed `sk-ssh-ed25519@openssh.com` (`ledger._genesis`); a genesis may name any number of witnesses, or none;
- afterwards, the set is changed by a ballot of kind **`witness`**, `add` or `remove`, opened by a Master Builder and decided by the two-thirds rule among the Masters (`ledger._open_witness`, `ledger._close_witness`); a new name may not collide, case-insensitively, with a member login, a custodian name or another witness, and the proposed key must sign a proof of possession;
- a `witness` entry signed by an unknown name is rejected (`ledger._signer`);
- until the [[founder-sunset]], a Custodian may freeze a witness key for 30 days by a correction; no correction stays, voids or undoes a ballot that adds a witness, because the Sunset counts witnesses. A frozen witness signs nothing, and members may still close ballots and draw lots (`ledger._act_freeze_witness`; see [[custodian-and-corrections]]). The last unfrozen witness is frozen only on the ground of an attack in progress;
- four witnesses are one half of the Sunset condition (`ledger.sunset_reached`).

**Capture alarm:** if replay fails, the witness logs "CAPTURE ALARM" and opens an issue labeled `capture-alarm` (`witness.alarm`), with only one such issue open at a time. The same alarm is raised, and nothing is signed, when the canonical ledger no longer holds the head the node last verified (a rollback), starts from another genesis, or ends with an entry dated ahead of the clock (`witness.verified_head`, `ledger.head_verdict`, `ledger.future_head`).

## What is not in the code yet
- **2f + 1 finality.** The whitepaper says a checkpoint is **final** when signed by ≥ `2f + 1` of `n ≥ 3f + 1` witnesses, but the verifier only **records** checkpoints. Nothing counts signatures or marks finality.
- **Checkpoint co-signing by the 6th degree.** Whitepaper §7.1 summarizes the duty of the 6th degree as "co-signs checkpoints"; the canon (`canon/degrees.toml`) states it as "Operate a witness node, once added by a witness ballot". There is no entry type for co-signing an epoch checkpoint.
- **Network status.** In v0.1 the genesis is expected to name **one** witness or none (any VPS running the witness container), and the verifier records checkpoints without counting signatures toward finality; in the whitepaper's words, v0.1 "is not Byzantine-tolerant". The target is 4 → 7 → 13 operators (v0.6 "Witnesses ×4").

## Why it matters
A repository administrator who force-pushes a different history cannot hide it. Every witness and every clone notices that `H(eₖ)` changed for some already-checkpointed `k`, and the anchored roots prove which history existed first (§4.4). The witnesses are the distributed version of the [[tyler]].

See [[chained-ledger]], [[opentimestamps]], [[founder-sunset]].
