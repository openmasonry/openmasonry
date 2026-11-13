---
title: "RFC 6962, Certificate Transparency (2013)"
type: source
tags: [merkle-tree, transparency-log, protocol]
sources:
  - raw/sources/proto-rfc6962-certificate-transparency.md
---

# RFC 6962: Certificate Transparency

A specification for public append-only logs of TLS certificates, built on Merkle trees.
- Leaf: `SHA-256(0x00‖d)`.
- Node: `SHA-256(0x01‖left‖right)`.
- The split is made at the largest power of two smaller than `n`.
- Empty tree: `SHA-256("")`.

**Why it matters.** It is the model of "verifiable transparency" that OpenMasonry follows in the [[chained-ledger]] and in the roots that witnesses anchor.

**In the code.** `crypto.merkle_root` implements exactly the MTH of RFC 6962 §2.1, with power-of-two splitting and no node duplication. The verifier checks the `root` of each witness checkpoint (see [[opentimestamps]]).
