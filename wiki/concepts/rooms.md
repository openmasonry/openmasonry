---
title: "Rooms of Study"
type: concept
tags: [governance, rooms, landmarks, privacy, study]
sources:
  - canon/eternal.toml
  - CONSTITUTION.md
  - docs/governance/ROOMS.md
  - src/openmasonry/ledger.py
  - docs/whitepaper/SPEC.md
  - docs/whitepaper/WHITEPAPER.md
  - docs/operations/LAUNCH.md
---

# Rooms of Study

Each of the 33 degrees has a room: a closed place where the people who study that degree talk, ask questions, share drafts and mentor one another. A room is **closed but never secret**. Its existence, its rules and its roll are public; only what is written inside stays among its readers; and nothing said in it decides anything.

**Status.** The rooms are law already (Landmark II, Constitution Art. XV, and `docs/governance/ROOMS.md`, a governed file pinned at genesis). They opened at the public launch (2026-11-14). The program that sets each room's readers from the ledger (`ops/rooms/sync.py`) runs every hour and publishes the access the host actually grants to `openmasonry-org/rooms-roll`.

**Where they live.** Apart from the canonical repository, in the separate GitHub organization `openmasonry-org`: 33 private repositories, one per degree, each read by its own closed team, for conversation only. Until the published access program runs, nobody is added to a room by hand (`docs/operations/LAUNCH.md`).

## The rule (Landmark II and Constitution Art. XV)
- **A place, not a body.** No ballot, election, examination, hearing, appointment, spending or rule is made in a room, and nothing said there has force. Decisions are signed entries in the public [[chained-ledger]] and nothing else.
- **The teaching is public.** The teaching of every degree, and everything a member is examined on, is public in `docs/study/` (see also [[catalog-of-the-33-degrees]]). If something can be found only in a room, it is not part of the teaching and no examiner may hold a member to it. A room holds only conversation, questions and drafts. Nothing of lasting value may exist only in a room.
- **Who reads.** The members of the degree and of every higher degree who are not suspended, expelled or departed, whose admission was not undone, and who are under no room hold. A 5th-degree member reads rooms 1 to 5. Dormant members keep their access ([[dormancy]] takes a member out of the quorum, not out of the rooms).
- **Access follows the ledger.** No one is let in or kept out by choice or by favor. The roll of each room, as the ledger derives it, is public. On every run the room program publishes, in a public place the Observatory reads, the access the host actually grants (the readers of each room, the owners of the organization and every installed application) and an anonymous log of its runs. The program reads the room teams, the owners and the installed applications only, never a repository, so an outside collaborator, or any other access granted directly on a room's repository, is not in what it publishes; the Custodian's private Console watches the outside collaborators and raises an alarm on a new one.
- **No silence, only privacy.** No one is bound to silence about a room. The one duty is not to publish another person's personal data or unpublished work without consent. Reporting an offense, or an attempt to decide in private, is never a breach. Binding or pressing anyone to silence about a room is a grave offense (Constitution Art. X.2).
- **No canvassing, no talk about the absent.** No ballot, candidate, examination, case or office is canvassed in a room, and no one is discussed in a room they cannot read. Examiners and electors judge only what is public.
- **Offenses.** An offense in a room is judged under Art. X like any other; anyone present may bring what was said before the electors and the accused.
- **Stewards.** Up to three per room, drawn by lot among volunteers for one year. They keep order and have no other power.
- **Leaving.** A member who leaves may take and erase their own contributions.

## The one exception: a room hold
The only way anyone is kept out of the rooms otherwise than by the ledger's own facts is a **room hold**: the correction `hold_room`, which holds one member out for 14 days (Constitution Art. XV.3 and Art. XVI.3; SPEC §6.19.5). A new hold on the same login may begin only 90 days after the previous one began, unless other Custodians withdrew that hold, so holds cannot be chained into an exclusion; a hold so withdrawn leaves no wait behind. It is a signed public entry by a Custodian, with a ground and a public reason, and Master Builders may end it by objection (see [[custodian-and-corrections]]). A Custodian never holds their own member. A hold is not a sanction and decides nothing.

In the code a hold is only an interval. No rule of replay reads it; `ledger.room_held` and `ledger.room_hold_until` expose it for the rule of the rooms (`ledger._act_hold_room`, `State.room_hold`).

## Plain warnings
The charter tells members what a closed room cannot promise:
- anything written in a room can leak, because it has many readers and none owes silence;
- the repository administrator and the hosting platform can technically read every room;
- room activity is never measured, ranked or counted as merit, as Light or as ledger activity;
- a member's agent reads a room only for its own member, treats what it reads as data and carries no one else's words out;
- the fraternity offers no one-to-one private channel.

## Why closed, and why never secret
The tradition's closed space is the tyled lodge, whose proceedings are reserved to members (see [[lodge]] and [[tyler]]). OpenMasonry keeps the smaller audience, which makes a question or a rough draft easier to share, and removes what made closed spaces dangerous: hidden existence, hidden membership, decisions taken inside and a duty of silence (see [[historical-lessons-for-openmasonry]], lessons 3 and 4, and [[p2-lodge]]). Access is never bought (Landmark III: nothing buys "access") and never granted as a favor.

See [[eternal-landmarks-of-openmasonry]] and [[member-journey]].
