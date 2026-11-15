---
title: "Governance: OpenMasonry vs. traditional fraternal orders"
type: comparison
tags: [comparison, governance, supreme-council, terms, transparency, separation-of-powers]
sources:
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/deg-wikipedia-scottish-rite.md
  - raw/sources/deg-sj-valley-degree-list.md
  - raw/sources/sym-landmarks-anderson-mackey-pound.md
  - CONSTITUTION.md
---

# Governance: OpenMasonry vs. fraternal orders

This page compares **who rules, for how long and how transparently** in three cases: the traditional AASR (Supreme Councils), the Craft (Blue Lodge) bodies (grand lodges; in some countries, grand orients) and OpenMasonry. For the traditional orders, it describes only what is **publicly documented**, and in general terms. The exact rules vary by jurisdiction and are set out in each grand body's own constitution and regulations.

## Powers

| Function | Traditional order (typical) | OpenMasonry |
|---|---|---|
| Admitting members | The lodge votes by secret ballot. In many jurisdictions the grand body also records or approves the admission | Ballot of all 2°+ members, with the one-fifth rule and a public result ([[ballot-and-blackball]]) |
| Conferring high degrees | The rite's bodies confer them by internal decision. The 33° comes by invitation of the Supreme Council | Waiting period, public work, examination by drawn examiners and a ballot of peers. The 33° comes by **lot** ([[verifiable-lottery]]) |
| Legislating | Grand lodges adopt constitutions and regulations. Supreme Councils govern the rituals of their rite | All Masters (3°+) vote on amendments: 2/3 of votes and 1/3 turnout. The [[landmarks]] cannot be amended |
| Judging | Discipline procedures set by each grand body; their form varies by jurisdiction | Arbiters (7°+), drawn juries and the Court of Review (31°) |
| Highest body | **Supreme Council**: governs the rite, confers the 33° and issues the rituals | **Supreme Council**: may only **delay** a decision for up to 30 days, convene an assembly and certify mirrors (procedural powers the verifier does not enforce). It **cannot** admit, promote, punish, spend or amend |
| Power held by one person | The Grand Master's prerogatives, which Mackey counts among the landmarks ([[landmarks]]); their extent varies by jurisdiction | **The Custodian's corrections**, until the Sunset only: a closed list of acts on closed grounds, each a signed public entry with a public reason. A correction may freeze, pause or undo (after 14 days of notice) and never grants: it cannot admit, promote, appoint, reinstate or punish. Master Builders stop one by objection (one fifth of the eligible Masters, never fewer than one) and remove the Custodian by simple majority ([[custodian-and-corrections]]) |

## Terms of office

In OpenMasonry an office is a seat held by election, lot or naming (Constitution Art. II.7). The duty a degree unlocks is not an office, and a witness is not one either: it is a key that a ballot may remove at any time.

| | Traditional | OpenMasonry |
|---|---|---|
| Worshipful Master of the lodge | Usually a one- or two-year term with re-election | 1 year, renewable once consecutively |
| Grand Master | Terms of a few years, sometimes with successive re-elections | **Does not exist.** As a member the founder is a 3° with one vote. Until the Sunset a founder named Custodian (by the genesis, which at the founding ceremony names the first founder, or by a founder's claim) also holds that office, with the powers of the Corrections article and no others ([[founder-sunset]]) |
| Custodian | No direct equivalent | Named at genesis, never appointed or elected; while no custodian key is live and few Masters who are not founders exist, a founder may take the office up again by a public claim that one such Master can stop. Each key ends by rule: 180 days without a sign of life, the Sunset condition (seven active Master Builders who are not founders and four witnesses), its own revoke key, removal by ballot, or seven years from its naming. Where no custodian key is live, no correction exists |
| Supreme Council members | In the SJ, active members generally serve for life until emeritus status. The Sovereign Grand Commander serves a long term | 33 seats by lot, **3 years, once in a lifetime**, with staggered renewal |
| Witness | No equivalent | Not an office: a key named by the genesis or added by a witness ballot, and removable by ballot at any time |
| Influence | Accumulates with seniority and title | The [[light-score]] decays with a 180-day half-life and is informational only; a member who stops taking part stops being counted and keeps the vote ([[dormancy]]) |

## Transparency

| | Traditional | OpenMasonry |
|---|---|---|
| Membership list | Private | Logins and keys public in the ledger |
| Votes | Secret forever | Secret during voting ([[commit-reveal]]) and public after the reveal (in v0.1) |
| Accounts | Reported internally to members | Public (Landmark II). There are no fees |
| Ritual | Reserved | Original, public ceremonies |
| Teaching | Given degree by degree to those admitted to it | Public for every degree (Landmark II) |
| Closed meetings | The tyled lodge: proceedings reserved to members | Study [[rooms]], closed but never secret: public rules and roll, no decisions, no duty of silence (§10.6; they opened at the public launch) |
| Use of exceptional power | Recorded internally, under each grand body's own rules | Every correction is a ledger entry with its ground and its reason, readable by anyone; acts of moderation outside the ledger are recorded in it as notes |
| Verification | The secretariat is trusted | Anyone can replay the entire ledger offline ([[chained-ledger]]) |
| Automation | None | The [[tyler]] validates every change in CI |

## Separation of powers

OpenMasonry declares four powers, and none may exercise another's function (Constitution, Art. II). The Custodian is none of the four and no part of their permanent structure: the office is an interim guardianship that makes no rule, judges no one and decides no ballot (Art. II.6).

```
 LEGISLATIVE            EXECUTIVE                          JUDICIAL                      GUARDIAN
 all Masters       │ Lodge officers, maintainers  │ Arbiters 7°, drawn juries,  │ Supreme Council 33°
 (amendments)      │ (8°), Watch (30°), witnesses │ Court of Review 31°         │ (delays ≤ 30 d, convenes)
```

In traditional orders, a rite's Supreme Council usually combines normative functions (rituals and regulations), the conferral of degrees and disciplinary functions within the rite. This is not a moral flaw, but it is exactly the combination of **secrecy, discretion and permanence** that the whitepaper identifies as the condition for capture (§1.3).

## Risks OpenMasonry accepts

- The lot may, by chance, produce a hostile Council. In an eligible pool of 300, the probability of a hostile two-thirds (22 of 33, the only majority with any power) is 4.1 × 10⁻⁶ when 30% of the pool is hostile and 3.2% when half is hostile (§7.5), and even then that Council could only **delay** decisions.
- A small population during the Founding Phase weakens the drawing of examiners: where few members exist, the lot draws from a small pool, and fewer examiners than a degree asks for may be seated.
- The correction power is a real exception to "no one holds special power". While few Master Builders exist, corrections are checked mostly by publicity and the right to fork; while the Custodian's member is the only Master Builder, no one can object or remove.
- After the Sunset no correction exists, and with it no freeze of a stolen key, until the members add a college of Custodians by amendment. A college drawn by lot is the intended path and is future work. The recovery of a lost key needs no Custodian: Master Builders co-sign it, and a public notice runs.
- In v0.1 votes are exposed after the reveal, which may make retaliation easier. Retaliating for a vote is a serious offense.

See also: [[openmasonry-vs-traditional-freemasonry]] · [[openmasonry-vs-token-daos]] · [[decision-function]] · [[custodian-and-corrections]] · [[supreme-council-aasr-southern-jurisdiction]]
