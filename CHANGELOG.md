# Changelog

## 0.1.0

The first release: the protocol, its verifier, the tools of the members and the founding texts. The genesis is not signed yet.

### Protocol

- An append-only, hash-chained ledger of signed JSON entries (`ledger/entries/NNNN/NNNNNN.json`, shards of 1,000), replayed by a deterministic fold from an empty state. Strict, portable encoding: exactly the fields of each type, ASCII strings and integers only (no float, no null), at most 8 KiB per entry and 32 KiB for the genesis, exact durations, canonical JSON. The exact rules are [SPEC.md](docs/whitepaper/SPEC.md).
- Ed25519 signatures in the SSHSIG format, verified in pure Python for `ssh-ed25519` and hardware-backed `sk-ssh-ed25519@openssh.com` keys (user presence required); the tools sign with OpenSSH's `ssh-keygen`.
- Thirty-four entry types:
  - founding and membership: `genesis`, `invite`, `petition`, `vouch`, `work`, `depart`;
  - ballots: `ballot_open`, `ballot_commit`, `ballot_reveal`, `ballot_close`, of six kinds (admission, advancement, amendment, sanction, witness, custodian);
  - examinations and the lot: `exam_open`, `exam_draw`, `exam_report`, `exam_recuse`, `council_call`, `council_draw`;
  - witnesses: `witness` (checkpoints);
  - keys: `rekey`, `rekey_recover`, `rekey_cosign`, `rekey_object`, `rekey_oppose`, `rekey_recover_apply`;
  - corrections and custodians: `correction`, `correction_withdraw`, `correction_object`, `correction_cosign`, `correction_apply`, `custodian_alive`, `custodian_revoke`, `custodian_claim`, `custodian_claim_object`, `custodian_claim_apply`;
  - succession: `succession_claim`.
- Admission by invitation: a Master Builder signs `invite {login, github_id}` and is the first sponsor; only the invited GitHub account petitions, within 30 days; two sponsors, or in the Founding Phase as many as there are active Masters (at most two), and, while fewer than seven Masters are present (neither dormant nor silent), one once the petition has been live 30 days; a sponsorship budget of four at a time.
- Commit–reveal ballots with fixed windows (7 days to commit, 3 to reveal, after a gap of 6 hours 15 minutes; only an amendment states its own, 2 to 30 (at least 7 while an elector is dormant) and 1 to 14 days), an early close once every elector has revealed, the quorum `min(N, max(3, ⌈N/3⌉))` over the electors present, the blackball rule for admissions and advancements, two thirds for amendments, sanctions and witnesses, and a simple majority to remove a custodian. A ballot that misses its quorum lapses without penalty and may be re-run once within 30 days, unless it gave less than 7 days to commit.
- Degree 1 by admission, degrees 2 to 32 by examination and advancement ballot, the 33rd by the verifiable lot of the Supreme Council; a two-step drand lot over a pool frozen in advance; an examiner ladder that, where no rung seats enough, draws from every rung together and lowers the number of examiners; an exam without a verdict times out without penalty, its silent examiners are skipped next time and the next lot seats everyone any rung holds, and a lot not drawn within 7 days lapses.
- Dormancy after 365 days without a signed act lowers the quorum and never removes a vote. A Master Builder who answered none of two calls that ended in the last 180 days, at least 7 days apart (an exam, or a ballot that gave at least 7 days to commit), is silent until one revealed vote or one report, and counts as dormant for the succession and the all-Masters rungs of the examiner lot; an admission and an advancement do not wait for a silent member of any degree, who keeps the vote.
- Sanctions (admonish, suspend, expel, expel for fraud, reinstate) by ballot; no sanction on a Master Builder is decided by a single elector.
- Governed files: six genesis pins (`canon/degrees.toml`, `canon/eternal.toml`, `CONSTITUTION.md`, `@protocol`, `docs/governance/CUSTODIAN.md`, `docs/governance/ROOMS.md`), changed only by amendment ballots opened by Master Builders, with one slot per path and text, a base pin, the removal of a pin that is not a genesis pin, the archive of every degree table in `canon/history/` and a protocol epoch for rule changes. `@protocol` is the digest of the files listed in `src/openmasonry/protocol.manifest`.
- Corrections by up to three custodians named at genesis, or by a founder's claim while no custodian key is live: immediate acts (`freeze_key`, `freeze_witness`, `stay`, `halt`, `hold_room`), the `note` of a moderation act, and two noticed acts (`void_ballot`, `undo_ballot`) that take effect only after 14 days of notice; closed grounds and a public reason pinned by digest; objections by Master Builders, limits, each custodian's share, recusal, the effective clock; the removal ballot, 180 days of silence, a seven-year term and the Sunset condition.
- Key recovery with or without a custodian: after a freeze or open, never more co-signers than exist among the Masters who answered within a year, a longer notice when fewer, the old key's one right to stop it, the final recovery that follows, and the opposition of the Master Builders.
- Succession: while no active Master Builder who is neither dormant nor silent exists, the members of the highest degree present examine, elect advancements, invite and sponsor until three active Masters who are neither dormant nor silent exist; meanwhile the calls of every member are recorded, and a silent successor is no successor.
- Rate limits: 20 counted entries per actor per UTC day, with an exempt set of entries that must always pass; three open ballots per opener, amendments counted apart; a checkpoint at most once an hour and only over a new entry; one custodian sign of life a day.
- State digest version 2: a Merkle root per section of records and a hash chain per history; ballots ended more than 111 days ago leave the state for the history. Every `witness` checkpoint states the digest and its `state_version`, and replay refuses a wrong one.
- Conformance vectors (`tests/vectors/`) and seeded property tests for a second implementation.

### Verifier and gates

- The pinned verifier `python -P -m openmasonry.verify`, also `om verify`: replay, clock tolerance (6 hours back, 2 minutes ahead), pull request author by numeric GitHub id (any author may carry a `depart` or a `rekey_object`), key listing on GitHub, the genesis only from the founder's account (`founder_github_id` in `src/openmasonry/network.toml`), anchors, drand beacons, the candidate-core check and the tree of governed files.
- The judge (`judge.yml`) runs the base branch's verifier on every pull request and auto-merges ledger-only ones; `tyler.yml` runs the tests, checks a candidate core against the merged ledger, audits `main` on every push and daily, and closes application issues that brought no invitation in 60 days.
- Clients and witnesses remember the head they verified: `ROLLBACK`, `BEHIND`, `DIFFERENT GENESIS` and `FUTURE HEAD` (a head more than 10 minutes ahead of the clock).

### Tools

- `bin/om` (and `bin\om.cmd` on native Windows): every act is a sealed draft, signed only after the person approves it in a system dialog, where a vote is chosen. Commands for a person who is not a member yet (`onboard`, `apply`), for members (`doctor`, `me`, `learn`, `rules`, `state`, `corrections`, `witnesses`, `genesis`, `invite`, `join`, `vouch`, `open` with `--rerun`, `vote`, `reveal`, `close`, `exam`, `report`, `recuse`, `draw`, `call-council`, `work`, `depart`, `rekey`, `recover`, `recover-cosign`, `recover-oppose`, `recover-object`, `recover-apply`, `object`, `claim-custodian`, `object-claim`, `apply-claim`, `claim-succession`, `alarm`), for custodians (`correct`, `cosign-correction`, `apply-correction`, `withdraw-correction`, `alive`, `revoke-custodian`), for publishing (`approve`, `drafts`, `discard`, `pending` with `--drop`, `--rebase` and `--publish`, `submit`) low-level tools (`verify`, `append`, `commit`, `declaration`, `digest`, `proof`, `arms`, `docs`) and public reads (`rooms`, `metrics`, `timeline`, `observatory --out DIR`); versioned JSON contracts.
- The founding account guard: `approve`, `submit` and `pending --publish` publish an entry a founder signs, or one of a custodian linked to a founder, only from the GitHub account the ledger records for that founder, and the genesis only from the account of `founder_github_id`.
- The officers as Agent Skills: the Guide (`/om`), the Guide at the door (`om-onboard`), Counselor, Secretary, Wardens, Almoner and Tyler.
- The MCP engine (`engines/openmasonry/`), built on the official MCP SDK: local MCP stdio with reads and drafts, and a public read-only HTTP endpoint; it never signs.
- The witness node (`node/`): a Docker container that closes ballots, draws lots, signs checkpoints and anchors them.
- The rule of the rooms in the pinned core (`rooms.py`, SPEC §15) and the room sync program that applies it (`ops/rooms/`); the Observatory, built from the ledger and the access the room sync publishes, with its Pages workflow (`.github/workflows/pages.yml`) in the pinned core (`ops/observatory/`).

### Texts

- The Whitepaper, the specification, the Patron Seals paper, the Constitution, the Seven Eternal Landmarks and the Declaration, the 33-degree canon with generated coats of arms and degree pages, and a study guide for every degree (`docs/study/`).
- The Custodian's charter and the rules of the rooms (governed), the public description of the Console, the launch checklist and the recovery runbooks.
- Architecture, roadmap, prior art, the agents' guides and a knowledge wiki.
