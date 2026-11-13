---
title: "Todd, announcement of OpenTimestamps (2016)"
type: source
tags: [timestamping, bitcoin, anchoring, protocol]
sources:
  - raw/sources/proto-opentimestamps-2016.md
---

# OpenTimestamps (2016)

A timestamping system that proves a piece of data existed before a given date. It works like this:
- calendar servers aggregate digests into a Merkle tree;
- only the root is written to Bitcoin, so the cost per timestamp is close to zero;
- a calendar cannot forge a timestamp, only refuse service.

**Why it matters.** It is OpenMasonry's "anchor layer" (whitepaper §4.1, §4.3). Bitcoin is used only as a public clock and notary, with no token. See [[opentimestamps]].
