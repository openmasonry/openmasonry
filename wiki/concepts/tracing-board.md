---
title: "Tracing Board"
type: concept
tags: [symbolism, tracing-board, pedagogy, tradition]
sources:
  - raw/sources/sym-mackey-symbolism-of-freemasonry-1869.md
  - raw/sources/sym-haywood-symbolical-masonry-1923.md
  - src/openmasonry/ledger.py
---

# Tracing Board

A degree's tracing board is a painted panel, or a drawing, that gathers the symbols of a degree: pillars, ashlars, tools, a ladder, heavenly bodies. It serves as a visual aid for instruction. It began as a chalk or charcoal drawing on the lodge floor, wiped away at the end of the meeting, and later became a portable canvas or floorcloth. John Harris's English boards (19th century) set the most widespread model. It should not be confused with the **trestle board**, on which the master of the works drew the plans (see [[masterwork]]).

**Traditional readings**
- **Mnemonic map.** The board shows in a single image everything the degree teaches by allegory. The lodge is a "mystical representation of the world", and the board is a map of that world.
- **Ephemerality.** The floor drawing, wiped away at every meeting, taught discretion and recalled that the work is always done anew.
- **Divine plan.** In some readings, the board is the plan of the Great Architect that each person should follow in their own life (see [[great-architect-of-the-universe]]).

## In OpenMasonry
- **"Tracing Board" is the name of the ledger itself.** The docstring of the `ledger` module says: "The Tracing Board: an append-only, hash-chained, signed ledger" (whitepaper glossary, Appendix D). Here the board is not an image that gets wiped away but **a record that cannot be wiped**: `ledger/entries/NNNN/NNNNNN.json`, chained by hash. See [[chained-ledger]].
- The inversion is deliberate. In the tradition the board was shown to a few and then hidden. In OpenMasonry it is public, replicable and auditable by anyone (Landmark II, "Light, not Secrecy").
- The "state of the fraternity" summary that the [[tyler]] writes on each run of the `judge` job (the output of the verifier; the daily `audit` job adds `openmasonry state`) plays the role of the "painted" board, a readable view of the reconstructed state. The public status page is the Observatory (`bin/om observatory`): built, not operating yet.
