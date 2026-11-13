---
title: "How do I join OpenMasonry?"
type: query
tags: [faq, invitation, petition, onboarding, github, ssh, cost, timeline]
sources:
  - docs/whitepaper/WHITEPAPER.md
  - canon/degrees.toml
---

# How do I join OpenMasonry?

You need a GitHub account and an SSH key. You introduce yourself in a public issue (an application). A Master Builder who is ready to answer for you invites you, and thereby becomes your first sponsor. You then sign a petition with your key, a second Master Builder sponsors you, and you go through a ballot of at most 10 days, 6 hours and 15 minutes (7 days of commit, a gap of 6 hours and 15 minutes, and up to 3 days of reveal; the ballot closes as soon as every elector has revealed). **It costs nothing.** If you are approved, you become an Apprentice (1°) the same day. The full step-by-step walkthrough, with every ledger entry, is in [[member-journey]].

## Frequently asked questions

### Who can join?
Any adult may apply: 18 years old, or the age of majority where you live, whichever is higher. No one is refused or ranked by sex, gender, origin, color, belief or unbelief, class or disability (Landmark I, see [[landmarks]]). The only conditions of admission the fraternity sets are adulthood, sponsorship, the signed Declaration, and the ballot. The invitation is the first act of sponsorship, not a fifth condition. The ledger also needs the means of signing (a GitHub account and a key listed on it) and some waits; these are means and delays, not conditions on the person (Constitution Art. III.1).

### Do I need to be a Freemason?
No. OpenMasonry is independent and is not recognized by any grand lodge or other Masonic body. Freemasons are welcome and remain bound by their own obligations, and no one will ask them to break them (Whitepaper §12.1). See [[openmasonry-vs-traditional-freemasonry]].

### How much does it cost?
**Nothing.** There is no initiation fee, no dues, no per-degree fee and no token (Landmark III). Running the verifier is free too. Timestamping on Bitcoin, via OpenTimestamps, costs the member nothing.

### What do I actually do?
Every act on the ledger follows the same pattern: a `bin/om` command only **drafts** the entry and prints its digest; nothing is signed until **you** approve it with `bin/om approve <digest>`, which opens a system dialog showing exactly what will be signed. On approval it signs the entry with your key and opens the pull request. `bin/om drafts` lists drafts waiting for approval, `bin/om discard` drops one, and `bin/om pending` shows your signed entries still waiting for their pull request. There is no flag that skips the dialog.

1. **Check your computer.** `bin/om onboard` checks your tools, your GitHub login and your key, sets the key up, and says your next step.
2. **SSH key.** Generate an **ed25519** key (`ssh-keygen -t ed25519`), or a hardware-backed one held by a FIDO2 token (`ssh-keygen -t ed25519-sk`, which signs only when touched); the verifier accepts these two types and no other. Register the public key on GitHub as an *authentication* key (not a signing key), which publishes it at `https://github.com/<your-login>.keys`. Keep the private key safe: it signs every act of yours. Once a member, you can replace it yourself with `bin/om rekey --new-key PATH` while you still hold it (once in 30 days). If you lose it, your membership is recovered through your peers, with or without a Custodian: you ask with a new one (`bin/om recover --new-key PATH`), Master Builders co-sign (two if a Custodian froze the old key, three otherwise, or as many as exist), and a public notice of 21, 30 or 45 days runs; if 30 days pass with fewer co-signatures than it needs (counted as one at least where another Master Builder exists; without a freeze, only if its notice had not begun), those who have co-signed (at least one) suffice, with 45 days of notice (see [[custodian-and-corrections]]). Keep your key safe all the same. `bin/om doctor` checks your tools, login, key and ledger.
3. **Read** the seven Landmarks and the Declaration (Whitepaper §3).
4. **Application.** Introduce yourself in your own words in a public issue: `bin/om apply --text FILE` publishes the text you wrote in `FILE` after you approve it in a dialog (it refuses personal data such as an e-mail address or a phone number; `--check` shows the issue first), or open an issue with the *Application* form (label `application`). It is not a ledger entry and gives no right: a Master Builder who comes to answer for you may invite you. An application that no invitation follows within 60 days is closed, with a notice of how to apply again. Membership is a public roll under the name OpenMasonry. Until you apply, `bin/om me` shows the step `apply`; while your application is open it shows `wait`, with the issue's link, until you are invited; once it is closed, the step is `apply` again.
5. **Invitation.** An active Master Builder (3°+) who is ready to answer for you drafts and approves an `invite` entry (`bin/om invite <your-login>`), which names your login and the numeric id of your GitHub account. By inviting you, that Master Builder becomes your **first sponsor**: they answer for your identity, adulthood and good faith, not for your opinions (Constitution Art. IV.3). The invitation counts in their budget of 4 sponsorships and lapses if you do not petition within 30 days; a lapsed invitation still counts in that budget for 90 days. Whom to invite is each Master Builder's own decision: `bin/om me` never lists inviting as a due step.
6. **Petition.** Once you are invited, run `bin/om join` from the repository root (without a live invitation it refuses, and explains how to apply). It shows you the Declaration and drafts a `petition` entry containing your **bare** key (`ssh-ed25519 <base64>` or `sk-ssh-ed25519@openssh.com <base64>`, without the trailing comment) and the SHA-256 of the Declaration text. Approve it with `bin/om approve <digest>`; the dialog signs it and opens the pull request with the new file in `ledger/entries/`. The pull request must come from the invited GitHub account, under the login exactly as the invitation spells it. The CLI refuses to draft an entry the protocol would reject. A petition is valid for 180 days; if you are not admitted by then, it lapses and you need a new invitation.
7. **Second sponsor.** Admission needs two sponsors, and your inviter is already the first. One more Master Builder (3°+) drafts and approves a `vouch` entry (`bin/om vouch <candidate>`). Each Master has a budget of 4 sponsorships, counting those admitted in the last 365 days who have not departed, plus the still-pending petitions they sponsor, their own live invitations and those that lapsed in the last 90 days. During the Founding Phase, with fewer than 7 active Masters, as many sponsors as there are Masters (at most two) is enough: with a single Master, your inviter alone; and once your petition has been live 30 days, your inviter alone in any case. That 30-day rule also holds after the Founding Phase whenever fewer than 7 Masters are present (neither dormant nor silent).
8. **Ballot.** **One of your sponsors** opens the admission ballot (`bin/om open admission <candidate>`), and members of 2°+ vote. First there are 7 days of commit, during which only sealed votes are published: `bin/om vote <ballot>` drafts the sealed vote, and the voter chooses Yes or No in the approval dialog. The reveal opens after a gap of 6 hours and 15 minutes and lasts 3 days (`bin/om reveal <ballot>`; see [[commit-reveal]]). When the reveal ends, or as soon as every elector has revealed, any active member can close the ballot (`bin/om close <ballot>`), or a witness does it on its next cycle if one is running. If too few voted to reach the quorum, the ballot lapses with no penalty: your petition stays live, and a sponsor opens it again or re-runs it once. You are refused if black balls reach one fifth of the votes ([[ballot-and-blackball]]).
9. **Done.** The [[tyler]] validates everything in CI and you become an **Apprentice of the Open Craft (1°)**. Your first work is a public reflection of 500+ words. `bin/om me` shows your degree and everything due for you now.

### How long does each degree take?
The figures are the **waiting periods** alone, added up from initiation. Each step also requires a public work, an examination by drawn examiners and a ballot, which take at least about 7½ days more (8 hours to the beacon of the lot, 7 days to commit and the gap of 6 hours 15 minutes, if every elector reveals at once), and about 10½ days with the full reveal window. So the 2nd degree is reached 37 d 14 h 15 m after initiation at the earliest, and the 3rd 105 d 4 h 30 m after it.

| Milestone | Minimum | ≈ |
|---|---:|---:|
| 1° Apprentice of the Open Craft | day 0 (after the admission ballot) | 0 |
| 2° Fellow of the Open Craft | 30 days | 1 month |
| 3° Master Builder (full member: sponsors, examines, votes on amendments) | 90 days | 3 months |
| 4° Keeper of Discretion | 270 days | 9 months |
| 14° Perfect Elect | 570 days | 1.6 years |
| 18° Knight of the Rose | 930 days | 2.5 years |
| 30° Kadosh, Guardian against Capture | 1,955 days | 5.4 years |
| 32° Master of the Royal Secret, Equilibrium | 2,685 days | 7.4 years |
| 33° Sovereign Guardian (you can only **enter the lot**) | 3,415 days | 9.4 years |

The complete degree-by-degree table is in [[catalog-of-the-33-degrees]].

### Can I pay or ask to go faster?
No. Time is the only "price", and it cannot be bought. The 33° cannot even be requested: it is drawn by lot among eligible 32° members ([[verifiable-lottery]]).

### Does a high degree give me more votes?
No. One person, one vote (Landmark IV). Degrees bring duties and eligibility. For example, a 7° may sit on juries and a 30° joins the security team.

### What if I stop participating or want to leave?
After 365 days without signed activity you become **dormant**: you keep your degree and your vote but drop out of the quorum count ([[dormancy]]). To come back, simply participate again. You may leave whenever you like with a `depart` entry (`bin/om depart`) and take your records with you; if you want to return, a Master Builder may invite you again after 90 days, and you start over at 1°. Your texts stay in your own repositories, and the ledger keeps only the hashes (Landmark VII; see Whitepaper §12.3).

### Is my data public?
Your login, the numeric id of your GitHub account, your public key, hashes and decisions are public. Do not put sensitive personal data in ledger entries. What you write in a study room (the rooms open at the public launch) is not on the ledger, but treat it as something that can leak: a room is closed, never secret, and its roll is public (Whitepaper §10.6; see [[rooms]]).

### Can someone undo my admission?
Not by disagreeing with it. Until the Founder's Sunset, the Custodian may undo an admission closed within the last 90 days, only on one of four closed grounds (a compromised key, a defect of the protocol, fraud of identity, an attack in progress), with a public reason, after 14 days of notice, and never when the Custodian's own member was your sponsor or opened your ballot. Any Master Builder may object, and one fifth of the eligible Masters, never fewer than one, stop it for good. Once you have advanced, the undo of your admission no longer applies. An undone admission leaves your record `voided`, which is not a sanction: you may be invited again 90 days after the undo (and for those 90 days a sanction ballot may still expel the record for fraud). See [[custodian-and-corrections]] and [[founder-sunset]].

See also: [[sybil-resistance]] · [[decision-function]] · [[waiting-period]] · [[light-score]] · [[rooms]]
