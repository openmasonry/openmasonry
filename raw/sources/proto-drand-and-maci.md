# Clip: drand (League of Entropy) and MACI

- **URLs:** https://drand.love/docs/overview/ · https://maci.pse.dev/docs/introduction
- **Authors:** the drand project / League of Entropy (Cloudflare, EPFL, Protocol Labs, ChainSafe and others); MACI by Privacy & Scaling Explorations (Ethereum Foundation)
- **Captured:** November 2026 (documentation: summary)

## drand
- A distributed randomness beacon: **verifiable, unpredictable and unbiasable** random numbers as a public service (HTTP JSON API, gRPC, libp2p; Go and JS clients).
- Operated by the League of Entropy, a consortium of independent organizations.
- From the drand specification (not covered by the overview page): each "round" is a threshold signature (threshold BLS) produced at a fixed period; no set of nodes below the threshold knows the value before it is published.

## MACI (Minimal Anti-Collusion Infrastructure)
- Private on-chain voting: votes encrypted (ECDH) to a **coordinator**; voters cannot prove whom they voted for, which weakens bribery and coercion. A later vote can override an earlier one.
- The coordinator publishes the result with **zk-SNARK proofs** of a correct tally, verified on-chain.
- Trust: privacy depends on the coordinator (who can decrypt the votes), but a dishonest coordinator cannot censor or tamper with the tally.
