---
title: "Ostrom's Principles"
type: concept
tags: [commons, governance, ostrom, protocol]
sources:
  - raw/sources/proto-ostrom-governing-the-commons.md
  - docs/whitepaper/WHITEPAPER.md
  - src/openmasonry/ledger.py
---

# Ostrom's Principles

The eight design principles that [[elinor-ostrom]] found, in *Governing the Commons* (1990), in self-governed commons that lasted for centuries: Alpine pastures, Japanese forests, irrigation systems. This work was decisive for her 2009 Nobel Prize in Economics. The principles show that the "tragedy of the commons" is not inevitable: communities create their own institutions, outside both the state and privatization.

## Explicit mapping (whitepaper §3.2)
| Principle | OpenMasonry mechanism | Where in the code |
|---|---|---|
| 1. Clear boundaries | Public, signed set of members | `State.members`; `ledger._petition`, `ledger._ballot_close`, `ledger._depart` |
| 2. Rules fitted to local conditions | Lodges adopt by-laws within the Constitution | §10 (not in the code yet) |
| 3. Collective choice | Every Master (3rd+) votes on amendments | `ledger.electorate` for amendment and witness |
| 4. Accountable monitoring | Witnesses, auditors (31st) and the public replay the ledger; every correction by the Custodian is a public entry that Master Builders can stop by objection ([[custodian-and-corrections]]) | `ledger.replay`; `ledger._witness` checks the head, the state digest and the root; `ledger._correction_object` |
| 5. Graduated sanctions | admonish → suspend → expel, with reinstatement | measures `admonish/suspend/expel/expel_for_fraud/reinstate` (`ledger.MEASURES`, `ledger._close_sanction`); a suspension ends by itself after 365 days |
| 6. Cheap conflict resolution | Arbiters (7th) and juries by lot | sanction electorate 7th+, else the Masters (`ledger.electorate`) |
| 7. Right to organize | MIT license and Landmark VII (fork) | Landmark VII in `canon/eternal.toml`; `depart` entry (`ledger._depart`) |
| 8. Nested enterprises | Lodge → House → Supreme Council; federation (19th) | houses in `canon/degrees.toml` |

## Readings
- **Fair burdens.** The 11th degree, Elect of the Twelve, studies "Economics of the commons: Ostrom's principles, free riding and fair burdens". The lesson of the degree: "A commons dies of silence before it dies of theft."
- **Maintenance.** The 8th, Intendant of the Works, and the 22nd, Knight of the Royal Axe, deal with maintenance work and maintainer burnout.
- **Caveat.** Ostrom studied physical resources and local communities. Applying her work to a digital fraternity is an analogy, and the whitepaper presents the mapping as a design target.

See [[eternal-landmarks-of-openmasonry]], [[enlightenment-sociability]], [[openmasonry-vs-token-daos]].
