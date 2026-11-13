# 30°: Kadosh, Guardian against Capture (study outline)

**House:** The Council of Kadosh. Philosophy, law, and the defense of the commons against capture.  
**Virtue:** Vigilance  
**Art:** Adversarial thinking: security, red-teaming and the anatomy of tyranny  
**Lesson:** "Every institution is one quiet exception away from becoming what it opposed."  
**Summary page:** [docs/degrees/degree-30.md](../degrees/degree-30.md) (generated from [`canon/degrees.toml`](../../canon/degrees.toml))

An outline; the general criteria of every examination are in the [README](README.md).

## Purpose

The 30th degree prepares members to defend the commons against capture. Every institution can be taken over quietly, by exception after exception. A Guardian against Capture has attacked the protocol as an adversary would, and helped repair what was found.

## Virtue: Vigilance

Vigilance is sustained attention to threats, without paranoia and without fatigue. It is misread as suspicion of persons, or as secrecy justified by danger.

## Art

Adversarial thinking: security, red-teaming and the anatomy of tyranny. The study covers threat modeling, attack surfaces, social as well as technical attacks, responsible disclosure, and the historical patterns by which institutions are captured. The Whitepaper's [threat model](../whitepaper/WHITEPAPER.md#8-integrity-threat-model-and-survivability) is the starting point.

## Lesson

> "Every institution is one quiet exception away from becoming what it opposed."

Institutions are rarely captured in one stroke. Each exception seems reasonable on its own; together they turn the institution into its opposite. The lesson trains members to notice the first one.

## Masterwork

The canon states it exactly as follows:

> A red-team report against the protocol with at least one fixed finding

Practical pointers:

- Define scope and rules of engagement in writing before testing; test against a local copy, never the live ledger or members' accounts.
- Report every unrepaired flaw privately, as [SECURITY.md](../../SECURITY.md) describes; publish it once repaired.
- See at least one finding through to a merged fix.
- Publish the report after the fixes, with method, findings, severity and status.

**Procedure.** At least 60 days in the 29th degree; then five examiners, drawn from the members of the 30th degree and above, then from the Master Builders, as drawn by lot under the rules in [SPEC.md](../whitepaper/SPEC.md#73-the-examiner-pool-ladder), each publishing a reasoned verdict; then an advancement ballot of peers (steps in the [guide of the 3rd degree](degree-03.md#54-from-work-to-degree-the-examination-and-the-ballot)).

## Examination criteria

- The report states its scope, method and findings clearly.
- At least one finding has been fixed.
- Disclosure was responsible, and no live system or person was harmed.
- The work is the candidate's own; help and sources are acknowledged and traceable.

## Reading

- **Étienne de La Boétie**, *Discourse on Voluntary Servitude* (public-domain translations).
- **Aristotle**, *Politics*, Book V, on how constitutions decay (public-domain translations).
- **Ross Anderson**, *Security Engineering* (earlier editions freely available online).
- **Ken Thompson**, "Reflections on Trusting Trust" (1984, widely available).
- **OWASP**, *Top Ten* (open).

## What it unlocks

The canon states: "Join the Watch (security response team); answer capture alarms". Anyone may raise a capture alarm, a public issue (`bin/om alarm`); the 30th degree answers them. These are duties and eligibility, never weight (Landmark IV).

---

*This is an outline; a full guide of the 30th degree is still to be written. An outline that has not been replaced delays and invalidates nothing: the canon alone sets what a degree requires.*
