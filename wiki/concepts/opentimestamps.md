---
title: "OpenTimestamps (anchoring)"
type: concept
tags: [protocol, timestamping, bitcoin, merkle-tree, anchoring]
sources:
  - raw/sources/proto-opentimestamps-2016.md
  - raw/sources/proto-rfc6962-certificate-transparency.md
  - src/openmasonry/crypto.py
  - node/witness.py
  - docs/whitepaper/WHITEPAPER.md
---

# OpenTimestamps (anchoring)

Peter Todd's open protocol (2016) for proving that a piece of data existed **before** a given date, by anchoring its hash in the Bitcoin blockchain. It works like this:
- public calendars aggregate many hashes into a Merkle tree;
- only the root goes into a transaction, so the cost per timestamp is practically zero;
- a calendar cannot forge a timestamp, only withhold service;
- Bitcoin is what proves validity.

## In OpenMasonry
- **Anchor layer** (whitepaper §4.1): OpenTimestamps → Bitcoin block headers, plus archives and mirrors (other forges, decentralized storage, members' clones).
- **Bitcoin only as a public clock and notary:** no token, no fee for members, no mining (§4.3).
- **In the code.** At each checkpoint (at most once an hour, and only when there are new entries), the witness:
  - computes the **cumulative** root `merkle_root(st.hashes)` of all entries;
  - writes that root to `ledger/anchors/NNNNNN.root`;
  - runs `ots stamp` (`witness.anchor`; whitepaper §9.1).

  The path of the proof goes into the checkpoint's `anchor` field. The judge holds both files to the signed checkpoint: the root file must be the root and a newline, and the proof must stamp that file's SHA-256 (SPEC §9.6). A merged proof is never changed; a complete proof is obtained later with `ots upgrade` on a copy, outside the repository.
- **Merkle tree** (`crypto.merkle_root`): the exact Merkle Tree Hash of RFC 6962 §2.1.
  - Leaf: `SHA-256(0x00‖h)`.
  - Node: `SHA-256(0x01‖MTH(D[0:k])‖MTH(D[k:n]))`, with `k` = the largest power of two smaller than `n`.
  - Empty tree: `SHA-256("")`.
  - No node is duplicated, which avoids the ambiguity of CVE-2012-2459.

  The verifier checks the `root` declared in each checkpoint (`ledger._witness`).
- **Honest clock.** Besides the anchor, the [[tyler]] refuses new entries stamped outside [now − 6 hours, now + 2 minutes] (`CLOCK_TOLERANCE`, `JUDGE_FUTURE_TOLERANCE`, `verify --clock-since`); a head more than 10 minutes ahead of a reader's clock is a capture alarm. The residual risk is backdating within that 6-hour window (§8.3); that is why every delay that protects a secret (the lot's beacon, the opening of reveals) is longer than it.
- **Survival:** with `m` independent copies that each fail with probability `q` per year, P(losing all of them) = `qᵐ`. With q = 0.1 and m = 8, that gives 10⁻⁸ (§8.1, C.5).

## Limits
- The anchor proves **prior existence**, not authorship or validity. Validity comes from replay (see [[chained-ledger]]).
- The `anchor` path is recorded, but the offline verifier does not open the `.ots` proof. Anyone who wants to confirm it against Bitcoin runs `ots verify` separately.

See [[byzantine-fault-tolerance]], [[tyler]].
