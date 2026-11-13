---
title: "Castro & Liskov, Practical Byzantine Fault Tolerance (1999)"
type: source
tags: [bft, distributed-systems, consensus, protocol]
sources:
  - raw/sources/proto-pbft-1999.md
---

# PBFT (1999)

The first practical Byzantine protocol for state machine replication. Its central points:
- `n ≥ 3f + 1` replicas tolerate `f` malicious ones;
- quorums of `2f + 1`;
- three phases (pre-prepare, prepare, commit);
- view change;
- stable **checkpoints** with `2f + 1` signatures.

**Why it matters.** OpenMasonry's witnesses (whitepaper §8.2) aim at the same bound, `2f + 1` signatures out of `n ≥ 3f + 1` witnesses; in v0.1 no checkpoint is final, and finality by that bound is planned for v0.6. See [[byzantine-fault-tolerance]].
