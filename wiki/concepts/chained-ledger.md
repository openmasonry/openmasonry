---
title: "Chained Ledger (the Tracing Board)"
type: concept
tags: [protocol, ledger, hash-chain, signatures, verification]
sources:
  - src/openmasonry/ledger.py
  - src/openmasonry/crypto.py
  - docs/whitepaper/SPEC.md
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/proto-rfc6962-certificate-transparency.md
---

# Chained Ledger (the Tracing Board)

OpenMasonry's source of truth is an append-only directory of JSON files, one per entry, in shards of 1,000 (`ledger/entries/0000/000000.json`, …, `ledger/entries/0001/001000.json`, …). Each entry points to the hash of the previous one, is signed by its author and is valid only if the state produced by all earlier entries allows it. The whitepaper calls it a blockchain "in the only sense that matters here", because it has no token, no fee market and no mining. The symbolic name comes from the [[tracing-board]].

## Exact rules (code)
- **Validity is a pure function:**
  `valid(e₀…eₙ) ⇔ ∀i: sig_ok(eᵢ, key(Sᵢ₋₁, actorᵢ)) ∧ prevᵢ = H(eᵢ₋₁) ∧ rules(Sᵢ₋₁, eᵢ)`, with `Sᵢ = apply(Sᵢ₋₁, eᵢ)` (whitepaper §4.2).
- **Strict envelope:** every entry has exactly the fields `seq, prev, time, type, actor, body, sig`; `actor` must follow GitHub's login rules; `time` is UTC in the format `YYYY-MM-DDTHH:MM:SSZ` (`ledger.apply`, `ledger.ts`).
- **Strict entries:** the body of each entry type has an exact set of fields, each with one JSON type, and an unknown field refuses the entry (`ledger.BODY_FIELDS`). A value is a string, an integer within ±(2^53 − 1), a boolean, an array or an object; there is no float and no `null`, strings are ASCII, and nesting stops at 6 levels (`ledger.strict_value`, `ledger.MAX_DEPTH`; SPEC §2.2).
- **Case-insensitive logins:** GitHub logins are compared without regard to case (`ledger.same_login`). A petition, an admitted candidate or a new witness whose name equals an existing member, witness or pending petition up to case is refused (`State.login_taken`, `ledger._signer`, `ledger._ballot_open`). An invited login is held in the same way: a second invitation for it, or a petition under another spelling, is refused (`State.name_holders`, `ledger._invite`, `ledger._petition_checks`).
- **Strict text fields:** free-text fields are constrained. Ballot ids are 1 to 64 characters of `a-z 0-9 . _ -` starting with a letter or digit; work references and examiners' reasons are `http(s)` URLs without spaces or quotes; amendment paths use only letters, digits, `_ . - /` (or `@protocol`); the fraternity's name is 1 to 120 printable ASCII characters (`ledger.BALLOT_ID_RE`, `ledger.URL_RE`, `ledger.PATH_RE`, `ledger.NAME_RE`).
- **Sequence:** `seq == st.seq + 1`, and entry 0 is the genesis, and only entry 0 is (`ledger.apply`).
- **Chaining:** `prev == st.head`; a mismatch raises "prev does not match head (history was altered)" (`ledger.apply`). The initial head is `canon.ZERO_HASH = "0"*64`.
- **Monotonic time:** `now >= st.time` (`ledger.apply`).
- **Signature:** an entry's `sig` is a signature in OpenSSH's signature format, in the namespace `openmasonry` (`canon.NAMESPACE`). **What counts as a valid signature is defined by the protocol itself**, in pure Python: `crypto.signature_valid` (behind `crypto.verify`) reads no file and runs no program, accepts exactly one spelling of each signature (canonical armor, fixed hash, the embedded key equal to the key the ledger holds, a canonical Ed25519 scalar) and gives the same verdict on every platform (SPEC §13). OpenSSH is used only to *make* signatures (`crypto.sign`); the verifier never calls it. Only bare keys of two types, with no options or comment, are accepted for founders, witnesses, custodians, candidates, proposed witnesses and the new key of a `rekey` or of a recovery (`ledger.ed25519`): **`ssh-ed25519 <base64>`**, and **`sk-ssh-ed25519@openssh.com <base64>`**, the same kind of key held by a hardware token, whose signatures count only with the token's user-presence flag. The signed payload is the canonical JSON **without** `sig` (`ledger.signed_payload`).
- **Entry hash:** `H = SHA-256` of the canonical JSON **with** `sig` (`ledger.entry_hash`). Canonical JSON has sorted keys, `,` and `:` separators and no whitespace; it refuses a float, a `null` or an integer out of range, so nothing outside the rules is ever hashed or signed (`crypto.canonical`).
- **Who signs:**
  - `genesis`: the first founder; it also names the witnesses and, with a proof by each of their two keys, at most three Custodians;
  - `petition`: the key declared by the candidate themselves, valid only under a live invitation for exactly that login (an `invite` entry signed by a Master Builder, which lapses after 30 days), one live petition at a time (it lapses after 180 days). It is one of the two cases in which a key the ledger does not yet hold signs an entry; the other is the recovery of a member's key (`rekey_recover` and its application), which Master Builders co-sign and which waits out a public notice of 21, 30 or 45 days (see [[custodian-and-corrections]]);
  - `witness`, `ballot_close`, `exam_draw` and `council_draw`: may be signed by a registered witness;
  - `correction`, `correction_cosign`, `correction_apply`, `correction_withdraw` and `custodian_alive`: a custodian key named in the genesis or by an applied founder's claim, while it is live; `custodian_revoke`: that Custodian's revoke key (see [[custodian-and-corrections]]);
  - `depart`, `rekey` and `rekey_object`: the member, also while suspended, frozen or during a halt;
  - everything else: an active member only.

  The rules are in `ledger._signer`, `ledger.WITNESS_TYPES` and `ledger.CUSTODIAN_SIGNED`.
- **Bounded writing:** an actor has at most 20 counted entries in a UTC day; departures, key replacements and recoveries, objections, votes, closes and draws, and the entries of an amendment ballot or of the ballot that removes a Custodian are never counted (`ledger.daily_exempt`; SPEC §5.4).
- **Drafted, then approved by a person:** the member CLI never signs on its own. Every act (`om vote`, `om exam`, `om recuse`, …) only writes a draft; `om approve` shows the exact entry to the person in an operating-system dialog, and only their approval signs it and opens the pull request (`actions.cmd_approve`).
- **Malformed entries:** a missing key, a wrong type and the like become `Invalid` instead of crashing the verifier (`ledger.apply`). The loader is strict: files must be regular files (not symlinks) named `NNNNNN.json` after their `seq`, each in its shard directory `NNNN` (`seq // 1000`, 1,000 entries to a shard); an entry is at most 8 KiB (`MAX_ENTRY_BYTES` = 8,192 bytes) and the genesis at most 32 KiB (`MAX_GENESIS_BYTES`), so long texts live in files pinned by hash; and JSON with duplicate keys, floats or constants such as `NaN` is refused (`ledger.load`, `ledger.strict_json`).
- **Replay:** `replay()` applies every entry from genesis and raises `Invalid` at the first violation (`ledger.replay`).
- **Append-only in CI:** the [[tyler]] rejects PRs that modify, rename or delete existing entries. It also rejects timestamps outside [now − 6 hours, now + 2 minutes] (`CLOCK_TOLERANCE`, `JUDGE_FUTURE_TOLERANCE`; `verify --clock-since`, in `verify.verify_report`; the `judge` job of `.github/workflows/judge.yml`).

## Guarantee
**Tamper-evidence:** any modification, deletion, insertion or reordering of an entry **followed by later entries** is detected by every verifier, unless the attacker finds a SHA-256 second preimage or forges an Ed25519 signature of an honest member (§8.1). **Truncating the newest entries**, or cutting the ledger back and continuing it another way, is not detected by replay alone. It is detected by memory and by comparison: each clone and each witness remembers the last head of the canonical ledger it verified and signs nothing on a ledger that no longer holds it (`ledger.head_verdict`, `ledger.remember_head`; SPEC §9.7), and witnesses, mirrors and anchors hold the same history elsewhere (see [[byzantine-fault-tolerance]], [[opentimestamps]]). A head dated more than ten minutes ahead of the clock is a capture alarm (`ledger.future_head`).

**State digest.** The stored facts of a state have one SHA-256, the state digest (`State.document`, `State.digest`; SPEC §4.11): the hash of a small document, version 2 (`STATE_VERSION`), holding the scalars, the Merkle root of each section of records and a hash chain for each history of records no rule reads any more (amendments, ballots, beacons, checkpoints, notes), so a verifier hashes again only what changed. A ballot that ended more than 111 days ago leaves the state for its history. Every witness checkpoint states the digest of the state it covers and the version of the document, and replay refuses a checkpoint whose digest is not the state's (`ledger._witness`). A witness posts a checkpoint at most once an hour, and only when another entry was added since its last one. Two verifiers that disagree on any stored fact therefore part at the next checkpoint, in public, and not at some later entry or never.

**Nothing is rewritten, even to repair.** A wrong is repaired by a new entry, a correction, which may undo, freeze or pause and never grants (Landmark VI; see [[custodian-and-corrections]]).

**Ordering and forks.** Two entries with the same `seq` come from different PRs, and the second one to be merged fails `prev`. The canonical history is "the longest valid chain that extends the latest witness-checkpointed and anchored head" (§4.4).

**Merkle roots.** `crypto.merkle_root` implements exactly the Merkle Tree Hash of RFC 6962 §2.1: leaf `SHA-256(0x00‖d)`, node `SHA-256(0x01‖left‖right)`, split at the largest power of two smaller than n, no duplicated nodes (`crypto.merkle_root`).

**Trust in the genesis.** The genesis itself cannot be verified by the protocol: the first founder chooses up to seven founding keys, the first witnesses and the Custodians. The defense is publicity (§9.2, "trusted setup"; see [[founder-sunset]]).

See also [[eternal-landmarks-of-openmasonry]] (Landmark VI: no record is ever rewritten or erased) and [[decision-function]].
