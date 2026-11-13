---
title: "The member's path: from invitation to the 33°"
type: synthesis
tags: [member-journey, petition, ballot, exam, ledger, process]
sources:
  - docs/whitepaper/WHITEPAPER.md
  - docs/whitepaper/SPEC.md
  - CONSTITUTION.md
  - canon/degrees.toml
---

# The member's path: from invitation to the 33°

This is the complete journey of a person through OpenMasonry, step by step, from an application and an invitation to the 33rd degree. For each step, the page lists **which ledger entry types** are recorded. The types are defined in Appendix A of the whitepaper, specified rule by rule in `docs/whitepaper/SPEC.md` and described in [[chained-ledger]]. Every entry is a JSON object signed with the SSH key of the member who acts and hash-chained to the previous entry. The [[tyler]] (the CI automation) validates every new entry by replaying the ledger before it is merged.

## Diagram

```
  ┌────────────────┐    invite     ┌───────────────┐   petition    ┌──────────────┐
  │ 0. Preparation │──────────────►│ 1. Invitation │──────────────►│ 2. Petition  │
  │ GitHub account │  (signed by a │ login + id;   │  (signed by   │ key + hash   │
  │ + SSH key;     │   Master 3°,  │ lapses after  │   the invited │ of the       │
  │ application in │   the first   │ 30 days       │   candidate)  │ Declaration  │
  │ a public issue │   sponsor)    └───────────────┘               └───────┬──────┘
  └────────────────┘                                                       │ vouch (second sponsor)
                                                                           ▼
                                                              ┌──────────────────────────┐
                                                              │ 3. Sponsors (Masters 3°) │
                                                              │ budget: 4 at a time      │
                                                              └────────────┬─────────────┘
                                                                           │ ballot_open (admission)
                                                                           ▼
                                                              ┌──────────────────────────────┐
                                                              │ 4. Admission ballot          │
                                                              │ electors: members 2°+        │
                                                              │ commit 7d                    │
                                                              │ gap of 6¼ hours              │
                                                              │ reveal 3d (or until all have │
                                                              │ revealed)                    │
                                                              │ ballot_commit / ballot_reveal│
                                                              └────────────┬─────────────────┘
                                                                           │ ballot_close: D(Y,B,N)
      lapsed (no quorum: no penalty, open again or re-run once) ◄──┤
                                         rejected (≥ 1/5 black balls) ◄────┤
                                                                           ▼ approved
  ┌─────────────────────────────────────────────────────────────────────────────────────────┐
  │ 5. 1° Apprentice ──► advancement cycle, repeated from the 2° to the 32°:                │
  │                                                                                         │
  │    waiting period W(d) ──► masterwork ─────────► exam_open ─► exam_draw ─► report ×k ─► │
  │    (time in degree)     (work, earns Light)      (draw with     (pass/fail,             │
  │                                                  beacon)        majority)               │
  │         ──► ballot_open (advancement) ──► commit/reveal ──► ballot_close ──► degree d   │
  │             electors: degree ≥ d                                                        │
  └───────────────────────────────────────┬─────────────────────────────────────────────────┘
                                          │ 32° + 730 days + never held a seat
                                          ▼
                              ┌────────────────────────────────┐
                              │ 6. council_call + council_draw │──► 33° Sovereign Guardian
                              │ 33 seats · 3 years · once      │    (the title stays; the power ends)
                              └────────────────────────────────┘

  Throughout: work (activity and Light) · witness (checkpoints) · dormancy after 365 days without activity · free exit (depart)
```

## Step by step

### 0. Preparation and application (off the ledger)
- The person has a GitHub account and a public SSH authentication key. GitHub publishes keys at `github.com/<login>.keys`. `om onboard` checks the computer, the GitHub login and the key, and says the next step.
- They read the [[landmarks]] and the Declaration (Whitepaper §3.1).
- **Application:** they introduce themselves, in their own words, in a public issue of the repository: `om apply` publishes the text after the person approves it in a dialog, or they use the issue form "Application" (label `application`). It asks for no personal data, it is not a ledger entry and it gives no right. An application that no invitation follows within 60 days is closed, with a courteous notice of how to apply again. Any adult may apply: 18 years old, or the age of majority where they live, whichever is higher.
- **Cost:** zero. There is no fee, no token and nothing to buy (Landmark III).

### 1. Invitation: the `invite` entry
- An active Master (3°+) who is ready to answer for the person signs an `invite` entry with the fields `login` and `github_id` (the numeric id of the GitHub account, a positive integer), with `bin/om invite <login>`. By that act the inviter is the candidate's **first sponsor** and answers for their identity, adulthood and good faith, not for their opinions (Constitution Art. IV.3).
- Rules (`ledger._invite`): the conditions of a vouch apply (no sponsorship ban, room in the budget); a Master cannot invite themselves; there is one live invitation per login, without regard to case; the login must not be held by a member who may not return yet (someone who departed, or whose admission was undone, may be invited again after 90 days, someone expelled after 365, and none while a sanction ballot on that record is open), a witness, a Custodian, a pending petition, another live invitation or the name of an open witness ballot; and the GitHub account (its numeric id) must be held by no one else: one account, one member.
- The invitation **lapses after 30 days** without a petition, by the passing of time alone; it still counts against the inviter's budget for 90 days after it lapsed. A login that names a custodian, or that a pending claim of the Custodian office names, cannot be invited.
- No outsider writes to the ledger uninvited: a person who is not a member signs exactly one entry, a petition under a live invitation, from the invited GitHub account.

### 2. Petition: the `petition` entry
- Under a live invitation for exactly that login (same spelling), the candidate signs, with their own key, a `petition` entry (`bin/om join`) with the fields `key` (the bare key, without a comment: `ssh-ed25519 <base64>`, or `sk-ssh-ed25519@openssh.com <base64>` for a key held by a hardware token) and `declaration_sha256` (the SHA-256 of the Declaration text, printed by `openmasonry declaration`).
- The key is **pinned** at that moment. If someone later takes over the GitHub account, they cannot swap the key without it being noticed.
- The petition takes the place of the invitation: the inviter is already its sponsor, and the petition carries the invitation's `github_id`, which the admitted member keeps.
- Rules (`ledger._petition_checks`): the login follows GitHub's rules and must not collide, case-insensitively, with another member or witness; the candidate must not already be a member (the wait of a departed or expelled member is checked again here); only one live petition at a time.
- The petition **lapses after 180 days** if not admitted, which frees its sponsors. The petition, the invitation and the exam clocks do not run while the ledger is halted.

### 3. Sponsorship: the `vouch` entry
- Admission needs two sponsors, as proposer and seconder. The inviter is the first; a second Master (3°+) signs a `vouch` (`bin/om vouch <login>`). A `vouch` from the inviter is not needed and is refused.
- Each Master has a budget of **4 sponsorships**: it counts those admitted in the last 365 days **plus** the live petitions they sponsor and their own live invitations. This is one of the four barriers of [[sybil-resistance]].
- A Master whose sponsored candidate is expelled for fraud (`expel_for_fraud`, up to 730 days after initiation) cannot invite or sponsor for 730 days.
- **Founding Phase:** while there are fewer than 7 active Masters, `max(1, min(2, Masters))` sponsors suffice: with a single Master, the inviter alone. And once a petition has been live 30 days, the inviter alone suffices, so a second Master who never answers holds no door shut; every Master still votes on the admission ([[founder-sunset]]). The 30-day waiver also holds after the Founding Phase while fewer than 7 Masters are present (neither dormant nor silent).

### 4. Admission ballot: `ballot_open`, `ballot_commit`, `ballot_reveal`, `ballot_close`
- **One of the sponsors** opens the ballot with `kind: admission`. The verifier checks that the petition is live and has the required sponsors, and freezes into the ballot the key and the sponsors being voted on. Only one ballot may be open per candidate.
- Members of 2°+ vote; if nobody of the 2° or higher is present, everyone votes. [[dormancy|Dormant]] and silent members keep the vote and are not counted in the quorum base (nor as present for that fallback).
- [[commit-reveal]]: during the commit window (7 days) only commitments (hashes) appear. The reveal window (3 days) opens after a gap of 6 hours and 15 minutes following the end of the commit window (the clock tolerance plus 15 minutes). In it each elector reveals their vote and salt (32 to 64 lowercase hexadecimal characters, drawn by `om vote`). Anyone who does not reveal counts for nothing. Only an amendment ballot chooses other windows. The ballot can be closed at the end of the reveal window, or as soon as every elector has revealed.
- `ballot_close` applies the [[decision-function]]. If the votes miss the quorum Q(N), the ballot **lapses**: nothing is lost, the petition stays live, and a sponsor opens another ballot or re-runs it once within 30 days, without waiting for those who did not vote. Otherwise **one fifth of black balls rejects** ([[ballot-and-blackball]]). If approved, the candidate becomes a **1° Apprentice**; if rejected, the petition is discarded and the candidate needs a new invitation.

### 5. Degree advancement (from the 2° to the 32°): `work`, `exam_open`, `exam_draw`, `exam_report`, `ballot_*`
To move from degree *d−1* to degree *d*, the order is always this:

1. **[[waiting-period]]:** serve the minimum time in the current degree (see the table in [[catalog-of-the-33-degrees]]).
2. **[[masterwork]]:** publish the work required by the degree and record it with a `work` entry (the `ref` field pointing to the PR, commit or document). Each `work` also raises the [[light-score]].
3. **`exam_open`:** **only the candidate themselves** opens the exam for the next degree, giving `work_ref` and `beacon_round`, which must be exactly the drand round about 8 hours in the future (`drand_round(now) + 9600`). Nobody knows that random number yet. At that moment the examiner pool (active members of degree ≥ *d*, excluding the candidate and, where possible, the sponsors; then Master Builders; see [[verifiable-lottery]]) and the number `k` are **frozen**. Where no rung of that ladder holds `k` members, everyone any rung holds is drawn together and `k` is lowered to them, in any phase. An exam cannot be reopened while it is pending; after a failure, only 90 days after the failed exam was opened; after an exam that lapsed or timed out, at once.
3b. **`exam_draw`:** once the round has happened, a witness (or any member) publishes its randomness and the examiners (2, 3, 5 or 7, depending on the degree) are **drawn** from the frozen pool ([[verifiable-lottery]]). The draw must be made within 7 days of the round; otherwise the exam times out without penalty and the candidate opens a new one. The Tyler checks each beacon against the public drand network (`verify --online`).
4. **`exam_report`:** each drawn examiner records `pass` or `fail`, only once, within 60 days of the opening. The exam passes by a strict majority of `pass`, and fails if half or more give `fail`. If 60 days pass without either majority, the exam **times out with no penalty**: the candidate may open a new one at once, and the examiners who stayed silent are left out of the next pool whenever anyone else can be drawn, and that next lot seats everyone any rung holds. An examiner with a conflict recuses (`exam_recuse`), and the next in the lot's order takes the seat; when nobody is left to take it, the exam lapses without penalty.
5. **Advancement ballot:** `ballot_open` with `kind: advancement`. The verifier requires a completed waiting period and a passed exam not yet used (each passed exam supports a single advancement ballot). It is opened by the candidate or by an examiner of the passed exam. Members of degree ≥ *d* vote, excluding the candidate; when fewer than 3 of them are present (a silent member is not present), the advancement is decided on the Masters' rung, and every member who had the vote on the first rung keeps it. Then come `ballot_commit`, `ballot_reveal` and `ballot_close`, under the same rule as admission. A ballot that lapses gives the exam back, passed and unused.

**The shortest path.** From admission, the 2nd degree takes at least 30 days of waiting, 8 hours to the beacon, then 7 days to commit and the gap of 6 hours 15 minutes: **37 d 14 h 15 m** if every elector reveals at the first second of the reveal window and the ballot closes at once, **40 d 14 h 15 m** with the full reveal window. The 3rd degree adds 60 days of waiting and the same exam and ballot: **105 d 4 h 30 m** from admission at the earliest, **111 d 4 h 30 m** with full windows. These are lower bounds on the clock alone, before any study.

Advancement is **one degree at a time**, up to the 32°. The practical milestones are these:

- **3°:** sponsor, examine, vote on amendments, be elected.
- **6°:** operate a witness node, once a witness ballot adds its key (the node then signs `witness` checkpoints; a witness is a key that a ballot may remove at any time, not an office).
- **7°:** sit on sanction juries.
- **30°:** join the Watch.
- **31°:** audit and sit on the Court of Review.

### 6. The 33°: `council_call` and `council_draw`
- The 33° is **never requested**. When there are vacancies, **any active member** records a `council_call` with `beacon_round = drand_round(now) + 9600` (about 8 hours in the future). Witnesses do not call the draw; without that `council_call`, nothing is drawn.
- The `council_call` **freezes the pool**: active 32° members with **at least 730 days** in the 32° who have **never** held a seat.
- After the round, a witness (or a member) records `council_draw` with the `beacon`, and the vacancies are drawn among those in the frozen pool who are still active and in the 32°.
- Each member drawn holds a seat for 3 years, without renewal. Afterwards they keep the title of Sovereign Guardian, but with no power at all.
- The Council's powers are narrow: delaying an already approved decision by up to 30 days, convening an extraordinary assembly and certifying official mirrors (witnesses join and leave by `witness` ballot). These powers are **procedural**: the Constitution defines them, but the verifier does not enforce them. See [[governance-openmasonry-vs-fraternal-orders]].

### Along the whole path
- **`work`:** every recorded contribution adds Light. Light decays with a 180-day half-life and never confers voting weight.
- **[[dormancy]]:** after 365 days without signed activity, the member drops out of the quorum base but keeps their degree and their vote.
- **`witness`:** witness nodes sign ledger checkpoints, each stating the digest of the whole state it covers.
- **Rooms:** from the 1° on, a member reads the study room of their degree and of every degree below it. A room is closed but never secret, and nothing is decided there (see [[rooms]]; the rooms open at the public launch).
- **Your key: `rekey`.** A member replaces their own key with `bin/om rekey --new-key PATH`: the current key signs the entry and the new key proves itself. It can be done once in 30 days, also while suspended, frozen or during a halt, and a replaced key is never registered again (`ledger._rekey`).
- **A lost or stolen key: `rekey_recover`, `rekey_cosign`, `rekey_oppose`, `rekey_object`, `rekey_recover_apply`.** The membership is recovered through peers, and never needs a Custodian. The member asks with a new key listed on their GitHub account (`om recover`). If a Custodian froze the old key, two Master Builders co-sign that the person asking is the member and 21 days of notice run from the request; otherwise (an open recovery) three co-sign, not all of them the member's sponsors while an active Master Builder who is not a sponsor exists, 30 days of notice run from the last co-signature, and the Master Builders may oppose it. Where fewer other Masters exist than that, all of them suffice and the notice is 45 days (only Masters who answered within the last year, or reached the 3rd degree within it, are counted); and when 30 days pass with fewer co-signatures than it needs (counted as one at least where another Master Builder exists; without a freeze, only if its notice had not begun), those who have co-signed (at least one) suffice and may all be sponsors, with 45 days of notice: after a freeze they start on that thirtieth day and the old key stays frozen meanwhile; without one, they start on that thirtieth day if the co-signatures then given are enough, and otherwise at the co-signature that makes them enough. A recovery reverses a departure when it is asked before the departure or within 30 days of it, or when it follows, within 150 days of that recovery's request or of the old key's stop of it, a recovery in time for that departure, whatever ended that recovery, so one follow-up may follow another; it does so when it completes, and a Council seat the departure ended comes back only into a vacancy. While a recovery is open, whoever holds the old key can stop it once (`om recover-object`); the next request, asked no sooner than 90 days after the stop, is final and the old key cannot stop it. A login asks once in 90 days. The new key completes the recovery (`om recover-apply`) within 60 days of the start of its notice. No one replaces a key for someone else (see [[custodian-and-corrections]]; the runbook is `docs/operations/RECOVERY.md`).
- **Corrections.** Until the [[founder-sunset]], a Custodian may freeze a key, stay a ballot before its reveal window, halt the ledger under attack or, after 14 days of notice, void an open ballot or undo an admission or an advancement closed within 90 days. No correction touches a ballot that adds a witness or advances a member to the 3rd degree. Every correction is a public entry with a ground and a reason, and a Master Builder may object to it (`correction_object`): one fifth of the eligible Masters, never fewer than one, void it. An undone admission leaves the record `voided`, which is not a sanction; the login may be invited again 90 days after the undo, and not while a sanction ballot on that record is open.
- **Exit and fork** (Landmark VII): any member may leave whenever they wish with a `depart` entry and take their records with them; no suspension, freeze or halt prevents it, and anyone may carry the entry to the repository. A Master Builder may invite them again after 90 days, and not while a sanction ballot on that record is open, and they start over at the 1° (a suspension still running follows them back).
- **Sanctions:** warning, suspension (ends on its own after 365 days), expulsion, expulsion for fraud and reinstatement, each by a sanction ballot of the Arbiters (7°+), or of the Master Builders where fewer than three Arbiters other than the accused are present. A sanction on a Master Builder is never decided by a single elector.

## Summary: step → entry types

| Step | Ledger entries | Who signs |
|---|---|---|
| Application | none (a public issue) | the person |
| Invitation | `invite` | a Master 3°+, the first sponsor |
| Petition | `petition` | the invited candidate themselves |
| Sponsorship | `vouch` | a second Master 3°+ |
| Admission | `ballot_open` → `ballot_commit` ×N → `ballot_reveal` ×N → `ballot_close` | a sponsor / electors 2°+ / member or witness |
| Work | `work` | the member |
| Exam | `exam_open` → `exam_draw` → `exam_report` ×k | the candidate / member or witness / drawn examiners |
| Advancement | `ballot_open` (advancement) → commit/reveal → `ballot_close` | member / electors of degree ≥ d |
| 33° | `council_call` → `council_draw` | active member / member or witness (drand beacon) |
| Exit | `depart` | the member |
| Key replacement | `rekey` | the member (current key; the new key signs a proof) |
| Key recovery | `rekey_recover` → `rekey_cosign` ×2 or ×3 → `rekey_recover_apply` (`rekey_object` or `rekey_oppose` stops it) | the member's new key / Masters 3°+ / the old key or the Masters |
| Objection | `correction_object` | a Master 3°+ |
| Removal of a Custodian | `ballot_open` (custodian) → commit/reveal → `ballot_close` | a Master 3°+ / the Masters except the Custodian's member |
| Integrity | `witness` | witness nodes |

See also: [[how-to-join-openmasonry]] · [[catalog-of-the-33-degrees]] · [[rooms]] · [[custodian-and-corrections]]
