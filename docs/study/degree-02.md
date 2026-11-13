# 2°: Fellow of the Open Craft (study guide)

**House:** The Craft Lodge. Self-knowledge and the tools of the work.  
**Virtue:** Diligence  
**Art:** Logic, Arithmetic and Geometry: the seven liberal arts as method  
**Lesson:** "Knowledge that is not shared is a debt, not a possession."  
**Summary page:** [docs/degrees/degree-02.md](../degrees/degree-02.md) (generated from [`canon/degrees.toml`](../../canon/degrees.toml))

This is the full public study guide of the 2nd degree. Everything a candidate for the 2nd degree is examined on is written here or in the documents it links to. How the guides work is explained in the [README](README.md).

## 1. Purpose of the degree

The 1st degree asks a member to see themselves. The 2nd asks them to make something for others. A Fellow is a member who has given the commons one piece of real, accepted work and has learned the methods that make work trustworthy: reasoning that holds, numbers that check, and structures that fit together.

It is also the first degree whose work is judged by peers drawn by lot: the candidate submits to strangers, and the fraternity commits to judge by stated criteria, in public. From the 2nd degree on, a member reviews Apprentice work and votes in Lodge ballots, so the degree trains the habits both require.

## 2. The virtue: Diligence

**What it is.** Diligence is steady, careful effort applied to a task until it is done well. Its root is the Latin *diligere*, to value or to love: the diligent worker cares about the thing being made and about the people who will use it.

**How it shows in practice.**

- Finishing. A small contribution that is complete, tested and documented is worth more than a large one that is abandoned.
- Checking one's own work before asking others to check it: running the tests, rereading the translation against the source, verifying each citation.
- Responding to review: answering every comment, changing what should change, and explaining honestly what should not.
- Keeping a steady pace instead of bursts. The waiting period is time to work regularly, not a delay to sit out.

**Common misreadings.**

- *Diligence as volume.* Many small, careless contributions are not diligence. Light, the public score of activity, counts at most one point per member per day and is informational only ([Whitepaper §7.6](../whitepaper/WHITEPAPER.md#76-light-a-record-of-service)); it is not a measure of this virtue and no examiner reads it.
- *Diligence as overwork.* Exhaustion produces errors. A diligent worker plans the effort so that it can be sustained.
- *Diligence as perfectionism.* Work that is never offered for review serves no one. Diligence includes knowing when a piece is good enough to submit and improving it from feedback.
- *Diligence as obedience.* Careful work sometimes means questioning the instructions. A contributor who notices an error in the task and says so is more diligent than one who implements it faithfully.

## 3. The art: Logic, Arithmetic and Geometry

In the classical scheme the seven liberal arts were divided into three arts of language (grammar, rhetoric and logic) and four of number (arithmetic, geometry, music and astronomy). The 2nd degree takes the bridge between them: logic, which completes the arts of language, and arithmetic and geometry, which open the arts of number. The canon calls them "the seven liberal arts as method": they are studied for the habits of mind they build, and those habits are what make a contribution to a public, verifiable commons trustworthy.

### 3.1 Logic: reasoning that holds

An **argument** is a set of premises offered in support of a conclusion. Two questions apply to every argument:

- **Validity.** Does the conclusion follow from the premises? An argument is valid when it is impossible for the premises to be true and the conclusion false.
- **Soundness.** Is it valid, and are the premises actually true?

A useful toolkit for a Fellow:

- **Conditionals.** "If P then Q" does not mean "if Q then P". Constitution [Art. V.6](../../CONSTITUTION.md#article-v-degrees) says an examination fails when half or more of its examiners report a fail. It does not follow that an examination passes whenever fewer than half report a fail: it may also time out.
- **Quantifiers.** "Every", "some" and "no" change the meaning of a sentence completely. "No one is bound to silence about a room" is a universal negative; one exception would contradict it.
- **Common fallacies.** Attacking the person instead of the argument (*ad hominem*); appealing to authority instead of evidence; the false dilemma that offers two options when there are more; the straw man that refutes a weaker version of a view; circular reasoning that assumes what it sets out to prove.
- **Definitions.** Many disagreements dissolve once both sides use a word in the same sense. Define the key terms of any argument before testing it.

### 3.2 Arithmetic: numbers that check

Arithmetic in this degree is the habit of computing what a rule implies instead of guessing. OpenMasonry's rules are full of numbers, and every one of them can be checked by hand. Two examples from the [specification](../whitepaper/SPEC.md#7-decision-functions):

- **Quorum.** For a ballot whose quorum base is `N`, the quorum is `Q(N) = min(N, max(3, ⌈N/3⌉))`. With 7 present electors the quorum is 3; with 12, it is 4.
- **The black-ball rule.** An admission or advancement passes, once quorate, when five times the number of "no" votes is less than the total of votes cast (`5·B < T`). With 6 votes cast, one "no" lets it pass (5 < 6); with 5 votes cast, one "no" refuses it (5 < 5 is false).

The same habit applies to any contribution: check the totals of a table and recompute a figure before quoting it.

### 3.3 Geometry: structure and proof

Euclid's *Elements* taught for two thousand years a method more than a set of facts: begin from a few definitions and axioms, and derive everything else by steps that anyone can check. OpenMasonry is built on the same idea. Anyone can replay the ledger from its first entry and obtain the same state (Landmark VI). The rules are the axioms; each entry is a step; the verifier checks every step.

Geometry also teaches proportion and fit: how parts relate to a whole. A contribution has to fit the structure it joins. Code fits the architecture of the program, a translation fits the terminology already in use, a catalog entry fits the format of the catalog.

### 3.4 Exercises

None of these is graded. A candidate for the 2nd degree holds the 1st, so they share attempts in the room of the 1st degree, which Fellows and Master Builders also read.

1. **Valid or not?** For each, say whether the conclusion follows: (a) "Only the candidate may open their own examination. Ana opened an examination. So Ana is the candidate." (b) "Every Master Builder may sponsor. Ben may sponsor. So Ben is a Master Builder." (Answers: (a) valid; (b) invalid: the premise says that Master Builders may sponsor, not that only they may, so the conclusion needs another premise.)
2. **Compute.** Find `Q(N)` for `N` = 2, 9, 10 and 31, and check your answers against the table in [SPEC §7.1](../whitepaper/SPEC.md#71-quorum).
3. **Black balls.** With 12 votes cast, how many "no" votes refuse an advancement? (Answer: 3 or more, since 5 × 2 = 10 < 12 but 5 × 3 = 15 is not.)
4. **A small proof.** Using the rule that an examination passes when the "pass" reports are a strict majority of the examiners, and fails when the "fail" reports reach half of them, show that with two examiners both must report "pass" for the examination to pass, and one "fail" is enough to fail it.

## 4. The lesson, unpacked

> "Knowledge that is not shared is a debt, not a possession."

**Knowledge as something received.** Almost everything anyone knows was taught to them, by teachers, books and the makers of the tools they use. It arrives as an inheritance.

**Why a debt.** What was received freely creates an obligation to pass it on. The fraternity's commons exists because earlier contributors paid that debt. A Fellow begins to pay it in turn, with the masterwork of this degree.

**Why not a possession.** Unlike a coin, knowledge is not diminished by being shared. Hoarding it to trade for advantage is the first step toward the hidden power that Landmark II refuses: there are no secrets of the teaching, no knowledge reserved to rank.

**The limit.** The lesson does not ask anyone to share what belongs to others. Personal privacy, private keys, a ballot while it is open and a flaw not yet repaired are the only secrets Landmark II permits, and they are not knowledge one owns; they are trusts one keeps.

## 5. The masterwork

The canon states it exactly as follows:

> One contribution to the commons (code, translation, essay or catalog entry), accepted by the normal review of the resource it joins, examined by two members drawn by lot

### 5.1 Choosing the contribution

The canon names four kinds. Any one suffices; the contribution must be **accepted**, that is, taken into a public resource of the commons through its normal review (for the repository, a pull request merged after review). The canon does not set a minimum size. Choose something that serves a real need and that can be completed with care:

- **Code:** a fix, a test, a small feature or an improvement to tooling in a repository of the commons. Diligence shows in tests, a clear description and responses to review.
- **Translation:** a document of the commons rendered into another language, faithful to the source and consistent with existing terminology. Name the source version translated.
- **Essay:** an original, sourced essay on a subject of the degree's art or of the fraternity's history, offered to the commons.
- **Catalog entry:** a sourced entry in one of the commons' catalogs (for example the knowledge base in [`wiki/`](../../wiki/index.md)), following its format.

### 5.2 Producing it

1. **Read the conventions** of the resource you will contribute to (its README, its contributing guide, its format).
2. **State the problem** your contribution solves in one or two sentences, and check that no one else is already doing it.
3. **Do the work in small steps,** checking each one: tests for code, a side-by-side reading for a translation, a source for each claim in an essay or entry.
4. **Cite sources** for every fact and quotation. Any consistent style serves.
5. **Submit it for review,** answer every comment, and revise. Acceptance by the resource's own review is part of the requirement.
6. **Write a short cover note** (a few paragraphs, published with the contribution or in its pull request) that says what the contribution is, why it was chosen, how it was checked and what was learned. The cover note helps examiners see the art and the virtue at work.

Authorship is the candidate's. Help and review from others are welcome and should be acknowledged in the cover note; work done by someone or something else and presented as one's own fails.

### 5.3 From work to degree: the examination and the ballot

The rules below are those of Constitution [Art. V](../../CONSTITUTION.md#article-v-degrees) and of the specification ([§6.8 to §6.11](../whitepaper/SPEC.md#68-exam_open), [§7.3](../whitepaper/SPEC.md#73-the-examiner-pool-ladder), [§6.4.2](../whitepaper/SPEC.md#642-kind-advancement)). Where this summary and the specification differ, the specification governs.

1. **Waiting period.** The examination can be opened once the candidate has held the 1st degree for at least **30 days**.
2. **Publish and record.** The accepted contribution must be reachable at a public `http(s)` address (for example the merged pull request). It may be recorded first with `bin/om work <url>` (one `work` entry per member in any 24 hours).
3. **Open the examination.** Only the candidate opens it, with `bin/om exam 2 --work <url>`. The entry names a public randomness beacon round about eight hours in the future and freezes the pool of possible examiners and their number at that moment.
4. **The pool.** The canon asks for **two examiners**. They are drawn from the members of the 2nd degree and above, then from all Master Builders, the candidate's sponsors last (Constitution [Art. V.7](../../CONSTITUTION.md#article-v-degrees)); where none of these holds as many members as the degree asks for, all of them are drawn together and the number is lowered to them. In short: two examiners, or fewer, as drawn by lot under the rules in [SPEC.md](../whitepaper/SPEC.md#73-the-examiner-pool-ladder). Nobody can choose an examiner.
5. **The draw.** After the beacon round, a witness or any member posts the draw (`bin/om draw`). A lot not drawn within 7 days of its round ends the examination without penalty, and a new one may be opened at once.
6. **Conflicts.** A drawn examiner with a conflict of interest (a friend, a colleague, a co-author) recuses, and the next member in the lot's order takes the seat. If nobody is left to take it, the examination lapses without penalty and may be opened again at once.
7. **Verdicts.** Each examiner reports `pass` or `fail` once and, under Art. V.5, publishes a short reasoned verdict. The examination passes with a strict majority of "pass" reports among the drawn examiners and fails when "fail" reports reach half of them. With two examiners, both must pass it, and one "fail" fails it.
8. **Time limit.** An examination without a majority verdict 60 days after it was opened has timed out: it ends without penalty, a new one may be opened at once, and examiners who never reported are left out of the next lot whenever anyone else can be drawn, and that lot seats everyone else who can examine.
9. **After a failure.** A new examination for the 2nd degree may be opened 90 days after the failed one was opened.
10. **The advancement ballot.** After a passed examination, the candidate or one of its examiners opens the ballot (`bin/om open advancement <login>`). The electors are the members of the 2nd degree and above, without the candidate; if fewer than three are present, the Master Builders without the candidate. Dormant electors keep their vote; the quorum counts the present ones. The ballot has seven days to commit and, after a gap of 6 hours 15 minutes, three to reveal (it closes early once every elector has revealed), needs a quorum, and is lost when black balls reach one fifth of the votes cast. A ballot lost on the votes counts as a failed examination; one that lapses for want of quorum leaves the passed examination free for another ballot.

## 6. Examination criteria

Examiners judge the work against the degree's stated art and virtue (Constitution [Art. V.5](../../CONSTITUTION.md#article-v-degrees)) and the requirement of the canon. A "pass" should rest on all five criteria below; a "fail" should name which one is not met and why, in terms the candidate can check.

| Criterion | Met when |
|---|---|
| 1. Requirement | The work is one contribution of a kind the canon names (code, translation, essay or catalog entry), and it has been accepted into a public resource of the commons. |
| 2. Virtue (diligence) | The contribution is complete and was checked by its author: tests pass, the translation is faithful, claims are sourced; review comments were answered. |
| 3. Art (logic, arithmetic, geometry) | The reasoning in the work and its cover note holds; any figures are correct; the contribution fits the structure and conventions of the resource it joined. |
| 4. Authorship and sources | The work is the candidate's own; help and borrowed material are acknowledged; sources are traceable. |
| 5. Service to the commons | The contribution is public and useful to someone other than its author. |

Not criteria: the size of the contribution beyond what the requirement asks, the kind chosen among the four, the candidate's opinions, style or language variety, their Light, their activity in the rooms, or who sponsored them. An examiner who would weigh any of these, or who knows the candidate personally, should recuse.

## 7. Reading

- **Euclid**, *Elements*, Book I (public-domain editions, such as Oliver Byrne's illustrated edition of 1847). Definitions, axioms and proof.
- **Aristotle**, *Prior Analytics* (part of the *Organon*; public-domain translations). The first systematic logic.
- **René Descartes**, *Discourse on the Method* (public domain, on Project Gutenberg). Four rules for careful inquiry.
- **Lewis Carroll**, *The Game of Logic* (public domain, on Project Gutenberg). Syllogisms as a game.
- **Bhāskara II**, *Līlāvatī* (H. T. Colebrooke translation, 1817, public domain). Arithmetic taught through problems.
- **Hesiod**, *Works and Days* (public-domain translations). An ancient poem on steady work.
- **P. D. Magnus**, *forall x: An Introduction to Formal Logic* (open textbook).
- **Richard Hammack**, *Book of Proof* (freely available). How to read and write a proof.
- The project's [decision functions](../whitepaper/SPEC.md#7-decision-functions) and the [contributing guide](../../CONTRIBUTING.md).

## 8. Questions for the room

These prompts are for conversation in the room of the 1st degree, where candidates for the 2nd degree study, and in the room of the 2nd degree. No examination, examiner or candidate is canvassed in either.

1. What is the difference between being busy and being diligent? How would an observer tell them apart?
2. Which contribution would you choose, and what makes it complete rather than merely started?
3. Find a sentence in the [Whitepaper](../whitepaper/WHITEPAPER.md) that seems to follow from the rules. Does it actually follow, or does it need another premise?
4. Why does a public, replayable ledger need arithmetic that anyone can check by hand?
5. In what sense is knowledge you received a debt? To whom is it owed?

## 9. What the degree unlocks

The canon states: "Review Apprentice work, vote in Lodge ballots, examine candidates for the 2nd degree when drawn by lot". A Fellow is an elector of admission ballots (whose electorate is the 2nd degree and above) and of advancement ballots to the 2nd degree, and stands in the first rung of the examiner lot for the 2nd degree. A Fellow also reads the rooms of the 1st and 2nd degrees.

These are duties and eligibility, never weight (Landmark IV): a Fellow's vote counts exactly as any other member's.

## 10. Toward the 3rd degree

After 60 days in the 2nd degree, a Fellow may open the examination for the 3rd degree with a substantive masterwork. The [guide of the 3rd degree](degree-03.md) describes it.
