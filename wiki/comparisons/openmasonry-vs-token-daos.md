---
title: "OpenMasonry vs. token DAOs"
type: comparison
tags: [comparison, dao, token-voting, governance, sybil, plutocracy]
sources:
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/cmp-buterin-coin-voting.md
  - raw/sources/cmp-feichtinger-2023-dao-governance.md
  - raw/sources/cmp-beanstalk-governance-attack-2022.md
  - CONSTITUTION.md
---

# OpenMasonry vs. token DAOs

A **DAO** (decentralized autonomous organization) usually decides by **token-weighted voting**: more tokens mean more votes. OpenMasonry is also autonomous and verifiable, but it **has no token**. The right to act comes from membership, and membership comes from the ledger (Whitepaper §4.3).

## The known problems of token voting

| Problem | Evidence | How OpenMasonry responds |
|---|---|---|
| **Plutocracy**: those with more capital decide | In 17 of 21 DAOs studied, fewer than 10 participants hold the majority of voting power ([[cmp-feichtinger-2023-dao-governance]]) | One person, one vote (Landmark IV). Degree carries no voting weight |
| **Apathy and low turnout** | For a small holder, voting is not worth it ([[cmp-buterin-coin-voting]]). Real participation is low ([[cmp-feichtinger-2023-dao-governance]]) | Voting is free (one commit). [[dormancy]] removes inactive members from the denominator, which avoids "death by quorum" |
| **Vote buying and renting** | The vote can be separated from economic risk by lending or wrappers ([[cmp-buterin-coin-voting]]) | There is nothing to buy or lend. The vote belongs to the person, tied to a key the member registered and only the member can replace. The coercion that remains is addressed in v0.3 (encrypted ballots) |
| **Flash governance attack** | Beanstalk, 2022: a flash loan gave over 2/3 of the votes and a loss of ~$182 million ([[cmp-beanstalk-governance-attack-2022]]) | Voting requires having been a member for some time (≥ 90 days to Master). Every vote has 7+3-day windows. The Supreme Council can suspend a decision for up to 30 days |
| **Incentive toward price, not mission** | Holders favor token value ([[cmp-buterin-coin-voting]]) | No token, no speculation. Status comes from work ([[masterwork]]) |
| **Cost of voting** | Delegating and voting on-chain cost millions in some DAOs ([[cmp-feichtinger-2023-dao-governance]]) | Git is the ledger. Bitcoin is used only as a clock, via OpenTimestamps, at no cost to the member |
| **Regulatory risk** | Financialized tokens expose a DAO to securities law | No money and no token (§4.3) |

## The price OpenMasonry pays

- **Identity and Sybil.** Without a token, the risk shifts to creating fake identities. The answer is four barriers: Master sponsors, a budget of 4 sponsorships (admitted in the last 365 days, plus still-pending petitions and live invitations), the one-fifth rule and the waiting period ([[sybil-resistance]]). This is the same family of solutions Buterin calls proof of personhood and proof of participation.
- **Slowness.** A ballot takes at least seven days and a quarter, and about ten and a half with the full reveal window. This is intentional.
- **Votes exposed after the reveal.** In v0.1 every vote becomes public after the reveal ([[commit-reveal]]). Encrypted ballots, in the style of MACI or of a threshold tally, are planned (v0.3).
- **No multi-witness finality yet.** Checkpoints are recorded, not counted, so there is no Byzantine fault tolerance yet.
- **An emergency power held by one office.** Until the [[founder-sunset]], the Custodian may sign corrections: freeze a key or a witness, stay a ballot, halt the ledger under attack, hold a member out of the rooms and, after 14 days of notice, void an open ballot or undo an admission or an advancement. A correction is a public entry with a closed ground and a public reason; it may undo, freeze or pause and never grants, and it never touches an amendment ballot, the ballot that removes the Custodian, or a ballot that adds a witness or advances a member to the 3rd degree. Master Builders stop one by objection (one fifth of the eligible Masters, never fewer than one) and remove the Custodian by simple majority. While few Master Builders exist, corrections are checked mostly by publicity and the right to fork ([[custodian-and-corrections]]).

## The same problem, two answers

Many token DAOs keep a comparable emergency power: a "security council" or guardian, often a multi-signature group, that can pause the system or block a proposal behind a timelock while token holders keep the last word. OpenMasonry's Custodian belongs to the same family of designs, with these differences: its acts are a closed list that cannot move anything of value or grant any status, its noticed acts wait 14 days in public, members stop it by signed objection, not by a token vote, and the office ends by a rule of the ledger. The Beanstalk attack went through an emergency path that executed a proposal at once ([[cmp-beanstalk-governance-attack-2022]]); a correction executes no proposal and cannot pass, change or apply an amendment.

## In one sentence

A token DAO asks "how much do you hold?". OpenMasonry asks "what have you built, and who vouches for it?".

See also: [[decision-function]] · [[verifiable-lottery]] · [[light-score]] · [[chained-ledger]]
