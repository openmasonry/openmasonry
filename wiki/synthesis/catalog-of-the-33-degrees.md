---
title: "Catalog of the 33 OpenMasonry degrees"
type: synthesis
tags: [degrees, catalog, aasr, houses, curriculum, waiting-period]
sources:
  - canon/degrees.toml
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/deg-wikipedia-scottish-rite.md
  - raw/sources/deg-sj-valley-degree-list.md
  - raw/sources/deg-nmj-degree-list.md
---

# Catalog of the 33 degrees

This page describes the 33 OpenMasonry degrees, one by one. The single source of truth is `canon/degrees.toml`, and the sheets in `docs/degrees/` are generated from it. Each degree lists:

- its OpenMasonry title, as it stands in the canon;
- the **House** that confers the degree;
- the **historical degree** of the Ancient and Accepted Scottish Rite (AASR), Southern Jurisdiction, that it refers to and the **public theme** of that degree;
- the virtue, the art (field of study) and the lesson;
- the required [[masterwork]], the [[waiting-period]], the examiners drawn by lot, and what the degree unlocks.

"Drawn by lot from members of degree ≥ N" below is the first rung only: where that degree holds too few members, the lot falls back to all Master Builders, then to the candidate's sponsors, and the number of examiners is lowered to those who can be drawn (Constitution Art. V.7).

> **Rule of respect.** The historical themes below are the ones described **publicly**: encyclopedia entries, the official pages of the Supreme Councils, and the public summary of the degrees written by [[albert-pike]]. No word, sign, grip, oath or passage of ritual is reproduced. OpenMasonry's ceremonial texts are original (Whitepaper §11.3). The historical names serve only as reference ([[deg-sj-valley-degree-list]], [[deg-wikipedia-scottish-rite]]).

> **Core principle.** A degree grants **duties and eligibility, never extra votes** (Landmark IV, see [[landmarks]]). A 3° Master Builder is already a full member. Degrees 4° to 32° are degrees of study and service, as in the tradition, where the "high degrees" expand on the Master's degree without standing above it.

## The six Houses

```
                        ┌────────────────────────────────────────┐
                        │ VI  SUPREME COUNCIL             33°    │ 33 seats by lot · 3 years · once in a lifetime
                        │     guards the Constitution; can only  │ (AASR: Supreme Council)
                        │     delay                              │
                        └───────────────────▲────────────────────┘
                        ┌───────────────────┴────────────────────┐
                        │ V   CONSISTORY               31°–32°   │ audit, Court of Review, balance
                        │                                        │ (AASR: Consistory)
                        └───────────────────▲────────────────────┘
             ┌──────────────────────────────┴──────────────────────────────┐
             │ IV  COUNCIL OF KADOSH                          19°–30°       │ federation, precedents, care,
             │                                                             │ security (the Watch, 30°)
             │                                                             │ (AASR: Council of Kadosh)
             └──────────────────────────────▲──────────────────────────────┘
                  ┌─────────────────────────┴─────────────────────────┐
                  │ III CHAPTER OF THE ROSE                15°–18°     │ resilience, assemblies, charity
                  │                                                   │ (AASR: Rose Croix Chapter)
                  └─────────────────────────▲─────────────────────────┘
        ┌───────────────────────────────────┴───────────────────────────────────┐
        │ II  LODGE OF PERFECTION                                  4°–14°        │ discretion, records, justice,
        │                                                                       │ moderation, systems architecture
        │                                                                       │ (AASR: Lodge of Perfection)
        └───────────────────────────────────▲───────────────────────────────────┘
   ┌────────────────────────────────────────┴────────────────────────────────────────┐
   │ I   CRAFT LODGE    1° Apprentice · 2° Fellow · 3° Master Builder                 │ the whole membership; 3° = full member
   │                                                                                 │ (Symbolic or Blue Lodge)
   └─────────────────────────────────────────────────────────────────────────────────┘
```

## Minimum cumulative time

The waiting period is the only "cost" of a degree, and time cannot be bought (Whitepaper §7.3). The values below are **lower bounds**: examinations and works make real paths longer. The 33° is not a promotion. It is the first moment at which someone may **enter the lot** for a seat, after 730 days in the 32°.

| ° | Title | Waiting period (days) | Cumulative minimum (days) | ≈ years (days ÷ 365) |
|---:|---|---:|---:|---:|
| 1 | Apprentice of the Open Craft | 0 | 0 | 0.00 |
| 2 | Fellow of the Open Craft | 30 | 30 | 0.08 |
| 3 | Master Builder | 60 | 90 | 0.25 |
| 4 | Keeper of Discretion | 180 | 270 | 0.74 |
| 5 | Steward of Memory | 30 | 300 | 0.82 |
| 6 | Scribe of Trust | 30 | 330 | 0.90 |
| 7 | Arbiter | 30 | 360 | 0.99 |
| 8 | Intendant of the Works | 30 | 390 | 1.07 |
| 9 | Elect of the Nine | 30 | 420 | 1.15 |
| 10 | Elect of the Fifteen | 30 | 450 | 1.23 |
| 11 | Elect of the Twelve | 30 | 480 | 1.32 |
| 12 | Master Architect | 30 | 510 | 1.40 |
| 13 | Seeker of the Vault | 30 | 540 | 1.48 |
| 14 | Perfect Elect | 30 | 570 | 1.56 |
| 15 | Knight of the East, the Rebuilder | 180 | 750 | 2.05 |
| 16 | Prince of the Rebuilt City | 60 | 810 | 2.22 |
| 17 | Knight of East and West | 60 | 870 | 2.38 |
| 18 | Knight of the Rose | 60 | 930 | 2.55 |
| 19 | Pontifex, Bridge Builder | 365 | 1,295 | 3.55 |
| 20 | Master of the Symbolic Lodge | 60 | 1,355 | 3.71 |
| 21 | Noachite, Keeper of Humility | 60 | 1,415 | 3.88 |
| 22 | Knight of the Royal Axe, Dignity of Labor | 60 | 1,475 | 4.04 |
| 23 | Chief of the Tabernacle, Servant of Rites | 60 | 1,535 | 4.21 |
| 24 | Prince of the Tabernacle, Interpreter of Symbols | 60 | 1,595 | 4.37 |
| 25 | Knight of the Brazen Serpent, the Healer | 60 | 1,655 | 4.53 |
| 26 | Prince of Mercy | 60 | 1,715 | 4.70 |
| 27 | Commander of the Temple | 60 | 1,775 | 4.86 |
| 28 | Knight of the Sun, Natural Philosopher | 60 | 1,835 | 5.03 |
| 29 | Knight of Saint Andrew, Equality | 60 | 1,895 | 5.19 |
| 30 | Kadosh, Guardian against Capture | 60 | 1,955 | 5.36 |
| 31 | Inspector Inquisitor, the Auditor | 365 | 2,320 | 6.36 |
| 32 | Master of the Royal Secret, Equilibrium | 365 | 2,685 | 7.36 |
| 33 | Sovereign Guardian | 730 | 3,415 | 9.36 |

The jumps are larger at degrees 4, 15, 19, 31, 32 and 33. Degrees 4, 15, 19, 31 and 33 open a new House (Perfection, Rose, Council of Kadosh, Consistory and Supreme Council). The 32° opens no House: it stays in the Consistory (31°–32°), and its 365-day jump reflects the maturity required of anyone who may enter the lot for the Council.

## The degrees, one by one

## House: Craft Lodge (degrees 1–3)

*Self-knowledge and the tools of the work.* In the historical AASR, this corresponds to the Symbolic Lodge (Blue Lodge).

### 1°: Apprentice of the Open Craft

- **House:** Craft Lodge
- **Historical degree (AASR-SJ):** Entered Apprentice.
- **Public theme of the historical degree:** The candidate is the rough ashlar that begins to be dressed: the degree presents the builder's elementary tools as allegories of self-discipline and of the start of the moral journey.
- **Virtue:** Humility
- **Art:** Grammar and Rhetoric: learning to read the work and speak clearly about it
- **Lesson:** "Before you shape the stone, learn to see the stone that you are."
- **Required masterwork:** Signed declaration of the Landmarks (the petition); after admission, a first public reflection (500+ words) at a public URL the member controls, recorded as a work entry. No examination: the admission ballot confers the degree
- **Waiting period:** 0 days in the previous degree (cumulative minimum since initiation: 0 days)
- **Examiners:** none
- **Unlocks:** Speak in the Lodge, open issues, join study circles
- **Generated sheet:** [degree-01.md](../../docs/degrees/degree-01.md)

### 2°: Fellow of the Open Craft

- **House:** Craft Lodge
- **Historical degree (AASR-SJ):** Fellowcraft.
- **Public theme of the historical degree:** The degree of study: the symbolic ascent of the staircase, and the seven liberal arts and sciences as the path to knowledge and to fair wages for one's labor.
- **Virtue:** Diligence
- **Art:** Logic, Arithmetic and Geometry: the seven liberal arts as method
- **Lesson:** "Knowledge that is not shared is a debt, not a possession."
- **Required masterwork:** One contribution to the commons (code, translation, essay or catalog entry), accepted by the normal review of the resource it joins, examined by two members drawn by lot
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 30 days)
- **Examiners:** 2, drawn by lot from members of degree ≥ 2
- **Unlocks:** Review Apprentice work, vote in Lodge ballots, examine candidates for the 2nd degree when drawn by lot
- **Generated sheet:** [degree-02.md](../../docs/degrees/degree-02.md)

### 3°: Master Builder

- **House:** Craft Lodge
- **Historical degree (AASR-SJ):** Master Mason.
- **Public theme of the historical degree:** Centered on the legend of Hiram Abiff, the master architect of Solomon's Temple who chooses death over betraying what was entrusted to him; it teaches fidelity and awareness of mortality.
- **Virtue:** Fidelity
- **Art:** Music and Astronomy: harmony, cycles and the measure of a life
- **Lesson:** "The temple is never finished; the builder is measured by what outlives them."
- **Required masterwork:** A substantive masterwork (2,000+ words or equivalent work), defended before three examiners: public written questions and answers in the masterwork's public thread, never in a room
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 90 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 3
- **Unlocks:** Sponsor candidates; examine candidates for the 2nd and 3rd degrees when drawn by lot, and for any higher degree whose own members are too few; be elected to Lodge office; found a Lodge
- **Generated sheet:** [degree-03.md](../../docs/degrees/degree-03.md)

## House: Lodge of Perfection (degrees 4–14)

*Duty, stewardship and justice inside the community.* In the historical AASR, this corresponds to the Lodge of Perfection.

### 4°: Keeper of Discretion

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Secret Master.
- **Public theme of the historical degree:** Opens the Lodge of Perfection in mourning for the dead master; the initiates are guardians of the sanctuary, and the degree deals with duty, silence and discretion.
- **Virtue:** Discretion
- **Art:** Ethics of information: privacy, confidentiality and the duty of silence
- **Lesson:** "A secret that protects a person is a trust; a secret that protects power is a lie."
- **Required masterwork:** A privacy review of one OpenMasonry process, with findings filed as issues
- **Waiting period:** 180 days in the previous degree (cumulative minimum since initiation: 270 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 4
- **Unlocks:** Serve as a teller of sealed ballots, once encrypted ballots exist
- **Generated sheet:** [degree-04.md](../../docs/degrees/degree-04.md)

### 5°: Steward of Memory

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Perfect Master.
- **Public theme of the historical degree:** Describes the funeral honors paid to Hiram; it teaches respect for the memory of those who built before us, and honesty in work.
- **Virtue:** Gratitude
- **Art:** History and archives: honoring those who built before us
- **Lesson:** "We stand on unmarked foundations; name them."
- **Required masterwork:** An archive entry documenting a person, lodge or idea from the history of fraternal societies, with sources
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 300 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 5
- **Unlocks:** Curate the History catalog
- **Generated sheet:** [degree-05.md](../../docs/degrees/degree-05.md)

### 6°: Scribe of Trust

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Intimate Secretary.
- **Public theme of the historical degree:** Revolves around someone who improperly overhears a conversation between Solomon and Hiram, King of Tyre; it deals with zeal, fidelity and the trust owed to agreements.
- **Virtue:** Faithfulness
- **Art:** Records and signatures: hashes, keys and the integrity of the written word
- **Lesson:** "Every record is a promise to someone who is not yet born."
- **Required masterwork:** Independently verify the full ledger from genesis and publish the verification transcript
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 330 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 6
- **Unlocks:** Operate a witness node, once added by a witness ballot
- **Generated sheet:** [degree-06.md](../../docs/degrees/degree-06.md)

### 7°: Arbiter

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Provost and Judge.
- **Public theme of the historical degree:** Solomon appoints judges to settle disputes among the workmen; the degree teaches impartial justice and the weight of evidence.
- **Virtue:** Justice
- **Art:** Dispute resolution: hearing both sides, evidence and proportionality
- **Lesson:** "Judge the act, not the person; judge yourself first."
- **Required masterwork:** Serve as an observer in one dispute and write a reasoned opinion
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 360 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 7
- **Unlocks:** Sit on dispute juries
- **Generated sheet:** [degree-07.md](../../docs/degrees/degree-07.md)

### 8°: Intendant of the Works

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Intendant of the Building.
- **Public theme of the historical degree:** Deals with choosing who will carry on the work of the Temple after the master's death; it teaches zeal, benevolence and the responsibility of oversight.
- **Virtue:** Diligence in service
- **Art:** Stewardship of shared work: planning, maintenance and delegation
- **Lesson:** "A builder who will not maintain is only a visitor."
- **Required masterwork:** Maintain one repository, catalog or study circle for 90 days
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 390 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 8
- **Unlocks:** Maintain a commons repository
- **Generated sheet:** [degree-08.md](../../docs/degrees/degree-08.md)

### 9°: Elect of the Nine

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Elu of the Nine.
- **Public theme of the historical degree:** The first of the "Elu" degrees, tied to the search for those guilty of Hiram's death; the most common public reading presents it as a warning against zeal that turns into vengeance.
- **Virtue:** Restraint
- **Art:** Incident response: acting under provocation without vengeance
- **Lesson:** "Zeal without restraint is the first apprentice of tyranny."
- **Required masterwork:** Write or improve an incident-response runbook and run a tabletop exercise
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 420 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 9
- **Unlocks:** Join the incident rota
- **Generated sheet:** [degree-09.md](../../docs/degrees/degree-09.md)

### 10°: Elect of the Fifteen

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Elu of the Fifteen.
- **Public theme of the historical degree:** Continues the narrative of the Elus; Pike reads it as a lesson against ignorance, ambition and, above all, fanaticism and intolerance.
- **Virtue:** Tolerance
- **Art:** Moderation: protecting dialogue from fanaticism, harassment and bad faith
- **Lesson:** "Tolerate persons, never the abolition of tolerance."
- **Required masterwork:** Moderate a public forum of OpenMasonry or another community for 60 days with a published moderation log
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 450 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 10
- **Unlocks:** Become a forum moderator
- **Generated sheet:** [degree-10.md](../../docs/degrees/degree-10.md)

### 11°: Elect of the Twelve

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Elu of the Twelve.
- **Public theme of the historical degree:** The Elus are rewarded and placed at the head of the tribes; the degree deals with the duty to govern justly and with respect for the people.
- **Virtue:** Equity
- **Art:** Economics of the commons: Ostrom's principles, free riding and fair burdens
- **Lesson:** "A commons dies of silence before it dies of theft."
- **Required masterwork:** A commons-health report on one OpenMasonry resource, scored against Ostrom's eight principles
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 480 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 11
- **Unlocks:** Review proposed amendments to operational rules for their effect on the commons
- **Generated sheet:** [degree-11.md](../../docs/degrees/degree-11.md)

### 12°: Master Architect

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Master Architect.
- **Public theme of the historical degree:** A degree of study of the principles of architecture and of the instruments of measurement; it values science and knowledge as part of the moral work.
- **Virtue:** Prudence
- **Art:** System design: geometry of structures, failure modes and simplicity
- **Lesson:** "Design so that the next builder can change what you built."
- **Required masterwork:** An architecture decision record (ADR) accepted into the canonical repository
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 510 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 12
- **Unlocks:** Review protocol-code amendments (one of the required reviewers)
- **Generated sheet:** [degree-12.md](../../docs/degrees/degree-12.md)

### 13°: Seeker of the Vault

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Royal Arch of Solomon.
- **Public theme of the historical degree:** Tells the legend of an underground vault, linked to Enoch, where something precious was hidden and is found again by those who persevere in digging.
- **Virtue:** Perseverance
- **Art:** Research: first principles, primary sources and the patience to dig
- **Lesson:** "What is buried is not lost to the one who keeps digging honestly."
- **Required masterwork:** A research paper with primary sources, examined as drawn by lot
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 540 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 13
- **Unlocks:** Supervise research circles
- **Generated sheet:** [degree-13.md](../../docs/degrees/degree-13.md)

### 14°: Perfect Elect

- **House:** Lodge of Perfection
- **Historical degree (AASR-SJ):** Perfect Elu (Grand Elect, Perfect and Sublime Mason).
- **Public theme of the historical degree:** Closes the Lodge of Perfection: the search for what was lost in the 3° comes to an end, and the degree consecrates the initiate to integrity and truth.
- **Virtue:** Integrity
- **Art:** Synthesis of the Perfection: the self as the first commons
- **Lesson:** "Integrity is the same person in the dark and in the light."
- **Required masterwork:** A public synthesis of degrees 4–13 and a service record: signed work entries or public records of service over at least 365 days
- **Waiting period:** 30 days in the previous degree (cumulative minimum since initiation: 570 days)
- **Examiners:** 5, drawn by lot from members of degree ≥ 14
- **Unlocks:** Preside over a Lodge of Perfection
- **Generated sheet:** [degree-14.md](../../docs/degrees/degree-14.md)

## House: Chapter of the Rose (degrees 15–18)

*Rebuilding, liberty of conscience and active charity.* In the historical AASR, this corresponds to the Rose Croix Chapter.

### 15°: Knight of the East, the Rebuilder

- **House:** Chapter of the Rose
- **Historical degree (AASR-SJ):** Knight of the East (or of the Sword).
- **Public theme of the historical degree:** Zerubbabel obtains from Cyrus release from the Babylonian captivity in order to rebuild the Temple; the degree deals with loyalty to truth and to the cause.
- **Virtue:** Loyalty to the work
- **Art:** Resilience: backups, mirrors, recovery and continuity
- **Lesson:** "Build with a trowel in one hand and a backup in the other."
- **Required masterwork:** Operate a verified mirror of the canonical repository for 90 days
- **Waiting period:** 180 days in the previous degree (cumulative minimum since initiation: 750 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 15
- **Unlocks:** Operate an official mirror
- **Generated sheet:** [degree-15.md](../../docs/degrees/degree-15.md)

### 16°: Prince of the Rebuilt City

- **House:** Chapter of the Rose
- **Historical degree (AASR-SJ):** Prince of Jerusalem.
- **Public theme of the historical degree:** The rebuilding continues under hostility, with the tool in one hand and the sword in the other; the degree deals with justice, courage and patience.
- **Virtue:** Civic courage
- **Art:** Civic governance: assemblies, mandates and accountability
- **Lesson:** "A city is rebuilt by citizens, not by princes."
- **Required masterwork:** Organize and document one assembly, with minutes published in the repository
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 810 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 16
- **Unlocks:** Convene assemblies
- **Generated sheet:** [degree-16.md](../../docs/degrees/degree-16.md)

### 17°: Knight of East and West

- **House:** Chapter of the Rose
- **Historical degree (AASR-SJ):** Knight of the East and West.
- **Public theme of the historical degree:** A transitional degree, with imagery from the Book of Revelation; it marks the passage from the rebuilding of the Temple to a philosophical and universal search for truth.
- **Virtue:** Universality
- **Art:** Comparative traditions: philosophies, religions and cultures in dialogue
- **Lesson:** "No single tradition owns the light; each one carries a lamp."
- **Required masterwork:** A comparative study across at least three traditions, published in its original language and in one translation into a second language
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 870 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 17
- **Unlocks:** Lead translation and outreach programs
- **Generated sheet:** [degree-17.md](../../docs/degrees/degree-17.md)

### 18°: Knight of the Rose

- **House:** Chapter of the Rose
- **Historical degree (AASR-SJ):** Knight Rose Croix.
- **Public theme of the historical degree:** One of the best-known degrees: faith, hope and charity, and the "new law" of love; in the Southern Jurisdiction it is presented in a universalist reading.
- **Virtue:** Charity
- **Art:** Active benevolence: mentoring, relief and the ethics of care
- **Lesson:** "Love that does not act is only a feeling about oneself."
- **Required masterwork:** Mentor two Apprentices to the degree of Fellow and lead one relief action
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 930 days)
- **Examiners:** 5, drawn by lot from members of degree ≥ 18
- **Unlocks:** Preside over a Chapter of the Rose; administer the relief fund
- **Generated sheet:** [degree-18.md](../../docs/degrees/degree-18.md)

## House: Council of Kadosh (degrees 19–30)

*Philosophy, law, and the defense of the commons against capture.* The name is that of the corresponding body in the historical AASR.

### 19°: Pontifex, Bridge Builder

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Grand Pontiff.
- **Public theme of the historical degree:** Opens the higher degrees with the image of the heavenly Jerusalem; the name evokes the "bridge maker", and the degree deals with persevering faith.
- **Virtue:** Concord
- **Art:** Federation: interoperability between Lodges, nodes and other communities
- **Lesson:** "Build bridges you are willing to cross in both directions."
- **Required masterwork:** Federate a witness node, or a new Lodge when lodges exist, with interoperability tests
- **Waiting period:** 365 days in the previous degree (cumulative minimum since initiation: 1,295 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 19
- **Unlocks:** Approve federation of new Lodges, when lodges exist
- **Generated sheet:** [degree-19.md](../../docs/degrees/degree-19.md)

### 20°: Master of the Symbolic Lodge

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Master of the Symbolic Lodge (the name *Master ad Vitam* belongs to the Northern Jurisdiction and to older lists).
- **Public theme of the historical degree:** Deals with the duties of the presiding officer of a lodge: governing with justice, tolerance and example, without tyranny.
- **Virtue:** Patience
- **Art:** Pedagogy: how adults learn, and how to teach without dominating
- **Lesson:** "The master's work is complete when the apprentice no longer needs the master."
- **Required masterwork:** Design or substantially improve one degree's study curriculum
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,355 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 20
- **Unlocks:** Author curricula; train examiners
- **Generated sheet:** [degree-20.md](../../docs/degrees/degree-20.md)

### 21°: Noachite, Keeper of Humility

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Noachite, or Prussian Knight.
- **Public theme of the historical degree:** Refers to the descendants of Noah and to the pride of the Tower of Babel; it teaches humility and an equal justice for the great and the small.
- **Virtue:** Humility before the law
- **Art:** Universal ethics and precedent: laws every person can accept
- **Lesson:** "The higher you stand, the lower the law must find you."
- **Required masterwork:** A precedent digest: summarize up to ten rulings from the public record, or all if fewer, and the principles they set
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,415 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 21
- **Unlocks:** Maintain the book of precedents
- **Generated sheet:** [degree-21.md](../../docs/degrees/degree-21.md)

### 22°: Knight of the Royal Axe, Dignity of Labor

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Knight of the Royal Axe, or Prince of Libanus.
- **Public theme of the historical degree:** Evokes the woodcutters who felled the cedars of Lebanon; it honors manual labor and the dignity of those who work.
- **Virtue:** Respect for work
- **Art:** Sustainability of labor: maintainers, burnout and fair recognition
- **Lesson:** "Honor the hands that cut the cedar, not only the names carved on it."
- **Required masterwork:** A recognition audit: identify and credit uncredited contributors
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,475 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 22
- **Unlocks:** Run the contributor-recognition rota
- **Generated sheet:** [degree-22.md](../../docs/degrees/degree-22.md)

### 23°: Chief of the Tabernacle, Servant of Rites

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Chief of the Tabernacle.
- **Public theme of the historical degree:** Inspired by the priesthood of Aaron in the tabernacle of the desert; it deals with service, reverence and the duties of those who lead worship.
- **Virtue:** Reverence
- **Art:** Ceremony design: ritual as shared meaning and as user experience
- **Lesson:** "A rite that no longer teaches has become a costume."
- **Required masterwork:** Write or revise an open ceremony (public, original text)
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,535 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 23
- **Unlocks:** Edit the open ritual book
- **Generated sheet:** [degree-23.md](../../docs/degrees/degree-23.md)

### 24°: Prince of the Tabernacle, Interpreter of Symbols

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Prince of the Tabernacle.
- **Public theme of the historical degree:** Continues the symbolism of the tabernacle and of the ancient religions; it teaches how to read the sacred symbols of several traditions.
- **Virtue:** Understanding
- **Art:** Semiotics: symbols, allegory and their many honest readings
- **Lesson:** "A symbol is a question that each generation must answer again."
- **Required masterwork:** Ten entries in the Symbols catalog with sources and multiple interpretations
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,595 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 24
- **Unlocks:** Curate the Symbols catalog
- **Generated sheet:** [degree-24.md](../../docs/degrees/degree-24.md)

### 25°: Knight of the Brazen Serpent, the Healer

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Knight of the Brazen Serpent.
- **Public theme of the historical degree:** Based on the biblical episode of the bronze serpent raised by Moses in the desert; it deals with faith, healing and regeneration.
- **Virtue:** Compassion
- **Art:** Wellbeing: mental health, burnout and care inside communities
- **Lesson:** "Heal the one in front of you before you theorize about the many."
- **Required masterwork:** Build or improve a wellbeing support process and train five members in it
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,655 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 25
- **Unlocks:** Serve as wellbeing steward
- **Generated sheet:** [degree-25.md](../../docs/degrees/degree-25.md)

### 26°: Prince of Mercy

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Prince of Mercy, or Scottish Trinitarian.
- **Public theme of the historical degree:** Deals with mercy and with symbolic triads; in Pike's reading, it defends tolerance among creeds.
- **Virtue:** Mercy
- **Art:** Restorative justice: repair, amnesty and the return of the excluded
- **Lesson:** "Justice that cannot forgive is only accounting."
- **Required masterwork:** Facilitate one restorative process or reinstatement review
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,715 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 26
- **Unlocks:** Grant clemency petitions a hearing
- **Generated sheet:** [degree-26.md](../../docs/degrees/degree-26.md)

### 27°: Commander of the Temple

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Knight Commander of the Temple.
- **Public theme of the historical degree:** Evokes the knightly orders of the Crusades, such as the Hospital and the Temple; it teaches that command is service, charity and humility.
- **Virtue:** Servant leadership
- **Art:** Leadership: responsibility without privilege, authority without ownership
- **Lesson:** "Command is a debt you pay to those who follow."
- **Required masterwork:** Hold an elected office for a full term with a public accountability report
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,775 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 27
- **Unlocks:** Stand for House-level office
- **Generated sheet:** [degree-27.md](../../docs/degrees/degree-27.md)

### 28°: Knight of the Sun, Natural Philosopher

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Knight of the Sun, or Prince Adept.
- **Public theme of the historical degree:** A degree of strong hermetic and philosophical symbolism; it deals with the search for truth through reason, and with light as knowledge.
- **Virtue:** Truthfulness
- **Art:** Science and epistemology: evidence, doubt and the limits of knowing
- **Lesson:** "Doubt is the lantern; certainty is where the lantern goes out."
- **Required masterwork:** An evidence review that recommends changing or confirming one OpenMasonry rule (an amendment it proposes need not pass)
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,835 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 28
- **Unlocks:** Chair evidence reviews
- **Generated sheet:** [degree-28.md](../../docs/degrees/degree-28.md)

### 29°: Knight of Saint Andrew, Equality

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Scottish Knight of Saint Andrew.
- **Public theme of the historical degree:** A degree of Scottish chivalric inspiration; it teaches equality, tolerance and humility among the brethren.
- **Virtue:** Equality
- **Art:** Accessibility and non-discrimination: the open door kept open
- **Lesson:** "Every locked door was once called a tradition."
- **Required masterwork:** An accessibility and inclusion audit of the whole admission path
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,895 days)
- **Examiners:** 3, drawn by lot from members of degree ≥ 29
- **Unlocks:** Raise an equality objection: refer to the Court of Review any rule that refuses or ranks anyone for sex, gender, origin, color, belief or unbelief, class or disability
- **Generated sheet:** [degree-29.md](../../docs/degrees/degree-29.md)

### 30°: Kadosh, Guardian against Capture

- **House:** Council of Kadosh
- **Historical degree (AASR-SJ):** Knight Kadosh, or Knight of the White and Black Eagle.
- **Public theme of the historical degree:** The summit of the higher degrees, associated with the memory of the Templars and of Jacques de Molay; it deals with the struggle against tyranny and intolerance, read in the Southern Jurisdiction without a spirit of vengeance.
- **Virtue:** Vigilance
- **Art:** Adversarial thinking: security, red-teaming and the anatomy of tyranny
- **Lesson:** "Every institution is one quiet exception away from becoming what it opposed."
- **Required masterwork:** A red-team report against the protocol with at least one fixed finding
- **Waiting period:** 60 days in the previous degree (cumulative minimum since initiation: 1,955 days)
- **Examiners:** 5, drawn by lot from members of degree ≥ 30
- **Unlocks:** Join the Watch (security response team); file capture alarms
- **Generated sheet:** [degree-30.md](../../docs/degrees/degree-30.md)

## House: Consistory (degrees 31–32)

*Audit, judgment and the balance of powers.* In the historical AASR, this corresponds to the Consistory.

### 31°: Inspector Inquisitor, the Auditor

- **House:** Consistory
- **Historical degree (AASR-SJ):** Inspector Inquisitor.
- **Public theme of the historical degree:** A judicial degree, set in a tribunal; it teaches impartial judgment and examining oneself before judging others.
- **Virtue:** Impartiality
- **Art:** Audit and judicial review: checking the powerful with their own rules
- **Lesson:** "Audit the auditors, beginning with yourself."
- **Required masterwork:** A full annual audit of one House, published with dissent sections
- **Waiting period:** 365 days in the previous degree (cumulative minimum since initiation: 2,320 days)
- **Examiners:** 5, drawn by lot from members of degree ≥ 31
- **Unlocks:** Sit on the Court of Review
- **Generated sheet:** [degree-31.md](../../docs/degrees/degree-31.md)

### 32°: Master of the Royal Secret, Equilibrium

- **House:** Consistory
- **Historical degree (AASR-SJ):** Master of the Royal Secret.
- **Public theme of the historical degree:** The synthesis of the system: the "royal secret" is publicly read as the balance between opposites and the union of the earlier lessons.
- **Virtue:** Balance
- **Art:** Synthesis: the balance of powers and the equilibrium of opposites
- **Lesson:** "The royal secret is that no one should hold it alone."
- **Required masterwork:** A thesis on the balance of powers in OpenMasonry, defended publicly: written questions and answers in its public thread, never in a room
- **Waiting period:** 365 days in the previous degree (cumulative minimum since initiation: 2,685 days)
- **Examiners:** 7, drawn by lot from members of degree ≥ 32
- **Unlocks:** Enter the sortition pool of the Supreme Council after 730 days in the degree
- **Generated sheet:** [degree-32.md](../../docs/degrees/degree-32.md)

## House: Supreme Council (degree 33)

*Guardianship of the Constitution. Serves; never commands.* In the historical AASR, this corresponds to the Supreme Council.

### 33°: Sovereign Guardian

- **House:** Supreme Council
- **Historical degree (AASR-SJ):** Inspector General (honorary, conferred by a Supreme Council).
- **Public theme of the historical degree:** Conferred by the Supreme Council, which governs the rite; in the Southern Jurisdiction the honorary 33° is given for outstanding service and cannot be asked for.
- **Virtue:** Self-limitation
- **Art:** Guardianship of the Constitution
- **Lesson:** "Guard the house so well that it never needs you."
- **Required masterwork:** Not applied for. Drawn by verifiable lot from all eligible 32nd-degree members (see Whitepaper §7.5)
- **Waiting period:** 730 days in the previous degree (cumulative minimum since initiation: 3,415 days)
- **Examiners:** none (a draw for the seat, not an examination)
- **Unlocks:** A three-year, non-renewable seat on the Supreme Council
- **Generated sheet:** [degree-33.md](../../docs/degrees/degree-33.md)

## Notes on the historical names

- **27° and 28°:** the canon follows the order of Pike (1884) and of today's Southern Jurisdiction valleys (27° *Knight Commander of the Temple*, 28° *Knight of the Sun*). The Wikipedia table reverses this order ([[deg-wikipedia-scottish-rite]]).
- **20°:** in the SJ the name is *Master of the Symbolic Lodge*. *Master ad Vitam* is the name used in the NMJ and in older lists.
- **33°:** in the SJ, the title of an active member of the Supreme Council is *Sovereign Grand Inspector General*, and the honorary title is *Inspector General Honorary*. The canon uses "Inspector General (honorary...)".
- The Northern Jurisdiction uses many different names; see [[aasr-southern-vs-northern-jurisdiction]].

## See also

[[member-journey]] · [[degree-symbols-and-virtues]] · [[seven-liberal-arts]] · [[waiting-period]] · [[verifiable-lottery]] · [[light-score]] · [[masonic-rites-compared]] · [[freemasonry-timeline]] · [generated degree index](../../docs/degrees/README.md)
