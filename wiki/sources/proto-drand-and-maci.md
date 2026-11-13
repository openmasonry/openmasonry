---
title: "drand (League of Entropy) and MACI"
type: source
tags: [randomness, beacon, voting, privacy, protocol]
sources:
  - raw/sources/proto-drand-and-maci.md
---

# drand and MACI

Notes on two tools from outside the project: drand, the public randomness beacon behind the lot, and MACI, the model for the encrypted ballots planned for v0.3.

**drand.** A public beacon of verifiable, unpredictable and unbiasable randomness, operated by the League of Entropy. It is the source of the `beacon` in the [[verifiable-lottery]] (whitepaper §7.4). The protocol uses the quicknet chain (3 s rounds), declares the round about 8 hours in advance (9,600 rounds, longer than the 6-hour clock tolerance) and audits the values with `verify --online` (`src/openmasonry/beacon.py`).

**MACI.** Anti-collusion infrastructure for voting. Votes are encrypted to a coordinator, the tally is proven by zk-SNARK and voters cannot prove how they voted. It is the model for the v0.3 roadmap, which plans to encrypt votes to a threshold key held by the Keepers of Discretion (4°). See [[commit-reveal]].
