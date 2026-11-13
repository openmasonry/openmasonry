# 12°: Master Architect (study outline)

**House:** The Lodge of Perfection. Duty, stewardship and justice inside the community.  
**Virtue:** Prudence  
**Art:** System design: geometry of structures, failure modes and simplicity  
**Lesson:** "Design so that the next builder can change what you built."  
**Summary page:** [docs/degrees/degree-12.md](../degrees/degree-12.md) (generated from [`canon/degrees.toml`](../../canon/degrees.toml))

An outline; the general criteria of every examination are in the [README](README.md).

## Purpose

The 12th degree prepares members to shape the structure itself. A Master Architect reviews changes to the protocol code, so the degree trains the judgment that good structures require: simple, explained, and open to change by others.

## Virtue: Prudence

Prudence is practical wisdom: choosing well under uncertainty, with attention to consequences and to what cannot be undone. It is misread as timidity, or as complexity added 'just in case'.

## Art

System design: the geometry of structures, failure modes and simplicity. The study covers modularity and information hiding, interfaces, failure analysis, reversibility, the cost of complexity, and the practice of recording decisions so that later builders know why things are as they are.

## Lesson

> "Design so that the next builder can change what you built."

Every structure will be changed by someone who did not build it. The lesson asks the designer to write for that person: explain the reasons, keep the parts separable, avoid cleverness that only its author understands.

## Masterwork

The canon states it exactly as follows:

> An architecture decision record (ADR) accepted into the canonical repository

Practical pointers:

- Choose a real design question in the canonical repository, not a hypothetical one.
- Follow a standard decision-record form: title, status, context, decision, consequences, with the alternatives considered.
- Say what would make the decision wrong and how it could be reversed.
- Submit it through the repository's normal review; a decision that would change a governed path still requires an amendment ballot.

**Procedure.** At least 30 days in the 11th degree; then three examiners, drawn from the members of the 12th degree and above, then from the Master Builders, as drawn by lot under the rules in [SPEC.md](../whitepaper/SPEC.md#73-the-examiner-pool-ladder), each publishing a reasoned verdict; then an advancement ballot of peers (steps in the [guide of the 3rd degree](degree-03.md#54-from-work-to-degree-the-examination-and-the-ballot)).

## Examination criteria

- The record was accepted into the canonical repository by its normal review.
- Context, alternatives and consequences are stated honestly, including the costs of the chosen option.
- The decision favors simplicity and reversibility, or explains why not.
- The work is the candidate's own; help and sources are acknowledged and traceable.

## Reading

- **Vitruvius**, *The Ten Books on Architecture* (Morris Hicky Morgan translation, public domain, on Project Gutenberg).
- **David L. Parnas**, "On the Criteria To Be Used in Decomposing Systems into Modules" (1972, widely available).
- **Jerome H. Saltzer and Michael D. Schroeder**, "The Protection of Information in Computer Systems" (1975, widely available).
- **Michael Nygard**, "Documenting Architecture Decisions" (widely available).
- **John Ousterhout**, *A Philosophy of Software Design* (widely available).

## What it unlocks

The canon states: "Review protocol-code amendments (one of the required reviewers)". These are duties and eligibility, never weight (Landmark IV).

---

*This is an outline; a full guide of the 12th degree is still to be written. An outline that has not been replaced delays and invalidates nothing: the canon alone sets what a degree requires.*
