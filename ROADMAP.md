# Roadmap

Each version has an **exit criterion**: what must be true and verified before the next one starts. Dates are targets, not promises. Every protocol change after genesis is an amendment (Constitution Art. VII), so the roadmap itself is a proposal to the Master Builders.

```
 v0.1 Genesis ──► v0.2 om ──► v0.3 Discretion ──► v0.4 Keys ──► v0.5 Federation ──► v0.6 Witnesses ──► v0.7 Seals ──► v1.0 Sunset
  (protocol built;   Q1 2027      Q2 2027             Q2 2027       Q3 2027             Q3 2027            Q4 2027        2028
   launch pending)
```

## v0.1 "Genesis"

Status: the protocol is built and tested; the genesis is not signed and the repository is not public yet.

### Built

- **Texts.** Whitepaper, the formal specification ([SPEC.md](docs/whitepaper/SPEC.md)), Constitution, Seven Eternal Landmarks, 33-degree canon, coats of arms, the charters of the Custodian and of the rooms.
- **A strict protocol.** Hash-chained ledger of signed entries; every entry has exactly the fields of its type, ASCII strings and integers only (no float, no null), at most 8 KiB (32 KiB for the genesis); canonical JSON written down; any error while an entry is judged refuses that entry.
- **Signature validity defined by the protocol.** Ed25519 signatures in the OpenSSH SSHSIG format are verified in pure Python, for both key types (`ssh-ed25519` and the hardware-backed `sk-ssh-ed25519@openssh.com`), with one accepted form per signature (SPEC §13). No OpenSSH is needed to verify; signing still uses `ssh-keygen`.
- **Governance rules.** Commit–reveal ballots, the decision function, the two-step drand lot with frozen pools, examinations, the Supreme Council draw, witnesses and witness ballots, departure and rejoining, sanctions with expiry.
- **Admission by invitation.** Nobody who is not a member writes to the ledger: a Master Builder signs an `invite`, and only then may the invited GitHub account petition. One GitHub account is one member.
- **Keys.** Rotation by the member (`rekey`: the old key signs, the new key proves, a key never returns), and recovery of a lost or stolen key through peers, with or without a Custodian: after a freeze, two Master Builders and 21 days of notice; without one, three Master Builders, 30 days and the Masters' right to oppose; never more co-signers than exist, with 45 days of notice when fewer, and after 30 days only those who signed (at least one) with 45 days (after a freeze from that thirtieth day, the old key frozen meanwhile); a recovery reverses a departure when it is asked before the departure or within 30 days of it, or when it follows, within 150 days of that recovery's request or of the old key's stop of it, a recovery in time for that departure, whatever ended that recovery, so one follow-up may follow another; the old key may stop a recovery once, while it is open, and the recovery that follows, no sooner than 90 days after the stop, is the peers' alone.
- **Corrections.** Custodians named at genesis, and the founder's fallback (a founder's claim of the office while no custodian key is live, before the Sunset and while fewer than three active Master Builders who are not founders exist, after 30 days of notice that one such Master can stop, a new claim by any founder then waiting 30 days; never a founder against whose custodian key a removal ballot passed); a closed menu of acts (freeze, stay, halt, room hold, note; void and undo after 14 days of notice) on closed grounds with a public reason; objections by Master Builders; limits, each custodian's share, recusal and the effective clock; the removal ballot; a seven-year term and the Sunset condition (Constitution Art. XVI).
- **Liveness.** No requirement exceeds the people who exist: a ballot that misses its quorum lapses without penalty and may be re-run once, unless it gave less than 7 days to commit (then it is opened again as a new ballot that waits for every elector); ballots close early once every elector has revealed; dormant Masters keep the vote and only lower the quorum (for the succession, the all-Masters rungs of the examiner lot and every rung of an advancement, a Master called to at least two exams or ballots that ended in the last 180 days, two calls counting as two only when they end at least 7 days apart, who answered none is silent and counts as dormant; only a ballot that gives at least 7 days to commit calls its electors, only a revealed vote answers it, and one revealed vote or one report ends a silence, a work does not; during a succession the calls of every member are recorded and a silent successor is no successor; an admission and an advancement do not wait for a silent member of any degree; when fewer than three are present on its first rung an advancement is decided on the Masters' rung, every elector of the first rung keeping the vote; and no fallback ever removes a vote); an exam without a verdict times out without penalty, its silent examiners are skipped next time, and the next lot seats everyone any rung holds, so every examiner who never answers is called; where no rung of the examiner ladder seats enough, every rung is drawn together and the number of examiners is lowered; while fewer than seven Masters are present (neither dormant nor silent), the second sponsor is waived after 30 days; a key recovery waits only for the Masters who answered within the last year; a succession lets the members of the highest degree present examine, elect advancements, invite and sponsor from 90 days after the claim, unless a Master who is neither dormant nor silent signs meanwhile, and until three active Masters who are neither dormant nor silent exist; the unstoppable entries pass every halt, cap and waiting period.
- **Rate limits.** 20 counted entries per actor per UTC day, 3 open ballots per opener (amendments counted apart), a checkpoint at most once an hour and only over a new entry, one sign of life a day.
- **Governed files.** Six genesis pins, canon history, and the pinned core (`@protocol`) listed in a manifest read from the tree being judged, so the core is upgraded through the judge; a closed set of workflows.
- **State digest.** One canonical serialization of the stored facts of the state, in sections with a Merkle root each and hash chains for the histories (version 2); every witness checkpoint states its digest and the document version, and replay refuses a wrong one. A later core changes a rule only from a fixed future time or `seq` stated in the voted text (never on the protocol epoch alone), and the `candidate` check requires a new core to replay the ledger already merged to the same head and digest.
- **Conformance vectors and property tests.** Small valid and invalid ledgers with the expected digest or refusal (`tests/vectors/`, SPEC §14), for a second implementation to pass.
- **Client anti-rollback.** Every clone and every witness remembers the head it last verified and signs nothing on a canonical ledger that lost it (`ROLLBACK`), lags (`BEHIND`), starts from another genesis, or is dated ahead of the clock (`FUTURE HEAD`).
- **Tyler.** The judge on base-branch code (`judge.yml`), holding each pull request to the numeric GitHub id of the actor and the genesis to the founder's account; auto-merge of ledger-only PRs; daily re-verification of `main`, the candidate-core check and the closing of stale applications (`tyler.yml`). Witness node (Docker, pinned verifier).
- **Members' tools.** Sealed drafts and approval in a system dialog (`om approve`), with the vote chosen in that dialog; publishing through the member's fork; `om onboard`, `om apply`, `om doctor`, `om me`, `om pending` (with `--publish` for a failed push), `om witnesses`; a native Windows launcher (`bin/om.cmd`); the Guide and the officers as Agent Skills; versioned JSON contracts; the MCP engine (`engines/openmasonry/`, decision 11 in [ARCHITECTURE](docs/architecture/ARCHITECTURE.md#decision-11-mcp-engine)): local MCP stdio with drafts, public read-only HTTP.
- **Runbooks.** [RECOVERY.md](docs/operations/RECOVERY.md) (keys, hosts, protocol flaws, upgrading the core, the last resort) and the [launch checklist](docs/operations/LAUNCH.md).
- A Python test suite (standard library `unittest`) that covers the protocol, the gates, the tools and the vectors.

### Before the public launch, in this order

1. **Organization and rooms.** The GitHub organization `openmasonry-org` holds the 33 rooms of study, one private repository per degree; the canonical repository stays `openmasonry/openmasonry`. The rule is already law (Landmark II, Constitution Art. XV, [rules of the rooms](docs/governance/ROOMS.md)); the rooms open at the launch. Public study outlines for all 33 degrees, full guides for the first three ([docs/study/](docs/study/README.md)).
2. **The room sync program.** A published program that derives the readers of each room from the ledger and applies them, with guards against mass changes, and that on every run writes, and its workflow publishes to the public repository named by `ROOMS_PUBLIC_REPO`, the access the host actually grants (the readers of each room, the owners of the organization and every installed application) and an anonymous log of its runs. Built: the rule is pinned (`src/openmasonry/rooms.py`, SPEC §15) and the program is [`ops/rooms/sync.py`](ops/rooms/sync.py); what remains is the setup of its GitHub App and of the private `ops` repository ([ops/rooms/README.md](ops/rooms/README.md)).
3. **Observatory and Console.** The Observatory: a public page computed from the ledger and the access the room sync publishes (members by degree, ballots, the admission funnel, witnesses, every correction and its state). The Console: the Custodian's private, local view of what GitHub shows only to an administrator, whose data sources and limits are public, and which decides nothing: every output that binds is public ([CONSOLE.md](docs/governance/CONSOLE.md)). Both are built (`bin/om observatory --out DIR`; the Console privately); the Observatory's workflow, `.github/workflows/pages.yml`, is part of the pinned core, and what remains is turning GitHub Pages on ([ops/observatory/README.md](ops/observatory/README.md)).
4. **Rehearsal.** The whole game in a throwaway copy of the repository ([LAUNCH.md](docs/operations/LAUNCH.md#rehearsing-the-ceremony)) and a public sandbox repository: genesis with custodian keys, an invitation and an admission, examinations to the 3rd degree, a stay, a void stopped by objection, an undo, a halt, a freeze and a key recovery, the removal of a Custodian, and each recovery runbook once.
5. **Launch.** The repository becomes public with a protected `main` branch and the ruleset of the launch checklist; the Founding Ceremony with three keys generated and stored separately (member key, custodian key, revoke key); the first witness as a Docker container on a VPS; the first invitations.

**Exit:** genesis drafted with `scripts/genesis.sh` (it names the Custodian) on a clean checkout of `main` and approved by the founder (`bin/om approve <digest>`), the Observatory published, and the first admission ballots closed.

## v0.2 "om" (Q1 2027)

- `om` in Go, **read path first**: `protocol/` core ported 1:1, native Ed25519 + SSHSIG (behind an interface), strict canonical JSON, offline drand BLS checks, `verify/state/learn/doctor`, inclusion and consistency proofs, read-only MCP tools.
- **The Go verifier passes every conformance vector** of `tests/vectors/` and states the same state digests; CI runs both judges and fails on disagreement.
- Then the **write path**: `join/vouch/ballot/exam/work/depart` with drafting tools for agents and signing only through ssh-agent with human approval; salts kept in the OS keychain.
- `om mcp`: MCP server inside the Go binary (resources, draft tools, guided prompts; signing stays behind `om approve`). Until then the MCP engine (`engines/openmasonry/`) serves MCP.
- `om witness run` replaces `node/witness.py`; drand BLS verification.
- Releases: goreleaser, SBOM, SLSA provenance, cosign; Homebrew tap and `go install`.

**Exit:** 100k-entry replay < 5 s; an agent completes the "join" flow end to end in CI; both implementations agree on every vector.

## v0.3 "Discretion" (Q2 2027)

- Encrypted ballots with **receipt-freeness as the acceptance test**: compare a Belenios-style threshold-homomorphic tally held by Keepers of Discretion (4°) drawn by lot with MACI; publish the comparison; implement the winner.
- Petition challenge window (objections with evidence, no money bounty).
- External cryptography review of the ballot design before activation by amendment.

**Exit:** a ballot is decided without any individual vote ever becoming public; the audit is published.

## v0.4 "Keys" (Q2 2027)

Rotation by the member and recovery through peers are part of v0.1. What remains:

- Attestation of hardware-backed keys, so the ledger can tell a key held by a token from one that only says so.
- Revocation of a key by ballot.

**Exit:** a key the ledger records as hardware-backed is proven to be one, and the members can revoke a stolen key by their own vote.

## v0.5 "Federation" (Q3 2027)

- Lodge namespaces with their own chains and `lodge_checkpoint` entries in the parent ledger; federation approved by Pontifex (19°) ballot.
- Lodge bylaws as governed files; local offices (Worshipful Master, Wardens…) elected per lodge.

**Exit:** two lodges run independently and verify each other.

## v0.6 "Witnesses ×4" (Q3 2027)

- At least four independent witness operators (different people, hosts and jurisdictions), added by witness ballot. Four witnesses are also one half of the Sunset condition.
- C2SP checkpoints so external witness networks (OmniWitness, Sigsum) can cosign consistency.
- `om audit`: turnout, minimal deciding coalitions, vouch-graph trust rank for 31° auditors.
- Multi-witness finality: checkpoints final at 2f + 1 of n ≥ 3f + 1; `om verify --finality`.
- Mirrors on Codeberg, GitLab and Radicle; Software Heritage archiving.

**Exit:** the loss of any one host, witness or forge does not stop the fraternity for more than an hour.

## v0.7 "Patron Seals" (Q4 2027)

- Patron Seals as ledger entries and a fiat-first treasury ([SEALS.md](docs/whitepaper/SEALS.md)): fiscal host or association, treasurer keys by ballot, quarterly retroactive grants decided by a panel of 7 Masters drawn by lot, conformance test proving no protocol function reads seals.
- Legal opinions in several jurisdictions, published before launch.

**Exit:** the first quarterly treasury report is published and reconciled on-chain and off-chain.

## v1.0 "Sunset" (2028)

- The Sunset condition holds in the ledger: seven active Master Builders who are not founders, and four witnesses. The verifier records it at the first entry after which it holds, and from that entry no custodian key signs anything, whether the genesis or a founder's claim named it (Constitution Art. XII.3, XVI.11).
- Administration of the canonical repository and of the rooms passes to owners who are the witness operators; CODEOWNERS moves to their team.
- **A college of Custodians, by amendment.** After the Sunset no correction exists: no key can be frozen, no ballot stayed and the ledger never halted (a lost key is still recovered through peers). The intended path is a college drawn by verifiable lot among the Master Builders, for a term. It is a proposal: it exists only when the members ratify it.
- External security audit of `om` published.

**Exit:** the Sunset is an entry in the ledger; no person, the founder included, holds any power over the fraternity that the protocol does not give to every Master Builder.

## Later

Mobile companion (read-only), translations of the curriculum, an open ceremony book (23°), research circles (13°), the relief fund under the Rose (18°).

## Still open in the tools

`om status` and reminders, conformance vectors for the MCP engine, a witness token as a dedicated GitHub App with expiry and a written rotation procedure.
