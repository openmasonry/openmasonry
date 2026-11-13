---
title: "The Seven Eternal Landmarks of OpenMasonry"
type: concept
tags: [protocol, constitution, landmarks, governance]
sources:
  - canon/eternal.toml
  - src/openmasonry/ledger.py
  - src/openmasonry/govern.py
  - docs/whitepaper/WHITEPAPER.md
  - CONSTITUTION.md
  - raw/sources/sym-landmarks-anderson-mackey-pound.md
---

# The Seven Eternal Landmarks of OpenMasonry

The part of the Constitution that **no ballot can amend**. It takes up the traditional idea of [[landmarks]] (unchangeable by definition), but with content that inverts several of Mackey's items, such as exclusion by sex and belief, and secrecy.

| # | Landmark | Text (verbatim) |
|:-:|---|---|
| I | **The Open Door** | No one is refused or ranked for sex, gender, origin, color, belief or unbelief, class or disability. The only conditions of admission the fraternity sets are adulthood, sponsorship, the signed Declaration, and the ballot. |
| II | **Light, not Secrecy** | All rules, records, ballots after they close, decisions and finances are public, and so is the teaching of every degree. The only secrets permitted are personal privacy, private keys, a ballot while it is open, and a flaw not yet repaired. Rooms of study may be closed but never secret: their existence, rules and roll are public, their door opens by rule and never by favor, nothing said in them has force, and no one is bound to silence about them except to protect a person's privacy. There are no hidden ranks, no hidden members and no hidden bodies. |
| III | **Nothing for Sale** | There is no token, coin, share or fee that buys membership, degree, vote, office or access. Status is never bought. After the founding it is earned by work and conferred by peers or by lot. |
| IV | **One Member, One Vote** | Every active member eligible for a ballot has exactly one vote. Degrees grant duties and eligibility, never weight. |
| V | **No Permanent Power** | Every office has a term. The Supreme Council is filled by verifiable lot and no one sits twice. A member who stops taking part stops being counted, and keeps the vote. |
| VI | **Verifiable Law** | Every rule that binds members is published as text, and as code wherever the ledger enforces it; anyone can replay the full history from genesis and obtain the same state. No record is ever rewritten or erased: a wrong is repaired only by a new public record, and a repair made by an office may undo, freeze or pause but never grant. |
| VII | **Exit and Fork** | Any member may leave at any time and keep their personal records; anyone may fork the code and the ledger. Legitimacy is not owned. It is earned in public. |

The text above is copied from the `landmark` tables of `canon/eternal.toml`, which alone is authoritative. The **Declaration** is in the `[declaration]` section of the same file; a petition commits to the SHA-256 of its UTF-8 `text` (`canon.declaration_digest`, printed by `openmasonry declaration`). It reads: "I come freely. I will seek light and share it. I will judge acts, not persons, and myself first. I will keep the secrets of others' privacy and no secret of power. I accept the Landmarks, and I may leave at any time."

## Closed rooms, never secret
Landmark II separates a **secret** from a **closed room**. Each of the 33 degrees has a study room read by the members of that degree and of every higher one. A room is a place of conversation, questions, drafts and mentoring; it is not a body and decides nothing. Its existence, its rules and its roll are public, access follows the ledger, and no one owes silence about it: the one duty is another person's privacy. The teaching of every degree and everything a member is examined on stay public. The rule is Constitution Art. XV, explained in `docs/governance/ROOMS.md` (whitepaper §10.6); the rooms themselves open at the public launch. The roll is public in practice too: on every run the room sync program publishes, in a public place the Observatory reads, the access the host actually grants (the readers of each room, the owners of the organization and every installed application) and an anonymous log of its runs, and the Observatory shows it beside the roll the ledger derives. The Custodian's Console stays private, but it is a working tool that decides nothing, and every binding output of it is published. See [[rooms]].

## Repair without rewriting: corrections read against Landmark VI
Landmark VI has two halves. The first is the old promise of verifiable law. The second sets the bounds of every repair, forever: no record is rewritten or erased, a wrong is repaired only by a new public record, and a repair made by an office "may undo, freeze or pause but never grant". A key recovery, which peers carry out, and the reinstatement a sanction ballot decides are not repairs made by an office.

The one power built on that sentence is the **correction**, held by the Custodian until the [[founder-sunset]] (Constitution Art. XVI). It is a deliberate and bounded exception to the idea that no one holds special power, and it is stated openly. A correction is a signed public entry of a closed kind, on one of a closed list of grounds, with a public reason pinned by hash. It can freeze a key or a witness, stay a ballot, halt the ledger under attack, hold a member out of the rooms, record a moderation note, and, after 14 days of notice, void an open ballot or undo an admission or an advancement (never one to the 3rd degree). It can never admit, advance, appoint, reinstate or sanction anyone, and never changes a vote, a key, a governed file, a Landmark or its own Article. Master Builders stop a correction by objection and remove the Custodian by simple majority; neither a freeze nor a halt keeps anyone from departing (Landmark VII). The mechanism and its limits are in [[custodian-and-corrections]].

Two other Landmarks press on the same office. An office, in the Constitution's sense (Art. II.7), is a seat held by election, lot or naming; the duty a degree unlocks is not an office, and a witness is a key that a ballot may remove at any time. Landmark V ("Every office has a term") is met for the Custodian by rule and not by a calendar date: a custodian key ends after 180 days without a sign of life, at the Sunset condition, by its own revoke key, by a ballot of the Masters, or seven years after it was named at the latest, and nothing makes it live again. Landmark II is met because every correction, its ground and its reason are public from the moment they are made.

## How immutability is enforced (code)
1. The **genesis** pins six hashes in one `pins` object, all required as 64 hex characters, under exactly these paths: `canon/degrees.toml`, `canon/eternal.toml`, `CONSTITUTION.md`, `docs/governance/CUSTODIAN.md`, `docs/governance/ROOMS.md` and `@protocol` (the digest of the pinned core, the files listed in the manifest `src/openmasonry/protocol.manifest`: fifteen files, the twelve listed files under `src/openmasonry/`, the manifest and `rooms.py` among them, and the three workflows, `judge.yml`, `tyler.yml` and `pages.yml`; `govern.read_manifest`) (`ledger._genesis`, `ledger.GENESIS_PINS`). Each pin must match exactly the bytes of its file (or the digest of the core) in the tree that carries the genesis.
2. An amendment ballot is opened only on a path of at most ten segments of letters, digits and `_ . -`, joined by `/`, each starting with a letter, a digit or `_` (or on `@protocol`). The opening is refused when the `path` begins with `ETERNAL_PREFIX = "canon/eternal.toml"`, compared without regard to case, when it lies at or under `ledger/`, or when it differs only by case from a path already pinned (`ledger._open_amendment`, `ledger.PATH_RE`, `ledger.fold`, `ledger._case_twin`). The grammar itself leaves no room for tricks such as `./canon/../canon/eternal.toml`: a segment cannot be `.` or `..`. An amendment fails at its close if the pin it would replace changed since it opened, or if an amendment of a path that differs from its own only by case passed in the meantime, and an amendment that pins sixty-four zeros removes a pin that is not one of the six of the genesis. No correction reaches a governed file or an amendment ballot either (`ledger.STAY_EXEMPT`).
3. `verify --tree` compares the bytes of **every pinned file** in the state (genesis plus approved amendments) with the latest ratified hash and reports any mismatch (`govern.check_tree`; `verify.verify_report`). It also reports any workflow under `.github/workflows/` that the manifest of the tree does not list (`govern.stray_workflows`): the set of workflows is closed, and a new one needs a ratified amendment of `@protocol`. The manifest is read from the tree being checked, so a ratified change of the list passes the judge that was there before it. Right after an amendment passes, the previous ratified version is also accepted until the PR with the new text is merged (for at most 30 days, `PRIOR_PIN_DAYS`); nothing else is. The [[tyler]] runs this check on every PR and push, and the witness refuses to sign if it fails, or if its own code is not the pinned core.
4. `canon/eternal.toml` has no ratified version but its genesis pin: the verifier reports a tree whose bytes differ from that pin as unratified, and no pin of it can be replaced or removed.
5. Changing the landmarks requires a **fork**: a new genesis, a new name and the public's judgment of legitimacy.

## Mechanisms that realize each landmark
- I → [[sybil-resistance]] (purely procedural criteria)
- II → [[chained-ledger]], [[commit-reveal]]; the public degree catalog ([[catalog-of-the-33-degrees]]); the rules of the study [[rooms]] (Constitution Art. XV and `docs/governance/ROOMS.md`), which open at the public launch
- III → no token ([[openmasonry-vs-token-daos]])
- IV → [[decision-function]]
- V → [[verifiable-lottery]], [[light-score]], [[dormancy]], [[founder-sunset]]
- VI → replay and the [[tyler]], which refuses any edit or deletion of a past entry; repair only by correction ([[custodian-and-corrections]])
- VII → MIT license, mirrors and [[opentimestamps]]

For the comparison with the tradition, see [[openmasonry-vs-traditional-freemasonry]] and [[regularity-and-recognition]].
