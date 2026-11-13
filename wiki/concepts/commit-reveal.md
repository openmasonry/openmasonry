---
title: "Commit–Reveal"
type: concept
tags: [protocol, voting, ballot, cryptography]
sources:
  - src/openmasonry/ledger.py
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/proto-drand-and-maci.md
---

# Commit–Reveal

The two-phase voting scheme that replaces the ballot box of white and black balls (see [[ballot-and-blackball]]). First each elector publishes only a commitment: the hash of their vote with a salt. Later they reveal the vote and the salt. No one votes swayed by a partial count, and no one changes their vote after seeing the others.

## Exact rule (code)
```
commitment = SHA-256( ballot_id ‖ "|" ‖ login ‖ "|" ‖ vote ‖ "|" ‖ salt )
```
- The function is `ledger.commitment`; the commitment is 64 lowercase hex characters.
- **Opening** (`ledger._ballot_open`): accepts the kinds `admission`, `advancement`, `amendment`, `sanction`, `witness` and `custodian`, the ballot that removes a Custodian (`ledger.KINDS`). The `id` is 1 to 64 characters of `a-z 0-9 . _ -`, starts with a letter or digit, and is unique (`ledger.BALLOT_ID_RE`); the `subject` has exactly the keys of its kind (`ledger.SUBJECT_KEYS`). Only one ballot of a kind is open on a subject (the same candidate, member, name or measure, case-insensitively; for an amendment the path together with the text proposed; `State.open_ballot_on`). Each kind has its opener: a sponsor of the candidate for an admission (the petition's key and sponsors are frozen into the ballot), the candidate or an examiner of the passed exam for an advancement, a Master Builder for an amendment, a witness ballot or a removal, and an Arbiter, or a Master Builder where fewer than three Arbiters exist, for a sanction. A member holds at most three open ballots of their own, and apart from them three amendment ballots.
- **Windows:** every ballot runs 7 days to commit and 3 to reveal. Only the opener of an amendment states other windows: 2 to 30 days to commit and 1 to 14 to reveal.
- **Commit** (`ledger._ballot_commit`): electors only, once each, while the commit window is open; the commitment is 64 lowercase hex characters. A member whose key is frozen by a correction commits and reveals like any other elector.
- **Reveal** (`ledger._ballot_reveal`): valid when `commit_until + REVEAL_GAP ≤ now ≤ reveal_until` (both ends included), where `REVEAL_GAP = CLOCK_TOLERANCE + 15 minutes` (a gap of 6 hours and 15 minutes). The gap ensures that no commitment backdated within the 6-hour clock tolerance can be made after reveals have begun. The vote must be `yes` or `no`, the salt 32 to 64 lowercase hexadecimal characters (`ledger.SALT_RE`; `om vote` draws 16 random bytes), and everything must match the commitment. Hence `reveal_until = opening + commit_days + REVEAL_GAP + reveal_days`.
- **Closing** (`ledger._ballot_close`): after `reveal_until`, or as soon as every elector has revealed, by any active member or a witness. It counts the revealed votes. **Unrevealed commitments count for nothing.** A ballot whose votes miss the quorum **lapses** with no penalty and may be re-run once within 30 days (at least 7 days to commit; a re-run, and a ballot that gave less than 7 days to commit, are never re-run); otherwise the [[decision-function]] decides. A failed admission discards the petition; a failed advancement marks the supporting exam as failed.
- **The clock of a ballot.** The windows are counted on the ballot's effective clock: the time during which the ledger was halted, the ballot stayed, or a correction that would void it pending is taken out, so no window is shortened (`State.ballot_time`, `State.effective`; SPEC §7.8). The stored deadlines are never rewritten. A stayed or paused ballot takes no commit, reveal or close, and a stay or a void is posted only before the reveal window opens, so no Custodian acts after reading a vote. Amendment ballots and the ballot that removes a Custodian are the exception: they run on wall time, through any halt, and are never stayed (see [[custodian-and-corrections]]).

## How a member votes (CLI)
`om vote <ballot>` only drafts a sealed vote with a fresh random salt; the agent or script never picks the vote. The person chooses Yes or No in the `om approve` system dialog, which computes the commitment, signs the entry and keeps the vote and salt in a local vault. `om reveal <ballot>` later drafts the reveal from that vault, and the vote is shown only in the dialog (`actions.cmd_vote`, `actions.cmd_approve`, `actions.cmd_reveal`).

## Declared limitation
Once revealed, each individual vote is public. This honors Landmark II ("Light, not Secrecy"), but it **weakens** the dissenter's protection against retaliation, which is the whole point of the traditional secret ballot (§6.1).
- **Planned:** encrypted votes, in the style of MACI or of a threshold-homomorphic tally, to a key held by Keepers of Discretion (4th degree) drawn by lot, with receipt-freeness as the test; only the total and a proof of correct tallying would be published (`ROADMAP.md`).
- Until then, retaliating against a vote is a sanctionable offense (Constitution, Art. VI).

Commit–reveal prevents herding. It does **not** prevent vote buying or coercion (§8.3).

See [[decision-function]] and [[tyler]] (which closes expired ballots).
