# Patron Seals: funding the Open Craft without selling it

**Whitepaper, version 0.1 · November 2026**
**Status:** proposal for v0.7 (see [ROADMAP.md](../../ROADMAP.md)). Nothing here is active until approved by amendment ballot and preceded by a published legal opinion.
**License:** CC BY-SA 4.0 · **Not legal, tax or investment advice.**

---

## Abstract

OpenMasonry needs money for a few concrete things: witness servers, security audits, translations, and above all fair payment for the **masterworks** members build for the commons. It must raise that money without violating its third Landmark, *Nothing for Sale*: no token, coin, share or fee may buy membership, degree, vote, office or access.

This paper proposes **Patron Seals**: non-transferable recognition records, written as signed entries in the OpenMasonry ledger itself, given to anyone who donates to a public, fiat-first treasury. A Seal is a thank-you and a public record of support. It cannot be sold (the ledger has no transfer operation), it has no price, and it confers **no right of any kind inside the protocol**: the verifier is forbidden from using it as an input to any electorate, eligibility or Light computation. The treasury pays for infrastructure and gives **retroactive grants** to works that already proved useful. A small panel of Master Builders drawn by lot decides the grants against a rubric published in advance. Donors never allocate. Accounts are public every quarter.

We also explain why we reject a **tradable** token, even one restricted to funding: it would put a price on the fraternity's attention, attract speculation, and very likely be a security or a regulated crypto-asset under the laws of many jurisdictions (for example, the Howey test applied in the United States, or the MiCA regulation of the European Union).

---

## 1. The problem

| Need | Yearly order of magnitude | Today |
|---|---|---|
| Witness nodes (4+ independent VPS) | low | volunteers |
| External audits (`om`, encrypted ballots) | high, one-off | none |
| Retroactive grants for masterworks | variable | none |
| Translations of the curriculum and wiki | medium | volunteers |
| Relief fund (18°, Chapter of the Rose) | variable | none |

Volunteer work alone tends to burn out maintainers. This is exactly the problem the 22° (Knight of the Royal Axe, *Dignity of Labor*) studies. Fraternities historically solved it with dues. OpenMasonry has no dues, by design.

## 2. Why not a tradable token

| Question | Tradable funding token | Patron Seal |
|---|---|---|
| Can it buy degree, vote or office? | must not, but its price invites pressure to make it so | impossible: the verifier would forbid using it as an input |
| Does it have a market price? | yes, which turns members into investors | no; the ledger has no transfer operation |
| Expectation of profit (the test of securities and crypto-asset laws)? | likely yes: bought hoping it appreciates through others' efforts | no: a donation receipt with no resale |
| Speculation, pump-and-dump, wash trading? | inevitable | impossible |
| Raises a lot quickly? | possibly | less, but sustainably |
| Fits Landmark III? | at best in letter, never in spirit | yes |

**Conclusion.** A tradable token is the one funding instrument most likely to corrupt the institution it funds. OpenMasonry will not launch one. Any future proposal to do so would conflict with Landmark III, which cannot be amended. It would require a fork.

## 3. What a Patron Seal is

- **A ledger entry, not a chain token.** A `seal` entry (schema governed like the canon) is signed by a treasurer key after a donation clears: `{"patron": <pseudonym or login>, "year": 2027, "receipt_sha256": <hash of the fiscal host's receipt>}`. It is non-transferable by construction, because the ledger binds it to a name and has no transfer operation. The same rules, the same verifier and the same anchors protect it as everything else.
- **No rights, ever (normative once adopted).** A `seal` entry can never be an input to the functions that compute electorates, eligibility, exams, sponsorship, Light, offices or grants. The verifier is to enforce this: its handler records the seal and touches nothing else, and a conformance test fails if any other function reads it. This is the lesson of Aragon (token holders pushing to liquidate the treasury, 2023) and Moloch (rage-quit turns membership into a claim on funds): any economic right attached to a badge becomes the badge's purpose.
- **One design per year, no tiers by amount.** "Patron of the Open Craft, 2027". The amount never appears in the entry, only the receipt hash, so the ledger cannot rank donors.
- **Pseudonymous and withdrawable.** A patron may use a pseudonym and may ask for a `seal_burn` entry at any time, which marks the Seal as withdrawn. The original entry stays in the ledger, so a patron who wants no lasting link uses a pseudonym.
- **Optional mirrors.** If the community wants wallet-visible badges, a read-only mirror can be issued as an off-chain EAS attestation or an ERC-5192 locked NFT (holder-burnable, ERC-5484 semantics). Mirrors are cosmetic: the protocol never reads any chain.

## 4. The treasury

```
   donors ──► fiscal host / non-profit (fiat: bank transfer, card) ──► payments (infrastructure, audits, grants, relief)
                       │                                                    │
                       └── each donation and each payout ──► signed ledger entry with the receipt's hash
                                                             (seal · treasury_out), quarterly report by 31°
```

- **Fiat first.** The first treasury holds no crypto. Holding or converting virtual assets would bring virtual-asset service-provider or money-transmitter licensing, which many jurisdictions require, and custody risk into a project that needs neither. Donations go to a fiscal host (such as an Open Source Collective) or a non-profit association whose statutes copy Landmarks II and III.
- **Signers.** Treasurer keys (for `seal` and `treasury_out` entries, and for the host's bank) belong to three treasurers elected for one year by ballot among Master Builders, renewable once. The founder can be one only if elected.
- **Who decides spending.**
  1. *Infrastructure* (witnesses, domains, CI) up to a yearly budget approved by an amendment ballot.
  2. *Retroactive grants*: each quarter a **grants panel of 7 Master Builders drawn by lot** scores nominated works against a rubric published before the quarter starts. Only verifiable deliverables count: merged PRs, ledger entries, published masterworks. Authors, their sponsors and their sponsorees recuse. All Masters then ratify the panel's allocation under the amendment rule (two-thirds, one-third turnout). There is no quadratic funding and no donor voting; the research behind this choice is in [PRIOR-ART.md](../research/PRIOR-ART.md).
  3. *Audits*: approved case by case by ballot.
  4. *Relief*: administered by a Knight of the Rose (18°) under a published policy; recipients stay private (aggregated in reports).
- **Never.** Paying for votes, exams or degrees; paying examiners for verdicts; paying anyone for a governance role. Grants pay for *works*, never for *positions*.
- **Transparency.** The host's books are public; every payout is a ledger entry with a receipt hash; an Inspector Inquisitor (31°) audits the year and publishes the report with a dissent section.

## 5. Why retroactive grants

Paying *after* a work proved useful (the model popularized by Optimism's Retroactive Public Goods Funding, whose later rounds also showed the costs of large voter-allocated pools) rewards results instead of promises, and fits the curriculum: a masterwork already passed an examination by members drawn by lot. Grants therefore follow a signal the fraternity already produces, without creating a new one that money could buy.

## 6. Firewall rules (normative once adopted)

1. `seal` and `treasury_out` entries are never inputs to electorates, eligibility, exams, sponsorship budgets, Light, offices or grants; the verifier is to enforce it and a conformance test to prove it.
2. The protocol, the Tyler and every witness never read any blockchain or wallet.
3. No ballot, exam, sponsorship or office may be conditioned on, or reference, a donation. Citing one is to be added to the grave offenses of Constitution Art. X.2 when these rules are adopted.
4. Patrons who are members recuse from grants to themselves, their sponsors and their sponsorees.
5. Seals are never shown on member profiles in `om` or in the Observatory.
6. Changing rules 1–5 requires two amendment ballots 90 days apart; rule 1 cannot be abolished without violating Landmark III.

## 7. Legal analysis (summary; a formal opinion is a precondition)

- **Securities law.** Tests of an investment contract (the Howey test of United States law is the best-known example) look for money invested in a common enterprise with an expectation of profit from others' efforts. A Seal is a donation receipt with no resale, no return and no claim, so those elements are absent. Non-transferability helps but does not settle the question alone; the absence of any return language matters as much. Guidance on digital assets changes often, and counsel must confirm the position at the time of adoption.
- **Crypto-asset law.** Regimes that classify crypto-assets by function (the MiCA regulation of the European Union is one) leave financial instruments to securities law. A non-transferable record of a fiat donation, with no remuneration or participation right, falls outside both by our reading. Because the first treasury holds no virtual assets, service-provider licensing should not apply.
- **Tax.** The treatment of donations varies from one jurisdiction to another.
- **Data protection.** The ledger stores a pseudonym or login and a receipt hash, never amounts or bank data. Patrons can burn their Seal.

## 8. Implementation sketch

| Piece | Where | Version |
|---|---|---|
| `seal`, `seal_burn`, `treasury_out` entry types; treasurer keys added by a `treasurer` ballot | the reference verifier (`src/openmasonry/ledger.py`), and the Go core planned for v0.2 | v0.7 |
| conformance test: no protocol function reads seal state | `tests/vectors/` | v0.7 |
| `om seal show`, `om treasury report` | `om` | v0.7 |
| fiscal host or association, public books | outside the repo | before v0.7 |
| optional EAS / ERC-5192 mirror | separate repo, read-only | only if requested by ballot |

## 9. Risks

| Risk | Mitigation |
|---|---|
| Seals perceived as "paying to belong" | no tiers, no display in the protocol, firewall rules, a published essay explaining the separation |
| Capture of the treasury | elected treasurers, grants panel drawn by lot, rubric published in advance, yearly 31° audit, recusal |
| Regulatory change | legal opinion before launch; ability to pause donations without affecting the protocol |
| Large donors gaining soft influence | donors never allocate; amounts never in the ledger; citing a donation is to be a grave offense (rule 3) |
| Treasurer key misuse | three elected treasurers, every payout a signed public entry with a receipt hash, yearly 31° audit, recall by sanction ballot |

## 10. Decision requested

Adopt Patron Seals (ledger entries, fiat-first) as the only funding-recognition instrument of OpenMasonry, under the firewall rules above, starting no earlier than v0.7 and only after (a) the legal entity exists, (b) a legal opinion is published and (c) an amendment ballot approves the treasury rules.
