# The Custodian Console

**Status: built, not operating yet.** The Console exists, privately, and starts watching at the public launch. This page is its public description: the Console is built to these rules and operates under them.

OpenMasonry is measured in two layers. The **Observatory** is a public page, built and not yet published: it is computed only from the ledger and from the access the room sync publishes, so anyone can reproduce every number on it. The **Console** is private: it is the tool the [Custodian](CUSTODIAN.md) uses to watch over the repository and the rooms, and it reads some facts that only an administrator of the GitHub organization can see. Because it is private, everything about it except its data is public: what it reads, what it never reads, how long it keeps what it reads, and who may ask about it.

The Console is a working tool of the Custodian, and it **decides nothing**. Nothing binds anyone because the Console showed it: every output that binds is public and made outside it, by the Custodian's own hand, as a signed entry of the ledger with its public reason, or as a public issue, a public pull request or a published file. Its code is private, like any member's own tools, and that is why this page states its rules (Landmark II).

## 1. What it is

- A program that runs on the Custodian's own machine and answers only to that machine. It is not a service, and nobody else logs in to it.
- A **read-only** tool. It changes nothing on GitHub and nothing in the ledger. It signs nothing: it holds no key.
- An alarm: it tells the Custodian when something differs from what the published rules say it should be.

## 2. What it reads

These are its only sources.

| Source | What it shows |
|---|---|
| The Observatory's data | Everything the public page shows, computed from the ledger: the chain, members by degree and standing, ballots, the admission funnel, examinations, witnesses, Custodians and corrections, the derived roll of each room. The state the CLI computes from the same ledger is reduced at once to counts (open ballots and their deadlines, examinations by degree and state, the two counts of the Sunset); no row about a member is kept. |
| Open pull requests and the judge's verdict on each | What is waiting, what the judge refused and why. |
| Failed workflow runs | A judge, an audit or a sync that did not finish. |
| Issues by label | `application`, `appeal`, `capture-alarm`. |
| Invitations to the organization | Pending and failed invitations to the rooms. |
| The room sync program | From the sync's state in the private `ops` repository, only the times of its runs (the last run, the last dry run, the last success); its invitations and failures stay in `ops`. |
| The room teams | Their members, compared with the roll the ledger derives: any difference between the two is an alarm. The room sync publishes the same access (the teams, the owners and the installed applications) on every run, so the public sees it too ([ops/rooms/README.md](../../ops/rooms/README.md#what-it-publishes-landmark-ii)). |
| The organization's administration | Owners, teams, installed applications, outside collaborators. |
| Rulesets, code owners and the other settings of LAUNCH.md | The settings of [LAUNCH.md](../operations/LAUNCH.md) as they stand, and any error in `.github/CODEOWNERS`: the repository's settings and rulesets, its Pages, its variable `ROOMS_PUBLIC_REPO`, `founder_github_id` in `src/openmasonry/network.toml`, and how many keys of which type the founding account lists at `github.com/<login>.keys`. |
| The Custodian's own sign of life | The date by which the next `custodian_alive` entry is due. |

It compares the settings it reads with [LAUNCH.md](../operations/LAUNCH.md) and reports every difference.

## 3. What it never reads and never keeps

- **Never the content of a room.** The Console calls no interface of GitHub that returns what is written in a room: no discussion, issue, comment, file or draft of a room repository. It reads who can read a room, never what is said there. A test in the Console's own code checks that no such call exists; the Console's code is private, so this is the Custodian's statement.
- **Never an audit-log export**, and never IP addresses, e-mail addresses or locations.
- **Never a profile of a person.** It computes no ranking, no streak, no list sorted by Light, no record of how a person votes, no pass rate of an examiner, no histogram of the hours or weekdays at which someone is active, and nothing about activity in a room.
- **No growth targets.** It counts what happened; it sets no goal for it.

## 4. How long it keeps what it reads

- A fact about a person that is not already in the public ledger (a pending invitation to a room, a failed invitation, a difference between the roll and the access of one login) is kept for **at most 90 days** and then erased.
- Facts that are public (the ledger, public issues, public pull requests) are not private data of the Console; it may re-read them at any time.
- The Console keeps an append-only history of its own snapshots, each chained to the one before by its hash, so that a later change of its history can be detected. That chained history holds no fact about a person: such facts are kept beside it and erased after 90 days.

## 5. Rights of members

- **Any member may ask what the Console holds about their login**, by a public issue labeled `appeal` or, where the question itself is private, through the channel of [SECURITY.md](../../SECURITY.md). The Custodian answers within 30 days with everything held, or with the statement that nothing is held.
- **No correction and no sanction rests on a fact that only the Console holds.** A reason of a correction, a charge in a sanction ballot and an answer to an appeal cite only what anyone can check: the ledger, a public page, or evidence put before the electors and the accused. If the Console is the only place a fact exists, that fact decides nothing.
- A member may ask for the correction of a wrong fact the Console holds about them, and for its erasure before the 90 days.

## 6. Who holds it

- The Console belongs to the office, not to the person. When the office passes on (the [charter](CUSTODIAN.md), section 9), the Console, its code and its history pass to the next administrators under these same rules.
- The Custodian's yearly report lists the categories of data the Console held during the year.
- A change of the sources in section 2 is a change of this page, made in public before the Console reads anything new.
