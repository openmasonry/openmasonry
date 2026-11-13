# Prior art for OpenMasonry: CLI/MCP architecture, roadmap and Patron Seals

> **Status:** survey of related work, November 2026. It informs the `om` Go CLI with an embedded MCP server (ARCHITECTURE), the ROADMAP and the separate *Patron Seals* whitepaper.
> **Method:** web search and direct reading of primary sources (specs, repos, papers). Every entry links its sources. Claims taken only from secondary summaries are marked **(secondary)**; unconfirmed claims are marked **(unverified)**.
> **Not legal advice.** The regulatory notes in §8 are a starting map for a lawyer, not conclusions.

Each entry: what it is → **lesson** (Adopt / Adapt / Avoid) → citation.

---

## 1. Git-native and decentralized collaboration and identity

**Radicle (Heartwood).** A peer-to-peer code collaboration network in Rust: nodes identified by public keys gossip repository inventories and replicate data with Git. A repository's identity is a signed identity document; 1.0 (Sept 2024) promised backwards-compatible protocol changes from then on.
**Adapt.** It confirms the whitepaper's thesis that Git can be the store and keys the identity. Radicle is already listed as a mirror; the `om` CLI should treat a Radicle remote as one more replica, not as a dependency. Note LWN's remark that per-node keys are simple and richer identity is still open, the same gap OpenMasonry fills with the ledger.
[Radicle Protocol Guide](https://radicle.xyz/guides/protocol) · [Radicle 1.0.0](https://radicle.dev/2024/09/10/radicle-1.0.0.html) · [LWN 966869](https://lwn.net/Articles/966869)

**Radicle Collaborative Objects (COBs).** Issues and patches stored as CRDT-like objects in special Git refs, each user writing under their own namespace; create/get/list/update, no delete.
**Adapt.** A good model for *non-normative* social data (discussion, drafts) that should survive a GitHub takedown. Keep the normative ledger a strict linear chain (`prev` hash), not a CRDT: the ledger needs total order, and COBs merge without it. Caveat: storing social objects in Git grows repo size **(secondary)**.
[radicle-cob crate](https://docs.rs/crate/radicle-cob/latest) · [Radicle 1.1](https://radicle.xyz/2024/12/05/radicle-1.1.html)

**git-bug.** A distributed, offline-first bug tracker that stores issues in Git objects (not working-tree files), syncs over normal remotes, and bridges to GitHub/GitLab/Jira. CLI, TUI and a web UI ship in one Go binary.
**Adopt (pattern).** The strongest precedent for `om`: a single Go binary that is both CLI and local server, with GitHub as a *bridge*, not the source of truth. Also a warning: years after launch its README still called it "not fully stable", so scope tightly.
[MichaelMure/git-bug](https://github.com/MichaelMure/git-bug) · [openSUSE package description](https://build.opensuse.org/package/show/devel:tools:scm/git-bug?rev=15)

**Gitopia.** Code hosting on a Cosmos-SDK application chain (Tendermint BFT) with a native token (LORE) for bounties and governance; storage on Arweave/IPFS **(secondary)**.
**Avoid.** It shows the path OpenMasonry rejects (§4.3 of the whitepaper): a chain and a token to solve an append problem that membership already solves. Useful only as a contrast in the Patron Seals paper.
[Gitopia intro (DEV)](https://dev.to/this-is-learning/open-source-in-the-web-30-world-gitopia-1a9h) · [git init gitopia](https://medium.com/gitopia/git-init-gitopia-a685661d5aad)

**Sigstore: gitsign + Rekor.** Keyless commit signing with short-lived certificates bound to an OIDC identity; each signature is recorded in the Rekor transparency log so it stays verifiable after the certificate expires. Certificate fields (emails) become public.
**Adapt / Avoid for members.** Do not make OIDC (i.e., a GitHub or Google login) the root of member identity: that hands the identity provider a hold over every member, contrary to §5.1 (key pinned at petition). Do use Sigstore for *release artifacts* of `om` (see §9). Rekor's "log every signature" idea is what witnesses already do for ledger entries. The design that resulted takes a middle road: every member is bound to a GitHub account by its numeric id (the judge checks that each entry comes from that account, and that the member's key is listed on it), but the root of the member's identity in the ledger is the SSH key pinned at the petition. GitHub can refuse to carry an entry, and that is visible; it cannot sign one, and a member who loses the account keeps the key, the record and the right to fork.
[Sigstore gitsign docs](https://docs.sigstore.dev/cosign/signing/gitsign) · [Introducing Gitsign](https://medium.com/sigstore/introducing-gitsign-9fd3f1b682aa)

**GitHub artifact attestations.** `actions/attest` (formerly `attest-build-provenance`) signs SLSA build provenance (in-toto) with Sigstore; alone it reaches SLSA Build L2, L3 with reusable workflows; verified with `gh attestation verify`. GitHub's Sigstore instance has no public transparency log.
**Adopt** for `om` releases, as a convenience layer. Because GitHub's instance has no public log, also publish provenance via a public log or reproducible-build checks so verification does not depend on GitHub alone.
[actions/attest-build-provenance](https://github.com/actions/attest-build-provenance) · [GitHub blog: Artifact Attestations](https://github.blog/security/supply-chain-security/introducing-artifact-attestations-now-in-public-beta/)

**Keybase.** Per-account signed "sigchains" of statements (add key, follow, prove a GitHub/Twitter account); later hashed into Stellar. Acquired by Zoom in May 2020; users questioned trusting a new owner with the servers.
**Adapt.** The sigchain is the closest ancestor of a member's ledger history, and cross-site proofs are a cheap Sybil signal. The acquisition is the lesson: proofs must stay verifiable with no operator (Alex Stamos made the same point at the time). The NCC audit also notes the low-level protocol was under-documented, so write the entry spec first.
[Keybase book: server/sigchain](https://book.keybase.io/docs/server) · [NCC Group audit 2019](https://api.keybase.io/docs-assets/blog/NCC_Group_Keybase_KB2018_Public_Report_2019-02-27_v1.3.pdf) · [Decrypt on Zoom acquisition](https://decrypt.co/28121/keybase-users-revolt-following-zoom-acquisition)

**Debian keyring and web of trust.** Uploading developers are those with a key in `debian-keyring`, kept by keyring maintainers; new members need signatures from existing developers (two for DD, one for DM, per LWN), and Debian warns that signing without first-hand knowledge destroys the web of trust.
**Adopt.** The nearest real-world analog of "Master-only sponsorship": a curated keyring with human gatekeeping, running for decades. Copy the norm (vouch only from direct knowledge) into the invitation, which only a Master Builder signs after a public application, and keep a published, replayable keyring (`om keyring export` → `allowed_signers`).
[Debian keysigning](https://www.debian.org/events/keysigning.en.html) · [debian-keyring README](https://sources.debian.org/src/debian-keyring/2025.09.18/README) · [LWN 831196](https://lwn.net/Articles/831196/bigpage)

**Nostr (NIPs).** Signed events over dumb relays. NIP-01 defines event format and relay protocol; NIP-05 maps a key to `name@domain` via `/.well-known/nostr.json`, and the spec tells clients to follow keys, not NIP-05 names; NIP-65 lists a user's relays.
**Adapt.** Two transferable ideas: (1) a human-readable name is only a *hint* pointing to a key; (2) relays as cheap, replaceable broadcast for announcements (ballot open/close) if GitHub is down. Do not depend on Nostr for normative data.
[nostr-protocol/nips](https://github.com/nostr-protocol/nips) · [NIP-05](https://github.com/nostr-protocol/nips/blob/master/05.md)

**DIDs and did:web.** W3C DID Core 1.0 went to Recommendation in 2022 over formal objections; one objection noted did:web needs DNS plus web hosting and did:key has no rotation. did:web resolves a DID document from an HTTPS path.
**Adapt (optional).** Offer `did:web:<host>:members:<login>` documents as an *export* so other systems can read member keys, but never as the source of truth: DNS and hosting are exactly the capture points the ledger avoids.
[did:web method](https://w3c-ccg.github.io/did-method-web) · [W3C Director's decision on DID 1.0](https://www.w3.org/2022/06/DIDRecommendationDecision.html)

---

## 2. Governance frameworks and their failures

**Aragon.** The largest DAO framework. In 2023 the Aragon Association reversed a voted plan to put its treasury under DAO control, citing a "51% attack" by activist holders, then dissolved and offered ANT holders redemption of ~86k ETH; holders voted to sue over the plan.
**Avoid.** A tradable governance token plus a large treasury invites holders whose goal is liquidation, not purpose. This is the central case study for the Patron Seals paper: seals must give no claim on the treasury and no vote.
[Blockworks](https://blockworks.com/news/aragon-dao-dissolves-ether) · [CoinDesk, May 2023](https://www.coindesk.com/business/2023/05/09/aragon-cancels-planned-community-control-of-200m-treasury-amid-battle-with-activist-investors/amp/) · [The Defiant](https://thedefiant.io/aragon-tokenholders-vote-to-sue-aragon-association)

**DAOstack: holographic consensus.** Proposals can be "boosted" by staking a prediction that they will pass; boosted ones pass by relative majority in a shorter window, others need an absolute majority. A HICSS 2021 study of 22 DAOs found boosted proposals were nearly always accepted, with benefits mostly in large DAOs.
**Adapt (later).** The useful idea is *attention routing*: a cheap signal decides which proposals get full electorate attention. Replace stake with non-monetary signals (sponsorship by Masters, Light). Not needed until the fraternity is large.
[DAOstack Genesis Protocol](https://daostack-1.gitbook.io/v1/introduction/holographic-consensus-overview/genesis-protocol) · [Faqir-Rhazoui et al., HICSS 2021](https://scholarspace.manoa.hawaii.edu/handle/10125/71296)

**Colony: reputation with decay, per domain.** Reputation earned per domain (and its parents), with constant decay so recent work counts more; per-colony decay rates configurable.
**Adopt (already).** Matches *Light* (half-life 180 days). Two refinements to consider: Light per house or lodge (domain-scoped), and a rule that changes to decay parameters take effect only at an epoch boundary, as Colony requires.
[Colony docs: reputation](https://docs.colony.io/learn/governance/reputation) · [colonyNetwork PR 1140](https://www.github.com/JoinColony/colonyNetwork/pull/1140)

**Snapshot.** Off-chain signed votes weighted by pluggable "strategies" (token balance, delegation); results need a trusted party to enact them.
**Avoid the weighting, adopt the separation.** Off-chain signed votes with deterministic tallying is exactly the ledger model; the weakness is weight-by-holdings and a trusted enactor. OpenMasonry has neither: weight is 1 and the Tyler enforces.
[Tally docs: Snapshot polls](https://docs.tally.xyz/user-guides/governance-frameworks/snapshot-polls/) · [Juicebox docs on Snapshot](https://juice-docs.vercel.app/user/resources/snapshot)

**Governor (OpenZeppelin) / Tally.** The most common on-chain token-governance contract: propose, vote by delegated tokens, timelock, execute.
**Adapt the lifecycle only.** The proposal → vote → *timelock* → execute sequence is sound; the timelock maps to the whitepaper's delay-only Council powers, and to the 14 days of public notice before a correction that voids or undoes a ballot can be applied (Constitution Art. XVI.4). Token-weighted voting is excluded by Landmark IV.
[OpenZeppelin governance guide](https://docs.openzeppelin.com/contracts/governance) · [Tally: Governor compatibility](https://docs.tally.xyz/user-guides/tally-contract-compatibility/openzeppelin-governor)

**Hats Protocol.** Roles as a tree of "hats": admins sit nearer the root; *eligibility* modules rule on who may wear a hat and their good standing; *toggle* modules switch a hat on or off (e.g., at season end).
**Adopt (model).** Map degrees and offices to role objects with explicit `eligibility(member, state)` and `active(role, time)` functions in the verifier. Term limits and "one Council seat per lifetime" become toggle and eligibility rules that are pure and testable.
[Hats-Protocol/hats-protocol](https://github.com/Hats-Protocol/hats-protocol)

**Moloch v2.** Minimal grant DAO: members can *ragequit* for their pro-rata share; *GuildKick* forces a ragequit on a member; non-voting "loot" shares.
**Adapt.** The lesson is the minimal surface. For OpenMasonry the right "exit" is the fork (Landmark VII), not a payout; Patron Seals must not carry a pro-rata claim, or they become shares.
[MolochVentures/moloch](https://github.com/MolochVentures/moloch/blob/master/README.md) · [ConsenSys audit of The LAO](https://consensys.io/diligence/audits/2020/01/the-lao/)

**Optimism Citizens' House and Retro Funding.** Badgeholders (non-token house) allocate retroactive grants. Round 3 (30M OP, 501 recipients, 643 submissions) cost badgeholders 30+ hours each on average. Self-reported impact metrics were hard to verify. Round 4 switched to voting on metric weights with a ratified "profit" definition. The 2024 status report admits it still did not reliably fund important contributions.
**Adapt.** Retro grants for "masterworks" are a good fit, but: keep rounds small, use a small evaluator panel drawn by lot (not everyone reviews everything), require verifiable artifacts (merged PRs, ledger entries) rather than self-reported metrics, and publish the evaluation rubric before the round.
[RetroPGF 3 recipients](https://optimism.io/blog/announcing-retropgf-round-3-recipients) · [RetroPGF 3 learnings](https://optimism.io/blog/retropgf-3-learnings-reflections) · [Retro Funding 2025](https://www.optimism.io/blog/retro-funding-2025) · [Gitcoin case study](https://explore.gitcoin.co/case-studies/optimism-retropgf-round-3)

**Gitcoin quadratic funding.** QF (Buterin, Hitzig, Weyl 2018) matches the square of the sum of square roots of contributions, optimal under its model but very exposed to Sybils and collusion. Gitcoin added COCM (attenuating clusters of similar donors) and model-based Sybil detection, and itself says complete Sybil resistance is impossible from donation data alone. Grants Stack was wound down in 2025.
**Avoid for allocation of the treasury.** QF turns each donor into a voter on grants, which would let money steer the fraternity. If ever used, only for matching *external* money to member-built projects, never for anything governance-adjacent.
[arXiv:1809.06421](https://arxiv.org/abs/1809.06421) · [Gitcoin GG20 Sybil strategy](https://gov.gitcoin.co/t/our-sybil-resistance-strategy-for-gg20/18524) · [COCM explainer](https://gitcoin.co/blog/leveling-the-field-how-connection-oriented-cluster-matching-strengthens-quadratic-funding) · [The Block on Grants Stack wind-down](https://theblock.co/post/352055/ethereum-public-goods-funding-protocol-gitcoin-winding-down-its-software-division)

**SourceCred and Coordinape.** SourceCred computed "cred" from contribution graphs (forum, GitHub) and the core team disbanded; Coordinape uses peer-allocated GIVE in small circles each epoch. Several DAOs ran both, Coordinape for what algorithms could not measure.
**Adapt.** Light is algorithmic; keep it informational. If peer recognition is ever added, use small circles (recommended for larger orgs) and keep it non-monetary. No post-mortem with a formal list of SourceCred's failure causes was found **(gap)**.
[MetaGame: SourceCred is dead](https://metagame.substack.com/p/sourcecred-is-dead-long-live-sourcecred) · [SourceCred/Coordinape comparison](https://collectivedaoarchives-catalog.vercel.app/records/sourcecred-and-coordinape-tool-comparison)

**Buterin, "Moving beyond coin voting governance" (2021).** Argues coin voting concentrates power, enables vote buying and lacks individual accountability; suggests proof of personhood/participation, limited governance scope and time delays.
**Adopt.** Direct support for OpenMasonry's choices (one member one vote, delay-only powers, minimal governed surface). Cite it in the Patron Seals paper as the reason seals carry no vote. Read via secondary coverage; the original essay was not opened **(secondary)**.
[Cointelegraph coverage](https://cointelegraph.com/news/vitalik-thinks-token-based-decentralized-governance-is-holding-defi-back)

### Key papers on DAO governance

**Fritsch, Müller, Wattenhofer, "Who controls DAOs?" (arXiv:2204.01176).** Compound, Uniswap, ENS: voting power held by a few addresses, often delegates powered by one large holder; they rarely overturned the broader outcome.
**Lesson:** concentration follows weight-by-holdings. **Adopt** as evidence for Landmark IV.
[arXiv:2204.01176](https://arxiv.org/abs/2204.01176)

**Feichtinger et al. (arXiv:2302.12125).** 21 DAOs with on-chain governance: voting power still highly centralized; also studies participation and costs.
**Lesson:** low turnout and concentration together. **Adopt** dormancy and quorum-of-active (§6.2) as the mitigation, and measure turnout per ballot in `om status`.
[arXiv:2302.12125](https://arxiv.org/abs/2302.12125)

**Falk et al., "Blockchain Governance: An Empirical Analysis of User Engagement on DAOs" (arXiv:2407.10945).** Aave, Compound, Lido, Uniswap: often 3–4 addresses form a "minimal quorum" able to decide a vote.
**Lesson:** publish a minimal-coalition metric. **Adopt:** `om audit` should report the smallest set of electors that could have decided each ballot.
[arXiv:2407.10945](https://arxiv.org/abs/2407.10945)

**Feichtinger, Fritsch, Heimbach, Vonlanthen, Wattenhofer, "SoK: Attacks on DAOs" (arXiv:2406.15071).** Classifies attacks into four categories; finds many exploit the *human* side of governance while audits focus on code. Includes Beanstalk (2022): a flash loan bought ~2/3 of voting power to pass an emergency proposal.
**Adopt.** Threat-model the social layer (bribery, rushed emergency paths, low-attention windows), not only the hash chain. No emergency path may skip the commit and reveal windows: a correction can pause a ballot or, after notice, void it, and can never decide one.
[arXiv:2406.15071](https://arxiv.org/abs/2406.15071) · [arXiv:2505.00888 (time-weighted snapshots)](https://arxiv.org/abs/2505.00888)

**"Fairness in Token Delegation" (arXiv:2510.05830).** Delegations are often misaligned with holders' stated priorities, and ranking-based delegate interfaces increase concentration.
**Avoid** delegation leaderboards. If proxy voting is ever added, do not rank delegates by power in the UI or the MCP tools.
[arXiv:2510.05830](https://arxiv.org/html/2510.05830v1)

**"Open Problems in DAOs" (arXiv:2310.19201).** A survey of open research questions for newcomers to the field.
**Reference** for the whitepaper's related-work section.
[arXiv:2310.19201](https://arxiv.org/abs/2310.19201)

---

## 3. Sybil resistance and personhood

**SybilLimit (Yu, Gibbons, Kaminsky, Xiao, IEEE S&P 2008).** Social-graph defense accepting O(log n) Sybils per attack edge in fast-mixing graphs, near-optimal.
**Adopt (already cited).** Keeps the whitepaper's honest framing: the budget `b` bounds per-edge damage; no graph algorithm removes the attack edge itself.
[dblp: YuGKX08](https://dblp.uni-trier.de/rec/conf/sp/YuGKX08.html)

**SybilRank (Cao et al., NSDI 2012).** Short trust-propagating random walks from trusted seeds, degree-normalized; at Tuenti ~90% of the 200k lowest-ranked accounts were fake. Critics show guarantees weaken with a few attack edges.
**Adapt** as an *audit tool*, not a gate: `om audit sybil` can rank members by trust reachable from the founding keys over the vouch graph, to point the 31° auditors at suspicious clusters.
[Bibliography (nymity.ch)](https://nymity.ch/sybilhunting/bibliography/) · [Koll et al. poster](https://ix.cs.uoregon.edu/~lijun/pubs/posters/koll13sybil_poster.pdf)

**BrightID.** Uniqueness from an analyzed graph of signed connections (SybilRank, Aura), no biometrics; coordinated rings can game it **(secondary)**.
**Adapt.** Confirms that vouch graphs plus human review (Aura's "experts") work better than either alone. Matches sponsorship plus ballot.
[BrightID repo](https://github.com/BrightID/BrightID) · [Aura: how it works](https://brightid.gitbook.io/aura/background/how-aura-works)

**Proof of Humanity (Kleros).** Registry entry needs a vouch and a deposit, then a 3.5-day challenge window judged by Kleros jurors; registrations expire after a year. Known abuse: "vouchallenges" (vouch for a fake to collect the challenge bounty).
**Adapt.** A public challenge window before admission is cheap and powerful. **Avoid** paying bounties for challenges: rewards create the vouchallenge incentive. Keep sponsor penalties non-monetary (loss of sponsorship rights, as in Constitution Art. IV).
[Kleros PoH explainer](https://blog.kleros.io/proof-of-humanity-an-explainer) · [PoH FAQ](https://docs.kleros.io/products/proof-of-humanity/poh-faq) · [HIP-58 thread](https://gov.proofofhumanity.id/t/phase-2-hip-58-removal-of-vouchallengers-deprecated-version/2483)

**Idena.** Proof of personhood by simultaneous global "flip" puzzle ceremonies **(secondary; ceremony details unverified)**.
**Avoid.** Synchronous ceremonies exclude people across time zones and are a poor fit for an asynchronous, Git-paced institution.
[BrightID vs Idena (secondary)](https://www.chainscorelabs.com/comparisons/dao-governance-on-chain-vs-off-chain/sybil-resistance-and-identity/brightid-vs-idena)

**Worldcoin / World.** Iris-scanning "Orb" personhood. MIT Technology Review reported deceptive recruitment and weak consent; Kenya paused it, Spain's AEPD ordered it to stop collecting biometrics (March 2024), others investigated.
**Avoid.** Biometrics contradict the whitepaper's minimal-personal-data stance (§5.4) and create regulatory exposure (data-protection laws such as the GDPR treat biometrics as sensitive data).
[Cryptobriefing summary of MIT TR](https://cryptobriefing.com/worldcoins-shady-history-and-data-collection-practices-mit-technology-review) · [Techloy: Kenya suspension](https://techloy.com/kenya-suspends-worldcoin-project-over-data-privacy-concerns)

**Circles UBI.** Personal currencies connected by a trust graph; users exchange currencies along trust edges; v2 adds group currencies. Minting rates differ between sources **(unverified)**.
**Avoid the money, note the graph.** Its trust graph is a Sybil-resistance device whose security depends on people trusting carefully, like vouching. A currency is out of scope for OpenMasonry.
[CirclesUBI/docs whitepaper](https://github.com/CirclesUBI/docs/blob/master/Circles.md) · [docs.aboutcircles.com](https://docs.aboutcircles.com/llms-full.txt)

**Gitcoin Passport / Human Passport.** Aggregates "stamps" (verifiable credentials of activity elsewhere) into a humanity score, with partner-set thresholds; renamed Human Passport (Dec 2024, per one source).
**Adapt (as optional evidence only).** A petition could attach optional external proofs (GitHub account age, Keybase-style site proofs) as *information for electors*, never as an automatic gate or score.
[Human Passport docs](https://docs.passport.xyz/overview)

---

## 4. Secret ballots

**MACI (PSE).** Voters send encrypted, signed messages to a coordinator, who publishes a tally with a zk-SNARK proof of correct processing. Voters can secretly change keys, so a briber cannot know whether a bribed vote counted. The coordinator can still see key changes and is trusted for privacy, not for correctness.
**Adapt for v0.3.** This is the target named in §6.1. Two changes for OpenMasonry: (1) replace the single coordinator with a threshold of Keepers (4°) so no one person sees decrypted votes; (2) the tally proof lands as a ledger entry the Tyler checks. Proof-system dependencies conflict with the "stdlib only" rule of the Python verifier, so verification may live in `om` only. That is a governance decision to make explicitly.
[MACI v0.x intro](https://maci.pse.dev/docs/v0.x/introduction) · [MACI 1.0 technical introduction](https://maci.pse.dev/blog/maci-1-0-technical-introduction)

**Helios (Adida, USENIX Security 2008).** Web-based open-audit voting with homomorphic encryption and distributed decryption keys; first used for a UCLouvain presidential election.
**Adapt.** Proof that verifiable, encrypted tallying can be simple enough for real organizations. Its known weaknesses are coercion resistance and, before Belenios, ballot stuffing by the server.
[Harvard SEAS on Helios](https://seas.harvard.edu/index%2ephp/news/computer-scientists-deploy-first-practical-web-based-secure-verifiable-voting-system) · [Intro to e-voting (arXiv:2602.12398)](https://arxiv.org/pdf/2602.12398)

**Belenios.** Helios descendant adding eligibility verifiability (credentials prevent ballot stuffing) and Pedersen threshold decryption; used in hundreds of elections.
**Adopt (design reference).** Closest fit to OpenMasonry: the ledger already provides eligibility (who may vote), and threshold decryption by Keepers matches §6.1. A Belenios-style homomorphic yes/no tally is simpler than zk-SNARKs for binary ballots: worth comparing against MACI before choosing.
[glondu/belenios](https://github.com/glondu/belenios) · [HAL: Belenios](https://hal.archives-ouvertes.fr/hal-02066930v1/html_references)

**Semaphore (PSE).** Zero-knowledge proof of membership in a Merkle group with a nullifier preventing double signaling; used for anonymous voting and signaling.
**Adapt (narrow).** Useful for *anonymous* acts that still must be one-per-member: whistleblowing to the Kadosh Watch (30°), anonymous grievances. Not for ballots where electorate rules depend on degree, unless degree-specific groups are maintained.
[Semaphore docs](https://docs.semaphore.pse.dev/V3) · [Semaphore V2 proofs](https://docs.semaphore.pse.dev/V2/guides/proofs)

**Receipt-freeness and coercion resistance.** Benaloh–Tuinstra (1994) introduced receipt-freeness (a voter cannot prove how they voted); Juels–Catalano–Jakobsson (WPES 2005) defined the stronger coercion resistance. An ePrint number sometimes given for it (2002/165) could not be confirmed **(unverified)**.
**Adopt as a stated goal.** Current commit–reveal is *not* receipt-free: the salt is a receipt. The roadmap should say so plainly and list receipt-freeness as the v0.3 acceptance criterion, not just "encrypted".
[Overview of E2E verifiable voting (arXiv:1605.08554)](https://arxiv.org/pdf/1605.08554) · [JCJ paper (author copy)](https://www.arijuels.com/wp-content/uploads/2013/09/JCJ05.pdf)

---

## 5. Sortition and public randomness

**Flanigan, Gölz, Gupta, Hennig, Procaccia, "Fair algorithms for selecting citizens' assemblies" (Nature 596, 2021).** Selection algorithms that satisfy demographic quotas while keeping individual selection probabilities as equal as possible (leximin); used for 40+ assemblies; available free via Panelot.
**Adapt.** Plain uniform lot is right while the fraternity is small. Once houses have quotas (e.g., Council seats across houses or regions), use a maximin/leximin distribution and publish it, then sample from it with the beacon. Distribution computation is deterministic and checkable; sampling is the beacon's job.
[Nature paper (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8387237/) · [Harvard SEAS](https://seas.harvard.edu/news/2021/08/can-ai-make-democracy-fairer)

**Sortition Foundation `sortition-algorithms`.** Python library with maximin, leximin, nash and other methods; leximin needs Gurobi (commercial/academic license).
**Avoid the dependency, keep the idea.** A solver-dependent draw cannot be replayed by any member with a stock toolchain. If quotas arrive, prefer maximin with an open LP solver, or precompute the distribution and pin its hash in an amendment.
[PyPI sortition-algorithms](https://pypi.org/project/sortition-algorithms/) · [Concepts](https://sortitionfoundation.github.io/sortition-algorithms/concepts)

**drand / League of Entropy.** Threshold BLS randomness beacon. `quicknet` is unchained (round signature over SHA-256(round)), 3 s period, RFC 9380-compliant G1 signatures, G2 public key; unpredictable unless a threshold of nodes collude (12 of 22 at launch). Docs advise using client libraries or verifying every value manually.
**Adopt, and verify offline.** Today `src/openmasonry/beacon.py` re-fetches rounds to compare; `om` should *verify the BLS signature* against the pinned quicknet chain hash and public key, so lot audits need no network. Keep the two-step "fix the future round first" rule (§8.3).
[drand developer docs](https://docs.drand.love/developer/) · [quicknet is live](https://docs.drand.love/blog/2023/10/16/quicknet-is-live) · [drand/drand](https://github.com/drand/drand)

**Verifiable Delay Functions (Boneh, Bonneau, Bünz, Fisch, CRYPTO 2018).** Functions needing a fixed number of sequential steps, with fast public verification; proposed for unbiasable beacons.
**Not now.** drand already gives unpredictability under a threshold assumption. A VDF over the drand output is a fallback if the League of Entropy ever becomes untrusted; keep it as a roadmap note, not a dependency.
[IACR ePrint 2018/601](https://eprint.iacr.org/2018/601) · [Survey, ePrint 2018/712](https://crypto.stanford.edu/~dabo/abstracts/VDFsurvey.html)

---

## 6. Transparency logs and witnessing

**Certificate Transparency (RFC 6962 → RFC 9162).** Append-only Merkle logs with signed tree heads, inclusion and consistency proofs. RFC 9162 (CT v2.0, Experimental) obsoletes 6962.
**Adopt (already).** The verifier uses the RFC 6962 Merkle Tree Hash. `om` should also produce and check *inclusion proofs* (one entry against a checkpoint) and *consistency proofs* (old checkpoint is a prefix of new), which let light clients and agents verify without replaying everything.
[RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html)

**Trillian → Tessera / TesseraCT.** Tessera is a Go library for tile-based logs (Merkle tree served as static, cacheable tiles plus checkpoints), the successor to Trillian; TesseraCT implements the static CT API.
**Adapt.** Tiles map naturally onto Git: the ledger could publish `tiles/` and `checkpoint` files so any static host (GitHub Pages, IPFS) serves proofs. Use Tessera as a reference, not necessarily a dependency.
[Introducing Trillian Tessera](https://blog.transparency.dev/introducing-trillian-tessera) · [Introducing TesseraCT](https://blog.transparency.dev/introducing-tesseract)

**C2SP signed-note, tlog-checkpoint, tlog-cosignature, tlog-witness.** Small specs: a signed note is text plus signature lines; a checkpoint is a note whose body is origin, tree size and root hash; a cosignature is a witness's timestamped Ed25519 signature (header `cosignature/v1`); clients require a quorum of cosignatures against split views. The tlog-witness protocol text itself was not read **(unverified details)**.
**Adopt.** Make OpenMasonry `witness` entries *also* emit a C2SP checkpoint and accept C2SP cosignatures. Then existing public witness networks (below) can cosign OpenMasonry's log for free, raising `n` beyond the fraternity's own operators.
[signed-note](https://www.github.com/C2SP/C2SP/blob/main/signed-note.md) · [tlog-cosignature](https://www.github.com/C2SP/C2SP/blob/main/tlog-cosignature.md) · [tlog-checkpoint](https://vat.pages.dev/C2SP/C2SP/blob/main/tlog-checkpoint.md)

**Sigsum.** Minimal transparency log for signed checksums; trust policies list witnesses and a quorum (e.g., 2-of-N); a single cosignature only says the witness saw that tree head and can detect later inconsistency.
**Adopt the policy format idea.** Express the witness quorum (`2f+1` of `n`) as a declarative, governed policy file, and be precise about what one cosignature does and does not prove.
[sigsum-witness man page](https://manpages.debian.org/unstable/sigsum-go/sigsum-witness.1.en.html) · [Meaning of a single cosignature?](https://lists.sigsum.org/mailman3/hyperkitty/list/sigsum-general@lists.sigsum.org/thread/DBWCT2AMV2A3VQFG5CKQA4GEE6LJ4HNV/)

**OmniWitness / ArmoredWitness.** transparency.dev witness networks that cosign many logs (Sigsum, Go SumDB, Sigstore); ArmoredWitness adds dedicated hardware with custodians (15 devices reported).
**Adapt.** A route to Byzantine tolerance before the fraternity has 4 operators: ask existing networks to witness the log. Caveat: they attest consistency only, never protocol validity (they do not replay the rules), so they complement, not replace, member-run witnesses.
[Can I get a witness network?](https://blog.transparency.dev/can-i-get-a-witness-network)

**OpenTimestamps.** Calendars aggregate hashes into a Merkle tree anchored in a Bitcoin transaction; proofs start "pending" and are upgraded with `ots upgrade`; verification needs the file, the `.ots` proof and Bitcoin block headers. A calendar can withhold service but not forge time.
**Adopt (already).** Recommendations: stamp with at least two independent calendars; store upgraded proofs in the repo; `om verify --anchors` should check proofs against block headers from a user-chosen source.
[opentimestamps.org](https://opentimestamps.org/) · [Peter Todd's announcement](https://petertodd.org/2016/opentimestamps-announcement)

---

## 7. Soulbound tokens and attestations (inputs for Patron Seals)

**Ohlhaver, Weyl, Buterin, "Decentralized Society: Finding Web3's Soul" (SSRN 4105763, 2022).** Proposes non-transferable "soulbound" tokens recording commitments, credentials and affiliations of "Souls", for Sybil-resistant governance, community key recovery and correlation-adjusted QF. Critics objected to permanent public identity records.
**Adapt.** Patron Seals are SBTs in spirit: a public, non-transferable record that someone gave. Take the critique seriously: allow anonymous or pseudonymous seals, let a patron hide or revoke their own seal, and never put personal data in it.
[SSRN 4105763](https://papers.ssrn.com/abstract=4105763) · [Cointelegraph on reception](https://cointelegraph.com/features/struggle-for-web3-s-soul-the-future-of-blockchain-based-identity)

**ERC-5192 (Minimal Soulbound NFTs).** A `locked()` signal plus `Locked`/`Unlocked` events on ERC-721; status Final.
**Adapt only if seals are ever mirrored on-chain.** Locking is a signal; it does not by itself prevent one address from receiving many seals or a patron from selling the *wallet*.
[ERC-5192](https://eips.ethereum.org/EIPS/eip-5192)

**ERC-5484 (Consensual Soulbound Tokens).** Non-transferable tokens with burn authorization fixed at issuance (`BurnAuth`: issuer, owner, both, neither); EIP page status shown inconsistently across sources **(unverified)**.
**Adopt the semantics.** Seal entries should fix revocation rules at issuance: the patron can always burn (privacy, GDPR-style erasure of the link to their identity); the fraternity can revoke only for fraud or chargebacks, by ballot.
[ERC-5484](https://eips.ethereum.org/EIPS/eip-5484)

**Ethereum Attestation Service (EAS).** A schema registry plus attestations under a schema, on-chain or off-chain (EIP-712-signed JSON never submitted on-chain), revocable by UID.
**Adapt.** "Off-chain signed attestation under a registered schema" is what a ledger entry already is. Model a seal as a ledger entry of type `seal` with a governed schema; optionally publish an EAS off-chain attestation mirror for wallets that understand it. No chain needed.
[EAS docs](https://easscan.org/docs) · [EAS SDK README](https://cdn.jsdelivr.net/npm/@ethereum-attestation-service/eas-sdk@2.9.1/README.md)

**Hypercerts.** Records of completed impact work that funders can back; now documented on AT Protocol; recorded funding can come from any rail.
**Adapt for retroactive grants.** Issue a non-financial "work certificate" ledger entry for each funded masterwork (who built it, which PRs, which grant paid), so grants are auditable against delivered work. Do not let them be fractionalized or traded.
[hypercerts-org](https://github.com/hypercerts-org) · [Hypercerts docs (v0.2 mirror)](https://hypercerts-v02-documentation.vercel.app)

---

## 8. Regulatory notes on tokens for fundraising (not legal advice)

**Howey and the SEC.** An investment contract exists where money is invested in a common enterprise with an expectation of profit from others' efforts. The 2019 SEC staff "Framework" applied this to digital assets; it was **withdrawn** and superseded by the SEC–CFTC interpretive release of March 17, 2026, which uses a five-part taxonomy (digital commodities, collectibles, tools, stablecoins, securities). Law-firm summaries say the release names non-transferable soulbound tokens such as credentials as examples of "digital tools" **(secondary)**. Any asset can still be sold as part of an investment contract.
**Lesson:** a seal stays far from Howey only if there is no expectation of profit at all: no resale, no yield, no treasury claim, no promotion as an investment, no price. Non-transferability helps but is not sufficient alone.
[SEC: 2019 Framework (withdrawn)](https://sec.gov/corpfin/framework-investment-contract-analysis-digital-assets) · [Sidley on the 2026 release](https://datamatters.sidley.com/2026/03/24/sec-releases-landmark-interpretation-on-application-of-u-s-securities-laws-to-crypto-assets-in-coordination-with-cftc/) · [Federal Register 2026-05635](https://www.govinfo.gov/content/pkg/FR-2026-03-23/html/2026-05635.htm)

**The EU (MiCA).** MiCA classifies assets by function (payment, utility, asset-referenced) and leaves anything that qualifies as a financial instrument to securities law, judged on economic substance; the answer can change over a project's life. It also licenses crypto-asset service providers (custody, exchange).
**Lesson:** a donation receipt with no rights and no market should fall outside, but regulators look at substance and marketing case by case, so the seal paper must avoid any language of return, appreciation or "investment". Taking donations in ordinary currency through a regulated payment rail or fiscal host avoids being a service provider; holding or converting crypto would raise the question.

---

## 9. Agent-facing conventions and the Go toolchain

**AGENTS.md.** Plain Markdown with project context for coding agents (overview, build/test, style, security); nearest file in the tree wins; explicit user prompts override it. Stewarded by the Agentic AI Foundation (Linux Foundation) since Dec 2025, read by many coding agents.
**Adopt.** Ship a root `AGENTS.md` as the one canonical text (other agent instruction files point to it), plus nested ones in `ledger/` ("never edit entries; use `om`") and `canon/` ("governed; amendment only").
[agents.md](https://agents.md/)

**llms.txt.** Proposal (Jeremy Howard, Sept 2024): `/llms.txt` with H1 name, blockquote summary, then H2 sections of Markdown link lists; optional `.md` copies of pages and `llms-full.txt`. Real consumption by major providers is disputed.
**Adopt (cheap).** Publish `llms.txt` on the state page listing the whitepaper, Constitution, ledger spec, `om` docs and MCP tool list. Low cost, low risk, no reliance.
[llmstxt.org](https://llmstxt.org/)

**Agent Skills (SKILL.md).** The open Agent Skills format (agentskills.io, Dec 2025): a folder with `SKILL.md` (frontmatter `name` ≤64 lowercase-hyphen chars matching the folder, `description` ≤1024 chars) plus optional `scripts/`, `references/`, `assets/`; progressive disclosure (metadata always, body <5k tokens on activation). Supported by several agents **(adoption counts secondary)**.
**Adopt.** Ship the officers as skills (`om`, `om-counselor`, `om-secretary`, `om-wardens`, `om-almoner`, `om-tyler`) that drive the `om` CLI or MCP tools; validate them with `skills-ref` in CI. Skills teach *procedure*; normative rules stay in the whitepaper and verifier.
[Agent Skills specification](https://agentskills.io/specification)

**Model Context Protocol (MCP).** Latest spec revision is 2026-07-28 per the Go SDK README; 2025-11-25 is still widely implemented. The security best practices require: no token passthrough, consent before local server installs, and for local servers the stdio transport (or an authenticated HTTP/unix socket). Tool annotations (`readOnlyHint`, `destructiveHint`) are hints clients must not trust for security **(annotation guidance secondary)**.
**Adopt.** `om mcp` over stdio by default; read-only tools (status, verify, explain, proofs) separate from tools that *prepare* a signed entry; the MCP server never holds or sends private keys and never auto-merges.
[MCP security best practices (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices) · [MCP tool annotations IG](https://modelcontextprotocol.io/community/tool-annotations/charter)

**Official Go MCP SDK (`modelcontextprotocol/go-sdk`).** Maintained with Google; packages `mcp`, `jsonrpc`, `auth`, `oauthex`; `mcp.AddTool` derives input/output JSON Schema from typed Go structs; `server.Run(ctx, &mcp.StdioTransport{})`. v1.7.0+ supports spec 2026-07-28.
**Adopt.** Typed tool structs give one source of truth for CLI flags, MCP schemas and docs. Pin a released SDK version and track spec deprecations (roots, sampling, logging deprecated in 2026-07-28).
[modelcontextprotocol/go-sdk](https://github.com/modelcontextprotocol/go-sdk) · [pkg.go.dev mcp](https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0-pre.3/mcp) · [Go SDK quick start](https://go.sdk.modelcontextprotocol.io/quick_start/)

**Cobra (`spf13/cobra`).** De facto Go CLI framework (kubectl, Hugo, gh), POSIX flags via pflag, generated completions and docs; Apache-2.0.
**Adopt.** Standard subcommand tree; also generate man pages and Markdown docs from the command tree so humans and agents read the same reference.
[spf13/cobra](https://github.com/spf13/cobra)

**OpenSSH SSHSIG (`PROTOCOL.sshsig`).** Signed blob = `"SSHSIG"` ‖ namespace ‖ reserved ‖ hash algorithm ‖ H(message); hash is `sha256` or `sha512`; namespace must be non-empty and prevents cross-protocol reuse; armored as `BEGIN SSH SIGNATURE`.
**Adopt (exactly).** `om` signs with `ssh-keygen -Y sign -n openmasonry` and accepts exactly the signatures the specification defines as valid (SPEC §13: one accepted form per signature, checked without OpenSSH), tested against the conformance vectors. Two key types are accepted: `ssh-ed25519` and the hardware-backed `sk-ssh-ed25519@openssh.com`.
[PROTOCOL.sshsig](https://raw.githubusercontent.com/openssh/openssh-portable/master/PROTOCOL.sshsig)

**SSHSIG in Go.** `golang.org/x/crypto/ssh` historically lacked SSHSIG; proposal golang/go#68197 was **accepted** (Aug 2025) with a `Sign`/`Verify` API (sign sha512, verify sha256/sha512, reject `ssh-rsa`); implementation PR golang/crypto#316 was still open when checked **(merge status unverified)**. Third-party options: `hiddeco/sshsig` (Apache-2.0, v0.2.0, Apr 2025), `42wim/sshsig`.
**Adopt with a seam.** Hide signing behind an internal `sig` interface; use x/crypto's API if released, else `hiddeco/sshsig` or ~150 lines over `x/crypto/ssh` + `crypto/ed25519`. Signing should prefer `ssh-agent` so `om` never reads private key files.
[golang/go#68197](https://github.com/golang/go/issues/68197) · [hiddeco/sshsig](https://pkg.go.dev/github.com/hiddeco/sshsig) · [42wim/sshsig](https://pkg.go.dev/github.com/42wim/sshsig)

**Go `crypto/ed25519`.** Standard-library Ed25519 (RFC 8032) sign/verify; no external dependency. API not re-checked for this survey **(unverified)**.
**Adopt** for raw verification inside the SSHSIG layer and for witness cosignatures in C2SP format.
[pkg.go.dev crypto/ed25519](https://pkg.go.dev/crypto/ed25519)

**GoReleaser + SLSA + reproducible builds.** GoReleaser documents reproducible builds (`CGO_ENABLED=0`, `-trimpath`, `mod_timestamp` from commit time; pinning the Go version is left to you) and SLSA provenance via `slsa-github-generator` (Sigstore-signed `.intoto.jsonl`). `-trimpath` removes absolute paths that break byte equality.
**Adopt.** Witness operators should *rebuild* `om` from the tagged commit and cosign the binary hash; a release is "blessed" when ≥ 2 independent rebuilds match. That turns the witness network into a reproducible-build check for its own software.
[GoReleaser: reproducible builds](https://goreleaser.com/blog/reproducible-builds/) · [GoReleaser: SLSA generation](https://goreleaser.com/blog/slsa-generation-for-your-artifacts/) · [slsa-github-generator Go builder](https://github.com/slsa-framework/slsa-github-generator/blob/v2.0.0/internal/builders/go)

---

## Design decisions this research supports

**CLI and MCP architecture**

1. **Two independent verifiers, one spec.** Keep the Python stdlib verifier as reference and make `om` (Go) a second implementation. CI replays the ledger with both and fails on any divergence: two implementations catch bugs that one hides (CT and Debian both rely on independent checking). The Go binary never becomes the only judge.
2. **Pure rules in Go mirror `ledger.py`.** `replay(entries) → (state, errors)` is pure; Git, GitHub, network, ssh-agent and the MCP transport stay outside it. MCP tools and CLI commands call the same rules (git-bug pattern: one binary, many front ends).
3. **Keys stay with the human.** `om` signs only through `ssh-agent` or `ssh-keygen -Y sign` (namespace `openmasonry`; Ed25519 only, plain or held by a hardware token). The MCP server can *prepare* an unsigned entry and show its canonical bytes and hash; the signature is a separate, human-approved step. MCP security guidance: no credential passthrough, consent before side effects.
4. **MCP over stdio by default.** Split tools into read-only (`status`, `verify`, `explain_rule`, `inclusion_proof`, `my_duties`) and preparatory (`draft_petition`, `draft_vote_commit`, `draft_reveal`); no tool merges, pushes, or reveals a vote without explicit user action. Do not rely on annotations for safety.
5. **Ballot secrets never touch the model context.** Salts and reveal material live in an OS keychain or a `0600` file under `~/.config/openmasonry/`, written by `om` itself. MCP tools return commitments, never salts. This is the concrete answer to "an agent votes for me" leaking the vote.
6. **Agent conventions as shipped artifacts.** Root and nested `AGENTS.md`, an `llms.txt` on the state page, and a `skills/` folder of officer skills (`om`, `om-onboard`, `om-counselor`, `om-secretary`, `om-wardens`, `om-almoner`, `om-tyler`), to be validated by `skills-ref` in CI.
7. **Light clients through proofs.** Add RFC 6962/9162-style inclusion and consistency proofs and C2SP checkpoints, so an agent or phone can check "my entry is in the canonical log" without full replay.
8. **Offline beacon verification.** Pin the drand quicknet chain hash and public key; `om verify` checks BLS signatures locally. Network only fetches missing rounds.
9. **Interoperable witnessing.** Emit C2SP `tlog-checkpoint` alongside `witness` entries and accept `tlog-cosignature`, so external networks (OmniWitness/ArmoredWitness, Sigsum witnesses) can add consistency cosignatures while member witnesses keep the validity role.
10. **Reproducible, attested releases.** GoReleaser with `-trimpath`, `CGO_ENABLED=0`, commit-time timestamps, pinned Go toolchain; SLSA provenance via `actions/attest`; witnesses rebuild and cosign release hashes.
11. **Governance analytics, not leaderboards.** `om audit` reports turnout, minimal deciding coalition per ballot, and vouch-graph trust rank from founding keys (SybilRank-style) for 31° auditors. Never rank members by influence in UI or MCP output.

**Roadmap**

12. **v0.2: `om` read path first** (verify, status, proofs, MCP read-only tools, skills), then write path (draft + sign via agent). The read path is safe to give agents on day one.
13. **v0.3 secret ballot with receipt-freeness as the acceptance criterion.** Compare a Belenios-style threshold-homomorphic yes/no tally (Keepers hold shares) with MACI before choosing; document that today's salt is a receipt.
14. **Public challenge window for petitions** (PoH lesson): a fixed period after vouching in which any member can object with evidence, with no monetary bounty.
15. **Roles as eligibility/toggle functions** (Hats lesson): express degrees, offices, terms and one-seat-per-lifetime as pure predicates, tested exhaustively like the decision function D.
16. **Quota-aware sortition later.** Keep uniform lot until houses need quotas; then adopt a published maximin/leximin distribution (Flanigan et al.) computed with an open solver and pinned by hash.

**Patron Seals**

17. **Seals are ledger entries, not chain tokens.** Type `seal` under a governed schema (EAS-style); non-transferable by construction because the ledger binds them to a key and has no transfer operation. Optional read-only mirrors (EAS off-chain attestation, ERC-5192 locked NFT) only if the community wants them.
18. **No rights, ever.** A seal grants no vote, degree, office, sponsorship, Light, treasury claim, refund right, or priority. Encode this as a Landmark-level rule checked by the Tyler (a `seal` entry can never be an input to electorate, eligibility or Light functions). This is the Aragon and Moloch lesson.
19. **Donors do not allocate.** Grants (witness costs, audits, retroactive masterwork grants) are decided by a small panel drawn by lot from Masters with a pre-published rubric and verifiable deliverables (merged PRs, ledger entries), followed by an amendment-rule ratification. No QF, no donor voting (Gitcoin and Optimism lessons).
20. **Fiat-first treasury through a fiscal host or nonprofit, published as ledger entries.** Each donation and each disbursement becomes a signed entry with an external receipt hash. Avoid holding or converting crypto in v1 (virtual-asset service-provider exposure) and avoid all language of return or appreciation (Howey, MiCA). Patrons may be pseudonymous and may burn their own seal (ERC-5484 owner-burn semantics, data-protection erasure).

---

## Risks

- **Key custody by agents.** If users paste private keys or salts into an agent, the security model collapses. Mitigation: agent-only signing, keychain-held salts, and tools that refuse to accept key material.
- **Prompt injection through the ledger.** Petitions, issue bodies and PR text are attacker-controlled and reach the model via MCP. A malicious petition could instruct an agent to vote. Mitigation: MCP results label user content as data; vote tools require the human to confirm the ballot ID and choice outside the model.
- **Implementation divergence.** Two verifiers can disagree on canonical JSON, Unicode, or integer edge cases, and a divergence is a fork. Mitigation: shared conformance vectors (`tests/vectors/`), a state digest in every checkpoint, cross-replay in CI, and a rule of precedence: the reference code decides what the ledger accepts, and the specification states it.
- **Dependency drift in Go.** SSHSIG in x/crypto is accepted but may not be merged; MCP spec revisions deprecate features (2026-07-28 deprecated roots, sampling and logging). Mitigation: internal interfaces, pinned versions, a quarterly dependency review entry in the roadmap.
- **Encrypted ballots raise the trust and complexity bar.** Threshold keys need live Keepers; zk systems need trusted setups or heavy dependencies that conflict with "stdlib only". Risk of shipping "encrypted" without receipt-freeness.
- **Witness monoculture.** External witness networks attest consistency, not validity. Mistaking their cosignatures for protocol approval would weaken the Byzantine argument in §8.2.
- **drand trust assumption.** A colluding threshold of League of Entropy nodes could bias lots. Residual and accepted, but it should be stated in the threat model with the VDF fallback note.
- **Patron Seals sliding toward a financial product.** Any later feature (seal tiers with perks, transferability, "early patron" bonuses, treasury yields) would invite securities analysis under Howey and comparable regimes, and would recreate the Aragon dynamic. Guard against it by Landmark-level rules and a review checklist before any seal change.
- **Plutocracy by reputation.** Even without votes, large patrons gain soft influence (visibility, access). Mitigation: show seals without amounts by default, or in bands; forbid patrons from sitting on the grant panel for rounds that fund their own proposals.
- **Regulatory and privacy uncertainty.** The SEC 2026 release is interpretive and may change; virtual-asset licensing regimes are new in several jurisdictions; data-protection law applies to donor data. Get counsel before launch; this document is not legal advice.
- **Research gaps.** Not read directly: several regulators' official texts, the tlog-witness spec, the full SoK attack categories, the Moloch v2 whitepaper, a SourceCred post-mortem, and Idena primary docs. Follow up before citing any of these as normative.
