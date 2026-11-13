---
title: "Verifiable Lot"
type: concept
tags: [protocol, sortition, randomness, drand, council]
sources:
  - src/openmasonry/lot.py
  - src/openmasonry/ledger.py
  - src/openmasonry/beacon.py
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/proto-drand-and-maci.md
---

# Verifiable Lot

The public, reproducible sortition used to choose examiners and to fill the Supreme Council: anyone with the same beacon obtains the same draw. It revives Athenian sortition (the *klērōtērion*), now with cryptographic proof.

## Exact rule (code)
```
rank(x) = SHA-256( beacon ‖ "|" ‖ purpose ‖ "|" ‖ x )
draw(pool, k, beacon, purpose) = the k members with the lowest rank
```
- `lot.rank` and `lot.draw` (which computes `sorted(set(pool), key=rank)[:k]` and requires `0 ≤ k ≤ len(pool)`).
- **Beacon:** drand's quicknet chain, run by the League of Entropy, with 3 s rounds (`ledger.DRAND_CHAIN`, `DRAND_GENESIS`, `DRAND_PERIOD`). The conversions are `ledger.drand_round(t)` and `ledger.drand_time(r)`.

## Two-step draw (no one knows the beacon when asking)
1. **Call.** `exam_open` (the candidate only) or `council_call` (any active member) must declare `beacon_round = drand_round(time) + 9600` (`BEACON_DELAY_ROUNDS`). That is a round about **8 hours** in the future, longer than the 6-hour clock tolerance (`CLOCK_TOLERANCE`): even a call backdated to the limit still points to a round that has not happened (`ledger._exam_open`, `ledger._council_call`). At the call, the pool and the number `k` are **frozen**, before anyone can know the beacon.
2. **Draw.** `exam_draw` (or `council_draw`) is accepted only from `drand_time(beacon_round)` on, and within 7 days of it (`LOT_DRAW_DAYS`, on the effective clock); it must carry the round's 32 bytes of randomness in lowercase hex (64 characters) (`ledger._exam_draw`, `ledger._council_draw`). Witnesses fetch the value and sign the draw automatically (`ledger.due_actions`, `beacon.fetch`). Witnesses do not call lots: without a `council_call` by a member, the Council is not drawn. **A lot that cannot be drawn lapses**: if the beacon is unavailable for good, after 7 days an exam has timed out without penalty and the candidate opens a new one with a new round, and a council call has lapsed.

- **Anti-grinding.** The `purpose` binds the draw to its object and round: `exam:{login}:{degree}:{round}` and `council:{round}`.
- **Audit.** Every (round, beacon) pair used is in the entries of the lots, and the state keeps their count and hash chain (the history `beacons`). The offline verifier trusts the recorded value. `openmasonry verify --online` fetches each round again from public drand relays and reports any forged beacon (`beacon.audit`; `__main__.cmd_verify`). The [[tyler]] checks the beacons a pull request adds in the `judge` job, and every beacon in the daily audit of `main`.

## Uses
- **Examiners.**
  - `k = examiners(degree)` members are drawn from `ledger.examiner_pool`. The ladder of pools is: (1) degree ≥ target, without the sponsors; (2) any Master, without the sponsors; (3) any Master except the candidate; (4) during a succession with no Master present, the successors except the candidate. A silent Master Builder (see [[dormancy]]) is left out of rungs (2) and (3), and a silent member is never a successor (the next degree down stands in). The first rung that has `k` people is used. If the candidate is a founder, each rung is first tried without the founding cohort.
  - **The lowered lot draws from every rung, in any phase.** If no rung has `k` people, everyone any rung holds is drawn together and `k` is lowered to that number, so the 32nd degree, which asks for seven examiners, is reached at exactly seven Master Builders, with six (`ledger.examiner_pool`, `ledger._exam_open`). Drawing from one rung at a time could alternate forever between a silent sponsor Master and a silent Fellow, neither ever silent long enough for the member below them to stand in; the union calls both. Its price: a silent member drawn beside one who answers makes that exam time out after 60 days, and the next lot leaves them out (SPEC section 12, point 74).
  - **After a timeout the lot seats everyone.** The next lot of the same candidate and degree is the union of the rungs, without the examiners found silent, and seats all of it, though a rung seats `k`: three Masters who sign a work a year and answer nothing, drawn two at a time, were never silent together, and the apprentice below them was never examined. The union calls them all, so within about three exams all are silent and the succession reaches the apprentice. Its price: a member who answers waits one more timeout beside those who do not, and a sponsor can be seated (SPEC section 12, point 75).
  - `exam_draw` ranks the whole frozen pool and seats the first `k`; an examiner whose key is frozen stands aside at the draw. A seated examiner who has not yet reported may recuse (`exam_recuse`, Constitution Art. V.5); the next active, non-dormant member in the lot's order takes the seat, so recusal cannot be used to pick a replacement, and when nobody is left the exam lapses without penalty (`ledger._exam_recuse`).
  - An exam cannot be reopened while it is pending. Once failed (by a majority of fails, or by a failed advancement ballot), another may be opened only 90 days after the failed one was opened (`EXAM_RETRY_DAYS`), so the candidate cannot "reshuffle" the draw. An exam that **times out** (60 days without a verdict, `EXAM_EXPIRY_DAYS`, or a lot not drawn in time) is no failure: a new one may be opened at once, and the examiners who stayed silent are left out of its pool whenever anyone else can be drawn.
- **Supreme Council (33rd).**
  - `council_call` requires vacancies (`COUNCIL_SEATS = 33`) and no other pending call, and it freezes the pool: active, non-dormant 32nd-degree members with ≥ 730 days in the degree and `past_seats == 0`.
  - `council_draw` draws, from this frozen pool, those still active and in the 32nd degree, until the seats are filled.
  - The term is `COUNCIL_TERM_DAYS = 3*365` (`ledger._council_call`, `ledger._council_draw`; `canon.COUNCIL_TERM_DAYS`).
  - The 33rd degree is never asked for.

## Resistance to capture
In a full draw of 33 seats from an eligible pool of 300, the number of hostile councillors follows a hypergeometric distribution (whitepaper §7.5):

| hostile fraction of the pool `p` | P(hostile two thirds, ≥ 22 of 33) | P(hostile blocking minority, ≥ 12 of 33) |
|---:|---:|---:|
| 20% | 4.5 × 10⁻¹⁰ | 1.6% |
| 30% | 4.1 × 10⁻⁶ | 26% |
| 40% | 0.098% | 74% |
| 50% | 3.2% | 97% |

The Council can only **delay**, never veto. That delaying power (≤ 30 days, by two thirds), the convening and the certification are **procedural**: they are in the Constitution (Art. VIII), but the verifier does not enforce them.

**Residual risks.** Compromise of the League of Entropy's threshold. Small populations during the Founding Phase.

**Tradition.** Choosing by lot who serves is the opposite of co-optation and of the lifelong chair. See [[eternal-landmarks-of-openmasonry]] (V), [[founder-sunset]], [[waiting-period]].
