---
title: "Custodian and Corrections"
type: concept
tags: [protocol, governance, custodian, corrections, objection, recovery]
sources:
  - src/openmasonry/ledger.py
  - src/openmasonry/govern.py
  - docs/whitepaper/SPEC.md
  - CONSTITUTION.md
  - docs/governance/CUSTODIAN.md
---

# Custodian and Corrections

A correction is how OpenMasonry repairs damage (a stolen key, a captured ballot, an attack) without rewriting anything: a new signed entry of a closed kind, made by a Custodian, that may undo, freeze or pause and never grants. The Custodian is the interim office that holds this power until the [[founder-sunset]].

This is a deliberate, bounded exception to the idea that no one holds special power, and the texts say so openly: as a member, no founder has any power another Master Builder lacks; until the Sunset a founder named Custodian (by the genesis, which at the founding ceremony names the first founder, or by a founder's claim) also holds that office, with the powers of the Corrections article and no others (Constitution Art. XII.2, Art. XVI). Master Builders can object to a correction from the first day; while few of them exist, the check rests mostly on publicity and the right to fork.

## The rule it serves
Landmark VI: "No record is ever rewritten or erased: a wrong is repaired only by a new public record, and a repair made by an office may undo, freeze or pause but never grant" (see [[eternal-landmarks-of-openmasonry]]). A key recovery is not such a repair: peers carry it out, not an office. The [[chained-ledger]] stays append-only; a correction is one more entry in it.

## Who the Custodian is
- The genesis names up to three Custodians: a name that is no member's, a custodian key, a separate revoke key, and the login of the founder who holds them (the Custodian's member). Both keys prove themselves in the genesis (`ledger._genesis`; SPEC §6.1, §4.8).
- **The founder's fallback** is the one other way a Custodian is named. While no custodian key is live, the Sunset has not come and fewer than three active Master Builders who are not founders exist, a founder may sign a `custodian_claim` with two new keys. It is public for 30 days, one objection of an active Master Builder who is not a founder voids it (`custodian_claim_object`), after which a new claim by any founder waits 30 days, and the founder applies it between day 30 and day 60 (`custodian_claim_apply`). A founder against whose key a removal ballot passed never claims again (`ledger._custodian_claim`, `ledger._claim_conditions`; SPEC §6.31 to §6.33; Constitution Art. XVI.10).
- No ballot or lot appoints a Custodian, and no entry gives an existing Custodian a new key. The office is no degree and has no vote.
- The custodian key signs corrections and the sign of life (`custodian_alive`), and nothing else; the revoke key has one power, to remove its own custodian key at once (`ledger._custodian_revoke`).
- On GitHub the same person administers the repository under the Custodian's charter, `docs/governance/CUSTODIAN.md`, a governed file.

## What a correction is
Every `correction` entry states one **act**, one **ground** and the SHA-256 of a **public reason** (`ledger._correction`; SPEC §6.19). The grounds are closed (`ledger.GROUNDS`): `key_compromised`, `protocol_defect`, `identity_fraud`, `attack_in_progress`, and `moderation`, which is the ground of a `note` and of no other act. A freeze states `key_compromised` and a halt `attack_in_progress`, and nothing else. Disagreement with an outcome is never a ground. The reason is a file archived as `ledger/reasons/<sha256>.md`; the tree check refuses a repository in which a reason is missing or altered (`govern.missing_reasons`, `govern.stray_reasons`).

**Immediate acts** take effect at their entry, end by themselves and need one custodian key (`ledger.ACT_DAYS`):

| Act | Effect | Lasts | Bounds |
|---|---|---|---|
| `freeze_key` | the member's key signs almost nothing (see below) | 30 days | ground `key_compromised` only; the same login again only 90 days after the start of every earlier freeze of it, unless other Custodians withdrew that freeze; frozen only while fewer keys are frozen than one tenth of the active members (a limit never below one; recoveries under way included), a limit that never holds back a key recovery (`ledger._act_freeze_key`, `ledger._freeze_room`) |
| `freeze_witness` | that witness signs nothing; members may still close ballots and draw lots | 30 days | the last unfrozen witness only on `attack_in_progress` (`ledger._act_freeze_witness`) |
| `stay` | one ballot takes no commit, reveal or close; the stayed time is taken out of its clock | 14 days | once in the life of a ballot, and only before its reveal window opens (`ledger._act_stay`) |
| `halt` | the ledger accepts only a short list of entries; the clocks of ballots, exams, lots, invitations and petitions stop (`State.effective`), except those of amendment ballots and of the ballot that removes a Custodian | 14 days | ground `attack_in_progress` only; at most once in 90 days, start to start (`ledger._act_halt`) |
| `hold_room` | the member is held out of the [[rooms]] | 14 days | never the Custodian's own member; a new hold on the same login only 90 days after the previous one began, unless other Custodians withdrew that hold (`ledger._act_hold_room`, read through `ledger.room_held`) |
| `note` | none: the public record of a moderation act done outside the ledger (hide, lock, block, unblock, limit, other), naming what it touched and the published rule it applied | n/a | ground `moderation` only; at most 10 per Custodian per UTC day; kept apart from the corrections, the state holding the newest 200 while every note stays in its entry (`ledger._act_note`) |

**Noticed acts** touch a ballot and take effect only after notice (`ledger.NOTICED_ACTS`; SPEC §6.19.7 to §6.19.9):

| Act | Effect once applied |
|---|---|
| `void_ballot` | an **open** ballot ends with no effect and no one is penalized: a petition stays as it was and an exam is free to support another ballot. It is posted only before the ballot's reveal window opens, and **while it is pending the ballot is paused**: no commit, reveal or close, and the pending time is taken out of the ballot's clock |
| `undo_ballot` | an **admission**, or an **advancement** to any degree but the 3rd, posted within 90 days of the ballot's close, is taken back by compare-and-swap: only if every fact the ballot set still stands exactly as the ballot left it, all of it or nothing. Nothing cascades. An undone admission leaves the record `voided`, which is not a sanction: the login may be invited again 90 days after the undo, and for those 90 days a sanction ballot may still expel the record for fraud. While a sanction ballot on the person is open, the undo of the admission is not applied |

A noticed act is public for **14 days of notice** (`NOTICE_DAYS`), is then applied by a further entry, `correction_apply`, within the next **7 days** (`APPLY_WINDOW_DAYS`), or never, and every condition is checked again on that day (`ledger._correction_apply`). A ballot is the target of each noticed act at most once, unless Custodians other than its poster withdrew the first. Where the genesis names more than one Custodian, a noticed act needs as many custodian keys as the genesis set (`correction_cosign`).

**Withdrawal.** The Custodian who posted a correction withdraws it alone; the others withdraw it only together, as many as a noticed act needs (`ledger._correction_withdraw`). A withdrawn immediate act ends at once; a freeze or a room hold withdrawn by Custodians other than its poster leaves no wait behind. A withdrawn noticed act is never applied. A note cannot be withdrawn.

## What a correction never does
- It never admits, advances, appoints, reinstates or sanctions anyone, and never changes a vote, a key, a governed file, a Landmark or the Corrections article.
- It never stays, voids or undoes an amendment ballot or the ballot that removes a Custodian (`ledger.STAY_EXEMPT`).
- **Recusal from the Sunset:** no Custodian stays, voids or undoes a ballot that adds a witness or advances a member to the 3rd degree, because the Sunset counts both and ends the Custodians' own keys (`ledger.sunset_ballot`).
- **Recusal from one's own member:** a Custodian never stays, voids or undoes a ballot whose subject, opener or sponsor is their own member, and never holds their own member out of the rooms (`ledger.party_to`).
- **Limits:** all Custodians together make at most five corrections in any 30 days, notes aside (`CORRECTIONS_PER_30_DAYS`), and each Custodian at most its share, `⌈5 / n⌉` with `n` the live custodian keys. The same act on the same target is not posted again within 90 days of objections voiding it.
- **What stays possible under a freeze or a halt:** departing (Landmark VII), replacing one's own key, stopping a recovery of one's own key, and taking part in an amendment ballot and in the ballot that removes a Custodian (`ledger.FREEZE_ALLOWED`, `ledger.HALT_ALLOWED`). A frozen member commits and reveals in every ballot: a freeze never changes who decides a ballot. A frozen member cannot object to a correction.

## How members stop a correction
- **Objection.** Any active Master Builder may object by a signed `correction_object` entry within 90 days, also during a halt. Three may not: the member of a Custodian who signed the correction, the member the correction is aimed at, and a member whose key is frozen. A correction is void for good at `max(1, ⌈E / 5⌉)` objections, where `E` counts the active Master Builders who are not dormant, other than the first two (`ledger.objections_needed`, `ledger._correction_object`): one fifth of the eligible Masters, rounded up, never fewer than one, so with five or fewer eligible one objection is enough. An immediate act ends at that moment; a noticed act voided before it is applied is never applied. An objection made after a noticed act was applied is recorded and reverses nothing: the remedy is then a new ballot, or removal. A note cannot be objected to.
- **Removal.** A ballot of kind `custodian` removes the key by a simple majority of the votes cast, with the ordinary quorum; the Custodian's member neither opens it nor votes. Its windows are fixed (7 days to commit, 3 to reveal), run through any halt, and no correction touches it (`ledger._open_custodian`, `ledger._close_custodian`; see [[decision-function]]).

## How the power ends
Silence (180 days without a `custodian_alive`), the Sunset condition (seven active Master Builders who are not founders and four witnesses, `ledger.sunset_reached`), revocation by the revoke key, removal by ballot, or the end of the term: seven years (2,555 days) from the genesis, or from the application of the claim that named the Custodian, whatever else happens (`State.custodian_end`; see [[founder-sunset]]). When a key ends, every act it had in force ends with it. **Where no custodian key is live, no correction exists**, until a founder's claim is applied; after the Sunset, or once three active Master Builders who are not founders exist, a new Custodian would exist only by amendment.

## Keys of members are not corrections
A member replaces their own key with a `rekey` entry signed by the current key, once in 30 days (`ledger._rekey`). A member whose key is lost or stolen recovers the membership through peers, not through the Custodian (`ledger._rekey_recover`, `ledger._rekey_cosign`, `ledger._rekey_oppose`, `ledger._rekey_object`, `ledger._rekey_recover_apply`; SPEC §6.26 to §6.30). **A recovery never needs a Custodian.** The member asks with a new key, and:

- **after a freeze** (a Custodian froze the old key): two Master Builders co-sign, and 21 days of notice run from the request;
- **open** (no freeze in force): three Master Builders co-sign; while an active Master Builder who is not a sponsor of the member exists, the co-signers are not all the member's sponsors; the old key is frozen and 30 days of notice run from the last co-signature; and the Master Builders may oppose it (`rekey_oppose`), one fifth of them voiding it;
- in either case, where fewer other active Master Builders exist than the number asked, all of them suffice, the only Master Builder needs none, and the notice is then 45 days; only the Masters who revealed a vote or reported within the last year, or reached the 3rd degree within it, are counted (one who answers nothing may still oppose);
- and when 30 days pass after the request with fewer co-signatures than it needs (counted as one at least where another Master Builder exists; without a freeze, only if its notice had not begun), those who have co-signed suffice (at least one where another Master Builder exists), and they may then all be sponsors; the notice is 45 days: after a freeze it starts on that thirtieth day and the old key stays frozen meanwhile; without one, it starts on that thirtieth day if the co-signatures then given are enough, and otherwise at the co-signature that makes them enough.

While the recovery is open, whoever holds the old key can stop it once (`rekey_object`); the request that follows, asked no sooner than 90 days after the stop, is **final**: the old key cannot stop it, and it needs three co-signers or as many as exist among the Masters who answered within the year. Where none answered, it needs none and applies after 45 days unless a Master opposes it: a thief who holds the member's GitHub account takes the membership in about 135 days even if the member watches. A login asks once in 90 days. A recovery lapses 60 days after its notice starts, or after the request where no notice began. A recovery reverses a departure when it is asked before the departure or within 30 days of it, or when it follows, within 150 days of that recovery's request or of the old key's stop of it, a recovery in time for that departure, whatever ended that recovery, so one follow-up may follow another; it does so when it completes, and a Council seat the departure ended comes back only into a vacancy. No correction replaces a key.

## Comparison and known limits
- Token DAOs often keep a comparable emergency power, a "security council" or guardian that acts behind a timelock; see [[openmasonry-vs-token-daos]].
- With one or two Master Builders there may be no one eligible to object, and with one, no one able to remove the key by ballot (SPEC §12).
- Notice periods count from entry times, and an entry can be backdated by up to the 6-hour clock tolerance; a head dated ahead of the clock is a capture alarm for every verifier (SPEC §9.7).
- Nothing in the protocol keeps personal data out of a note or a reason; the Constitution forbids it (Art. XIII.4), procedurally.
- The public Observatory (numbers computed from the ledger, `om observatory --out DIR`, and, beside the roll each room derives, the access the host actually grants and the room program's anonymous run log, as that program publishes them) has operated since the public launch, at https://openmasonry.github.io/openmasonry/; the Custodian's private Console (`docs/governance/CONSOLE.md`) is a working tool that decides nothing, and every binding output of it is published. The record of corrections is the ledger itself.

See also [[tyler]], [[byzantine-fault-tolerance]] and [[sybil-resistance]].
