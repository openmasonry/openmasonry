# Clip: Yu, Gibbons, Kaminsky, Xiao, *SybilLimit* (IEEE S&P 2008)

- **URL:** https://www.comp.nus.edu.sg/~yuhf/yuh-sybillimit.pdf
- **Authors:** Haifeng Yu (NUS), Phillip B. Gibbons (Intel Research Pittsburgh), Michael Kaminsky (Intel Research Pittsburgh), Feng Xiao (NUS)
- **Date:** 2008, IEEE Symposium on Security and Privacy
- **Captured:** November 2026 (copyrighted paper: summary)

## Key facts
- **Sybil attack:** a malicious user pretends to have multiple identities ("sybil nodes") and can then "out vote" honest users in collaborative tasks (Byzantine consensus, voting, DHTs).
- Without a central authority, simple defenses (tying identity to IP, CAPTCHAs, payment) give limited protection.
- **Key idea (SybilGuard/SybilLimit):** in a social graph, edges between the honest region and the Sybil region ("attack edges") are scarce, because they require deceiving real humans. Hence the number of Sybils accepted is bounded per attack edge.
- **Result:** SybilLimit accepts O(log n) Sybil nodes per attack edge, a Θ(√n) reduction relative to SybilGuard (O(√n log n)); ~200× better in a million-node system; the guarantee is within a factor of log n of optimal.
- **Assumptions:** a fast-mixing social graph (verified empirically on three real networks) and a limited number of attack edges.
