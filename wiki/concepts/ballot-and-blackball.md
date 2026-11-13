---
title: "Ballot and Black Ball"
type: concept
tags: [ballot, voting, admission, tradition]
sources:
  - raw/sources/sym-haywood-symbolical-masonry-1923.md
  - raw/sources/sym-landmarks-anderson-mackey-pound.md
  - src/openmasonry/ledger.py
---

# Ballot and Black Ball

The secret vote by which a lodge admits or refuses a candidate. Traditionally each voter drops a white ball (yes) or a black ball (no) into a ballot box; hence the verb "to blackball". The secrecy of the ballot is one of Mackey's landmarks.

**Historical variations (Haywood, 1923)**
- **United States:** **unanimity** is usually required. A single black ball rejects.
- **England:** **three** black balls were needed.
- **France:** a candidate was rejected when **one fifth** of the votes were negative.
- Haywood acknowledges the abuses (voting on rumor or out of a personal grudge) and the criticism that unanimity gives too much power to a single member. Even so, he concludes that "the present system is as good a method of balloting as can be devised."

**Readings**
- **Harmony.** Unanimity protects the inner peace of the lodge: no one enters against the will of a brother.
- **Protecting the voter.** Secrecy shields the voter from pressure to follow the majority and from retaliation.
- **Risk of capture.** An individual, anonymous veto can block someone forever and can serve factions.

## In OpenMasonry
- OpenMasonry adopts the **French one-fifth rule**: in admission and advancement, a candidate is rejected if and only if `5B ≥ T` (`ledger.decide`: `return 5 * no < t`). With T ≤ 5 votes, one black ball still rejects, which preserves the intimacy of small lodges. In larger bodies, a single grudge is not enough. See [[decision-function]].
- Secrecy is replaced by **commit–reveal**: the vote stays hidden while the commit window is open and is published in the reveal window (see [[commit-reveal]]). The whitepaper admits this weakens the protection of dissenters and names encrypted ballots in the MACI style as a possible later step. Retaliating against a vote is a serious offense.
- **Who opens a ballot.** An admission is opened by a sponsor of the candidate; an advancement by the candidate or an examiner of the passed examination; a sanction by an Arbiter (7th+) where three or more active Arbiters other than the accused exist, else by a Master Builder, never by the accused; an amendment, a witness ballot and the removal of a Custodian by a Master Builder (SPEC §6.4).
- **Windows.** Every ballot but an amendment runs 7 days to commit and 3 to reveal; the opener of an amendment chooses 2 to 30 days and 1 to 14. A ballot closes at the end of its reveal window, or as soon as every elector has revealed.
- **Lapse.** A ballot whose votes miss the quorum lapses and penalizes nobody: the petition stays live and a sponsor opens another ballot, or re-runs it once within 30 days without waiting for those who did not vote. See [[decision-function]].
- The admission electorate is the members of the 2nd degree and above (`ledger.electorate`); [[dormancy|dormant]] members keep the vote and are not counted in the quorum base.
