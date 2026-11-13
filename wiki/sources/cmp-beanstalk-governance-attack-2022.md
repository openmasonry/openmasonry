---
title: "Source: the Beanstalk governance attack (April 2022)"
type: source
tags: [dao, governance-attack, flash-loan, case-study]
sources:
  - raw/sources/cmp-beanstalk-governance-attack-2022.md
---

# Source: the Beanstalk governance attack (2022-04-17)

A real case showing that, when votes are proportional to tokens, **governance can be rented**.

## What happened

1. The attacker took a **flash loan** (borrowed and repaid within the same transaction) of about $1 billion.
2. They converted the loan into governance tokens and thereby held **more than 2/3 of the votes**.
3. They used the `emergencyCommit` function, which executed a proposal immediately once a supermajority existed, to pass BIP-18, which transferred the funds to them.
4. They repaid the loan. The protocol's loss was about **$182 million**, and the attacker kept about $76–80 million.

## Causes identified

Voting power that could be bought on the spot; no delay between approval and execution; unaudited governance code.

## Relation to OpenMasonry

In OpenMasonry there is nothing to borrow. Votes come from membership, and membership requires an [[waiting-period]] of at least 90 days to reach the Master degree, plus sponsors and a ballot. Every vote has a commit window (7 days) and a reveal window (3 days) ([[commit-reveal]]). And the Supreme Council can **suspend** an already approved decision for up to 30 days. See [[openmasonry-vs-token-daos]].
