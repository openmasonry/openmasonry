# Clip: The Beanstalk governance attack (April 17, 2022)

- **URLs:**
  - https://medium.com/immunefi/hack-analysis-beanstalk-governance-attack-april-2022-f42788fc821e (Immunefi, technical analysis)
  - https://www.theregister.com/2022/04/18/beanstalk_loses_182m_flash_loan/ (The Register, news)
  - https://rekt.news/beanstalk-rekt (Rekt, incident write-up)
  - https://www.certik.com/blog/revisiting-beanstalk-farms-exploit (CertiK)
- **Authors:** Immunefi; The Register; Rekt News; CertiK (various staff authors)
- **Dates:** April 2022 and later retrospectives
- **Accessed:** November 2026

## Key facts (paraphrased)

- **When:** April 17, 2022, Beanstalk Farms (a stablecoin protocol on Ethereum governed by token votes).
- **How:** the attacker took a **flash loan** (borrowed and repaid within one transaction; reported as roughly $1 billion from Aave and other pools), converted it into governance tokens, obtained a **supermajority (≥ 2/3)** of voting power, and executed a malicious proposal (BIP-18) through an `emergencyCommit` function that allowed immediate execution once a supermajority was reached, bypassing the normal proposal lifecycle (a 24-hour wait from proposal creation had already elapsed).
- **Loss:** about **$182 million** in protocol value; the attacker kept roughly **$76–80 million**, much of it sent to a mixer.
- **Root causes cited:** governance weight purchasable instantly with borrowed capital; no execution delay between vote and effect; the exploited governance code had not been audited.
- **Lesson widely drawn:** where votes are proportional to tokens and tokens can be borrowed, governance can be **rented**; time locks and vote-escrow are partial mitigations.
