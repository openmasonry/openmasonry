# Study guides

The public study material of the 33 degrees of OpenMasonry: one guide per degree, from the [1st](degree-01.md) to the [33rd](degree-33.md).

By founding rule, the teaching of every degree, and everything a member is examined on, is public (Landmark II in [`canon/eternal.toml`](../../canon/eternal.toml); Constitution [Art. XV.2](../../CONSTITUTION.md#article-xv-rooms)). The one-page summary of each degree in [`docs/degrees/`](../degrees/README.md) is generated from the degree canon and states the bare requirements. These guides are the teaching around those requirements: what the degree is for, how to study its art, how to produce its masterwork and what an examiner looks for.

## How the guides work

- **One guide per degree.** Each file is named after its degree (`degree-01.md` to `degree-33.md`) and links to the generated summary of the same degree.
- **The canon governs.** Every requirement quoted here (the virtue, the art, the lesson, the masterwork, the waiting period, the number of examiners, what the degree unlocks) is copied from [`canon/degrees.toml`](../../canon/degrees.toml), a governed file. If a guide and the canon ever disagree, the canon is right and the guide is an error to be fixed. The exact procedure of examinations and ballots is in the [specification](../whitepaper/SPEC.md); where a guide and the specification disagree, the specification is right.
- **Full guides and outlines.** The guides of the three degrees of the Craft Lodge (1st to 3rd) are complete. The guides of the 4th to the 33rd degree are outlines: purpose, virtue, art, lesson, masterwork, criteria and readings. Each outline is meant to be replaced by a full guide; an outline that has not been replaced delays and invalidates nothing: the canon alone sets what a degree requires. Writing or substantially improving a curriculum is itself the masterwork of the [20th degree](degree-20.md).
- **Public and open to change.** The guides are ordinary documents of the repository. Anyone may propose a correction or an improvement by pull request. A guide is not a governed file: changing it does not change what any examiner may require, which is set by the canon.

## What every guide contains

1. **Purpose.** What the degree is for, in plain words.
2. **Virtue.** What the virtue is, how it shows in practice and how it is commonly misread.
3. **Art.** An introduction to the field of knowledge the canon names for the degree, with exercises in the full guides.
4. **Lesson.** The one-sentence teaching of the degree, unpacked.
5. **Masterwork.** The required work, quoted exactly as the canon states it, with a practical guide to producing it.
6. **Examination criteria.** What an examiner checks.
7. **Reading.** Public, freely or widely available sources. Classics are cited by title and author; any public-domain translation serves.
8. **Questions for the room.** Prompts for conversation in the degree's room (full guides).
9. **What it unlocks.** The duties the degree makes a member eligible for.

## What an examiner looks for, in general

The Constitution tells examiners to judge the work against the degree's stated art and virtue, to publish a short reasoned verdict and to declare any conflict of interest ([Art. V.5](../../CONSTITUTION.md#article-v-degrees)). Every guide turns that rule into criteria a candidate can check before submitting. Across all degrees they come to five questions:

1. **Does the work meet the requirement as the canon states it?** The `work` field of the degree is a requirement, not a theme. A masterwork that asks for "an accessibility and inclusion audit of the whole admission path" is not met by an essay on accessibility.
2. **Are the virtue, the art and the lesson made concrete?** The work shows the art in use (the method, the vocabulary, the standards of the field) and the virtue in practice (in how the work was done, not only in what it says). The lesson is a lens: a good work lets a reader see it at work without being told.
3. **Is it the person's own work?** The candidate is the author. Help, review and borrowed material are acknowledged. Work produced by someone or something else and presented as one's own fails, whatever its quality.
4. **Are sources cited?** Every fact, quotation and borrowed idea can be traced by a reader. Any consistent citation style is acceptable; consistency and traceability are what count.
5. **Does it serve the commons?** The work is public, reachable at a stable address, and useful to someone other than its author.

Criteria are **checkable and fair**. An examiner states which criterion a work meets or misses and why, in terms another member could verify. Taste is not a criterion: style, opinions, school of thought, language variety and the candidate's conclusions are never grounds for a fail, so long as the reasoning is honest and the requirement is met. Examiners judge only what is public (Constitution [Art. XV.5](../../CONSTITUTION.md#article-xv-rooms)). Retaliation against a member for how they examined is a grave offense (Constitution [Art. VI.2](../../CONSTITUTION.md#article-vi-ballots)).

## Never graded by Light or activity

Study is judged by the work alone.

- **Light is informational only.** It is the public, decaying score of a member's signed activity, it never weighs a vote and no rule reads it (Landmark IV; [Whitepaper §7.6](../whitepaper/WHITEPAPER.md#76-light-a-record-of-service)). A high Light is not a reason to pass, and a low one is not a reason to fail.
- **Room activity is never measured.** No one counts, ranks or publishes who writes or reads in a room, and activity there never counts as merit, for or against anyone, in an examination or a ballot ([rules of the rooms §9](../governance/ROOMS.md#9-plain-warnings)).
- **Seniority, friendship and degree are not evidence.** The verdict rests on the work and on the criteria of the degree.

## Drafts and the rooms

Each degree has a study room, read by the members of that degree and of every higher degree ([rules of the rooms](../governance/ROOMS.md)). The rooms open at the public launch; until they do, drafts are discussed in public. A room is the right place to share a draft for comment, ask about a source, or ask how others approached a masterwork. Three rules shape how it is used for study:

- **Nothing of lasting value lives only in a room.** If an explanation given in a room is worth keeping, its author publishes it. If something can be found only in a room, it is not part of the teaching and no examiner may hold a candidate to it.
- **No examination is canvassed in a room.** A draft may be discussed; a pending examination, its examiners and its verdict may not. Examiners judge only the published work.
- **Drafts stay their author's.** No one publishes another person's unpublished work without consent, and a member who leaves may take and erase their own contributions.

A member who has not yet reached a degree cannot read its room, but can read its guide: the guide is the whole of what will be asked. Drafts for the next degree are therefore shared in the room of the degree the candidate holds, which every member of a higher degree also reads.

## The path of a masterwork, in short

The rules below are summarized from the [Constitution, Art. V](../../CONSTITUTION.md#article-v-degrees) and the [specification](../whitepaper/SPEC.md#68-exam_open); the guides of the 2nd and 3rd degree describe them in detail.

1. **Publish** the work at a public `http(s)` address. Content such as essays lives outside the ledger, which keeps only references, so that an author can erase their own content ([Whitepaper §12.3](../whitepaper/WHITEPAPER.md#123-data-protection)).
2. **Record** it, if desired, with `bin/om work <url>`: a signed `work` entry (at most one per member in any 24 hours).
3. **Open the examination** with `bin/om exam <n> --work <url>` once the waiting period of the degree is complete. Only the candidate may open it, and only for the next degree.
4. **The lot** draws the examiners from a public beacon about eight hours later, from a pool frozen when the examination opened.
5. **The examiners report** `pass` or `fail`, each with a published reasoned verdict, within 60 days of the opening. An examination without a majority verdict by then times out, with no penalty, and may be opened again at once; only a failed one waits 90 days.
6. **The ballot.** After a passed examination, the candidate or one of its examiners opens the advancement ballot, and the peers decide.

The 1st degree is reached by admission instead, and the 33rd only by lot; their guides explain how.

## Index

| ° | Guide | Status |
|---:|---|---|
| 1 | [Apprentice of the Open Craft](degree-01.md) | full guide |
| 2 | [Fellow of the Open Craft](degree-02.md) | full guide |
| 3 | [Master Builder](degree-03.md) | full guide |
| 4 | [Keeper of Discretion](degree-04.md) | outline |
| 5 | [Steward of Memory](degree-05.md) | outline |
| 6 | [Scribe of Trust](degree-06.md) | outline |
| 7 | [Arbiter](degree-07.md) | outline |
| 8 | [Intendant of the Works](degree-08.md) | outline |
| 9 | [Elect of the Nine](degree-09.md) | outline |
| 10 | [Elect of the Fifteen](degree-10.md) | outline |
| 11 | [Elect of the Twelve](degree-11.md) | outline |
| 12 | [Master Architect](degree-12.md) | outline |
| 13 | [Seeker of the Vault](degree-13.md) | outline |
| 14 | [Perfect Elect](degree-14.md) | outline |
| 15 | [Knight of the East, the Rebuilder](degree-15.md) | outline |
| 16 | [Prince of the Rebuilt City](degree-16.md) | outline |
| 17 | [Knight of East and West](degree-17.md) | outline |
| 18 | [Knight of the Rose](degree-18.md) | outline |
| 19 | [Pontifex, Bridge Builder](degree-19.md) | outline |
| 20 | [Master of the Symbolic Lodge](degree-20.md) | outline |
| 21 | [Noachite, Keeper of Humility](degree-21.md) | outline |
| 22 | [Knight of the Royal Axe, Dignity of Labor](degree-22.md) | outline |
| 23 | [Chief of the Tabernacle, Servant of Rites](degree-23.md) | outline |
| 24 | [Prince of the Tabernacle, Interpreter of Symbols](degree-24.md) | outline |
| 25 | [Knight of the Brazen Serpent, the Healer](degree-25.md) | outline |
| 26 | [Prince of Mercy](degree-26.md) | outline |
| 27 | [Commander of the Temple](degree-27.md) | outline |
| 28 | [Knight of the Sun, Natural Philosopher](degree-28.md) | outline |
| 29 | [Knight of Saint Andrew, Equality](degree-29.md) | outline |
| 30 | [Kadosh, Guardian against Capture](degree-30.md) | outline |
| 31 | [Inspector Inquisitor, the Auditor](degree-31.md) | outline |
| 32 | [Master of the Royal Secret, Equilibrium](degree-32.md) | outline |
| 33 | [Sovereign Guardian](degree-33.md) | outline |

## Independence

OpenMasonry is not affiliated with any Masonic body. The guides are original texts. They use historical degree names only as public reference and contain no ritual, obligation, password, sign, grip, word or catechism of any Masonic body.
