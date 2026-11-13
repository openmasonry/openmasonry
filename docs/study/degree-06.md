# 6°: Scribe of Trust (study outline)

**House:** The Lodge of Perfection. Duty, stewardship and justice inside the community.  
**Virtue:** Faithfulness  
**Art:** Records and signatures: hashes, keys and the integrity of the written word  
**Lesson:** "Every record is a promise to someone who is not yet born."  
**Summary page:** [docs/degrees/degree-06.md](../degrees/degree-06.md) (generated from [`canon/degrees.toml`](../../canon/degrees.toml))

An outline; the general criteria of every examination are in the [README](README.md).

## Purpose

The 6th degree makes a member a guarantor of the record. OpenMasonry claims that anyone can replay its history and reach the same state (Landmark VI). A Scribe of Trust has done it personally and published the proof, so that the claim rests on witnesses and not on faith.

## Virtue: Faithfulness

Faithfulness is exactness in keeping what was entrusted: copying without alteration, reporting without embellishment, and saying plainly when something could not be checked. It is misread as trust in the system ('the tests pass, so it must be right') or as loyalty to the people who maintain it.

## Art

Records and signatures: how hash functions, hash chains, Merkle trees and digital signatures make a written record tamper-evident. The study covers what a hash commits to, what a signature proves (possession of a key, not identity) and why independent replication matters. The [specification](../whitepaper/SPEC.md) describes exactly what the verifier checks.

## Lesson

> "Every record is a promise to someone who is not yet born."

A record outlives the people who made it. Whoever reads it later, perhaps generations later, cannot ask the writer what was meant or whether it was altered. Integrity of the record is a promise made to that reader.

## Masterwork

The canon states it exactly as follows:

> Independently verify the full ledger from genesis and publish the verification transcript

Practical pointers:

- Use a clone you control, and record the exact commit of the ledger head and the version of the verifier you ran.
- Run the full verification from genesis (`bin/om verify`; see [SPEC §9.1](../whitepaper/SPEC.md#91-the-verify-command)) and, where possible, the online checks that re-fetch the public beacons.
- Check at least one part by independent means, such as a hand check of an entry hash or the conformance vectors in `tests/vectors/`.
- Publish the full transcript, with the state digest reached and any warning, unedited.

**Procedure.** At least 30 days in the 5th degree; then three examiners, drawn from the members of the 6th degree and above, then from the Master Builders, as drawn by lot under the rules in [SPEC.md](../whitepaper/SPEC.md#73-the-examiner-pool-ladder), each publishing a reasoned verdict; then an advancement ballot of peers (steps in the [guide of the 3rd degree](degree-03.md#54-from-work-to-degree-the-examination-and-the-ballot)).

## Examination criteria

- The transcript covers the whole ledger from genesis to a stated head.
- The versions, commands and environment are stated so that anyone can repeat the run.
- The candidate reports what was checked, what was taken on trust and any discrepancy found.
- At least one independent check beyond the standard command is documented.
- The work is the candidate's own; help and sources are acknowledged and traceable.

## Reading

- **Whitfield Diffie and Martin Hellman**, "New Directions in Cryptography" (1976, widely available).
- **Ralph Merkle**, "A Certified Digital Signature" (widely available).
- **B. Laurie, A. Langley and E. Kasper**, *Certificate Transparency*, RFC 6962 (open).
- **S. Josefsson and I. Liusvaara**, *Edwards-Curve Digital Signature Algorithm (EdDSA)*, RFC 8032 (open).
- The project's [specification](../whitepaper/SPEC.md) and [architecture](../architecture/ARCHITECTURE.md).

## What it unlocks

The canon states: "Operate a witness node, once added by a witness ballot". Witness nodes are added and removed only by witness ballot (Constitution [Art. XI.2](../../CONSTITUTION.md#article-xi-witnesses-the-tyler-and-infrastructure)). These are duties and eligibility, never weight (Landmark IV).

---

*This is an outline; a full guide of the 6th degree is still to be written. An outline that has not been replaced delays and invalidates nothing: the canon alone sets what a degree requires.*
