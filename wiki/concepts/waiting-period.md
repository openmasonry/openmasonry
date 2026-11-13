---
title: "Waiting Period"
type: concept
tags: [degrees, time, advancement, protocol, tradition]
sources:
  - canon/degrees.toml
  - src/openmasonry/ledger.py
  - src/openmasonry/canon.py
  - docs/whitepaper/WHITEPAPER.md
---

# Waiting Period

In Masonic tradition the waiting period is the **minimum time** a member must remain in a degree before being raised to the next. The periods vary widely between grand lodges and rites. In many American jurisdictions the three Craft (Blue Lodge) degrees can be conferred within a few weeks. Elsewhere months are counted between degrees and years in the higher degrees, and exceptional dispensations exist.

**Readings**
- **Pedagogical:** the time is for absorbing the lesson of one degree before the next. A stone is not dressed in one go (see [[rough-and-perfect-ashlar]]).
- **Proof of constancy:** staying shows commitment and not mere enthusiasm.
- **Critical:** where dispensations are easy, or where speed can be "bought" (one-day degrees, degree festivals), the waiting period becomes a formality.

## In OpenMasonry
The waiting period is the **only "cost" of a degree**, and time cannot be bought (whitepaper §7.3). The protocol enforces it as follows:
- **Canonical field:** `wait_days` in `canon/degrees.toml` is the minimum number of days in the **previous** degree. Examples: 30 for the 2nd, 60 for the 3rd, 180 for the 4th and the 15th, 365 for the 19th, 31st and 32nd, and 730 for the 33rd.
- **Check:** `wait_ok(m, target, now)` requires `now − since(m, current_degree) ≥ wait_days(target)` (`ledger.wait_ok`), reading the waiting period from the canon **ratified** at that point in history (`State.degree`, via `canon.degrees_for`), not from today's file. The rule is checked when an exam opens (`ledger._exam_open`) and when an advancement ballot opens (`ledger._ballot_open`). A failed exam (by a majority of fails, or by a failed advancement ballot) allows a new exam only 90 days after it was opened (`EXAM_RETRY_DAYS`), which adds time to the path. An exam that times out after 60 days without a verdict costs no wait: a new one may be opened at once.
- **Minimum path:** `canon.minimum_days_to(n)` sums the waiting periods from 2 to n. The result is 3rd = 90 days, 14th = 570, 18th = 930, 30th = 1,955, 32nd = 2,685 and the earliest possible seat in the 33rd = 3,415 days (≈ 9.4 years). Each advancement also takes an exam and a ballot: at least 7 days 14 hours 15 minutes more (8 hours to the beacon, 7 days to commit, the gap of 6 hours 15 minutes, and an early close when every elector has revealed), so the 2nd degree comes 37 d 14 h 15 m after initiation at the earliest.
- **33rd:** the degree cannot be asked for. An active member publishes `council_call`, which fixes a future drand round and freezes the pool: 32nd-degree members with ≥ 730 days in the degree who have never held a seat (`ledger._council_call`). After that round, `council_draw` draws from this pool. See [[verifiable-lottery]].
- Time is also a barrier in [[sybil-resistance]]: new identities need ≥ 90 days to become Masters able to sponsor.
- There is no dispensation: no office, not even the founder, skips the waiting period of a degree. The founders begin at the 3rd degree by the genesis, so they never pass the Craft waits; from the 3rd on they wait like everyone else (see [[founder-sunset]]).
