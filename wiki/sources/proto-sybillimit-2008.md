---
title: "Yu et al., SybilLimit (IEEE S&P 2008)"
type: source
tags: [sybil, security, social-graph, protocol]
sources:
  - raw/sources/proto-sybillimit-2008.md
---

# *SybilLimit* (2008)

A social-graph-based defense protocol against Sybil attacks. Because edges between honest nodes and Sybils ("attack edges") are scarce, the number of fake identities accepted is bounded by **O(log n) per attack edge**, a Θ(√n) improvement over SybilGuard.

**Why it matters.** The whitepaper (§5.3) uses this result to justify the sponsorship budget: each deceived Master is an "attack edge", and the budget `b = 4` makes the per-edge constant explicit and small. See [[sybil-resistance]].

**Limit.** OpenMasonry does not implement SybilLimit (random walks on the graph). It only uses the same intuition: trust costs human edges.
