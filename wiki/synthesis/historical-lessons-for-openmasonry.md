---
title: "Historical lessons for OpenMasonry"
type: synthesis
tags: [history, design, governance, capture, decline, lessons]
sources:
  - raw/sources/hist-regius-poem.md
  - raw/sources/hist-anderson-constitutions-1717.md
  - raw/sources/hist-schaw-statutes-stevenson.md
  - raw/sources/hist-mackey-principles-masonic-law.md
  - raw/sources/hist-supreme-council-sj-pike.md
  - raw/sources/hist-prince-hall.md
  - raw/sources/hist-godf-droit-humain.md
  - raw/sources/hist-propaganda-due.md
  - raw/sources/hist-membership-decline.md
  - raw/sources/proto-ostrom-governing-the-commons.md
  - raw/sources/sym-sociability-jacob.md
  - docs/whitepaper/WHITEPAPER.md
---

# Historical lessons for OpenMasonry

What three centuries of Freemasonry (and six of the Old Charges) teach the design of OpenMasonry. Each lesson gives the **historical evidence**, the project **mechanism** that answers it and the corresponding **whitepaper section**. The full chronology is in [[freemasonry-timeline]].

> Starting point: Freemasonry **got the forms right** (degrees, sponsors, ballots, a written constitution, the lodge as a school) and **got the conditions wrong**: closure, opacity and permanence. OpenMasonry is independent, is not affiliated with any Masonic body and does not claim to speak for any (whitepaper §12.1).

---

## 1. The forms of self-government are what is worth preserving
**Evidence.** The oldest documents are **written regulations**, not secrets: the articles of the [[hist-regius-poem|Regius Poem]], the warden elected every year and the record book of [[william-schaw]] (1598). The Constitutions of 1723 require every rule change to be offered in writing "to the Perusal of all the Brethren", "even of the youngest Apprentice", and approved by a **majority** ([[james-anderson]]). [[margaret-jacob]] shows that lodges were laboratories of constitution-making, election, representation and **merit in place of birth**. See [[enlightenment-sociability]].
**Response.** The constitution as code, amendments by ballot carrying the hash of the new text (§6.4) and the [[chained-ledger]] as a public "minute book" (§4).

## 2. Closure: the closed door is costly and lasts for centuries
**Evidence.** Charge III of 1723 excludes women. [[albert-mackey]] (1856) calls this "indisputable". [[prince-hall]] is turned away in Boston, initiated in a military lodge in 1775, receives only a limited permit as African Lodge No. 1 (1776) and the charter of African Lodge No. 459 in 1784; his heirs wait until **1989/1994** for recognition; four American Grand Lodges still deny it in 2026 ([[prince-hall-freemasonry]]). [[maria-deraismes]] needed a rebel lodge (1882) and founded [[le-droit-humain]] (1893), which remains outside "regularity". The [[grand-orient-de-france]] opened the door on belief in 1877 and was excluded in 1878.
**Pattern.** Openness has always come **from the margins**, at the price of losing recognition. Control of [[regularity-and-recognition|recognition]] has meant control of legitimacy.
**Response.** Landmark I ("The Open Door") as an **eternal landmark**, which the verifier refuses to amend (§3). No central recognition authority: the legitimacy of a fork is decided in public (Landmark VII, §8.4).

## 3. Opacity leads to capture: the P2 case
**Evidence.** The [[p2-lodge]] combined **hidden membership**, **personal loyalty** to Licio Gelli and **no auditing**. It came to gather 962 names from the top of the Italian state and was declared by the Anselmi Commission an organization that had infiltrated the institutions. The GODF Affair of the Cards (*Affaire des Fiches*, 1904) shows the same logic serving a government. **Important:** P2 was repudiated by its own Grand Orient. The lesson is structural, not an accusation against Freemasonry.
**Whitepaper thesis (§1.3).** Power accumulates where **secrecy, discretion and permanence** meet.
**Response.**
- Secrecy → Landmark II: rules, records, decisions, finances and the teaching of every degree are public. The only secrets are personal privacy, private keys, votes still open and a flaw not yet repaired. Study rooms may be closed but never secret, and there are no hidden members or bodies (§3, §10.6).
- Discretion → Landmark VI: every rule that binds members is published as text, and as tested code wherever the ledger enforces it, anyone can replay the history from genesis, and no record is ever rewritten or erased (§4, §8.1). One discretionary power remains, and it is stated openly: until the [[founder-sunset]] the Custodian may repair by corrections, which are closed in kind and in ground, public with their reason, open to objection by the Master Builders, and able only to undo, freeze or pause, never to grant ([[custodian-and-corrections]]).
- Permanence → Landmark V: terms of office, a Supreme Council chosen by [[verifiable-lottery]] (single seat, 3 years) (§7.4–7.5), and members who stop taking part stop being counted while keeping the vote ([[dormancy]]; Light, §7.6). The Custodian's office ends by rule, not by its holder's choice: 180 days of silence, the Sunset condition, its own revoke key, a simple majority of the Masters, or seven years after it was named.
- Patronage → Landmark III: nothing for sale, no token, no fee that buys a degree, a vote or access; status is never bought, and after the founding it is earned by work and conferred by peers or by lot (§4.3, §10.5).

## 4. Secrecy is not privacy
**Evidence.** Files kept secret can end up exposed without control: the secret files on officers' convictions that French lodges supplied to the War Ministry came out in 1904 and brought down a minister (the Affair of the Cards, see [[grand-orient-de-france]]). Mackey defended ballot secrecy to protect the voter, but it also made the veto **unaccountable**: nobody answers for the black ball.
**Response.** Separate what is **public** (rules, decisions, tallies) from what is **personal** (erasable content kept off the ledger, only its hash on it, compatible with data protection laws such as the GDPR, §12.3). For voting, [[commit-reveal]] today and encrypted voting with a MACI-style tally proof on the roadmap (§6.1). The whitepaper admits the trade-off: after the reveal, the individual vote becomes public.
**Closed is not secret.** The study room of a degree follows the same line. It may be **closed**, so that a question or a draft has a smaller audience, but it is never **secret**: its existence, its rules and its roll are public, nothing said in it has force and no one owes silence about it (Landmark II, §10.6; see [[rooms]]). Members are told plainly that a closed room can leak, which is why nothing of lasting value may exist only in one.

## 5. The single veto and the one-fifth rule
**Evidence.** Regulation VI (1721/1723) required **unanimity**. England relaxed the rule in 1754 (up to three black balls). The United States kept unanimity ([[ballot-and-blackball]]).
**Response.** The decision function rejects with **one fifth** of black balls: a single black ball still rejects when there are up to 5 voters, but an isolated grudge does not block larger groups (§6.3).
**Source.** The whitepaper attributes the one-fifth rule to French practice as recorded by Haywood (1923, ch. III) and cites Mackey (1856) only for the English three black balls; the rule does not appear in Mackey's *Principles of Masonic Law* ([[hist-mackey-principles-masonic-law]], [[sym-haywood-symbolical-masonry-1923]]).

## 6. Factions, schisms and the right to leave
**Evidence.** Ancients vs. Moderns (1751–1813), then the break between the UGLE and the [[grand-orient-de-france]] after 1877 ([[freemasonry-timeline]]). Each rupture produced decades of dispute over who is "regular".
**Response.** The fork as an **explicit and cheap right** (Landmark VII): no leader can suspend the fraternity, because the rules are public, the code that enforces them runs from any clone, and any copy of the repository can carry on (§8.4). The founder's place is bounded in the same spirit. As a member, no founder has any power another Master Builder lacks. Until the Sunset a founder named Custodian (by the genesis, which at the founding ceremony names the first founder, or by a founder's claim) also holds that office, with the powers of the Corrections article and no others; that office ends by rule at the *Founder's Sunset* (seven active Master Builders who are not founders and four witnesses), and the Masters can end it earlier by simple majority (§9.2; [[founder-sunset]]). While few Master Builders exist, corrections are checked above all by publicity and the right to fork, and only by as many members as can object.

## 7. Life-tenured apex bodies
**Evidence.** The [[supreme-council-aasr-southern-jurisdiction]] has at most 33 active members and is self-perpetuating. [[albert-pike]] led it for **32 years**. The body nearly disappeared in 1844 (4 members) after a reputational crisis.
**Response.** The 33 degrees are preserved as **curriculum and duties**, never as voting weight (Landmark IV). Time is the only "price" of a degree, about 9.4 years until eligibility for the 33° (§7.3), and the top is chosen by lot (§7.4). See [[catalog-of-the-33-degrees]].

## 8. Decline: the forms attract, the conditions repel
**Evidence.** United States: **4.1 million (1959) → 869,000 (2023)**, a drop of about 79%. England: about 200,000 (2008) → about 150,000 domestic members (2023/24), −2.5% a year ([[hist-membership-decline]]). These are the best-documented series; the wiki has no comparable figures for other regions with long Masonic traditions, such as Germany, Latin America or the Philippines, and draws no conclusion about them. The whitepaper (§1.2) attributes part of this to the perception that secrecy sounds like exclusion and unexplained ceremony sounds like make-believe. This is **interpretation**; the causes of associational decline are broad (see the general decline of civic associations since the 1960s).
**Response.** Original and **public** ceremonies, with their meaning explained (§11). A door open to all. A **dormancy** rule (365 days), which prevents the "death by quorum" of associations whose rolls are full of inactive members (§6.2).

## 9. Legend is not history
**Evidence.** Athelstan and Euclid (Regius), the history since Adam (Anderson), the "Constitutions of 1786" attributed to Frederick II, the 1717 date, the "Freemasonry brought about independence" claim and the forged Luciferian letter of Pike. Many Masonic and anti-Masonic narratives are **founding myths** or **frauds**.
**Response.** OpenMasonry claims only the history it can **demonstrate**: a signed genesis, [[opentimestamps]] stamps and full replay. Its wiki explicitly marks what is legend, what is disputed and what is fact.

## 10. Durable commons follow known principles
**Evidence.** [[elinor-ostrom]] showed that self-governed commons last for centuries when they have clear boundaries, local rules, collective choice, accountable monitoring, graduated sanctions, cheap conflict resolution, the right to organize and nested layers. Lodges had several of these traits, but **lacked independent monitoring**, exactly where P2 flourished.
**Response.** The explicit mapping in §3.2 to the [[ostrom-principles]], with witnesses, auditors (31°) and anyone replaying the ledger.

---

See also: [[openmasonry-vs-traditional-freemasonry]], [[sybil-resistance]], [[byzantine-fault-tolerance]], [[custodian-and-corrections]].
