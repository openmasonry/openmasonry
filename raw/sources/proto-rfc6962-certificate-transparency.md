# Clip: RFC 6962: Certificate Transparency (2013)

- **URL:** https://www.rfc-editor.org/rfc/rfc6962
- **Authors:** B. Laurie, A. Langley, E. Kasper (Google)
- **Date:** June 2013 (Experimental)
- **Captured:** November 2026 (IETF text; short quotations)

## Section 2.1: Merkle Hash Trees
- Empty list: `MTH({}) = SHA-256()`.
- Leaf: `MTH({d(0)}) = SHA-256(0x00 || d(0))`.
- Internal node (n > 1): `MTH(D[n]) = SHA-256(0x01 || MTH(D[0:k]) || MTH(D[k:n]))`, where **k is the largest power of two smaller than n** (k < n ≤ 2k).
- Distinct 0x00/0x01 prefixes separate the leaf and node domains (second-preimage resistance).
- Nothing is duplicated: an unpaired leaf is promoted by the power-of-two split.

## Purpose
- Public, **append-only**, auditable logs of TLS certificates. Anyone can verify the log's correctness, prove that a new version extends the old one (consistency proof) and detect a log that shows different views to different parties. The log does not prevent misissuance; it makes it visible.
