---
title: "OpenMasonry overview"
type: overview
tags: [overview, openmasonry]
sources:
  - raw/sources/hist-anderson-constitutions-1717.md
  - raw/sources/hist-propaganda-due.md
  - raw/sources/hist-membership-decline.md
  - raw/sources/proto-ostrom-governing-the-commons.md
  - raw/sources/deg-wikipedia-scottish-rite.md
  - docs/whitepaper/SPEC.md
  - CONSTITUTION.md
---

# Overview

OpenMasonry is an open, token-free fraternity of 33 degrees that anyone can verify, running on GitHub. It keeps the forms that made Freemasonry last three centuries (degrees as a curriculum of character, sponsors, the ballot, the lodge as a school, the builder's allegory) and removes what lets fraternities be captured: secret government, discretionary rules and permanent power.

## The central thesis
Power accumulates where three things meet: **secrecy, discretion and permanence** (see [[historical-lessons-for-openmasonry]] and [[p2-lodge]]). OpenMasonry removes all three: every rule, record and decision is public and reproducible ([[chained-ledger]]), and so is the teaching of every degree; every rule is public text, and tested code wherever the ledger enforces it ([[decision-function]]), and no office is eternal ([[verifiable-lottery]], [[light-score]], [[dormancy]]). The study rooms of the degrees may be closed, but they are never secret and they decide nothing ([[rooms]], [[eternal-landmarks-of-openmasonry]]).

One bounded exception is stated openly. As a member, no founder has any power another Master Builder lacks, save the fallback of taking up the Custodian office again while no custodian key is live and few other Masters exist. Until the Sunset a founder named Custodian (by the genesis, which at the founding ceremony names the first founder, or by a founder's claim) also holds that office, with the powers of the Corrections article and no others: signed, public corrections that may undo, freeze or pause and never grant, which Master Builders stop by objection ([[custodian-and-corrections]], [[founder-sunset]]). Every custodian key also ends seven years after it was named. While few Master Builders exist, corrections are checked mostly by publicity and the right to fork.

## Where to start
- **History:** [[freemasonry-timeline]] → [[historical-lessons-for-openmasonry]]
- **The degrees:** [[catalog-of-the-33-degrees]] → [[degree-symbols-and-virtues]] → [[member-journey]]
- **How to join:** [[how-to-join-openmasonry]]
- **The protocol:** [[chained-ledger]], [[commit-reveal]], [[decision-function]], [[sybil-resistance]], [[byzantine-fault-tolerance]], [[opentimestamps]], [[tyler]]
- **Principles:** [[eternal-landmarks-of-openmasonry]], [[ostrom-principles]], [[founder-sunset]], [[custodian-and-corrections]], [[rooms]]
- **Comparisons:** [[openmasonry-vs-traditional-freemasonry]], [[openmasonry-vs-token-daos]], [[masonic-rites-compared]], [[governance-openmasonry-vs-fraternal-orders]]

## Active areas
- **Traditional symbols reinterpreted:** [[square-and-compasses]], [[rough-and-perfect-ashlar]], [[tracing-board]], [[ballot-and-blackball]], [[seven-liberal-arts]].
- **People and institutions:** [[james-anderson]], [[albert-pike]], [[albert-mackey]], [[prince-hall]], [[maria-deraismes]], [[elinor-ostrom]], [[united-grand-lodge-of-england]].

## Status
Status: v0.1, genesis not yet signed. Whitepaper, formal specification, Constitution, canon of the 33 degrees, reference verifier with tests and conformance vectors, generated coats of arms, CI (Tyler) and witness node are ready. The CI judge runs the base branch's code, and of it only the pinned core (`@protocol`: the fifteen files a manifest lists, namely the verifier and the three workflows, which are the only workflows the repository may hold). Entries are strict, signature validity is defined by the protocol itself, admission is by invitation, members replace and recover keys, corrections and objections are in the ledger rules, every checkpoint states the digest of the state, and clones refuse a rolled-back ledger. The lottery uses a beacon 8 hours ahead, and canon history is versioned. Still to come before launch: the **Founding Ceremony** (`scripts/genesis.sh`), the first witness, and three pieces that are built but not operating yet: the program that opens the study rooms from the ledger (on every run it publishes, in a public place the Observatory reads, the access the host actually grants, that is the readers of each room, the owners of the organization and every installed application, and an anonymous log of its runs), the public Observatory and the Custodian's private Console (a working tool that decides nothing; its binding outputs are published). Genesis can happen without a witness and add one later through a `witness` ballot. The study rooms of the 33 degrees are already law (Constitution Art. XV, `docs/governance/ROOMS.md`) and open at the public launch. The whitepaper (`docs/whitepaper/WHITEPAPER.md`) explains intent; the exact rules are in `docs/whitepaper/SPEC.md` and in the code.

## Known limitations
- Votes become public after the reveal until v0.3.
- Checkpoints are recorded, not counted: there is no multi-witness finality yet.
- The correction power is a deliberate exception to "no one holds special power". Its bounds are the whole defense, and with a single Master Builder nothing checks it but publicity and the fork.
- After the Sunset no correction exists until the members add a college of Custodians by amendment, which is future work. A lost key is recovered through peers with or without a Custodian.
- Notice periods rest on honest timestamps; an entry can be backdated by up to six hours, and a head dated more than ten minutes ahead of a reader's clock is a capture alarm.
- With a single member, the GitHub account is the root of trust: a recovery of the only Master Builder's key rests on the identity gate, the old key's right to stop one request and 45 days of notice. The final request, 90 days after a stop, cannot be stopped, so whoever holds the GitHub account takes the membership in about 135 days even if the member watches; the same holds where every other Master answered nothing for a year, unless one of them opposes.
- Until the Sunset a single person administers the repository on GitHub; mirrors and the recovery runbooks (`docs/operations/RECOVERY.md`) are the mitigation.

The system is **tamper-evident**, not "unbreakable".
