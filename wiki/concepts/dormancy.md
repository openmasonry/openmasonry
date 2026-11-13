---
title: "Dormancy"
type: concept
tags: [protocol, membership, quorum, activity]
sources:
  - src/openmasonry/ledger.py
  - src/openmasonry/canon.py
  - docs/whitepaper/WHITEPAPER.md
---

# Dormancy

The state of a member who has gone more than a year without any signed activity. They **keep their degree and their vote**, but are not counted in the quorum, and drop out of the examiner and lot pools and of the counts of Master Builders until they act again.

## Exact rule (code)
```
dormant(m, t) ⇔ t − last_activity(m) > 365 days
```
- `Member.dormant` takes the member's latest activity (`Member.last_active`: the newest point of activity, or the admission while there is none) and returns `expired(last, now, canon.DORMANT_AFTER_DAYS)`: more than 365 days have passed, to the second.
- `canon.DORMANT_AFTER_DAYS = 365`. The comparison is strict: at exactly 365 full days the member is still active.
- `State.active()` excludes dormant members. So they are left out of `masters`, `examiner_pool` and the pool frozen at `council_call`, and out of the **quorum base** of every ballot.
- **Dormancy never removes a vote.** The electors of a ballot are every active member of its rung, dormant ones included (`ledger.eligible`); the quorum and the turnout count only the present ones (`ledger.electorate` returns both). A dormant Master may commit and reveal like any other, so the first dormant founder to sign is never an electorate of one: the others are electors too.
- **Leaving dormancy:** any new entry signed by the member counts as activity again, except a departure and the upkeep of a key (`rekey`, `rekey_object`), which add none (`Member.credit`, `ledger.UNCREDITED`). A dormant member may still sign: dormancy never blocks an act, and a dormant member keeps access to the study [[rooms]].

## Why it exists
It prevents **death by quorum**, the slow paralysis of associations whose rolls fill up with inactive names. Because the quorum base `N` of the [[decision-function]] counts only present members, the quorum `Q(N) = min(N, max(3, ⌈N/3⌉))` stays reachable as people drift away, while every member who returns still has a say.

## Side effects
- `founding_phase()` uses `masters(now)`, which excludes dormant members (`State.founding_phase`). If Masters fall dormant and the number of active Masters drops below 7, the fraternity **returns to the Founding Phase**, and its sponsor rule applies again: `max(1, min(2, Masters))` sponsors, and one once a petition has been live 30 days. See [[sybil-resistance]].
- Dormant Masters do not count for the [[founder-sunset]], for the founder's fallback (a founder's claim of the Custodian office) or for the succession: when every Master is dormant, a member below the 3rd degree may claim the succession, and any entry signed within 90 days by a Master who, after it, is active and neither dormant nor silent cancels it.
- **Silent Masters.** A Master Builder is **silent** when called to at least two examinations or ballots that ended in the last 180 days and they answered none of them, even if they signed other entries; two calls count as two only when they end at least 7 days apart (`Member.called`). Only a ballot that gives at least 7 days to commit calls its electors, and only a revealed vote answers it (a sealed vote never revealed does not); a shorter ballot calls nobody, and if it lapses it is never re-run: it is opened again as a new ballot that waits for every elector (`ledger.full_call`). A silence ends with one revealed vote or one report; recording a work does not end it (`Member.silent`, `ledger._heard`). A silent Master counts as dormant for the succession (claiming it, canceling it, and the three Masters that end it must be neither dormant nor silent), and for rungs 2 and 3 of the lot of examiners; at every rung of an admission and of an advancement a silent member of any degree is not counted present, so a lone apprentice behind a silent Master still admits a newcomer, who can then examine them. Like a dormant one, a silent member keeps the vote: no fallback ever removes a vote (Landmark V). While a succession is in force, the calls of every member are recorded (`ledger._serves`), and a successor who is silent is no successor: where the whole highest degree present is silent, the next degree down stands in (`State.successors`). The Guide tells a member who counts as silent so, with a `silent` notice.
- In the tradition, it roughly matches the member who goes "dormant" through non-attendance in many grand lodges, but here without any financial dues (Landmark III). See [[light-score]].
