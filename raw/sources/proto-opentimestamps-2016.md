# Clip: Peter Todd, announcement of OpenTimestamps (2016)

- **URL:** https://petertodd.org/2016/opentimestamps-announcement
- **Author:** Peter Todd
- **Date:** Sept. 15, 2016 (public alpha of client v0.2.0)
- **Captured:** November 2026 (copyrighted work: summary + 1 short quotation)

## Key facts
- Proves that a piece of data existed **before** a given moment, by anchoring it in the Bitcoin blockchain, with no trusted authority.
- **Aggregation:** servers combine many digests into a Merkle tree and write only the root to Bitcoin; one transaction serves countless timestamps, at practically zero cost.
- **Public calendars** (e.g. alice, bob) return an "incomplete" timestamp in ~1 s; it is completed later (`ots upgrade`) once Bitcoin confirms.
- **Trust model:** a calendar cannot forge a timestamp; at worst it refuses service or goes offline. Quotation: "it's Bitcoin, not the aggregation system, that proves the validity".
- The proof is a sequence of operations (SHA-256, append, prepend) that any verifier re-executes up to a block header. Full verification requires a local Bitcoin node.
- **Limits:** it proves only prior existence (existed by such a date); it does not prove authorship or authenticity.
