---
title: "Decision Function D"
type: concept
tags: [protocol, voting, quorum, governance]
sources:
  - src/openmasonry/ledger.py
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/sym-haywood-symbolical-masonry-1923.md
---

# Decision Function D

The pure function that decides every OpenMasonry ballot (admission, advancement, amendment, sanction, witness and the removal of a Custodian), once its votes reach the quorum.

## Exact rule (code)
Let `N` be the **quorum base** of the ballot (the electors present, that is not dormant, when it opened), `Y` the revealed yes votes, `B` the revealed no votes and `T = Y + B`.
```
Q(N) = min( N, max(3, ⌈N/3⌉) )                         quorum of votes cast
D_admission(Y,B,N) = T ≥ Q(N) ∧ 5B < T                  rejected by 1/5 black balls
D_advancement      = D_admission
D_amendment(Y,B,N) = T ≥ Q(N) ∧ 3Y ≥ 2T ∧ 3T ≥ N         two thirds, one-third turnout
D_sanction = D_witness = D_amendment
D_custodian(Y,B,N) = T ≥ Q(N) ∧ Y > B                    simple majority of the votes cast; a tie fails
```
- The functions are `ledger.quorum`, `ledger.quorate` and `ledger.decide`. The two rules are `return 5 * no < t` and `return 3 * yes >= 2 * t and 3 * t >= electorate`. An empty base or `t < Q(N)` yields false.
- **A ballot that misses the quorum lapses** (`ballot_close`): it decides nothing and penalizes nobody, and `decide` is not asked. With three present electors or fewer the quorum is all of them. A lapsed ballot may be re-run once, within 30 days and with at least 7 days to commit, and the re-run does not wait again for those who did not vote; a re-run, and a ballot that gave less than 7 days to commit, are never re-run (a short ballot that lapses is opened again as a new ballot, which waits for every elector). A sanction on a Master Builder also lapses with fewer than two votes cast, and is never opened with fewer than two electors. Amendment, sanction and witness ballots follow the two-thirds rule; a `custodian` ballot, whose one possible decision is to remove a custodian key, passes when `yes > no`; an unknown kind is an error, so the function is exhaustive over the six kinds (`ledger.KINDS`).
- **Equivalence (Appendix C.1):** `B ≥ ⌈T/5⌉ ⇔ 5B ≥ T`. So an admission is **rejected if and only if `5B ≥ T`**.
- The condition `3T ≥ N` is implied by `T ≥ Q(N)`, because `Q(N) ≥ ⌈N/3⌉`. It is redundant but explicit.

Worked examples: an admission with `N = 7` and 5 yes, 1 no passes (`5 < 6`); with 4 yes, 1 no it fails (`5 < 5` is false); with 2 votes it lapses (`T < 3`). An amendment with `N = 12` and 4 yes, 0 no passes (`T = Q = 4`). A removal of a Custodian with 2 yes, 2 no fails: a tie fails (SPEC §7.2).

## Electorates (`ledger.electorate`)
The rung is chosen on the members present; the electors are every active member of that rung, the dormant ones included, and `N` counts the present ones (see [[dormancy]]). No fallback ever removes a vote (Landmark V): whoever had the vote on the first rung keeps it on the next.

| Kind | Rung | Fallback |
|---|---|---|
| admission | 2nd degree and above (a silent member is not counted present) | everyone (1st+) if nobody of the 2nd or higher is present, the electors of the first rung keeping the vote |
| advancement to degree d | degree ≥ d, except the candidate (a silent member is not counted present) | Masters (3rd+) if fewer than 3 are present, the electors of the first rung keeping the vote; in a succession, the successors if no Master is present |
| amendment | Masters (3rd+) | none |
| witness (add/remove) | Masters (3rd+) | none |
| sanction | Arbiters (7th+), except the accused | Masters (except the accused) if fewer than 3 are present |
| custodian (remove) | Masters (3rd+), except the member the Custodian is linked to | none |

The electorate is frozen when the ballot opens (`Ballot.electors`). Only one ballot of a kind is open on a subject (`State.open_ballot_on`); for an amendment the subject is the path together with the text proposed, so two texts for one path may be open at once. Every ballot but an amendment has fixed windows (7 days to commit, 3 to reveal). The removal ballot and amendment ballots run through a halt of the ledger and are never stayed, voided or undone by a correction (see [[custodian-and-corrections]]).

## Tested properties
- **Monotonicity:** one more yes never turns approval into rejection.
- **Quorum safety:** nothing passes with fewer than Q(N) votes.
- **Small-body blackball:** if T ≤ 5, one black ball rejects.
- **Bounded blackball:** if T > 5, rejection requires ≥ ⌈T/5⌉ black balls.
- **Capture threshold (C.2):** with `h` honest members voting no, a hostile admission passes only if `a > 4h`.

**Why 1/5 and not unanimity.** Unanimity lets a single member bar someone forever. The one-fifth rule comes from the French practice recorded by Haywood (see [[ballot-and-blackball]]). Each vote counts 1, whatever the degree (Landmark IV; see [[level-and-plumb]] and [[eternal-landmarks-of-openmasonry]]). Dormant members keep the vote and drop out of the quorum base (see [[dormancy]]).
