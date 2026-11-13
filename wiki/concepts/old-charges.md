---
title: "Old Charges"
type: concept
tags: [history, law, old-charges, constitutions, tradition]
sources:
  - raw/sources/sym-landmarks-anderson-mackey-pound.md
  - docs/whitepaper/WHITEPAPER.md
  - src/openmasonry/ledger.py
  - CONSTITUTION.md
---

# Old Charges

The medieval and early modern manuscripts of the English and Scottish stonemasons. They combine a legendary history of the craft, running from Euclid's geometry through the builders of the Temple, with rules of conduct: loyalty to lord and master, honest work, fair wages, not poaching another's apprentice. The oldest is the **Regius Poem** (c. 1390, 794 lines), followed by the **Cooke Manuscript** (c. 1425). More than a hundred versions survive.

**The 1723 *Constitutions*.** [[james-anderson]] rewrote this heritage for the Grand Lodge of London as **six Charges**:

- I. Concerning God and Religion;
- II. Of the Civil Magistrate;
- III. Of Lodges;
- IV. Of Masters, Wardens, Fellows and Apprentices;
- V. Of the Management of the Craft in working;
- VI. Of Behavior.

Charge I is the most famous. It binds the Mason to the moral law and, instead of imposing a creed, only to the religion "in which all men agree". Its authorship is debated (Desaguliers and Payne appear as possible co-authors). Anderson changed the text in 1738, and Entick restored the 1723 wording in 1756.

**Readings**
- **Legal.** The Charges are the "common law" of the craft, the origin of the constitutions and regulations of every grand lodge.
- **Professional ethics.** Before any symbolism, they are a code of conduct for a working guild.
- **Religious and political.** Charge I is read sometimes as Enlightenment tolerance, sometimes as disguised deism. Charge II (loyalty to the civil magistrate, refusal to conspire) is the root of the political neutrality of lodges.

## In OpenMasonry
- OpenMasonry inherits the idea of a **written constitution** that binds everyone, including those who govern. Its own is text, and code where the ledger enforces it: "Every rule that binds members is published as text, and as code wherever the ledger enforces it" (Landmark VI). See [[eternal-landmarks-of-openmasonry]], [[chained-ledger]].
- The entry "Charge" became the **Declaration** signed in the petition, whose SHA-256 goes into the `petition` entry: `ledger._petition` compares it with the digest the genesis recorded (`declaration_sha256`), and the tree check compares that digest with the text in the `[declaration]` section of `canon/eternal.toml` (`govern.check_tree`, `canon.declaration_digest`). See [[sybil-resistance]] and [[member-journey]] for the rest of the admission path.
- Charge I is radicalized: the "religion in which all men agree" becomes **no requirement of belief at all** (Landmark I). See [[great-architect-of-the-universe]].
- Governed files (`CONSTITUTION.md`, `canon/degrees.toml`, `canon/eternal.toml`, the charters `docs/governance/CUSTODIAN.md` and `docs/governance/ROOMS.md`, and the protocol core, `@protocol`, all pinned at genesis, plus any that amendments come to pin) change only by a hash-pinned amendment (`ledger._genesis`, `ledger._open_amendment`, `ledger._close_amendment`; `govern.check_tree`). The Eternal Landmarks never change, and no correction changes a governed file either (see [[custodian-and-corrections]]).
