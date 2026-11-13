---
title: "Founder's Sunset"
type: concept
tags: [protocol, governance, founder, custodian, decentralization]
sources:
  - src/openmasonry/ledger.py
  - src/openmasonry/canon.py
  - docs/whitepaper/SPEC.md
  - docs/whitepaper/WHITEPAPER.md
  - CONSTITUTION.md
  - docs/governance/CUSTODIAN.md
---

# Founder's Sunset

The Founder's Sunset is the moment, fixed by a rule of the ledger, at which the one power the founders hold beyond other members, the Custodian office, ends for good. The project aims to be something "which no person, including its founder, can own" (whitepaper §1.3), and it answers a risk of capture the tradition knows well: lifelong grand masterships, patronage networks and, in the extreme case, [[p2-lodge]].

**The honest sentence** (Constitution Art. XII.2): as a member, no founder has any power another Master Builder lacks, save one fallback, to take up the office of Custodian again while no custodian key is live (below). Until the Sunset a founder named Custodian (by the genesis, which at the founding ceremony names the first founder, or by a founder's claim) also holds that office, with the powers of the Corrections article (Art. XVI) and no others. The office and its acts are described in [[custodian-and-corrections]].

## Two hats, three keys
A founder who is also a Custodian acts under two names that the ledger keeps apart (SPEC §4.8, §6.1):

| Key | Signs | Where it is named |
|---|---|---|
| **Member key** | every ordinary act of the member: votes, invitations, works | the founder's record in `founders` of the genesis |
| **Custodian key** | corrections and the sign of life, and nothing else (`ledger.CUSTODIAN_TYPES`) | `custodians[].key` of the genesis, or the `key` of a founder's claim |
| **Revoke key** | one entry only, `custodian_revoke`, which removes its own custodian key at once | `custodians[].revoke_key` of the genesis, or the `revoke_key` of a founder's claim |

The genesis names at most three Custodians (`ledger.CUSTODIANS_MAX`), each with a name that is no member's, the two keys, the login of the founder who holds them (the Custodian's `member`) and a proof of possession by each key (`ledger._genesis`, `ledger.custodian_message`, `ledger.custodian_revoke_message`). A genesis may also name none. **Custodians exist only as the genesis or a founder's claim names them:** no ballot and no lot creates one, and nothing gives an existing one a new key. The office is no degree and carries no vote.

## Stages and code
1. **Genesis.** The founder and up to six co-founders become **3rd-degree Master Builders, never more**. There is no "Grand Master" chair to inherit. `ledger._genesis` requires 1 to 7 founders (`canon.FOUNDING_MASTERS`), distinct logins, distinct GitHub accounts (`github_id`), valid keys and the first founder's signature. Each founder receives a record with `founder = true`: as a member, that mark is the honorary title of "Founding Architect" and never a power. The genesis also pins the six governed hashes (the canon, the Landmarks, the Constitution, the Custodian's and the rooms' charters, and `@protocol`).
2. **Founding Phase** (fewer than 7 active Masters, `State.founding_phase`). It relaxes the sponsor rule so that the fraternity can grow from a single Master: the required number of sponsors is `max(1, min(2, active Masters))` instead of 2, and one once a petition has been live 30 days, so that a Master who never answers holds no door shut; that waiver also holds after the phase while fewer than 7 Masters are present, neither dormant nor silent (`ledger.sponsors_required`, checked in `ledger._open_admission`; every other Master still votes on the admission). In any phase, an exam whose last rung of examiners holds fewer than `k` members proceeds with those it holds (`ledger._exam_open`).

   In any phase, when the candidate is a founder, `ledger.examiner_pool` first tries every rung of its ladder **without** the founding cohort: founders do not examine one another while enough other members exist. The Founding Phase is a condition, not an era: it resumes if Masters go dormant or leave and fewer than 7 remain active (see [[dormancy]]).
3. **The Sunset.** `ledger.sunset_reached` holds when the ledger shows **7 active Master Builders who are not founders** (`SUNSET_MASTERS`) **and 4 witnesses** (`SUNSET_WITNESSES`). It is evaluated after every accepted entry; the first time it holds, the time is stored in the state and never changed again, whatever happens to the Masters and the witnesses afterwards (SPEC §7.9). From that entry on, no custodian key signs anything, whether the genesis or a founder's claim named it (`State.custodian_end`), and no founder's claim is accepted. "Not a founder" is the `founder` mark of the record, and the mark follows the person (the same GitHub account) through a new admission.
4. **Administration.** At the Sunset, the administration of the canonical repository and of the rooms passes to owners who are the witness operators (Constitution Art. XII.3). This step is procedural: the verifier ends the keys; people hand over the hosting.

The Founding Phase and the Sunset are different thresholds. Seven active Masters end the Founding Phase, founders included. The Sunset counts only Masters who are not founders, and it also needs four witnesses (added by `witness` ballot, `ledger._open_witness` and `ledger._close_witness`; see [[byzantine-fault-tolerance]]).

## Five ways a key ends
A custodian key signs nothing, for good, from the first of these (Constitution Art. XVI.11; SPEC §4.8, §7.9):

| End | Rule | Code |
|---|---|---|
| **Silence** | 180 days without a signed sign of life (`custodian_alive`); a correction is not a sign of life | `CUSTODIAN_SILENCE_DAYS`, `ledger._custodian_alive` |
| **The Sunset** | the condition above | `ledger.sunset_reached` |
| **Revocation** | the Custodian's own revoke key removes the custodian key at once | `ledger._custodian_revoke` |
| **Removal** | a ballot of kind `custodian`, opened by any Master Builder except the Custodian's member, decided by a simple majority of the votes cast with the ordinary quorum; that member neither opens it nor votes | `ledger._open_custodian`, `ledger._close_custodian`, `ledger.decide` |
| **The term** | seven years (2,555 days) from the genesis, or from the application of the claim that named the Custodian; no sign of life and no halt moves it | `CUSTODIAN_TERM_DAYS`, `State.custodian_end` |

When a key ends, every act it had in force ends with it and none of its pending acts is ever applied. A lapse is not an entry: it follows from stored facts and the time asked about, so every verifier computes the same answer. On a ledger whose genesis named no Custodian, a custodian entry is refused with "no custodian exists, so no correction exists"; a key that lapsed, was revoked or was removed "signs nothing", and nothing makes it live again (`ledger._signer`).

## The founder's fallback
While no custodian key is live, the Sunset has not come and fewer than three active Master Builders who are not founders exist, a founder may take up the office again with two new keys (`custodian_claim`, `om claim-custodian`). The claim is public for 30 days, one objection of an active Master Builder who is not a founder voids it (`om object-claim`), after which a new claim by any founder waits 30 days, and the founder applies it between day 30 and day 60 (`om apply-claim`). The new key is bound exactly as one of the genesis, with its own seven-year term. A founder against whose key a removal ballot passed never claims again (`ledger._custodian_claim`, `ledger._claim_conditions`; Constitution Art. XVI.10).

## After the Sunset
The intended path is a college of Custodians drawn by lot among the Master Builders, for a term. It is future work: it exists only if the members add it by amendment (Constitution Art. XVI.14). Until they do, there is no correction of any kind. The members lose nothing they need: the recovery of a lost key never needs a Custodian (an open recovery is co-signed by Master Builders and runs 30 days of notice, or 45 when fewer co-signers exist than it asks; see [[custodian-and-corrections]]), and replacing a key one still holds (`rekey`) needs no one.

## What the founder can do now
- **As a member:** exactly what any Master Builder can. One vote, a budget of four sponsorships, no special seat.
- **As Custodian:** the corrections of Constitution Art. XVI, each a signed public entry with a closed ground and a public reason: freeze a member's key or a witness key for 30 days, stay one ballot for 14 days before its reveal window opens, halt the ledger for 14 days under attack, hold a member out of the rooms for 14 days, record a moderation note (ground `moderation`), and, after 14 days of notice, void an open ballot (posted before its reveal window opens) or undo an admission or an advancement closed within 90 days. No correction touches a ballot that adds a witness or advances a member to the 3rd degree. Master Builders stop a correction by objection (see [[custodian-and-corrections]]).
- **As administrator of the repository:** settings, code-owner review of changes outside the ledger, moderation of conversation and security reports, under the Custodian's charter (`docs/governance/CUSTODIAN.md`).

## What the founder cannot do, even now
- Forge entries, because that would need the other members' keys.
- Rewrite or delete history: the chain, the witnesses and the anchors expose it (see [[chained-ledger]] and [[opentimestamps]]), and Landmark VI forbids it.
- Admit, advance, appoint, reinstate or sanction anyone by correction, or change a vote, a key, a governed file or a Landmark. A correction may undo, freeze or pause; it never grants.
- Touch an amendment ballot, or the ballot that removes a Custodian: neither is ever stayed, voided or undone, and the removal ballot runs through any halt.
- Keep a member from departing, from replacing their own key, or from taking part in that removal.
- Correct a ballot in which the Custodian's own member is the subject, the opener or a sponsor (recusal, `ledger.party_to`).
- Skip a [[waiting-period]] or reach the 33rd degree without the lot (see [[verifiable-lottery]]).
- Sign on someone's behalf: the member CLI only drafts acts, and each person approves their own in a system dialog (`om approve`).

## Known limits
- **Before many members can check it.** Any Master Builder other than the Custodian's member may object to a correction from the first day, but while few exist the check rests mostly on publicity and the right to fork. While the Custodian's member is the only Master Builder, no one can object to a correction or remove the Custodian; where no Master who is not a founder exists, a founder's claim of the office is one founder's to take up (SPEC §6.31, §12).
- **Trust in the genesis.** The genesis is the one act no protocol can verify. Seven "puppet" founders could end the Founding Phase on day one, though founders never count toward the Sunset. The defense is publicity: every founding login and key can be checked at `github.com/<login>.keys`, and the community can reject a genesis it does not trust by forking before it grows (whitepaper §9.2).
- **Hosting.** The repository administrator can deny service on GitHub. The remedy is to carry on in a mirror: the canonical location is the one the ratified `src/openmasonry/network.toml` names, and the runbooks are in `docs/operations/RECOVERY.md`.

See [[eternal-landmarks-of-openmasonry]] (V, VI, VII), [[custodian-and-corrections]] and [[tyler]].
