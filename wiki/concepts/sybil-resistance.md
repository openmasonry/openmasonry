---
title: "Sybil Resistance"
type: concept
tags: [protocol, sybil, security, sponsorship, identity]
sources:
  - src/openmasonry/ledger.py
  - src/openmasonry/canon.py
  - src/openmasonry/identity.py
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/proto-sybillimit-2008.md
---

# Sybil Resistance

In a Sybil attack, someone creates many fake identities to outvote the honest members. With no token and no proof of work, OpenMasonry must limit this attack in another way. The tradition already had the tool: **sponsorship**, in which a proposer and a seconder stake their own reputation.

## The four costs (whitepaper §5.3) and the code
1. **Only Masters sponsor.** `invite` and `vouch` both require `degree ≥ SPONSOR_MIN_DEGREE = 3` (`ledger._invite`, `ledger._vouch`; `canon.SPONSOR_MIN_DEGREE`). Reaching Master takes ≥ 90 days and two exams conducted by other members.
2. **Sponsorship budget.** The limit is `b = SPONSOR_BUDGET_PER_YEAR = 4` (`canon.SPONSOR_BUDGET_PER_YEAR`). The budget counts the members admitted in the last 365 days who have the actor as a sponsor and have not departed since, **plus the petitions still alive that the actor sponsors** (less than 180 days old, or with an admission ballot open) **and the actor's own live invitations** (`ledger.sponsorships`, checked for an invitation and a vouch alike in `ledger._sponsor_checks`). A petition not admitted within 180 days lapses and frees its sponsors; an invitation with no petition within 30 days lapses (`INVITE_EXPIRY_DAYS`), but it still counts against its inviter for 90 days after it lapsed, so that inviting and letting invitations lapse cannot be repeated without limit. A login that names a custodian, or that a pending claim of the Custodian office names, cannot be invited. With `SPONSORS_REQUIRED = 2` sponsors per admission, `s` colluding Masters can admit at most `⌊s·b/2⌋ = 2s` identities per year (Appendix C.3).
3. **The ballot.** A candidate is rejected when `5B ≥ T`. With `h` honest members voting no, a hostile admission needs **`a > 4h`** (Appendix C.2; see [[decision-function]]).
4. **Time.** New identities start at the 1st degree and need ≥ 90 days before they can sponsor (see [[waiting-period]]).

**Required sponsors** (`ledger.sponsors_required`, checked in `ledger._open_admission`), and only one of them may open the admission ballot:
- outside the Founding Phase, always **2**;
- inside it, `max(1, min(2, active Masters))`, which allows growth from a single Master and never requires zero; and **1** once the petition has been live 30 days, so that a second Master who never answers holds no door shut. Every other Master still votes on the admission, and the blackball stands.

The inviter is the first sponsor (`ledger._petition`), so one `vouch` from another Master completes the two, and with a single Master the inviter alone suffices. A sponsor answers for the candidate's identity, adulthood and good faith, not for their opinions (Constitution Art. IV.3).

## The closed door of the ledger
Any adult may apply, but an application is a public issue of the repository, outside the ledger, and gives no right. Every candidate enters through a Master Builder who answers for them: a Master invites, and thereby sponsors, and a `petition` is valid only under a live invitation for exactly that login (`ledger._invite`, `ledger._petition_checks`). So no outsider writes to the ledger: a person who is not a member signs exactly one entry, a petition under a live invitation. A stranger cannot fill the ledger with petitions; spam can reach only the issue tracker. Invitations draw on the same budget as vouches.

## Relation to SybilLimit
Yu et al. (2008) show that defenses based on trust edges accept O(log n) Sybils per **attack edge**, that is, per deceived honest human. They also show that any defense based on graph mixing must accept at least Ω(1) per edge. OpenMasonry does not implement random walks. Instead, the budget `b` makes the cost per edge explicit and small.

## Identity
A member *is* a GitHub login bound to a key (**`ssh-ed25519`**, or the hardware-backed **`sk-ssh-ed25519@openssh.com`**) recorded by the petition (`ledger._signer`, `ledger._petition`) and to the numeric id of the GitHub account named in the invitation (`github_id`), which the petition carries and the admitted member keeps. **One GitHub account is one member:** an invitation is refused when its `github_id` already belongs to a member of any status, a live invitation or a pending petition under another login, and two founders cannot share one (`State.id_holders`, `ledger._invite`, `ledger._genesis`). The login follows GitHub's rules and is compared case-insensitively everywhere: an invitation or a petition whose login collides, up to case, with another member, a witness, another live invitation or another pending petition is refused (`State.name_holders`, `ledger._invite`, `ledger._petition_checks`). A witness name can never become a member login. There can be only one live invitation and one live petition per candidate. Someone who departed (`depart`), or whose admission was undone by a correction, may be invited again after 90 days; someone expelled, after 365 (`ledger.may_return`, checked when the invitation is signed and again at the petition). The person is the GitHub account, not the login: a returning record inherits the founder mark, past seats, a sponsorship ban, the record of fraud and a suspension still running only when it comes back under the same account. A refused candidate, or one whose petition lapsed, also needs a new invitation. If the GitHub account is later compromised, that does not change the key: only the member's current key can replace it, with a `rekey` entry that the new key also signs (`ledger._rekey`; once in 30 days, and a replaced key never returns). A lost or stolen key is recovered through peers, never by a single hand, and never needs a Custodian: the member asks with a new key (`ledger._rekey_recover`); Master Builders co-sign (`ledger._rekey_cosign`), two after a Custodian froze the old key, three otherwise and not all of them the member's sponsors, or as many as exist; a notice of 21, 30 or 45 days runs, in which the old key can stop the recovery once (`ledger._rekey_object`) and, for a recovery without a freeze, the Master Builders can oppose it (`ledger._rekey_oppose`); then the new key completes it (`ledger._rekey_recover_apply`). The protocol defines no revocation of a key by ballot.

The judge's online gate (`identity.pr_problems`) adds what replay cannot see: for an `invite`, the invited login must today be the GitHub account with the stated numeric id; for a `petition`, the pull request must come from that same account, and the key must be listed at `github.com/<login>.keys`; for a `rekey` or a recovery, the pull request must come from the account the ledger records for the member, with the new key listed there. A network failure fails closed.

## When an admission was a fraud
Two remedies exist, and they differ. A **sanction ballot** with the measure `expel_for_fraud` is the members' judgment: it expels, and within 730 days of the admission it suspends each sponsor's right to sponsor for 730 days. An **`undo_ballot` correction** is a repair, not a judgment: until the [[founder-sunset]], a Custodian may undo an admission closed within the last 90 days, on a closed ground such as `identity_fraud`, after 14 days of notice and unless Master Builders object. It leaves the record `voided`, bans no sponsor and records no fraud; where fraud is alleged, only a sanction ballot may find it (Constitution Art. X.7; see [[custodian-and-corrections]]).

## Sponsors answer for fraud
- **Two-year ban.** The sanction measure `expel_for_fraud`, applied within 730 days of initiation, suspends each sponsor's right to sponsor for 730 days (`ledger._close_sanction`, checked in `ledger._sponsor_checks` for an invitation and a vouch alike; Constitution Art. IV.4).

## Known limits
- **Genesis.** Up to seven "puppet" founders could end the Founding Phase on day one. The defense is the publicity of the genesis (§9.2; see [[founder-sunset]]), and the judge accepts a genesis only from the founder's GitHub account (`founder_github_id` in `src/openmasonry/network.toml`). Founders never count toward the Sunset, which needs seven active Master Builders who are not founders.
- **One person, several accounts.** The protocol binds one GitHub account to one member; it cannot see a person who holds two accounts. That is what sponsors answer for, and what the ballot and the budget make costly.

See [[eternal-landmarks-of-openmasonry]] (I, III), [[dormancy]].
