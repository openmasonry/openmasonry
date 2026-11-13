# 15°: Knight of the East, the Rebuilder (study outline)

**House:** The Chapter of the Rose. Rebuilding, liberty of conscience and active charity.  
**Virtue:** Loyalty to the work  
**Art:** Resilience: backups, mirrors, recovery and continuity  
**Lesson:** "Build with a trowel in one hand and a backup in the other."  
**Summary page:** [docs/degrees/degree-15.md](../degrees/degree-15.md) (generated from [`canon/degrees.toml`](../../canon/degrees.toml))

An outline; the general criteria of every examination are in the [README](README.md).

## Purpose

The 15th degree opens the Chapter of the Rose with the work of rebuilding and continuity. A commons that exists in one place can be lost in one event. A Rebuilder keeps an independent, verified copy of the fraternity's record so that it can always be restored.

## Virtue: Loyalty to the work

Loyalty to the work is faithfulness to the shared project itself, beyond any person or host. It is misread as loyalty to the current maintainers or to one platform; a mirror exists precisely so that the work survives the loss of either.

## Art

Resilience: backups, mirrors, recovery and continuity. The study covers replication, independent hosting, verification of copies, monitoring for divergence, recovery drills and the documentation that lets someone else restore a system. The project's procedures are in [RECOVERY.md](../operations/RECOVERY.md), and the Constitution asks for mirrors on at least three independent hosts ([Art. XI.3](../../CONSTITUTION.md#article-xi-witnesses-the-tyler-and-infrastructure)).

## Lesson

> "Build with a trowel in one hand and a backup in the other."

Builders rebuild while defending what they build. Here the defense is not a weapon but a copy: build and keep a backup at the same time, never one after the other.

## Masterwork

The canon states it exactly as follows:

> Operate a verified mirror of the canonical repository for 90 days

Practical pointers:

- Host the mirror independently of the canonical host.
- Synchronize on a regular schedule and verify each synchronization from genesis.
- Publish the verification results throughout the 90 days, including any divergence and how it was handled.
- Perform at least one restore drill from the mirror and document it.

**Procedure.** At least 180 days in the 14th degree; then three examiners, drawn from the members of the 15th degree and above, then from the Master Builders, as drawn by lot under the rules in [SPEC.md](../whitepaper/SPEC.md#73-the-examiner-pool-ladder), each publishing a reasoned verdict; then an advancement ballot of peers (steps in the [guide of the 3rd degree](degree-03.md#54-from-work-to-degree-the-examination-and-the-ballot)).

## Examination criteria

- The mirror operated for at least 90 days, as the published verifications show.
- Each verification covers the full ledger, not only recent entries.
- Divergences, outages and their handling are reported honestly.
- The work is the candidate's own; help and sources are acknowledged and traceable.

## Reading

- **Scott Chacon and Ben Straub**, *Pro Git* (freely available).
- **Betsy Beyer and others**, *Site Reliability Engineering*, chapters on data integrity (freely available online).
- **Stanford University Libraries**, the LOCKSS program ("Lots of Copies Keep Stuff Safe") and its published papers (widely available).
- The project's [recovery runbooks](../operations/RECOVERY.md).

## What it unlocks

The canon states: "Operate an official mirror". Official mirrors are certified or decertified by the Supreme Council, subject to reversal by amendment ballot (Constitution [Art. VIII.3](../../CONSTITUTION.md#article-viii-the-supreme-council)). These are duties and eligibility, never weight (Landmark IV).

---

*This is an outline; a full guide of the 15th degree is still to be written. An outline that has not been replaced delays and invalidates nothing: the canon alone sets what a degree requires.*
