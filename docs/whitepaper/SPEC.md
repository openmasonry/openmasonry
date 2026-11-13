# OpenMasonry Protocol Specification

**Describes:** the reference implementation in `src/openmasonry/` as it stands in November 2026 (Whitepaper 0.1 "Genesis").
**Companion to:** [WHITEPAPER.md](WHITEPAPER.md), which explains intent. This document states the rules.
**Precedence:** where this document and the code disagree, the code decides what the ledger accepts, and this document is wrong. Where the code and the Whitepaper disagree, the code wins, and the disagreement is listed in [section 11](#11-known-differences-from-the-whitepaper).

---

## Contents

1. [Scope and conventions](#1-scope-and-conventions)
2. [Encoding](#2-encoding)
3. [Constants](#3-constants)
4. [State](#4-state)
5. [Common checks applied to every entry](#5-common-checks-applied-to-every-entry)
6. [Entry types](#6-entry-types)
7. [Decision functions](#7-decision-functions)
8. [Governed files and pins](#8-governed-files-and-pins)
9. [Gate checks that are not part of replay](#9-gate-checks-that-are-not-part-of-replay)
10. [Invariants](#10-invariants)
11. [Known differences from the Whitepaper](#11-known-differences-from-the-whitepaper)
12. [Open points for implementers](#12-open-points-for-implementers)
13. [Signatures](#13-signatures)
14. [Conformance vectors](#14-conformance-vectors)
15. [Rooms (derived, outside replay)](#15-rooms-derived-outside-replay)

---

## 1. Scope and conventions

### 1.1 Scope

OpenMasonry keeps its whole state in an append-only, hash-chained ledger of signed JSON entries. The state at any moment is the result of a deterministic fold over the entries, starting from an empty state. This document specifies:

- how an entry is encoded, hashed and stored (section 2);
- every constant of the protocol (section 3);
- the state and its derived views, and the one digest of its stored facts (section 4);
- the checks that every entry passes, and the rules of each entry type (sections 5 and 6);
- the pure decision functions (section 7);
- governed files and their pins (section 8);
- the checks the online judge adds, and the rule by which a client remembers the head it verified, which are **not** part of replay (section 9);
- the invariants that hold in the current code (section 10);
- what a valid signature is (section 13);
- the conformance vectors a second implementation runs (section 14);
- the rooms: who may read each degree's private room, derived from the state and outside replay (section 15).

It describes the protocol **as the code implements it today**. It does not describe intended future behavior, and it invents no rule. Section 11 lists where the code and the Whitepaper differ, and section 12 the choices and gaps that deserve a second look before the protocol is frozen.

The goal is that a second implementation, in another language, accepts and refuses exactly the same ledgers and reaches the same state. To that end every rule is stated in terms that do not depend on a runtime: exact integers, ASCII strings and exact durations (section 1.4).

### 1.2 Requirement words

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY and OPTIONAL are to be interpreted as described in RFC 2119.

### 1.3 Terms

| Term | Meaning |
|---|---|
| **entry** | One JSON object with exactly the seven envelope fields of section 2.1. The unit of the ledger. |
| **envelope** | The seven top-level fields of an entry: `seq`, `prev`, `time`, `type`, `actor`, `body`, `sig`. |
| **body** | The JSON object in the `body` field. Its meaning depends on `type`. |
| **actor** | The login in the `actor` field: the party the entry speaks for. A member login, an invited petitioner's login, a witness name or a custodian name. |
| **signer key** | The public key that must have signed an entry. It is decided by the state *before* the entry (section 5.2). |
| **key** | A public key in the text form of section 2.6, of one of two types: `ssh-ed25519`, or `sk-ssh-ed25519@openssh.com` (the same kind of key held by a hardware token). The **point** of a key is its 32 key bytes. Two keys are **the same key** when their points are equal, whatever their types. |
| **ledger** | The ordered sequence of entries `e[0], e[1], …`, stored as one file per entry. |
| **state** | The value of section 4. Written `S`. The empty state is `S₋₁`. |
| **apply** | The function that checks one entry against a state and, if it is lawful, folds it in: `Sᵢ = apply(Sᵢ₋₁, e[i])`. Implemented by `ledger.apply`. |
| **replay** | Applying every entry in order from the empty state: `ledger.replay`. Replay fails at the first entry that is refused. |
| **refusal** | The failure of an entry. The reference implementation raises `ledger.Invalid(seq, msg)`, printed as `entry {seq}: {msg}`. |
| **now** | Inside `apply`, the time of the entry being applied. Replay never reads a clock. |
| **member** | A login with a record in `S.members`, whatever its status. |
| **witness** | A name with a key in `S.witnesses`: a node that may close ballots, draw lots and sign checkpoints. |
| **checkpoint** | A `witness` entry, and the record the history `checkpoints` absorbs from it (section 4.11): the hash of the entry before it, the digest of the state that entry left, and optionally the Merkle root of all entries so far and the path of its anchor (section 6.16). |
| **state digest** | The SHA-256 of the state document: the scalars of a state, the Merkle root of each section of its records and the hash chain of each history (section 4.11). |
| **invitation** | The record an `invite` entry leaves in `S.invitations`: a Master Builder names a login and the numeric id of its GitHub account, and so opens the ledger to that login's petition (sections 4.3 and 6.17). |
| **custodian** | A name with a record in `S.custodians`: a custodian key, a revoke key and the login of the member account of the person who holds them (section 4.8). Named by the genesis, or by a founder's claim (section 6.31). A custodian is not a member and holds no vote. |
| **claim** | The record a `custodian_claim` entry leaves in `S.claims` (section 4.6): a founder takes up the Custodian office again while no custodian key is live, after 30 days of notice; until it is applied, one Master Builder who is not a founder can stop it (sections 6.31 to 6.33). |
| **succession** | The record a `succession_claim` leaves in `S.succession` (section 4.6). In force 90 days after it, unless a Master Builder who is active and neither dormant nor silent signed an entry meanwhile, and until three such Master Builders exist: the **successors**, the active members, neither dormant nor silent, of the highest degree present when that degree is 1 or 2, then stand in for Master Builders in four things (section 6.34). |
| **present** | An elector who is not dormant at the opening of a ballot. Every eligible member is an elector, dormant or not; the quorum and the turnout count the present ones (the ballot's **quorum base**, section 7.1). |
| **unstoppable set** | The entries no halt stops (`HALT_ALLOWED` and `ledger._unstoppable`): the custodians' own entries and the revoke key's removal, departures, key replacements, every entry of a key recovery, objections to a correction, a witness's checkpoint, and every entry of an amendment ballot or of the ballot that removes a custodian (section 5.2). |
| **daily-exempt set** | The entries the cap of entries per day neither counts nor refuses (`DAILY_EXEMPT` and `ledger.daily_exempt`): departures, key replacements and recoveries, objections, the revoke key's removal, votes, closes and draws, and the opening of an amendment ballot or of the ballot that removes a custodian (section 5.4). |
| **protocol epoch** | `S.epoch`: the number of amendments of `@protocol` that passed. It says that a new core is in force; a later core makes a rule change apply from a fixed time or `seq` written in its text, not from the epoch alone, so the entries already merged replay as before (section 12, point 68). |
| **correction** | The record a `correction` entry leaves in `S.corrections` (section 4.9): one act of a closed menu, signed by a custodian key, on one closed ground, with a public reason pinned by digest (section 6.19). The act `note` leaves its record in `S.notes` instead and is no correction record (section 6.19.6). |
| **noticed act** | A correction whose act is `void_ballot` or `undo_ballot`. It is **pending** for 14 days of notice and takes effect only by a `correction_apply`, within the 7 days that follow (section 6.19.9). While a `void_ballot` is pending its ballot is paused; a pending act changes nothing else. Every other act that restricts is **immediate**. |
| **recovery** | The record a `rekey_recover` entry leaves in `S.recoveries` (section 4.10): a member whose key is lost or stolen asks for a new one. It is not a correction: Master Builders co-sign it, and the key the ledger holds can stop it (sections 6.26 to 6.30). |
| **interval** | A stretch of time `[start, end)`: it holds a time `t` exactly when `start ≤ t < end`, and its length is `end − start` (section 7.8). |
| **effective clock** | Wall time minus the time the ledger was halted, and for one ballot minus the time that ballot was stayed or under a pending `void_ballot` (section 7.8). |
| **gate** | A check made by the online judge before an entry is merged (section 9). Gates are not replayed. |

### 1.4 Notation and conventions

- `H(x)` is the SHA-256 of the byte string `x`, written as 64 lowercase hexadecimal characters. When `x` is a character string, it is first encoded as UTF-8 (`crypto.sha256`).
- `canonical(v)` is the canonical JSON encoding of a JSON value (section 2.2).
- `fold(x)` is the case folding of a name or a path (`ledger.fold`). Names and paths are ASCII, so it is ASCII lowercasing: `A` to `Z` become `a` to `z` and nothing else changes.
- `{x}` inside a refusal message is an interpolated value. `{x!r}` is the Python `repr` of the value (for an ASCII string without quotes or backslashes, the string in single quotes).

Three conventions hold in every rule of this document. They are stated once here and not repeated.

**Integers.** Every number of the protocol is an integer `n` with `−(2^53 − 1) ≤ n ≤ 2^53 − 1`. There is no fraction, no exponent, no floating-point value and no `null` anywhere in an entry (section 2.2). A boolean is never an integer: where a rule asks for an integer, `true` and `false` are refused. All arithmetic in the rules is exact integer arithmetic; `⌈N/3⌉` is computed as `(N + 2) div 3`.

**Strings.** Every string of an entry, object keys included, consists only of the line feed U+000A and the characters U+0020 to U+007E (section 2.2). Every grammar of section 2.6 is narrower still. "Character" and "code point" are therefore the same thing as "byte", and no rule depends on a Unicode table.

**Durations.** A **time** is a UTC instant with a resolution of one second. `a − b` is an exact number of seconds, and `n d` means `n × 86,400` seconds. Nothing is ever rounded to whole days. Two predicates are used for every rule that counts days:

```
waited(start, now, n)   ⇔   now − start ≥ n d      a waiting period of n days is complete
expired(start, now, n)  ⇔   now − start > n d      something that lasts n days has expired
```

So a wait of 90 days is complete at the very second 90 days have passed, and a thing that lasts 180 days is still valid at that second and has expired one second later. A stored deadline `until = start + n d` follows the same two forms: a wait is complete when `now ≥ until`, and a thing is still valid while `now ≤ until`. In replay `now ≥ start` always holds, because time never goes backwards. Section 3 says, for every constant measured in days, which of the two forms uses it.

A third form is used by corrections alone: an immediate act is in force on an **interval** `[start, end)` (section 7.8), so an act of `n` days is in force for exactly `n × 86,400` seconds and is over at the second `start + n d`. And a small, closed list of durations is counted on the **effective clock** instead of the wall: `waited` and `expired` are then read with `effective(start, now)` in the place of `now − start` (section 7.8). Wherever this document does not say "effective clock", a duration is wall time.

### 1.5 Conformance

An implementation conforms when, for every finite sequence of entry files and the same external inputs (section 1.6):

1. it refuses the sequence exactly when the reference implementation does, at the same `seq`; and
2. when it accepts, its state equals the reference state field by field (section 4).

Condition 2 is checkable without comparing fields one by one: the stored facts of a state have one digest (section 4.11), a `witness` entry states that digest for the state it covers (section 6.16), and the vectors of section 14 state it for small ledgers. Two implementations that accept the same checkpoint hold the same state at that entry.

Refusal messages are quoted exactly so that tests can be shared. An implementation SHOULD report the same message. Only the accept or refuse outcome and the resulting state are normative. Because the checks of one entry are evaluated in a fixed order and the first failure wins, the message of a doubly unlawful entry depends on that order; this document lists preconditions in the order the code evaluates them.

### 1.6 Inputs of replay

Replay is a pure function of three inputs:

1. the ordered entries;
2. the **degree tables**, looked up by digest (section 8.4). Replay reads two numbers per degree: `wait_days` and `examiners`;
3. the signature predicate `sig_ok(payload, sig, actor, key)`, specified in [section 13](#13-signatures). `ledger.apply` takes it as the parameter `verifier`. It is consulted once for every entry (C12), a second time for a `rekey` and for a `rekey_recover`, whose proof it checks (section 6.18, Q5; section 6.26, RR9), for a `ballot_open` that proposes a new witness, whose proof it checks (section 6.4.5, W7), and twice for a `custodian_claim`, whose two proofs it checks (section 6.31, CL8); and for a `genesis` once for each founder after the first and once for each witness (section 6.1, G21a and G21b) and twice for each custodian (G22), whose proofs of possession it checks. A verifier that judges new entries on top of history it verified before may take the older entries **on trust** (`apply(…, trusted=True)`, section 9.1): the predicate is then not asked for them, and every other rule is evaluated all the same.

Input 2 is content-addressed: a degree table is identified by the SHA-256 of its bytes, which the ledger records, so every verifier that has the file reads the same table, and a verifier that lacks it cannot go on (section 8.4). A table is consulted at three kinds of entry: the genesis (G3), the opening of an amendment ballot on `canon/degrees.toml` (M6), and every entry that reads a degree. Nothing else is read from the verifier's tree. In particular the public reason of a correction is never opened by replay (section 6.19), and the Declaration digest that petitions commit to is recorded by the genesis entry and read from the state (sections 6.1 and 6.2).

---

## 2. Encoding

### 2.1 The envelope

An entry is a JSON object with **exactly** these seven members, no more and no fewer:

| Field | JSON type | Constraint |
|---|---|---|
| `seq` | integer | Equal to the previous `seq` plus 1. The first entry has `seq = 0`. A boolean is refused. |
| `prev` | string | Equal to the entry hash (section 2.3) of the previous entry. For entry 0, the 64-character string of zeros `ZERO_HASH`. Only equality is checked. |
| `time` | string | Section 2.5. Not earlier than the previous entry's time. Equal times are allowed. |
| `type` | string | One of the thirty-four types of section 6. |
| `actor` | string | A login (section 2.6). |
| `body` | object | Exactly the fields of its type (section 6). |
| `sig` | string | The signature over the signed payload (section 2.3). Replay places no other constraint on the string; the signature predicate does. |

### 2.2 Values and canonical JSON

**Values.** A value that appears in an entry, at any depth, is one of the following (`ledger.strict_value`). Anything else refuses the entry.

| Value | Rule |
|---|---|
| object | Its keys are strings (as below) and distinct. Its members are values. |
| array | Its elements are values. |
| string | Only U+000A (line feed) and U+0020 to U+007E. No other control character, no U+007F, nothing above U+007E. |
| integer | `−(2^53 − 1) ≤ n ≤ 2^53 − 1`. |
| boolean | `true` or `false`. |

There is no `null`, and no number with a fraction or an exponent (`1.0`, `1e5` and `-0.0` are refused even though their value is whole). **Nesting** is limited to `MAX_DEPTH` = 6: the entry object is at level 1, a container directly inside it is at level 2, and a container at level 7 is refused. The entry types of section 6 use four levels.

Because of these rules every string of an accepted entry is ASCII, and every number is an integer that every common JSON library reads exactly.

**Canonical JSON.** `canonical(v)` is the byte string produced by `crypto.canonical` for a value as defined above. It is a function of the value alone:

1. **No whitespace.** Members are separated by `,` and a key from its value by `:`. Nothing else is inserted.
2. **Key order.** The members of every object, at every depth, are written in ascending order of their keys, compared as sequences of Unicode code points. Keys are ASCII, so this is also the order of their bytes and of their UTF-16 code units (the order of RFC 8785).
3. **Arrays** keep their order.
4. **Strings** are written between `"`. Three escapes can occur in an entry:

   | Character | Written as |
   |---|---|
   | `"` (U+0022) | `\"` |
   | `\` (U+005C) | `\\` |
   | U+000A | `\n` |

   Every other character of an entry string (U+0020 to U+007E, including `/`) is written as itself, one byte. For completeness, `crypto.canonical` applied to a string outside the entry alphabet writes U+0008, U+000C, U+000D and U+0009 as `\b`, `\f`, `\r` and `\t`, any other character below U+0020 as `\u00XX` with lowercase hexadecimal digits, and every other character literally in UTF-8; no entry reaches it with such a string.
5. **Integers** are written in base 10 with no leading zeros, no `+` sign and no exponent, with a leading `-` when negative. Zero is `0`.
6. **Booleans** are `true` and `false`.

`crypto.canonical` refuses a value that holds a float, a `null`, an integer outside the range, a non-string key or any other type (`TypeError` or `ValueError`), so nothing outside these rules is ever hashed or signed.

Example. The entry

```json
{"seq": 1, "prev": "0000000000000000000000000000000000000000000000000000000000000000",
 "time": "2027-01-01T00:00:00Z", "type": "work", "actor": "hiram",
 "body": {"ref": "https://example.org/w", "kind": "essay"}, "sig": "x"}
```

has the canonical encoding (one line, no trailing newline):

```
{"actor":"hiram","body":{"kind":"essay","ref":"https://example.org/w"},"prev":"0000000000000000000000000000000000000000000000000000000000000000","seq":1,"sig":"x","time":"2027-01-01T00:00:00Z","type":"work"}
```

### 2.3 Signed payload and entry hash

- **Signed payload** (`ledger.signed_payload`): `canonical` of the entry with the member `sig` removed, that is, the object with the six members `actor`, `body`, `prev`, `seq`, `time`, `type`. These are the bytes the signature covers.
- **Entry hash** (`ledger.entry_hash`): `H(canonical(entry))` over **all seven** members, `sig` included. This is the value the next entry carries in `prev`, the value stored in `S.hashes`, and the leaf of the Merkle tree (section 2.4).

For the example of section 2.2 the signed payload is the same line without `"sig":"x",` and the entry hash is `d42607b1398ce62fdc6a42bd65d8ea4dc2e45044f18b3d21d3754f54aa4055b5`.

Because the hash covers `sig` as a string, two entries that differ only in the text of their signature are different entries with different hashes. The signature predicate therefore accepts exactly one spelling of a signature (section 13).

### 2.4 Merkle root

`crypto.merkle_root(leaves)` is the Merkle Tree Hash of RFC 6962, section 2.1, over a list of entry hashes:

- each leaf input is the 32 bytes of an entry hash (the hexadecimal string decoded);
- `MTH([d]) = SHA-256(0x00 ‖ d)`;
- `MTH(D[0:n]) = SHA-256(0x01 ‖ MTH(D[0:k]) ‖ MTH(D[k:n]))` for `n > 1`, with `k` the largest power of two strictly smaller than `n`;
- the result is written as 64 lowercase hexadecimal characters;
- for the empty list the function returns `H("")`. A `witness` entry never needs it, since `upto_seq ≥ 0`.

No node is duplicated when a level has an odd number of nodes. The same function is the root of a section of the state document (section 4.11), over the 32-byte leaves of its records.

**The frontier.** The root of a list that only grows can be kept in O(log n) space and updated in amortized O(1) hashes (`crypto.merkle_append`, `crypto.merkle_frontier_root`; `State.entries_root` for `S.hashes`). The frontier of `n` leaves is the list of the roots of the perfect subtrees of the binary decomposition of `n`, largest first, each with its size. Appending a leaf `d` pushes `(1, H(0x00 ‖ d))` and then, while the last two have the same size, replaces them by `(2 × size, H(0x01 ‖ left ‖ right))`. The root folds the frontier from the smallest to the largest, `node = H(0x01 ‖ left ‖ node)`, which is `MTH` because `MTH` splits at the largest power of two below `n`. It equals `merkle_root` for every `n` (the tests compare them for every size up to 2,000 and every power of two ± 1 up to 2¹⁴ + 1).

Vectors, with `a = H("a")`, `b = H("b")`, `c = H("c")`: `merkle_root([a]) = a23bd5b06da9048238a65b3f1d9d0b9e15fae3dde262688e6489aa4c763d1820`; `merkle_root([a, b]) = ad5ca6cddc0b27c6a83e332bf28011769236e6c6a1f786ebf7b5267b37a5bd22`; `merkle_root([a, b, c]) = cac3d448d4e20a2ad5eae1f500e63c2a7f9217cd14572ba7fd22e26dc1ec2648`.

### 2.5 Time

A time is written as a string of exactly 20 ASCII characters matching

```
([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z
```

(`ledger.TIME_RE`, matched against the whole string). The six groups are read as decimal integers `year, month, day, hour, minute, second` and checked one by one (`ledger.ts`); no library parser is involved:

| Field | Range |
|---|---|
| `year` | `YEAR_MIN` = 2020 to `YEAR_MAX` = 9000 |
| `month` | 1 to 12 |
| `day` | 1 to the length of the month: 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31, with 29 for February in a leap year |
| `hour` | 0 to 23. Hour 24 is refused. |
| `minute` | 0 to 59 |
| `second` | 0 to 59. Second 60 (a leap second) is refused. |

A year is a leap year when it is divisible by 4 and not by 100, or divisible by 400 (the proleptic Gregorian calendar). The time is the UTC instant with those fields; its Unix time is an integer.

A value that is not a string or does not match the pattern is refused with `time must be YYYY-MM-DDTHH:MM:SSZ, got {time!r}`; a field out of range with `time must be YYYY-MM-DDTHH:MM:SSZ, a real UTC time in the years 2020 to 9000, got {time!r}`.

The year range keeps every date the rules compute inside the range every runtime supports: the longest duration a rule adds to an entry time is `CUSTODIAN_TERM_DAYS` (2,555 days, plus one second), and the latest lot round is 8 hours after an entry time. The same text form, with the final `Z`, is used wherever a time is written inside the state or frozen in a ballot (`ledger.iso`; sections 4.4 and 4.6).

### 2.6 Grammars

All patterns are matched against the **whole** string (`fullmatch`). They name their characters explicitly; none uses a class such as `\d` or `\w` whose meaning depends on the Unicode tables of a runtime. Quoted from `ledger.py`:

```python
HEX64 = re.compile(r"[0-9a-f]{64}")
BALLOT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
PATH_RE = re.compile(r"@protocol|[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}){0,9}")
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{1,300}")
TIME_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
KEY_RE = re.compile(r"ssh-ed25519 [A-Za-z0-9+/]{68}|sk-ssh-ed25519@openssh\.com [A-Za-z0-9+/]{99}=")
NAME_RE = re.compile(r"[\x20-\x7e]{1,120}")
SALT_RE = re.compile(r"[0-9a-f]{32,64}")
WORK_KIND_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
ANCHOR_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}){0,9}")
STRING_RE = re.compile(r"[\n\x20-\x7e]*")
NOTE_TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,119}")
NOTE_RULE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,63}")
```

| Name | Used for |
|---|---|
| `STRING_RE` | every string of an entry, keys included (section 2.2) |
| `LOGIN_RE` | `actor`, founder logins, witness names, custodian names, the `login` of an `invite`, of a `rekey_cosign` and of a `rekey_oppose` |
| `KEY_RE` | every public key, of either type (together with the blob and point checks below) |
| `HEX64` | genesis pins and Declaration digest, `new_sha256`, commitments, beacons, the `reason_sha256` of a correction |
| `BALLOT_ID_RE` | ballot ids |
| `PATH_RE` | amendment paths |
| `URL_RE` | `work.ref`, `exam_open.work_ref`, `exam_report.reason` |
| `NAME_RE` | the fraternity name (genesis) |
| `SALT_RE` | the salt of a revealed vote |
| `WORK_KIND_RE` | `work.kind` |
| `ANCHOR_RE` | `witness.anchor`, together with a length of at most `ANCHOR_MAX` = 200 |
| `TIME_RE` | `time` (section 2.5) |
| `NOTE_TARGET_RE` | `target.target` of a correction whose act is `note` (section 6.19.6) |
| `NOTE_RULE_RE` | `target.rule` of the same |

In words:

- **Login:** 1 to 39 characters; ASCII letters, digits and hyphens; no leading hyphen, no trailing hyphen, no two hyphens in a row.
- **Key:** one of two forms, each with no options, no comment and no trailing newline.
  - **Plain:** the literal `ssh-ed25519`, one space, exactly 68 base64 characters without padding: the canonical base64 of exactly 51 bytes, namely the OpenSSH key blob `00 00 00 0b` ‖ `ssh-ed25519` ‖ `00 00 00 20` ‖ 32 key bytes.
  - **Hardware-backed:** the literal `sk-ssh-ed25519@openssh.com`, one space, exactly 99 base64 characters and one `=`: the canonical base64 of exactly 74 bytes, namely the OpenSSH key blob `00 00 00 1a` ‖ `sk-ssh-ed25519@openssh.com` ‖ `00 00 00 20` ‖ 32 key bytes ‖ `00 00 00 04` ‖ `ssh:`. The last field is the **application** of the key, and it MUST be exactly the four bytes `ssh:`; a key made for any other application is refused.

  A string is a **valid key** when it matches `KEY_RE` **and** `crypto.valid_public_key` accepts it (`ledger.ed25519`): the base64 decodes to the exact blob of its type and encodes back to the same characters (so a key has one text form), and the 32 key bytes are the canonical encoding of an Ed25519 point of order exactly `L` (the identity and every point with a small-order component are refused), the same check for both types. The checks are specified in section 13 (S4). Every rule below that asks for "a key" asks for a valid key. The **point** of a valid key is its 32 key bytes (`crypto.public_point`; `ledger.point` writes them as 64 lowercase hexadecimal characters), and two valid keys are **the same key** when their points are equal (`ledger.same_key`): every rule that asks whether a key is held, or was seen before, compares points, so one point can never be registered twice under the two types. A key is validated when an entry brings it; a key the state already holds was validated then, and a rule that asks who holds a key only decodes the 32 bytes of each stored key (`crypto.key_bytes`, `ledger.holds`) and compares them.
- **Hex:** exactly 64 characters, `0-9` and `a-f` only.
- **Ballot id:** 1 to 64 characters of `a-z`, `0-9`, `.`, `_`, `-`; the first is a letter or digit.
- **Path:** the literal `@protocol`, or 1 to 10 segments separated by `/`; each segment is 1 to 100 characters of ASCII letters, digits, `_`, `.`, `-`, and starts with a letter, a digit or `_`. A path therefore never starts with `/`, never contains an empty segment, a `.` or `..` segment, a backslash or a colon. A path that matches is used exactly as written; there is no normalization.
- **URL:** `http://` or `https://` (lowercase), then 1 to 300 characters from the listed set (so at most 307 or 308 characters in all). No space, no quote of either kind (`"` or `'`), no backslash, no control character.
- **Name:** 1 to 120 printable ASCII characters, U+0020 to U+007E.
- **Salt:** 32 to 64 lowercase hexadecimal characters. The reference tool draws 16 random bytes and writes them as 32 characters.
- **Work kind:** 1 to 32 characters of `a-z`, `0-9`, `_`, `-`; the first is a letter or digit.
- **Anchor:** a relative path with the segments of **Path** (never `@protocol`), at most 200 characters in all.
- **Note target:** 1 to 120 characters of ASCII letters, digits and `.`, `_`, `:`, `/`, `#`, `@`, `-`; the first is a letter or digit. What a moderation act touched: a thread, a comment, an account (`openmasonry/degree-07#12`, `user:some-login`). No space and no URL query.
- **Note rule:** 1 to 64 characters of ASCII letters, digits and `.`, `_`, `:`, `/`, `#`, `-`; the first is a letter or digit. The published rule the act applied (`ROOMS.md#5`).

Two logins are **the same login** when their foldings are equal (`ledger.same_login`). Uniqueness checks use this comparison. Lookups do not: an actor or a body field that names a member, a petition, a witness or an examiner must match the stored login **exactly**, character for character (section 5.2).

### 2.7 Files and the loader

The ledger is a directory (by default `ledger/entries/`) of **shards**, each a directory holding the JSON text files of `SHARD_SIZE` = 1,000 consecutive entries, and nothing else. The **path** of entry `seq` inside the directory (`ledger.entry_name`) is `{seq // 1000:04d}/{seq:06d}.json`: the shard is `seq // 1000` in decimal, left-padded with zeros to at least four digits, and the file name is `seq` in decimal, left-padded with zeros to at least six digits, followed by `.json`. So `0000/000000.json` to `0000/000999.json`, then `0001/001000.json`, …, `0999/999999.json`, `1000/1000000.json`, …, `9999/9999999.json`, `10000/10000000.json`: every entry has exactly one path, and every shard but the last holds exactly 1,000 entries. `ledger.load(directory)` reads it under these rules. A refusal at file index `i` is reported as `entry {i}: …`; the paths in the messages are written relative to the directory, with `/`.

1. If the directory does not exist, the ledger is empty. If it cannot be listed for any other reason (for example the path is a file): `cannot read the ledger directory: {reason}`, reported at index 0.
2. The names in the directory, **all of them**, are taken, except the one name `.gitkeep`, which is ignored there (and only there). In the order of `(length of the name, name)`, ascending, names compared by code point:
   - a name that is a directory (not a symbolic link to one) MUST be the name of a shard: four digits, or five to thirteen digits without a leading zero. Refusal at index 0: `ledger directory {name} is not a shard (shards are named after seq // 1000, in four digits at least: 0000, 0001, …)`. Its names, **all of them**, are taken as `{shard}/{name}`, and it MUST hold at least one: `ledger shard {shard} holds no entry`, at index `shard × 1000` (a shard that cannot be listed: `cannot read {shard}: {reason}`, at the same index). Nothing deeper is listed: a directory inside a shard is a name of the shard;
   - any other name (a file, a symbolic link, anything else) is taken as it is.

   Rule 2 is applied to every name of the directory before rule 3 is applied to any.
3. The names taken (`ledger.entry_order`), in the order of `(length, name)`, MUST each be the path of an entry, `entry_name(seq)` for some `seq`. The first that is not is refused:
   - a name at the top that is the name of a shard: `ledger shard {name} must be a directory, not a symlink or a file`, at index `shard × 1000`;
   - a name at the top that is the file name of an entry, `{seq:06d}.json`: `ledger file {name} is not in its shard: entry {seq} is {entry_name(seq)}`, at index `seq`;
   - a name `{shard}/{file}` whose file name is that of an entry and whose shard is not `seq // 1000`: `ledger file {name} is in the wrong shard: entry {seq} is {entry_name(seq)}`, at index `seq`;
   - a name whose first part is not the name of a shard (only a listing that descends further than rule 2 can hold one; see `actions.canonical_ledger` below): the refusal of a directory of rule 2;
   - any other name: `ledger file {name} is not an entry (the directory holds only the entries, each named after its seq in the shard of seq // 1000: 0000/000000.json, 0000/000001.json, …)`, at index `shard × 1000` for a name inside a shard, 0 at the top.

   Then the entries MUST be numbered from 0 with no gap: with `n` paths, every seq from 0 to `n − 1` has its own, and the first that does not is refused at its index: `ledger file {entry_name(i)} is missing (the entries are numbered from 0 without a gap)`. The file at index `i` is the one at `entry_name(i)`. So any other file or directory, at either level, refuses the ledger, and so does an entry in another shard, a gap, a shard that is not full before the next one, and a shard with a name not written in its canonical way (`000`, `00001`).
4. The file at index `i` MUST be a regular file: not a symbolic link, not a directory, not any other kind of file. Refusal: `ledger file {name} must be a regular file, not a symlink or a directory`.
5. The file size MUST be at most `MAX_GENESIS_BYTES` = 32,768 bytes for file 0 and `MAX_ENTRY_BYTES` = 8,192 bytes for every other file. Refusal: `{name} exceeds {limit} bytes`. A file that cannot be read: `cannot read {name}: {reason}`.
6. The content MUST be **strict JSON** (`ledger.strict_json`):
   - valid UTF-8, without a byte order mark (`not UTF-8`; `a byte order mark is not allowed`);
   - arrays and objects nested at most 6 deep, counted on the text before it is parsed (so the limit never depends on a parser's own recursion limit; `values nest deeper than 6 levels`);
   - one JSON text under the grammar of RFC 8259, whitespace around tokens allowed (a syntax error is reported in the words of the host parser, which are not normative);
   - no object with a **duplicate key**, at any depth (`duplicate key {key!r}`);
   - none of the non-standard constants `NaN`, `Infinity` and `-Infinity` (`non-standard JSON constant {constant}`);
   - no number written with a fraction or an exponent (`a number with a fraction or an exponent is not allowed ({the first 24 characters of the literal})`);
   - every integer literal at most 16 digits long (not counting a leading `-`) and within `±(2^53 − 1)`. The length is checked on the text, before any conversion, so no arbitrary-precision limit of a runtime is involved (`an integer is outside ±(2^53 − 1)`). `-0` is the integer zero;
   - the parsed value is a value in the sense of section 2.2 (`null is not allowed`; `a string holds a character outside ASCII (line feed, U+0020 to U+007E)`; `an object key is not a string`; `a value of type {type} is not allowed`). The same four messages, and those of the integer range and of the nesting limit, are the `{error}` of check C2 in section 5.1.

   Refusal: `{name} is not strict JSON: {error}`.
7. The parsed value MUST be an object whose `seq` is an integer (not a boolean) equal to `i`. Refusal: `{name} does not hold entry {i}`.

The loader returns the parsed objects in order. Two files with different bytes that parse to the same JSON value are the same entry: the entry hash is computed from the parsed value, never from the file bytes. A file need not be canonical; the reference tools write the entry with two-space indentation and a final newline (`ledger.entry_text`), and refuse to write a file larger than the limit.

`ledger.apply` judges a parsed value by the same rules (section 5.1, checks C2 and C4), so an entry built in memory and an entry read from a file are refused alike. For the size it measures the canonical encoding, which is never longer than the file it came from.

The loader reads the entries directory and nothing beside it. Its siblings are not part of the ledger: `ledger/anchors/` holds the roots and proofs a witness's checkpoint names (section 9.6), and `ledger/reasons/` holds the public reasons of corrections, one file `{sha256}.md` per reason (section 8.5). A reason file inside the entries directory would refuse the ledger under rule 3.

The clients read the canonical ledger from git rather than from a directory (`actions.canonical_ledger` and the witness's `canonical_entries`, section 9.7): they list every file of the tree under `ledger/entries/` (`git ls-tree -r`), take every path but the top `.gitkeep` under rule 3, refuse a file that is not a regular file of the tree (a symbolic link or a submodule) under rule 4, and read the contents under rules 6 and 7. The size limits of rule 5 are applied when the entries are replayed (section 5.1, check C4).

An empty or absent directory is an empty ledger. Replay of an empty ledger returns the empty state; `verify` reports it as valid (`ledger is empty (no genesis yet)`).

---

## 3. Constants

Every constant below is fixed in code. Changing one changes the `@protocol` digest (section 8.3) and therefore needs a passed amendment. For constants measured in days, the column "Form" says which predicate of section 1.4 reads it.

### 3.1 Encoding and identity

| Name | Value | Unit | Defined in | Used by |
|---|---|---|---|---|
| `ENVELOPE` | `seq, prev, time, type, actor, body, sig` | field names | `ledger` | `ledger.apply` (C1) |
| `BODY_FIELDS`, `PIN_FIELDS`, `FOUNDER_FIELDS`, `WITNESS_FIELDS`, `CUSTODIAN_FIELDS` | the exact fields of each body and record (section 6) | field names and JSON types | `ledger` | `ledger.apply` (C10) |
| `TARGET_FIELDS` | the exact fields of the target of each act of a correction (section 6.19) | field names and JSON types | `ledger` | `correction` (N4) |
| `SUBJECT_FIELDS` | admission `{candidate}`; advancement `{member, degree}`; amendment `{path, new_sha256}`; sanction `{member, measure}`; witness `{action, name, key, proof}` with `key` and `proof` only to add; custodian `{remove}` | field names and JSON types | `ledger` | `ballot_open` |
| `UNSTOPPABLE_KINDS` | `amendment, custodian` | set of ballot kinds | `ledger` | `ledger._unstoppable` (the halt gate and the freeze gate, section 5.2); `ledger.daily_exempt` (C12a); `State.pauses` (an amendment and a removal run on wall time); `ledger.due_actions` (the closes due during a halt) |
| `ZERO_HASH` | 64 × `0` | hex string | `canon` | `prev` of entry 0; head of the empty state |
| `MAX_SAFE_INT` | `2^53 − 1` = 9,007,199,254,740,991 | integer | `ledger`, `crypto` | every integer |
| `MAX_INT_DIGITS` | 16 | digits | `ledger` | `ledger.strict_json` |
| `MAX_DEPTH` | 6 | levels | `ledger` | `ledger.strict_json`, `ledger.strict_value` |
| `MAX_ENTRY_BYTES` | 8,192 | bytes | `ledger` | `ledger.load`, `ledger.apply` (C4) |
| `STATE_VERSION` | 2 | version | `ledger` | `State.document`: the `v` of the state document (section 4.11), and through it the digest a `witness` entry states (Z4a, Z5). The only version: no other is accepted |
| `HISTORY` | `amendments`, `ballots`, `beacons`, `checkpoints`, `notes` | names | `ledger` | the histories of the state document (section 4.11) |
| `BALLOT_RETIRE_DAYS` | 111 (`UNDO_WINDOW_DAYS + NOTICE_DAYS + APPLY_WINDOW_DAYS`) | days, wall time | `ledger` | `ledger._retire`: a ballot that ended more than this long ago leaves `S.ballots` for the history `ballots` (C14r) |
| `MAX_GENESIS_BYTES` | 32,768 | bytes | `ledger` | `ledger.load`, `ledger.apply` (C4): the limit of `MAX_ENTRY_BYTES`, for entry 0 |
| `YEAR_MIN`, `YEAR_MAX` | 2020, 9000 | years | `ledger` | `ledger.ts` |
| `ANCHOR_MAX` | 200 | characters | `ledger` | `witness` |
| `KEEP_FILE` | `.gitkeep` | file name | `ledger` | `ledger.load`, `ledger.entry_order`: ignored at the top of the entries directory, and only there |
| `SHARD_SIZE` | 1,000 | entries | `ledger` | `ledger.entry_name`: the entries of one shard directory (section 2.7) |
| `NAMESPACE` | `openmasonry` | string | `canon` | signature namespace |
| `YES`, `NO` | `yes`, `no` | strings | `ledger` | `ballot_reveal`, `ballot_close` |
| `KINDS` | `admission, advancement, amendment, custodian, sanction, witness` | set | `ledger` | `ballot_open` |
| `BALLOT_TYPES` | `ballot_open, ballot_commit, ballot_reveal, ballot_close` | set of types | `ledger` | `ledger._unstoppable`: the entries of a ballot; `govern.amendment_only` (section 9.5) |
| `RESULTS` | `passed, failed, lapsed, voided, undone` | tuple of strings | `ledger` | the values of `Ballot.result` once a ballot is not open (section 4.4) |
| `MEASURES` | `admonish, suspend, expel, expel_for_fraud, reinstate` | set | `ledger` | sanction ballots |
| `SANCTION_ON` | the standing each measure requires (section 6.4.4) | sets | `ledger` | sanction ballots, at opening and at close |
| `GONE` | `departed, expelled, voided` | set of statuses | `ledger` | the statuses of a record that is no longer a membership (FK1, HR1, A4) |
| `DEPART_BLOCKED` | `GONE` | set of statuses | `ledger` | `ledger._signer` for `depart` |
| `REKEY_BLOCKED` | `GONE` | set of statuses | `ledger` | `ledger._signer` for `rekey`; and, through `ledger.recoverable`, for `rekey_object`, `rekey_recover` and `rekey_recover_apply`, with one exception: a member who departed (`left` is set; section 6.15) |
| `WITNESS_TYPES` | `witness, ballot_close, exam_draw, council_draw` | set | `ledger` | `ledger._signer`, `identity.pr_problems` |
| `CUSTODIAN_TYPES` | `correction, correction_cosign, correction_apply, correction_withdraw, custodian_alive` | set of types | `ledger` | `ledger._signer`: types a custodian key signs |
| `RECOVERY_TYPES` | `rekey_recover, rekey_recover_apply` | set of types | `ledger` | `ledger._signer`: types the new key of a recovery signs |
| `CUSTODIAN_SIGNED` | `CUSTODIAN_TYPES` and `custodian_revoke` | set of types | `ledger` | `ledger._signer`; `identity.pr_problems`: types any pull request may carry |
| `HALT_ALLOWED` | `CUSTODIAN_SIGNED`, `RECOVERY_TYPES` and `correction_object, depart, rekey, rekey_object, rekey_cosign, rekey_oppose, witness` | set of types | `ledger` | `ledger._signer`: what is accepted while the ledger is halted, besides the entries of a ballot of an `UNSTOPPABLE_KINDS` kind |
| `FREEZE_ALLOWED` | `depart, rekey, rekey_object, ballot_commit, ballot_reveal` | set of types | `ledger` | `ledger._frozen_may`: what a frozen member signs, besides the entries of a ballot of an `UNSTOPPABLE_KINDS` kind |
| `STAY_EXEMPT` | `amendment, custodian` | set of ballot kinds | `ledger` | `correction` (SY2, VB2, UB2): kinds never stayed, voided or undone |
| `NOTICED_ACTS` | `void_ballot, undo_ballot` | tuple of acts | `ledger` | `correction`: the acts that need notice |
| `UNDO_KINDS` | `admission, advancement` | tuple of ballot kinds | `ledger` | `correction` (UB2): the kinds an `undo_ballot` reaches; of `advancement`, never one to the 3rd degree (UB2a) |
| `UNCREDITED` | `depart, rekey, rekey_object` | set of types | `ledger` | `ledger.apply` (C14): types that add no activity |
| `PROVING` | `genesis, ballot_open, rekey, rekey_recover, custodian_claim` | set of types | `ledger` | `ledger.apply`: types whose rule checks further signatures |
| `REKEY_DOMAIN` | `openmasonry rekey v1` | string | `ledger` | first line of the proof message of a `rekey` (section 6.18) |
| `CUSTODIAN_DOMAIN` | `openmasonry custodian v1` | string | `ledger` | first line of the message a custodian key signs at genesis (section 6.1) and in a founder's claim (section 6.31) |
| `CUSTODIAN_REVOKE_DOMAIN` | `openmasonry custodian-revoke v1` | string | `ledger` | first line of the message a revoke key signs at genesis (section 6.1) and in a founder's claim (section 6.31) |
| `WITNESS_DOMAIN` | `openmasonry witness v1` | string | `ledger` | first line of the message a witness key signs to be named at genesis or proposed by a witness ballot (sections 6.1 and 6.4.5) |
| `FOUNDER_DOMAIN` | `openmasonry founder v1` | string | `ledger` | first line of the message the key of a founder after the first signs at genesis (section 6.1) |
| `GROUNDS` | `key_compromised, protocol_defect, identity_fraud, attack_in_progress, moderation` | list of strings | `ledger` | `correction` (N2) |
| `NOTE_GROUND` | `moderation` | string | `ledger` | `correction` (N5, N5a): the ground of a `note`, and of no other act |
| `NOTE_ACTIONS` | `hide, lock, block, unblock, limit, other` | list of strings | `ledger` | `correction`, act `note` (NT1) |
| key types | `ssh-ed25519`, `sk-ssh-ed25519@openssh.com` | strings | `crypto` (`PLAIN`, `SK`) | every key and signature (sections 2.6 and 13) |
| `SK_APPLICATION` | `ssh:` | 4 bytes | `crypto` | the application of a hardware-backed key (S2, S4) |
| `SK_USER_PRESENT` | `0x01` | bit of the flags byte | `crypto` | signatures of a hardware-backed key (S3) |
| `HASH` | `sha512` | hash name | `crypto` | the hash of the signed message inside every signature (S2, S3) |

### 3.2 Governed paths

| Name | Value | Used by |
|---|---|---|
| `DEGREES_PATH` | `canon/degrees.toml` | genesis pin; `State.degree`; amendment close |
| `ETERNAL_PREFIX` | `canon/eternal.toml` | genesis pin; amendments refused on this prefix |
| `LEDGER_PREFIX` | `ledger` | amendments refused at or under this path |
| Constitution path | `CONSTITUTION.md` | genesis pin |
| `PROTOCOL_PIN` | `@protocol` | genesis pin; `govern.protocol_digest` |
| Custodian charter path | `docs/governance/CUSTODIAN.md` | genesis pin |
| Rooms charter path | `docs/governance/ROOMS.md` | genesis pin |
| `GENESIS_PINS` | the six paths above that are genesis pins: `canon/degrees.toml`, `canon/eternal.toml`, `CONSTITUTION.md`, `@protocol`, `docs/governance/CUSTODIAN.md`, `docs/governance/ROOMS.md` | `ledger._genesis` (C10, G1); `govern.genesis_pins` |
| `PRIOR_PIN_DAYS` | 30 days; the prior pin is lawful while `S.time ≤ close time + 30 d` | amendment close; `govern.check_tree` |
| `MANIFEST` | `src/openmasonry/protocol.manifest`: the file of the tree that lists the pinned core (section 8.3) | `govern.read_manifest`; `govern.protocol_digest`; `govern.stray_workflows` |
| `MANIFEST_REQUIRED` | `src/openmasonry/protocol.manifest`, `src/openmasonry/govern.py`: the paths every manifest lists | `govern.parse_manifest` |
| `MANIFEST_MAX_BYTES` | 65,536 bytes | `govern.parse_manifest` |
| `MANIFEST_PATH_RE` | `[A-Za-z0-9._-]{1,100}(?:/[A-Za-z0-9._-]{1,100}){0,9}`, matched against a whole line | `govern.parse_manifest` |
| `WORKFLOWS_DIR` | `.github/workflows` | `govern.stray_workflows` (section 8.5) |
| `REASONS_DIR` | `ledger/reasons`: where the tree holds the public reasons of corrections, as `{sha256}.md` | `govern.missing_reasons` (section 8.5) |
| `REASON_MAX_BYTES` | 65,536 bytes | `govern.missing_reasons` |
| `REASONS_KEEP` | `.gitkeep`: the only other name allowed in `ledger/reasons/` | `govern.stray_reasons` |
| `ANCHORS_DIR` | `ledger/anchors`: where the tree holds the roots a witness anchored, and their proofs | `govern.anchor_problems` (section 9.6) |
| `ANCHOR_MAX_BYTES` | 16,384 bytes | `govern.anchor_problems` |
| `OTS_PREFIX` | the header of an OpenTimestamps proof file (31 bytes: `00`, `OpenTimestamps`, `00 00`, `Proof`, `00`, `bf 89 e2 e8 84 e8 92 94`), the major version `01` and the SHA-256 operation `08` | `govern.anchor_mismatch` (section 9.6) |
| `HISTORY_DIR` | `canon/history`: where the tree archives every degree table the ledger ever pinned, as `{sha256}.toml` | `govern.unarchived_tables` (section 8.5) |
| removal of a pin | an amendment whose `new_sha256` is `ZERO_HASH` (64 × `0`) removes the pin of a path that is not in `GENESIS_PINS` | amendment open (M7a) and close (section 6.7) |

### 3.3 Membership and sponsorship

| Name | Value | Form | Defined in | Used by |
|---|---|---|---|---|
| `FOUNDING_MASTERS` | 7 members | | `canon` | maximum number of founders at genesis; `State.founding_phase` (fewer than 7 active Masters) |
| founder degree | 3 | | literal in `ledger._genesis` | genesis |
| `SPONSORS_REQUIRED` | 2 sponsors | | `canon` | `ledger.sponsors_required` |
| `SPONSOR_WAIVE_DAYS` | 30 days | `waited` on the **effective clock**, from the petition | `ledger` | `ledger.sponsors_required`: while fewer than 7 Master Builders are present (the Founding Phase, or later while fewer answer), one sponsor suffices once a petition has been live this long (section 7.5) |
| `SUCCESSION_DAYS` | 90 days, wall time | `waited`, from the `succession_claim` | `ledger` | `State.succession_status` (section 6.34) |
| `SUCCESSION_MASTERS` | 3 active Master Builders | | `ledger` | the succession ends once this many exist (C14b) |
| `SPONSOR_MIN_DEGREE` | 3 | | `canon` | `invite`; `vouch`; `ledger.may_sponsor`; `State.masters` |
| `SPONSOR_BUDGET_PER_YEAR` | 4 sponsorships | | `canon` | `invite`; `vouch` |
| `SPONSOR_YEAR_DAYS` | 365 days | an admitted member counts until `expired`, while not departed | `ledger` | `ledger.sponsorships` |
| `INVITE_EXPIRY_DAYS` | 30 days | an invitation is live until `expired` on the **effective clock** | `ledger` | `State.invited` |
| `INVITE_COUNTED_DAYS` | 90 days | a lapsed invitation counts until `expired(time, now, 30 + 90)` on the **effective clock** | `ledger` | `ledger.sponsorships` (section 7.5) |
| `PETITION_EXPIRY_DAYS` | 180 days | a petition is live until `expired` on the **effective clock** | `ledger` | `State.live` |
| `REJOIN_AFTER_DAYS` | 90 days | `waited` | `ledger` | `ledger.may_return`: `invite` of a departed member, or of a login whose admission was undone (`voided`), and its `petition` |
| `VOIDED_FRAUD_DAYS` | 90 days | the window is open while `not waited`, counted from the undo: it closes at the second the wait of `REJOIN_AFTER_DAYS` ends | `ledger` | sanction `expel_for_fraud` on a `voided` record (SN2a) |
| `EXPELLED_REPETITION_DAYS` | 365 days | `waited` | `ledger` | `ledger.may_return`: `invite` of an expelled member, and its `petition` |
| `SUSPENSION_DAYS` | 365 days | `waited` (`now ≥ suspended_until`) | `ledger` | sanction `suspend`; `Member.standing` |
| `SPONSOR_BAN_DAYS` | 730 days | `waited` (`now ≥ sponsor_ban_until`) | `ledger` | sanction `expel_for_fraud`; `ledger.may_sponsor` |
| `FRAUD_WINDOW_DAYS` | 730 days | the window is open until `expired` | `ledger` | sanction `expel_for_fraud` |
| `SILENT_DAYS` | 180 days | a call counts while `not expired`, counted from its end; one revealed vote or one report ends the silence for as long | `ledger` | `Member.silent`, `Member.called` (section 7.7) |
| `SILENT_CALLS` | 2 calls | | `ledger` | `Member.silent`: a Master Builder (or, while a succession is in force, any member) called to this many examinations or ballots in `SILENT_DAYS`, who answered none, is silent; `Member.called` keeps this many missed calls |
| `SILENT_APART_DAYS` | 7 days | two missed calls are both kept only when their ends are at least this far apart (`t1 − t2 ≥ 7 d`) | `ledger` | `Member.called` (section 7.7): calls that end closer together are one absence |
| `DORMANT_AFTER_DAYS` | 365 days | presence lasts until `expired` | `canon` | `Member.dormant`: a dormant elector keeps the vote and is not counted by the quorum (section 7.1); dormant Masters do not count for the Founding Phase, the Sunset, the founder's fallback or the succession |
| `WORK_INTERVAL` | 24 hours | `now − last_work ≥ 24 h` | `ledger` | `work` |
| `REKEY_INTERVAL_DAYS` | 30 days | `waited`, from the member's `last_rekey` (a `rekey`, or the application of a recovery) | `ledger` | `rekey` |
| `LIGHT_HALF_LIFE_DAYS` | 180 days | | `canon` | `Member.light` (informational) |
| `LIGHT_WINDOW_DAYS` | 1,800 days | a point of activity is kept until `expired`, counted from the newest point | `canon` | `Member.credit` (section 5.3): ten half-lives |

### 3.4 Ballots

| Name | Value | Unit | Defined in | Used by |
|---|---|---|---|---|
| quorum | `Q(N) = min(N, max(3, ⌈N/3⌉))`, with `N` the ballot's quorum base (section 7.1) | votes | `ledger.quorum` | `ledger.decide` |
| `RERUN_DAYS` | 30 days, wall time: a re-run is opened while `not expired(closed, now, 30)` of the lapsed ballot | days | `ledger` | `ballot_open` (B2e) |
| `SANCTION_MASTER_VOTES` | 2 | electors and votes | `ledger` | a sanction on a Master Builder, a `reinstate` aside (`frozen.master`), needs this many electors to open (B8a) and this many votes cast to decide (section 6.7) |
| `COMMIT_DAYS` | 7; an amendment may state 2 to 30 | days | `ledger`; range literal in `ledger._ballot_open` | commit window; the least one a ballot gives when its quorum base leaves out some electors (B9a), a re-run (B2f), the ballot a re-run re-runs (B2g), and a ballot that calls its electors (`ledger.full_call`, effect 2a of section 6.7) |
| `REVEAL_DAYS` | 3; an amendment may state 1 to 14 | days | `ledger`; range literal in `ledger._ballot_open` | reveal window |
| `OPENER_WINDOWS` | `amendment` | set of ballot kinds | `ledger` | `ballot_open` (B6a): the kinds whose opener states the windows; every other kind has the fixed 7 and 3 |
| `CLOCK_TOLERANCE` | 6 | hours | `ledger` | the gate of section 9.2; `REVEAL_GAP` |
| `REVEAL_GAP` | `CLOCK_TOLERANCE` + 15 minutes = 6 h 15 min | duration | `ledger` | gap between the commit and reveal windows |
| blackball ratio | rejected when `5·no ≥ votes` | votes | literal in `ledger.decide` | admission, advancement |
| two-thirds rule | passes when `3·yes ≥ 2·votes` and `3·votes ≥ N`, with `N` the quorum base | votes | literal in `ledger.decide` | amendment, sanction, witness |
| majority rule | passes when `yes > no` (a tie fails) | votes | literal in `ledger.decide` | custodian |
| elector degree, admission | 2, else 1 (nobody of degree 2 or higher present, the voters of degree 2 kept); present: not dormant and not silent | degree | literal in `ledger.electorate` | admission |
| elector degree, advancement | the degree sought, else 3 (fewer than 3 present, the voters of the first rung kept), else the successors (no Master Builder present, the voters so far kept); present: not dormant and not silent; never the candidate | degree | literal in `ledger.electorate` | advancement |
| elector degree, amendment and witness | 3 | degree | literal in `ledger.electorate` | amendment, witness |
| elector degree, sanction | 7, else 3 | degree | literal in `ledger.electorate` | sanction |
| elector degree, custodian | 3, never the member the custodian is linked to | degree | literal in `ledger.electorate` | custodian |
| opener degree, amendment, witness and custodian | 3 | degree | `canon.SPONSOR_MIN_DEGREE`, in `ledger._master` and `ledger._open_custodian` | M0, W0, CU3 |
| opener degree, sanction | 7 where three or more active Arbiters other than the accused exist, else 3 | degree | literals in `ledger._open_sanction` | section 6.4.4, SN5 |
| electorate fallback threshold | fewer than 3 present | electors | literal in `ledger.electorate`, `ledger._open_sanction` | advancement, sanction (electorate and opener) |
| highest degree by advancement | 32 | degree | literal in `ledger._open_advancement`, `ledger._exam_open` | advancement, exams |

### 3.5 Examinations, the lot and the Council

| Name | Value | Form | Defined in | Used by |
|---|---|---|---|---|
| `DRAND_CHAIN` | `52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971` (quicknet) | | `ledger` | `beacon.fetch` (gate) |
| `DRAND_GENESIS` | 1,692,803,367 Unix seconds | | `ledger` | `ledger.drand_round`, `ledger.drand_time` |
| `DRAND_PERIOD` | 3 seconds | | `ledger` | same |
| `BEACON_DELAY_ROUNDS` | 9,600 rounds (= 28,800 s = 8 h) | | `ledger` | `exam_open`, `council_call` |
| `EXAM_EXPIRY_DAYS` | 60 days | an exam is open to verdicts until `expired` on the **effective clock**; one without a verdict then has **timed out**, with no penalty | `ledger` | `Exam.expired`, `Exam.timed_out`, `exam_draw`, `exam_report`, `exam_recuse` |
| `LOT_DRAW_DAYS` | 7 days | a lot is drawn while `not expired(drand_time(round), now, 7)` on the **effective clock**; then an exam's lot has lapsed (it timed out) and a council call has lapsed | `ledger` | `Exam.draw_lapsed`, `exam_draw` (F3a), `ledger.council_lapsed`, `council_call`, `council_draw`, `ledger.due_actions` |
| `EXAM_RETRY_DAYS` | 90 days | `waited` on the **effective clock**, from the opening of the failed exam | `ledger` | `exam_open` |
| `COUNCIL_SEATS` | 33 seats | | `canon` | `council_call`, `council_draw` |
| `COUNCIL_TERM_DAYS` | 1,095 days (3 × 365) | a seat is held while `now ≤ seat_until` | `canon` | `council_draw`; `Member.seated` |
| Council eligibility degree | 32 | | literal in `ledger._council_pool` | `council_call`, `council_draw` |
| Council degree | 33 | | literal in `ledger._council_draw` | `council_draw` |
| `WAIT_DAYS_MAX` | 3,650 days | | `canon` | bounds of a degree table (section 8.4) |
| `EXAMINERS_MAX` | 33 examiners | | `canon` | same |
| `CANON_MAX_BYTES` | 262,144 bytes | | `canon` | the largest file that can be a degree table (section 8.4) |

### 3.6 Constants of the gate and of the tools (not replayed)

| Name | Value | Defined in | Used by |
|---|---|---|---|
| `CLOCK_TOLERANCE` | 6 hours (past tolerance) | `ledger` | `verify.verify_report` |
| `JUDGE_FUTURE_TOLERANCE` | 2 minutes (future tolerance of a merge) | `ledger` | `verify.verify_report` (section 9.2) |
| `FUTURE_TOLERANCE` | 10 minutes (a merged head dated further ahead is an alarm) | `ledger` | `ledger.future_head` (section 9.7), which `verify.verify_report` asks with `--online` (step 5 of section 9.1) |
| `FOUNDER_GITHUB_ID` | the `founder_github_id` of `src/openmasonry/network.toml`; 0 in a tree where it is not set | `canon` | `identity.pr_problems`: the account a genesis comes from (section 9.3) |
| `CARRIED` | `depart, rekey_object` | `identity` | `identity.pr_problems`: member entries any pull request may carry (section 9.3) |
| `CANDIDATE_TIMEOUT` | 3,600 seconds | `verify` | `verify.candidate_problems`: how long a candidate core may take to replay (section 9.1) |
| `HEADS_VERSION` | 1 | `ledger` | `ledger.remember_head`: the `v` of a client's memory of verified heads (section 9.7) |
| `KEYS_URL` | `https://github.com/{login}.keys` | `identity` | `identity.fetch_github_keys` |
| key list read cap | 262,144 bytes, timeout 10 s | `identity` | `identity.fetch_github_keys` |
| `USER_URL` | `https://api.github.com/users/{login}` | `identity` | `identity.fetch_github_user` |
| account answer read cap | 262,144 bytes, timeout 10 s | `identity` | `identity.fetch_github_user` |
| `RELAYS` | `https://api.drand.sh`, `https://api2.drand.sh`, `https://drand.cloudflare.com` | `beacon` | `beacon.fetch`: tried in this order |
| beacon fetch timeout | 10 s per relay | `beacon` | `beacon.fetch` |
| `CANONICAL_REPO` | the `repository` of `src/openmasonry/network.toml` (`openmasonry/openmasonry`), or the environment variable `OM_CANONICAL` where it is set | `canon` | the canonical ledger of a clone (section 9.7); the tools that clone, fetch and publish. No rule of replay or of the gate reads it |
| `ROOMS` | 33 rooms | `rooms` | `rooms.team`, `rooms.team_degree`, `rooms.readers`: one room, one team and one private repository per degree (section 15) |
| `OPS` | `remove, cancel, move, invite, hold` | `rooms` | `rooms.sync_plan`: the order of a plan (section 15.2) |

### 3.7 The degree table

`wait_days(d)` and `examiners(d)` are not code constants. They come from the degree table pinned at the moment they are read (section 8.4), so an amendment of `canon/degrees.toml` changes them from the entry that closes its ballot onward. Every table replay reads has passed the validation of section 8.4: `0 ≤ wait_days(d) ≤ 3650`, `0 ≤ examiners(d) ≤ 33`, and `examiners(d) ≥ 1` for `2 ≤ d ≤ 32`. The table currently in the repository (digest `cc5055199c8213648f536a6856c9d6879944c48be7151593ad279f73b84b7b32`) gives:

| Degree `d` | `wait_days(d)` | `examiners(d)` |
|---|---:|---:|
| 1 | 0 | 0 |
| 2 | 30 | 2 |
| 3 | 60 | 3 |
| 4 | 180 | 3 |
| 5 to 13 | 30 | 3 |
| 14 | 30 | 5 |
| 15 | 180 | 3 |
| 16, 17 | 60 | 3 |
| 18 | 60 | 5 |
| 19 | 365 | 3 |
| 20 to 29 | 60 | 3 |
| 30 | 60 | 5 |
| 31 | 365 | 5 |
| 32 | 365 | 7 |
| 33 | 730 | 0 |

`wait_days(d)` is the minimum time a member must have held degree `d − 1` (`waited`). `wait_days(33)` is the time a member must have held the 32nd degree to enter the Council lot.

### 3.8 Custodians and corrections

| Name | Value | Form | Defined in | Used by |
|---|---|---|---|---|
| `CUSTODIANS_MAX` | 3 custodians | | `ledger` | genesis (G14) |
| `CUSTODIAN_SILENCE_DAYS` | 180 days, wall time | a custodian key is live until `expired`, counted from its last sign of life | `ledger` | `State.custodian_end` |
| `CUSTODIAN_TERM_DAYS` | 2,555 days (7 × 365), wall time | a custodian key is live until `expired`, counted from the genesis that named it, or from the application of the claim that named it | `ledger` | `State.custodian_end` (section 7.9) |
| `CLAIM_NOTICE_DAYS` | 30 days, wall time | a claim is applied once `waited`, counted from the claim | `ledger` | `custodian_claim_apply` (CA3); `State.claim_status` |
| `CLAIM_EXPIRY_DAYS` | 60 days, wall time | a claim is alive until `expired`, counted from the claim | `ledger` | `State.claim_status`, `State.claim_pending` |
| `CLAIM_MASTERS` | 3 | | `ledger` | a claim needs fewer than this many active Master Builders who are not founders (CL4, CA4) |
| `CLAIM_AGAIN_DAYS` | 30 days, wall time | `waited`, counted from the objection that voided the latest claim | `ledger` | `custodian_claim` (CL5a): after an objection, the next claim of any founder |
| `SUNSET_MASTERS` | 7 active Master Builders who are not founders | | `ledger` | `ledger.sunset_reached` (section 7.9) |
| `SUNSET_WITNESSES` | 4 witnesses | | `ledger` | the same |
| `FREEZE_DAYS` | 30 days, wall time | interval `[start, start + 30 d)` | `ledger` | acts `freeze_key`, `freeze_witness` |
| `REFREEZE_AFTER_DAYS` | 90 days, wall time | `waited`, from the start of every earlier freeze of the login that other custodians did not withdraw | `ledger` | act `freeze_key` (FK3) |
| `FREEZE_CAP_DIVISOR` | 10: keys frozen at once are at most `max(1, n div 10)` for `n` active members who are not dormant (`len(active(now))`) | | `ledger` | act `freeze_key` (FK4) |
| `STAY_DAYS` | 14 days, wall time | interval | `ledger` | act `stay` |
| `HALT_DAYS` | 14 days, wall time | interval | `ledger` | act `halt` |
| `HALT_INTERVAL_DAYS` | 90 days, wall time | `waited`, from the start of the previous halt | `ledger` | act `halt` (HT1) |
| `HOLD_DAYS` | 14 days, wall time | interval | `ledger` | act `hold_room` |
| `REHOLD_AFTER_DAYS` | 90 days, wall time | `waited`, from the start of every earlier hold of the login that other custodians did not withdraw | `ledger` | act `hold_room` (HR4) |
| `NOTES_PER_DAY` | 10 notes per custodian per UTC calendar day | | `ledger` | act `note` (NT4) |
| `NOTES_KEPT` | 200: the state keeps the newest 200 notes | | `ledger` | `correction`, act `note` (section 6.19.6) |
| `CORRECTIONS_PER_30_DAYS` | 5 corrections, notes aside, all custodians together; and for one custodian `⌈5 / n⌉` of them, with `n` the custodian keys live at the entry | | `ledger` | `correction` (N6, N6a) |
| `REPOST_AFTER_DAYS` | 90 days, wall time | `waited`, from the moment objections voided a correction with the same act and the same target | `ledger` | `correction` (N7) |
| `CORRECTION_WINDOW_DAYS` | 30 days, wall time | a correction counts until `waited` | `ledger` | `correction` (N6) |
| `OBJECTION_DAYS` | 90 days, wall time | objections are accepted until `expired`, counted from the correction or, for a noticed act that was applied, from its application | `ledger` | `correction_object` (J7) |
| `NOTICE_DAYS` | 14 days, wall time | a noticed act may be applied once `waited` | `ledger` | `correction_apply` (AP4); `State.notice_end` |
| `APPLY_WINDOW_DAYS` | 7 days, wall time | a noticed act is applied until `expired(time, now, 14 + 7)`, or never | `ledger` | `State.apply_end`, `State.noticed_status` |
| `UNDO_WINDOW_DAYS` | 90 days, wall time | a ballot is undone by a correction posted until `expired`, counted from its close | `ledger` | act `undo_ballot` (UB6) |
| `RECOVER_NOTICE_DAYS` | 21 days, wall time | a recovery that follows a freeze may be applied once `waited`, counted from the request | `ledger` | `State.recovery_notice_end`; `rekey_recover_apply` (RA4) |
| `RECOVER_OPEN_NOTICE_DAYS` | 30 days, wall time | an open recovery may be applied once `waited`, counted from the start of its notice | `ledger` | the same |
| `RECOVER_LOWERED_NOTICE_DAYS` | 45 days, wall time | any recovery whose co-signers are lowered at `now` (`ledger.lowered`), or that was dropped (`ledger.dropped`), may be applied once `waited`, counted from the start of its notice | `ledger` | `State.recovery_notice_days`; `rekey_recover_apply` (RA4) |
| `RECOVER_EXPIRY_DAYS` | 60 days, wall time | a recovery is alive until `expired`, counted from the start of its notice, or from the request while the notice has not started | `ledger` | `State.recovery_end`, `State.recovery_status` |
| `RECOVER_INTERVAL_DAYS` | 90 days, wall time | `waited`, from the previous request of the login, and from the objection that stopped it | `ledger` | `rekey_recover` (RR5, RR6) |
| `RECOVER_COSIGNERS` | 2 Master Builders, or as many active Master Builders other than the member who answered within `ANSWER_DAYS` as exist | | `ledger` | `ledger.nominal_cosigners`, `ledger.cosigners_needed`: a recovery that follows a freeze (RA5) |
| `RECOVER_OPEN_COSIGNERS` | 3 Master Builders, or as many active Master Builders other than the member who answered within `ANSWER_DAYS` as exist | | `ledger` | the same: an open recovery (RC6, RA5) |
| `RECOVER_FINAL_COSIGNERS` | 3 Master Builders, or as many active Master Builders other than the member who answered within `ANSWER_DAYS` as exist | | `ledger` | the same: the recovery that follows one the old key stopped (RA5) |
| `RECOVER_DROP_DAYS` | 30 days, wall time | a request is dropped once `now ≥ time + 30 d` without all the co-signatures it needed | `ledger` | `Recovery.drop_time`, `ledger.dropped`, `ledger.cosigners_needed`, `State.recovery_start` (section 6.26) |
| `DEPART_RECOVER_DAYS` | 30 days, wall time | a departed member asks for a recovery while `not expired`, counted from the departure | `ledger` | `rekey_recover` (RR3a) |
| `DEPART_FOLLOW_DAYS` | 150 days, wall time (`RECOVER_INTERVAL_DAYS + RECOVER_EXPIRY_DAYS`) | a request that follows a recovery asked in time for the departure comes while `not expired`, counted from the later of that recovery's `time` and `objected` | `ledger` | `rekey_recover` (RR3a, `follows`) |
| `ANSWER_DAYS` | 365 days, wall time | a Master Builder counts among the co-signers a recovery waits for while their `heard`, or their `since[3]`, is `not expired` (section 6.26) | `ledger` | `ledger.answering_masters`, `ledger.cosigners_needed`, `ledger.dropped`, `ledger.only_sponsors` |
| `OBJECTION_DIVISOR` | 5: a correction is void at `max(1, ⌈E / 5⌉)` objections | | `ledger` | `ledger.objections_needed` |
| `ACT_DAYS` | `freeze_key` 30, `freeze_witness` 30, `stay` 14, `halt` 14, `hold_room` 14 | days | `ledger` | `correction`, effect 1 |
| `ACT_GROUND` | `freeze_key`: `key_compromised`; `halt`: `attack_in_progress`; `note`: `moderation` | | `ledger` | `correction` (N5) |
| `MAX_ACT_DAYS` | 30: the longest of `ACT_DAYS` | days | `ledger` | `State.acting`: a record that old is never in force |
| `ALIVE_INTERVAL` | 24 hours, wall time | `now − alive ≥ 24 h` | `ledger` | `custodian_alive` (AL1) |
| `SECOND` | 1 second: the resolution of every time | | `ledger` | `State.custodian_end`, `State.void_span`, `ledger.make_entry` |

### 3.9 Rate limits

Section 5.4 states the rules and the reasons for these values.

| Name | Value | Form | Defined in | Used by |
|---|---|---|---|---|
| `ENTRIES_PER_DAY` | 20 entries per actor per UTC calendar day | | `ledger` | `ledger.apply` (C12a) |
| `DAILY_EXEMPT` | `depart, rekey, rekey_object, custodian_revoke, correction_object, custodian_claim_object, rekey_recover, rekey_cosign, rekey_oppose, rekey_recover_apply, ballot_commit, ballot_reveal, ballot_close, exam_draw, council_draw` | set of types | `ledger` | `ledger.daily_exempt` (C12a, C14a): types that are neither counted nor refused for the count; so is a `ballot_open` of an `UNSTOPPABLE_KINDS` kind |
| `OPEN_BALLOTS_PER_OPENER` | 3 open ballots per opener of the kinds other than `amendment` and `custodian`, together; and, counted apart, 3 open amendment ballots; a ballot of kind `custodian` is never counted | | `ledger` | `ballot_open` (B7b) |
| `REOPEN_AFTER_DAYS` | 90 days, wall time | `waited`, from the close of a ballot of the same opener on the same subject that `failed` or `lapsed` | `ledger` | `ballot_open` (B7a) |
| `REOPEN_KINDS` | `sanction, witness` | set of ballot kinds | `ledger` | `ballot_open` (B7a): the kinds the wait applies to, a re-run aside |
| `CHECKPOINT_INTERVAL` | 1 hour of ledger time | `now − time of the witness's last checkpoint ≥ 1 h` | `ledger` | `witness` (Z7); `ledger.checkpoint_due` |
| `ALIVE_INTERVAL` | 24 hours | section 3.8 | `ledger` | `custodian_alive` (AL1) |

---

## 4. State

The state is the dataclass `ledger.State`. Field names below are the names in the code. "Stored" means the value is a fact recorded by some entry and changes only when an entry changes it. "Derived" means a pure function of stored facts and a time `now`; a derived view is never stored and can change with `now` alone.

The order of the keys of a map is not significant, with one exception noted in section 5.2 (which collision a refusal message names). Lists and tuples are ordered.

### 4.1 `State`

| Field | Type | Initial | Meaning |
|---|---|---|---|
| `name` | string | `""` | Name of the fraternity, set at genesis. |
| `head` | hex string | `ZERO_HASH` | Entry hash of the last applied entry. |
| `seq` | integer | `−1` | `seq` of the last applied entry. |
| `time` | time or null | null | Time of the last applied entry. |
| `declaration_sha256` | hex string | `""` | The digest of the Declaration, recorded at genesis. Every petition must carry it. |
| `members` | map login → Member | empty | Every login ever admitted or founded. Records are never removed. |
| `witnesses` | map name → key | empty | The current witnesses. |
| `custodians` | map name → Custodian | empty | Every custodian the genesis or a founder's claim named, live or not (section 4.8). Records are never removed. |
| `custodian_threshold` | integer | 0 | The number the genesis stated: 0 without custodians, otherwise 1 to their number; set to 1 by the application of a founder's claim, whose custodian is then the only live one (section 6.33). It is the number of custodian keys a **noticed** act needs before it is applied (CS5, AP5), and the number of custodians who together withdraw a correction they did not post (section 6.20). An immediate act is the act of one key whatever this number. |
| `corrections` | map integer → Correction | empty | Every correction ever accepted, notes aside, under the `seq` of its entry (section 4.9). Records are never removed. |
| `notes` | list of Note | empty | The newest `NOTES_KEPT` = 200 notes, in order (sections 4.6 and 6.19.6). When a new one is recorded, the oldest beyond 200 leaves the list for the history `notes` (section 4.11); it stays in its entry. |
| `sunset` | time or null | null | The time of the entry at which the Sunset condition first held (section 7.9). Set once. |
| `recoveries` | map login → Recovery | empty | The latest key recovery of each login that ever asked for one, whatever became of it (section 4.10). A new request of the same login replaces the record. |
| `invitations` | map login → Invitation | empty | Invitations not yet followed by their petition. A lapsed invitation stays in the map and counts for nothing (section 4.3) until a new invitation of the same login replaces it. |
| `petitions` | map login → Petition | empty | Petitions not yet decided. A lapsed petition stays in the map and counts for nothing (section 4.3) until a new petition of the same login replaces it. |
| `ballots` | map id → Ballot | empty | Every ballot that is open, or that ended (closed, or voided) at most `BALLOT_RETIRE_DAYS` = 111 days ago. A ballot that ended longer ago is read by no rule: it leaves the map for the history `ballots`, and its id goes to `retired` (section 4.11). |
| `exams` | map (login, degree) → Exam | empty | The latest exam of each login for each degree, within the login's current membership. |
| `hashes` | list of hex string | empty | `hashes[i]` is the entry hash of entry `i`. The state document leaves it out: `head` and `seq` commit to it (section 4.11). |
| `pins` | map path → hex | empty | Governed path → the SHA-256 last ratified for it. |
| `prior_pins` | map path → hex | empty | For a path amended at least once after it was pinned: the pin just before its latest amendment. |
| `prior_until` | map path → time | empty | Until which ledger time the prior pin is still lawful in the tree. |
| `council_call` | integer or null | null | The drand round of a pending Council draw; null when none is pending. |
| `council_pool` | tuple of login | empty | The pool frozen by a pending `council_call`; emptied by the draw. |
| `day` | string | `""` | The UTC calendar day of the last applied entry: the first ten characters of its `time` (`YYYY-MM-DD`). |
| `day_entries` | map actor → integer | empty | For the day `day`: how many entries of each actor were counted (section 5.4). Emptied when an entry of a later day is applied, so it holds only the actors of one day. |
| `acts` | integer | 0 | How many applied entries have a `type` other than `witness`. Read by one rule: a witness posts a checkpoint only when this number has grown since its last one (Z6). |
| `witness_marks` | map name → `{acts, time}` | empty | For each witness that ever posted a checkpoint: the value of `acts` and the time at its latest one. Records are never removed. Read by Z6 and Z7. |
| `claims` | map integer → Claim | empty | Every founder's claim of the Custodian office ever accepted, under the `seq` of its `custodian_claim` entry (section 4.6). Records are never removed. |
| `succession` | Succession or null | null | The latest succession claim, whatever became of it (section 4.6). A new claim replaces it. |
| `epoch` | integer | 0 | The **protocol epoch**: how many amendments of `@protocol` passed (section 6.7). Read by no rule of this core. It moves at the close of the ballot, before the new core is merged, so a later core does not branch on it alone (section 12, point 68). |
| `history` | map name → `(count, acc)` | each of `HISTORY` → `(0, ZERO_HASH)` | For each **history** (`amendments`, `ballots`, `beacons`, `checkpoints`, `notes`): how many records it absorbed, and the hash chain of their leaves (section 4.11). A record no rule reads enters it once, and is not kept: every passed Amendment, every Checkpoint, every Beacon a lot used, every ballot of `ballots` that ended more than 111 days ago, every note beyond the newest 200. |
| `retired` | set of ballot id | empty | The id of every ballot the history `ballots` absorbed. An index of that history, left out of the document (a function of what the history absorbed). Read by B3 (an id is never used twice), UB0 and B2r. |
| `degree_tables` | list of hex string | empty | The `new_sha256` of every passed amendment of `canon/degrees.toml`, in order. An index of the history `amendments`, left out of the document. Read by no rule: the tree gate archives every table the ledger ever pinned (section 8.5, step 4a). |
| `known_keys` | set of hex string | empty | The point (64 lowercase hexadecimal characters) of every key an accepted entry ever registered: the keys of the founders and witnesses of the genesis, the custodian key and the revoke key of every custodian it named, the key of every petition, the key of every witness ballot that proposed to add a witness, the new key of every `rekey`, the new key of every `rekey_recover`, and the custodian key and the revoke key of every `custodian_claim`. Every one of them proved possession when it was registered: it signed the entry (the first founder, a petition, a `rekey_recover`) or a proof inside it (G21a, G21b, G22, W7, Q5, RR9, CL8). It only grows. Read by three rules: neither a `rekey`, nor a `rekey_recover`, nor a `custodian_claim` ever registers a point in this set (sections 6.18, 6.26 and 6.31). |

### 4.2 `Member`

| Field | Type | Stored / derived | Meaning |
|---|---|---|---|
| `login` | string | stored | The login, exactly as first written. |
| `key` | string | stored | The member's public key: the founder's key at genesis, otherwise the key of the petition. Replaced only by a `rekey` signed by the member (section 6.18) or by the application of a recovery (section 6.29). |
| `degree` | integer 1 to 33 | stored | Current degree. |
| `since` | map degree → time | stored | When the member received each degree held in this record. Founders have `since[1] = since[2] = since[3]` = genesis time. `since[1]` is the time of admission and identifies the **membership** (below). |
| `sponsors` | tuple of login | stored | The sponsors frozen by the admission ballot, the inviter first and then in vouch order. Empty for founders. |
| `status` | `active`, `suspended`, `expelled`, `departed` or `voided` | stored | The recorded status. `suspended` is not rewritten to `active` when the suspension has been served; `standing` does that. `voided` is the status of a record whose admission a correction undid (section 6.19.8): it is not a sanction, and the login may be invited again once `REJOIN_AFTER_DAYS` = 90 days have passed, like a login that departed. The three statuses of `GONE` (`departed`, `expelled`, `voided`) are those of a record that is no longer a membership. |
| `activity` | list of time | stored | At most one time per UTC calendar day on which the member was credited (section 5.3): the time of that day's latest credited entry. Starts with the time of genesis or admission. Ascending. No time in it is more than `LIGHT_WINDOW_DAYS` = 1,800 days older than the last one: an older point is dropped when the member is credited again. Rules read the last time alone (`dormant`). |
| `seat_until` | time or null | stored | End of the Council seat, if the member was drawn and the seat was not removed. |
| `past_seats` | integer | stored | Number of times the login was drawn to the Council. Survives a re-admission of the same GitHub account (section 6.4.1). |
| `status_since` | time or null | stored | Time of the last status change by a sanction, a departure or the undo of the admission. Null if none. A departure that a recovery reverses puts back the value from before it (section 6.29). |
| `suspended_until` | time or null | stored | End of the current suspension. A departure does not clear it, and a suspension still running is carried into a new membership of the same GitHub account (section 6.4.1). |
| `sponsor_ban_until` | time or null | stored | The member may not sponsor before this time. Survives a re-admission of the same GitHub account. |
| `founder` | boolean | stored | True for a member created by genesis, and for every later record of the same login under the same GitHub account: the mark follows the person through a departure and a new admission (section 6.4.1). |
| `last_work` | time or null | stored | Time of the member's latest `work` entry. |
| `fraud_history` | tuple of time | stored | The times at which this login was expelled for fraud. Survives a re-admission of the same GitHub account. Read by no rule. |
| `github_id` | integer | stored | The numeric id of the GitHub account behind the login: the founder's `github_id` at genesis, otherwise the one the invitation stated. Positive. A new admission of the login records the id of its new invitation. Read by the account rule of section 4.7 (`id_holders`: G13, I8, A4); whether the login is that account on GitHub is the gate of section 9.3, checked when the entry that states it is merged. |
| `last_rekey` | time or null | stored | Time of the member's latest change of key: a `rekey` entry, or the application of a recovery. Null in a new record: it does not survive re-admission. |
| `left` | object or null | stored | Null, except in the record of a member who departed (section 6.15): then `{status, status_since, seat_until}`, the three values the record held before that departure (the two times in the text form of section 2.5, and left out when null). Read by `ledger.recoverable` and by the application of a recovery, which puts the three back and sets `left` to null (section 6.29). |
| `missed` | tuple of time | stored | For a record whose calls are recorded (degree 3 or higher, or any record while a succession is in force; section 7.7): the end times of at most 2 calls (examinations and ballots) it answered nothing in, ascending, at least 7 days apart, none `expired(t, now, 180)` as of the last call recorded (`Member.called`, section 7.7). Empty in a new record. |
| `heard` | time or null | stored | For the same records: the latest of its revealed votes and reports and of the end times of the calls it answered (section 7.7). Null in a new record. |
| `standing(now)` | status | derived | `active` if `status = suspended`, `suspended_until` is set and `now ≥ suspended_until`; otherwise `status`. |
| `is_active(now)` | boolean | derived | `standing(now) = active`. |
| `dormant(now)` | boolean | derived | `expired(last, now, 365)`, with `last` the latest time in `activity` (or `since[1]` if the list is empty). |
| `silent(now)` | boolean | derived | False when `heard` is set and `not expired(heard, now, 180)`; otherwise true exactly when at least 2 times of `missed` are `not expired(t, now, 180)` (`SILENT_DAYS`, `SILENT_CALLS`; section 7.7). |
| `seated(now)` | boolean | derived | `seat_until` is set and `now ≤ seat_until`. The status is not considered. |
| `light(now)` | real | derived, informational | `Σ 0.5^((now − t) / 180 d)` over `t` in `activity`, which holds the points of the 1,800 days before the newest one (a point that was dropped weighed less than `2^−10`). Never read by any rule, and never part of the state document. Implementations need not reproduce its floating-point value. |

The **membership** of a record is the text form of `since[1]` (`ledger.membership`). A login that departs, is expelled or has its admission undone, and is admitted again, gets a new record with a later `since[1]`, hence another membership. A ballot about a member records the membership it was opened on (section 4.4) and never changes a later one.

### 4.3 Invitation and petition

`S.invitations[login]` is a record with three fields, all stored:

| Field | Type | Meaning |
|---|---|---|
| `by` | login | The Master Builder who signed the `invite` entry: the candidate's first sponsor. |
| `github_id` | integer | The numeric id of the GitHub account the inviter named. Positive. |
| `time` | time | Time of the `invite` entry. |

An invitation of `login` is **live** at `now` (`State.invited(login, now)`) when `S.invitations` has the key `login`, exactly as spelled, and `not expired(i.time, now, 30)` on the **effective clock** (section 7.8): a halt does not use up an invitation. A live invitation holds its name (section 4.7) and counts against its inviter's budget (section 7.5). An invitation that is not live has **lapsed**: it holds nothing, blocks nothing and counts for nothing. Lapse is a matter of time alone: no entry makes an invitation lapse, and no entry removes one except the petition that takes its place (section 6.2) and a later invitation of the same login (section 6.17).

`S.petitions[login]` is a record with four fields, all stored:

| Field | Type | Meaning |
|---|---|---|
| `key` | string | The key the petitioner chose and signed with. |
| `vouches` | list of login | The sponsors, in order: first the Master who invited, then the Masters who vouched. |
| `time` | time | Time of the `petition` entry. |
| `github_id` | integer | The `github_id` of the invitation the petition was filed under. |

Derived views of a petition `p` of `login` at `now`:

- **live** (`State.live`): `not expired(p.time, now, 180)` on the **effective clock** (section 7.8).
- **reserved** (`State.reserved`): live, **or** an admission ballot on `login` is open. A reserved petition holds its name and its key (section 4.7) and counts against its sponsors' budgets (section 7.5).
- **lapsed**: not reserved. A lapsed petition holds nothing, blocks nothing and counts for nothing. Lapse is a matter of time alone: no entry is needed to make a petition lapse.

### 4.4 `Ballot`

| Field | Type | Stored / derived | Meaning |
|---|---|---|---|
| `id` | string | stored | The ballot id. |
| `kind` | string | stored | One of `KINDS`. |
| `subject` | object | stored | A copy of the `subject` of the `ballot_open` body. |
| `electors` | set of login | stored | The electorate, fixed at opening: every eligible member, the dormant ones included (section 7.1). Nothing is ever added to it or removed from it. |
| `commit_until` | time | stored | Opening time + `commit_days` d. |
| `reveal_until` | time | stored | `commit_until` + `REVEAL_GAP` + `reveal_days` d. |
| `opened_by` | login | stored | Actor of the `ballot_open` entry. |
| `commits` | map login → hex | stored | One commitment per elector who committed. |
| `reveals` | map login → `yes` or `no` | stored | The revealed votes, one per elector who revealed. |
| `result` | null, `passed`, `failed`, `lapsed`, `voided` or `undone` | stored | Null while the ballot is **open**. Set to `passed`, `failed` or `lapsed` by its `ballot_close` (`lapsed`: the votes cast did not reach the quorum, section 6.7). An open ballot becomes `voided`, and a passed one `undone`, only by the application of a noticed correction (section 6.25); no other change of a result exists. The five values are `RESULTS`. |
| `closed` | time or null | stored | Time of the `ballot_close` entry. Null for a ballot that was never closed (open, or voided). |
| `undo` | map field → `[before, after]` | stored | The **undo record**, written at the close of a ballot that `passed` and whose kind can be undone (section 6.7): for each fact the ballot set, its value before and after the close. Empty for every other ballot. |
| `corrected` | integer or null | stored | The `seq` of the correction that voided or undid the ballot. Set once. |
| `opened` | time | stored | Time of the `ballot_open` entry: where the ballot's own clock starts (section 7.8). |
| `frozen` | object | stored | What the electors vote on, fixed at opening. Admission: `{key, vouches, github_id}`, the petition's key, its valid sponsors and its GitHub account id. Advancement: `{admitted}`, the membership of the subject, a time in the text form of section 2.5. Sanction: `{admitted}`, and `master: true` when the subject holds the 3rd degree or higher and the measure is not `reinstate` (section 6.4.4). Amendment: `{base}`, the pin of the path when the ballot opened, `""` for a path not pinned (section 6.4.3). Empty for witness and custodian. |
| `base` | integer or null | stored | The **quorum base**: how many electors the quorum and the turnout count (section 7.1). The electors who were **present** (not dormant) at the opening, or for a re-run those of them who voted in the lapsed ballot, at least 1 (B9). Null when it equals the number of electors. |
| `rerun` | string | stored | The id of the lapsed ballot this one re-runs (B2a); empty for any other ballot. |
| `quorum_base()` | integer | derived | `base`, or `len(electors)` while `base` is null. |
| reveal opens | time | derived | `commit_until + REVEAL_GAP`. |
| ballot time at `now` | time | derived | `ballot_time(b, now) = opened + effective(opened, now, id)` (section 7.8): where the ballot's own clock stands. Equal to `now` for a ballot that was never halted, stayed or under a pending `void_ballot`. The three windows compare **this** time with `commit_until` and `reveal_until`, which are never rewritten. |

A ballot is **open** exactly while `result` is null, whatever the time. The **subject key** of a ballot (`ledger.subject_key`) is `fold` of: `candidate` for admission, `member` for advancement, `name` for witness, `remove` for custodian; for amendment `fold(path)`, the character `|` and `new_sha256` (a slot per text proposed, so a pending amendment never holds a path against another text); and for sanction `fold(member)`, the character `|` and `measure` (a sanction is about a member **and** a measure, so a ballot on one measure never holds the place of another). `open_ballot_on(kind, key)` is the open ballot of that kind with that subject key, if any.

### 4.5 `Exam`

| Field | Type | Stored / derived | Meaning |
|---|---|---|---|
| `candidate` | login | stored | The member examined. |
| `degree` | integer | stored | The degree examined for. |
| `examiners` | tuple of login, or null | stored | Null until the draw. Then the current examiners: the first `k` of `ranking`, changed only by recusals. |
| `beacon_round` | integer | stored | The drand round whose randomness the draw must use. Positive. |
| `opened` | time | stored | Time of the `exam_open` entry. |
| `reports` | map login → `pass` or `fail` | stored | One verdict per examiner who reported. |
| `pool` | tuple of login | stored | The examiner pool, frozen at `exam_open`, in ascending login order. |
| `work_ref` | string | stored | The URL of the masterwork. |
| `ranking` | tuple of login | stored | The whole pool in lot order, set by `exam_draw`. |
| `recused` | tuple of login | stored | Examiners who recused, in order. |
| `k` | integer | stored | Number of examiners to draw, frozen at `exam_open`. At least 1. |
| `consumed` | boolean | stored | An advancement ballot has been opened on this exam, and neither lapsed (section 6.7) nor was voided since (section 6.19.7). |
| `ballot_failed` | boolean | stored | That advancement ballot was lost on the votes. |
| `lapsed` | boolean | stored | The exam ended without a verdict that counts and without penalty: a recusal found no replacement, the advancement ballot was won on the votes but could not be applied, or the advancement it supported was undone by a correction (section 6.19.8). |
| `skipped` | tuple of login | stored | The silent examiners of the exams before, left out of this exam's pool (E8a), in ascending login order: those of the exam this one replaced, and, when that exam ended (lapsed or timed out), the `skipped` it carried. So the set grows from exam to exam while anyone else can be drawn. Empty when they could not be left out (nobody else could be drawn, and the pool was computed again without them) or there were none. |
| `expired(now)` | boolean | derived | `expired(opened, now, 60)` on the **effective clock** (section 7.8; `Exam.expired(now, S)`). |
| `draw_lapsed(now)` | boolean | derived | `examiners` is null, not `lapsed`, and `expired(drand_time(beacon_round), now, 7)` on the **effective clock** (`LOT_DRAW_DAYS`): the lot was not drawn in time, for instance because the beacon is unavailable for good. |
| `passed()` | boolean | derived | Not `lapsed`, not `ballot_failed`, `examiners` is neither null nor empty, and `2 × (number of pass reports) > len(examiners)`. An exam with no examiners never passes. |
| `failed(now)` | boolean | derived | False if `lapsed`. Otherwise true if `ballot_failed`; otherwise false if `passed()`; otherwise true exactly when `examiners` is non-empty and `2 × (number of fail reports) ≥ len(examiners)`. Running out of time is no failure. |
| `timed_out(now)` | boolean | derived | Not `lapsed`, not `ballot_failed`, not `passed()`, not the fail rule above, and `expired(now)` or `draw_lapsed(now)`: no verdict was reached in time because an examiner never reported or the lot was never drawn. No penalty. |
| `ended(now)` | boolean | derived | `lapsed` or `timed_out(now)`: a new exam for the same degree may open at once (E6). |
| `silent(now)` | tuple of login | derived | When `timed_out(now)` and `examiners` is non-empty: the examiners not in `reports`, in their order; otherwise empty. |

An exam is in exactly one of five conditions at `now`: **lapsed**, **passed**, **failed**, **timed out**, or **undecided** (none of the four). Until an exam lapses, `len(examiners) = k` from the draw on, because a recusal either seats a replacement or lapses the exam; `passed()` and the fail rule are therefore majorities of `k`, and one can never follow the other. A timed-out exam is one in which neither majority was reached, so some examiner did not report: when all `k` reported, one of the two majorities holds.

### 4.6 Other records

The first three records below are never kept in the state: each is absorbed by its history the moment it is made (section 4.11), and the entries hold everything it says.

- **Amendment:** `{ballot, path, new_sha256, time}`, made by the close of a passed amendment ballot. `time` is a string in the text form of section 2.5 (`YYYY-MM-DDTHH:MM:SSZ`).
- **Checkpoint:** `{witness, upto_seq, head, state_sha256, state_version, root, anchor}`, made by a `witness` entry; `root` and `anchor` are the body's values, null (and so left out of the record) when the body has no such field.
- **Beacon:** `{round, beacon}`, made by an `exam_draw` or a `council_draw`.
- **Note:** `{seq, by, action, target, rule, reason_sha256, time}`: the `seq` of the `correction` entry whose act is `note`, the custodian who signed it, the three fields of its target, the digest of its public reason and the time of the entry.
- **Claim** (`ledger.Claim`, section 6.31): `seq` (of the `custodian_claim` entry), `founder` (its actor), `name`, `key`, `revoke_key`, `time`, all stored when it is accepted; `objected` (time or null) and `objector` (login, `""` until then), set once by a `custodian_claim_object`; `applied` (time or null), set once by a `custodian_claim_apply`. Derived: `claim_status(c, now)`, the first that holds: `applied` when `applied ≤ now`; `objected` when `objected ≤ now`; `expired` when `expired(time, now, 60)`; `ready` when `waited(time, now, 30)`; otherwise `pending`. A claim that is `pending` or `ready` is **alive**; `claim_pending(now)` is the alive claim, if any (never two at once, CL5).
- **Succession** (`ledger.Succession`, section 6.34): `seq`, `by`, `time`, all stored by the `succession_claim`; `end` (time or null) and `canceled_by` (login, `""` unless canceled), set once by C14b. Derived: `succession_status(now)`: none when `S.succession` is null; `canceled` when `end ≤ now` and `canceled_by` is not empty; `ended` when `end ≤ now`; `in_force` when `waited(time, now, 90)`; otherwise `pending`.

### 4.7 Derived views of the state

| View | Definition |
|---|---|
| `active(now, d, X)` | The logins of members with `is_active(now)`, `degree ≥ d`, not `dormant(now)`, and not in the set `X`; in ascending order of login (code point order). `d` defaults to 1 and `X` to the empty set. |
| `masters(now)` | `active(now, 3)`. Includes every degree from 3 to 33. |
| `present_masters(now)` | The logins of `masters(now)` whose record is not `silent(now)` (section 7.7), in the same order. Read by the succession (SC2, C14b). |
| `eligible(S, now, d, X)` | Like `active`, with the dormant members kept: everyone of degree `≥ d`, not in `X`, with `is_active(now)`. The voters of a rung (section 7.1). |
| `electorate(S, kind, subject, now)` | Section 7.1: `(electors, base)`. `electors_for` is its first half. |
| `non_founder_masters(now)` | The number of `masters(now)` whose record has `founder` false. Read by the Sunset (section 7.9) and the founder's fallback (CL4, CA4). |
| `succession_status(now)`, `successors(now)`, `stands_in(login, now)` | Section 6.34: where the succession stands; while it is `in_force`, the logins of `active(now)` of the highest degree `t` present, when `1 ≤ t ≤ 2` (else none), where a member who is `silent(now)`, of any degree, is not present; and whether `login` holds the 3rd degree or is a successor. |
| `claim_status(c, now)`, `claim_pending(now)` | Section 4.6. |
| `founding_phase(now)` | `len(masters(now)) < 7`. A condition, not an era: it can lapse and resume. |
| `seats(now)` | The logins of members with `seated(now)`; ascending. Neither status nor dormancy is considered: a suspended holder keeps the seat. |
| `degree(n)` | The row of degree `n` in the degree table whose digest is `pins["canon/degrees.toml"]` (section 8.4). |
| `name_holders(x, now)` | The list of pairs `(role, spelling)` holding the name `x` up to case, in this order: `("member", l)` for every key `l` of `members` with `fold(l) = fold(x)`, whatever the status; `("witness", w)` likewise for `witnesses`; `("custodian", c)` likewise for `custodians`, live or not; `("invitation", l)` for every **live** invitation; `("petition", l)` for every **reserved** petition; `("ballot", name)` for every open ballot of kind `witness` whose subject has `action = add` and a `name` with the same folding; `("claim", name)` for the alive claim of the Custodian office, if its `name` has the same folding. |
| `key_holders(key, now)` | The list of pairs `(role, name)` holding the public key `key`, in the same order: members of any status whose `key` is the same key (section 2.6: equal points, whatever the two types); witnesses; custodians, live or not, whose custodian key **or** revoke key is the same key (`("custodian", name)`); reserved petitions; open witness ballots with `action = add` and the same key; `("recovery", login)` for every recovery **alive** at `now` whose new key is the same key (section 4.10); and `("claim", name)` for the alive claim whose custodian key or revoke key is the same key. An invitation names no key and is never in this list. For a `key` that is not a valid key the list is empty. `key` is validated once; the keys the state holds are decoded and compared, never validated again (section 2.6). |
| `id_holders(id, now)` | The list of pairs `(role, login)` holding the GitHub account with the numeric id `id`, in this order: `("member", l)` for every record of `members` whose `github_id` equals it, whatever the status (the founders among them); `("invitation", l)` for every **live** invitation with that `github_id`; `("petition", l)` for every **reserved** petition with that `github_id`. Witnesses have no account and are never in this list. |
| `invited(x, now)` | Section 4.3: `x` has a live invitation under exactly that spelling. |
| `key_owner(key, now)` | The name of the first pair of `key_holders(key, now)`; none if the list is empty. |
| `login_taken(x)` | The first key of `members`, then of `witnesses`, then of `custodians`, that is the same login as `x`; none if there is none. Used by the tools, not by a rule. |
| `custodian_end(c)` | Section 4.8: the first second at which the custodian key is not live. |
| `custodian_status(c, now)` | Section 4.8: `live`, `lapsed`, `revoked` or `removed`. |
| `custodians_live(now)` | The names of the custodians whose key is live at `now`, ascending. Read by N6a, CL2 and CA4. |
| `span(c)`, `in_force(c, now)`, `correction_status(c, now)` | Section 4.9 and section 7.8: the interval of an immediate act, whether it holds `now`, and the word for its condition. |
| `void_span(c)` | Section 4.9 and section 7.8: the interval on which a `void_ballot` is pending, and so pauses its ballot. |
| `notice_end(c)`, `apply_end(c)`, `noticed_status(c, now)`, `pending(c, now)`, `live_signers(c, now)` | Section 4.9 and section 6.19.9: the two bounds of the time in which a noticed act may be applied, the word for where it stands, whether it can still be applied, and its signers whose key is live. |
| `void_pending(ballot, now)` | The correction with `act = void_ballot` and `target.id = ballot` that is pending at `now`; none if there is none. At most one is pending at a time (VB3). |
| `recovery_start(r, now)`, `recovery_notice_days(r, now)`, `recovery_notice_end(r, now)`, `recovery_end(r, now)`, `recovery_status(r, now)`, `recovery_alive(login, now)`, `recovering(login, now)` | Section 4.10: where the notice of a recovery starts, the first and the last second at which it may be applied, the word for where it stands, and the recovery of `login` that is alive, or under way, at `now`, if any. |
| `frozen_keys(now)` | The set of logins whose key is frozen at `now`: the `target.login` of every `freeze_key` in force, and every login with a recovery under way. Read by FK4. |
| `key_frozen(login, now)` | `frozen(login, now)` is not none, **or** `recovering(login, now)` is not none: the key the ledger holds for the member signs only what a frozen member may sign (section 6.19.1). |
| `acting(act, now, fields)` | The corrections with that `act`, whose `target` has the given fields with the given values, that are in force at `now`; in the order of `S.corrections`. |
| `frozen(login, now)` | The first of `acting("freeze_key", now, login)`; none if there is none. At most one exists (FK3). It looks at freezes alone: a key held by a recovery after its freeze ran out is not `frozen`, it is `key_frozen`. |
| `witness_frozen(name, now)` | The first of `acting("freeze_witness", now, name)`; none if there is none. |
| `stayed(ballot, now)` | The first of `acting("stay", now, ballot)`; none if there is none. At most one exists (SY3). |
| `open_sanction_on(login)` | The first open ballot of kind `sanction` whose subject has `member = login` (exact), whatever its measure; none if there is none. Read by AP6a. |
| `open_by(login, kind)` | The number of open ballots whose `opened_by` is `login` and that share the count of a ballot of `kind`: for `amendment`, the open amendment ballots; for any kind but `custodian`, the open ballots of the kinds other than `amendment` and `custodian`. A ballot of kind `custodian` is in no count. Read by B7b. |
| `halted(now)` | The first of `acting("halt", now)`; none if there is none. At most one exists (HT1). |
| `room_hold(login, now)` | The first of `acting("hold_room", now, login)`; none if there is none. |
| `pauses(ballot)`, `paused(start, now, ballot)`, `effective(start, now, ballot)`, `due(start, span, ballot)`, `ballot_time(b, now)`, `ballot_due(b, deadline)` | Section 7.8: the effective clock. |
| `open_ballot_on(kind, key)` | Section 4.4. |

**One name, one key, one account, one role.** The rules of sections 6.1, 6.2, 6.4.1, 6.4.5, 6.17, 6.18 and 6.31 keep this invariant: at any time, a name (up to case) has at most one holder among members of any status, witnesses, custodians (live or not), live invitations, reserved petitions, the subjects of open ballots that add a witness and the alive claim; a public key (a point, under either key type) has at most one holder among the same and the recoveries that are alive, invitations aside, a custodian and a claim each holding two keys (a custodian key and a revoke key); and a GitHub account (a `github_id`) has at most one holder among members of any status, live invitations and reserved petitions. The single exception is a returning login: its own earlier record, departed, expelled or voided, holds the same name as its own new invitation and then its own new petition, may hold the same account as both, and may hold the same key as that petition. So one GitHub account is at most one member: the same account under another login is refused, whatever the status of the record that holds it.

### 4.8 `Custodian`

`S.custodians[name]` is a record created by the genesis (section 6.1), or by the application of a founder's claim (section 6.33), and never removed. **Custodians exist only as the genesis or a founder's claim named them.** No other entry, no ballot and no lot creates a custodian, and nothing gives one a new key: once the keys of all of them have lapsed or been removed, no correction exists on that ledger until a founder's claim is applied, and none at all after the Sunset, or once three active Master Builders who are not founders exist, until an amendment says otherwise.

| Field | Type | Stored / derived | Meaning |
|---|---|---|---|
| `name` | string | stored | The custodian's name: the `actor` of its entries. A login by its grammar, and never a member login or a witness name (section 4.7). |
| `key` | string | stored | The custodian key. It signs the five `CUSTODIAN_TYPES`: `correction`, `correction_cosign`, `correction_apply`, `correction_withdraw` and `custodian_alive`. It never changes. |
| `revoke_key` | string | stored | The revoke key. It signs one type, `custodian_revoke`. It never changes. |
| `member` | login | stored | The login of the member account of the person who holds the two keys: a founder (of the genesis, or the founder whose claim named it). Read for recusal (HR2, SY4, VB4, UB8), for objections (J4, J4a) and by the ballot that removes the custodian (section 6.4.6). |
| `alive` | time | stored | The last sign of life: the time of the genesis (or of the claim's application), then of each `custodian_alive`. |
| `genesis` | boolean | stored | True for a custodian the genesis named; false for one a founder's claim named. |
| `revoked` | time or null | stored | When the key was removed: by a `custodian_revoke` (section 6.23), or by the close of a passed ballot of kind `custodian` (section 6.4.6). Set once. |
| `removed` | string | stored | The id of that ballot, when a ballot removed the key; empty otherwise. |
| `since` | time | stored | The time of the genesis that named the custodian, or of the application of the claim that named it: where its term starts. It never changes. |
| `claim` | integer or null | stored | The `seq` of the `custodian_claim` that named it; null for a custodian of the genesis. |
| `bounded` | boolean | derived | `genesis` is true or `claim` is not null: bound by the Sunset and the term. Every record is bounded. |
| `custodian_end(c)` | time | derived | The first second at which the key is not live: the earliest of `alive + 180 d + 1 s`; `revoked`, when set; and, when `bounded`, `S.sunset`, when set, and `since + 2,555 d + 1 s` (the end of the term, `CUSTODIAN_TERM_DAYS`). |
| `custodian_status(c, now)` | string | derived | `live` when `now < custodian_end(c)`; otherwise `lapsed` when `revoked` is null, `removed` when `removed` is not empty, else `revoked`. |

The key of a custodian is **live** at `now` exactly when `now < custodian_end(c)`. For the silence rule this is `not expired(alive, now, 180)`: the key signs through the last second of the 180 days and lapses in the next one; for the term it is `not expired(since, now, 2555)`, in the same way. A key that is not live signs nothing, and nothing makes it live again: `alive` moves only by an entry the live key signs, `revoked` is set only while the key is live, `since` never moves, and `revoked` and `S.sunset` are set once and never cleared. So a key that lapsed, was revoked or was removed never signs again. **A lapse is not an entry.** It is a consequence of the stored facts and of the time asked about, so it is the same whenever it is computed.

### 4.9 `Correction`

`S.corrections[seq]` is the record of one accepted `correction` entry (section 6.19) whose act is not `note`, under the `seq` of that entry. Records are never removed. A `note` leaves a Note in `S.notes` (section 4.6) and no record here: it cannot be objected to, withdrawn, co-signed or applied, because those entries find no correction under its `seq`.

| Field | Type | Stored / derived | Meaning |
|---|---|---|---|
| `seq` | integer | stored | The `seq` of the `correction` entry: the correction's id. |
| `by` | string | stored | The custodian who signed it. |
| `act` | string | stored | The act. |
| `target` | object | stored | A copy of `body.target`. |
| `ground` | string | stored | One of `GROUNDS`. |
| `reason_sha256` | hex string | stored | The digest of the public reason. |
| `time` | time | stored | The time of the entry. |
| `class` | `immediate` or `noticed` | stored | `ledger.Correction.class_`. An immediate act is in force from `time`. A noticed act (`void_ballot`, `undo_ballot`) is never "in force": it is pending, and has its effect once, when it is applied. |
| `until` | time or null | stored | For an immediate act, `time + D d`, with `D` the days of the act: where it lapses by itself. Null for a noticed act. Never rewritten. |
| `subject` | login or `""` | stored | The member the act is aimed at, if any: `target.login` for `freeze_key` and `hold_room`; the `member` of the ballot's subject for `stay` and `void_ballot`; the `member` or, for an admission, the `candidate` of the ballot's subject for `undo_ballot`. Read by J5. |
| `objections` | tuple of login | stored | The Masters who objected, in order. |
| `void` | time or null | stored | When its objections reached the number that voids it. Set once. |
| `withdrawals` | tuple of string | stored | The custodians who signed its withdrawal, in order (section 6.20). |
| `withdrawn` | time or null | stored | When it was withdrawn: by the custodian who posted it, or by enough other custodians. Set once. |
| `withdrawn_by` | string | stored | The custodian whose signature withdrew it; empty until then. An act is **overruled** (`ledger._overruled`) when `withdrawn` is set and `withdrawn_by ≠ by`: custodians other than its poster withdrew it. Read by FK3, HR4, VB3 and UB7. |
| `signers` | tuple of string | stored | For a noticed act: the custodian who posted it, then each custodian who co-signed it (section 6.24), in order. Empty for every other class. |
| `applied` | time or null | stored | For a noticed act: the time of the `correction_apply` that gave it its effect (section 6.25). Set once. |
| `applied_by` | string | stored | The custodian who signed that entry; empty until then. |
| `released` | time or null | stored | For a `freeze_key`: the time at which the recovery of the frozen key was applied while the freeze was in force (section 6.29). Set once. |
| `span(c)` | interval | derived | For an immediate act: `[time, max(time, end))`, with `end` the earliest of `until`, `withdrawn` when set, `void` when set, `released` when set, and `custodian_end(S.custodians[by])`. |
| `in_force(c, now)` | boolean | derived | False for a noticed act. Otherwise `time ≤ now < end`. |
| `notice_end(c)` | time | derived | For a noticed act: `time + 14 d`, the first second at which it may be applied. |
| `apply_end(c)` | time | derived | For a noticed act: `time + 21 d`, the last second at which it may be applied. |
| `void_span(c)` | interval | derived | For a `void_ballot`: `[time, max(time, end))`, with `end` the earliest of `applied`, `void` and `withdrawn`, each when set, and of `custodian_end(S.custodians[by])` when that is at most `apply_end`, else `apply_end + 1 s`. It holds exactly the times at which `pending(c, now)` is true. |
| `noticed_status(c, now)` | string | derived | For a noticed act, the first that holds: `applied` when `applied ≤ now`; `void` when `void ≤ now`; `withdrawn` when `withdrawn ≤ now`; `ended` when `custodian_end(S.custodians[by]) ≤ min(now, apply_end)`; `expired` when `now > apply_end`; `ready` when `now ≥ notice_end`; otherwise `pending`. Read by CS3, AP3, CW2 and X1b. |
| `pending(c, now)` | boolean | derived | `class = noticed` and `noticed_status(c, now)` is `pending` or `ready`: the act can still be applied. |
| `live_signers(c, now)` | list of string | derived | The names in `signers` whose custodian key is live at `now`. |
| `correction_status(c, now)` | string | derived, informational | For a noticed act, `noticed_status(c, now)`. For an immediate act: `active` while `now < end`; then `void` when `void ≤ now`; then `withdrawn` when `withdrawn ≤ now`; then `released` when `released ≤ now`; then `lapsed` when `end = until`; otherwise `ended` (the key of its custodian lapsed or was removed first). |

Only `objections`, `void`, `withdrawals`, `withdrawn`, `withdrawn_by`, `signers`, `applied`, `applied_by` and `released` ever change after the record is created, each by an entry (sections 6.20, 6.21, 6.24, 6.25 and 6.29). The end of an immediate act is never stored: it is computed from those facts and from the record of its custodian (section 7.8). Neither is the condition of a noticed act: section 6.19.9.

### 4.10 `Recovery`

`S.recoveries[login]` is the record of the latest accepted `rekey_recover` entry of `login` (section 6.26). A later request of the same login replaces it; nothing else removes it.

A recovery is of one of two kinds, told by `freeze`. A recovery **after a freeze** was asked while a `freeze_key` of the login was in force. An **open** recovery was asked without one: no custodian key was live, or no custodian froze the key (a recovery never needs a custodian). It has no freeze to follow, its notice starts when the co-signatures it needs are there, and the Master Builders may oppose it (section 6.30). Either kind may be **final**: it follows a recovery of the same membership that the old key stopped, and the old key does not stop it. Either kind is **lowered** at `now` (`ledger.lowered`) when it needs fewer co-signers than its nominal number because fewer other Master Builders exist (section 6.27), and **dropped** when, 30 days after the request, the co-signatures given by then (counted as at least one where another Master Builder exists) are fewer than it needs, and, for an open recovery, its notice had not begun by then (section 6.26); its notice is then the longer one.

| Field | Type | Stored / derived | Meaning |
|---|---|---|---|
| `login` | login | stored | The member whose key is being recovered. |
| `key` | string | stored | The new key: it signed the request and signs its application. |
| `seq` | integer | stored | The `seq` of the `rekey_recover` entry. |
| `time` | time | stored | The time of that entry. |
| `freeze` | integer or null | stored | The `seq` of the `freeze_key` correction that was in force on the login at that entry; null for an open recovery. |
| `admitted` | string | stored | The membership of the login at that entry (section 4.2): the recovery is of that membership and of no later one. |
| `cosigners` | tuple of login | stored | The Master Builders who co-signed, in order (section 6.27). |
| `objected` | time or null | stored | When the key the ledger held stopped it (section 6.28). Set once. |
| `applied` | time or null | stored | When the new key took the member's place (section 6.29). Set once. |
| `notice` | time or null | stored | For an open recovery: the time of the entry at which the co-signatures it needs were complete, which is where its notice starts (the request itself, where it needs none). Null until then, and always null for a recovery after a freeze. Set once. A notice that starts at the drop moment is not stored here (`recovery_start`). |
| `final` | boolean | stored | True when, at the request, the record it replaced was of the same membership and had `objected` set. |
| `opposed` | tuple of login | stored | For an open recovery: the Master Builders who opposed it, in order (section 6.30). |
| `void` | time or null | stored | When their number voided it. Set once. |
| `dropped` | integer or null | stored | The number of co-signatures the request had at its drop moment (`drop_time`), recorded by the first `rekey_cosign` at or after that moment (section 6.27). Null until then. Set once. |
| `departure` | time or null | stored | The departure this recovery was asked in time for (the `status_since` of the departed record): set at the request when the record is `departed` (RR3a), or by a `depart` of the member while this is the latest recovery of the membership and it is in time for it (section 6.15, effect 0). Null otherwise. Read by RR3a (`follows`). |
| `drop_time()` | time | derived | `time + 30 d` (`RECOVER_DROP_DAYS`). |
| `given_at_drop()` | integer | derived | `dropped`, or `len(cosigners)` while `dropped` is null: the co-signatures given by the drop moment. |
| `dropped(S, r, now)` | boolean | derived | `now ≥ drop_time()`, `max(given_at_drop(), 1 if m > 0 else 0) < min(nominal, m)` (the drop lowers what it needs), and, for an open recovery, `notice` is null or later than `drop_time()`; after a freeze that guard alone decides (section 6.26). |
| `recovery_start(r, now)` | time or null | derived | Where the notice starts, as things stand at `now` (default `S.time`): when `dropped`, `drop_time()` after a freeze, and for an open recovery `drop_time()` if the first `given_at_drop()` co-signatures are `cosigned` at `now` (section 6.27), else `notice`; otherwise `time` for a recovery after a freeze and `notice` for an open one. |
| `recovery_notice_days(r, now)` | integer | derived | 45 (`RECOVER_LOWERED_NOTICE_DAYS`) when the recovery is lowered or dropped at `now`; otherwise 21 after a freeze and 30 for an open recovery. `now` defaults to `S.time`. |
| `recovery_notice_end(r, now)` | time or null | derived | The first second at which the recovery may be applied, as things stand at `now`: `recovery_start + recovery_notice_days(r, now) d`; null while `recovery_start` is null. |
| `recovery_end(r, now)` | time | derived | The last second at which the recovery is alive, as things stand at `now`: `recovery_start(r, now) + 60 d`, or `time + 60 d` while it is null. |
| `recovery_status(r, now)` | string | derived | The first that holds: `applied` when `applied ≤ now`; `objected` when `objected ≤ now`; `opposed` when `void ≤ now`; `canceled` when the record of `S.members[login]` has another membership than `admitted` and that membership began at or before `now` (the login was admitted anew), or when the correction `S.corrections[freeze]` has a `void` or a `withdrawn` that is at most `min(now, recovery_end)`; `expired` when `now > recovery_end`; `requested` when `recovery_start` is null; `ready` when `now ≥ recovery_notice_end(r, now)` and `cosigned(S, r, r.cosigners, now)` (section 6.27): a recovery that cannot be applied, such as one after a freeze still short of its co-signatures, is never shown `ready`; otherwise `pending`. |
| `recovery_alive(login, now)` | Recovery or none | derived | The record of `login`, when its status at `now` is `requested`, `pending` or `ready`: the recovery is **alive**. |
| `recovering(login, now)` | Recovery or none | derived | The record of `login`, when its status at `now` is `pending` or `ready`: the recovery is **under way**. |

While a recovery is **alive** its new key is held (section 4.7), and it takes co-signatures, the objection of the old key and oppositions. While it is **under way**, that is from the start of its notice on, the key the ledger holds for the member is `key_frozen` (also after a freeze has run its 30 days), and the login counts among the frozen keys of FK4. An open recovery that is only `requested` freezes nothing: the key the ledger holds signs as before. A recovery that is `objected`, `opposed`, `canceled`, `expired` or `applied` holds nothing. Its condition is computed, never stored: no entry marks a recovery as canceled or expired.

### 4.11 The state document and the state digest

`State.document()` is the **state document**: one small JSON value in the sense of section 2.2 that commits to every stored fact of a state and to nothing else. `State.digest()` is the **state digest**: `H(canonical(document))`, 64 lowercase hexadecimal characters. Two states have the same digest exactly when their stored facts are equal (short of a collision of SHA-256). A `witness` entry states the digest of the state it covers and replay refuses a wrong one (section 6.16, Z5); `verify --json` prints the digest of the state it reached (section 9.1); the vectors of section 14 state it for small ledgers.

The document does not hold the records: it holds the **root of each section** and the **accumulator of each history**, so its size is fixed, and a verifier that keeps the leaves of the records it hashed before hashes again only the records an entry changed.

**What it commits to.** Every field marked "stored" in sections 4.1 to 4.10, each in exactly one place: a **section**, a **scalar** or a **history**. Three fields of `State` are left out, each because the document commits to it otherwise: `S.hashes` (`head` and `seq` commit to it: each entry holds the hash of the entry before it, C7, so two states with the same `head` have the same list), and the two **indexes of the history**, `S.retired` and `S.degree_tables`, which are functions of the records the histories `ballots` and `amendments` absorbed. **Nothing derived is in it:** no `standing`, `dormant` or `light`, no status of a correction, of a custodian key or of a recovery, no `live`, `reserved` or `in_force`, no deadline as it stands. The document is a function of the entries alone; the time at which it is computed, and the questions asked of the state before, change nothing in it.

**The encoding, version 2.** `ledger.STATE_VERSION` = 2.

```
document     = {"v": 2, "scalars": {…}, "sections": {name: root, …}, "history": {name: {"count": n, "acc": acc}, …}}
state_sha256 = H(canonical(document))
leaf(k, r)   = SHA-256(canonical([k, r]))                     32 bytes: the leaf of the record r under the key k
root         = merkle_root(the leaves of the section, in ascending order of key)     section 2.4, RFC 6962
acc'         = SHA-256(acc || leaf)                           32-byte strings, concatenated; acc₀ = 32 zero bytes
```

**Values.** Every record and scalar is written with the same rules:

1. A **record** is a JSON object with one member per stored field, under the field's name in this document. The records are Member, Ballot, Exam, Custodian, Correction, Recovery, Claim and Succession, an invitation and a petition (section 4.3), an Amendment, a Checkpoint, a Beacon and a Note (section 4.6), a witness mark (section 4.1), and the objects a record holds as they were built from entries: `subject`, `frozen` and `undo` of a Ballot, `target` of a Correction, `left` of a Member.
2. A **map inside a record** (a value whose keys are data: the `since` of a Member, the `commits` and `reveals` of a Ballot, the `reports` of an Exam) is an array of two-element arrays `[key, value]`, in ascending order of key.
3. A **set** is an array of its elements in ascending order; a **tuple** or a **list** is an array in its own order.
4. A **time** is a string in the one text form of section 2.5.
5. A field whose value is **null is left out**. No `null` occurs. Every other field is present, also when its value is empty: `""`, `0`, `false`, `[]` are written.
6. A boolean is `true` or `false`, and every number is an integer. No floating-point value occurs.
7. **Keys are ordered** by code point for strings (they are ASCII, so by byte: `Zed` comes before `ada`), by value for integers, and the key `(login, degree)` of `S.exams` by login and then by degree; it is written as the array `[login, degree]`.

**Sections.** A section is a keyed collection of the state. Its **leaves** are `leaf(k, r)` for each key `k` and record `r`, in ascending order of key, and its **root** is the Merkle root of section 2.4 over those 32-byte leaves (RFC 6962: a leaf `x` enters the tree as `H(0x00 || x)`, two nodes as `H(0x01 || left || right)`, and the empty section has the root `H("")` = `e3b0c442…b855`). The seventeen sections, all present in `sections`:

| Section | Key | Record |
|---|---|---|
| `members` | login | Member: `login`, `key`, `degree`, `since` (a map degree → time), `sponsors`, `status`, `activity`, `seat_until`, `past_seats`, `status_since`, `suspended_until`, `sponsor_ban_until`, `founder`, `last_work`, `fraud_history`, `github_id`, `last_rekey`, `left`, `missed`, `heard` |
| `witnesses` | name | the key, a string |
| `custodians` | name | Custodian: `name`, `key`, `revoke_key`, `member`, `alive`, `genesis`, `revoked`, `removed`, `since`, `claim` |
| `corrections` | `seq` | Correction: `seq`, `by`, `act`, `target`, `ground`, `reason_sha256`, `time`, `class`, `until`, `subject`, `objections`, `void`, `withdrawals`, `withdrawn`, `withdrawn_by`, `signers`, `applied`, `applied_by`, `released` |
| `recoveries` | login | Recovery: `login`, `key`, `seq`, `time`, `freeze`, `admitted`, `cosigners`, `objected`, `applied`, `notice`, `final`, `opposed`, `void`, `dropped`, `departure` |
| `claims` | `seq` | Claim: `seq`, `founder`, `name`, `key`, `revoke_key`, `time`, `objected`, `objector`, `applied` |
| `invitations` | login | `{by, github_id, time}` |
| `petitions` | login | `{key, vouches, time, github_id}`, `vouches` in its order |
| `ballots` | id | Ballot: `id`, `kind`, `subject`, `electors` (a set), `commit_until`, `reveal_until`, `opened_by`, `commits` and `reveals` (maps login → value), `result`, `frozen`, `opened`, `closed`, `undo`, `corrected`, `base`, `rerun` |
| `exams` | `[login, degree]` | Exam: `candidate`, `degree`, `examiners`, `beacon_round`, `opened`, `reports` (a map login → verdict), `pool`, `work_ref`, `ranking`, `recused`, `k`, `consumed`, `ballot_failed`, `lapsed`, `skipped` |
| `notes` | `seq` | Note: `{seq, by, action, target, rule, reason_sha256, time}` (the newest 200; the list's order is the order of `seq`) |
| `pins`, `prior_pins` | path | the hex string |
| `prior_until` | path | the time |
| `day_entries` | actor | the integer |
| `witness_marks` | name | `{acts, time}` |
| `known_keys` | the point (hex) | `true`: a set is a section whose every record is `true` |

**Scalars.** `scalars` is an object with these members, written by the rules above: `name`, `head`, `declaration_sha256` and `day` (strings), `seq`, `custodian_threshold`, `acts` and `epoch` (integers), `time` and `sunset` (times, left out while null), `council_call` (an integer, left out while null), `council_pool` (an array of logins, in its order) and `succession` (a Succession record: `seq`, `by`, `time`, `end`, `canceled_by`; left out while null).

**Histories.** A history holds what left the state for good, or never entered it, because no rule reads it (section 4.1, `S.history`). It is written `{"count": n, "acc": acc}`: how many records it absorbed, and the hash chain of their leaves, starting from `acc₀` (64 zeros). Absorbing a record with leaf `x` sets `acc' = SHA-256(acc || x)` and `n' = n + 1`. The five histories, all present in `history`, and the leaf each absorbs:

| History | When a record enters it | Its leaf |
|---|---|---|
| `amendments` | the close of a passed amendment ballot (section 6.4.3): the Amendment `{ballot, path, new_sha256, time}` | `SHA-256(canonical(record))` |
| `ballots` | a ballot that ended more than `BALLOT_RETIRE_DAYS` = 111 days before the entry being applied (C14r), in ascending order of `(end, id)` | `leaf(id, ballot)`: the leaf it had in the section `ballots` |
| `beacons` | each `exam_draw` and `council_draw`: the Beacon `{round, beacon}` | `SHA-256(canonical(record))` |
| `checkpoints` | each `witness` entry, after Z5: the Checkpoint `{witness, upto_seq, head, state_sha256, state_version, root, anchor}`, `root` and `anchor` left out when the body has none | `SHA-256(canonical(record))` |
| `notes` | a note that the 201st newer note pushes out of `S.notes` (section 6.19.6), oldest first | `leaf(seq, note)`: the leaf it had in the section `notes` |

A record a history absorbed is not kept: the entries hold everything it said, and a tool that wants one reads it there (`verify.lot_beacons` reads the beacons for the online audit, section 9.4; `om state` reads the checkpoints). Its id stays known where a rule needs it: `S.retired` holds the id of every retired ballot (B3, B2r, UB0), and `S.degree_tables` the new text of every passed amendment of `canon/degrees.toml` (the tree gate, section 8.5).

**What no rule reads, and why the ballots can go.** A ballot is read after it ended (by its close, or by the application of the `void_ballot` that voided it) only by: the undo of a passed admission or advancement (section 6.19.8), posted within `UNDO_WINDOW_DAYS` = 90 days of the close (UB6) and applied, co-signed or checked again within `NOTICE_DAYS + APPLY_WINDOW_DAYS` = 21 days of its posting (section 6.19.9), all in wall time; the re-run of a lapsed ballot, opened within `RERUN_DAYS` = 30 days of its close (B2a to B2e: the re-run that B2d looks for was opened in that window, so it ended later, and is kept at least as long); and the opener's wait of B7a, `REOPEN_AFTER_DAYS` = 90 days from the close. Every other rule reads open ballots only (`open_ballot_on`, `open_sanction_on`, `open_by`, the windows, the holders of names and keys, stays and voids, `party_to` while a correction is posted or pending), and the uniqueness of an id reads `S.retired` too. So a ballot that ended more than `BALLOT_RETIRE_DAYS` = 90 + 14 + 7 = 111 days ago is read by no rule, and C14r removes it at the first entry dated later. Retirement changes no outcome (section 10, invariant 59): a correction or a re-run that names a retired ballot is refused, as it was before, with a message that says so (UB0, B2r). The checkpoints, the beacons and the amendments were never read by any rule; the notes beyond the newest 200 never were either (the rule of ten notes a day reads that day's notes only).

**The digest a verifier keeps.** The document is the same however it is computed. The reference (`State.digest`) remembers, for each section, the leaf of every record as it last hashed it, and hashes again only a record that changed: a record of a class of section 4 carries a version that every assignment to one of its fields renews (`ledger._Record`), and a rule that changes a list or a map of a record in place renews it by `touch()`; a plain map (an invitation, a petition, a witness mark, a note) is compared by value, and a string, an integer or a time by value. Only a section in which something changed has its root computed again. The memory is not a fact: a copy of the state does not inherit it, and `ledger.state_digest(S)` computes the same digest from nothing, which the tests compare after every entry of every vector and of the random runs. Over a ledger, the cost of the checkpoints is that of the records that changed between them and of the roots of the sections they changed, never that of the whole history.

**Examples.** The document of the empty state, in canonical JSON (the seventeen roots are the root of an empty section, the five accumulators 64 zeros), and its digest:

```
{"history":{"amendments":{"acc":"0000…0000","count":0},"ballots":{"acc":"0000…0000","count":0},"beacons":{"acc":"0000…0000","count":0},"checkpoints":{"acc":"0000…0000","count":0},"notes":{"acc":"0000…0000","count":0}},"scalars":{"acts":0,"council_pool":[],"custodian_threshold":0,"day":"","declaration_sha256":"","epoch":0,"head":"0000000000000000000000000000000000000000000000000000000000000000","name":"","seq":-1},"sections":{"ballots":"e3b0c442…b855","claims":"e3b0c442…b855",…,"witnesses":"e3b0c442…b855"},"v":2}

abfb86b1c6152bcc676a96ac0ee9a378050879d467f7800ea3ac820e87b19ac9
```

(`0000…0000` stands for 64 zeros and `e3b0c442…b855` for `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`, written out in full in the document; `sections` lists all seventeen names in ascending order.)

A worked example: the state of the vector `valid-admission-passes` (section 14), after alice's admission. The record of alice in the section `members`, as `[key, record]`: eight of its fields are null and left out, and four that are empty (`0`, `false`, `[]`) are written.

```
["alice",{"activity":["2027-01-11T09:15:01Z"],"degree":1,"founder":false,"fraud_history":[],"github_id":735577802,"key":"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICCwBPYGKomu0O2QutwjOXL/sws4wTOL+Zu0VhacS96Q","login":"alice","missed":[],"past_seats":0,"since":[[1,"2027-01-11T09:15:01Z"]],"sponsors":["hiram","ada"],"status":"active"}]
```

Its leaf is `a04423e1fc69506440aae797348e02a1c8ab6e15dd6eed86e96ad026358aaaa8`. The section holds four records, in the order `ada`, `alice`, `carol`, `hiram`, with the leaves `3e3ee637…7f7e`, `a04423e1…aaa8`, `8bde328d…64be` and `791502ce…2158`; with `L(x) = H(0x00 || x)` and `N(a, b) = H(0x01 || a || b)` its root is `N(N(L(ada), L(alice)), N(L(carol), L(hiram)))` = `08b7138e0827a872ebc51ef8eb461ee55a8dc87576f259c7bd4ade311da49c45`. The section `witnesses` holds one record, `["tyler","ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINItFUo6KrHoH1PqeHSuVS2I9nwEa6OTqynk9bZ78yYX"]`, whose leaf is `5ed4eb03…39a4`, and its root is `L(leaf)` = `1129700b363c0a60c0de345f79bc1d6a31be607cbb4dbbbb6ff8e897c05cf22e`. The scalars are

```
{"acts":12,"council_pool":[],"custodian_threshold":0,"day":"2027-01-11","declaration_sha256":"41c3d420815ec46fc92dfaa7b09c0cc64475e3243802bf819ffde8d9dd4b73fb","epoch":0,"head":"6e6295447322bb362b84bf1eae7132661e66c5a92f44c212239b4d6165421266","name":"OpenMasonry Vector Lodge","seq":11,"time":"2027-01-11T09:15:01Z"}
```

the five histories are empty, and the digest of the whole document, 2,179 bytes in canonical JSON, is `63ff1f5be2341c8e36e826116f783de79dfba6b6110756911da95b9ac993b9be`, the `state_sha256` the vector expects.

**What follows from the rules.** The digest does not depend on the order in which a map or a set was filled, on the runtime's hashing of strings or on the identity of an object, on a clock or on the path by which the state was reached: replaying a ledger in one pass, continuing from the state of a prefix, and reading the entries from files or from memory give the same digest (section 10, invariant 52). It changes when any single stored fact changes. A second implementation needs no cache to be conforming: hashing every leaf at every checkpoint gives the same digest, only more slowly.

**Versions.** `v` names these rules together with the list of sections, scalars and histories and the fields of their records. A change of any of them that changes the document of a state some ledger can reach changes which checkpoints replay accepts: it is a change of the protocol (an amendment of `@protocol`), and it takes a new `v` (section 12, point 46). The design is meant to last: a new stored field goes into the record that holds it or into a new section, and a new kind of record no rule reads after a while into a new history, without changing how the others are written.

---

## 5. Common checks applied to every entry

### 5.1 The order of `apply`

`ledger.apply(S, e)` performs these checks in this order. The first that fails refuses the entry with the quoted message. `next` is `S.seq + 1`.

| # | Check | Refusal message (reported at) |
|---|---|---|
| C1 | `e` is an object whose set of members is exactly `ENVELOPE`. | `an entry has exactly the fields seq, prev, time, type, actor, body, sig` (at `next`) |
| C2 | `e` is a value in the sense of section 2.2: no float, no `null`, integers in range, ASCII strings, at most 6 levels. | `not strict JSON: {error}` (at `next`) |
| C3 | `seq` is an integer (a boolean is refused) and `seq = next`. | `expected seq {next}` (at `next`) |
| C4 | `body` is an object, `type` is a string and `sig` is a string. Then: the canonical encoding of `e` is at most 32,768 bytes if `seq = 0`, else 8,192 bytes. | `malformed entry`; `entry exceeds {limit} bytes` |
| C5 | `actor` is a string matching `LOGIN_RE`. | `actor must be a valid GitHub login` |
| C6 | `time` is a valid time (section 2.5). | the two messages of section 2.5 |
| C7 | `prev = S.head`. | `prev does not match head (history was altered)` |
| C8 | `S.time` is null, or `now ≥ S.time`, with `now` the entry's time. | `time goes backwards` |
| C9 | `type = "genesis"` exactly when `seq = 0`. Then: `type` is one of the thirty-four types of section 6. | `entry 0 is the genesis, and only entry 0`; `unknown entry type {type!r}` |
| C10 | `body` has the exact shape of its type (below). | `malformed {type} entry: …` |
| C11 | The signer key is resolved (section 5.2). | the messages of section 5.2 |
| C12 | `sig_ok(signed payload, sig, actor, signer key)`. | `bad signature` |
| C12a | The entry is **exempt** (`ledger.daily_exempt`: `type` is in `DAILY_EXEMPT`, or `type = "ballot_open"` and `body.kind` is in `UNSTOPPABLE_KINDS`), **or** fewer than `ENTRIES_PER_DAY` = 20 entries of `actor` are counted for the UTC calendar day of the entry (section 5.4): with `day` the first ten characters of `time`, the count is `S.day_entries[actor]` when `S.day = day` and the map has the actor, else 0. | `{actor} already has 20 entries dated {day} (at most 20 entries per actor per UTC day; a vote, a close, a lot, a departure, a key replacement or recovery, an objection, the entries of an amendment ballot or of the ballot that removes a custodian, and custodian_revoke are not counted)` |
| C13 | The type's preconditions hold (section 6). | the messages of section 6 |

If C1 to C13 pass, the type's effects are applied, then:

- **C14, activity.** Section 5.3.
- **C14b, succession.** If `S.succession` is not null and its `end` is null: when its status at `now` is `pending`, the signer key was resolved through `S.members` (section 5.2), that record is still the record of `actor`, holds the 3rd degree or higher, `is_active(now)`, and is neither `dormant(now)` nor `silent(now)` after the effects, `end = now` and `canceled_by = actor` (a Master Builder showed themselves); otherwise, when `len(present_masters(now)) ≥ 3` (`SUCCESSION_MASTERS`), `end = now` (section 6.34). A departure therefore cancels nothing: after it the record is not active; nor does an entry of a silent Master that is no revealed vote and no report.
- **C14a, the counts of the day.** If `S.day` is not the day of the entry: `S.day` becomes that day and `S.day_entries` becomes empty. Then, unless the entry is exempt (C12a): `S.day_entries[actor]` becomes the count of C12a plus 1. Then, unless `type = "witness"`: `S.acts` grows by 1.
- **C14s, Sunset.** If `S.sunset` is null and the Sunset condition holds on the state as it now stands, at `now` (section 7.9): `S.sunset = now`.
- **C14r, retirement.** Every ballot `b` of `S.ballots` whose **end** (`ledger.ballot_end`: `b.closed`, or for a voided ballot the `applied` time of the correction `b.corrected`) satisfies `expired(end, now, BALLOT_RETIRE_DAYS)` (111 days, wall time) leaves the state, in ascending order of `(end, id)`: its leaf (section 4.11) is absorbed by the history `ballots`, its id is added to `S.retired`, and it is removed from `S.ballots`. An open ballot never retires. Section 4.11 shows that no rule reads a ballot that ended more than 111 days before the entry it judges.
- **C15, chain.** `entry_hash(e)` is appended to `S.hashes`; `S.head` becomes that hash; `S.seq` becomes `seq`; `S.time` becomes `now`.

**Exact bodies (C10).** Every entry type has an exact set of body fields, each with one JSON type, some of them optional (`ledger.BODY_FIELDS`; the tables of section 6). The check is `ledger._shape`, in this order:

1. every key of the body, in ascending order, must be a field of the type: `malformed {type} entry: unknown field {key!r}`;
2. then, for each field of the type in the order of its table in section 6: if present it must have the JSON type listed (`malformed {type} entry: field {key!r} must be a string`, `… an integer`, `… an array` or `… an object`; a boolean is not an integer); if absent it must be optional (`malformed {type} entry: missing field {key!r}`).

For `genesis`, `pins` is checked the same way against the six paths of `GENESIS_PINS`, each a required string, with the messages `malformed genesis entry: pins: …`; then each element of `founders` against its record (`login`, `key` and `github_id` required, `proof` an optional string) and each element of `witnesses` against its record of three required strings, with the messages `malformed genesis entry: founder: …` and `malformed genesis entry: witness: …` (for an element that is not an object: `… : not an object`); and then each element of `custodians` against its record of six required strings, with the messages `malformed genesis entry: custodian: …`. The subject of a `ballot_open` is checked by the rule of its kind (section 6.4, B4 and B5), and the target of a `correction` by N4 (section 6.19). The halt gate and the freeze gate of section 5.2 read `body.kind` of a `ballot_open` and `body.id` of the three other ballot types; C10 has already made each a string. The **patterns and ranges** of the values (a login, a URL, a hash, a window of days) are checked later, by the type's preconditions, each with its own message.

**No entry is a crash.** Whatever happens while an entry is applied, the outcome is acceptance or a refusal of that entry. If the code raises anything other than a refusal (an internal error of any kind, an error reading a degree table from disk, an error in the signature predicate), the entry is refused with `malformed {type} entry: {error class}: {error}` (`malformed entry: …` when the type is unknown). A degree table that is missing gives `degree canon {first 12 characters of the digest}… is not archived in canon/history/`.

**Refusals leave no trace.** Every precondition of an entry is evaluated before its first effect, so a refusal under C1 to C13 leaves the state exactly as it was, and no rule ever changes the entry itself. Only a failure of the kind of the previous paragraph that happened in the middle of the effects could leave a partial change; the reference tools therefore apply an entry to a copy of the state, and `replay` stops at the first refusal and discards its state. An implementation MUST NOT continue from a state on which an entry was refused in that way.

**Order matters for messages only.** C9 and C10 precede C11 and C12: an entry of an unknown type, or with a malformed body, is refused as such before its signer or its signature is looked at. C12a comes after the signature, so only an entry its actor really signed is ever refused for the count, and a refused entry is never counted.

**Entries taken on trust.** `ledger.apply(S, e, verifier, trusted=True)` and `ledger.replay(entries, verifier, trusted=n)` (the first `n` entries) evaluate every check of this section and of section 6 except two: every question to the signature predicate is answered yes (C12 and the proofs of G21a, G21b, G22, W7, Q5, RR9 and CL8), and Z5 does not compute the state digest. The state reached is the one a full replay reaches, whenever a full replay accepts the entries. It is for a verifier that judges what was added to a history it verified before (section 9.1); a replay with `trusted = 0`, the default, is the definition of a valid ledger.

### 5.2 Signer resolution: who may sign which type

`ledger._signer(S, e, now)` returns the key that must have signed the entry, and the member record it belongs to if any, or refuses. The rows are tried in this order. After the first row, and before every other, comes the **halt gate**: if a halt is in force at `now` (`halted(now)`, section 6.19.4), `type` is not in `HALT_ALLOWED`, and the entry is not an entry of an unstoppable ballot (below), the entry is refused with `the ledger is halted until {end} (correction {seq}): only custodian entries, custodian_revoke, correction_object, depart, rekey, the entries of a key recovery, a witness checkpoint, an amendment ballot and the ballot that removes a custodian are accepted`.

An entry is **an entry of an unstoppable ballot** (`ledger._unstoppable`) when its type is `ballot_open` and `body.kind` is in `UNSTOPPABLE_KINDS` (`amendment`, `custodian`), or its type is `ballot_commit`, `ballot_reveal` or `ballot_close` and `S.ballots[body.id]` exists and has a kind in `UNSTOPPABLE_KINDS`.

| `type` | Signer key | Refusals |
|---|---|---|
| `genesis` | The value of `key` in the first element of `body.founders`. | `genesis needs founders` when `body.founders` is empty. |
| `correction`, `correction_cosign`, `correction_apply`, `correction_withdraw`, `custodian_alive` | `S.custodians[actor].key`, provided the record exists and the key is live at `now` (section 4.8). | In this order: `no custodian exists, so no correction exists` when `S.custodians` is empty; `{actor} is not a custodian`; `the custodian key of {actor} is {status} and signs nothing (a lapsed, revoked or removed key never signs again)`, with `status` = `lapsed`, `revoked` or `removed`. |
| `custodian_revoke` | `S.custodians[actor].revoke_key`, provided `body.name = actor`, the record exists and the custodian key is live at `now`. | `no custodian exists, so no correction exists`; then `the actor of a custodian_revoke is the custodian whose key it removes` when `body.name ≠ actor`; then the two messages above. |
| `petition` | `body.key`: the petitioner signs with the key being registered. | The petition preconditions P0 to P7a of section 6.2 are evaluated here, before the signature. P0 requires a live invitation: without one, no key outside the state can sign anything. |
| `witness` | `S.witnesses[actor]`, provided no `freeze_witness` of `actor` is in force at `now`. | `unknown witness` when `actor` is not a key of `S.witnesses`; `the witness {actor} is frozen until {end} (correction {seq})`. |
| `ballot_close`, `exam_draw`, `council_draw` | `S.witnesses[actor]` when `actor` is a key of `S.witnesses`, under the same proviso; otherwise the member rule below. | the frozen-witness message; otherwise as below |
| `rekey_recover` | `body.key`: the member's **new** key signs the request. Provided the record `S.members[actor]` is **recoverable** (below), and `body.key` is a valid key (section 2.6). | `{actor} is not a member whose key can be recovered (not a member, departed, expelled or voided)`; then `keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)` |
| `rekey_recover_apply` | `S.recoveries[actor].key`: the new key the request named. Provided the record `S.members[actor]` is recoverable, and `S.recoveries[actor]` exists with `applied`, `objected` and `void` all null. | the first message of the row above; then `no recovery of the key of {actor} is pending` |
| `depart` | `S.members[actor].key`, provided the record exists and its `status` is not in `DEPART_BLOCKED` (`departed`, `expelled`, `voided`). | `{actor} is not a member who can depart (not a member, already departed, expelled or voided)` |
| `rekey` | `S.members[actor].key`, the key the ledger holds (the key being replaced), provided the record exists and its `status` is not in `REKEY_BLOCKED` (`departed`, `expelled`, `voided`). | `{actor} is not a member who can replace their key (not a member, departed, expelled or voided)` |
| `rekey_object` | `S.members[actor].key`, provided the record is recoverable. | the same message |
| `ballot_reveal`, when the record `S.members[actor]` has `status = voided`, `S.ballots[body.id]` exists and `actor` is a key of its `commits` | `S.members[actor].key`: a vote sealed before the admission was undone is still revealed (section 6.19.8). | none here; in every other case of a `ballot_reveal` the next row applies |
| every other type | `S.members[actor].key`, provided the record exists and `is_active(now)`. | `{actor} is not an active member` |

A record is **recoverable** (`ledger.recoverable`) when it exists and either its `status` is not in `REKEY_BLOCKED`, or its `status` is `departed` and its `left` is not null: the member departed, and a completed recovery reverses the departure (sections 6.15 and 6.29). Every departure sets `left`; which departed records may still ask for a recovery is RR3a (section 6.26).

The last five rows (from `depart` on) end with the **freeze gate**: if the key of `actor` is frozen at `now` (`key_frozen(actor, now)`: a `freeze_key` of `actor` is in force, or a recovery of that key is under way), the entry is refused unless it is one of the entries a frozen member may sign (section 6.19.1). The message is `the key of {actor} {why}: a frozen member may only depart, rekey, vote (commit and reveal), take part in an amendment ballot or the ballot that removes a custodian, or object to a recovery of their own key`, where `{why}` is `is frozen until {end} (correction {seq})` while a freeze is in force, and otherwise `stays frozen while its recovery is pending (entry {seq}, until {recovery_end} at the latest)`, with `seq` that of the recovery and `recovery_end` as in section 4.10. In both gates and in the frozen-witness message, `end` is the end of the act's interval as things stand at that entry (section 7.8), in the text form of section 2.5. The two rows of the recovery types have no freeze gate: the key that signs them is not the frozen one.

Rules that follow from the code:

1. **Exact match.** `actor` is looked up in `S.custodians`, `S.witnesses` and `S.members` by exact string equality. A member admitted as `Alice` cannot sign as `alice`.
2. **No name is two things.** A name is never a key of two of `S.custodians`, `S.witnesses` and `S.members` (section 4.7), so the resolution of the four `WITNESS_TYPES` is never ambiguous, and the type alone says which map a custodian entry is looked up in.
3. **Active means `is_active(now)`.** A member with `status = suspended` whose suspension has been served may sign. A dormant member may sign; dormancy never blocks an act.
4. A witness may sign only the four `WITNESS_TYPES`. A witness cannot open a ballot, vote, invite, vouch or post a `council_call`.
5. **Leaving needs no good standing** (Landmark VII), **and neither does replacing or defending one's own key.** A member under an unserved suspension can sign exactly three types with the key the ledger holds: `depart`, `rekey` and `rekey_object`. `DEPART_BLOCKED` and `REKEY_BLOCKED` are the lists of statuses that cannot; a status added to the protocol later can leave and can replace its key unless it is added to them. **Neither a freeze nor a halt is a status, and neither stops any of the three:** `depart`, `rekey` and `rekey_object` are in `HALT_ALLOWED` and in `FREEZE_ALLOWED`, so a member whose key is frozen can always leave, can always replace that key and can always stop a recovery of it (unless that recovery is final, section 6.28), also while the ledger is halted. None of the three is counted against the entries of a day either (all three are in `DAILY_EXEMPT`; a `rekey` is bounded by its own rule, once in 30 days).
6. An expelled, departed or voided login may sign one type with its own key: `petition`, under P0 and P1. Two cases add to this. A record that is `voided` reveals a vote it sealed in a ballot that is still open (the row above): the vote was cast before the undo. A record that departed (`left` is set) still signs `rekey_object` with that key, and the new key of a recovery of it signs the two recovery types (RR3a bounds when such a recovery may be asked).
7. **No stranger signs without a second party.** A key that is not in the state (not a member's, not a witness's and not a custodian's) can sign exactly two things. One is the `petition` of a login that holds a live invitation, signed by an active Master Builder (section 6.17). The other is the `rekey_recover` of any member whose record is recoverable (a recovery never needs a custodian, and RR3a bounds it for a member who departed), and then the `rekey_recover_apply` of that same request; the request changes no key, and its application needs its co-signers, its notice and, unless it is final, the silence of the key the ledger holds (section 6.29). Everything else that reaches the ledger is signed by a key the ledger already knew. **One case rests on the gate alone:** where the member is the only active Master Builder, a request without a freeze needs no co-signer (`ledger.cosigners_needed` is 0), so in replay nothing but the 45 days of notice and the old key's objection stands between a key outside the state and that membership; that the request comes from the member's own GitHub account, with a key that account lists, is the gate of section 9.3 (section 12, point 62).

8. **The key the ledger holds.** For a member the signer key is the key of the record at that moment: after a `rekey` it is the new key, from the very next entry, and the old key signs nothing more.
9. **A custodian signs custodian entries and nothing else.** A custodian key signs the five `CUSTODIAN_TYPES`; a revoke key signs `custodian_revoke`. Neither is the key of a member or of a witness (section 4.7), so neither can sign any other type, and no member or witness key can sign a custodian entry. While `S.custodians` is empty (the genesis named none and no founder's claim has been applied, section 6.33), the six types are refused for every actor.
10. **The gates look at time, not at an entry.** Whether a halt or a freeze is in force, and whether a custodian key is live, is computed at `now` from stored facts (sections 4.8 and 7.8). No entry is needed for a freeze to end or a key to lapse, and none can be missing.

11. **What a frozen member and a halted ledger still take is decided by the entry, not only by its type.** The two gates read the kind of the ballot an entry belongs to (`ledger._unstoppable`). The halt gate lets a `ballot_open`, `ballot_commit`, `ballot_reveal` or `ballot_close` through exactly when its ballot is an amendment or removes a custodian. The freeze gate lets a `ballot_commit` and a `ballot_reveal` through in every ballot (`FREEZE_ALLOWED`), and a `ballot_open` and a `ballot_close` exactly when the ballot is an amendment or removes a custodian. A custodian can therefore neither halt the ledger against its own removal or against an amendment, nor freeze the Masters out of either, and no freeze changes who votes in any ballot. A frozen key still never co-signs or opposes a recovery and never objects to a correction: it may be in other hands, and those entries vouch for or against someone.

The resolution also says **whose act** the entry is: the member record whose key was returned, for the last five rows of the table, and nobody for the others (the two recovery types included).

### 5.3 Activity bookkeeping

After the type's effects (C14): if the signer key was resolved through `S.members` (the last five rows of the table of section 5.2), the type is not in `UNCREDITED` (`depart`, `rekey`, `rekey_object`), and that record is still the record of `actor`, the member is **credited** at `now` (`Member.credit`):

- if the last time in `activity` falls on the same UTC calendar day as `now` (same year, month and day), it is replaced by `now`;
- otherwise `now` is appended;
- then every time `t` at the front of the list with `expired(t, now, LIGHT_WINDOW_DAYS)`, that is with `now − t > 1,800 d`, is removed. The last time is `now` and is never removed.

Consequences:

- Activity belongs to the member who signed. A `custodian_claim`, a `custodian_claim_apply` and a `custodian_claim_object` credit the member who signed them (the founder; the objecting Master); so does a `succession_claim`. A `petition` (signed with the key in its body, also when the login has an earlier record), a `genesis`, every entry signed by a witness and every entry signed by a custodian key or a revoke key credit nobody: a custodian's entries never add activity to the member the custodian is linked to. A `correction_object` credits the Master who signed it, and a `rekey_cosign` the Master who co-signed. A `rekey_recover` and a `rekey_recover_apply` are signed by a key that is not yet the member's and credit nobody. An `invite` credits the Master who signed it, like any other act of a member.
- A member gains at most **one point per UTC day**, whatever the number of entries; the point carries the time of the day's latest entry, so `dormant` is measured from the member's true last act.
- A member created by genesis or by an admission starts with `activity = [now]` from the effect itself.
- **The list is bounded.** It holds one time per UTC day and spans at most 1,800 days, so at most 1,801 times, however long the membership lasts. What is dropped is read by no rule: `dormant` reads the last time, and in `light` a dropped point weighed less than `2^−10`.
- `depart` adds nothing, and neither do `rekey` and `rekey_object`: replacing or defending a key is upkeep, not work, and a suspended member may do it.

Activity feeds `dormant(now)` and `light(now)` and nothing else. The reveal of a `voided` record (section 5.2) credits that record like any other; nothing reads the activity of a record that is no membership.

### 5.4 Rate limits

Nobody writes to the ledger without bound. Each limit below is a rule of replay, evaluated from stored facts, and each exists because the entry it limits costs every verifier something forever: a record in the state, bytes in the state digest, or a full digest computation.

**Entries per actor per day (C12a, C14a).** An actor has at most `ENTRIES_PER_DAY` = 20 counted entries in one UTC calendar day. The day of an entry is the first ten characters of its `time`; the count is kept in `S.day` and `S.day_entries` and starts again with the first entry of a later day, so the state holds the counts of one day only. The actor is the `actor` string, whatever signs: a member, a witness, a custodian, a petitioner, the new key of a recovery. The **daily-exempt set** is neither counted nor refused: the types of `DAILY_EXEMPT`, and the opening of an amendment ballot or of a ballot that removes a custodian (`ledger.daily_exempt`):

- `depart`, `rekey`, `rekey_object`, `custodian_revoke`, `correction_object` and `custodian_claim_object`, because they must stay possible whatever else was signed under the same name that day: leaving (Landmark VII), replacing one's own key, stopping a recovery of one's own key, removing a custodian key with its revoke key, objecting to a correction and to a founder's claim. Whoever holds a stolen key could otherwise use up the day to keep its owner from answering. Each is bounded by its own rule: once per membership, once in 30 days, once per recovery, once per custodian, once per objector and correction or claim;
- the four entries of a key recovery (`rekey_recover`, `rekey_cosign`, `rekey_oppose`, `rekey_recover_apply`), bounded by `RECOVER_INTERVAL_DAYS` and by once per Master Builder per recovery;
- every entry of an amendment ballot and of the ballot that removes a custodian: the opening, bounded by B7 and B7b (one slot per text proposed, and at most three open amendment ballots per opener; at most one removal ballot per custodian), the vote and the close as below;
- `ballot_commit` and `ballot_reveal`, because a vote is bounded by itself (one commitment and one reveal per elector per ballot) and a cap on votes would let whoever opens many ballots at once keep electors from voting in all of them;
- `ballot_close`, `exam_draw` and `council_draw`, because each happens once per ballot or per lot, whoever signs it, and a witness that closes many ballots on one day must not be kept from closing the rest.

Twenty is far above what a member signs by lawful acts in a day under the other rules (three open ballots, four sponsorships, one `work`, the reports of the exams one was drawn to), and equal to what a witness reaches only by a checkpoint in almost every hour. It is a backstop: it bounds what a rule that was overlooked could cost, and it is not the limit that binds in ordinary use (section 12, point 61).

**Open ballots per opener (B7b).** A member has at most `OPEN_BALLOTS_PER_OPENER` = 3 ballots of their own open at once of the kinds other than `amendment` and `custodian`, together, and apart from them at most 3 open amendment ballots. A ballot of kind `custodian` is never counted and never refused for the count: there is at most one per custodian. Every open ballot is scanned by the rules that look for a subject (B7), a name or a key (section 4.7), so the number of open ballots is a cost of every later entry. Three lets a sponsor run the admissions of a season beside a sanction; counting amendments apart means no other ballot ever holds the place of the amendment that repairs the law; a closed ballot frees its place, and any active member or witness closes an ended ballot.

**The same subject again (B7a).** The opener of a ballot of one of `REOPEN_KINDS` (`sanction`, `witness`) that `failed` or `lapsed` opens a ballot of that kind on the same subject key again only once `REOPEN_AFTER_DAYS` = 90 days have passed since its close (`waited`), unless the new ballot is the re-run of the lapsed one (B2a). Only one ballot of a kind is open on a subject (B7), so without the wait one member could hold a subject forever by closing a ballot and opening the next in the same pull request. Another member may open one at once: the rule stops a slot from being held, it does not stop the question from being put again. A ballot that `passed` leaves no wait, because a passed ballot holds nothing (two thirds of the votes agreed) and the opener of a passed amendment must be able to propose the correction of a wrong pin at once; a ballot that a correction `voided` leaves none, because nobody is penalized by a void. `admission` and `advancement` are not in `REOPEN_KINDS`: such a ballot can only be opened on a live petition by a sponsor (A3) or on a passed, unused exam by the candidate or an examiner (D5), so it cannot be opened freely, and one that lapsed for want of a quorum is meant to be opened again at once (section 6.7). `amendment` and `custodian` are not in it either: an amendment's slot is its text (B7), so nobody holds a path by opening on it, and the ballot that removes a custodian must never wait on the custodian's account. Ninety days is the rest the protocol uses elsewhere after a failed attempt (`EXAM_RETRY_DAYS`, `RECOVER_INTERVAL_DAYS`, `REJOIN_AFTER_DAYS`).

**Checkpoints (Z6, Z7).** A witness posts a checkpoint only when at least one entry whose type is not `witness` was applied since its own last checkpoint (`S.acts` has grown past the `acts` of its mark in `S.witness_marks`), and only when that last checkpoint is at least `CHECKPOINT_INTERVAL` = 1 hour old. A checkpoint makes every verifier compute a full state digest (Z5) and leaves a record in the state; one that covers nothing new adds nothing. The first rule alone is no bound per hour on a busy ledger; the second bounds one witness key to 24 checkpoints a day (20 with C12a) however busy the ledger is. A checkpoint of another witness is not a new entry. `ledger.checkpoint_due(S, name, now)` is the same condition as a pure function, for the witness node.

**Signs of life (AL1).** A custodian key gives at most one `custodian_alive` in `ALIVE_INTERVAL` = 24 hours, counted from its last sign of life (the genesis, or the `custodian_claim_apply` that named it, for the first). One sign in 180 days keeps a key live (section 4.8); a sign a day is already far more than the rule needs, and each entry is one more entry for every verifier.

What else is bounded, and by what: invitations and sponsorships by the budget (section 7.5); `work` by `WORK_INTERVAL`; `rekey` by `REKEY_INTERVAL_DAYS`; exams by the retry rule (E6); restricting corrections by `CORRECTIONS_PER_30_DAYS` and each custodian's share (N6, N6a); notes by `NOTES_PER_DAY`, and the notes the state keeps by `NOTES_KEPT`; recovery requests by `RECOVER_INTERVAL_DAYS`; objections, co-signatures, oppositions, verdicts and recusals by "once per actor per target".

---

## 6. Entry types

Each subsection gives: the signer; the body fields; the preconditions in evaluation order, each with its exact refusal message; the effects on the state; and notes. Preconditions come after the common checks C1 to C12a. The body tables are exact (C10): a field not listed is refused, "required" means that absence is refused, and the column "Type" is the JSON type checked by C10. The column "Constraint" is checked by the numbered preconditions.

The subsections keep the order in which the types were specified: `invite` (6.17) and `rekey` (6.18) come after the first sixteen, the five types of custodians and immediate corrections follow (6.19 to 6.23), then the two that make a noticed correction effective (6.24, 6.25), the five of the recovery of a key (6.26 to 6.30), the three of the founder's fallback (6.31 to 6.33) and the succession claim (6.34). An admission reads in this order: `invite` (section 6.17), `petition` (6.2), `vouch` (6.3), `ballot_open` of kind `admission` (6.4.1), the votes (6.5, 6.6) and `ballot_close` (6.7).

### 6.1 `genesis`

**Signer:** the key of the first founder, taken from the body (section 5.2). **Function:** `ledger._genesis`.

| Body field | Type | Constraint |
|---|---|---|
| `name` | string, required | `NAME_RE`: 1 to 120 printable ASCII characters. |
| `pins` | object, required | Exactly the six members below, no more and no fewer (C10). Each value is a string, required, matching `HEX64`. |
| `pins["canon/degrees.toml"]` | string, required | Pin of the degree table. |
| `pins["canon/eternal.toml"]` | string, required | Pin of the eternal Landmarks and the Declaration. |
| `pins["CONSTITUTION.md"]` | string, required | Pin of the Constitution. |
| `pins["@protocol"]` | string, required | Pin of the protocol core (section 8.3). |
| `pins["docs/governance/CUSTODIAN.md"]` | string, required | Pin of the Custodian's charter. |
| `pins["docs/governance/ROOMS.md"]` | string, required | Pin of the charter of the rooms. |
| `declaration_sha256` | string, required | `HEX64`. The digest of the Declaration: `H` of the UTF-8 bytes of `[declaration].text` in `canon/eternal.toml`. |
| `founders` | array, required | 1 to 7 objects, each with `login` (string, required: a login), `key` (string, required: a key), `github_id` (integer, required: at least 1, the numeric id of the founder's GitHub account) and `proof` (string: a signature, below; absent in the first founder, required in every other). No other field. |
| `witnesses` | array, required | Any number of objects, possibly none, each with exactly three strings, all required: `name` (a login), `key` (a key) and `proof` (a signature, below). The size limit of the entry bounds the number. |
| `custodians` | array, required | 0 to 3 objects, each with exactly six strings, all required: `name` (a login that is no founder's and no witness's), `key` and `revoke_key` (two keys), `member` (the login of a founder of this genesis), `proof` and `revoke_proof` (signatures, below). |
| `custodian_threshold` | integer, required | 0 when `custodians` is empty; otherwise 1 to the number of custodians. |

**Nobody is named at genesis with a key they do not hold.** The first founder signs the entry itself. Every other founder, and every witness, proves possession of the key the entry gives them. The **founder message** (`ledger.founder_message(login, github_id, key)`) and the **witness message** (`ledger.witness_message(name, key)`) are ASCII byte strings whose lines are each ended by the single byte `LF` = `0x0A`, with nothing else between them:

```
message = "openmasonry founder v1" LF login LF github-id LF key LF
message = "openmasonry witness v1" LF name LF key LF
```

where `login`, `name` and `key` are the fields of the record exactly as written and `github-id` is the founder's `github_id` in base 10, without sign or leading zero. The first lines are the constants `FOUNDER_DOMAIN` and `WITNESS_DOMAIN`. `proof` is a signature of that message by `key`, in the one accepted form of section 13 for the type of the key: `sig_ok(founder message, proof, login, key)` and `sig_ok(witness message, proof, name, key)`. The witness message is also what the key of a proposed witness signs in a witness ballot (section 6.4.5). Vector: for the login `ada`, the id 42 and the key `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINoyJDqgsowJ2Yz/AaNNQHzExhtKRp6k5bVLwkCQz0/L`, the founder message has 111 bytes and the SHA-256 `75cd9832dea2fa7b6f746ecdbc9384ff68e27da1e2a73640d7926cfc60460326`; for the name `tyler` and the key `sk-ssh-ed25519@openssh.com AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29tAAAAIO+Vgg1pQV/h0dKMn+52r6UFgZ5Q9q1iVM+ST2qhwJNRAAAABHNzaDo=`, the witness message has 157 bytes and the SHA-256 `48bdff09028c50474bc03e8b708c8fb9e011d64ee5f524f2b7807349df34cdf6`.

Each custodian proves possession of its two keys. The **custodian message** (`ledger.custodian_message(name, member, key)`) and the **revoke message** (`ledger.custodian_revoke_message(name, key, revoke_key)`) are ASCII byte strings of four lines, each ended by the single byte `LF` = `0x0A`, with nothing else between them:

```
message = "openmasonry custodian v1" LF name LF member LF key LF
message = "openmasonry custodian-revoke v1" LF name LF key LF revoke-key LF
```

where `name`, `member`, `key` and `revoke-key` are the fields of the custodian's record exactly as written, the two keys in the text form of section 2.6. The first lines are the constants `CUSTODIAN_DOMAIN` and `CUSTODIAN_REVOKE_DOMAIN`. `proof` is a signature of the custodian message by `key`, and `revoke_proof` a signature of the revoke message by `revoke_key`, each in the one accepted form of section 13 for the type of its key, checked by the same predicate as every signature: `sig_ok(custodian message, proof, name, key)` and `sig_ok(revoke message, revoke_proof, name, revoke_key)`.

Vector: for the name `warden`, the member `hiram`, the key `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINoyJDqgsowJ2Yz/AaNNQHzExhtKRp6k5bVLwkCQz0/L` and the revoke key `sk-ssh-ed25519@openssh.com AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29tAAAAIO+Vgg1pQV/h0dKMn+52r6UFgZ5Q9q1iVM+ST2qhwJNRAAAABHNzaDo=`, the custodian message has 119 bytes and the SHA-256 `4c80dbe76c07140c109ba360d9cf6a9919af77544524c8aa03f2026839d44c29`, and the revoke message has 248 bytes and the SHA-256 `a122e5f9dbcbccab35d593a3dc2d055084960bfb28c64411624677ab8a0b1187`. No field holds a line feed, so each message has one reading. The five proof messages of the protocol (the founder, witness, custodian and revoke messages, and that of a `rekey`, section 6.18) differ in their first line, and none begins with `{` as the signed payload of every entry does: a proof made for one purpose is never a proof for another, and never the signature of an entry.

| # | Precondition | Refusal message |
|---|---|---|
| G1 | The six values of `pins` match `HEX64`. | `genesis must pin each governed path to a sha256 (64 lowercase hex)` |
| G2 | `declaration_sha256` matches `HEX64`. | `genesis must record the sha256 of the Declaration (64 lowercase hex)` |
| G3 | The degree table with digest `pins["canon/degrees.toml"]` is available to the verifier and well formed (section 8.4). | `degree canon {first 12}… is not archived in canon/history/`; `degree canon {first 12}… is malformed (33 degrees with exact fields)` |
| G4 | `1 ≤ len(founders) ≤ 7`. | `1..7 founders` |
| G5 | `founders[0].login = actor` (exact). | `genesis must be signed by the first founder` |
| G6 | The foldings of all founder logins and all witness names are pairwise distinct. | `duplicate founder or witness name (case-insensitive)` |
| G7 | Every founder login matches `LOGIN_RE`. | `founder logins must be valid GitHub logins` |
| G8 | Every witness name matches `LOGIN_RE`. | `witness names follow login rules` |
| G9 | Every founder key and every witness key is a valid key (section 2.6), of either type. | `keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)` |
| G10 | No two founder or witness keys are the same key: their points are pairwise distinct, whatever their types. | `founders and witnesses must use distinct keys (one key per login)` |
| G10a | The first founder has no `proof`, and every other founder has one. | `the first founder signs the genesis itself and carries no proof; every other founder carries one` |
| G11 | `name` matches `NAME_RE`. | `name: 1..120 printable ASCII characters` |
| G12 | Every founder's `github_id ≥ 1`. | `founder github_id must be a positive integer (the numeric GitHub user id)` |
| G13 | The founders' `github_id` values are pairwise distinct. | `founders must be distinct GitHub accounts (a github_id appears twice: one GitHub account, one member)` |
| G14 | `len(custodians) ≤ 3` (`CUSTODIANS_MAX`). | `0..3 custodians` |
| G15 | `custodian_threshold = 0` when `custodians` is empty; otherwise `1 ≤ custodian_threshold ≤ len(custodians)`. | `custodian_threshold is 0 without custodians, and otherwise 1 to the number of custodians` |
| G16 | Every custodian `name` matches `LOGIN_RE`. | `custodian names follow login rules` |
| G17 | The foldings of all founder logins, all witness names and all custodian names are pairwise distinct. | `a custodian name must differ from every founder login, witness name and other custodian name (case-insensitive): it is never a member login` |
| G18 | Every custodian `key` and `revoke_key` is a valid key (section 2.6), of either type. | `keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)` |
| G19 | The points of all founder keys, all witness keys and all custodian keys and revoke keys are pairwise distinct, whatever their types. | `a custodian key and its revoke key must differ from each other and from every other key of the genesis` |
| G20 | Every custodian `member` is exactly the `login` of a founder of this genesis. | `a custodian's member must be the login of a founder of this genesis` |
| G21 | The custodians' `member` values are pairwise distinct. | `custodians must be linked to distinct members (one person, one custodian key)` |
| G21a | For each founder after the first, in order: `sig_ok(founder message, proof, login, key)`. | `bad founder proof: the key of {login} must sign the founder message (login, github_id, key)` |
| G21b | For each witness, in order: `sig_ok(witness message, proof, name, key)`. | `bad witness proof: the key of {name} must sign the witness message (name, key)` |
| G22 | For each custodian, in order: `sig_ok(custodian message, proof, name, key)`; then `sig_ok(revoke message, revoke_proof, name, revoke_key)`. | `bad custodian proof: the custodian key must sign the custodian message (name, member, key)`; `bad custodian revoke proof: the revoke key must sign the revoke message (name, key, revoke key)` |

Effects:

1. `S.pins = pins`: the six paths, each with its value.
2. `S.declaration_sha256 = declaration_sha256`.
3. `S.name = name`.
4. For each founder, in order: `S.members[login] = Member(login, key, degree = 3, since = {1: now, 2: now, 3: now}, sponsors = (), status = active, activity = [now], founder = true, github_id = the founder's github_id)`; every other field at its default (null, 0 or empty).
5. `S.witnesses = {name: key}` for each witness.
6. `S.known_keys` = the set of the points of all founder and witness keys and of the custodian key and the revoke key of every custodian.
7. For each custodian, in order: `S.custodians[name] = Custodian(name, key, revoke_key, member, alive = now, genesis = true, revoked = null, removed = "", since = now)`.
8. `S.custodian_threshold = custodian_threshold`.

Notes:

- Genesis is entry 0 and only entry 0 (C9). It credits nobody (section 5.3).
- The six pins and the Declaration digest are not compared with any file during replay. Comparing them with the tree is the gate of section 8.5.
- Founders hold the 3rd degree, never more.
- Replay requires the founders to be distinct accounts (G13) and does not compare any `github_id` with GitHub. Whether each login is the account with that id is the gate of section 9.3.
- A founder or a witness may hold a key of either type (section 2.6). The genesis is signed by the first founder's key, under the rules of that key's type (section 13).
- Every point of `S.known_keys` proved possession: the first founder's key signed the entry, and each other key signed its message (G21a, G21b, G22). Without the proofs a genesis could register, and so bar from every later `rekey`, a key its holder never offered.
- Replay does not ask who the first founder is. That the genesis comes from the GitHub account the pinned core names (`founder_github_id`) is the gate of section 9.3.
- **Custodians.** A genesis may name none: then `S.custodians` stays empty, and no correction is accepted on that ledger (section 5.2), until a founder's claim is applied (sections 6.31 to 6.33). A claim needs no custodian of the genesis: it needs only that no custodian key is live, that the Sunset has not been reached and that fewer than three active Master Builders who are not founders exist. A custodian is not a member: its name is in no map but `S.custodians`, it holds no degree and no vote, and its keys are no member's and no witness's. The name and both keys are held for good (section 4.7): no invitation, petition, witness ballot or `rekey` can ever take them, also after the key has lapsed or been revoked. G21 keeps one person from holding two custodian keys under one member account. The proofs (G21a, G21b, G22) are checked once, here; nothing in an entry proves that the two keys are held by different devices, or offline.
- The key set of `pins` is fixed by the protocol, not chosen by the founders: a missing path is refused with `malformed genesis entry: pins: missing field '{path}'`, any other key with `malformed genesis entry: pins: unknown field '{key}'`. After genesis the six pins are ordinary pins: an amendment moves any of them except `canon/eternal.toml` (section 8.2), and amendments may pin further paths.

### 6.2 `petition`

**Signer:** `body.key` (self-signed). **Functions:** `ledger._petition_checks` (P0 to P7a, before the signature check), `ledger._petition` (P8).

| Body field | Type | Constraint |
|---|---|---|
| `key` | string, required | A valid key (section 2.6). |
| `declaration_sha256` | string, required | Equal to `S.declaration_sha256`. |

| # | Precondition | Refusal message |
|---|---|---|
| P0 | A live invitation exists for exactly `actor`. First: no pair of `name_holders(actor, now)` is an `invitation` under another spelling. Then: `invited(actor, now)`. | `login {actor!r} collides with the invitation of {other!r} (a petition uses exactly the invited login)`; `no live invitation for {actor!r} (a Master Builder invites first, and an invitation lapses after 30 days)` |
| P1 | `may_return(S.members.get(actor), now)` (`ledger.may_return`): `S.members` has no record under `actor` (exact), **or** the record has `status = departed` or `status = voided` (its admission was undone by a correction) and `waited(status_since, now, 90)`, **or** it has `status = expelled` and `waited(status_since, now, 365)`. | `already a member (departed members, and members whose admission was undone, may petition again once 90 days have passed, expelled members once 365 have)` |
| P2 | For each pair of `name_holders(actor, now)`, in order: a `member` pair has exactly the spelling `actor`; no pair is a `witness`; a `petition` pair has exactly the spelling `actor`. | `login {actor!r} collides with {other!r} (logins are case-insensitive)`; `login {actor!r} collides with the witness {other!r} (a witness name cannot become a member login, and names are case-insensitive)`; `login {actor!r} collides with the pending petition of {other!r}` |
| P3 | `actor` has no live petition. | `a petition is already pending` |
| P4 | No admission ballot with subject key `fold(actor)` is open. | `an admission ballot on this login is open` |
| P5 | No pair of `name_holders(actor, now)` is a `ballot`. | `login {actor!r} is the name proposed by an open witness ballot ({other!r})` |
| P6 | `body.key` is a valid key (section 2.6), of either type. | `keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)` |
| P7 | Every pair of `key_holders(body.key, now)` is exactly `("member", actor)`. Keys are compared by their points. | `this key is already used by {other} (one key per login: members, witnesses and petitions)` |
| P7a | The point of `body.key` is not in `S.known_keys`, **unless** it is the key of `S.members[actor]` (the record under exactly `actor`), or the key of a record of `S.petitions` whose login is the same login as `actor` (up to case). Keys are compared by their points. | `this key was used in this ledger before (a key that was ever registered here is never registered again; a returning member may keep the key of their own record, and a petitioner the key of their own lapsed petition)` |
| P8 | `body.declaration_sha256 = S.declaration_sha256`. | `petition must commit to the sha256 of the Declaration (openmasonry declaration)` |

Effects:

1. Every key of `S.petitions` that is the same login as `actor` is removed. After P2 to P4 these can only be lapsed petitions: the actor's own, or one under another spelling of the login.
2. The invitation `i = S.invitations[actor]` is removed from `S.invitations`.
3. `S.petitions[actor] = {key: body.key, vouches: [i.by], time: now, github_id: i.github_id}`.
4. The point of `body.key` is added to `S.known_keys`.

Notes:

- **The petition takes the place of its invitation.** The inviter is the first sponsor without a `vouch` entry, and a `vouch` by the inviter is refused (V4). The inviter's budget counts the candidate once: as a live invitation before the petition, as a reserved petition after it (section 7.5). The inviter is not looked at again here: an inviter who has since left, been banned or been expelled stays in `vouches`, and the admission ballot decides at its opening who still counts (A2).
- Under P0 a petition is, besides the request of a key recovery (section 6.26), the only entry that a key outside the state can sign, and only while an invitation is live. A candidate who is refused, or whose petition lapses, needs a new invitation. A candidate whose admission ballot **lapsed** (too few voted, section 6.7) keeps the petition: a sponsor opens another ballot on it.
- P1 refuses an active member, a suspended member (served or not) and a member who left or was expelled too recently. The same condition was required when the invitation was signed (I5, section 6.17), and time only moves forward, so the waiting periods of P1 are always complete once P0 has passed; likewise P2 to P5 cannot fail then, since an invitation is refused while its name is held and holds the name while it is live. Two cases remain for P1, in which the record changes back between the invitation and the petition, and the petition is refused: a member who was expelled, was invited after the 365 days, and is then reinstated by a sanction ballot (section 6.4.4) before petitioning is `active` again; and a member who departed, was invited after the 90 days, and whose departure a recovery then reverses (a recovery asked before the departure or within 30 days of it, or one that follows such a recovery, applied after the invitation: section 6.26) is back in the status it had. A voided record is no third case: it is invited only once 90 days have passed since the undo and while no sanction ballot on it is open (I5), and from then on no ballot that could expel it is opened (SN2a). P2 to P5 are kept as stated and evaluated. A returning login must be spelled exactly as its earlier record (I5, P2).
- P7 lets a returning member petition with the key of their old record (the key that record holds now, after any `rekey`), and with no key that anyone else holds. P7a then looks at `S.known_keys`: a key that was ever registered is not registered again by a petition, whoever held it, except the key of the login's own record and the key of the login's own petition (a lapsed one, which effect 1 replaces). So the key of a petition of another login, a key a member replaced and the key of a removed witness never come back.
- A **lapsed** petition blocks nothing: not its own login, not another spelling of it, not its key. It is simply replaced.
- The entry credits nobody, also when `actor` has an earlier record (section 5.3).
- Whether the key really belongs to the login on GitHub, and whether the pull request comes from the invited GitHub account, are gates (section 9.3), not rules of replay.

### 6.3 `vouch`

**Signer:** an active member. **Function:** `ledger._vouch`.

| Body field | Type | Constraint |
|---|---|---|
| `candidate` | string, required | The login of a live petition, exact. |

A `vouch` adds a further sponsor to a petition. The first sponsor is the inviter, by the invitation itself.

| # | Precondition | Refusal message |
|---|---|---|
| V1 | `candidate` has a live petition. | `no such petition (or it lapsed)` |
| V2 | No admission ballot with subject key `fold(candidate)` is open. | `the admission ballot on this petition is already open (its sponsors are frozen)` |
| V3 | `stands_in(actor, now)`: the actor's `degree ≥ 3`, or the actor is a successor (section 6.34). | `only Master Builders may sponsor (and, while a succession is in force, the members of the highest degree present)` |
| V4 | `actor` is not already in the petition's `vouches` (the inviter is, from the start). | `already a sponsor of this petition (the inviter sponsors by inviting)` |
| V5 | The actor's `sponsor_ban_until` is null or `now ≥ sponsor_ban_until`. | `sponsorship suspended (a sponsored member was expelled for fraud)` |
| V6 | `sponsorships(actor, now) < 4` (section 7.5). | `sponsorship budget exhausted` |

V5 and V6 are the two checks of `ledger._sponsor_checks`, which an `invite` makes in the same order (I6, I7).

Effects:

1. `actor` is appended to `S.petitions[candidate].vouches`.

### 6.4 `ballot_open`

**Signer:** an active member. **Function:** `ledger._ballot_open`, with one opening function per kind (`ledger.OPENERS`). The type is in `PROVING`: the rule of the kind `witness` asks the signature predicate about a proof (W7).

| Body field | Type | Constraint |
|---|---|---|
| `id` | string, required | `BALLOT_ID_RE`; never used before. |
| `kind` | string, required | One of `KINDS`. |
| `subject` | object, required | Exactly the fields of the kind (below). |
| `commit_days` | integer, optional | Only for the kind `amendment` (`OPENER_WINDOWS`). Default 7. 2 to 30. |
| `reveal_days` | integer, optional | Only for the kind `amendment`. Default 3. 1 to 14. |
| `rerun` | string, optional | The id of a lapsed ballot this one re-runs. |

Preconditions common to every kind, first part:

| # | Precondition | Refusal message |
|---|---|---|
| B1 | `kind` is in `KINDS`. | `kind must be one of ['admission', 'advancement', 'amendment', 'custodian', 'sanction', 'witness']` |
| B2 | `id` matches `BALLOT_ID_RE`. | `ballot id: 1..64 of a-z 0-9 . _ - starting with a letter or digit` |
| B3 | `id` is not a key of `S.ballots` (open or ended) and not in `S.retired`: an id is used once, ever. | `ballot id {id!r} is already used` |
| B4 | The key set of `subject` is exactly `SUBJECT_FIELDS[kind]`; for the kind `witness` the keys `key` and `proof` may be absent at this point (W2 decides). | `{kind} subject has exactly the keys {sorted list of the kind's fields}` |
| B5 | Each field of `subject` has its JSON type: `degree` an integer (not a boolean), every other field a string. | `{kind} subject: {key!r} must be a string`, or `… an integer` |
| B6a | The kind is `amendment`, **or** the body has neither `commit_days` nor `reveal_days`. | `{a} {kind} ballot has fixed windows (7 days to commit, 3 to reveal): it takes no commit_days and no reveal_days (only an amendment ballot does)`, with `{a}` = `an` for `admission` and `advancement` and `a` for `custodian`, `sanction` and `witness` |
| B6 | `2 ≤ commit_days ≤ 30` and `1 ≤ reveal_days ≤ 14`. | `voting windows: 2..30 days to commit, 1..14 to reveal` |
| B2r | With `rerun` present, `rerun` is not in `S.retired`. | `ballot {rerun} ended more than 111 days ago and left the state (no rule reads a ballot after that)` |
| B2a | With `rerun` present, `p = S.ballots[rerun]`: `p` exists and `p.result = lapsed`. | `ballot {rerun} did not lapse: only a ballot that lapsed for want of quorum is re-run` |
| B2b | `p.kind = kind` and `p.subject = subject` (the same object). | `a re-run has the kind and the subject of the ballot it re-runs ({rerun})` |
| B2c | `p.rerun` is empty: a re-run is never re-run. | `ballot {rerun} re-ran ballot {p.rerun}: a ballot is re-run once, and a re-run never` |
| B2d | No ballot of `S.ballots` has `rerun` equal to `rerun` (in the order they were opened, the first names the refusal). | `ballot {rerun} was re-run already, by ballot {id} (a ballot is re-run once)` |
| B2e | `not expired(p.closed, now, 30)` (`RERUN_DAYS`). | `ballot {rerun} lapsed more than 30 days ago (a re-run is opened within 30 days of the close)` |
| B2g | `p` gave at least 7 days to commit: `p.commit_until − p.opened ≥ 7 d` (`ledger.full_call`). A short ballot that lapses is opened again as a new ballot, with its whole quorum. | `ballot {rerun} gave less than 7 days to commit and is never re-run (open a new ballot, which waits for every elector)` |
| B2f | `commit_days ≥ 7`. | `a re-run gives at least 7 days to commit` |

B2r and B2a to B2e, B2g and B2f, in that order, are evaluated only when the body has `rerun`, and before the preconditions of the kind. B2g comes before B2f because no commit window makes the re-run of a short ballot acceptable: its message names the way that works (a new ballot), where B2f's would only ask for a longer window that is refused all the same. Then the preconditions of the kind (sections 6.4.1 to 6.4.6), then, second part:

| # | Precondition | Refusal message |
|---|---|---|
| B7 | `open_ballot_on(kind, subject key)` is none. | `a ballot on this subject is already open` |
| B7a | Unless the body has `rerun`, for a kind of `REOPEN_KINDS` (`sanction`, `witness`): no ballot `b` of `S.ballots` has `opened_by = actor`, the same kind, the same subject key, `result` = `failed` or `lapsed`, and `not waited(b.closed, now, 90)`. The ballots are looked at in the order they were opened; the first such one names the refusal. | `{actor} opened ballot {b.id} on this subject, and it {b.result} less than 90 days ago (the same member opens a ballot on the same subject again only 90 days after that close; another member may open one)` |
| B7b | `kind = "custodian"`, or `open_by(actor, kind) < 3` (`OPEN_BALLOTS_PER_OPENER`; section 4.7: amendments are counted apart, a removal never). | `{actor} has 3 ballots open (a member has at most 3 open ballots of their own at once, and apart from them at most 3 amendment ballots; the ballot that removes a custodian is not counted)` |
| B8 | With `(electors, base) = electorate(S, kind, subject, now)` (section 7.1): `electors` is not empty. | `no electors` |
| B8a | When `frozen.master` is true (a sanction on a Master Builder, section 6.4.4): `len(electors) ≥ 2` (`SANCTION_MASTER_VOTES`). | `a sanction on a Master Builder is never decided by a single elector: this electorate has {n} (at least 2 are needed)` |

**B9, the quorum base of a re-run.** With `rerun` present: `silent` = the electors of `p` not among the keys of `p.reveals`; `present` = the logins of `active(now)` that are in `electors`; `base = max(1, len(present − silent))`. Whoever did not vote in the lapsed ballot is not waited for again, and keeps the vote.

**B9a, time to wake up.** After B9 and before B8a: `base ≥ len(electors)`, **or** `commit_days ≥ 7` (`COMMIT_DAYS`). Refusal: `{len(electors) − base} of the {len(electors)} electors are not waited for (dormant, silent, or silent in the ballot this one re-runs): the ballot gives at least 7 days to commit, so that they can wake up and vote`. A ballot whose quorum base leaves out some of its electors (the dormant, the silent members of an admission or an advancement, section 7.7, or for a re-run those who did not vote in the lapsed ballot) gives them the full commit window to answer. Only an amendment ballot can fail it: every other kind has the fixed 7 days (B6a), and a re-run at least 7 (B2f).

Effects, applied only after B1 to B9a and the kind's preconditions have all passed:

1. The kind's opening effect, if any (advancement, and a witness ballot that adds a witness).
2. `S.ballots[id] = Ballot(id, kind, a copy of subject, electors, commit_until = now + commit_days d, reveal_until = now + commit_days d + REVEAL_GAP + reveal_days d, opened_by = actor, commits = {}, reveals = {}, result = null, frozen, opened = now, closed = null, undo = {}, corrected = null, base, rerun)`, with `commit_days = 7` and `reveal_days = 3` wherever the body states none, `base` null when it equals `len(electors)`, and `rerun` the body's value or `""`.

**Who may open which kind.** The signer rule asks for an active member; each kind then asks more of the opener:

| Kind | Opener | Rule |
|---|---|---|
| `admission` | a sponsor of the candidate who still counts | A3 |
| `advancement` | the candidate, or an examiner of the passed examination | D5 |
| `amendment` | a Master Builder (`degree ≥ 3`) | M0 |
| `sanction` | never the accused; an Arbiter (`degree ≥ 7`) where three or more active Arbiters other than the accused exist, else a Master Builder | SN4, SN5 |
| `witness` | a Master Builder | W0 |
| `custodian` | a Master Builder who is not the custodian's member | CU3, CU4 |

Notes:

- A witness cannot open a ballot. A dormant member can: dormancy blocks no act (section 5.2).
- The electorate is computed once, here. Nothing is ever added to it or removed from it. It holds the dormant members of its rung, who keep the vote; the quorum base counts the present ones (section 7.1).
- **A re-run** is the one way a lapsed ballot's subject is put again without its quorum: once, within 30 days, with at least 7 days to commit, any member who may open that kind opening it. It keeps every elector's vote and does not wait again for those who did not vote. A re-run timed for someone's absence gains nothing: the absent member is an elector of the re-run, and a no reveals the same.
- **Windows.** Every ballot but an amendment runs 7 days to commit and 3 to reveal. The opener of an amendment may state other windows within the ranges of B6: a text may need a longer reading, and nobody else is kept waiting by it but the path it names. No opener of any other kind sets how long a subject is held.
- **One subject, one opener, one season** (B7, B7a, B7b; the reasons are in section 5.4). B7 keeps one ballot of a kind on a subject; B7a keeps the opener of a sanction or witness ballot that failed or lapsed from holding that subject by opening on it again; B7b bounds the ballots one member holds open at all, amendments apart and removals never.
- A member whose key is frozen may open a ballot of kind `amendment` or `custodian` and no other, and during a halt only a ballot of those two kinds is opened (section 5.2).

The decision function is quoted once, from `ledger.decide`, and referred to by each kind:

```python
def decide(kind: str, yes: int, no: int, electorate: int) -> bool:
    if kind in ("admission", "advancement"):
        rule = "blackball"
    elif kind in ("amendment", "sanction", "witness"):
        rule = "two_thirds"
    elif kind == "custodian":
        rule = "majority"
    else:
        raise ValueError(f"unknown ballot kind {kind!r}")
    t = yes + no
    if not quorate(t, electorate):
        return False
    if rule == "blackball":
        # Rejected when black balls reach one fifth of the votes cast (5B >= T).
        return 5 * no < t
    if rule == "majority":
        # custodian: more yes than no among the votes cast; a tie fails.
        return yes > no
    # amendment / sanction / witness: two-thirds of votes cast, one-third turnout.
    return 3 * yes >= 2 * t and 3 * t >= electorate
```

**Closing in general.** At `ballot_close` (section 6.7) a ballot whose votes cast do not reach the quorum of its base, or a sanction on a Master Builder (a `reinstate` aside) with fewer than two votes cast, **lapses**: `result = lapsed`, it has no effect, and the rule of its kind is not consulted. Otherwise the votes give `ok = decide(kind, yes, no, N)`, with `N` the quorum base (`Ballot.quorum_base()`). Each kind then says, under "At close", when a ballot that is `ok` is **applied**. `result` is `passed` exactly when the ballot was `ok` and applied; in every other quorate case it is `failed`. A ballot that was won on the votes but can no longer be applied lawfully (the subject left, a name or key is now taken, the degree no longer fits, the custodian key is already gone) therefore closes as `failed`; it never blocks the close.

#### 6.4.1 Kind `admission`

| Aspect | Rule |
|---|---|
| Subject fields | `candidate` (string): the login of a live petition, exact. |
| Opening preconditions | **A1.** `candidate` has a live petition. Refusal: `no live petition`. **A2.** With `sponsors` = the logins of the petition's `vouches` (the inviter, then the vouchers), in order, for which `may_sponsor(login, now)` holds (section 7.5): `len(sponsors) ≥ sponsors_required(S, now, petition)` (section 7.5: one, in the Founding Phase, once the petition has been live 30 days). Refusal: `candidate lacks sponsors`. **A3.** `actor` is in `sponsors`. Refusal: `only a sponsor may open the candidate's admission ballot`. **A4.** `admissible(candidate, petition.key, petition.github_id, now)` (below). Refusal: `{candidate!r} collides with another name, key or GitHub account, or is a member again (one name, one key, one account, one role; logins are case-insensitive)`. |
| Electorate | The rung of degree 2 (section 7.1); if nobody of degree 2 or higher is present (not dormant and not silent, section 7.7), the rung of degree 1, whose voters hold every voter of degree 2 (the dormant and the silent among them keep the vote). |
| Frozen data | `frozen = {key: petition.key, vouches: sponsors, github_id: petition.github_id}`. An inviter or a voucher for whom `may_sponsor(login, now)` no longer holds (section 7.5: active, of the 3rd degree or standing in for a Master, section 6.34, and under no ban) is left out and never becomes a sponsor of record. |
| Decision rule | `decide("admission", yes, no, N)`: quorum, then `5 * no < t`. |
| At close | A ballot that **lapsed** changes nothing: the petition stays as it is, and a sponsor may open another ballot on it while it is live. Otherwise: **1.** `admit = ok and admissible(candidate, frozen.key, frozen.github_id, now)`, evaluated first. **2.** `S.petitions[candidate]` is removed, whatever the result. **3.** If not `admit`: nothing else; the candidate needs a new invitation to petition again. **4.** If `admit`: every exam `S.exams[(candidate, d)]` is removed, for every `d`; then, with `kept` = the old record under the same login **when its `github_id` equals `frozen.github_id`** (else none), and `serving` = `kept` exists, its `suspended_until` is set and `now < suspended_until`: `S.members[candidate]` is set to a **new** record: `Member(candidate, frozen.key, degree = 1, since = {1: now}, sponsors = frozen.vouches as a tuple, activity = [now], github_id = frozen.github_id, status = suspended and suspended_until = kept.suspended_until if serving, else status = active and suspended_until = null, founder, past_seats, sponsor_ban_until and fraud_history = those of kept, or false, 0, null and empty if there is none)`; every other field at its default. |

`admissible(cand, key, id, now)` (`ledger._admissible`) holds when all four do: `may_return(S.members.get(cand), now)` (P1: no record under `cand`, or a record that left and waited, 90 days for a departed or voided one and 365 for an expelled one); every pair of `name_holders(cand, now)` is `("member", cand)` or `("petition", cand)` (so a live invitation under any spelling of the name would make it fail; none can exist while the petition is reserved); every pair of `key_holders(key, now)` is one of the same two; every pair of `id_holders(id, now)` is one of the same two. The last condition cannot fail on its own: an invitation is refused while its account is held (I8), and the invitation and then its petition hold the account from then until the ballot closes. It is stated and evaluated all the same. The first condition asks the wait again, at the opening and at the close: a record expelled (for fraud or not) while the ballot is open, or before it, is admitted again only once its 365 days have passed, as an invitation would require (I5).

Notes: the new member is built from the frozen copy, not from the petition as it stands at close. A returning member starts again at the 1st degree: the record loses degree, `since`, `status_since`, `seat_until`, `last_work`, `last_rekey`, `left`, `missed` and `heard`, and the examinations of the earlier membership are gone, so every degree can be examined again. What follows the person and not the membership is kept: `founder`, `past_seats`, `sponsor_ban_until`, `fraud_history`, and a suspension that is still running (`suspended_until`, with `status = suspended`: leaving and returning does not end a suspension; one that has been served is not carried). **The person is the GitHub account, not the login.** A login that is admitted again under another `github_id` is another person: the new record inherits nothing, and the old record is replaced by it. **A founder who returns is still a founder:** the examiner rule of section 7.3 still applies to them, and they are never one of the seven Masters the Sunset counts (section 7.9). If the earlier record was reinstated to `active` while the admission ballot was open, the ballot fails (step 1) and the record is untouched.

#### 6.4.2 Kind `advancement`

| Aspect | Rule |
|---|---|
| Subject fields | `member` (string): a login, exact. `degree` (integer). |
| Opening preconditions | **D1.** `S.members[member]` exists and `is_active(now)`. Refusal: `no such member`. **D2.** `degree = member.degree + 1` and `degree ≤ 32`. Refusal: `advancement is one degree at a time, up to 32`. **D3.** `waited(member.since[member.degree], now, wait_days(degree))`, with the table pinned now. Refusal: `waiting period not complete`. **D4.** `S.exams[(member, degree)]` exists, `passed()` is true and `consumed` is false. Refusal: `examination not passed (each passed exam supports one advancement ballot)`. **D5.** `actor` is `member`, or is one of that exam's `examiners`. Refusal: `only the candidate, or an examiner of the passed examination, may open the advancement ballot`. |
| Opening effect | The exam's `consumed` becomes true. |
| Electorate | The rung of `degree` without the member (section 7.1); if fewer than 3 are present in it, the rung of degree 3 without the member, the voters of the first rung keeping the vote; if nobody is present in that one, the successors without the member (section 6.34), the voters of the earlier rungs (the dormant and the silent among them) keeping the vote. |
| Frozen data | `frozen = {admitted: membership of the member}` (section 4.2). |
| Decision rule | `decide("advancement", yes, no, N)`: quorum, then `5 * no < t`. |
| At close | Let `m = S.members[member]`, `same` = `m` exists and its membership equals `frozen.admitted`, and `ex = S.exams[(member, degree)]` if `same` (else none). A ballot that **lapsed**: if `ex` exists, its `consumed` becomes false (the exam is passed and free again, `ledger._release_exam`); nothing else. Otherwise: **1.** If not `ok`: if `ex` exists, its `ballot_failed` becomes true; `failed`. **2.** If `ok` but not (`same` and `m.is_active(now)` and `degree = m.degree + 1`): if `ex` exists, its `lapsed` becomes true; `failed`. **3.** Otherwise `m.degree = degree`; `m.since[degree] = now`; `passed`. |

Notes: the ballot is opened by the candidate or by one of the examiners of the passed examination (D5), the people who know the examination is done; nobody else opens a ballot about another member's degree. The exam state after a ballot is always consistent: when the ballot lapsed for want of a quorum, the exam is as it was before the ballot, and another ballot may be opened on it at once, with no retry wait; lost on the votes, the exam has **failed** and may be repeated once 90 days have passed since it opened (E6); won on the votes but not applicable, because the member departed, was expelled or is suspended at the close, the exam has **lapsed** and a new one may be opened at once, as soon as the member may act again (for example after a reinstatement). A ballot opened on an earlier membership of the login (`same` is false) changes nothing at all.

#### 6.4.3 Kind `amendment`

| Aspect | Rule |
|---|---|
| Subject fields | `path` (string): a path (`PATH_RE`). `new_sha256` (string): `HEX64`. |
| Opening preconditions | **M0.** The actor's `degree ≥ 3`. Refusal: `only Master Builders may open an amendment ballot`. **M1.** `path` matches `PATH_RE`. Refusal: `amendment path: letters, digits, _ . - and / only (or @protocol)`. **M2.** `fold(path)` does not start with `canon/eternal.toml`. Refusal: `eternal landmarks cannot be amended`. **M3.** `fold(path)` is not `ledger` and does not start with `ledger/`. Refusal: `the ledger cannot be pinned: no amendment governs a path under ledger/`. **M4.** No key `p` of `S.pins` has `p ≠ path` and `fold(p) = fold(path)`. Refusal: `amendment path {path!r} collides with the pinned path {p!r} (they differ only by case)`. **M5.** `new_sha256` matches `HEX64`. Refusal: `amendment must pin the new text's sha256 (64 lowercase hex)`. **M7a.** When `new_sha256 = ZERO_HASH` (the removal of a pin): `path` is a key of `S.pins` (refusal: `{path} is not pinned: there is no pin to remove (a new_sha256 of 64 zeros removes one)`), and `path` is not in `GENESIS_PINS` (refusal: `{path} is pinned by the genesis, and a genesis pin is never removed`); M6 is then not asked. **M6.** For `path = "canon/degrees.toml"` (exact): the degree table with digest `new_sha256` is available to the verifier and well formed (section 8.4). Refusals: `the new degree canon {first 12 characters}… is not archived: add canon/history/{new_sha256}.toml before opening this ballot (in an earlier pull request, or in the pull request that opens it)`; `the new degree canon {first 12 characters}… is malformed (33 degrees with exact fields): it can never be ratified`. |
| Electorate | The rung of degree 3 (section 7.1). |
| Frozen data | `frozen = {base: S.pins[path]}`, or `{base: ""}` for a path not pinned: the pin the amendment replaces. |
| Decision rule | `decide("amendment", yes, no, N)`: quorum, then `3 * yes >= 2 * t and 3 * t >= N`. |
| At close | If not `ok`: `failed`. Otherwise: **0.** If a key `p` of `S.pins` has `p ≠ path` and `fold(p) = fold(path)`: `failed` (M4 at the close: another spelling of the path was pinned since the opening). **0a.** If `S.pins[path]` (`""` for a path not pinned) is not `frozen.base`: `failed` (another text won first). **1.** If `path = "canon/degrees.toml"` and the table with digest `new_sha256` is not available and well formed: `failed`. (It was both at the opening, M6, and a verifier that lacks the file stopped there; this is a net, never a refusal of the close.) **2.** The Amendment `{ballot: id, path, new_sha256, time: now in the text form of section 2.5}` is absorbed by the history `amendments` (section 4.11), and `new_sha256` is appended to `S.degree_tables` when `path = "canon/degrees.toml"`. **2a.** If `path = "@protocol"`: `S.epoch` grows by 1. **2b.** If `new_sha256 = ZERO_HASH`: `path` is removed from `S.pins`, `S.prior_pins` and `S.prior_until`; `passed`. **3.** If `path` is already a key of `S.pins`: `S.prior_pins[path] = S.pins[path]` and `S.prior_until[path] = now + 30 d`. **4.** `S.pins[path] = new_sha256`; `passed`. |

Notes: a path is used exactly as written, and pins are matched case-sensitively. M2 and M3 are case-insensitive **prefix** tests: `canon/eternal.toml.bak`, `Canon/Eternal.toml` and `Ledger/entries/0000/000000.json` are refused. M4 keeps two pins from naming one file on a case-insensitive file system; the one-open-ballot rule (B7) compares paths case-insensitively, together with the text proposed: two amendments of one path with different texts may be open together (so nobody holds a path by opening a bogus text on it), and the first to pass changes the pin, so the other fails at its close (step 0). A second spelling of the same path with the same text cannot be opened while the first is open, and a path that differs only by case from a pinned path is refused by M4. Two spellings of one path that was not pinned, with different texts, may be open together, and the base check does not tell them apart (each froze `""`); so M4 is asked again at the close (step 0): the first to pass pins its spelling, and the other fails. Without it both would pass, and M4 would then refuse every later amendment of either spelling, freezing both pins for good. A passed amendment on a path that is not yet pinned makes it governed and records no prior pin. An amendment may re-pin a path to its current value. **The new degree table is archived before anyone votes on it** (M6): the table is read during replay from the entry that closes the ballot on, so its text must be in every verifier's tree by then; asked at the opening, the condition can never leave a passed ballot that no entry is able to close, and no close depends on when a clone received a file. Only Master Builders open an amendment ballot (M0): the legislative power is theirs. **A pin can be removed** (M7a, step 2b): a path a passed amendment made governed is governed no more once another amendment pins sixty-four zeros on it; the six genesis pins are never removed. The removal of `@protocol` is therefore impossible. The epoch moves by every passed amendment of `@protocol`, also one that re-pins it to its current digest (step 2a asks only the path). **Two readings** (Constitution Art. VII.3, procedural): an amendment that alters the decision function, the electorates, the sponsorship rules or Art. VII is first passed as a first reading, whose ballot pins `first-reading/` followed by the governed path (for the core, `first-reading/protocol.patch`, the patch that makes the change), never the governed path itself; the second ballot, at least 90 days later, pins the governed path to exactly the text the first reading ratified. The verifier does not tell a first reading from any other amendment: it pins whatever path a passed amendment names.

#### 6.4.4 Kind `sanction`

| Aspect | Rule |
|---|---|
| Subject fields | `member` (string): a login, exact. `measure` (string): one of `MEASURES`. |
| Opening preconditions | **SN1.** `measure` is in `MEASURES`. Refusal: `measure must be one of ['admonish', 'expel', 'expel_for_fraud', 'reinstate', 'suspend']`. **SN2.** `member` is a key of `S.members`, that record's status is not `departed`, and it is not `voided` unless `measure = expel_for_fraud`. Refusal: `no such member`. **SN2a.** For a `voided` record: `not waited(status_since, now, 90)` (`VOIDED_FRAUD_DAYS`, counted from the undo): the ballot is opened before 90 days have passed. Refusal: `the admission of {login} was undone 90 days ago or more (a voided record is expelled for fraud only by a ballot opened before 90 days have passed since the undo; from then on the login may be invited again)`. **SN3.** `standing(now)` of the member is in `SANCTION_ON[measure]` (below). Refusal: `{measure} applies only to a member who is {the allowed standings, sorted, joined by " or "}; {login} is {standing}`. **SN4.** `actor` is not `member`. Refusal: `a member cannot open a sanction ballot on themselves`. **SN5.** With `arbiters` = `active(now, 7, {member})` has three logins or more: the actor's `degree ≥ 7` when `arbiters`, else `degree ≥ 3`. Refusals: `only an Arbiter (7th degree or higher) may open a sanction ballot while three or more active Arbiters exist`; `only Master Builders may open a sanction ballot (an Arbiter where three or more active Arbiters exist)`. |
| Electorate | The rung of degree 7 without the member (section 7.1); if fewer than 3 are present in it, the rung of degree 3 without the member. |
| Frozen data | `frozen = {admitted: membership of the member}`, and `master: true` when the member's `degree ≥ 3` and `measure ≠ reinstate`. A sanction on a Master Builder is refused at opening when its electorate holds fewer than two members (B8a), and lapses at its close when fewer than two votes were cast (section 6.7). |
| Decision rule | `decide("sanction", yes, no, N)`: quorum, then `3 * yes >= 2 * t and 3 * t >= N`. |
| At close | Let `m = S.members[member]`. `failed` unless all hold: `ok`; `m` exists and its membership equals `frozen.admitted`; `m.standing(now)` is in `SANCTION_ON[measure]` (for a `voided` record the 90 days of SN2a are asked at the opening only). Otherwise `passed`, with: **`admonish`:** nothing changes. **`suspend`:** `m.status = suspended`; `m.suspended_until = now + 365 d`; `m.status_since = now`. **`reinstate`:** `m.status = active`; `m.suspended_until = null`; `m.status_since = now`. **`expel`, `expel_for_fraud`:** `m.status = expelled`; `m.seat_until = null`; `m.suspended_until = null`; `m.status_since = now`. **`expel_for_fraud` only:** `now` is appended to `m.fraud_history`; and if `not expired(m.since[1], now, 730)`, every login in `m.sponsors` that is a key of `S.members` gets `sponsor_ban_until = now + 730 d`. |

`SANCTION_ON`, by the member's `standing(now)` (a suspension that has been served counts as `active`):

| Measure | `active` | `suspended` | `expelled` | `departed` | `voided` |
|---|:-:|:-:|:-:|:-:|:-:|
| `admonish` | yes | yes | yes | no | no |
| `suspend` | yes | no | no | no | no |
| `expel` | yes | yes | no | no | no |
| `expel_for_fraud` | yes | yes | no | no | yes, by a ballot opened before 90 days have passed since the undo |
| `reinstate` | no | yes | yes | no | no |

(In the code `SANCTION_ON["expel"]` and `SANCTION_ON["expel_for_fraud"]` differ only by `voided`; SN2 keeps every other measure from a voided record before SN3 is reached.)

**A voided record and fraud.** An admission undone by a correction leaves no finding of fraud (section 6.19.8). Where there was fraud, the members may still find it: for 90 days after the undo, a ballot with the measure `expel_for_fraud`, and that measure alone, may be opened on the `voided` record. If it passes, the record becomes `expelled` with all the consequences of that measure: `status_since = now` (so the login waits 365 days and not 90), `now` in `fraud_history`, and the ban of the sponsors when the admission was within 730 days. `REJOIN_AFTER_DAYS` and `VOIDED_FRAUD_DAYS` are both 90 days from the undo, and the two windows never overlap: before the 90 days have passed only the ballot can be opened (SN2a), and from that second on only the return holds (`waited`, P1 and I5). An invitation is also refused while a sanction ballot on the login is open (I5), so the login cannot be invited again while such a ballot is open or may still be opened.

Notes: the precondition is checked when the ballot opens and again when it closes, so a member who departs, or whose admission is undone, while the ballot is open is out of its reach, and a repeated `expel` is refused at opening and never restarts the 365 days of I5 and P1. `suspend` does not touch `seat_until`: the seat stays held (section 4.7). **The subject of a sanction ballot is the member and the measure** (section 4.4): at most one ballot per member and measure is open, and ballots on different measures of one member may be open together, each judged by its own precondition at its close. So no ballot on a light measure holds the place of a grave one. The accused never opens a ballot on themselves (SN4), and the opener is of the degree the electorate is drawn from (SN5): an Arbiter where three or more exist besides the accused, a Master Builder otherwise. **No sanction on a Master Builder, a `reinstate` aside, is decided by a single elector** (B8a): of two Masters, neither can sanction the other, and a quorum of one, when the others are dormant, does not decide one either.

#### 6.4.5 Kind `witness`

| Aspect | Rule |
|---|---|
| Subject fields | `action` (string): `add` or `remove`. `name` (string): a login. `key` (string): a key, and `proof` (string): a signature by that key over the witness message of section 6.1, `ledger.witness_message(name, key)`; both present exactly when `action = add`. |
| Opening preconditions | **W0.** The actor's `degree ≥ 3`. Refusal: `only Master Builders may open a witness ballot`. **W1.** `action` is `add` or `remove`, and `name` matches `LOGIN_RE`. Refusal: `witness ballot needs action and a valid name`. **W2.** `key` and `proof` are both present if `action = add`, and both absent otherwise. Refusal: `a witness subject has action, name, key and proof to add a witness, and action and name only to remove one`. **W3.** For `remove`: `name` is a key of `S.witnesses` (exact). Refusal: `no such witness`. **W4.** For `add`: `name_holders(name, now)` is empty. Refusal: `a new witness name cannot equal a member login, a witness, a custodian, an invited login, a pending petition, the name of an open witness ballot, or the name of a pending claim of the Custodian office (case-insensitive)`. **W5.** For `add`: `key` is a valid key (section 2.6), of either type. Refusal: `keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)`. **W6.** For `add`: `key_holders(key, now)` is empty. Refusal: `this key is already used by {owner} (one key per login)`. **W7.** For `add`: `sig_ok(witness_message(name, key), proof, name, key)`. Refusal: `bad witness proof: the proposed key must sign the witness message (name, key)`. |
| Opening effect | For `add`: the point of `key` is added to `S.known_keys`. The key proved possession (W7): nobody registers, and so bars from every later `rekey`, a key they do not hold. |
| Electorate | The rung of degree 3 (section 7.1). |
| Frozen data | None. The subject itself carries the name and key, and the open ballot holds both (section 4.7). |
| Decision rule | `decide("witness", yes, no, N)`: quorum, then `3 * yes >= 2 * t and 3 * t >= N`. |
| At close | If not `ok`: `failed`. **`remove`:** if `name` is a key of `S.witnesses`, it is removed and the ballot `passed`; otherwise `failed`. **`add`:** if `name_holders(name, now)` or `key_holders(key, now)` holds any pair other than this ballot's own `("ballot", name)`: `failed`. Otherwise `S.witnesses[name] = key`; `passed`. |

#### 6.4.6 Kind `custodian`

The one decision a ballot takes about a custodian is to **remove its key**. No ballot and no lot appoints a custodian or replaces one; the one entry that names one after the genesis is a founder's claim (sections 4.8 and 6.31), and a founder against whose custodian key this ballot passed never claims again (CL6).

| Aspect | Rule |
|---|---|
| Subject fields | `remove` (string): the name of a custodian, exact. Nothing else: B4 refuses any other key with `custodian subject has exactly the keys ['remove']`. |
| Windows | Fixed: 7 days to commit and 3 to reveal. The opener cannot choose them (B6a). |
| Opening preconditions | **CU1.** `remove` is a key of `S.custodians`. Refusal: `no such custodian`. **CU2.** That custodian's key is live at `now`. Refusal: `the custodian key of {remove} is already {status}`, with `status` = `lapsed`, `revoked` or `removed`. **CU3.** The actor's `degree ≥ 3`. Refusal: `only Master Builders may open the ballot that removes a custodian`. **CU4.** `actor` is not the same login as the custodian's `member`. Refusal: `{actor} is the member of the custodian {remove} and cannot open the ballot that removes it`. |
| Electorate | The rung of degree 3 without the custodian's member (section 7.1): the Master Builders, never the member the custodian is linked to. |
| Frozen data | None. |
| Decision rule | `decide("custodian", yes, no, N)`: the usual quorum over that electorate, then `yes > no`. A simple majority of the votes cast; a tie fails. |
| At close | `failed` unless `ok` and the custodian's key is live at `now`. Otherwise `revoked = now` and `removed = id` on the custodian's record; `passed`. |
| What no correction can do to it | It is never stayed (SY2), voided (VB2) or undone (UB2). Its windows run on **wall time**: `pauses(id)` is empty for a ballot of this kind, so neither a halt nor anything else stops its clock (section 7.8). |
| Who may still act in it | Every entry of the ballot (`ballot_open`, `ballot_commit`, `ballot_reveal`, `ballot_close`) is accepted while the ledger is halted, and from a member whose key is frozen (section 5.2); the same holds for an amendment ballot. A witness may close either during a halt, and `ledger.due_actions` lists that close as due. Neither is counted by C12a or B7a; a `custodian` ballot is not counted by B7b either, while amendment ballots have their own count of three (B7b). |

Notes: a passed removal has exactly the effects of a `custodian_revoke` (section 6.23): from the next entry on the key signs nothing, every immediate act it had in force ends at `now`, and every noticed act it posted and that was still pending can never be applied (`ended`, section 6.19.9). The record's status reads `removed`. At most one removal ballot per custodian is open at a time (B7; the subject key is `fold(remove)`). Where the member the custodian is linked to is the only active Master Builder, nobody can open the ballot (CU3, CU4), and its electorate would be empty (B8): until other Masters exist, a custodian is checked by publicity and by the right to fork. A removal that is `ok` at its close after the key already lapsed or was revoked closes as `failed`, and changes nothing.

### 6.5 `ballot_commit`

**Signer:** an active member. **Function:** `ledger._ballot_commit`.

| Body field | Type | Constraint |
|---|---|---|
| `id` | string, required | The id of an open ballot. |
| `commitment` | string, required | `HEX64`. |

| # | Precondition | Refusal message |
|---|---|---|
| K1 | `S.ballots[id]` exists and is open. | `no open ballot` |
| K1a | The ballot is not stayed at `now` (section 6.19.3). | `ballot {id} is stayed until {end} (correction {seq})` |
| K1b | No `void_ballot` of this ballot is pending at `now` (`void_pending(id, now)`, section 6.19.7). | `ballot {id} is paused while the correction that would void it is pending (correction {seq}, until {apply_end} at the latest)` |
| K2 | `actor` is in the ballot's `electors`. | `not an elector` |
| K3 | `ballot_time(b, now) ≤ commit_until` (section 7.8). | `commit window closed` |
| K4 | `actor` is not a key of `commits`. | `already committed` |
| K5 | `commitment` matches `HEX64`. | `commitment is 64 lowercase hex` |

Effects:

1. `commits[actor] = commitment`. A commitment is not an answer (section 7.7): only the reveal is.

Notes: the commitment is `H(id ‖ "|" ‖ login ‖ "|" ‖ vote ‖ "|" ‖ salt)` over the joined string (`ledger.commitment`); it is not checked until the reveal. The four parts cannot contain `|` (a ballot id, a login, `yes` or `no`, and a hexadecimal salt), so the joined string has one reading. Vector: `commitment("b1", "alice", "yes", "0123456789abcdef0123456789abcdef") = db3a976241672ea1d4581472900adcccb3a719f7f837fc6c774fac0148a13b65`. A commitment may be posted from the time of the opening entry itself. **Signer:** an active member; a member whose key is frozen commits like any other elector (section 6.19.1).

### 6.6 `ballot_reveal`

**Signer:** an active member; or a `voided` record that holds a commitment in the ballot (section 5.2). **Function:** `ledger._ballot_reveal`.

| Body field | Type | Constraint |
|---|---|---|
| `id` | string, required | The id of an open ballot. |
| `vote` | string, required | `yes` or `no`. |
| `salt` | string, required | `SALT_RE`: 32 to 64 lowercase hexadecimal characters. |

| # | Precondition | Refusal message |
|---|---|---|
| R1 | `S.ballots[id]` exists and is open. | `no open ballot` |
| R1a | The ballot is not stayed at `now`. | `ballot {id} is stayed until {end} (correction {seq})` |
| R1b | No `void_ballot` of this ballot is pending at `now`. | `ballot {id} is paused while the correction that would void it is pending (correction {seq}, until {apply_end} at the latest)` |
| R2 | `commit_until + REVEAL_GAP ≤ ballot_time(b, now) ≤ reveal_until` (section 7.8). | `not in the reveal window ({opens} to {closes}, both included)`: `ballot_due(b, commit_until + REVEAL_GAP)` and `ballot_due(b, reveal_until)`, the wall times at which the ballot's clock reaches the two bounds as the pauses stand (the stored values themselves for a ballot never paused), in the text form of section 2.5 |
| R3 | `vote` is `yes` or `no`, and `salt` matches `SALT_RE`. | `vote must be yes or no, salt 32..64 lowercase hex characters` |
| R4 | `actor` is not a key of `reveals`. | `already revealed` |
| R5 | `commits[actor]` exists and equals `commitment(id, actor, vote, salt)`. | `reveal does not match commitment` |

Effects:

1. `reveals[actor] = vote`.
2. **Heard** (section 7.7): if the calls of `S.members[actor]` are recorded (`degree ≥ 3`, or any degree while `succession_status(now) = in_force`), its `heard = now`.

Notes: **the reveal window is closed at both ends**: it holds its first second, `commit_until + REVEAL_GAP` on the ballot's clock, and its last, `reveal_until`. Each elector reveals once (R4); a second reveal, identical or not, is refused. An elector who did not commit fails R5. The gap between the last possible commitment and the first reveal is `REVEAL_GAP` of wall time or more whatever was paused, because the ballot's clock never runs faster than the wall. A record whose admission was undone after it committed still reveals (section 5.2): the vote was cast, and no correction changes a vote.

### 6.7 `ballot_close`

**Signer:** a witness (with the witness key), or an active member. **Function:** `ledger._ballot_close`, with one closing function per kind (`ledger.CLOSERS`).

| Body field | Type | Constraint |
|---|---|---|
| `id` | string, required | The id of an open ballot. |

| # | Precondition | Refusal message |
|---|---|---|
| X1 | `S.ballots[id]` exists and is open. | `no open ballot` |
| X1a | The ballot is not stayed at `now`. | `ballot {id} is stayed until {end} (correction {seq})` |
| X1b | No `void_ballot` of this ballot is pending at `now` (`void_pending(id, now)`, section 6.19.7). | `ballot {id} is paused while the correction that would void it is pending (correction {seq}, until {apply_end} at the latest)` |
| X2 | The ballot is **closable** (`ledger.closable`): `ballot_time(b, now) > reveal_until` (section 7.8), **or** every elector has revealed (`len(reveals) = len(electors)`). | `ballot still open` |

Effects:

1. `yes` = number of `yes` values in `reveals`; `no` = number of `no` values; `N = quorum_base()` (section 4.4: the electors present at the opening, less the non-responders of a re-run). Every revealed vote is counted, whatever became of the elector since, a dormant elector's included.
2. `closed = now`.
2a. If the ballot gave at least 7 days to commit (`ledger.full_call`: `commit_until − opened ≥ 7 d`), every login of `electors` is **called** at `now` (section 7.7), answered exactly when it is a key of `reveals`: whatever the result, a lapsed ballot included. A ballot with a shorter commit window calls nobody.
3. **Lapse.** If the votes do not reach the quorum (`not quorate(yes + no, N)`, section 7.1), **or** `frozen.master` is true and `yes + no < 2` (a sanction on a Master Builder is never decided by a single vote): `result = lapsed`; for an advancement ballot the exam is released (section 6.4.2); nothing else changes, and the effects end here. A lapsed ballot that gave at least 7 days to commit may be re-run once (B2a, B2g).
4. `ok = decide(kind, yes, no, N)`.
5. `before` = the facts of the ballot (below), as they stand.
6. The kind's "At close" rule (sections 6.4.1 to 6.4.6) is applied; `result` becomes `passed` or `failed` as it says.
7. If `result = passed` and `before` is not empty: `undo = {field: [before[field], after[field]]}` for every field of `before`, with `after` the same facts as they now stand.

**The facts of a ballot** (`ledger._facts`) are the stored values a passed ballot of its kind sets, read from the state at a given moment. They are the whole of what an `undo_ballot` compares and puts back (section 6.19.8):

| Kind | Field | Value |
|---|---|---|
| `admission` | `member.admitted` | The membership of `S.members[candidate]` (the text form of `since[1]`, section 4.2); `""` when there is no record. |
| | `member.status` | That record's `status`; `""` when there is none. |
| | `member.degree` | That record's `degree`; 0 when there is none. |
| `advancement` | `member.degree` | The `degree` of `S.members[member]`; 0 when there is no record. |
| | `member.since` | The text form of that record's `since[degree]`, with `degree` the degree of the subject; `""` when the record has no such date. |
| every other ballot | | none: the facts are empty, and so is `undo`. |

Vector: an admission of `alice`, who had no earlier record, closed as passed at `2027-01-11T07:55:12Z` has `undo = {"member.admitted": ["", "2027-01-11T07:55:12Z"], "member.status": ["", "active"], "member.degree": [0, 1]}`. An advancement of a member from the 1st to the 2nd degree closed at time `T` has `undo = {"member.degree": [1, 2], "member.since": ["", T]}`.

Notes:

- Commitments never revealed count for nothing.
- **A ballot that misses the quorum lapses.** It decides nothing and penalizes nobody: a petition stays as it is, an exam is passed and free again, and nothing is recorded against the subject. A ballot that is quorate is decided, and a decided ballot that does not pass has `failed`, with the consequences of its kind. So an elector who is absent cannot cost a candidate a refusal and a wait; with three present electors or fewer the quorum is all of them (section 7.1). An absence that keeps a ballot from its quorum blocks it once: the re-run does not wait for those who did not vote (B9).
- **Early close.** A ballot may be closed as soon as every elector has revealed: nothing can change its votes any more (a reveal is given once, and the electorate is fixed). A ballot in which one elector stays silent runs to the end of its reveal window.
- A close is refused while the ledger is halted for every ballot but an amendment and one that removes a custodian (section 5.2), for a stayed ballot while its stay is in force (X1a), and for a ballot under a pending `void_ballot` (X1b). The halted, the stayed and the pending time are out of the ballot's clock, so the reveal window is as long after a pause as before it.
- **No close is refused for a reason of the ballot's content.** Every ballot whose reveal window has ended, or whose electors have all revealed, can be closed, and closes as `passed`, `failed` or `lapsed`. (The new text of an amendment of `canon/degrees.toml` is asked for when the ballot opens, M6.)
- A ballot that nobody closes stays open, keeps blocking another ballot on the same subject (B7) and keeps one of its opener's three places (B7b; a ballot of kind `custodian` holds none); a witness closes closable ballots as a matter of course (`ledger.due_actions`, which lists no ballot that is stayed or under a pending `void_ballot`, and while the ledger is halted lists no lot and no close but that of an amendment or of a ballot of kind `custodian`), and any active member may.

### 6.8 `exam_open`

**Signer:** an active member, who must be the candidate. **Function:** `ledger._exam_open`.

| Body field | Type | Constraint |
|---|---|---|
| `candidate` | string, required | The actor's own login. |
| `degree` | integer, required | The candidate's degree + 1, at most 32. |
| `work_ref` | string, required | A URL (`URL_RE`). |
| `beacon_round` | integer, required | Equal to `drand_round(now) + 9600` (section 7.4), and positive. |

| # | Precondition | Refusal message |
|---|---|---|
| E1 | `S.members[candidate]` exists and `is_active(now)`. | `no such candidate` |
| E2 | `actor` equals the candidate's login. | `only the candidate may open their own examination` |
| E3 | `degree = candidate.degree + 1` and `degree ≤ 32`. | `exams are for the next degree, up to 32` |
| E4 | `waited(candidate.since[candidate.degree], now, wait_days(degree))`. | `waiting period not complete` |
| E5 | `work_ref` matches `URL_RE`. | `work_ref must be an http(s) URL without spaces or quotes` |
| E6 | If `S.exams[(candidate, degree)]` exists: it has `ended(now)` (lapsed, or timed out: section 4.5), **or** it has `failed(now)` and `waited(its opened, now, 90)` on the **effective clock** (section 7.8). | `an exam for this degree exists; retry only after a failure and 90 days (an exam that lapsed or timed out is opened again at once)` |
| E7 | With `rnd = drand_round(now) + 9600`: `rnd > 0` and `beacon_round = rnd`. | `beacon_round must be {rnd} (now + 9600 rounds), a positive integer` |
| E8 | With `k = examiners(degree)`, `skip` = `silent(now)` of the exam of E6, together with that exam's `skipped` when it has `ended(now)` (none when there is no such exam), `wide` = that exam has `timed_out(now)` (its lot drawn or not; false when there is no such exam), and `pool = examiner_pool(S, candidate, degree, now, skip, wide)` (section 7.3): `len(pool) ≥ k`, **or** `pool` is not empty (the lowered lot, the union of the rungs, lowers the number, in any phase). | `{k} examiners required, only {len(pool)} available` |
| E9 | After E8's adjustment, `k ≥ 1`. | `an examination needs at least one examiner` |

Effects:

1. If `len(pool) < k` (E8's second branch), `k` becomes `len(pool)`. If `wide` (the exam of E6 timed out), `k` becomes `len(pool)` in any case: **after a timeout the lot seats everyone the pool holds**, and never fewer than `examiners(degree)` while a rung seats that many.
1a. If the exam of E6 has `timed_out(now)` and its `examiners` is not empty, each of its examiners is **called** (section 7.7), with the end `due(opened, 60 d) + 1 s` of that exam and answered exactly when it is a key of its `reports`. This comes after the pool was computed: a Master Builder whom this call makes silent still stands in this pool, unless `skip` leaves them out, and is left out of LR2 and LR3 from then on.
2. `S.exams[(candidate, degree)] = Exam(candidate, degree, examiners = null, beacon_round, opened = now, reports = {}, pool, work_ref, ranking = (), recused = (), k, consumed = false, ballot_failed = false, lapsed = false, skipped)`, with **E8a** `skipped` = the logins of `skip` that are not in `pool`, in ascending order, or empty when `pool` holds a login of `skip` (the pool was computed again without `skip`: it left nobody out, and one carried without being called would never fall silent). An earlier exam under the same key is replaced.

Notes: the pool and `k` are frozen here, before the beacon exists. E9 cannot fail with a table that passed section 8.4; it states that no exam is ever opened with zero examiners. A lapsed or timed-out exam is replaced at once, with no wait (E6). **Non-responders never block**: an examiner who never reports makes the exam time out, with no penalty for the candidate, and is left out of the next lot whenever anyone else can be drawn, which then seats everyone any rung holds, so that every member who never answers is called and falls silent; and where no rung of the ladder holds as many members as the degree asks for, the lot draws everyone any rung holds and the number of examiners is lowered to them, so the 32nd degree is reached at exactly seven Masters (six examiners).

### 6.9 `exam_draw`

**Signer:** a witness (with the witness key), or an active member. **Function:** `ledger._exam_draw`.

| Body field | Type | Constraint |
|---|---|---|
| `candidate` | string, required | |
| `degree` | integer, required | |
| `beacon` | string, required | `HEX64`: the randomness of round `beacon_round`. |

| # | Precondition | Refusal message |
|---|---|---|
| F1 | `S.exams[(candidate, degree)]` exists, its `examiners` is null and it has not `lapsed`. | `no exam awaiting its draw` |
| F2 | Not `expired(now)` (effective clock, section 4.5). | `the exam has expired` |
| F3 | `now ≥ drand_time(beacon_round)` (section 7.4). | `the beacon round has not happened yet` |
| F3a | Not `draw_lapsed(now)` (section 4.5): the draw is made within 7 days of the beacon round, on the effective clock. | `the lot of this exam was not drawn within 7 days of its beacon round ({drand_time(beacon_round)}): the exam lapsed with no penalty, and a new one may be opened` |
| F4 | `beacon` matches `HEX64`. | `beacon is the round's 32-byte randomness in lowercase hex` |

Effects:

1. `ranking = draw(pool, len(pool), beacon, "exam:{candidate}:{degree}:{beacon_round}")` (section 7.4), using the exam's stored `candidate`, `degree` (in decimal) and `beacon_round`.
2. `examiners` = the first `k` elements of `ranking`.
3. The Beacon `{round: beacon_round, beacon}` is absorbed by the history `beacons` (section 4.11).
4. **Frozen examiners stand aside.** For each of those first `k` logins, in order, whose key is frozen at `now` (`key_frozen(x, now)`, section 4.7: a freeze in force, or a recovery under way), unless the exam has `lapsed` meanwhile: effects 1 to 4 of an `exam_recuse` by that login are applied (section 6.11).

Notes: replay does not check that `beacon` is the true randomness of the round; that is the gate of section 9.4. The draw is accepted from the round's time until 7 days after it, on the effective clock, and never after the exam expired. **A lot that cannot be drawn lapses**: if the beacon is unavailable for good (drand retired, or every relay down), the gate refuses every draw (section 9.4), and after 7 days the exam has timed out without penalty; the candidate opens a new one at once, with a new round. The deterministic condition is F3a: no `exam_draw` within `LOT_DRAW_DAYS` of `drand_time(beacon_round)`. The members of the pool are not re-checked at the draw.

### 6.10 `exam_report`

**Signer:** an active member who is a drawn examiner. **Function:** `ledger._exam_report`.

| Body field | Type | Constraint |
|---|---|---|
| `candidate` | string, required | |
| `degree` | integer, required | |
| `verdict` | string, required | `pass` or `fail`. |
| `reason` | string, optional | A URL (`URL_RE`). |

| # | Precondition | Refusal message |
|---|---|---|
| T1 | `S.exams[(candidate, degree)]` exists. | `no such exam` |
| T2 | The exam has not `lapsed`. | `the exam has lapsed` |
| T3 | `examiners` is not null, `actor` is in `examiners`, and `actor` is not a key of `reports`. | `not a drawn examiner, or already reported` |
| T4 | `verdict` is `pass` or `fail`. | `verdict is pass or fail` |
| T5 | `reason` is absent, or matches `URL_RE`. | `reason must be the http(s) URL of the published, reasoned verdict` |
| T6 | Not `expired(now)` (effective clock). | `the exam has expired` |

Effects:

1. `reports[actor] = verdict`.
2. **Heard** (section 7.7): if the calls of `S.members[actor]` are recorded (`degree ≥ 3`, or any degree while `succession_status(now) = in_force`), its `heard = now`.
3. If the exam was neither `passed()` nor under the fail rule before step 1, and is one of them after it (this report decided it): every login of `examiners` is **called** at `now` (section 7.7), answered exactly when it is a key of `reports`.

Notes: a report is accepted after the exam has already passed or failed on the verdicts, and after an advancement ballot has consumed it, until the exam expires; it cannot change the outcome (section 4.5). `reason` is validated and then not stored.

### 6.11 `exam_recuse`

**Signer:** an active member who is a drawn examiner. **Function:** `ledger._exam_recuse`.

| Body field | Type | Constraint |
|---|---|---|
| `candidate` | string, required | |
| `degree` | integer, required | |

| # | Precondition | Refusal message |
|---|---|---|
| U1 | `S.exams[(candidate, degree)]` exists, its `examiners` is not null and it has not `lapsed`. | `no drawn exam` |
| U2 | `actor` is in `examiners` and is not a key of `reports`. | `only a drawn examiner who has not reported may recuse` |
| U3 | Not `expired(now)` (effective clock). | `the exam has expired` |
| U4 | The exam is undecided: not `consumed`, not `passed()` and not `failed(now)`. | `the exam is already decided` |

Effects:

1. `actor` is appended to `recused`.
2. `next` = the first login `x` of `ranking`, in order, such that `x` is not in `examiners` (as it stood before this entry), `x` is not in `recused` (after step 1), `x` is a key of `S.members`, that member `is_active(now)` and is not `dormant(now)`, and the key of `x` is not frozen at `now` (`key_frozen(x, now)`, section 4.7). There may be none.
3. `examiners` = `examiners` without `actor`, in the same order, followed by `next` if there is one.
4. If there is no `next`, `lapsed` becomes true, and every login left in `examiners` is **called** at `now` (section 7.7), answered exactly when it is a key of `reports`.

Notes: an exam never goes on with fewer examiners than `k`. When nobody is left in the lot's order to replace a recused examiner, the exam **lapses**: it ends without a verdict and without penalty, no further report or recusal is accepted, and the candidate may open a new exam at once (E6), which freezes a new pool. U4 keeps a recusal from undoing an exam that already has its verdict. The four effects are also applied, without an `exam_recuse` entry, to an examiner whose key is frozen: at the `correction` that freezes it (section 6.19.1) and at an `exam_draw` that would seat it (section 6.9); and to an examiner whose admission is undone, at the `correction_apply` that undoes it (section 6.19.8). An examiner who is frozen, or who is no longer a member, cannot report, so the seat passes on exactly as if they had stepped aside.

### 6.12 `council_call`

**Signer:** an active member. **Function:** `ledger._council_call`.

| Body field | Type | Constraint |
|---|---|---|
| `beacon_round` | integer, required | Equal to `drand_round(now) + 9600`, and positive. |

| # | Precondition | Refusal message |
|---|---|---|
| L1 | `S.council_call` is null, or the pending call has lapsed (`ledger.council_lapsed`: `expired(drand_time(S.council_call), now, 7)` on the effective clock). | `a council draw is already pending` |
| L2 | `len(seats(now)) < 33`. | `no vacancies` |
| L3 | With `rnd = drand_round(now) + 9600`: `rnd > 0` and `beacon_round = rnd`. | `beacon_round must be {rnd}, a positive integer` |
| L4 | The pool is not empty. | `no eligible 32nd-degree members` |

The **pool** (`ledger._council_pool`) is the list, in ascending login order, of the logins `l` in `active(now, 32, seats(now))` with `degree = 32` exactly, `waited(since[32], now, wait_days(33))` and `past_seats = 0`.

Effects:

1. `S.council_call = rnd`; `S.council_pool = pool`.

### 6.13 `council_draw`

**Signer:** a witness (with the witness key), or an active member. **Function:** `ledger._council_draw`.

| Body field | Type | Constraint |
|---|---|---|
| `beacon` | string, required | `HEX64`: the randomness of round `S.council_call`. |

| # | Precondition | Refusal message |
|---|---|---|
| Y1 | `S.council_call` is not null and `now ≥ drand_time(S.council_call)`. | `no council call whose beacon round has passed` |
| Y1a | The pending call has not lapsed (L1). | `the council call was not drawn within 7 days of its beacon round ({drand_time(rnd)}): it lapsed, and a new call may be made` |
| Y2 | `beacon` matches `HEX64`. | `beacon is 32-byte lowercase hex` |

Effects, with `rnd` the pending round:

1. `vacancies = 33 − len(seats(now))`. It is never negative (section 10, invariant 28).
2. `ranking = draw(S.council_pool, len(S.council_pool), beacon, "council:{rnd}")`: the whole frozen pool in lot order (section 7.4).
3. The logins of `ranking` are taken one by one, in order. A login is **seated** when fewer than `vacancies` logins have been seated so far **and** its member exists, `is_active(now)`, is not `dormant(now)`, has `degree = 32` and has `past_seats = 0`. A login that fails the test is skipped, and the next one in the order is considered.
4. `S.council_call = null`; `S.council_pool = ()`.
5. The Beacon `{round: rnd, beacon}` is absorbed by the history `beacons` (section 4.11).
6. For each seated member: `degree = 33`; `since[33] = now`; `seat_until = now + 1095 d`; `past_seats` increases by 1.

Notes: a call that lapsed is replaced by the next `council_call`, which freezes a new pool; nothing else of it remains. The pool is frozen at the call and every name is judged again at the draw, so a member who left, was suspended, went dormant or changed since the call is passed over deterministically, and the seat goes to the next name in the lot's order. If the order is exhausted first, the remaining seats stay vacant for a later call. A member keeps degree 33 after the seat ends.

### 6.14 `work`

**Signer:** an active member. **Function:** `ledger._work`.

| Body field | Type | Constraint |
|---|---|---|
| `ref` | string, required | A URL (`URL_RE`). |
| `kind` | string, optional | `WORK_KIND_RE`: a short label such as `essay` or `code`. |

| # | Precondition | Refusal message |
|---|---|---|
| O1 | `ref` matches `URL_RE`. | `work needs an http(s) URL (PR, commit or document) without spaces or quotes` |
| O2 | `kind` is absent, or matches `WORK_KIND_RE`. | `work kind: 1..32 of a-z 0-9 _ - starting with a letter or digit` |
| O3 | The actor's `last_work` is null, or `now − last_work ≥ 24 h`. | `one work entry per member per 24 hours` |

Effects:

1. The actor's `last_work = now`. (And the activity of section 5.3.)

Notes: `kind` is validated and not stored. O3 and the one-point-per-day rule of section 5.3 bound what a member can add to the ledger and to their own Light by repetition.

### 6.15 `depart`

**Signer:** a member whose status is not in `GONE` (`departed`, `expelled`, `voided`; section 5.2); a suspended member included. **Function:** `ledger._depart`.

Body: the empty object `{}`. Any field is refused (C10).

Preconditions: none beyond the signer rule.

Effects:

0. With `r = S.recoveries[actor]`, if it exists, has the member's membership as `admitted`, has `applied` null, and either is alive at `now` (`requested`, `pending` or `ready`) or has `not expired(t, now, 90)` (`RECOVER_INTERVAL_DAYS`) for `t` the latest of its `time`, `objected` and `void` that are set: `r.departure = now`. That recovery is **asked in time** for this departure (RR3a).
1. `left = {status, status_since, seat_until}`, the three values of the record as they stand before this entry, the two times in the text form of section 2.5 and left out when null. Every departure records them.
2. `S.members[actor].status = departed`; `seat_until = null`; `status_since = now`.

Notes:

- **Leaving is always possible** (Landmark VII). A member whose key is frozen may sign `depart`, it is accepted while the ledger is halted (section 5.2, rule 5), and it is never counted against the entries of a day (section 5.4): no correction and no limit can keep anyone in. `depart` adds no activity (section 5.3). The record keeps its degree, key and history, and its GitHub account stays held by it (section 4.7); it changes again only if the login is admitted anew (section 6.4.1), or if a recovery reverses the departure (below).
- **A departure may be signed by a key in other hands.** The ledger cannot tell the member from whoever else holds the key, frozen or not. A `depart` takes effect at once, like any other: from this entry on the record is `departed`. It is **reversed** if a recovery of that key is completed (section 6.29, effect 4): the recovery that was alive at the departure, which goes on; one asked within `DEPART_RECOVER_DAYS` = 30 days of the departure; or one that **follows** a recovery asked in time for this departure (`Recovery.departure`, effect 0 and RR3a), whatever ended that one (it expired, the old key stopped it, the Masters opposed it, its freeze was withdrawn), when it is asked within `DEPART_FOLLOW_DAYS` = 150 days of that one's request, or of the old key's stop of it when that came later. A recovery is asked in time for the departure when it is asked after it within the 30 days, or when, at the departure, it is the latest recovery of the membership, was not applied, and is alive or was asked, stopped or voided at most 90 days before, or when it follows, as above, a recovery asked in time for it (every request for a departed record carries the departure, so one follow-up may follow another). The person who then holds the membership, with the new key, may depart again at once, and that departure is reversed only by the same rule. If no such recovery completes, the departure stands; with no recovery asked in time, or once the last one asked in time ended more than 150 days ago, it is final. An old recovery never reverses a departure long after it: one whose request, stop by the old key or voiding, whichever is latest, came more than 90 days before the departure is not in time for it.
- A suspension is not ended by leaving: `suspended_until` stays in the record, and if the same GitHub account is admitted again while it is still running, the new membership starts suspended until then (section 6.4.1).

### 6.16 `witness`

**Signer:** a witness, with the witness key. A member cannot sign this type. **Function:** `ledger._witness`.

A checkpoint **covers every entry before it**: it names the entry just before itself, the hash of that entry, and the digest of the state that entry left, which is the state this entry is applied to.

| Body field | Type | Constraint |
|---|---|---|
| `upto_seq` | integer, required | The `seq` of this entry, minus 1. |
| `head` | string, required | The entry hash of entry `upto_seq`: `S.head`. |
| `state_sha256` | string, required | The state digest (section 4.11) of `S`, the state after entry `upto_seq`. |
| `state_version` | integer, required | The version of the state document whose digest `state_sha256` is: `STATE_VERSION` = 2. |
| `root` | string, optional | The Merkle root of entries `0..upto_seq`. |
| `anchor` | string, optional | `ANCHOR_RE` and at most 200 characters: the repository-relative path of the proof that anchors `root` (for example `ledger/anchors/000012.root.ots`). |

| # | Precondition | Refusal message |
|---|---|---|
| Z1 | `upto_seq = seq − 1`, with `seq` the `seq` of this entry. | `witness upto_seq must be {seq − 1} (a checkpoint covers every entry before it)` |
| Z2 | `head = S.head`. | `witness head mismatch` |
| Z6 | `S.witness_marks` has no record of `actor`, **or** `S.acts` is greater than the `acts` of that record: an entry whose type is not `witness` was applied since this witness's last checkpoint. | `no entry but checkpoints since the last checkpoint of {actor} (a witness posts a checkpoint only when an entry that is not a checkpoint was added since its last one)` |
| Z7 | `S.witness_marks` has no record of `actor`, **or** `now − time ≥ 1 h` (`CHECKPOINT_INTERVAL`), with `time` that of the record. | `the last checkpoint of {actor} is less than 1 hour old (at most one checkpoint per witness per hour)` |
| Z3 | `root` is absent, or `root = merkle_root(S.hashes)`: the root of entries `0..upto_seq` (`State.entries_root`, which keeps the RFC 6962 frontier of `S.hashes` and so costs O(log n) hashes; section 2.4). | `witness Merkle root mismatch` |
| Z4 | `anchor` is absent, or has at most 200 characters and matches `ANCHOR_RE`. | `anchor: a repository-relative path (letters, digits, _ . - and /) of at most 200 characters` |
| Z4a | `state_version = STATE_VERSION` (2). | `witness state_version must be 2: the version of the state document whose digest it states (a core that changes the document reads each checkpoint by its own version)` |
| Z5 | `state_sha256 = digest(S)`, the state digest of section 4.11 computed on the state as it stands before this entry's effect. Not evaluated for an entry taken on trust (section 5.1). | `witness state digest mismatch` |

The rows are in the order of evaluation: Z6 and Z7 come before Z3, and Z4a before Z5.

Effects:

1. `S.witness_marks[actor] = {acts: S.acts, time: now}`.
2. The Checkpoint `{witness: actor, upto_seq, head, state_sha256, state_version, root: body.root or null, anchor: body.anchor or null}` is absorbed by the history `checkpoints` (section 4.11).

Notes:

- When Z5 is evaluated nothing of this entry has changed the state (section 5.1), so `S` is exactly the state after entry `seq − 1`. The digest covers the checkpoints before this one (through the history `checkpoints`), and not this one: the record it leaves is a fact of the next state.
- Z5 has one message whatever is wrong with the field: a string that is not 64 lowercase hexadecimal characters is not the digest.
- **A checkpoint names its document version** (Z4a). A later core that changes the state document (a new `STATE_VERSION`) can tell the checkpoints written under the old one, and judge each by the document of its own version, or take it on trust; this core knows one version and accepts that one.
- **What the rule is for.** A verifier whose state differs from the witness's in any stored fact computes another digest and refuses the checkpoint. Two implementations that drifted apart therefore part at the next checkpoint, with a refusal anyone can see, and not at some later entry or never. A checkpoint a witness signs is also a statement that can be held against it: it names the whole state, not only the chain of hashes.
- A checkpoint cannot name an earlier position. One that lost its place in the sequence (another entry took its `seq`) is refused under Z1 and is made again on the new head, which the witness node does (section 9.7 says what else it checks first).
- An absent proof is an absent field: there is no `null` (section 2.2). Replay does not open the file `anchor` names; the gate of section 9.6 holds the files a pull request adds under `ledger/anchors/` to the anchors its checkpoints name. Checkpoints are recorded; no rule derives finality from them.
- **A checkpoint covers something new, and a witness posts at most one an hour** (Z6, Z7; section 5.4). The first checkpoint of a witness is always lawful. The checkpoint of another witness is not a new entry for Z6: two witnesses cannot feed each other. `ledger.checkpoint_due(S, name, now)` is the two conditions as a pure function, which the witness node asks before it signs.

### 6.17 `invite`

**Signer:** an active member. **Function:** `ledger._invite`.

An invitation is how a login that is not a member comes to write to the ledger: it makes lawful one `petition` of that login (section 6.2, P0), and it makes the inviter the candidate's first sponsor.

| Body field | Type | Constraint |
|---|---|---|
| `login` | string, required | `LOGIN_RE`: the GitHub login of the person invited. Not the actor's own. |
| `github_id` | integer, required | At least 1: the numeric id of the GitHub account behind `login`. |

| # | Precondition | Refusal message |
|---|---|---|
| I1 | `login` matches `LOGIN_RE`. | `login must be a valid GitHub login` |
| I2 | `github_id ≥ 1`. | `github_id must be a positive integer (the numeric GitHub user id)` |
| I3 | `stands_in(actor, now)`: the actor's `degree ≥ 3`, or the actor is a successor (section 6.34). | `only Master Builders may invite (and, while a succession is in force, the members of the highest degree present)` |
| I4 | `login` is not the same login as `actor` (up to case). | `a Master Builder cannot invite themselves` |
| I5 | For each pair `(role, other)` of `name_holders(login, now)`, in order, these checks in this order. A `member` pair has exactly the spelling `login`, its record satisfies `may_return(record, now)` (departed or voided, and `waited(status_since, now, 90)`; or expelled and `waited(status_since, now, 365)`), and no sanction ballot on it is open (`open_sanction_on(login)` is none). No pair is a `witness`. No pair is a `custodian`. No pair is an `invitation`. No pair is a `petition`. No pair is a `ballot`. No pair is a `claim`. | `login {login!r} collides with {other!r} (logins are case-insensitive)`; `{login} is already a member (a departed member, or one whose admission was undone, may be invited again once 90 days have passed, an expelled member once 365 have)`; `a sanction ballot on {login} is open ({id}): the login is invited again only once it has closed`; `login {login!r} collides with the witness {other!r} (a witness name cannot become a member login, and names are case-insensitive)`; `login {login!r} collides with the custodian {other!r} (a custodian name cannot become a member login, and names are case-insensitive)`; for an invitation, `{login} already has a live invitation` when `other = login`, else `login {login!r} collides with the invitation of {other!r}`; for a petition, `{login} already has a pending petition` when `other = login`, else `login {login!r} collides with the pending petition of {other!r}`; `login {login!r} is the name proposed by an open witness ballot ({other!r})`; `login {login!r} collides with the custodian name of a pending claim ({other!r}): nobody is invited under it while the claim is pending` |
| I6 | The actor's `sponsor_ban_until` is null or `now ≥ sponsor_ban_until`. | `sponsorship suspended (a sponsored member was expelled for fraud)` |
| I7 | `sponsorships(actor, now) < 4` (section 7.5). | `sponsorship budget exhausted` |
| I8 | Every pair `(role, other)` of `id_holders(body.github_id, now)` is exactly `("member", login)`. | `the GitHub account with id {github_id} is already the {role} {other!r} (one GitHub account, one member: a returning member keeps the same login, and no account comes in under another)` |

Effects:

1. Every key of `S.invitations` that is the same login as `login` is removed. After I5 these can only be lapsed invitations: of that login, or of another spelling of it.
2. `S.invitations[login] = {by: actor, github_id: body.github_id, time: now}`.

Notes:

- The signer rule (section 5.2) already requires an active member; I3, I6 and I7 are the conditions of a `vouch` (V3, V5, V6). An invitation therefore needs exactly what a sponsorship needs, and it counts in the same budget from the moment it is signed.
- I4 can never be the only failing check, since the actor is an active member and I5 would refuse the name; it exists for its message.
- I5 is the name rule of section 4.7 for a login that is to become a petitioner. It refuses the name of a pending claim of the Custodian office (`claim` pairs, section 4.7): once the claim is applied that name is a custodian's, and a custodian name never becomes a member login. While a sanction ballot on a returning record is open, its login is not invited: the ballot may still change the record (a `voided` one may be expelled for fraud, section 6.4.4), and the admission it would open waits for it (A4 asks the wait again). A reserved petition includes one whose time has run out but whose admission ballot is still open. The waiting period of a returning member is enforced here, and stated again at the petition (P1).
- An invitation lapses when `expired(time, now, 30)` on the effective clock (section 7.8): the petition MUST be an entry with a time at most 30 days after the invitation, to the second, not counting the time the ledger was halted in between. A lapsed invitation is not removed by time; it is replaced by the next invitation of the login (effect 1) and otherwise stays in `S.invitations`, where it counts in its inviter's budget for 90 more days (`INVITE_COUNTED_DAYS`, section 7.5) and for nothing else.
- The invitation is not revoked by anything that happens to the inviter. If the inviter departs, is suspended, is expelled or comes under a ban while the invitation is live, the invited login may still petition; the inviter is then left out of the sponsors when the admission ballot opens (A2).
- **One GitHub account, one member** (I8). The account is refused while anyone else holds it: a member record of any status under another login (active, suspended, departed, expelled or voided, a founder included), a live invitation of another login, or a reserved petition of another login. After I5, a pair with `other = login` can only be the member record of a returning login, which is the one case allowed: the same account on the same login. The message names the first holder found, in the order of `id_holders`. So a GitHub account that was renamed cannot be invited under its new login while its old login has a record, and a departed or expelled member returns under the login of the record. Whether `login` is today the GitHub account with that id is the gate of section 9.3. What I8 does not ask is listed in section 12, point 19.
- The entry credits the inviter with activity (section 5.3).

### 6.18 `rekey`

**Signer:** a member whose status is not in `GONE` (section 5.2), a suspended member included, with the key the ledger holds for them: the **old** key. **Function:** `ledger._rekey`.

A `rekey` replaces the member's key by a new one. Two keys sign it: the old key signs the entry, as for any act of the member, and the new key signs the **proof**, so nobody registers a key they do not hold.

| Body field | Type | Constraint |
|---|---|---|
| `key` | string, required | A valid key (section 2.6), of either type: the new key. |
| `proof` | string, required | A signature by the new key over the proof message below, in the one accepted form of section 13 for the type of the new key. |

The **proof message** (`ledger.rekey_message`, of the login, the key being replaced and the new key) is an ASCII byte string of four lines, each ended by the single byte `LF` = `0x0A`, with nothing else between them:

```
message = "openmasonry rekey v1" LF actor LF old-key LF new-key LF
```

where `actor` is the entry's `actor` exactly as written, `old-key` is `S.members[actor].key` in the state before the entry, and `new-key` is `body.key`, the two keys in the text form of section 2.6 (type, one space, base64). The first line is the constant `REKEY_DOMAIN`. There is no space before or after a line feed and no carriage return.

Vector: for the actor `ada`, the old key `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINoyJDqgsowJ2Yz/AaNNQHzExhtKRp6k5bVLwkCQz0/L` and the new key `sk-ssh-ed25519@openssh.com AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29tAAAAIO+Vgg1pQV/h0dKMn+52r6UFgZ5Q9q1iVM+ST2qhwJNRAAAABHNzaDo=`, the message has 234 bytes and its SHA-256 is `872750786a97b04505b889d8fb0a3b4789744b86cfed00e9ac671d07394d185d`. A login and a key contain no line feed, so the message has one reading. It begins with `o` while the signed payload of every entry begins with `{`, so a proof is never a signature of an entry and the signature of an entry is never a proof. The proof is checked by the same predicate as every signature, in the same namespace: `sig_ok(proof message, body.proof, actor, body.key)` (section 13).

| # | Precondition | Refusal message |
|---|---|---|
| Q1 | `body.key` is a valid key (section 2.6). | `keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)` |
| Q2 | `key_holders(body.key, now)` is empty. For the first pair found: when it is `("member", actor)`, the first message; otherwise the second. | `this is already your key`; `this key is already used by {other} (one key per login: members, witnesses and petitions)` |
| Q3 | The point of `body.key` is not in `S.known_keys`. | `this key was used in this ledger before (a key that was ever registered here is never registered again)` |
| Q4 | The member's `last_rekey` is null, or `waited(last_rekey, now, 30)`. | `one rekey per member per 30 days` |
| Q5 | `sig_ok(rekey_message(actor, member.key, body.key), body.proof, actor, body.key)`. | `bad proof: the new key must sign the rekey message (login, old key, new key)` |

Effects:

1. The member's `key = body.key`.
2. The member's `last_rekey = now`.
3. The point of `body.key` is added to `S.known_keys`.

Notes:

- **From the next entry on** the member's signer key is the new key (section 5.2). The old key signs nothing more for this login, and it can never be registered by a `rekey` again, by this member or by anyone (Q3): a key that was replaced because it was stolen does not come back.
- Q2 and Q3 compare points, so the other type of a key already held or already known is refused like the key itself. Every key that anyone holds is in `S.known_keys`, so Q2 cannot fail without Q3; it comes first for its message.
- Q3 covers every key any entry ever registered (section 4.1), whether or not anyone holds it today: the member's own earlier keys, the key of a petition that lapsed or was refused, the key of a witness who was removed or never added.
- **Open ballots are not disturbed.** A commitment is bound to the login, not to the key (section 6.5), so a member who committed before a `rekey` reveals after it with the new key, and the reveal is checked against the stored commitment as always (R5). Electorates, exams and seats name logins and are unchanged.
- A suspended member may rekey and can still sign nothing else but `depart` and `rekey_object`. The entry adds no activity, whoever signs it (section 5.3), and it is never counted by C12a: Q4 bounds it.
- A member whose key is frozen may rekey, and a `rekey` is accepted while the ledger is halted (section 5.2, rule 5). The freeze is on the login and goes on after the `rekey`, until it ends or a custodian withdraws it (section 6.19.1).
- Q4 is counted within one record: a record created by a new admission starts with `last_rekey` null.
- A `rekey` needs the old key. A member whose key is lost recovers the membership with a new key by the entries of sections 6.26 to 6.30: a custodian freezes the old key (section 6.19.1), or the recovery is asked without a freeze; Master Builders co-sign; and a notice of 21, 30 or 45 days runs. No correction replaces a key.
- A `rekey` is accepted while a recovery of the same key is alive, and leaves it as it is: the recovery, if it is applied, replaces whatever key the ledger holds then. Q4 counts the application of a recovery like a `rekey` (section 6.29).
- Whether the new key is listed for the login on GitHub, and whether the pull request comes from the member's own GitHub account, are gates (section 9.3), not rules of replay.

### 6.19 `correction`

**Signer:** a custodian, with its custodian key; `actor` is the custodian's name (section 5.2). **Function:** `ledger._correction`, with one function per act (`ledger.ACTS`).

A correction is how a custodian repairs damage without rewriting anything (Landmark VI: a repair may undo, freeze or pause but never grant). It is one **act** from a closed menu, on one **ground** from a closed list, with a public **reason** pinned by digest. The menu has three classes:

- five **immediate** acts (`freeze_key`, `freeze_witness`, `stay`, `halt`, `hold_room`): each is in force from its own entry, on an interval that ends by itself (section 7.8), and no further entry is ever needed to end it. An immediate act is the act of **one** custodian key, whatever `S.custodian_threshold` says;
- two **noticed** acts (`void_ballot`, `undo_ballot`): the act is pending for 14 days of notice, needs as many custodian keys as `S.custodian_threshold`, and takes effect only by a `correction_apply` (section 6.25), within the 7 days after the notice. While a `void_ballot` is pending its ballot is paused; otherwise a pending act changes nothing. Its life is section 6.19.9;
- the `note`, which has no effect in the ledger and is recorded apart from the corrections, in `S.notes` (section 6.19.6).

Where no custodian key is live, no correction exists: on a ledger whose genesis named no custodian, every entry of this section and of sections 6.20 and 6.22 to 6.25 is refused by the signer rule, and the same holds once the keys of all the custodians have lapsed or been removed (section 4.8). In both cases a founder's claim (sections 6.31 to 6.33), where its conditions hold, names a custodian and its key, from whose application corrections exist again; after the Sunset, or once three active Master Builders who are not founders exist, no claim is possible and no correction exists until an amendment says otherwise.

| Body field | Type | Constraint |
|---|---|---|
| `act` | string, required | One of `freeze_key`, `freeze_witness`, `stay`, `halt`, `hold_room`, `note`, `void_ballot`, `undo_ballot`. |
| `target` | object, required | Exactly the fields of the act (sections 6.19.1 to 6.19.8), each a required string; the empty object for `halt`. |
| `ground` | string, required | One of `GROUNDS`: `key_compromised`, `protocol_defect`, `identity_fraud`, `attack_in_progress`, `moderation`. The last is the ground of a `note` and of nothing else (N5, N5a). |
| `reason_sha256` | string, required | `HEX64`: the SHA-256 of the bytes of the public reason, archived in the repository as `ledger/reasons/{reason_sha256}.md`. |

Preconditions common to every act, first part. `C` is the custodian `S.custodians[actor]`.

| # | Precondition | Refusal message |
|---|---|---|
| N1 | `act` is one of the eight acts. | `act must be one of ['freeze_key', 'freeze_witness', 'halt', 'hold_room', 'note', 'stay', 'undo_ballot', 'void_ballot']` |
| N2 | `ground` is in `GROUNDS`. | `ground must be one of ['attack_in_progress', 'identity_fraud', 'key_compromised', 'moderation', 'protocol_defect']` |
| N3 | `reason_sha256` matches `HEX64`. | `reason_sha256 is the sha256 (64 lowercase hex) of the public reason, archived as ledger/reasons/<sha256>.md` |
| N4 | `target` has exactly the fields of the act (`ledger.TARGET_FIELDS`), checked like a body (section 5.1, "Exact bodies"). | `malformed correction entry: {act} target: unknown field {key!r}`; `… : missing field {key!r}`; `… : field {key!r} must be a string` |
| N5 | For `freeze_key` the ground is `key_compromised`; for `halt` it is `attack_in_progress`; for `note` it is `moderation` (`ledger.ACT_GROUND`). | `freeze_key takes one ground only: key_compromised`; `halt takes one ground only: attack_in_progress`; `note takes one ground only: moderation` |
| N5a | For every act but `note`: the ground is not `moderation` (`NOTE_GROUND`). The five other acts take any of the four other grounds. | `the ground moderation is the ground of a note, and of no other act` |

Then the preconditions of the act (sections 6.19.1 to 6.19.8), then, second part:

| # | Precondition | Refusal message |
|---|---|---|
| N7 | No record `x` of `S.corrections` has the same `act`, a `target` equal to this one, `void` set and `not waited(x.void, now, 90)` (wall time; `REPOST_AFTER_DAYS`). The first such record names the refusal. | `correction {x.seq}, the same act on the same target, was voided by objections less than 90 days ago (it is posted again only 90 days after that)` |
| N6 | Fewer than `CORRECTIONS_PER_30_DAYS` = 5 records `x` of `S.corrections` have `not waited(x.time, now, 30)` (wall time). Every such record counts, whoever signed it and whatever became of it (withdrawn, void, lapsed, expired, applied). A noticed act counts from the entry that **posts** it; its co-signatures and its application are not corrections and count for nothing. Notes are not records of `S.corrections` and are not counted. | `at most 5 corrections in any 30 days, all custodians together (notes aside)` |
| N6a | With `n` = the number of custodian keys live at `now` (`custodians_live(now)`; at least 1, the signer's) and `share = ⌈5 / n⌉`: fewer than `share` of the records counted by N6 have `by = actor`. | `at most {share} corrections per custodian in any 30 days while {n} custodian key(s) are live (each one's share of the 5 of all custodians together; notes aside)` |

N7, N6 and N6a are not evaluated for a `note`: its effect (section 6.19.6) is applied after the preconditions of the act, and nothing more.

Effects of every act but `note`, applied only after every precondition has passed:

1. `S.corrections[seq] = Correction(seq, by = actor, act, a copy of target, ground, reason_sha256, time = now, class, until, subject, objections = (), void = null, withdrawals = (), withdrawn = null, withdrawn_by = "", signers, applied = null, applied_by = "", released = null)`, with `seq` the `seq` of this entry. For an immediate act: `class = immediate`, `until = now + D d`, with `D` the days of the act (`ledger.ACT_DAYS`: 30 for `freeze_key` and `freeze_witness`, 14 for `stay`, `halt` and `hold_room`), and `signers = ()`. For a noticed act: `class = noticed`, `until = null` and `signers = (actor,)`. `subject` is the login the act returns (below), or the empty string.
2. The act's own effect at the entry, if any. Only `freeze_key` has one. A noticed act has none here; a `void_ballot` pauses its ballot from this entry on through the views the other rules read (`void_pending`, the effective clock).

Notes:

- **Nothing else changes at this entry.** A `correction` entry writes one record and, for a `freeze_key`, moves seats of examiners exactly as their own recusal would. It never creates, removes or changes a member, a degree, a status, a key, a witness, a pin, a petition, an invitation, a ballot's electorate, a commitment, a revealed vote or a result. What an immediate act does, it does through the views of section 4.7 that the other rules read: `frozen`, `witness_frozen`, `stayed`, `halted` and the effective clock; a pending `void_ballot` pauses its ballot through `void_pending` and the same clock. What a noticed act decides, it does at its `correction_apply`, and that is only ever to take something away (section 10, invariant 38).
- **Each custodian has a share, and all of them a ceiling** (N6, N6a). With one live key the share is the whole five; with two it is three each; with three it is two each. The ceiling of five holds whatever the shares add up to. So where several custodians exist, no one of them can use up the allowance the others may need, and where one exists the limit is the ceiling alone. The share follows the keys that are live at the entry: when a key lapses or is removed, the shares of the others grow.
- **An act the Master Builders voided is not posted again at once** (N7). Objections void one correction; without N7 a custodian could post the same act on the same target in the next entry and oblige the Masters to object again, each time. The same act on the same target waits 90 days from the moment it was voided; another act, or the same act on another target, is not held.
- **Replay does not read the reason.** N3 checks the form of the digest only. That the file exists in the tree and hashes to its name is the gate of section 8.5.
- **One key for an immediate act, the threshold for a noticed one.** `S.custodian_threshold` is read by no rule of the posting of an immediate act or of a note: each is the act of one custodian key, also where the genesis names three custodians and a threshold of two, because a key in a thief's hands or a ballot under attack cannot wait for a second signature, and every immediate act ends by itself and can be ended by objection. A noticed act is posted by one key and applied only with the threshold (sections 6.24 and 6.25).
- A custodian entry credits nobody (section 5.3).

#### 6.19.1 Act `freeze_key`

| Aspect | Rule |
|---|---|
| Target | `login` (string): a member, exact. |
| Ground | `key_compromised` only (N5). |
| Preconditions | **FK1.** `S.members[login]` exists and its `status` is not in `GONE` (`departed`, `expelled`, `voided`). Refusal: `no such member`. **FK2.** (None: a custodian **may** freeze the key of the member they are linked to. It restricts nobody but the person who holds the custodian key.) **FK3.** Every record of `S.corrections` with `act = freeze_key` and the same `login` that was **not overruled** (section 4.9: withdrawn by a custodian other than the one who posted it) has `waited(its time, now, 90)` (wall time; `REFREEZE_AFTER_DAYS`). A freeze that ran to its end, was withdrawn by its own poster, was voided by objections, was released by a recovery or ended with its custodian's key counts; one that other custodians withdrew does not. Refusal: `the key of {login} was frozen less than 90 days ago (the same key is frozen again only 90 days after the previous freeze began, unless other custodians withdrew that freeze)`. **FK4.** With `n = len(active(now))` and `cap = max(1, n div 10)` (`FREEZE_CAP_DIVISOR`): fewer than `cap` logins **other than `login`** have their key frozen at `now` (`frozen_keys(now)`), counting each login that is the target of a `freeze_key` in force **or** has a recovery under way (section 4.10). Refusal: `too many keys are frozen at once: at most {cap} (a tenth of the {n} active members, never fewer than 1)`. FK4 is asked by a freeze only: no recovery is ever held back by it (RR10, RC6). |
| Subject | `login`. |
| In force | `[now, now + 30 d)`, unless it ends earlier (section 7.8). At most one freeze of a login is in force at a time (FK3). |
| Effect at the entry | **Frozen examiners stand aside.** For every exam of `S.exams`, in the order of the map, that has `examiners` not null, has not `lapsed`, holds `login` in `examiners` and not in `reports`, is not `expired(now)` (effective clock), is not `consumed`, has not `passed()` and has not `failed(now)`: effects 1 to 4 of an `exam_recuse` by `login` are applied (section 6.11). |
| While in force | The signer rule refuses every entry whose signer key is resolved through `S.members[login]`, **except** (`ledger._frozen_may`): the five types of `FREEZE_ALLOWED`, which are `depart`, `rekey`, `rekey_object`, `ballot_commit` and `ballot_reveal` (the member's vote, in every ballot); and every entry of an unstoppable ballot (section 5.2: `ballot_open` of kind `amendment` or `custodian`, and `ballot_close` of a ballot of either kind). **A frozen member cannot object to a correction** (`correction_object` is not on the list), and opens and closes no other ballot. Refusal: `the key of {login} is frozen until {end} (correction {seq}): a frozen member may only depart, rekey, vote (commit and reveal), take part in an amendment ballot or the ballot that removes a custodian, or object to a recovery of their own key`, with `end` the end of the interval as things stand, in the text form of section 2.5. The same exceptions hold while a recovery of the key is under way after the freeze has ended (section 6.26). A drawn examiner who is frozen at an `exam_draw` stands aside at the draw (section 6.9), and a frozen member is passed over as a replacement (section 6.11). |

Notes: a freeze is not a status. The member stays `active`, stays in `active(now)` and `masters(now)`, stays in every electorate frozen before the freeze, and is put into electorates frozen during it. **A freeze never changes who decides a ballot:** the frozen key commits and reveals in every ballot the member is an elector of, exactly as before. A custodian who could silence an elector by a freeze could turn an amendment or a sanction, the ballots no correction may otherwise touch; and a key that may be in other hands can do less harm by one vote among the electors than a custodian could by choosing which electors vote. The exceptions hold for the key the ledger holds at that moment: after a `rekey` the freeze goes on, on the login, until it ends or is withdrawn. FK3 keeps a login from being frozen for more than 30 days in 90 by any one custodian's choice; a freeze that the **other** custodians withdrew leaves no wait, so that its poster, or anyone, may freeze the key again when the withdrawal was the mistake (a freeze its own poster withdrew is spent like any other, so no custodian renews a freeze by withdrawing it). A freeze that objections voided is also held by N7. What protects the Masters who would object is the cap of FK4, not an exception for objections: with fewer than twenty active members one key is frozen at a time. The target of a freeze is also the one Master who could not have objected to it anyway (J5). A freeze of the custodian's own member is objected to by the other Masters, like any other.

#### 6.19.2 Act `freeze_witness`

| Aspect | Rule |
|---|---|
| Target | `name` (string): a witness, exact. |
| Ground | Any of `GROUNDS` but `moderation` (N5a). |
| Preconditions | **FW1.** `name` is a key of `S.witnesses`. Refusal: `no such witness`. **FW2.** No `freeze_witness` of `name` is in force at `now`. Refusal: `the witness {name} is already frozen`. **FW3.** Some other key of `S.witnesses` has no `freeze_witness` in force at `now`, **or** the ground is `attack_in_progress`. Refusal: `the last unfrozen witness is frozen only on the ground attack_in_progress`. |
| Subject | None (the empty string). |
| In force | `[now, now + 30 d)`, unless it ends earlier. |
| While in force | The signer rule refuses every entry `name` signs as a witness. Refusal: `the witness {name} is frozen until {end} (correction {seq})`. |

Notes: members may still sign `ballot_close`, `exam_draw` and `council_draw` (section 5.2), so freezing every witness stops no ballot; only checkpoints wait.

#### 6.19.3 Act `stay`

| Aspect | Rule |
|---|---|
| Target | `ballot` (string): the id of an open ballot. |
| Ground | Any of `GROUNDS` but `moderation` (N5a). |
| Preconditions | **SY1.** `S.ballots[ballot]` exists and is open. Refusal: `no open ballot`. **SY2.** Its `kind` is not in `STAY_EXEMPT` (`amendment`, and `custodian`, the ballot that removes a custodian). Refusal: `a ballot of kind {kind} is never stayed`. **SY2a.** The ballot is not one the Sunset counts (`ledger.sunset_ballot`): not of kind `witness` with `action = add`, and not of kind `advancement` with `degree = 3`. Refusal: `recusal: a ballot that adds a witness, or that advances a member to the 3rd degree, is never stayed, voided or undone by a correction (the Sunset counts both, and the Sunset ends the custodians' keys)`. **SY3.** No record of `S.corrections` has `act = stay` and this `ballot`, whatever became of it. Refusal: `ballot {ballot} was stayed once already (a ballot is stayed at most once)`. **SY3a.** `ballot_time(b, now) < commit_until + REVEAL_GAP`: the ballot's reveal window has not opened. Refusal: `the reveal window of ballot {id} opened at {opens}: a ballot is stayed, or its voiding posted, only before any vote can be revealed`, with `opens` = `ballot_due(b, commit_until + REVEAL_GAP)` in the text form of section 2.5. **SY4.** `C.member` is not a party to the ballot (`ledger.party_to`): not the same login as its `opened_by`, as `subject.member` or as `subject.candidate`; and, for an admission, not the same login as any element of `frozen.vouches` or of the `vouches` of the candidate's petition, if `S.petitions` still holds one. Refusal: `recusal: the custodian {C.name} never stays a ballot whose subject, opener or sponsor is their own member ({C.member})`. |
| Subject | `subject.member` of the ballot when it has one (advancement, sanction); otherwise none. |
| In force | `[now, now + 14 d)`, unless it ends earlier. |
| While in force | No `ballot_commit`, `ballot_reveal` or `ballot_close` of that ballot is accepted (K1a, R1a, X1a). Refusal: `ballot {id} is stayed until {end} (correction {seq})`. The stayed time is taken out of the ballot's own clock (section 7.8), so each of its windows is extended by exactly the time the stay was in force. |

Notes: **no custodian pauses or ends a ballot after reading a vote** (SY3a, and VB3a for a `void_ballot`). While a ballot's clock is before the first second of its reveal window, no reveal of it exists (R2); from that second on, neither act is posted. A stay is posted once in the life of a ballot, whatever became of the first one (SY3): a withdrawn stay is not renewed. The custodians are recused from the two kinds of ballot whose passing can end their own keys (SY2a; section 7.9).

#### 6.19.4 Act `halt`

| Aspect | Rule |
|---|---|
| Target | The empty object. |
| Ground | `attack_in_progress` only (N5). |
| Preconditions | **HT1.** Every record of `S.corrections` with `act = halt`, whatever became of it, has `waited(its time, now, 90)` (wall time; `HALT_INTERVAL_DAYS`). Refusal: `the ledger was halted less than 90 days ago (at most one halt in 90 days, start to start)`. |
| Subject | None. |
| In force | `[now, now + 14 d)`, unless it ends earlier. Two halts never overlap (HT1). |
| While in force | The signer rule refuses every entry whose type is not in `HALT_ALLOWED` (`correction`, `correction_cosign`, `correction_apply`, `correction_withdraw`, `custodian_alive`, `custodian_revoke`, `rekey_recover`, `rekey_recover_apply`, `correction_object`, `depart`, `rekey`, `rekey_object`, `rekey_cosign`, `rekey_oppose`, `witness`) and that is not an entry of an unstoppable ballot (an amendment, or the ballot that removes a custodian; section 5.2). Refusal: `the ledger is halted until {end} (correction {seq}): only custodian entries, custodian_revoke, correction_object, depart, rekey, the entries of a key recovery, a witness checkpoint, an amendment ballot and the ballot that removes a custodian are accepted`. The halted time is taken out of the effective clock (section 7.8), except for a ballot of kind `amendment` or `custodian`, which runs on wall time. |

Notes: a `ballot_close` of any other ballot is refused during a halt, whoever signs it, and so are `exam_draw` and `council_draw`: nothing is decided and no lot is drawn, and no window of those ballots runs out while the ledger is halted. A witness's **checkpoint** (the entry type `witness`) is accepted: it changes nothing, and it is evidence of the state under attack. An amendment ballot and the ballot that removes a custodian go on through a halt, on wall time, from their opening to their close (section 6.4.6). Every entry of a key recovery is accepted (`rekey_recover`, `rekey_cosign`, `rekey_oppose`, `rekey_object`, `rekey_recover_apply`): its notice is wall time, so a halt cannot use up the notice in which the holder of the key may stop the recovery, and it cannot hold back a member whose key was taken.

#### 6.19.5 Act `hold_room`

| Aspect | Rule |
|---|---|
| Target | `login` (string): a member, exact. |
| Ground | Any of `GROUNDS` but `moderation` (N5a). |
| Preconditions | **HR1.** `S.members[login]` exists and its `status` is not in `GONE` (`departed`, `expelled`, `voided`). Refusal: `no such member`. **HR2.** `login` is not the same login as `C.member`. Refusal: `recusal: the custodian {C.name} never corrects their own member ({C.member})`. **HR3.** No `hold_room` of `login` is in force at `now`. Refusal: `{login} is already under a room hold`. **HR4.** Every record of `S.corrections` with `act = hold_room` and the same `login` that was **not overruled** (section 4.9) has `waited(its time, now, 90)` (wall time; `REHOLD_AFTER_DAYS`), as FK3 for a freeze: a hold that ran to its end, was withdrawn by its own poster or was voided by objections counts; one that other custodians withdrew does not, and so leaves no wait behind (the member may be held again at once). Refusal: `{login} was held less than 90 days ago (the same login is held again only 90 days after the previous hold began, unless other custodians withdrew that hold; only a sanction ballot keeps a member out longer)`. |
| Subject | `login`. |
| In force | `[now, now + 14 d)`, unless it ends earlier. |
| While in force | No rule of replay reads it. `ledger.room_held(S, member, now)` is true, and `ledger.room_hold_until(S, member, now)` is the end of the interval as things stand; the rule of the rooms reads them. |

#### 6.19.6 Act `note`

A `note` is the public record of a moderation act done outside the ledger (hiding a comment, locking a thread, blocking an account). It has no effect on the state but its own record, and it is no correction record.

| Aspect | Rule |
|---|---|
| Target | `action` (string): one of `NOTE_ACTIONS`. `target` (string): `NOTE_TARGET_RE`, what the act touched. `rule` (string): `NOTE_RULE_RE`, the published rule it applied. |
| Ground | `moderation` only (N5). A note needs a reason like every correction. |
| Preconditions | **NT1.** `action` is one of `hide`, `lock`, `block`, `unblock`, `limit`, `other`. Refusal: `note action must be one of ['block', 'hide', 'limit', 'lock', 'other', 'unblock']`. **NT2.** `target` matches `NOTE_TARGET_RE`. Refusal: `note target: 1..120 of letters, digits and . _ : / # @ - starting with a letter or digit`. **NT3.** `rule` matches `NOTE_RULE_RE`. Refusal: `note rule: 1..64 of letters, digits and . _ : / # - starting with a letter or digit`. **NT4.** Fewer than `NOTES_PER_DAY` = 10 records of `S.notes` have `by = actor` and a `time` on the same UTC calendar day as `now`. (The list is in the order of time, so the count reads it from its end and stops at the first note of an earlier day.) Refusal: `at most 10 notes per custodian per UTC day`. |
| Effect | `{seq, by: actor, action, target, rule, reason_sha256, time: now}` is appended to `S.notes`; then every record but the newest `NOTES_KEPT` = 200 leaves the front of the list, oldest first, and is absorbed by the history `notes` with the leaf it had in the section `notes` (section 4.11). Nothing is written to `S.corrections`. |

Notes: a note states the ground `moderation` because it is none of the four grounds of a repair: nothing in the ledger is repaired by it, and a note that claimed `attack_in_progress` would read as a finding nobody can object to. A note is not counted by N6, N6a or N7. It cannot be withdrawn, objected to, co-signed or applied: those entries look for a record of `S.corrections` under its `seq`, find none, and are refused with `no such correction` (CW1, J1, CS1, AP1). **The state keeps the newest 200 notes; every note stays in its entry**, which is the public moderation log. The bound keeps the list from growing with the life of the ledger: NT4 reads at most one day of it (30 notes, with three custodians), and no other rule reads it. The public reason of a note is required of the pull request that adds it and is listed among the reasons of the tree like any other (section 8.5), from the entries, also after the note has left the list.

#### 6.19.7 Act `void_ballot`

A noticed act. Once applied, an **open** ballot ends with no effect and nobody is penalized.

| Aspect | Rule |
|---|---|
| Target | `id` (string): the id of an open ballot. |
| Ground | Any of `GROUNDS` but `moderation` (N5a). "Disagreement with an outcome" is not a ground and cannot be stated. `key_compromised` is meant for votes cast by a stolen key; replay does not read the reason, so that is for the public reason to show. |
| Preconditions | Evaluated at the `correction` entry, with `C` the custodian who signs. **VB1.** `S.ballots[id]` exists and is open. Refusal: `no open ballot`. **VB2.** Its `kind` is not in `STAY_EXEMPT` (`amendment`, `custodian`). Refusal: `a ballot of kind {kind} is never voided or undone by a correction`. **VB2a.** The ballot is not one the Sunset counts (SY2a). Refusal: `recusal: a ballot that adds a witness, or that advances a member to the 3rd degree, is never stayed, voided or undone by a correction (the Sunset counts both, and the Sunset ends the custodians' keys)`. **VB3.** No record of `S.corrections` has `act = void_ballot` and this `id`, unless it was overruled (section 4.9: withdrawn by a custodian other than its poster). Refusal: `ballot {id} was the target of a void_ballot once already (correction {seq}): a ballot is the target of a void_ballot at most once, unless other custodians withdrew it`. **VB3a.** `ballot_time(b, now) < commit_until + REVEAL_GAP`: the ballot's reveal window has not opened (SY3a, with the same refusal). **VB4.** `C.member` is not a party to the ballot (`ledger.party_to`, SY4). Refusal: `recusal: the custodian {C.name} never voids or undoes a ballot whose subject, opener or sponsor is their own member ({C.member})`. |
| Subject | `subject.member` of the ballot when it has one (advancement, sanction); otherwise none. |
| While pending | **The ballot is paused**, exactly as by a stay: no `ballot_commit`, `ballot_reveal` or `ballot_close` of it is accepted (K1b, R1b, X1b), and the pending time is taken out of the ballot's own clock (`void_span`, section 7.8), so each of its windows is extended by exactly that time. That lasts at most 21 days and one second, and it ends at once if the act is applied, voided by objection, withdrawn or `ended`. Refusal: `ballot {id} is paused while the correction that would void it is pending (correction {seq}, until {apply_end} at the latest)`. |
| Checked again at the application | VB1, VB2, VB2a and VB4, the last for the custodian who posted the act, every co-signer whose key is live and the custodian who applies it (AP6). VB3 and VB3a are rules of the day the act is posted. |
| Effect of the application | **1.** The ballot's `result = voided` and `corrected` = the `seq` of the correction. **2.** For an advancement: if `S.members[member]` exists with the membership `frozen.admitted`, and `S.exams[(member, degree)]` exists, that exam's `consumed` becomes false. The exam is as it was before the ballot opened: passed, and free to support another ballot. **3.** Nothing else. |

What "the state from before the ballot opened" means, kind by kind: an **admission** leaves its petition in `S.petitions` with its sponsors, exactly as before (no vouch was accepted while the ballot was open, and the petition's age went on counting on the effective clock, so it may have lapsed meanwhile); an **advancement** gives the exam back (effect 2); a **sanction** and a **witness** ballot changed nothing by opening, except that a witness ballot that proposed a key put its point in `S.known_keys`, where it stays (that set only grows). The ballot's `commits`, `reveals`, `electors` and deadlines are **not** changed: the commitments stay in the record and are never counted, because a ballot that is not open is never closed. The ballot id is used for good; another ballot on the same subject may be opened at once (B7 looks at open ballots).

**Posted before any vote can be read, and paused until it is settled.** A `void_ballot` is posted only while the ballot's clock is before the first second of its reveal window (VB3a), and from that entry on the ballot's clock stands still. So between the posting and the application nobody, the custodians included, learns a vote of that ballot: the custodians decide whether to apply the act knowing what they knew when they posted it. If the act is applied, the ballot is voided with its commitments sealed. If it is voided by objection, withdrawn, `ended` or left to expire, the ballot goes on from where it stood, with every window as long as it was. A stay and a notice may be posted together; the two pauses overlap and are counted once (section 7.8).

#### 6.19.8 Act `undo_ballot`

A noticed act. Once applied, what a **passed** ballot decided is taken back, by **compare-and-swap**: only if every fact the ballot set still stands exactly as the ballot left it, all of it or nothing, and nothing else is touched.

| Aspect | Rule |
|---|---|
| Target | `id` (string): the id of a ballot. |
| Ground | Any of `GROUNDS` but `moderation`, as for `void_ballot`. |
| Preconditions | Evaluated at the `correction` entry, with `C` the custodian who signs. **UB0.** `id` is not in `S.retired`. Refusal: `ballot {id} ended more than 111 days ago and left the state (no rule reads a ballot after that)`. **UB1.** `S.ballots[id]` exists. Refusal: `no such ballot`. **UB2.** Its `kind` is in `UNDO_KINDS` (`admission`, `advancement`). Refusal: `only an admission or an advancement is undone by a correction (ballot {id} is of kind {kind})`. **UB2a.** The ballot is not one the Sunset counts: not an advancement to the 3rd degree (SY2a). Refusal: `recusal: a ballot that adds a witness, or that advances a member to the 3rd degree, is never stayed, voided or undone by a correction (the Sunset counts both, and the Sunset ends the custodians' keys)`. **UB3.** Its `corrected` is null. Refusal: `ballot {id} was already voided or undone (correction {seq})`. **UB4.** Its `result` is `passed`. Refusal: `only a ballot that passed is undone (ballot {id} is still open)` for an open ballot, or `… (ballot {id} {result})` for one that `failed` or `lapsed`, with its result. **UB5.** For an advancement: `S.members[member]` exists and its `status` is neither `departed` nor `voided`. Refusal: `the undo of ballot {id} has nothing to undo: {member} left, and a record that left is not touched`. **UB6.** `not expired(closed, now, 90)` (wall time; `UNDO_WINDOW_DAYS`): the correction is posted within 90 days of the ballot's close. Refusal: `ballot {id} closed more than 90 days ago (a ballot is undone only by a correction posted within 90 days of its close)`. **UB7.** No record of `S.corrections` has `act = undo_ballot` and this `id`, unless it was overruled (section 4.9). Refusal: `ballot {id} was the target of a undo_ballot once already (correction {seq}): a ballot is the target of a undo_ballot at most once, unless other custodians withdrew it`. **UB8.** `C.member` is not a party to the ballot (`ledger.party_to`: its opener, the `member` or `candidate` of its subject, and for an admission each sponsor in `frozen.vouches`). Refusal: the recusal message of VB4. |
| Subject | `subject.member` of the ballot (advancement) or `subject.candidate` (admission). |
| While pending | Nothing changes and nothing waits. |
| Checked again at the application | UB0 to UB5, then AP6a, then UB8 (for the custodian who posted the act, every co-signer whose key is live and the custodian who applies it), and then the **comparison**. UB6 and UB7 are rules of the day the act is posted: an act posted on the 90th day is applied after it. |
| The members decide first (AP6a) | At the application only, for an admission: no sanction ballot on the candidate is open (`open_sanction_on(candidate)` is none). Refusal: `the undo of ballot {id} is not applied while a sanction ballot on {candidate} is open (ballot {its id}): the members decide first`. |
| The comparison (AP7) | For each field of the ballot's `undo` record (section 6.7), in the order of the record: the fact as it stands now (`ledger._facts`) equals the recorded `after` value. Refusal, at the first that differs: `the undo of ballot {id} no longer applies: {field} is {found!r}, not {after!r} as the ballot left it (nothing is undone unless everything the ballot changed still stands)`. |
| Effect of the application | The ballot's `result = undone` and `corrected` = the `seq` of the correction; then the effect of its kind, below. |

The effect, by kind:

- **`advancement`.** `degree` goes back to the recorded `before` value (one less); `since[degree]`, the date of the degree that is taken back, is removed; and the exam `S.exams[(member, degree)]`, if there is one, gets `lapsed = true`. **The exam is void, with no penalty:** it is not passed and not failed (section 4.5), it supports no new ballot (D4), and the member may open a new exam for that degree at once (E6: a lapsed exam needs no 90 days). The waiting period of the degree is counted from the date of the degree the member still holds, which is in the past. The exam is not given back as passed and unused, as a `void_ballot` does: an undone advancement was decided and applied, the ground of the undo may lie in the examination as much as in the vote, and the entry cannot tell which; giving the exam back would let the same decision be taken again on a record nobody has re-examined. The member's status is not changed, and it is looked at only by UB5 (a record that departed or was voided is not touched): a member suspended or expelled since then loses the degree all the same.
- **`admission`.** The record is **not** replaced by the record it replaced, if there was one. Instead:
  1. `status = voided`; `status_since = now`; `seat_until = null`. This is not a sanction: the record keeps its degree, key, sponsors and history, no ban falls on its sponsors, and nothing is written to `fraud_history`.
  2. **No electorate is touched.** The login stays in the `electors` of every ballot it is in, open or closed, and the votes it revealed are counted at the close like any other (section 6.7, effect 1). A vote it **sealed** before the undo is still revealed: the signer rule lets a `voided` record sign the `ballot_reveal` of a ballot in which it holds a commitment (section 5.2). A vote it had not sealed can no longer be cast.
  3. Its seats as an examiner pass on: for every exam still undecided in which it holds a seat and has not reported, effects 1 to 4 of an `exam_recuse` are applied (section 6.11), exactly as for a member whose key is frozen (section 6.19.1).
  4. `login` is removed from the `vouches` of every record of `S.petitions`, and every record of `S.invitations` whose `by` is `login` is removed. A petition under an open admission ballot keeps the sponsors that ballot froze (`frozen.vouches` is not changed).

  From then on the login is a record that is no longer a membership (`GONE`): it signs nothing but a new `petition` and the reveal of a vote it sealed, cannot depart or rekey, is out of the reach of every sanction but one (below), and enters no new electorate and no new pool. The electorates of ballots already closed still list it, and so may the pool of an exam frozen before the undo and not yet drawn: if the lot then seats it, the seat is one that cannot report, as for a member who left (section 12, point 6). **It may be invited again once 90 days have passed since the undo** (I5 and P1: the wait of a login that departed, `REJOIN_AFTER_DAYS`), by any Master, with the same GitHub account or another; its name and its account are held by the old record exactly as those of a departed member are (section 4.7).

**An undo finds no fraud, and does not keep the members from finding it.** Two rules keep a correction from standing in the place of a judgment. While a sanction ballot on the member is open, the undo of the admission is not applied (AP6a): the members' ballot is decided first, and if it expels the member the comparison then refuses the undo, because the status is no longer the one the admission left. And until 90 days have passed since an undo, the `voided` record may still be expelled for fraud by a sanction ballot (SN2, SN2a in section 6.4.4), with the ban of the sponsors and the entry in `fraud_history`; the 90 days in which the login cannot be invited again are the same 90 days.

**Nothing cascades, and no vote is changed.** The votes the person cast, in ballots that have closed and in ballots that are still open, the reports they gave as an examiner, the vouches under which others were admitted and the works they recorded all stand. An undo takes back the facts of one ballot and removes the person from the seats, petitions and invitations that are still open; it re-decides nothing, and it changes the electorate and the count of no ballot. (A correction that could take an elector out of an open ballot would be a way to turn that ballot.) The petition that an admission consumed is not put back, and neither are the examinations of an earlier membership that the admission removed.

**Newest first.** Because the comparison refuses an undo once a later ballot changed the same fact, a chain is undone from its end: a member admitted and then advanced has `member.degree = 2`, which is not the `1` the admission left, so the advancement is undone first and the admission after it. Each undo must be **posted** within 90 days of the close of its own ballot.

What the comparison protects against, and what it does not: it reads only facts that a decision of the members sets (a status, a degree, the date of a degree), never one the person can change alone, so a member cannot escape an undo by replacing a key or recording a work. A member who **departs** changes `member.status`, and the undo of the admission is then refused: the person has left, and comes back only by a new invitation after 90 days.

#### 6.19.9 The life of a noticed act

A noticed act is in exactly one condition at any time `now` (`State.noticed_status`). The condition is **computed** from stored facts and from `now`; no entry marks a notice as over or an act as expired.

```
                    posted by `correction` at time T        (signers = [author])
                                   │
                                   ▼
                    ┌──────────────────────────────┐    correction_cosign: signers grow, up to the threshold
                    │ pending      T ≤ now < T+14d │    correction_object: objections grow
                    └──────────────┬───────────────┘
                                   │ time alone
                                   ▼
                    ┌──────────────────────────────┐    correction_cosign, correction_object: as above
                    │ ready     T+14d ≤ now ≤ T+21d│
                    └──────────────┬───────────────┘
                                   │ correction_apply, with every check of section 6.25
                                   ▼
                                applied                 (final: the effect happened, once)

 from pending or ready, and final:
   void        objections reached max(1, ⌈E / 5⌉)                          (correction_object)
   withdrawn   its poster, or enough other custodians, withdrew it         (correction_withdraw)
   ended       the key of the custodian who posted it is no longer live    (time, custodian_revoke, a removal ballot, the Sunset)
   expired     now > T + 21 d and nobody applied it                        (time alone)
```

| Condition | Holds when (the first that does) | Final |
|---|---|---|
| `applied` | `applied ≤ now` | yes |
| `void` | `void ≤ now` | yes |
| `withdrawn` | `withdrawn ≤ now` | yes |
| `ended` | `custodian_end(S.custodians[by]) ≤ min(now, T + 21 d)` | yes |
| `expired` | `now > T + 21 d` | yes |
| `ready` | `now ≥ T + 14 d` | no |
| `pending` | otherwise | no |

Rules that follow:

1. **Only a pending or a ready act can be co-signed, withdrawn or applied** (CS3, CW2, AP3), and only a ready one applied (AP4). The five final conditions are final: `applied`, `void` and `withdrawn` are stored and set once, a custodian key never becomes live again, and time does not run back.
2. **An act is applied at most once.** `applied` is set by one `correction_apply` and makes every later one fail (AP2).
3. **The notice is wall time**: 14 days to the second from the time of the `correction` entry, whatever was halted or stayed in between. A halt does not stretch it, and custodian entries and objections are accepted during a halt. **A pending `void_ballot` pauses its ballot** for exactly the time it is pending (`void_span`, section 4.9); a pending `undo_ballot` pauses nothing.
4. **Objections.** From the entry that posts the act until it is applied, the objections of section 6.21 can void it: at `max(1, ⌈E / 5⌉)` of them it is `void` for good and can never be applied. After it is applied, objections are still accepted for 90 days, **for the record only**: they are appended to `objections`, `void` is not set, and the effect is not reversed. An act that was never applied (withdrawn, ended, expired) can be objected to for 90 days from its entry, and is then marked `void`.
5. **The key of the custodian who posted it must stay live** until it is applied. If that key lapses, is revoked or is removed by ballot, the act is `ended` whoever else signed it. A co-signer whose key is no longer live simply stops counting toward the threshold; another custodian may co-sign in their place.
6. **One per ballot, unless the other custodians overruled it.** A ballot is the target of at most one `void_ballot` and at most one `undo_ballot` (VB3, UB7). An act that was voided by objection, withdrawn by its own poster, ended or expired is not posted again. One that custodians other than its poster withdrew does not count: the withdrawal of several does not use up, against the poster's judgment, the one time the act may be posted. An act voided by objection is in any case held by N7 for 90 days.

### 6.20 `correction_withdraw`

**Signer:** a custodian, with its custodian key. **Function:** `ledger._correction_withdraw`.

The custodian who posted a correction withdraws it alone. The others withdraw it together: as many of them as a noticed act needs keys (`S.custodian_threshold`).

| Body field | Type | Constraint |
|---|---|---|
| `seq` | integer, required | The `seq` of a correction in force, or of a noticed act still pending. |

| # | Precondition | Refusal message |
|---|---|---|
| CW1 | `S.corrections[seq]` exists. | `no such correction` |
| CW2 | That correction is an immediate act in force at `now` (section 7.8), **or** a noticed act that is `pending` or `ready` at `now` (section 6.19.9). | `correction {seq} is not in force or pending (nothing to withdraw)` |
| CW3 | `actor` is not in the correction's `withdrawals`. | `{actor} already signed the withdrawal of correction {seq}` |

Effects:

1. `actor` is appended to the correction's `withdrawals`.
2. If `actor` is the correction's `by`, **or** the number of custodians in `withdrawals` whose key is live at `now` is at least `S.custodian_threshold`: `withdrawn = now` and `withdrawn_by = actor`. Otherwise the correction stays as it is, in force or pending, and the signature stands for a later one to complete.

Notes:

- **One custodian of several does not undo the act of another.** Where the genesis set a threshold of two, a single key (stolen, or mistaken) cannot lift a freeze another custodian placed, cancel the recovery that follows it, or cancel a pending act: it takes the poster, or two. Where the threshold is one, every custodian key withdraws alone, as every one of them posts and applies alone. A signature in `withdrawals` of a key that has since lapsed or been removed does not count.
- A noticed act that is withdrawn is canceled for good: it is never applied, and a ballot it paused goes on at once. An act that was applied cannot be withdrawn. For an immediate act, the interval of the act ends at `now` (section 7.8): a member is unfrozen, a ballot resumes, a halt or a hold is lifted, for every entry that follows, one stamped in the same second included. A withdrawal undoes nothing that happened while the act was in force: a recused examiner is not seated again, and the time a ballot was paused stays out of its clock.
- **What a withdrawn act leaves behind depends on who withdrew it** (`ledger._overruled`). Withdrawn by its own poster, it is spent: it still counts in FK3, HR4, VB3 and UB7, so no custodian renews a freeze, or posts a noticed act twice, by withdrawing and posting again. Withdrawn by the others (`withdrawn_by ≠ by`), it leaves no wait in FK3 or HR4 and does not use up the one `void_ballot` or `undo_ballot` of its ballot. Either way it still counts in N6, N6a, SY3 and HT1, and may still be objected to (section 6.21). A note is no correction and cannot be withdrawn (CW1).

### 6.21 `correction_object`

**Signer:** an active member (section 5.2), who must be a Master Builder. It is accepted during a halt. A member whose key is frozen cannot sign it (section 6.19.1). **Function:** `ledger._correction_object`.

| Body field | Type | Constraint |
|---|---|---|
| `seq` | integer, required | The `seq` of a correction. |

`c` is the correction `S.corrections[seq]` and `linked` is `S.custodians[c.by].member`, the member account of the custodian who signed it.

| # | Precondition | Refusal message |
|---|---|---|
| J1 | `S.corrections[seq]` exists. | `no such correction` |
| J2 | (None. A note is no record of `S.corrections`: an objection that names the `seq` of a note is refused by J1.) | |
| J3 | The actor's `degree ≥ 3`. | `only Master Builders may object to a correction` |
| J4 | `actor ≠ linked`. | `{actor} is the member of the custodian who made correction {seq} and cannot object to it` |
| J4a | `actor` is not the `member` of any custodian in `c.signers`. | `{actor} is the member of a custodian who co-signed correction {seq} and cannot object to it` |
| J5 | `actor ≠ c.subject`. | `{actor} is the target of correction {seq} and cannot object to it` |
| J6 | `c.void` is null. | `correction {seq} is already void` |
| J7 | `not expired(t, now, 90)` (wall time; `OBJECTION_DAYS`), with `t = c.applied` for a noticed act that was applied and `t = c.time` otherwise. | `objections to correction {seq} closed 90 days after it`; for a noticed act that was applied, `objections to correction {seq} closed 90 days after it was applied` |
| J8 | `actor` is not in `c.objections`. | `already objected to correction {seq}` |

Effects:

1. `actor` is appended to `c.objections`.
2. `E` = the number of logins of `masters(now)` that are neither `linked`, nor the `member` of a custodian in `c.signers`, nor `c.subject`. If `c.applied` is null and `len(c.objections) ≥ max(1, ⌈E / 5⌉)` (`ledger.objections_needed`; `⌈E / 5⌉ = (E + 4) div 5`): `c.void = now`.

Notes:

- **Void for good.** A void correction is never in force again, cannot be withdrawn, co-signed or applied, and takes no further objection. An immediate act that was in force ends at the time of the entry that voided it (section 7.8); one that had already ended is marked void and nothing else changes. A noticed act that is voided before it is applied is never applied. With `E ≤ 5`, one objection is enough.
- **Once applied, a noticed act is not reversed by objection.** Objections are accepted for 90 days after the application and are recorded in `objections`; `void` stays null and the effect stands. The members' remedy against an applied act is their own: a new ballot (an admission, an advancement, a witness ballot), or the removal of the custodian (section 6.4.6).
- `E` is counted at each objection, with the Masters active and not dormant at that moment; the objections already recorded are not counted again. The objector is an active member, dormant or not (section 5.2, rule 3), so an objection can come from a Master who is not in `E`.
- The target of a freeze cannot end their own freeze (J5): if the key is in a thief's hands, the thief's objection must not count. Nor can they object to any other correction while their key is frozen: an objection is not among the entries a frozen member signs (section 6.19.1). J5 also keeps the subject of a stayed, voided or undone ballot from objecting to that correction.
- The window of J7 is wall time, to the second, and is the same for an act in force and for one that has ended: a correction is answerable for 90 days, and a noticed act for 90 days more from its application.
- The entry credits the objector with activity (section 5.3).

### 6.22 `custodian_alive`

**Signer:** a custodian, with its custodian key. **Function:** `ledger._custodian_alive`.

Body: the empty object `{}`. Any field is refused (C10).

| # | Precondition | Refusal message |
|---|---|---|
| AL1 | `now − alive ≥ 24 h` (`ALIVE_INTERVAL`), with `alive` the custodian's last sign of life: the genesis (or the `custodian_claim_apply` that named it), or its latest `custodian_alive`. | `the custodian {actor} gave a sign of life less than 24 hours ago (at most one custodian_alive per custodian in 24 hours)` |

The signer rule requires the key to be live.

Effects:

1. `S.custodians[actor].alive = now`.

Notes: this is the only entry that counts as a sign of life. A custodian key lapses when `expired(alive, now, 180)` in wall time (`CUSTODIAN_SILENCE_DAYS`): a `correction`, a `note` and a `correction_withdraw` leave `alive` unchanged. The time of the genesis (or of the `custodian_claim_apply` that named it) is the first sign of life. A key that has lapsed cannot sign this entry, so a lapse is permanent. A sign of life postpones the silence deadline and nothing else: it does not move the end of the term or the Sunset (section 7.9). One sign in 24 hours is the most the ledger takes (AL1; section 5.4).

### 6.23 `custodian_revoke`

**Signer:** the **revoke key** of the custodian named by `actor`, and `actor` MUST equal `body.name` (section 5.2). **Function:** `ledger._custodian_revoke`.

| Body field | Type | Constraint |
|---|---|---|
| `name` | string, required | The custodian whose key is removed: the actor. |

Preconditions: none beyond the signer rule, which requires the key to be live.

Effects:

1. `S.custodians[actor].revoked = now`.

Notes: the custodian key is removed at once. From the next entry on, one stamped in the same second included, it signs nothing; every immediate act it had in force ends at `now` (section 7.8); every noticed act it posted that was still pending is `ended` and can never be applied (section 6.19.9); and its revoke key signs nothing more either. The Master Builders can do the same by ballot (section 6.4.6). The record stays in `S.custodians`: the name and the two keys remain held forever (section 4.7). This is the one power of a revoke key. A revoke key cannot sign a correction, and a custodian key cannot sign a revocation.

### 6.24 `correction_cosign`

**Signer:** a custodian, with its custodian key (section 5.2). **Function:** `ledger._correction_cosign`.

Another custodian key endorses a pending noticed act. It is needed until the act has as many signers as `S.custodian_threshold`; where the threshold is 1 the entry is never accepted, because the custodian who posted the act is its first signer.

| Body field | Type | Constraint |
|---|---|---|
| `seq` | integer, required | The `seq` of a noticed act that is pending or ready. |

`c` is the correction `S.corrections[seq]`.

| # | Precondition | Refusal message |
|---|---|---|
| CS1 | `S.corrections[seq]` exists. | `no such correction` |
| CS2 | `c.class = noticed`. | `correction {seq} is not a noticed act (an immediate act is the act of one custodian key and takes effect by itself)` |
| CS3 | `noticed_status(c, now)` is `pending` or `ready` (section 6.19.9). | `correction {seq} was already applied (a correction is applied once)` when it is `applied`; otherwise `correction {seq} is {status}: nothing to co-sign`, with `status` = `void`, `withdrawn`, `ended` or `expired` |
| CS4 | `actor` is not in `c.signers`. | `{actor} already signed correction {seq}` |
| CS5 | `len(live_signers(c, now)) < S.custodian_threshold`. | `correction {seq} already has the {threshold} custodian signature(s) it needs` |
| CS6 | The member the actor is linked to is not a party to the ballot `S.ballots[c.target.id]` (`ledger.party_to`). | the recusal message of VB4, for the actor |

Effects:

1. `actor` is appended to `c.signers`.

Notes: a co-signature changes nothing else and is not a correction: N6 does not count it. A custodian whose key is no longer live at the application does not count toward the threshold (AP5), and CS5 counts only live signers, so another custodian may then co-sign.

### 6.25 `correction_apply`

**Signer:** a custodian, with its custodian key: any live custodian, a signer of the act or not (section 5.2). **Function:** `ledger._correction_apply`.

The one entry that gives a noticed act its effect. Everything that made the act lawful when it was posted is asked again, as things stand at this entry.

| Body field | Type | Constraint |
|---|---|---|
| `seq` | integer, required | The `seq` of a noticed act that is ready. |

`c` is the correction `S.corrections[seq]`, `T = c.time`, and `b` is the ballot `S.ballots[c.target.id]`.

| # | Precondition | Refusal message |
|---|---|---|
| AP1 | `S.corrections[seq]` exists. | `no such correction` |
| AP2 | `c.class = noticed`; and `c` is not `applied`. | the message of CS2; `correction {seq} was already applied (a correction is applied once)` |
| AP3 | `noticed_status(c, now)` is `pending` or `ready`: `c` is not void, not withdrawn, the key of the custodian who posted it is still live, and `now ≤ T + 21 d`. | `correction {seq} is {status}: nothing to apply`, with `status` = `void`, `withdrawn`, `ended` or `expired` |
| AP4 | `now ≥ T + 14 d` (wall time; `NOTICE_DAYS`). | `correction {seq} is under notice until {T + 14 d} (14 days after it was posted)` |
| AP5 | `len(live_signers(c, now)) ≥ S.custodian_threshold`. | `correction {seq} has {n} of the {threshold} custodian signature(s) it needs` |
| AP6 | Every precondition of the act that is checked again at the application holds as things stand now (VB1, VB2, VB2a and VB4 for a `void_ballot`; UB0 to UB5 and UB8 for an `undo_ballot`), with recusal asked of each custodian in `live_signers(c, now)` and of the actor, in that order. | the messages of sections 6.19.7 and 6.19.8 |
| AP6a | For the `undo_ballot` of an admission, evaluated after UB5 and before UB8: no sanction ballot on the candidate is open. | `the undo of ballot {id} is not applied while a sanction ballot on {candidate} is open (ballot {its id}): the members decide first` |
| AP7 | For an `undo_ballot`: the comparison of section 6.19.8. | `the undo of ballot {id} no longer applies: {field} is {found!r}, not {after!r} as the ballot left it (nothing is undone unless everything the ballot changed still stands)` |

Effects, applied only after every precondition has passed:

1. `c.applied = now`; `c.applied_by = actor`.
2. `b.corrected = seq`.
3. The effect of the act: section 6.19.7 for a `void_ballot`, section 6.19.8 for an `undo_ballot`.

Notes:

- **The window is closed on both sides.** An act is applied from `T + 14 d` through `T + 21 d`, both seconds included, in wall time. After that it has expired and can never be applied; the same act cannot be posted again on the same ballot (VB3, UB7). An undo that AP6a holds back while a sanction ballot runs is applied when that ballot has closed, if the 7 days have not run out and the comparison still holds; a sanction ballot that stays open through them lets the undo expire (section 12, point 55).
- **Applied once.** AP2 refuses a second application, and the effect of the first has also made AP6 fail: a voided ballot is no longer open, and an undone one no longer `passed`.
- **All or nothing.** Every check precedes the first change, so an undo that fails the comparison on any field changes none.
- The entry is accepted during a halt, like every custodian entry. It credits nobody.

### 6.26 `rekey_recover`

**Signer:** the member's **new** key, `body.key` (section 5.2); `actor` is the member's login. **Function:** `ledger._rekey_recover`.

A member whose key is lost, or in other hands, asks to go on with a new one. This is not a correction, and no custodian decides it. The request changes no key. It opens a **recovery** (section 4.10) that Master Builders co-sign (section 6.27), that whoever holds the old key can stop (section 6.28), that the Master Builders may oppose where no freeze stands behind it (section 6.30), and that the new key completes after its notice (section 6.29).

There are two ways into a recovery, and one rule that crosses both:

| | After a freeze | Open (no freeze) | Final (either kind) |
|---|---|---|---|
| Asked when | a `freeze_key` of the login is in force | no freeze is in force: no custodian key is live, or no custodian froze the key (a recovery never needs a custodian) | the previous recovery of the same membership was stopped by the old key |
| Co-signers needed (`ledger.cosigners_needed`) | `min(2, m)` | `min(3, m)`, and not all of them sponsors of the member while a Master who is not one exists | `min(3, m)` |
| The notice starts | at the request | at the entry that completes the co-signatures (the request itself when `m = 0`) | as for its kind |
| The notice lasts | 21 days; 45 when lowered | 30 days; 45 when lowered | 45 days when lowered (`m < 3`), else as for its kind |
| The old key is frozen | from the freeze, and while the recovery is under way | from the start of the notice | as for its kind |
| The old key can stop it | yes | yes | **no** |
| The Master Builders stop it by | objecting to the freeze (section 6.21) | opposing it (section 6.30) | as for its kind |
| Dropped: 30 days after the request without all its co-signatures | it needs only the co-signatures given by then, never fewer than one where another Master exists; the notice is 45 days and starts at the drop moment, and the old key stays frozen meanwhile | the same, and they may all be sponsors; the notice starts at the drop moment when those given suffice, else at the co-signature that makes them suffice | as for its kind |

`m` is the number of active Master Builders other than the member **who answered within the last year** (`ledger.answering_masters`: the logins of `masters(now)` without `login` whose `heard`, the latest of their revealed votes and reports, or whose `since[3]`, the day they reached the 3rd degree, is not `expired(…, now, 365)`, `ANSWER_DAYS`), counted at each entry that reads it: the request, each co-signature and the application. A Master who signs a work a year and answers nothing keeps every other power, opposition included, and is not waited for: without this, every request waited forever for the co-signature of such a Master, and a lost key, or a thief's departure, was never undone (point 76). A recovery is **lowered** at `now` when `min(nominal, m) < nominal`, with `nominal` its number (2, 3, or 3 for a final one: `ledger.nominal_cosigners`): no requirement exceeds the people who exist, and a lowered one is balanced by a longer notice, `RECOVER_LOWERED_NOTICE_DAYS` = 45 days.

**The drop** (`ledger.dropped`, `Recovery.drop_time`, `Recovery.given_at_drop`). Peers who never answer do not hold a request forever. Its drop moment is `drop_time = time + 30 d` (`RECOVER_DROP_DAYS`, wall time). At `now ≥ drop_time` the request is **dropped** when the drop lowers what it needs, `max(given_at_drop, 1 if m > 0 else 0) < min(nominal, m)`, and, for an open recovery, its notice had not begun by the drop moment (`notice` null or later than `drop_time`); after a freeze that guard alone decides. Who the co-signers are now is not asked here: a co-signer who is no longer an active Master still counts toward `given_at_drop`, and is left out only where the co-signers are counted as standing (RC6, RA5). `given_at_drop` counts the co-signatures given by the drop moment: `dropped`, which the first co-signature at or after it records (section 6.27, effect 1), or `len(cosigners)` while none came after it. A dropped request needs `min(min(nominal, m), max(given_at_drop, 1 if m > 0 else 0))` co-signers (`cosigners_needed`): only those already given, and never fewer than one where another Master Builder exists. Its notice is 45 days and starts (`recovery_start`): after a freeze, at `drop_time`; for an open recovery, at `drop_time` when the co-signatures given by then are `cosigned` as things stand, and otherwise at the co-signature that makes them so (`notice`, RC6). A notice that starts at the drop moment starts with no entry. No start of a notice asks the cap on frozen keys (FK4): it bounds the freezes of the custodians, and a recovery under way counts in it, but a recovery is never held back by it (RR10, RC6).

| Body field | Type | Constraint |
|---|---|---|
| `key` | string, required | A valid key (section 2.6), of either type: the new key. It signs this entry. |
| `proof` | string, required | A signature by the new key over the proof message of a `rekey` (section 6.18): `rekey_message(actor, S.members[actor].key, body.key)`, which binds the login, the key the ledger holds and the new key. |

RR1 and RR2 are evaluated by the signer rule, before the signature (section 5.2):

| # | Precondition | Refusal message |
|---|---|---|
| RR1 | The record `S.members[actor]` is recoverable (section 5.2): it exists and its `status` is not in `REKEY_BLOCKED`, or it departed (`left` is set). A suspended member may ask. | `{actor} is not a member whose key can be recovered (not a member, departed, expelled or voided)` |
| RR2 | `body.key` is a valid key. | `keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)` |
| RR3a | The member's `status` is not in `GONE`, **or** it is `departed` with `left` set and `status_since` (the departure) set, and either `not expired(status_since, now, 30)` (`DEPART_RECOVER_DAYS`) or `follows`: the record `l = S.recoveries[actor]` exists, has the same `admitted` as the member's membership and `l.departure = status_since` (it was asked in time for this departure, whatever ended it: section 6.15), and `not expired(max(l.time, l.objected when set), now, 150)` (`DEPART_FOLLOW_DAYS`). | `{actor} departed more than 30 days ago (a recovery reverses a departure only when it is asked before it or within 30 days of it, or follows one so asked within 150 days of that one's request, or of the old key's stop of it)` |
| RR4 | `S.recoveries` has no record of `actor` that is alive (`requested`, `pending` or `ready`). | `a recovery of the key of {actor} is already pending (entry {seq})` |
| RR5 | If `S.recoveries[actor]` exists: `waited(its time, now, 90)` (wall time; `RECOVER_INTERVAL_DAYS`). | `the last recovery of the key of {actor} was requested less than 90 days ago (one request per member in 90 days)` |
| RR6 | If that record has `objected` set: `waited(objected, now, 90)`. | `the old key of {actor} stopped a recovery less than 90 days ago (the next request, 90 days after that, cannot be stopped by the old key and needs 3 co-signers, or as many other Master Builders as exist)` |
| RR7 | `key_holders(body.key, now)` is empty. For the first pair found: when it is `("member", actor)`, the first message; otherwise the second. | `this is already your key`; `this key is already used by {other} (one key per login: members, witnesses and petitions)` |
| RR8 | The point of `body.key` is not in `S.known_keys`. | `this key was used in this ledger before (a key that was ever registered here is never registered again)` |
| RR9 | `sig_ok(rekey_message(actor, member.key, body.key), body.proof, actor, body.key)`. | `bad proof: the new key must sign the rekey message (login, old key, new key)` |
| RR10 | (None. An open recovery that needs no co-signer, `r.freeze` null and `m = 0`, final or not, starts its notice at this entry, whatever else is frozen: the cap on frozen keys, FK4 of section 6.19.1, bounds freezes only.) | |

Effects:

1. `S.recoveries[actor] = Recovery(login = actor, key = body.key, seq, time = now, freeze, admitted = the membership of the member, cosigners = (), objected = null, applied = null, notice, final, opposed = (), void = null)`, with `freeze` = the `seq` of the `freeze_key` of `actor` in force at `now` (`frozen(actor, now)`), or null for an open recovery; `final` = the record this one replaces exists, has `objected` set and has the same `admitted`; `notice = now` for the open recovery of RR10, else null; `dropped = null`; and `departure` = the member's `status_since` when the record is `departed`, else null.
2. The point of `body.key` is added to `S.known_keys`.

Notes:

- **A key the ledger does not hold signs this entry.** It is the second and last case of that, after the `petition` (section 5.2, rule 7). What replay asks of it: the record is recoverable; the key is new to the ledger; and it proves itself. **Replay asks for no freeze**, also while a custodian key is live, because a custodian who never answers would otherwise lock every lost key out for good; of a member who departed, RR3a asks only that the request come within 30 days of the departure, or follow, within 150 days, a recovery asked in time for it. That the key belongs to the member's GitHub account, and that the pull request comes from that account, is the gate of section 9.3. The entry gives the new key no power: it signs nothing else until section 6.29.
- **Without a freeze, the peers stand in for it.** Without a custodian, or without one who answers, no key is frozen, and a ledger whose custodians have all ended (the Sunset, the term, silence, removal) or are silent would otherwise lose every member whose key is lost. An open recovery asks more of the peers instead: three co-signers and not two, who are not all the member's sponsors; a notice of 30 days and not 21, which starts only when the co-signatures are complete; and the right of the Master Builders to oppose (section 6.30). Until the notice starts, nothing is frozen and the old key signs as before, so a request alone takes nothing from the member.
- **Never more co-signers than exist** (on every path, the final recovery included). With fewer other active Master Builders than the number asked, all of them are needed and that is enough (`min`), and the notice is 45 days: two founders recover each other's keys, and a ledger of one Master is not a dead end. **The only Master Builder needs no co-signer.** After a freeze, the freeze (by a custodian key, which a founder who is the custodian's member holds apart from the member key) and the 45 days stand behind the request. Without a freeze, the request rests on the 45 days of notice, on the old key's right to object, and on the identity gate of section 9.3 (the request comes from the member's own GitHub account, with a key that account lists): replay itself asks nothing more of it (section 5.2, rule 7; section 12, point 62).
- **Nor do peers who never answer hold it.** A request that has been open 30 days without all its co-signatures is dropped (above): it needs only those given by then, and at least one where another Master Builder exists, with the 45 days of notice. One answering Master, the notice and the old key's objection then stand behind it.
- **A recovery the old key stopped is followed by one it cannot stop.** Whoever holds the old key can stop a recovery (section 6.28); if that is a thief, a rule that let the old key stop every recovery would lock the member out forever. So the request that follows a stopped one (RR6: 90 days later at the earliest; `final`) is not stopped by the old key, and needs three co-signers, or as many other Master Builders as exist, with the longer notice when that is fewer: the judgment passes from the key to the peers. (Three flat would leave a membership of fewer than four Masters locked out for good once a thief had stopped one recovery.) The Master Builders still stop a final recovery they doubt, by objecting to its freeze or by opposing it. A final recovery that ends without being applied is followed by an ordinary one.
- **While the recovery is under way the old key stays frozen**, also after the freeze it followed has run its 30 days (section 5.2, the freeze gate): the holder of the old key signs only what a frozen member signs. The login counts among the frozen keys of FK4, and its seats as an examiner are passed over (sections 6.9 and 6.11). A recovery is under way for at most 60 days from the start of its notice (`RECOVER_EXPIRY_DAYS`); an open recovery that waits for its co-signers is alive for at most 60 days from the request.
- **It ends by itself**, with no entry, when 60 days have passed without its application (`expired`); when the freeze it followed is withdrawn or voided by objection, at any time before its application, also after that freeze has run out (`canceled`); or when the login is admitted anew (`canceled`: a recovery never reaches a membership it was not asked for). The Master Builders can therefore stop a recovery after a freeze by objecting to that freeze (section 6.21), for 90 days from it. A freeze that merely ran its time, or ended with the key of its custodian, leaves the recovery under way.
- The new key of a request that was not applied stays in `S.known_keys`: the next request needs another key (RR8).
- RR5 and RR6 are counted on the login, across memberships; `final` is of one membership.
- The entry adds no activity (section 5.3). It is accepted during a halt (`HALT_ALLOWED`) and never counted by C12a: RR5 bounds it.

### 6.27 `rekey_cosign`

**Signer:** an active member (section 5.2), who must be a Master Builder and not the member whose key is recovered. **Function:** `ledger._rekey_cosign`.

A Master Builder answers that the person asking for the new key is the member.

| Body field | Type | Constraint |
|---|---|---|
| `login` | string, required | `LOGIN_RE`: the member whose recovery is co-signed. |

`r` is the recovery `S.recoveries[login]`.

| # | Precondition | Refusal message |
|---|---|---|
| RC0 | `login` matches `LOGIN_RE`. | `login must be a valid GitHub login` |
| RC1 | A recovery of `login` is alive at `now` (`recovery_alive(login, now)`: `requested`, `pending` or `ready`). | `no recovery of the key of {login} is pending` |
| RC2 | The actor's `degree ≥ 3`. | `only Master Builders may co-sign a key recovery` |
| RC3 | `actor ≠ login`. | `a member cannot co-sign the recovery of their own key` |
| RC4 | `actor` is not in `r.cosigners`. | `already co-signed the recovery of the key of {login}` |
| RC5 | `actor` is not in `r.opposed`. | `{actor} opposed the recovery of the key of {login} and cannot co-sign it` |
| RC6 | (None. A co-signature **completes** an open recovery when `recovery_start(r, now)` is null and, with `actor` added, `ledger.cosigned` holds, below; it is accepted whatever else is frozen: the cap on frozen keys, FK4 of section 6.19.1, bounds freezes only.) | |

Effects:

1. If `r.dropped` is null and `now ≥ drop_time(r)`: `r.dropped = len(r.cosigners)` (before this co-signature), the co-signatures given by the drop moment (section 6.26). Whether the co-signature completes the recovery (RC6) is decided before it, with `recovery_start(r, now)` as it stood before this entry.
1a. `actor` is appended to `r.cosigners`.
2. If the co-signature completes an open recovery (RC6): `r.notice = now`. From this entry on the recovery is under way: the old key is frozen and the notice (30 days, or 45 when lowered) runs.

**Complete** (`ledger.cosigned(S, r, cosigners, now)`) means both: the number of **standing** co-signers (`ledger.standing_cosigners`: logins of `cosigners` that are keys of `S.members` whose record `is_active(now)` and has `degree ≥ 3`) is at least `cosigners_needed(S, r, now)`; and, for an open recovery, not `only_sponsors`: the standing co-signers are not all in the member's `sponsors` while some login of `answering_masters(S, login, now)` (the Masters `m` counts) is in none of them. `only_sponsors` never holds once the request is `dropped` (section 6.26): then the co-signatures given are enough, whoever gave them, and the 45 days of notice, the old key's objection and the Masters' opposition stand behind it.

Notes: any number of Masters may co-sign. The co-signers who are still active Masters at the application are counted there again (RA5, RA6). RC0 keeps a string that is no login out of the refusal of RC1, which quotes it. RC3 is reached where an open recovery is still `requested` and the old key not yet frozen: the member cannot answer for their own request. The member the custodian who froze the key is linked to may co-sign like any other Master. The cap of FK4 never refuses a co-signature (RC6): a login that a freeze, or a recovery of its own, keeps frozen holds back the freezes of other logins, never the recovery of another login (section 12.7, point 71). A co-signature credits the Master with activity. It is accepted during a halt and never counted by C12a; a frozen key never co-signs (section 5.2, rule 11).

### 6.28 `rekey_object`

**Signer:** the member, with **the key the ledger holds** for them, the old key (section 5.2): a record that is recoverable, a suspended member included. It is accepted from a frozen key and during a halt, it is never counted against the entries of a day (section 5.4), and any pull request may carry it (section 9.3). **Function:** `ledger._rekey_object`.

Body: the empty object `{}`. Any field is refused (C10).

| # | Precondition | Refusal message |
|---|---|---|
| RO1 | A recovery of `actor` is alive at `now`. | `no recovery of the key of {actor} is pending` |
| RO2 | That recovery is not final. | `the recovery of the key of {actor} follows one the old key stopped, and the old key cannot stop this one (it needs 3 co-signers, or as many other Master Builders as exist; Master Builders may object to the freeze it follows, or oppose a recovery asked without one)` |

Effects:

1. `S.recoveries[actor].objected = now`.

Notes: the recovery is canceled for good; its new key can never complete it. The old key is no longer held by the recovery: it stays frozen only for what is left of a freeze, and no new request for that login is accepted for 90 days (RR6). **Whoever holds the old key can stop a recovery once, and cannot complete one**: this entry needs the old key, and sections 6.26 and 6.29 need the new one. If the holder of the old key is a thief, the member asks again after the 90 days, and that recovery is final (RO2): three Master Builders, or as many others as exist, and not the old key, decide it. The entry adds no activity (section 5.3).

### 6.29 `rekey_recover_apply`

**Signer:** the new key of the member's recovery, `S.recoveries[actor].key` (section 5.2); `actor` is the member's login. **Function:** `ledger._rekey_recover_apply`.

Body: the empty object `{}`. Any field is refused (C10).

RA1 and RA2 are evaluated by the signer rule, before the signature. `r` is `S.recoveries[actor]`.

| # | Precondition | Refusal message |
|---|---|---|
| RA1 | The record `S.members[actor]` is recoverable (RR1). | `{actor} is not a member whose key can be recovered (not a member, departed, expelled or voided)` |
| RA2 | `r` exists, and none of `r.applied`, `r.objected` and `r.void` is set. | `no recovery of the key of {actor} is pending` |
| RA3 | The membership of the member is `r.admitted`; `recovery_status(r, now)` is not `canceled`; and is not `expired`. | `the recovery of the key of {actor} was asked for an earlier membership of the login, and ended with it`; `the recovery of the key of {actor} ended when the freeze it followed (correction {r.freeze}) was withdrawn or voided`; `the recovery of the key of {actor} expired at {recovery_end} (60 days after it was requested)`, or `… (60 days after its notice began)` when its notice began after the request (an open recovery, or a dropped one) |
| RA3a | The status is not `requested`: the notice of an open recovery has started. With `n` the number of standing co-signers and `k = cosigners_needed(S, r, now)`. | `the recovery of the key of {actor} has {n} of the {k} co-signatures of active Master Builders that start its notice`, followed by `, and one of them must not be a sponsor of the member` when `only_sponsors` holds |
| RA4 | `now ≥ recovery_notice_end(r, now)` (wall time); the status is then `ready` when RA5 and RA6 hold too. With `d = recovery_notice_days(r, now)`. | `the recovery of the key of {actor} is under notice until {recovery_notice_end} ({d} days after its notice began`, then `; {d} because it was open 30 days without all its co-signatures)` when the recovery is dropped, `; {d} because fewer Master Builders exist than the {nominal} co-signers it asks for)` when `d` is 45 otherwise, and `)` else |
| RA5 | `n ≥ k`: at least `cosigners_needed(S, r, now)` logins of `r.cosigners` are standing at `now`. | `the recovery of the key of {actor} has {n} of the {k} co-signatures of active Master Builders it needs` |
| RA6 | Not `only_sponsors(S, r, r.cosigners, now)` (an open recovery that is not dropped; section 6.27). | `the co-signers of the recovery of the key of {actor} are all sponsors of {actor}: a Master Builder who is not one must co-sign too` |

Effects:

1. If `r.freeze` is not null and the freeze `S.corrections[r.freeze]` is in force at `now`: its `released = now`. The freeze ends with this entry (section 7.8).
2. The member's `key = r.key` and `last_rekey = now`.
3. `r.applied = now`.
4. **A departure signed with the old key is reversed.** If the member's `status` is `departed` and `left` is not null: `status` and `status_since` become the values of `left` (null where `left` has none); `seat_until` becomes the value of `left` only while `len(seats(now)) < 33` (`COUNCIL_SEATS`; a draw may have filled the seat since the departure), and null otherwise; and `left` becomes null.

Notes:

- **From the next entry on** the member's signer key is the new key, and nothing is frozen: the old key signs nothing more for this login, and it can never be registered again by a `rekey` or a recovery, by anyone (it is in `S.known_keys`).
- **What a recovery cannot do without**: after a freeze, the freeze (a request dies with a freeze that is withdrawn or voided), the co-signers (RA5), the notice (RA4: 21 days of wall time, or 45 when lowered or dropped, in which the holder of the old key may object, also during a halt) and, unless it is final, the silence of the old key (RA2). An open recovery: the co-signers, who are not all sponsors (RA5, RA6), the 30 days from their completion, or 45 when lowered or dropped (RA3a, RA4), the silence of the old key unless it is final, and no voiding opposition (RA2). **It never needs a custodian.**
- **The co-signers are counted as things stand at this entry**, like every condition of an application: a co-signer who is no longer an active Master Builder does not count, and `cosigners_needed` reads the Master Builders of this moment.
- The window is closed on both sides: from `recovery_notice_end` through `recovery_end`. It does not need the freeze to be still in force.
- **Effect 4 and Landmark VII.** Any `depart` may have been signed by whoever else holds the key; the ledger cannot tell (section 6.15), and RR3a bounds the time in which a recovery that reverses it may be asked. The departure took effect when it was signed. It is reversed here because the person the peers have just answered for holds the membership again, as it stood before that entry: the status of then (`active`, or `suspended` with its `suspended_until`, which a departure never clears), and the Council seat if one was held and no draw has filled it since (a seat comes back only into a vacancy, invariant 28). That person leaves, if they wish, by a `depart` signed with the new key, which no rule delays, and which a later recovery reverses only within the bounds of RR3a. A recovery that is not applied leaves the departure as it is.
- **Open ballots are not disturbed**, as for a `rekey` (section 6.18): a commitment is bound to the login, so a member who committed with the old key reveals afterwards with the new key.
- Q4 of a later `rekey` counts from this entry: the member replaces the recovered key again only 30 days later.
- That the new key is still listed for the account on GitHub, and that the pull request comes from the member's own GitHub account, are gates (section 9.3), asked again here. The entry adds no activity; it is accepted during a halt and never counted by C12a.

### 6.30 `rekey_oppose`

**Signer:** an active member (section 5.2), who must be a Master Builder, not the member whose key is recovered and not a co-signer of that recovery. **Function:** `ledger._rekey_oppose`.

A Master Builder opposes an **open** recovery: one asked without a freeze. It is the check the Master Builders have on such a recovery, in the place of the objection to a freeze.

| Body field | Type | Constraint |
|---|---|---|
| `login` | string, required | `LOGIN_RE`: the member whose recovery is opposed. |

`r` is the recovery `S.recoveries[login]`.

| # | Precondition | Refusal message |
|---|---|---|
| RP0 | `login` matches `LOGIN_RE`. | `login must be a valid GitHub login` |
| RP1 | A recovery of `login` is alive at `now`. | `no recovery of the key of {login} is pending` |
| RP2 | `r.freeze` is null: the recovery is open. | `the recovery of the key of {login} follows a freeze (correction {r.freeze}): a Master Builder objects to that correction instead (correction_object)` |
| RP3 | The actor's `degree ≥ 3`. | `only Master Builders may oppose a key recovery` |
| RP4 | `actor ≠ login`. | `a member stops the recovery of their own key with rekey_object, signed by the old key` |
| RP5 | `actor` is not in `r.cosigners`. | `{actor} co-signed the recovery of the key of {login} and cannot oppose it` |
| RP6 | `actor` is not in `r.opposed`. | `already opposed the recovery of the key of {login}` |

Effects:

1. `actor` is appended to `r.opposed`.
2. `E` = the number of logins of `masters(now)` other than `login`. If `len(r.opposed) ≥ max(1, ⌈E / 5⌉)` (`ledger.objections_needed`): `r.void = now`. The recovery is `opposed` from this entry on: it holds nothing, the old key is not frozen by it, and it is never applied.

Notes: the number that voids is the number that voids a correction (section 6.21), over every active Master Builder but the member, the co-signers among them: a co-signature does not move the number. It is counted at each opposition, with the Master Builders of that moment. With `E ≤ 5`, one opposition is enough. A Master Builder gives one answer to a recovery: a co-signer cannot oppose (RP5) and an opposer cannot co-sign (RC5). A voided recovery leaves the 90 days of RR5 to the next request and no other wait; the request that follows is not final. The entry credits the Master with activity (section 5.3). It is accepted during a halt and never counted by C12a; it is refused from a frozen key.


### 6.31 `custodian_claim`

**Signer:** an active member (section 5.2), who must be a founder, with their member key. **Function:** `ledger._custodian_claim`. The type is in `PROVING`: it asks the signature predicate about two proofs (CL8).

**The founder's fallback**. Whenever no custodian key is live, the Sunset has not been reached and fewer than three active Master Builders who are not founders exist, a founder may take up the Custodian office again, with a new custodian key and a new revoke key, as often as needed; never a founder against whose custodian key a removal ballot passed. The claim is under notice for 30 days; then the founder applies it, by day 60 (section 6.33). Until it is applied, during the notice or after it, one objection of an active Master Builder who is not a founder voids it (section 6.32). The gate of section 9.3 requires the pull request to come from the founder's own GitHub account: the numeric id of its author must equal the `github_id` the ledger holds for the founder (the generic rule for every entry a member signs).

| Body field | Type | Constraint |
|---|---|---|
| `name` | string, required | `LOGIN_RE`: the custodian's name, held by nobody. |
| `key` | string, required | A valid key (section 2.6): the new custodian key. |
| `revoke_key` | string, required | A valid key: the new revoke key. |
| `proof` | string, required | A signature by `key` over `custodian_message(name, actor, key)` (section 6.1). |
| `revoke_proof` | string, required | A signature by `revoke_key` over `custodian_revoke_message(name, key, revoke_key)`. |

| # | Precondition | Refusal message |
|---|---|---|
| CL1 | The actor's record has `founder` true. | `only a founder may claim the Custodian office` |
| CL2 | `custodians_live(now)` is empty. | `the custodian key of {first live} is live: the office is taken up again only when no custodian key is live` |
| CL3 | `S.sunset` is null. | `the Sunset was reached at {sunset}: no founder takes up the Custodian office after it` |
| CL4 | `non_founder_masters(now) < 3` (`CLAIM_MASTERS`). | `{n} active Master Builders who are not founders exist: with 3 or more the Custodian office is filled only by amendment` |
| CL6 | No record of `S.custodians` has a non-empty `removed` and a `member` that is the same login as `actor`. | `a removal ballot ({removed}) passed against the custodian key {name} of {actor}: that founder never takes up the office again` |
| CL5 | `claim_pending(now)` is none: no other claim is alive. | `a claim of the Custodian office is already pending (entry {seq})` |
| CL5a | The latest record of `S.claims` (the greatest `seq`), if any, has `objected` null or `waited(objected, now, 30)` (`CLAIM_AGAIN_DAYS`): after an objection, the next claim of any founder waits 30 days. | `the claim of entry {seq} was objected to less than 30 days ago (after an objection, the next claim of any founder waits 30 days, so that no name is held out of invitations claim after claim)` |
| CL7 | `name` matches `LOGIN_RE`, and `name_holders(name, now)` is empty. | `custodian names follow login rules`; `the custodian name {name!r} is held by the {role} {other!r} (a custodian name is a login nobody holds, case-insensitive)` |
| CL7a | `key` and `revoke_key` are valid keys; they are not the same key; `key_holders` of each is empty; and neither point is in `S.known_keys`. | `keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)`; `a claimed custodian key and its revoke key must differ from each other and be new keys (a key that was ever registered here is never registered again)` |
| CL8 | `sig_ok(custodian_message(name, actor, key), proof, name, key)`, then `sig_ok(custodian_revoke_message(name, key, revoke_key), revoke_proof, name, revoke_key)`. | `bad custodian proof: the custodian key must sign the custodian message (name, member, key)`; `bad custodian revoke proof: the revoke key must sign the revoke message (name, key, revoke key)` |

CL1 to CL6 are `ledger._claim_conditions` with CL1 before them, evaluated in the order CL1, CL2, CL3, CL4, CL6, CL5, CL5a.

Effects:

1. `S.claims[seq] = Claim(seq, founder = actor, name, key, revoke_key, time = now, objected = null, objector = "", applied = null)`.
2. The points of `key` and `revoke_key` are added to `S.known_keys`.

Notes: while the claim is alive it holds its name and its two keys (section 4.7). A claim that is objected or expires frees the name; its keys stay known and are never registered again. After an objection no founder claims again for 30 days (CL5a), so a pending claim cannot hold a login out of invitations (I5) claim after claim; a claim that merely expires leaves no wait. The two messages are those of the genesis, with the founder's login as the member: the keys are new to the ledger (CL7a), so no proof of an earlier ceremony can be replayed here. The entry credits the founder with activity. **Abuse.** A stolen member key of a founder can claim the office; it cannot hold it against one Master Builder who is not a founder (section 6.32), it cannot apply the claim without the founder's GitHub account (section 9.3), and the 30 days are public. Where no such Master exists, the office is one founder's to take up, and the honest warning of the Constitution (Art. XVI.13) says so.

### 6.32 `custodian_claim_object`

**Signer:** an active member (section 5.2) of the 3rd degree or higher who is not a founder. **Function:** `ledger._custodian_claim_object`.

| Body field | Type | Constraint |
|---|---|---|
| `seq` | integer, required | The `seq` of an alive claim. |

| # | Precondition | Refusal message |
|---|---|---|
| CO1 | `S.claims[seq]` exists. | `entry {seq} is not a claim of the Custodian office` |
| CO2 | Its `claim_status(now)` is `pending` or `ready`. | `the claim of entry {seq} is {status}` |
| CO3 | The actor's `degree ≥ 3` and `founder` is false. | `only a Master Builder who is not a founder may object to a claim of the Custodian office` |

Effects: `objected = now`; `objector = actor`. One objection is enough: the claim is `objected` for good, and a new claim may be made by any founder once 30 days have passed since the objection (CL5a, `CLAIM_AGAIN_DAYS`).

Notes: it is in the daily-exempt set (section 5.4). A dormant Master who is not a founder may object (dormancy blocks no act); a successor may not (section 6.34). A frozen key cannot sign it (it is not in `FREEZE_ALLOWED`), but no key is frozen while no custodian key is live, unless a recovery of it is under way.

### 6.33 `custodian_claim_apply`

**Signer:** an active member (section 5.2): the founder who signed the claim, with their member key. **Function:** `ledger._custodian_claim_apply`.

| Body field | Type | Constraint |
|---|---|---|
| `seq` | integer, required | The `seq` of an alive claim. |

| # | Precondition | Refusal message |
|---|---|---|
| CA1 | CO1 and CO2. | the two messages of section 6.32 |
| CA2 | `actor` is the claim's `founder`. | `only {founder}, who signed the claim of entry {seq}, applies it` |
| CA3 | `waited(time, now, 30)` (`CLAIM_NOTICE_DAYS`). | `the claim of entry {seq} is under notice until {time + 30 d} (30 days after it)` |
| CA4 | CL2, CL3, CL4 and CL6, as things stand at `now`. | their messages |

Effects:

1. `S.custodians[name] = Custodian(name, key, revoke_key, member = actor, alive = now, genesis = false, revoked = null, removed = "", since = now, claim = seq)`.
2. `S.custodian_threshold = 1`: the new custodian is the only live one (CA4), and a noticed act needs that one key.
3. The claim's `applied = now`.

Notes: the claim is applied between day 30 and day 60 (`CLAIM_EXPIRY_DAYS`), or never. The new custodian is bound exactly as one of the genesis: silence (180 days), the Sunset, its revoke key, the removal ballot, and a term of 2,555 days counted from this entry (section 7.9). Every rule of the corrections reads it as it reads a custodian of the genesis; its member is the founder for recusal and objections.

### 6.34 `succession_claim`

**Signer:** an active member (section 5.2) below the 3rd degree. **Function:** `ledger._succession_claim`.

Body: the empty object `{}`. Any field is refused (C10).

**Succession**. The game must keep moving while one active member exists. When no Master Builder is present (`present_masters(now)` is empty: every Master left, is suspended, is dormant, or is silent, section 7.7), any active member below the 3rd degree may claim the succession. Any entry signed within 90 days by a Master Builder who after it is active, not dormant and not silent cancels the claim (C14b). After 90 days the claim is **in force** until three such Master Builders exist (C14b), and the **successors**, the active members, neither dormant nor silent, of the highest degree `t` present, when `t` is 1 or 2, a silent member being no member present at any degree, stand in for Master Builders in four things, and nothing else:

1. they are the last rung of the lot of examiners (section 7.3);
2. they elect an advancement where no Master Builder is present in its electorate (section 7.1), the voters of the earlier rungs (the dormant and the silent among them) keeping the vote;
3. they may invite (I3);
4. they may sponsor (V3, A2, `may_sponsor`).

They open and vote in no amendment, witness, sanction or custodian ballot, object to no correction and to no claim, co-sign and oppose no recovery, and they never count for the Sunset, the Founding Phase, the founder's fallback or the sponsors an admission needs (`sponsors_required` counts `masters(now)` alone). Once a successor reaches the 3rd degree, the highest degree present is 3 and there are no successors; the succession still ends only at three Master Builders.

| # | Precondition | Refusal message |
|---|---|---|
| SC1 | The actor's `degree < 3`. | `a Master Builder needs no succession (only a member below the 3rd degree claims it)` |
| SC2 | `present_masters(now)` is empty. | `an active Master Builder who is neither dormant nor silent exists ({first}): no succession` |
| SC3 | `succession_status(now)` is neither `pending` nor `in_force`. | `a succession claim is already {pending | in force} (entry {seq})` |

Effects: `S.succession = Succession(seq, by = actor, time = now, end = null, canceled_by = "")`.

**C14b** (section 5.1) is the rest of the rule: after every entry, a pending claim is canceled by an entry of a Master Builder who is then active, not dormant and not silent, and a claim that is pending or in force ends when `present_masters(now)` holds three.

Notes. **Abuse.** A member below the 3rd degree who claims while a Master is merely dormant gains nothing if that Master shows themselves: one entry of theirs within the 90 days cancels the claim. A Master who departs cancels nothing. **A silent Master** (called to two examinations or ballots in 180 days, and answering none, section 7.7) **does not bar a succession**: they are not present for SC2, their entries cancel no claim until they reveal a vote or report, and they do not count toward the three that end it; they keep their vote. **A silent successor** is no successor: while a succession is in force the calls of every member are recorded, and a successor called to two examinations or ballots, 7 days apart or more, who answers none, is left out of `successors(now)`, so the next degree down stands in, as it does for a dormant one. After the 90 days, a Master who comes back is a Master again at once once they are neither dormant nor silent (they count in every electorate, and the successors are no more as soon as a Master is present, because the highest degree present is 3), and the succession ends at three. The successors' powers are the ones that let the fraternity reach the 3rd degree again; none of them reaches the law, the witnesses, a sanction, the Custodian or a correction. A succession that ended or was canceled leaves no wait: a new claim may be made whenever SC2 holds again.

---

## 7. Decision functions

### 7.1 Quorum

`ledger.quorum`, in integers:

```python
def quorum(n: int) -> int:
    return min(n, max(3, -(-n // 3)))
```

`-(-n // 3)` is `⌈n/3⌉` for `n ≥ 0`.

| `N` | 0 | 1 | 2 | 3 to 9 | 10 to 12 | 13 to 15 | 16 to 18 | 30 | 31 |
|---|---|---|---|---|---|---|---|---|---|
| `Q(N)` | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 10 | 11 |

`ledger.quorate(votes, N)` is `N > 0 and votes ≥ Q(N)`. **A ballot that is not quorate lapses** (section 6.7): it decides nothing, and nobody is penalized by it. With three present electors or fewer the quorum is all of them, so one absent elector lapses the ballot; the ballot is then opened again, at no cost to its subject, or re-run once without waiting for those who did not vote (B2a, B9).

**The electorate and its quorum base** (`ledger.electorate(S, kind, subject, now)`). Each kind names its **rungs** (sections 6.4.1 to 6.4.6). The rung of degree `d` without the set `X` has two lists: its **present** members, `active(now, d, X)` (not dormant), and its **voters**, `eligible(S, now, d, X)` (the same, with the dormant kept). The choice between two rungs ("if fewer than 3 are present") is made on the present lists, as it always was; the **electors** of the ballot are then the voters of the rung chosen, and its **base** is the number of its present members, or 1 when none is present and some voter exists (0 when there is no voter at all). The admission and the advancement leave out of their present lists every member who is `silent(now)` (section 7.7), so the choice between their rungs and their base never wait for a silent member, who stays among the voters and keeps the vote: an admission whose members of degree 2 or higher are all dormant or silent falls to the rung of degree 1, whose voters are every active member, those of degree 2 or higher included. The advancement differs in two more ways. When fewer than 3 are present on its first rung and it falls to the rung of degree 3, the present list is that rung's and the voters are the **union** of both rungs' voters: a member who had the vote on the first rung keeps it (for an advancement to the 2nd degree, a dormant Fellow whose absence moved the ballot to the Masters still votes). And it adds a last step: when nobody is present in the rung of degree 3, the present list becomes the successors without the member (section 6.34) and the voters the union of the voters so far and those successors.

| Kind | Rungs, in order |
|---|---|
| admission | degree 2; degree 1 when nobody is present in it (present: not dormant and not silent) |
| advancement | degree `degree` without the member; degree 3 without the member when fewer than 3 are present, the voters of the first rung kept; the successors when nobody is present in that one (present: not dormant and not silent) |
| amendment, witness | degree 3 |
| sanction | degree 7 without the member; degree 3 without the member when fewer than 3 are present |
| custodian | degree 3 without the custodian's member |

So **dormancy lowers the quorum and never removes a vote**: a Master who signed nothing for a year is an elector of every ballot of their rung and may commit and reveal like any other, and the quorum and the turnout count the present electors (`N` = the base). The first dormant founder to sign is therefore never an electorate of one: the others are electors too, and a no from any of them counts. A re-run lowers the base further (B9). Where nobody is present, one vote reaches the quorum, and a sanction on a Master Builder (a `reinstate` aside) still needs two (B8a, section 6.7).

### 7.2 `decide`

The code is quoted in section 6.4. With `Y` yes votes, `B` no votes, `T = Y + B` and `N` the quorum base of the ballot (section 7.1; `len(electors)` when no elector was dormant):

- the kind is one of the six of `KINDS`; **any other kind is an error** (`ValueError`), never a default rule;
- every kind is false when the votes are not quorate (`N = 0` or `T < Q(N)`); `ballot_close` never asks it then, because such a ballot has lapsed (section 6.7);
- **admission, advancement:** pass iff `5·B < T`;
- **amendment, sanction, witness:** pass iff `3·Y ≥ 2·T` and `3·T ≥ N`;
- **custodian:** pass iff `Y > B`: a simple majority of the votes cast, and a tie fails.

For `N ≥ 1`, `T ≥ Q(N)` already implies `3·T ≥ N`, so the turnout clause never decides alone. Since `Q(N) ≥ 1` for `N ≥ 1`, a ballot with no revealed vote is never quorate: it lapses.

Worked examples:

| Kind | `N` | `Y` | `B` | `T` | `Q(N)` | Test | Result |
|---|---:|---:|---:|---:|---:|---|---|
| admission | 1 | 1 | 0 | 1 | 1 | `0 < 1` | pass |
| admission | 2 | 1 | 0 | 1 | 2 | `T < Q` | false: the ballot lapses |
| admission | 3 | 3 | 0 | 3 | 3 | `0 < 3` | pass |
| admission | 3 | 2 | 1 | 3 | 3 | `5 < 3` is false | fail |
| admission | 7 | 2 | 0 | 2 | 3 | `T < Q` | false: the ballot lapses |
| admission | 7 | 4 | 1 | 5 | 3 | `5 < 5` is false | fail |
| admission | 7 | 5 | 1 | 6 | 3 | `5 < 6` | pass |
| advancement | 12 | 9 | 2 | 11 | 4 | `10 < 11` | pass |
| advancement | 12 | 8 | 2 | 10 | 4 | `10 < 10` is false | fail |
| amendment | 7 | 2 | 1 | 3 | 3 | `6 ≥ 6` and `9 ≥ 7` | pass |
| amendment | 7 | 3 | 2 | 5 | 3 | `9 ≥ 10` is false | fail |
| amendment | 12 | 3 | 0 | 3 | 4 | `T < Q` | false: the ballot lapses |
| amendment | 12 | 4 | 0 | 4 | 4 | `12 ≥ 8` and `12 ≥ 12` | pass |
| sanction | 3 | 2 | 1 | 3 | 3 | `6 ≥ 6` and `9 ≥ 3` | pass |
| witness | 3 | 1 | 1 | 2 | 3 | `T < Q` | false: the ballot lapses |
| custodian | 6 | 3 | 2 | 5 | 3 | `3 > 2` | pass |
| custodian | 6 | 2 | 2 | 4 | 3 | `2 > 2` is false | fail |
| custodian | 6 | 2 | 0 | 2 | 3 | `T < Q` | false: the ballot lapses |
| custodian | 1 | 1 | 0 | 1 | 1 | `1 > 0` | pass |

### 7.3 The examiner pool ladder

`ledger.examiner_pool(S, m, target, now)`, for candidate `m` and target degree `target`, with `k = examiners(target)` and `X = {m.login} ∪ m.sponsors`:

| Rung | Pool |
|---|---|
| LR1 | `active(now, target, X)`: peers of the target degree, without the candidate and the candidate's sponsors |
| LR2 | `active(now, 3, X)` without the logins that are `silent(now)` (section 7.7): any Master Builder who answers, without the same |
| LR3 | `active(now, 3, {m.login})` without the logins that are `silent(now)`: any Master Builder who answers, except the candidate |
| LR4 | `successors(now)` without the candidate (section 6.34): empty unless a succession is in force and no Master Builder is present |

LR1 keeps a silent Master of the target degree or higher; LR2 and LR3, which reach every Master Builder, leave out the silent ones, as `active` leaves out the dormant. `examiner_pool(S, m, target, now, skip)` takes a set `skip`, the silent examiners of the exams before (E8): every rung leaves them out (LR3 is then `active(now, 3, {m.login} ∪ skip)`), and if every rung is then empty, the ladder is computed again without `skip`, so nobody is ever lost for want of the others. A pool made only of a silent member is therefore drawn only while nobody else can be: it gives that member a chance to answer, and locks nothing, because an admission does not wait for a silent member (section 7.1): the members who answer can admit a newcomer, whom the next lot can draw.

- If `m.founder` is false, the rungs are tried in the order LR1, LR2, LR3, LR4.
- If `m.founder` is true, let `C` be the set of logins of **all** records with `founder = true`, whatever their status. The order is LR1 − C, LR2 − C, LR3 − C, LR4 − C, LR1, LR2, LR3, LR4.
- The result is the **first** rung with at least `k` logins. If no rung has `k`, the result is the **union of the rungs**: every login that any rung of the order holds, whatever its size, or the empty list.
- **After a timeout, the union.** `examiner_pool(S, m, target, now, skip, wide)` with `wide` true (the exam before for the same candidate and degree `timed_out(now)`, its lot drawn or not: E8) returns the **union** of the rungs LR1 … LR4, for a founder too (the order without `C` does not apply: the union takes every rung, `C` included); if that union has fewer than `k` logins, it is still the result, as above. `skip` still applies, and so does the computation again without it. So a lot after a timeout seats everyone any rung holds, never fewer than the first rung that seats `k`, and the founding cohort is seated in a founder's lot after a timeout: an inert founder Master is called with the others and falls silent with them (point 75).

Why the union and not one rung: a lot of one examiner calls one member, and the calls of two exams are at least 60 days apart (E8 records the calls of an exam that timed out at its expiry). Behind a sponsor Master (in LR3 only) and a Fellow (in LR1 only) who each sign one entry a year and answer nothing, a lot drawn from one rung seated one of the two at a time, and four calls (two each within 180 days) span more than 180 days, so the two were never silent together and the 1st-degree member was never examined and never a successor (point 74). The union seats both, both are called by each exam, and the succession reaches the member. The price: a silent member can be seated beside one who answers, and that exam times out after 60 days before the next lot leaves the silent member out (`skip`). It is one exam in the usual shape; the union never removes anyone from the pool, so nobody becomes the sole examiner by it.

Why the union after a timeout, though a rung seats `k`: behind three Masters who each sign one `work` a year and answer nothing (four at the 2nd degree), a lot of `k` from one rung called at most `k` of them per exam, LR2 and LR3 then left the two silent ones out, the lot seated the third alone, and never more than two were silent at once: the member below them was never examined and never a successor, for as long as each signed one entry a year (point 75). An exam that timed out shows that a lot of `k` is not answered, so the next lot calls everyone any rung holds: within three exams every member who never answers is silent, and the succession reaches the member. The price is point 75.

Each rung is in ascending login order, and so is the frozen pool. `exam_open` (E8) then requires a non-empty pool, and lowers `k` to `len(pool)` when the pool is smaller (**the lowered lot always lowers the number**, in every phase; before, only the Founding Phase did, and the 32nd degree, which asks for seven examiners, could not be reached at exactly seven Master Builders).

Example. Three founders `ada`, `carol`, `hiram` (all 3°) and one 1° member `yan` sponsored by `ada` and `hiram`, opening the exam for degree 2 (`k = 2`): LR1 = `active(now, 2, {yan, ada, hiram})` = `[carol]`, too small; LR2 = `[carol]`, too small; LR3 = `active(now, 3, {yan})` = `[ada, carol, hiram]`, which seats 2. The pool is `(ada, carol, hiram)` and `k = 2`.

### 7.4 The lot and the beacon

**Rounds** (`ledger.unix`, `ledger.drand_round`, `ledger.drand_time`), all in integers. `unix(t)` is the number of whole seconds from 1970-01-01T00:00:00Z to `t`:

```
drand_round(t)  = (unix(t) − 1692803367) div 3 + 1
drand_time(r)   = the instant with Unix time 1692803367 + (r − 1) × 3
```

`div` rounds toward negative infinity. An entry that requests a lot at time `t` MUST declare `beacon_round = drand_round(t) + 9600`, and that number MUST be positive: a round is a positive integer, so no lot can be requested at a time more than 8 hours before the beacon chain began (2023-08-23). The time of the declared round is between 28,798 and 28,800 seconds after `t`. Example: `drand_round(2027-01-01T00:00:00Z) = 35319412`, the declared round is `35329012`, and `drand_time(35329012) = 2027-01-01T08:00:00Z`. For every entry time of section 2.5 the round is below `2^53` and its time is a valid date.

**Rank and draw** (`lot.rank`, `lot.draw`):

```
rank(beacon, purpose, x) = H( beacon ‖ "|" ‖ purpose ‖ "|" ‖ x )        (the joined ASCII string)
draw(pool, k, beacon, purpose) = the first k elements of the distinct elements of pool,
                                 sorted by ascending rank (ranks compared as hexadecimal strings)
```

`draw` fails if `k` is not an integer, `k < 0` or `k > len(pool)`. `beacon` is the 64-character lowercase hexadecimal string exactly as written in the entry, not its decoded bytes. The result does not depend on the order of `pool`. Two different names have the same rank only if SHA-256 collides; `lot.draw` then orders them by the names themselves.

| Lot | Pool | `k` | Purpose string |
|---|---|---|---|
| examiners (`exam_draw`) | the exam's frozen `pool` | `len(pool)` for the ranking; the first `exam.k` are the examiners | `exam:{candidate}:{degree}:{beacon_round}` |
| Council (`council_draw`) | `S.council_pool` | `len(pool)` for the ranking; the first eligible names fill the vacancies (section 6.13) | `council:{round}` |

Vector: with `beacon` = 64 zeros and purpose `exam:alice:2:100`, `rank(…, "bob") = b53c703d497f6304e04d28e08260c4cf6ac824f353cff2df3d3ffc4de51db4d8`, and `draw(["ada", "bob", "carol"], 3, …) = ["ada", "bob", "carol"]` (ranks begin `88c143ed`, `b53c703d`, `bd0ddd84`).

**Two steps.** The entry that requests the lot (`exam_open`, `council_call`) fixes the round and freezes the pool. The entry that performs it (`exam_draw`, `council_draw`) is accepted only at or after `drand_time(round)` and carries the randomness. Replay trusts the value recorded; the gate of section 9.4 compares it with the public beacon.

### 7.5 Sponsors and the sponsor budget

**Who may sponsor** (`ledger.may_sponsor`): a login whose member record exists, `is_active(now)`, `stands_in(login, now)` (`degree ≥ 3`, or a successor, section 6.34), and has `sponsor_ban_until` null or `now ≥ sponsor_ban_until`. An `invite` and a `vouch` check this when they are made (I3 and I6, V3 and V5, and the signer rule), and the admission ballot checks every sponsor, the inviter included, **again** when it opens (A2): only those who may still sponsor at that moment count toward the number required and become the sponsors of record.

**Sponsors required** (`ledger.sponsors_required`), with `M = len(masters(now))`:

```
sponsors_required(S, now, p) = 1                    if P < 7 and p is given
                                                       and waited(p.time, now, 30) on the effective clock
                             = max(1, min(2, M))    if P < 7
                             = 2                    otherwise
```

with `P = len(present_masters(now))`, the active Master Builders who are neither dormant nor silent (section 7.7). `P < 7` holds throughout the Founding Phase (`P ≤ M < 7`), and also after it while fewer than seven Masters answer. So 1 when `M` is 0 or 1, or once the petition `p` has been live 30 days (`SPONSOR_WAIVE_DAYS`) while `P < 7`, and 2 otherwise. It is evaluated when the admission ballot opens (A2), with the petition. The inviter is a sponsor from the invitation on, so with one Master the inviter alone suffices, and otherwise one `vouch` by a second Master is needed for 30 days. **A Master who never answers holds no door shut**: after the 30 days the inviter opens the ballot alone, and every other Master still votes on it (the blackball stands). Outside the Founding Phase, a Master among six or more peers who sign a work a year and answer nothing needed a second sponsor nobody gave, and admitted nobody until the law itself was changed; two ballots of seven days that call every Master make them silent, and the waiver then applies (point 77). Successors never count in `M` or `P`.

**Budget** (`ledger.sponsorships`, I7 and V6). For a Master `a` at `now`:

```
sponsorships(a, now) =   number of records m in S.members with a ∈ m.sponsors, m.status ≠ departed
                         and not expired(m.since[1], now, 365)
                       + number of petitions q in S.petitions with a ∈ q.vouches and q reserved at now
                       + number of invitations i in S.invitations with i.by = a
                         and not expired(i.time, now, 30 + 90) on the effective clock
```

An invitation or a vouch is accepted only if `sponsorships(a, now) < 4`, so after it the count is at most 4. An invitation counts from the moment it is signed; when its petition is filed it leaves the third term and enters the second in the same entry, so the candidate is counted once throughout. An invitation with no petition stays in the count after it lapses, until `INVITE_COUNTED_DAYS` = 90 days more have passed (120 days after it was signed, on the effective clock): otherwise one Master could hold a login by inviting it again every 30 days at no cost. A new invitation of the same login replaces the lapsed one (section 6.17, effect 1), so one login is never counted twice by it. A petition leaves the count when its ballot passes or fails (the petition is then removed), and not when it lapses for want of quorum, since a lapsed ballot leaves the petition as it was; with no open ballot it leaves when it lapses, more than 180 days after it was filed. An admitted member leaves the count more than 365 days after admission, or at once on departure; an expulsion does not remove them earlier, and re-admission replaces the record.

Example. `hiram` invited `p1`, who has petitioned, and vouched for `p2` (both petitions live, no ballot yet); he invited `p3` ten days ago, who has not petitioned; and he sponsored `m1`, admitted 100 days ago, and `m2`, admitted 400 days ago. The count is `1 + 2 + 1 = 4`: his next invitation or vouch is refused until `p3`'s invitation has been lapsed for 90 days, one of the petitions is decided, or `m1` departs.

### 7.6 The fraud ban

Set by a passed sanction with measure `expel_for_fraud` (section 6.4.4): the time is appended to the member's `fraud_history`, and if `not expired(m.since[1], now, 730)`, that is, at most 730 days after admission, every sponsor of `m` that has a record gets `sponsor_ban_until = now + 730 d`. A banned member's `invite` or `vouch` is refused while `now < sponsor_ban_until` (I6, V5), and an earlier invitation or vouch of theirs no longer counts when a ballot opens (A2). The ban and the fraud history belong to the person: both are carried to the new record if the login is admitted again (section 6.4.1).

### 7.7 Activity, dormancy and standing

- `is_active(now)` (section 4.2) decides who may **sign** (section 5.2), with five exceptions: `depart`, `rekey` and `rekey_object`, which a suspended member signs (and `rekey_object` also a member who departed, while a recovery of the key is alive); the `ballot_reveal` of a `voided` record in a ballot in which it sealed a vote; and the two recovery types, `rekey_recover` and `rekey_recover_apply`, which the new key signs for any recoverable record.
- `dormant(now)` is `expired(last activity, now, 365)`. It decides, together with `is_active`, who is **counted**: `active(now, …)` excludes dormant members, and with it the quorum base of every ballot (section 7.1), every examiner pool, the Council pool, and the counts of Masters that define the Founding Phase, the Sunset, the founder's fallback and the succession. **It never removes a vote:** every electorate holds the dormant members of its rung.
- A dormant member may still sign any entry their status allows. That entry is activity and ends the dormancy for later entries, unless its type is in `UNCREDITED` (`depart`, `rekey`, `rekey_object`), which adds no activity (section 5.3).
- **Silence** (`Member.silent`, `Member.called`, `ledger._call`, `ledger._heard`, `ledger._serves`). A Master Builder who is called and does not answer is **silent**: `silent(now)` holds when the member was called to at least `SILENT_CALLS` = 2 examinations or ballots that ended in the last `SILENT_DAYS` = 180 days, at least `SILENT_APART_DAYS` = 7 days apart, and answered none of them (section 4.2). Two things are recorded, and only for a record of degree 3 or higher at that moment, or for any record while `succession_status(now) = in_force` (whoever is called then serves as a successor; `ledger._serves`):
  - a **call** ends with an end time and an answer: at the close of a ballot that gave at least 7 days to commit (`ledger.full_call`), for each of its electors (answered: the elector revealed a vote; a commitment alone is no answer; effect 2a of section 6.7; a ballot with a shorter commit window calls nobody); at the `exam_report` that decides an exam, for each of its examiners (answered: they reported; section 6.10); when an exam lapses because a seat finds no replacement, for each examiner left (section 6.11); and, for an exam that timed out with examiners drawn, at the next accepted `exam_open` of the same candidate and degree, after its pool is frozen, for each of its examiners, dated the first second at which it had timed out (`_timed_out_at`: `due(opened, 60 d) + 1 s`; section 6.8, effect 1a). A call not answered adds its end to `missed`, which then keeps, of the times that are not `expired(t, now, 180)`, the newest 2 that are at least 7 days apart: taken from the newest down, a time is kept when it is at least 7 days before the last one kept, until two are kept (two calls that end within 7 days of each other are one absence, and the record keeps a fixed size); a call answered moves `heard` to its end when that is later;
  - a **revealed vote or a report** (`ballot_reveal`, `exam_report`) sets `heard = now`; a `ballot_commit` does not.

  One revealed vote or one report ends the silence at once, for 180 days; a `work`, or any other entry, does not. A silent member keeps every vote, signs everything their status allows, and is counted everywhere else; they count as absent in three places only: the succession (`present_masters`, SC2 and C14b; and `successors`, which leaves out a silent member of any degree), the all-Masters rungs of the examiner ladder (LR2, LR3, section 7.3), and the present lists, and so the quorum base, of an admission and of an advancement (section 7.1). An exam that timed out and is never opened again records no call. A member below the 3rd degree is called only while a succession is in force; a silent record of a past succession is read only by the present lists of an admission and of an advancement, within its 180 days.
- Electorates and pools are frozen when computed. A member who becomes dormant, suspended, expelled or departed afterward stays in the frozen set (and in `N`), but can sign only if still active. The two lots check their pools again where it matters: a replacement examiner (section 6.11) and every name drawn to the Council (section 6.13) must be active and not dormant at that moment.

Summary of who is what at `now`:

| Recorded status | `standing` | May sign | Counted in `active(…)` | Holds a Council seat |
|---|---|---|---|---|
| `active` | `active` | every member type | if not dormant | while `now ≤ seat_until` |
| `suspended`, `now < suspended_until` | `suspended` | `depart`, `rekey` and `rekey_object` only | no | while `now ≤ seat_until` |
| `suspended`, `now ≥ suspended_until` | `active` | every member type | if not dormant | while `now ≤ seat_until` |
| `expelled` | `expelled` | `petition` only, once 365 days have passed and a Master Builder has invited the login | no | no (`seat_until` is null) |
| `departed` | `departed` | `petition` only, once 90 days have passed and a Master Builder has invited the login; `rekey_object`, while a recovery of the key is alive; the new key of a recovery, the two recovery types (RR3a) | no | no (`seat_until` is null) |
| `voided` | `voided` | `petition` only, under P0 and P1; and the `ballot_reveal` of a vote it sealed in a ballot still open | no | no (`seat_until` is null) |

### 7.8 Intervals and the effective clock

**Intervals.** An immediate act of a correction (section 6.19) is in force on the interval `span(c) = [start, end)` (`State.span`):

```
start = c.time
end   = max(start, min(c.until,
                       custodian_end(S.custodians[c.by]),
                       c.withdrawn  if it is set,
                       c.void       if it is set,
                       c.released   if it is set))
in_force(c, t)  ⇔  start ≤ t < end
```

So an act ends at the earliest of five things: the lapse of its own time, its withdrawal (section 6.20), the objections that void it (section 6.21), for a freeze the application of the recovery of the frozen key (section 6.29), and the end of the key that signed it, by silence, by revocation, by a removal ballot, by the Sunset or by the end of the term (section 4.8). A noticed act has no such interval and is never in force; a `void_ballot` has the interval on which it is **pending**, `void_span(c)` (section 4.9), which pauses its ballot and nothing else. `end` is **computed** from stored facts each time it is asked; it is stored nowhere, and no stored deadline is ever rewritten. An interval whose `end` is not after its `start` is empty: the act was never in force. An act is in force for the entries that come after its own entry, one stamped in the same second included, and it is over for the entries that come after the entry that ended it, one stamped in the same second included.

**The effective clock.** `pauses(ballot)` (`State.pauses`) is the list of the intervals `span(c)` of every correction with `act = halt` and, when `ballot` is given, of every correction with `act = stay` and `target.ballot = ballot`, together with the intervals `void_span(c)` of every correction with `act = void_ballot` and `target.id = ballot`; empty intervals are dropped, and intervals that overlap or touch are merged into one, so the list is disjoint and in ascending order. **One exception:** when `ballot` is the id of a ballot of a kind in `UNSTOPPABLE_KINDS` (`amendment`, `custodian`), `pauses(ballot)` is the empty list; an amendment and the ballot that removes a custodian run on wall time, and no halt pauses them (no correction ever stays or voids either, `STAY_EXEMPT`). Then, for times `start ≤ now`:

```
paused(start, now, ballot)     =  Σ over [a, b) in pauses(ballot) of  max(0, min(b, now) − max(a, start))
effective(start, now, ballot)  =  (now − start) − paused(start, now, ballot)
```

The definition is over all of `S.corrections`; the reference implementation reads the halts and each ballot's stay and `void_ballot` corrections from an index that it keeps beside the map (`State._pausing`), which is not a stored fact and is not in the state document, so that counting a duration never scans every correction.

`effective(start, now)` without a ballot counts halts alone. It is an exact number of seconds, at least 0 and at most `now − start`; it never decreases as `now` grows, and it grows by at most one second per second. A halt, a stay and a pending void that overlap are counted once.

**What is counted on it.** The effective clock replaces `now − start` in exactly these rules, and in no other:

| Rule | Counted as |
|---|---|
| the three windows of a ballot (K3, R2, X2) | `ballot_time(b, now) = b.opened + effective(b.opened, now, b.id)`, compared with the stored `commit_until`, `commit_until + REVEAL_GAP` and `reveal_until` |
| the expiry of an exam (F2, T6, U3; `Exam.expired`, `Exam.timed_out`) | `effective(opened, now) > 60 d` |
| the time in which a lot is drawn (F3a, L1, Y1a; `Exam.draw_lapsed`, `ledger.council_lapsed`) | `effective(drand_time(round), now) > 7 d` |
| the wait before an exam is repeated (E6) | `effective(opened, now) ≥ 90 d` |
| the waiver of the second sponsor (`ledger.sponsors_required`, A2) | `effective(petition.time, now) ≥ 30 d` |
| the expiry of an invitation (`State.invited`; P0) | `effective(time, now) > 30 d` |
| the expiry of a petition (`State.live`, and through it `State.reserved`) | `effective(time, now) > 180 d` |
| the time a live or lapsed invitation counts in its inviter's budget (`ledger.sponsorships`; section 7.5) | `effective(time, now) > 30 d + 90 d` ends it (`INVITE_EXPIRY_DAYS + INVITE_COUNTED_DAYS`) |

**Everything else is wall time:** dormancy, the length of a suspension, of a sponsorship ban and of a Council seat, the fraud window, the sponsor's year, the waits before a departed, voided or expelled login returns, the 90 days in which a voided record may be expelled for fraud, the waiting period of a degree, the 24 hours between two works, the 30 days between two rekeys, the prior-pin window, the time of a beacon round, and every duration of this section and of section 6.19: the length of a freeze, a stay, a halt and a hold, the 90 days of FK3, HR4, HT1, J7 and N7, the 30 days of N6 and N6a, the UTC day of NT4 and of C12a, the hour of Z7, the 24 hours of AL1, the 90 days of B7a, the 30 days of B2e, the 180 days of a custodian's silence and the 2,555 days of its term; the 14 days of notice of a noticed act and the 7 days in which it is applied (section 6.19.9), the 90 days in which a ballot can be undone (UB6), the 180 days and the 7 days of silence (section 7.7), the 21, 30, 45, 60 and 90 days of a recovery and the 30 and 150 days of RR3a (sections 6.15, 6.26 and 6.29), the 30 and 60 days of a founder's claim (sections 6.31 to 6.33) and the 90 days of a succession claim (section 6.34). The three windows of an amendment ballot and of a ballot of kind `custodian` are wall time too.

**Worked example.** A ballot `b` is opened at `T0` with `commit_days = 7`, so `commit_until = T0 + 7 d`. At `T0 + 3 d` a custodian halts the ledger (`until = T0 + 17 d`), and withdraws the halt at `T0 + 5 d`: the halt was in force on `[T0 + 3 d, T0 + 5 d)`. At `T0 + 4 d`, during the halt, a custodian stays ballot `b`; nobody withdraws or voids the stay, so it is in force on `[T0 + 4 d, T0 + 18 d)`. Then:

```
pauses()   = [ [T0 + 3 d, T0 + 5 d) ]
pauses(b)  = [ [T0 + 3 d, T0 + 18 d) ]                the halt and the stay overlap: one interval of 15 days

effective(T0, T0 + 20 d) = 18 d                       20 days of wall time, 2 of them halted
effective(T0, T0 + 20 d, b) = 5 d                     for the ballot, 15 of them paused
effective(T0, T0 + 4 d, b) = 3 d
effective(T0 + 10 d, T0 + 20 d, b) = 2 d              only the pause inside the span counts
```

The commit window of `b` is open while `ballot_time(b, now) ≤ T0 + 7 d`, that is while `effective(T0, now, b) ≤ 7 d`: its last second is `T0 + 22 d`, exactly 15 days after the stored `commit_until`, which still reads `T0 + 7 d`. A ballot opened at `T0` that was not stayed lost only the two halted days: its commit window ends at `T0 + 9 d`. An invitation signed at `T0` is live through `T0 + 32 d`.

**Where a deadline falls** (`State.due(start, span, ballot)`, `State.ballot_due(b, deadline)`). `due(start, span, ballot)` is the last time `t` with `effective(start, t, ballot) ≤ span`, computed from the pauses as they stand: `t` starts at `start + span`, and for each interval `[a, b)` of `pauses(ballot)`, in order, with `b > start` and `a ≤ t`, `t` grows by `b − max(a, start)`. `ballot_due(b, deadline) = due(b.opened, deadline − b.opened, b.id)`. These are views for people and tools (the reads of section 9.1, the refusal message of R2); every rule compares `effective` itself. A pause can still end early, and a new pause can still begin: a deadline shown today is where it falls as things stand, not a promise.

**Eager and lazy evaluation agree.** No entry marks the end of an act or the lapse of a key, so there is nothing an implementation could apply early, late or not at all. Every question a rule asks (is this key live, is this act in force, how much effective time has passed) is a function of the stored facts and of the time asked about. And a later entry never changes an earlier answer: an entry with time `T` can only set `withdrawn`, `void`, `released`, `applied`, `objected`, `revoked`, `S.sunset` or the `notice` and `void` of a recovery to `T`, or move `alive` to `T` while the key is still live at `T`, which moves the end of that key and of its acts further into the future. Each of these changes intervals and conditions only at or after `T`. Hence, for a ledger `e[0..n]` and any `j < n`, with `T` the time of `e[j + 1]`: `in_force(c, t)`, `custodian_status(c, t)`, `noticed_status(c, t)`, `void_span(c)` restricted to times before `T`, and `recovery_status(r, t)` for every `t < T`, and `effective(a, t, ballot)` for every `a ≤ t ≤ T`, have the same value on `S_j` and on `S_n`, for the records `S_j` holds. (A recovery record replaced by a later request of the same login is no longer held, and is not asked about.) Within one second the order of the entries decides, as stated above.

### 7.9 The Sunset, the term and the recusal

**The Sunset condition.** `ledger.sunset_reached(S, now)` holds when both:

```
len(S.witnesses) ≥ SUNSET_WITNESSES = 4
the number of logins in masters(now) whose record has founder = false  ≥  SUNSET_MASTERS = 7
```

It is evaluated once per accepted entry, after the entry's effects, its activity and the counts of the day (section 5.1, C14s), on the state as it then stands and at the entry's time. The first time it holds, `S.sunset` is set to that time and is never changed again, whatever happens to the Masters and the witnesses afterwards. From then on the key of every custodian, whether the genesis or a founder's claim named it, is not live (section 4.8): `custodian_end` is at most `S.sunset`, so those keys sign nothing in any later entry, one stamped in the same second included, and every act they had in force ends at `S.sunset`. `S.sunset` is recorded also on a ledger without custodians.

"Not a founder" is the `founder` mark of the record, and the mark follows the person: a founder who departs and is admitted again under the same GitHub account is still a founder (section 6.4.1) and never counts among the seven.

The condition is not re-evaluated between entries. Time alone can change `masters(now)` (a suspension is served, a member goes dormant); the Sunset is recorded at the first **entry** after which the condition holds, and that entry itself, if a custodian signed it, is the last one a custodian signs. No founder's claim is accepted after it (CL3, CA4).

**The term.** Whether or not the Sunset is ever reached, the key of every custodian ends with its term: it is live while `not expired(since, now, 2555)` (`CUSTODIAN_TERM_DAYS`, seven years of 365 days, counted from the time of the genesis, or for a custodian a founder's claim named from the application of that claim), and `custodian_end` is at most `since + 2,555 d + 1 s`. The key signs through the last second of the 2,555 days and nothing after it. The term is wall time and nothing moves it: no sign of life, no halt and no entry of any kind. An interim office that could last as long as the condition that ends it stays unmet would not be interim; the term is the latest date at which it ends. So a custodian key ends at the earliest of four things: its silence, its revocation or removal, the Sunset, and the term. **The founder's fallback** (section 6.31) is the one way back while few Masters exist: whenever no key is live, before the Sunset and with fewer than three active Master Builders who are not founders, a founder may take up the office again, as often as needed, never after a removal ballot passed against that founder's key. Each claimed key runs its own term from its own application.

**The recusal.** The Sunset counts witnesses and Master Builders who are not founders, and reaching it ends the custodians' own keys. No correction therefore touches the two kinds of ballot that add to either count (`ledger.sunset_ballot`): a ballot of kind `witness` with `action = add`, and a ballot of kind `advancement` to the 3rd degree. Such a ballot is never stayed (SY2a), voided (VB2a) or undone (UB2a; a witness ballot is of no kind an undo reaches at all, UB2). The custodians keep, toward such ballots, only what touches no ballot: a `freeze_witness` of a witness key that is compromised, a `freeze_key`, a halt (which pauses every ballot alike, for 14 days in 90), and the undo of the **admission** of a member, which is refused once that member has advanced (the comparison of section 6.19.8).

---

## 8. Governed files and pins

### 8.1 What genesis pins

Genesis sets six pins (section 6.1), the paths of `GENESIS_PINS`: `canon/degrees.toml`, `canon/eternal.toml`, `CONSTITUTION.md`, `@protocol`, `docs/governance/CUSTODIAN.md` and `docs/governance/ROOMS.md`. Each is 64 lowercase hexadecimal characters. For the five files the intended value is the SHA-256 of the file's bytes; for `@protocol` it is the digest of section 8.3. `govern.genesis_pins(root)` computes the six values for a tree, and `om genesis` uses it. Genesis also records `declaration_sha256`, the digest of the Declaration text inside `canon/eternal.toml`. Replay records these seven values without comparing them to any file; the degree table named by the first pin must be available and well formed (G3).

### 8.2 How amendments change pins

A passed amendment ballot on `path` with `new_sha256` (section 6.4.3):

1. fails, without any of the effects below, if the pin of `path` is no longer the one the ballot froze at its opening (`frozen.base`), or if another key of `S.pins` equals `path` up to case (M4, asked again at the close);
2. has the history `amendments` absorb the Amendment `{ballot, path, new_sha256, time}` (section 4.11), appends `new_sha256` to `S.degree_tables` when `path` is `canon/degrees.toml`, and for `@protocol` adds 1 to `S.epoch`;
3. for `new_sha256 = ZERO_HASH`, removes `path` from `S.pins`, `S.prior_pins` and `S.prior_until` (the path is governed no more; never a genesis pin, M7a);
4. otherwise, if `path` was already pinned, moves the old pin to `S.prior_pins[path]` and sets `S.prior_until[path] = now + 30 d`, replacing any earlier prior pin of that path;
5. and sets `S.pins[path] = new_sha256`.

Consequences:

- A pin changes only at genesis or by a passed amendment. A pin is removed only by a passed amendment that pins 64 zeros, and a genesis pin never.
- Two amendments of one path may be open together, one per text (B7); the first to pass changes the pin, and the others fail at their close (step 1). Nobody holds a path by opening a bogus text on it.
- `canon/eternal.toml` can never be amended (M2), so its pin is the genesis value forever. M2 compares a prefix, up to case: no path that starts with `canon/eternal.toml`, such as `Canon/Eternal.toml` or `canon/eternal.toml.d/x`, can be pinned either. `S.declaration_sha256` never changes either: no entry type writes it after genesis.
- Nothing at or under `ledger/` can be pinned (M3): the entries are protected by the chain, not by a pin.
- Paths are exact, case-sensitive strings, and no two keys of `S.pins` are equal up to case (M4). `Canon/Degrees.toml` can therefore never be pinned beside `canon/degrees.toml`, which is the only spelling `State.degree` reads.
- Any other path that passes `PATH_RE` can become governed, including paths that do not exist yet.

### 8.3 The `@protocol` digest

`@protocol` names the **pinned core**: the files whose bytes decide what is valid, the list of those files, and the workflows of the repository. `govern.protocol_digest(root)` is its digest for the tree at `root`. There is one definition, and it reads nothing but the listed files: it does not consult git, does not list a directory and runs no program.

1. **Manifest.** The list is **data, not code**: the file `src/openmasonry/protocol.manifest` (`govern.MANIFEST`) **of the tree being checked**. `govern.read_manifest(root)` reads it from `root`; the code that computes the digest holds no list of its own. `govern.parse_manifest(bytes)` accepts exactly one form and fails (`UnsafeTree`) on anything else, each message prefixed with `src/openmasonry/protocol.manifest: `:

   | # | Rule | Message |
   |---|---|---|
   | F1 | At most `MANIFEST_MAX_BYTES` = 65,536 bytes. | `larger than 65536 bytes` |
   | F2 | Every byte is ASCII. | `holds a byte outside ASCII` |
   | F3 | The file ends with a line feed `0x0A` (so it is not empty). Its lines are the byte strings between line feeds. | `must end with a line feed (and cannot be empty)` |
   | F4 | Every line is a **safe relative path**: it matches `MANIFEST_PATH_RE` as a whole, that is 1 to 10 segments separated by `/`, each of 1 to 100 characters among ASCII letters, digits, `.`, `_` and `-`; and no segment is `.` or `..`. So there is no blank line, no comment, no space or tab, no carriage return, no leading `/`, no backslash and no way out of the tree. | `line {n} is not a safe relative path (segments of letters, digits, . _ - joined by /; no blank line, comment, space or carriage return)` |
   | F5 | Lines are in **strictly ascending** order, compared as byte strings: line `n` is greater than line `n − 1`. So no path is listed twice, and a set of paths has one manifest. | `line {n} is not after line {n − 1} (paths are strictly sorted, so none is listed twice)` |
   | F6 | No two lines are equal up to case (`fold`). | `lines {i} and {j} differ only by case` |
   | F7 | The manifest lists itself and `src/openmasonry/govern.py` (`MANIFEST_REQUIRED`): the list, and the code that reads it, are always part of what is pinned. | `does not list {path}` |

   F4 and F5 are checked together, line by line, before F6 and F7. Lines are numbered from 1. The manifest of the repository this document describes lists fifteen paths:

   | # | Path | What it is |
   |---|---|---|
   | 1 | `.github/workflows/judge.yml` | the judge: the workflow gates of section 9.6 and the command of section 9.1 (job `judge`), and the auto-merge of a pull request of entries it passed (job `admit`) |
   | 2 | `.github/workflows/pages.yml` | the Observatory: builds the public page from the ledger of `main` and publishes it on GitHub Pages (two actions of GitHub, pinned by commit); it judges nothing |
   | 3 | `.github/workflows/tyler.yml` | the Tyler: the audit of `main` (section 9.1), the capture alarm, the tests, the candidate check (section 9.1), the agent engine and the close of stale applications (section 9.6) |
   | 4 | `src/openmasonry/__init__.py` | the package marker (empty) |
   | 5 | `src/openmasonry/beacon.py` | the gate of section 9.4 |
   | 6 | `src/openmasonry/canon.py` | constants and the degree tables (section 8.4) |
   | 7 | `src/openmasonry/crypto.py` | canonical JSON, hashes, the Merkle root, signatures (section 13) |
   | 8 | `src/openmasonry/govern.py` | reading the manifest, the digest and the tree gate (this section and 8.5) |
   | 9 | `src/openmasonry/identity.py` | the gate of section 9.3 |
   | 10 | `src/openmasonry/ledger.py` | replay: every rule of sections 2 to 7 |
   | 11 | `src/openmasonry/lot.py` | the lot (section 7.4) |
   | 12 | `src/openmasonry/network.toml` | the name of the canonical repository (`repository`) and the numeric GitHub id of the account that founds it (`founder_github_id`; 0 while it is not set), read by the gate of section 9.3 |
   | 13 | `src/openmasonry/protocol.manifest` | the manifest itself |
   | 14 | `src/openmasonry/rooms.py` | the rooms rule (section 15): who reads which room, and the plan the sync program applies; replay never reads it |
   | 15 | `src/openmasonry/verify.py` | the entry point the judge and the audit run (section 9.1) |

2. **Safety.** The manifest and every path it lists MUST be a regular file of the tree. The computation fails (`UnsafeTree`) when one of them is missing (`{path} is missing`), is not a regular file (`{path} is not a regular file`), cannot be read (`{path} cannot be read: {reason}`), is or lies under a symbolic link, or resolves outside `root`; and when the manifest is malformed (step 1).
3. **Digest.** One SHA-256 is fed, for each path in manifest order, four fields with nothing between them:

   ```
   u64(len(path)) ‖ path ‖ u64(len(content)) ‖ content
   ```

   `path` is the ASCII bytes of the path as listed, `content` the bytes of the file, and `u64(n)` the integer `n` as 8 bytes, big-endian. The digest is the 64 lowercase hexadecimal characters of the result. Because both variable fields carry their length, two different sequences of (path, content) never produce the same input. The manifest is one of the listed files, so its own bytes are hashed like any other: adding a path to the list, or removing one, changes the digest even when no other byte of the tree moved. The digest is over working-tree bytes, so a conversion of line endings changes it (the repository normalizes them to LF in `.gitattributes`).

**Changing the list.** Because the manifest is read from the tree being checked, the digest of a tree does not depend on which version of the code computes it: the verifier of the base branch and the verifier inside a pull request give the same value for the pull request's tree. A change of the core is therefore made through the judge, in this order: (1) the new tree is prepared, with its manifest (a new module or a new workflow listed, a path removed) and its files; (2) an amendment of `@protocol` pins `protocol_digest` of that tree and passes; (3) the pull request with exactly that tree is judged by the **old** code, which reads the new manifest, computes the ratified digest and finds the new workflow listed, and lets it through; (4) after the merge the new code judges `main` and computes the same digest. Until step 2 the same pull request is unlawful: a manifest that nobody voted on gives a digest the ledger does not pin. The same holds for a manifest from which a path was **removed** in order to change that file afterward without a vote: the removal itself changes the digest and needs the amendment. What this does not make possible is listed in section 12, point 18.

**The closure.** The ten Python files of the manifest import only one another and the Python standard library, wherever the import statement stands; `tests/test_core.py` reads the manifest, parses them and fails on any other import. Running `python -P -m openmasonry.verify` therefore loads no other module of the repository. The manifest and this property change only together with the pin: adding a file to the core, or an import of a module outside it, changes a listed file and so the digest.

**A closed set of workflows.** A tree may hold nothing under `.github/workflows/` besides the files its own manifest lists (section 8.5, step 5). A workflow file that the manifest does not list is therefore never lawful by review alone: it could define a job named `judge`, which GitHub would report under the same name as the required check of the real judge. The digest itself does not see such a file (it reads the listed files only); the tree gate and the judge's own gate (section 9.6) do. A workflow that the manifest does list is covered by the digest, so it is lawful exactly when the ledger pins a digest of a tree that lists it.

**What it does not cover.** Everything else: the command line and the members' tools (`src/openmasonry/__main__.py`, `actions.py`, `guide.py`, `heraldry.py`, `onboard.py`), the Observatory (`metrics.py`, `observatory.py`), the room sync program and the templates of `ops/`, the launcher (`bin/`), the witness node (`node/`), `scripts/`, the other files of `.github/` (issue forms, code owners), `engines/`, `skills/`, `tests/`, `docs/` (two documents are pinned on their own, section 8.1), `pyproject.toml`, `canon/` (two files pinned on their own, and `canon/history/` not at all) and the ledger. Such code changes by code-owner review, not by amendment. It cannot change a verdict of the judge: the judge runs only the entry point above with the base branch's code (section 9.1), its workflow refuses any file under `src/` that Python would find in place of a pinned module or of a standard one, and no workflow exists outside the core (section 9.6). `om verify` runs the same `verify.verify_report` from the command line.

### 8.4 Canon history: degree tables by digest

Replay never reads "the current" degree table. `State.degree(n)` reads the table whose digest is `S.pins["canon/degrees.toml"]` at that point of the history, through `canon.degrees_for(digest)`:

1. The candidates are `canon/history/{digest}.toml` of the verifier's own tree, then `{digest}.toml` in each extra directory of `canon.archives` (the judge passes the `canon/history/` of the pull request's tree, section 9.1), then `canon/degrees.toml` of the verifier's own tree.
2. A candidate **answers** if it is a regular file, not a symbolic link, of at most `CANON_MAX_BYTES` bytes, and the SHA-256 of its bytes equals `digest`. An extra directory is read only under the digest asked, so it can add a table and never change one. The table is thus identified by its content: whichever file answers, the bytes are the same.
3. The bytes that answer MUST be a **well-formed degree table** (`canon.parse_degrees`). A table has **one form**, read line by line by `canon._parse_tables`, with no TOML library:
   - at most `CANON_MAX_BYTES` = 262,144 bytes; valid UTF-8; no byte order mark; every line, the last included, ended by the single byte `LF` (so no carriage return);
   - each line is exactly one of: the empty line; a **comment**, `#` followed by any characters other than U+0000 to U+0008, U+000A to U+001F and U+007F (a tab is allowed); one of the two **headers** `[[degree]]` and `[[house]]`, with nothing before or after; or a **pair** `key = value`, with the key 1 to 32 characters of `a` to `z` and `_`, one space, `=`, one space, and the value to the end of the line;
   - a pair stands only after a header, and belongs to the table that header opened: there is no key at the top level and no other table;
   - a key appears at most once in a table;
   - a value is one of: a **string**, `"` then any characters other than `"`, `\`, U+0000 to U+001F and U+007F, then `"` (no escape of any kind, no single-quoted or multi-line string); an **integer**, `0` or 1 to 4 digits without a leading zero and without a sign; or, for the key `range` of a `[[house]]` only, `[a, b]` with two such integers, one comma and one space;
   - there are exactly 33 `[[degree]]` tables; each has **exactly** the fields `n, house, title, historical, virtue, art, lesson, work, wait_days, examiners, unlocks, tincture, ordinary, charge`, no more and no fewer;
   - `n` is an integer from 1 to 33, and the 33 values of `n` are distinct (so they are exactly 1 to 33);
   - `wait_days` is an integer with `0 ≤ wait_days ≤ 3650` (`WAIT_DAYS_MAX`);
   - `examiners` is an integer with `0 ≤ examiners ≤ 33` (`EXAMINERS_MAX`), and `examiners ≥ 1` when `2 ≤ n ≤ 32`, the degrees reached by examination;
   - every other field of a degree is a string;
   - each `[[house]]` table, if any, has exactly `id`, `name` and `purpose` (strings) and `range = [a, b]` with `1 ≤ a ≤ b ≤ 33`, and no two houses have the same `id`. Replay reads nothing of a house; a table with a malformed house is all the same no table.
4. `canon.canon_status(digest)` is therefore one of three: `ok` (a candidate answers and is well formed), `missing` (no candidate answers: the verifier lacks the text), `malformed` (a candidate answers and is not a well-formed table).

**The verdict is the same for every verifier.** The bytes are fixed by the digest, and whether they are a table is decided by the rules of step 3 alone: a scan of lines against fixed patterns over explicit characters, with no recursion, no number longer than four digits and no library whose behavior differs between runtimes or versions. A file in this form is also valid TOML with the same reading, so other tools read it with any TOML library; but a file that some TOML library accepts and that is not in this form (a key at the top level, another table, an escape in a string, an inline comment, a nested value, a long integer) is `malformed` for every verifier alike.

Replay uses two fields of a row: `wait_days` and `examiners`. It reads them in D3, E4, E8 (through `examiner_pool`) and L4 (`wait_days(33)`).

What each status means for an entry:

| Where | `missing` | `malformed` |
|---|---|---|
| genesis (G3), for `pins["canon/degrees.toml"]` | the entry is refused | the entry is refused |
| opening of an amendment ballot on `canon/degrees.toml` (M6), for the **new** table | the opening is refused until the file is archived | the opening is refused: the table can never be ratified |
| any later entry that reads a row | the entry is refused (`degree canon … is not archived in canon/history/`); the clone reports `canon_pending` | cannot happen: a pin is only ever set to a table that was `ok` when its ballot opened and when it closed |

So an amendment of the degree canon takes these steps in order: the file `canon/history/{new_sha256}.toml` is added to the repository, by an earlier pull request or by the pull request of entries that opens the ballot (section 9.6); the ballot is opened; it passes on the votes; it is closed, and from that entry on replay reads the new table. A table that is not well formed is never put to a vote. No ballot waits for a file: every open ballot can be closed (section 6.7).

### 8.5 Checking the tree

`govern.check_tree(S, root, entries, since, base)` is a **gate**, run by `verify --tree`, not part of replay. `entries` are the entries `S` was replayed from, and `since` is the number of entries that were there before the pull request being judged (the `--since` of section 9.1; none when nothing is being judged). `base` is the tree of the branch the pull request is judged against (`--base-root`; none otherwise). It reports violations in this order: the pins (steps 1 to 4), the archived degree tables (step 4a), the workflows (step 5), the Declaration, the reasons of corrections (step 6). `govern.tree_report` returns both lists, violations and warnings, at once. `govern.tree_warnings(S, root, entries, since)` returns what the gate reports without holding it against the tree (step 6). For each path of `S.pins`, in ascending order:

1. `actual` is `protocol_digest(root)` for `@protocol`; otherwise the SHA-256 of the file's bytes, or the marker `(missing)` when the path is not a regular file. A symbolic link on the way, or a path resolving outside the tree, is a violation by itself, and so is a file of the manifest that is missing or not a regular file (`@protocol: {path} is missing`) and a manifest that is malformed (`@protocol: src/openmasonry/protocol.manifest: {message of section 8.3, step 1}`): such a tree is unlawful whatever the pins say.
2. The path is lawful when `actual = S.pins[path]`.
3. **Prior-pin window.** It is also lawful when `actual = S.prior_pins[path]` and `S.time ≤ S.prior_until[path]`. `S.time` is the time of the last entry of the ledger being checked, not the clock.
4. Otherwise the violation is `{path}: tree sha256 {first 12 of actual}… ≠ ratified {first 12 of pin}… — needs a passed amendment`.

4a. **Every degree table ever pinned stays archived** (`govern.unarchived_tables`). For each digest `d` of `govern.pinned_tables(S, entries)`, in order and each once (the pin of `canon/degrees.toml` in the genesis entry, when the entries are given; the `new_sha256` of every passed amendment of that path; its prior pin; its pin): `canon/history/{d}.toml` (`HISTORY_DIR`) MUST be a regular file of the tree, reached through no symbolic link, whose SHA-256 is `d`. Violations: `canon/history/{d}.toml is missing (every degree table the ledger ever pinned stays archived)`, with the message of step 1 for a link or a file that is not regular; `canon/history/{d}.toml has sha256 {first 12 of actual}…, which is not its name`. Replay reads each of these tables by its digest (section 8.4); a tree that lost one cannot replay its own ledger once `canon/degrees.toml` changes, so the gate keeps them all, and the judge refuses any change in that directory but an addition (section 9.6).

**What the pull request did not change is an alarm, not a lock**. With `base` given, a violation of steps 1 to 5 or of the Declaration check whose path holds exactly the same in `root` as in `base` (the same `@protocol` digest; the same bytes of the file; the same unreadable condition) is reported as a **warning**, with ` (unchanged by this pull request: an alarm, not a refusal)` appended, and the tree is lawful for that pull request. So is a stray name under `ledger/reasons/` (the last violation of step 6) that `base` holds the same: otherwise one file merged around the gate would refuse every later pull request of entries. The reasons of the corrections of step 6 are always judged in full. So an unratified `main` (an amendment passed and nobody applied its text; a file merged around the gate) never stops a departure, a key replacement or any other entry: the audit of `main` (no `base`) still refuses it, which is the alarm, and the pull request that repairs it is judged on what it changes. **A genesis is judged without `base`**: when `since = 0` (`govern.tree_report` ignores `base` then), the six pins of entry 0 must match the tree exactly, whatever the base branch holds. A genesis drafted on a tree that differs from `main` is therefore refused, and not merged with a warning: no amendment ever corrects entry 0, and the pin of `canon/eternal.toml` is never amended.

5. **A closed set of workflows** (`govern.stray_workflows`). Every name directly under `{root}/.github/workflows/`, whether a file, a directory or a link, MUST be a path of the manifest **of that tree**, exactly as spelled. Each one that is not, in ascending order, is the violation `.github/workflows/{name}: a workflow outside the pinned core (src/openmasonry/protocol.manifest) — needs a passed amendment of @protocol`. This holds whatever the pins say: the digest does not read such a file, so no pin can make it lawful. A manifest that is missing or malformed lists nothing, so every name there is then a violation (beside the violation of step 1). A tree without the directory has no such violation (its listed workflows are then missing, which step 1 reports); a directory that cannot be listed is the violation `.github/workflows ({error}): a workflow outside the pinned core …`.

6. **The reasons of corrections** (`govern.missing_reasons`), reported last, after the Declaration check below. The reasons are those of every `correction` entry of the ledger, notes included, as `(seq, reason_sha256)` in order (`govern.cited_reasons`: read from `entries`, and from `S.corrections` and `S.notes` when the caller holds no entries). For each: the file `ledger/reasons/{reason_sha256}.md` (`REASONS_DIR`) of the tree `root`. With a `reasons` directory given (`govern.tree_report`, `missing_reasons` and `stray_reasons` take it), the file `{reason_sha256}.md` of that directory instead, named `reasons/{reason_sha256}.md` in the messages, and the stray names of that directory: `verify --tree` passes it when `--root` is not given and the ledger is not the repository's own (`ledger/entries`), as `reasons/` beside that ledger's entries directory, so that the reasons of a scratch ledger are its own. With `--root` (the judge's run) and for the repository's own ledger, the tree's `ledger/reasons/` is read, as below.
   - **A file that is there and is not the reason is a violation, whatever the age of its correction:** it MUST be a regular file, reached through no symbolic link, of at most `REASON_MAX_BYTES` = 65,536 bytes, and the SHA-256 of its bytes MUST be `reason_sha256`. Violations: `correction {seq}: ledger/reasons/{sha}.md is larger than 65536 bytes`; `correction {seq}: ledger/reasons/{sha}.md has sha256 {first 12 of actual}…, which is not its name`; and, for a symbolic link or a file that is not regular, `correction {seq}: {message of step 1}`.
   - **A file that is missing is a violation for a correction the pull request adds** (`since` is given and `seq ≥ since`): `correction {seq}: ledger/reasons/{sha}.md is missing (the public reason of a correction is archived under its sha256)`. For an older correction, and whenever nothing is being judged (`since` is none: the audit of `main`, a reader's own check), the same sentence is a **warning** (`tree_warnings`; the report of section 9.1 lists it under `warnings`) and the tree is lawful.
   - Then (`govern.stray_reasons`): every name directly under `ledger/reasons/`, whether a file, a directory or a link, other than `.gitkeep` and the names `{reason_sha256}.md` of the corrections of the ledger, in ascending order, is the violation `ledger/reasons/{name}: no correction of the ledger pins this file (ledger/reasons/ holds only the public reasons of corrections, each named after its sha256)`. A tree without the directory has no such violation. So a reason enters the repository with the correction that pins it, or after it, never before, and nothing else enters that directory at all.

Then, when `S.declaration_sha256` is set: the digest of the Declaration in the tree (`H` of the UTF-8 bytes of `[declaration].text` in `{root}/canon/eternal.toml`) MUST equal it. Violation: `canon/eternal.toml: the Declaration's sha256 {first 12}… ≠ the one recorded at genesis {first 12}…` (with `(unreadable)` when the file or the field cannot be read). Because the file is pinned and can never be amended, this is in effect a check of the genesis entry: a genesis that records a digest other than that of the Declaration it pins never passes the gate.

Because `@protocol` is a pin like the others, this gate is what protects the judge itself: a tree in which any file of the manifest differs from the ratified one, the manifest among them, is unlawful until the ledger that comes with it holds a passed amendment pinning the new digest, and a tree with a workflow outside its own manifest is always unlawful. The six genesis pins are all checked, the two charters included.

Step 6 is what makes the reason of a correction public and fixed, and what keeps the directory closed: the judge lets a pull request add reason files beside entries without a code-owner review (section 9.6), and this gate admits only a text whose digest a custodian's signed entry pins. The entry pins a digest, not a link; the judge refuses the pull request that carries a correction without its reason, so a reason cannot be withheld when the correction is made, and a file whose bytes are not its name is unlawful in every tree, so a reason cannot be rewritten after the fact. A reason is **not** required to exist forever for a tree to be lawful: a copy of the repository that has lost an old reason file is reported, not refused, since a rule that made every later tree answer for every file ever published would let one deleted file make the whole repository unlawful for good. Replay itself never opens the file (section 6.19).

The prior-pin window lets the tree keep the previous ratified text between the close of an amendment and the merge of the change that applies it. It lasts until the ledger's own time passes `close time + 30 d`. Only the single latest prior version of a path is accepted. A path that becomes governed by its first amendment has no prior pin: the tree is unlawful until the file has the new content.

---

## 9. Gate checks that are not part of replay

Everything in this section is checked by the judge when a pull request is merged, by an auditor on demand, or by a client before it acts (section 9.7). **None of it is part of replay.** A ledger that passed these gates when its entries were merged is not re-judged against them later, and `replay` of the same entries gives the same state whether or not the gates would pass today. A second implementation of replay MUST NOT apply them inside `apply`.

### 9.1 The `verify` command

The verifier's entry point is the module `openmasonry.verify`, run as `python -P -m openmasonry.verify [flags]`. It is part of the pinned core (section 8.3). `om verify [flags]` calls the same code with the same flags and prints its report; on the repository's own ledger, when that report is valid, it then applies the rule of a client (section 9.7), for which it takes one more flag, `--accept-genesis HASH`. `verify.verify_report` runs, in this order, stopping at the first failure:

| Step | Flag | Check | Failure message prefix |
|---|---|---|---|
| 1 | always | `load`, then `replay` (sections 2.7, 5, 6); with `--since SEQ`, the first `SEQ` entries are taken on trust (below) | `INVALID — ` |
| 2 | `--clock-since SEQ` | section 9.2 | `STALE OR FUTURE TIME — ` |
| 3 | `--pr-author LOGIN --since SEQ` (both or neither), optionally with `--pr-author-id N` | section 9.3 | `WRONG AUTHOR OR KEY — ` |
| 4 | `--anchors-changed FILE` (with `--since`) | section 9.6, the anchors | `UNLAWFUL ANCHOR — ` |
| 5 | `--online` | the last entry is not dated ahead of the verifier's clock (section 9.7), then section 9.4 | `FUTURE HEAD — `, then `FORGED BEACON — ` |
| 5a | `--candidate-root DIR` | the candidate core replays the same ledger to the same head and state (below) | `CANDIDATE DIFFERS — ` |
| 5b | `--tree --base-root DIR` with `--since SEQ` (the genesis pull request, `SEQ = 0`, included) and `DIR` a directory | the degree tables the pull request adds (`govern.added_tables`, below) | `UNLAWFUL ARCHIVE — ` |
| 6 | `--tree [--root DIR] [--base-root DIR]` | sections 8.5 and 9.5 | `UNRATIFIED — ` |

**An empty ledger is valid before any step**: when `load` finds no entry, the command reports `valid` with the message `ledger is empty (no genesis yet)` and runs none of the steps, so no gate judges a tree, a clock, an author or an anchor before the genesis.

**The clock is read once**, before step 1 (`verify_report(a, clock)`), and steps 2 and 5 use that one reading: the time a long replay takes is never held against a fresh entry.

**Entries before `--since` are taken on trust** (section 5.1): `replay(entries, trusted = SEQ)`. Their signatures were verified by the judge when they were merged, and the state digests of their checkpoints were computed then; a run without `--since` verifies everything, and the audit of `main` is such a run. Every other rule is evaluated for every entry, so the state the judge reaches is the state a full replay reaches. The cost of judging a pull request then grows with the rules of the old entries, not with their signatures and digests.

**The tree's own archive** (`canon.archives`). With `--root R` (with or without `--tree`), every replay of the run, the one of step 1 and the one of the identity step (section 9.3), looks degree tables up in `R/canon/history` too (section 8.4): a table is found there under its own digest only, so the directory can add a table and never change one. So a pull request of entries may carry the table that its new amendment ballot of `canon/degrees.toml` names, and open that ballot in the same pull request (M6); and the summary the judge prints (`verify --ledger pr/ledger/entries --root pr`, section 9.6) replays it the same way.

**Step 5b, the degree tables a pull request adds** (`govern.added_tables(R, B, entries, SEQ)`, with `R` the `--root` tree and `B` the `--base-root` tree). For every name under `canon/history/` of `R` that is not under `canon/history/` of `B`, in ascending order, one problem at most: `{rel}: {reason}` when the file cannot be read safely (as the paths of section 8.3, step 2); `{rel}: an archived degree table is named after the sha256 of its bytes ({first 12 characters of that sha256}…)` unless its name is `{sha256 of its bytes}.toml`; `{rel}: not a well-formed degree table (33 degrees with exact fields)` unless it is well formed (section 8.4); and, when the pull request adds entries (`SEQ` is less than the number of entries), `{rel}: a pull request that adds entries archives only the degree table its new amendment ballot of canon/degrees.toml names (the genesis pull request: the one its genesis pins)` unless its digest is the `new_sha256` of a `ballot_open` of kind `amendment` and path `canon/degrees.toml` among the entries from `SEQ` on, or, for the genesis pull request (`SEQ = 0`), the `pins["canon/degrees.toml"]` of entry 0. `rel` is `canon/history/{name}`. Any problem fails the step, with the first as its message. The allowance for a pull request of amendment-ballot entries (section 9.5) never applies to it: an unlawful archive is never a warning.

Before step 1, a negative `--clock-since` or `--since` is a usage error: the command fails with `USAGE — --clock-since and --since count entries from 0; a negative value is an error`. `SEQ` is a count of entries from 0. `--pr-author` without `--since`, or the reverse, fails at step 3 with `USAGE — --pr-author and --since go together`; `--pr-author-id` without `--pr-author` fails there with `USAGE — --pr-author-id goes with --pr-author and --since`; `--anchors-changed` without `--since` fails at step 4 with `USAGE — --anchors-changed goes with --pr-author and --since`, and a file that cannot be read with `USAGE — cannot read {file}: {error}`. `--base-root` without `--tree` and `--since` fails before step 6 with `USAGE — --base-root goes with --tree and --since`.

**A candidate core** (`--candidate-root DIR`, `verify.candidate_problems`). The verifier runs, as a separate program, `python -P -m openmasonry.verify --ledger LEDGER --json` with `DIR/src` as its only module path (and nothing of `DIR` runs in the verifier's own process), and compares the report with its own: the candidate MUST report the ledger valid (`the candidate core refuses the ledger: {message}`), with the same `entries` and `head` (`the candidate core reaches {name} {value}, the pinned core {value}`), and, when its `state_version` is the verifier's, the same `state_sha256` (`the candidate core reaches the state digest {d1}, the pinned core {d2} (a rule change must not change the replay of the entries already merged: branch it on a fixed future time or entry number written in the code, never on the protocol epoch alone)`). A candidate with another `state_version` is held to the head alone, and a warning says so. A candidate that gives no report within `CANDIDATE_TIMEOUT` = 3,600 seconds, or no JSON object, fails (`the candidate core of {DIR} gave no report …`). This is how a change of the core is checked before it is merged: it must replay what is already kept exactly as the pinned core does, so a rule that changes is made to apply from a fixed time or `seq` stated in the text the ballot pinned (section 12, point 68). The `candidate` job of `tyler.yml` runs it on every pull request (event `pull_request`, never in the judge, which runs no code of a pull request); electors check it before they vote an amendment of `@protocol`. **The check executes the candidate's code**, as whoever runs it, with that user's files, keys and ssh-agent in reach: a candidate tree is untrusted until it is ratified. Electors rely on the `candidate` job, or run the check only in a disposable container or VM that holds no keys, never where their member key lives. The client `om verify` therefore runs a candidate only when the person types `RUN` at its terminal prompt or passes `--i-trust-this-code`; otherwise it runs nothing and exits with status 2. The pinned `python -P -m openmasonry.verify` (the CI job) does not ask.

The exit status is 0 when every requested check passes and 1 otherwise (2 for a command line that cannot be parsed). With `--json` the command prints one object, schema `om.verify/1`, with exactly the members `schema`, `valid` (boolean), `entries` (the number of entries replayed), `head` (the entry hash of the last one, or null), `state_sha256` (the state digest of section 4.11 of the state replay reached; null for an empty ledger and for one that replay refused), `state_version` (the `v` of the state document this core writes, `STATE_VERSION`), `message` (the text output without its `also:` and `warning:` lines), `problems` (every violation found by the failing step, or `["usage"]` for a usage error; empty when valid) and `warnings` (what step 6 reports without refusing: the reasons of older corrections that the tree does not hold, what was unlawful already in the base tree, and, for a pull request of amendment-ballot entries, the pins the tree does not match; section 9.5; and the warning of step 5a). The text output prints each warning on a line `warning: …`.

The judge runs every step but 5a on the pull request's ledger: `python3 -P -m openmasonry.verify --ledger pr/ledger/entries --tree --root pr --base-root base --online --clock-since BASE --pr-author AUTHOR --since BASE --pr-author-id ID --anchors-changed FILE`, where `base` is the checkout of the base branch the verifier itself runs from, `BASE` is the number of entries on the base branch, `FILE` holds what the pull request changes under `ledger/anchors/` (section 9.6), and `AUTHOR` and `ID` are the login and the numeric id of the pull request's author as GitHub's event states them (`pull_request.user.login`, `pull_request.user.id`). The step also passes the workflow's read-only token in `GITHUB_TOKEN`, which `identity.fetch_github_user` sends only to raise the rate limit of its lookup. This is the only program of the repository the judge runs. The audit of `main` (`.github/workflows/tyler.yml`, job `audit`) runs the same entry point with `--tree`, then with `--tree --online`; the second run is the one that reads a clock, and it refuses a `main` whose last entry is dated ahead of it (`FUTURE HEAD`, section 9.7).

### 9.2 Clock tolerance

With `real` the judge's clock at the moment of judging: every entry with index `≥ SEQ` MUST have a time `t` with

```
real − CLOCK_TOLERANCE  ≤  t  ≤  real + JUDGE_FUTURE_TOLERANCE          (6 hours back, 2 minutes ahead)
```

Both bounds are inclusive, and both are named constants of `ledger` (section 3.6). Violation: `entry {seq} claims {time}`.

**Two minutes to merge, ten before the alarm.** The judge merges nothing dated more than `JUDGE_FUTURE_TOLERANCE` = 2 minutes ahead of its clock. A reader raises the alarm of section 9.7 only for a head dated more than `FUTURE_TOLERANCE` = 10 minutes ahead of the reader's clock. The eight minutes between the two are the margin for honest clocks: an entry the judge accepted at its limit does not alarm a reader whose clock is up to eight minutes behind the judge's. The reference tools never stamp an entry before the head: `ledger.make_entry` stamps the later of the machine's clock and the head's time plus one second, so a tool whose clock is a little behind the last entry still writes an entry that C8 accepts.

Because replay requires times to be non-decreasing, this gate bounds how far any accepted entry could be backdated when it was merged. The protocol's protective delays are chosen to exceed the 6-hour tolerance: `REVEAL_GAP` (6 h 15 min) and `BEACON_DELAY_ROUNDS` (8 h). Replay itself enforces only monotonic time.

### 9.3 Pull request author, key listing and GitHub account

`identity.pr_problems(entries, since, author, author_id, founder_id)` walks the ledger, keeping the state before each entry, and for each entry with `seq ≥ since` reports what follows.

**A person is a GitHub account, and an account is its numeric id.** A login can be renamed, and a login that was given up can be taken by someone else. The author of a pull request is therefore held to the `github_id` the ledger records, never to the login. The author's id is `author_id` when it is given (the judge passes the id of the pull request event, and no lookup is made); otherwise it is looked up once for `author`, as in check 3, and used for every entry of the walk.

1. **Whose pull request.** By the first that applies:
   - An entry whose type is in `WITNESS_TYPES` and whose actor is a key of `S.witnesses` at that point, and an entry whose type is in `CUSTODIAN_SIGNED` and whose actor is a key of `S.custodians` at that point: **any author**. A witness key and a custodian key belong to no GitHub account.
   - A `depart` and a `rekey_object` (`identity.CARRIED`): **any author**. Each is signed by the key the ledger holds for the member and restricts nobody but that member; a member whose GitHub account is in other hands must still be able to leave, and to stop a recovery of their key, and then needs someone else to carry the entry.
   - A `genesis`: check 5.
   - A `petition`: check 4.
   - Every other entry whose actor has a record in `S.members` at that point: the numeric id of the pull request's author MUST equal that record's `github_id`. Violation: `entry {seq} ({type}): {actor} is the GitHub account with id {github_id}, but the pull request is by the account with id {found}`.
   - Any other entry (its actor is nobody the ledger knows; replay refuses it): the actor MUST be the same login as the author. Violation: `entry {seq} ({type}) has actor {actor}, but the pull request is by {author}`.
2. **Key listing.** For a `petition`, `body.key` MUST be listed for the account at the time of judging, and so MUST the member's new key: `body.key` of a `rekey` and of a `rekey_recover`, and, for a `rekey_recover_apply` whose actor has a record in `S.recoveries` at that point, the `key` of that record, asked again on the day of the application (`identity._key_listed`). The list is `https://github.com/{login}.keys`, with `login` the login the account has **today**: the pull request author's login, once check 1 or check 4 found the author's id to be the right one, and the actor's login otherwise. Each non-empty line of the response is reduced to its first two whitespace-separated fields joined by one space, and the key is compared with those strings, so a key of either type is listed in exactly its text form of section 2.6. Violation: `entry {seq}: the petition key is not listed at {url}`, or `entry {seq}: the new key is not listed at {url}` for a `rekey`, a `rekey_recover` and a `rekey_recover_apply`.
3. **Invited account.** For an `invite`, `body.login` MUST be, at the time of judging, the GitHub account whose numeric id is `body.github_id`. The id is the member `id` of the JSON object served at `https://api.github.com/users/{login}` (`identity.fetch_github_user`); the member `login` of the same object MUST be the same login as `body.login` (case-insensitive). The same check is made for each element of `body.founders` of a `genesis`, in order. It is skipped for a login that does not match `LOGIN_RE` (replay refuses that entry). Violation: `entry {seq}: the GitHub account {login} has id {found}, not {github_id}`.
4. **Petitioner's account.** For a `petition` whose actor has a record in `S.invitations` at that point, the numeric id of the pull request's author MUST equal that invitation's `github_id`. Violation: `entry {seq}: the invitation is for the GitHub account with id {github_id}, but the pull request is by the account with id {found}`. A petition without an invitation is left to replay, which refuses it (P0).
5. **The founder's account.** A `genesis` is accepted only from the account the pinned core names: `founder_id`, which is `canon.FOUNDER_GITHUB_ID`, the `founder_github_id` of `src/openmasonry/network.toml` in the code that judges. In this order: it MUST be set (at least 1; a tree that carries 0 refuses every genesis, and the repository's first commit sets it to the id of the founding account): `entry {seq}: founder_github_id is not set in src/openmasonry/network.toml (the genesis is accepted only from the founder's GitHub account: set it to the numeric id of the first founder before the genesis)`; the `github_id` of the first founder MUST equal it: `entry {seq}: the first founder states the GitHub id {id}, but src/openmasonry/network.toml names the founder with id {founder_id}`; and the numeric id of the pull request's author MUST equal it: `entry {seq}: the genesis comes from the founder's GitHub account (id {founder_id}), but the pull request is by the account with id {found}`.
6. **Fail closed.** If the key list cannot be fetched: `entry {seq}: cannot fetch {url} ({error}); refusing (fail closed)`. The same message, with the URL of the account, when an account cannot be looked up, when the answer is not a JSON object with an integer `id` and a string `login` (`the answer has no numeric id or no login`), or when it names another login (`answered for another login, {login}`).

After the checks of an entry, the entry is applied to the state on trust (every signature accepted, no digest computed); if it is refused, the refusal is reported and the walk stops.

Together, checks 3 and 4 bind an admission to one GitHub account: the Master names a login and its numeric id; the judge confirms that the login is that account when the invitation is merged; and the petition is accepted only from a pull request opened by that account. Another account that takes over the login cannot petition (check 4 fails for its id). An account renamed after the invitation still can: it is the same account, and its key is looked for under the login it has now.

For a `rekey`, checks 1 and 2 mean that the new key is one the member's GitHub account lists today, in a pull request opened by the very account the ledger records for the member; the old key's signature and the new key's proof are rules of replay (section 6.18). A login that was renamed away and taken by another account cannot carry the member's `rekey`, and a member who renamed the account loses nothing. When the judge passes the id of the pull request event, no account is looked up.

For the recovery of a key the same checks stand in for the signature of the old key, which is lost or frozen: the request and its application come from the GitHub account the ledger records for the member (check 1), with a new key that account lists (check 2), on both days. Replay cannot ask any of that: it accepts a `rekey_recover` from any key that is new to the ledger, for any recoverable record (section 6.26). **The gate is what keeps a stranger from asking in a member's name**; what keeps a stranger who passed it (who controls the member's GitHub account) from completing the recovery is the co-signers, the notice and the objection of the old key, which any pull request may carry (check 1), and after it the judgment of the Master Builders (sections 6.26 to 6.30). Where the member is the only Master Builder, nobody co-signs, and this gate, the 45 days of notice and the old key are all there is (section 12, point 62). A `rekey_cosign` and a `rekey_oppose` are ordinary entries of the Master who signs them.

**The founder's claim is the founder's account** (check 1). A `custodian_claim`, a `custodian_claim_apply` and a `custodian_claim_object` are entries a member signs: the pull request's author MUST be the GitHub account the ledger holds for the actor. A stolen member key of a founder therefore claims the office only from the founder's own GitHub account, and the objection of one Master Builder who is not a founder voids it in replay (section 6.32).

**The genesis is tied to the repository's owner** (check 5). Entry 0 is the one entry no earlier state can vouch for: without the check, whoever opened the first pull request with a lawful genesis would found the fraternity. The founder's id is in a file of the pinned core, so the genesis pins it with `@protocol`, and the judge reads it from the base branch's code, never from the pull request.

A historical entry is never re-checked against today's key list or today's accounts.

### 9.4 Public beacons (drand)

`beacon.audit`: for every `{round, beacon}` used by a lot (with `--since SEQ`, by a lot of the entries from `SEQ` on), the verifier fetches `{relay}/{DRAND_CHAIN}/public/{round}` from the first relay of `RELAYS` that answers and compares the `randomness` field with `beacon`. Violation: `round {round}: recorded {first 12}… ≠ drand`. If no relay answers, the command fails.

The state keeps no beacon (the history `beacons` holds only their count and hash chain): `verify.lot_beacons` reads them from the entries of a ledger that replays. An `exam_draw` used `body.beacon` with the `beacon_round` of the latest `exam_open` of the same candidate and degree, a `council_draw` with the `beacon_round` of the latest `council_call`; each records exactly one, so the beacons of the entries before `SEQ` are the first ones, as many as those entries hold lots.

Offline replay accepts any 64 hexadecimal characters as a beacon (F4, Y2). The correctness of the lot therefore rests on this gate and on anyone re-running it. The judge fetches the beacons of the entries it is judging; the audit of `main` (no `--since`) fetches all of them.

### 9.5 Governed files

`verify --tree` (section 8.5). The judge checks the pull request's tree against the pins of the pull request's ledger, with the base branch's code. A pull request that changes a file of the pinned core (section 8.3) or any other governed file therefore passes only when its ledger already holds the passed amendment that pins the new bytes (or still holds the prior pin, within its window). A pull request that changes code outside the core changes no pin, and this gate has nothing to say about it: such changes are left to code-owner review. The one exception is a file under `.github/workflows/`: the tree gate refuses any that the pull request's manifest does not list (section 8.5, step 5). A pull request that changes the manifest itself changes a file of the core, and passes on the same condition as any other such change (section 8.3, "Changing the list").

**What a pull request did not change does not refuse it** (`--base-root`, section 8.5). The judge passes the base branch's tree, so a violation that is there already, in the very same bytes, is a warning: a ledger-only pull request (the judge's own gate allows it to change nothing but entries, anchors and reasons) is therefore judged only on what it adds, and an unratified `main` is an alarm for the audit, never a lock on the entries of a pull request. A pull request that changes a governed file is held to the pins for that file, and the pull request of the genesis to all six (section 8.5).

**The amendment that repairs a tree always gets through** (`govern.amendment_only`), also without `--base-root`. A tree can become unlawful with nobody changing a file: an amendment moved a pin, and the `PRIOR_PIN_DAYS` of the text before it ran out before the new text was merged; or an amendment pinned a wrong digest. If the gate then refused every pull request, the ballot that corrects the pin could never be opened, voted or closed. So when `--since SEQ` is given, at least one entry was added, and **every** entry from `SEQ` on is an entry of an amendment ballot (a `ballot_open` of kind `amendment`, or a `ballot_commit`, `ballot_reveal` or `ballot_close` whose ballot was opened as an amendment, in this pull request or before), the violations of section 8.5 do not refuse the pull request, **unless one of them is about the public reasons** (step 6: a violation that begins with `correction ` or with the reasons directory, `ledger/reasons/`): they are reported under `warnings`, and the message ends with `note: the tree does not match the ratified pins; accepted because every new entry belongs to an amendment ballot`. Such a pull request changes nothing governed (the judge's own gate, section 9.6, lets it add only entries, the files of a checkpoint, the public reasons of corrections and a degree table, each held to its own rule), so it cannot be what made the pins unlawful. The reasons are never let through: an amendment ballot needs no file under `ledger/reasons/`, and a pull request of entries merges without review, so the allowance would otherwise let any elector of an amendment ballot put any file there. Any other entry beside them, and the tree is held to its pins.

### 9.6 Workflow gates

The judge workflow (`.github/workflows/judge.yml`) runs on pull requests into `main` and refuses a pull request before it runs `verify` when:

- a file under `ledger/entries/` is modified, renamed, type-changed or deleted (entries may only be added);
- a file added under `ledger/entries/` is not an entry in its shard, `ledger/entries/{shard}/{seq}.json`: the seq in six digits, or seven to sixteen digits without a leading zero, and the shard four digits, or five or more without a leading zero, equal to `seq // 1000` written the same way (`{seq // 1000:04d}`). The workflow checks the form with one pattern and the shard by the digits of the seq without its last three (an `awk` program, so no number is converted), and the message is `Only entry files, each in the shard of its seq (ledger/entries/NNNN/NNNNNN.json), may be added to ledger/entries/:`. The loader of section 2.7 refuses any other name there as well, and its widths are minimums, so the ledger does not stop at 1,000,000 entries, nor at 10,000,000;
- a file under `canon/history/` is modified, renamed, type-changed or deleted (the archive only grows; `canon/history/` also has a code owner);
- it adds or changes a file Python could execute implicitly (`__pycache__/`, `sitecustomize.py`, `usercustomize.py`, `*.pyc`, `*.pyo`, `*.pth`, `*.so`, `*.dylib`, or a `.py` file at the repository root);
- it adds or changes anything under `src/` other than a file directly in `src/openmasonry/` (a loose module or another package under `src/` would be found before the standard library, and a directory inside the package before the pinned module of the same name);
- it adds a symbolic link or a submodule, or changes a file into one;
- its tree (the head commit, not only the difference) holds any path at or under `.github/workflows`, compared without regard to case, other than a file the pull request's own manifest lists: a line of `src/openmasonry/protocol.manifest` at the head commit that is exactly `.github/workflows/` followed by one segment of letters, digits, `.`, `_` and `-`. The workflow reads that file as data (`git show`); when it is absent, nothing is listed. The message is `Only the workflows of the pinned core may exist under .github/workflows/ (a new one needs an amendment of @protocol that lists it in src/openmasonry/protocol.manifest):`. This is a second view of the rule of section 8.5 (step 5), written out in the workflow; like that rule it only asks that the file be listed, and whether a tree with that manifest is ratified is decided by the digest (section 9.5). `tests/test_core.py` holds the two views to the same verdicts;
- it adds entries **and** changes anything else. The exceptions are the witness's files: an **added** `ledger/anchors/{seq}.root` or `ledger/anchors/{seq}.root.ots` (`{seq}` six digits or more), each then held to the checkpoint that names it by the verifier (below); an anchor file that is modified is not excepted; an **added** file `ledger/reasons/{64 hex}.md`, the public reason of a correction (a reason that is modified or deleted is not excepted; and the tree gate of section 8.5 refuses a tree in which the reason of a correction the pull request adds is missing, in which any reason does not hash to its name, or in which that directory holds a file no correction pins); and an added `canon/history/{64 hex}.toml`, a degree table, in any pull request of entries; in one after the genesis the verifier then holds it to its name, to its form and to the amendment ballot of `canon/degrees.toml` that the pull request opens (step 5b of section 9.1).

**Anchors belong to checkpoints** (`govern.anchor_problems`, step 4 of section 9.1). The workflow writes what the pull request changes under `ledger/anchors/` (`git diff --no-renames --name-status`, one line per file: a status letter, a tab, a path; `govern.parse_changes`) to a file and passes it as `--anchors-changed`. For each line whose path is under `ledger/anchors/`:

- a file **modified** (`M`) is refused: `{path}: an anchor file is never changed once merged (a checkpoint's root and proof are added with it, and an upgraded proof stays outside the repository)`;
- any other status but `A` (a deletion, a line of another form): `{path}: an anchor is added, never changed, deleted or renamed`;
- a file is **added** (`A`) only when a `witness` entry of the same pull request (`seq ≥ SEQ`) names it in `anchor`, or names it with `.ots` appended (the root beside its proof). Violation: `{path}: no witness entry of this pull request names this anchor`;
- the file MUST be a regular file of the tree, reached through no symbolic link, of at most `ANCHOR_MAX_BYTES` = 16,384 bytes: `{path} is not a regular file`; `{path} is larger than 16384 bytes`;
- **its bytes are what the checkpoint determines** (`govern.anchor_mismatch`): all of them for a root file, the header and digest that begin it for a proof, for every `witness` entry of the pull request that names it, as `{path}: {why}`. A checkpoint without `root` anchors no file: `the checkpoint that names it states no root, so it anchors no file`. The file the checkpoint names in `anchor` is its **proof** when that name ends in `.ots`: it MUST begin with `OTS_PREFIX` (the 31-byte header of an OpenTimestamps proof file, `00 4f 70 65 6e 54 69 6d 65 73 74 61 6d 70 73 00 00 50 72 6f 6f 66 00 bf 89 e2 e8 84 e8 92 94`, then the major version `01` and the operation `08`, SHA-256) followed by the 32 bytes of SHA-256 of the root file, `root` and a newline (`LF`) in ASCII: the digest an OpenTimestamps client stamps for that file. Otherwise: `not an OpenTimestamps proof of the root the checkpoint signs (it must begin with the format's header, version 1, the SHA-256 operation and the digest of the root file)`. Every other file a checkpoint names (the name without `.ots`, or an `anchor` that does not end in `.ots`) is its **root file**, and MUST be exactly `root` and a newline: `not the root the checkpoint signs (a root file holds the root and a newline, nothing else)`.

So the one directory a ledger-only pull request may write to without a review holds only roots and proofs that signed checkpoints name, each small, and whoever carries a checkpoint (anyone may: section 9.3) chooses neither the bytes of its root file nor whose root its proof stamps. Of a proof, only the header and the digest that begin it are checked; the bytes after the digest (the calendars' operations and attestations, up to `ANCHOR_MAX_BYTES` in all) are not checked at all, here or anywhere in the verifier. A witness signs the root and the path, not the bytes of the proof, so whoever carries a checkpoint chooses what follows the digest: it may be junk, which makes that proof worthless, and nobody reviews it. A proof is checked against Bitcoin by whoever relies on it (`ots verify` on the root file). Nothing merged is ever changed: a proof stays as it was stamped (pending calendar attestations), and a complete proof is obtained later, outside the repository, with `ots upgrade` on a copy.

**No third-party action, no fixed Python**. The judge checks out the base branch and fetches the pull request with plain `git` and no credentials, and runs the runner's `python3`: the verifier needs nothing but the standard library. The `audit`, `tests` and `candidate` jobs of `tyler.yml` do the same; only the `engine` job, which is no part of any verdict, uses an action (`setup-node`, pinned to a commit), and so does `pages.yml`, which publishes the Observatory and judges nothing (`actions/upload-pages-artifact` and `actions/deploy-pages`, each pinned to the full commit of a release). **The judge is a convenience; `verify` is the law**: a merge made without it is lawful when the resulting `main` passes the pinned `verify --tree` (with the checks of a pull request), and each such merge is recorded as a `note` (`docs/operations/RECOVERY.md`, section 10).

**The jobs.** `judge.yml` has two: `judge`, the gate (the required check, `docs/operations/LAUNCH.md`), and `admit`, which, once `judge` passes on a pull request that adds entries (and so, by the gates above, nothing else but the files of a witness and the reasons of corrections) and is not a draft, enables auto-merge for the judged head commit; it checks out nothing. A pull request of anything else needs a code owner's review. `tyler.yml` holds the others but the two jobs of `pages.yml` (`build` and `deploy`, which publish the Observatory), and no job of either is named `judge`, so only the judge can meet the required check: `audit` (section 9.1); `alarm`, which opens a capture alarm on `main` when the offline audit fails, at once, and when the online audit has failed three times in a row; `tests`, the test suite of a pull request and of `main` (feedback, not the gate); `candidate` (section 9.1; section 12, point 67); `engine`, the agent engine, no part of any verdict; and `applications`, daily and on demand, which closes open applications older than 60 days with a notice of how to apply again, at most 50 a run, never the issue of a member (any status), of a login that holds or ever held an invitation, or of a petitioner. `audit` and `applications` also run daily on a schedule. GitHub disables the scheduled runs of a workflow after 60 days without activity in a public repository; a witness's checkpoint pull requests keep it active. Should the schedule stop, the Custodian or a maintainer re-enables the workflow and runs it by `workflow_dispatch`; no job commits to the repository to keep it active.

The judge runs from the base branch's code and reads the pull request's files as data. Because of that, the degree tables (section 1.6) come from the **base branch's** tree, and also from the `canon/history/` of the pull request's tree, under its own digest only (section 8.4), in every replay the judge runs: the gate's, the identity step's and the summary's (section 9.1).

### 9.7 The rule of a client: the verified head, and a head dated ahead

Replay cannot see that history was rewound. A ledger cut back to an earlier entry and continued another way replays as well as the true one, and so does a ledger whose newest entries were simply removed. What can see it is memory: **each clone remembers the head of the canonical ledger it last verified**, and holds the canonical ledger against that memory before it drafts, approves or signs anything. This section binds the reference tools (`om`, and the witness node `node/witness.py`); a second implementation of a client SHOULD do the same. The decision is pure and in the pinned core (`ledger.head_verdict`, `ledger.remember_head`, `ledger.future_head`); the files and git are outside it (`actions.canonical_guard`, `witness.verified_head`).

**The canonical ledger** of a clone is `ledger/entries/` of the branch `main` of the canonical repository (`canon.CANONICAL_REPO`, read from `src/openmasonry/network.toml`), as the clone last fetched it, read from git by the full name of that branch (`refs/remotes/{remote}/main`, so that no tag or other ref of the same short name can stand for it) and never from the working copy: a working copy may hold entries of one's own that are not merged, and they never count.

**The memory** is one JSON value, kept outside the repository: for `om`, the file `heads.json` of the configuration directory (`$OM_HOME`, by default `~/.config/openmasonry`), private to the user; for the witness node, the file `OM_WITNESS_HEADS` names (by default `witness-heads.json` beside its clone).

```json
{"v": 1, "heads": {"<entry hash of a genesis>": [{"seq": 41, "hash": "<entry hash of entry 41>"}]}}
```

Each element is a **mark**: the head of a history of that genesis that this clone verified, or that the person accepted. One history has one mark, which moves forward with it; a second mark under the same genesis exists only after a fork was accepted (below). Anything in the file that is not a well-formed mark is ignored.

**The verdict.** Let `hashes` be the entry hashes of the canonical ledger, after it verified, `n` their number, and `known` the entry hashes of the ledger the clone holds in its working copy. `head_verdict(store, hashes, known)` is the first that applies:

| Verdict | Condition | What the client does |
|---|---|---|
| `first` | The memory holds no mark at all. | Remembers the head. A new device starts here: it trusts the first history it verifies. |
| `genesis` | The memory holds marks, and none for this genesis. | Refuses: `DIFFERENT GENESIS — the canonical ledger starts from the genesis {hash}, …`. A different genesis is a different fraternity. |
| `ok` | Some mark `(seq, hash)` has `seq < n` and `hashes[seq] = hash`: the canonical ledger holds an entry this clone verified, at its place. | Remembers the new head, and goes on. |
| `behind` | No mark is held, and some mark has `seq ≥ n` without being shown lost: the canonical ledger ends before it. | Reports `BEHIND — the canonical ledger this clone fetched has {n} entries, and this clone verified entry {seq} (hash {hash}) earlier: …`, drafts and signs nothing on it, and remembers nothing. Not a rollback: the same entries, fewer of them, as far as this clone can tell (a mirror that lags). |
| `rollback` | No mark is held, and every mark is **lost**: `seq < n` and `hashes[seq] ≠ hash`; or `seq ≥ n`, `known` holds the mark (`known[seq] = hash`) and `hashes` is not a prefix of `known`. | Refuses: `ROLLBACK — the canonical ledger no longer contains entry {seq} (hash {hash}) that this clone verified earlier`, with the highest lost mark. Nothing is drafted, approved or signed. |

**When the memory changes.** Only after the canonical ledger itself verified (it is a prefix of the ledger just replayed, or it is replayed from its own genesis), and only on `first`, on `ok`, or when the person accepts. `remember_head` then replaces every mark the history holds by its head `(n − 1, hashes[n − 1])`, and keeps the marks it does not hold. A canonical ledger that does not verify is reported (`INVALID — the canonical ledger does not verify: …`) and is never remembered.

**Accepting another history.** `om verify --accept-genesis HASH` (for the witness node, the variable `OM_WITNESS_ACCEPT_GENESIS`), where `HASH` is the entry hash of the genesis of the canonical ledger as it stands, remembers that ledger's head whatever the verdict: once for a new fraternity, and once for a **fork**, a history of the same genesis that no longer holds the remembered head. The mark of the history that was left stays, so a clone that still follows it keeps working. A `HASH` that is not the genesis of the canonical ledger accepts nothing. This is the person's decision: an agent never passes the flag by itself.

**Where it is applied.** `om verify` on the repository's own ledger (the report keeps its schema: a rollback, another genesis and a canonical ledger that does not verify make it invalid, with the message above; `behind` adds its line to the message of a valid report); `om doctor`; before every draft and before every approval (`actions.propose`, `actions.cmd_approve`: the commands refuse with the message, and nothing is signed); in the sync status that precedes every publication (`actions.canonical_status`, also when the repository cannot be reached, on what was last fetched); and in every cycle of the witness node, before it signs: a rollback, another genesis or a `main` that does not verify is a **capture alarm** and the node signs nothing; on `behind` it logs and only verifies.

**A head dated ahead of the clock.** `future_head(t, now)` holds when `t − now > FUTURE_TOLERANCE` (10 minutes), with `t` the time of the last entry, which is the latest time of the ledger (C8). The judge merges no entry dated more than 2 minutes ahead of its own clock (section 9.2), so a head ten minutes ahead of an honest clock did not pass the judge. In a ledger that is already merged it means the gate was passed around, and every notice period of the protocol (14 days before a correction is applied, 21 before a recovery, the windows of a ballot) is counted from entry times: a post-dated entry starts a wait in the future, and a later entry dated honestly is refused by C8 until the clock catches up. So it is a **capture alarm condition** for whoever verifies:

- `verify --online`, the audit of `main` (section 9.1, step 5): `FUTURE HEAD — entry {seq} is dated {time}, more than 10 minutes ahead of this clock ({now})`;
- `om verify` and `om doctor` on the repository's own ledger, and the canonical ledger in the rule above (`FUTURE HEAD — entry {seq} of the canonical ledger is dated {time}, ahead of this clock ({now}): …`): nothing is drafted or signed on it;
- the witness node: a capture alarm, and nothing is signed.

Replay itself reads no clock and accepts the ledger: the condition is the reader's, and a reader whose own clock is slow by more than ten minutes raises it wrongly (section 12, point 48).


---

## 10. Invariants

Each statement holds for every state `Sᵢ` reached by a successful replay under the current code, and can be tested against it. `e[i]` is the entry with `seq = i`.

1. **Chain.** `S.seq + 1 = len(S.hashes)`; `S.hashes[i] = entry_hash(e[i])`; `S.head = S.hashes[S.seq]`; `e[i].prev = S.hashes[i − 1]` for `i > 0`, and `e[0].prev = ZERO_HASH`.
2. **One genesis.** `e[0].type = "genesis"`, and no other entry has that type.
3. **Monotonic time.** `time(e[i]) ≥ time(e[i − 1])`; `S.time = time(e[S.seq])`; every entry time lies in the years 2020 to 9000.
4. **Prefix.** For every `j ≤ n`, replaying `e[0..j]` succeeds whenever replaying `e[0..n]` does, and yields exactly the state the longer replay had after entry `j`. No later entry changes whether an earlier entry was lawful.
5. **Determinism.** With the same three inputs (section 1.6), replay yields the same outcome and the same state on every run, on every runtime and in every conforming implementation. No rule reads a clock, a random source, the network, a floating-point value or a Unicode table.
6. **One encoding.** Every accepted entry is a value in the sense of section 2.2: its strings are ASCII, its numbers are integers within `±(2^53 − 1)`, it holds no `null`, its body has exactly the fields of its type, and its canonical encoding is at most 8,192 bytes (32,768 for entry 0).
7. **Signed by the right key.** Every accepted entry satisfied `sig_ok` for exactly one key, determined by the state before it: the first founder's key (genesis), the key in the body (petition, under a live invitation), a witness key (the four witness types, when the actor is a witness), a custodian key (the five `CUSTODIAN_TYPES`), a custodian's revoke key (`custodian_revoke`), the new key of a recovery (`rekey_recover`: the key in the body; `rekey_recover_apply`: the key the request named), or the key of the member record under `actor` as it stood before the entry (for a `rekey`, the key being replaced; for a `rekey_object`, the key whose recovery it stops). An accepted `rekey` and an accepted `rekey_recover` also satisfied `sig_ok` for the new key, over the proof message of section 6.18; an accepted `ballot_open` that proposes a witness, for the proposed key, over the witness message; and an accepted genesis for the key of every founder after the first, of every witness and for the two keys of every custodian it names, over the messages of section 6.1. ("Satisfied" is of a replay with `trusted = 0`; section 5.1.)
8. **No act by an inactive member.** Every accepted entry whose signer key was resolved through `S.members` was signed by a member with `is_active(now)`, with three exceptions: a `depart`, a `rekey` or a `rekey_object` signed by a member under an unserved suspension; a `rekey_object` signed by a member who departed; and the `ballot_reveal` of a `voided` record in a ballot in which it held a commitment. And none was signed by the key of a member that was frozen at that entry (by a freeze in force, or by a recovery under way), except a `depart`, a `rekey`, a `rekey_object`, a `ballot_commit`, a `ballot_reveal`, and every entry of an amendment ballot or of a ballot that removes a custodian. No `correction_object` was signed by a frozen key. A login whose record is expelled, departed or voided gets no entry accepted under that rule but those two exceptions; besides them the only entry such a login can have accepted on its own key is a `petition`, under P0 and P1.
9. **One member, one vote.** In every ballot, `commits` and `reveals` hold at most one value per login, each written by exactly one entry; every key of `reveals` is a key of `commits`; every key of `commits` is in `electors`; every revealed vote is counted at the close, so `yes + no = len(reveals) ≤ len(electors)`. No degree, title, seat or score changes the weight of a vote, and no correction changes who the electors of a ballot are or which of their votes count.
10. **Frozen ballots.** After `ballot_open`, a ballot's `id`, `kind`, `subject`, `electors`, `commit_until`, `reveal_until`, `opened`, `opened_by` and `frozen` never change, by any entry, a correction included. No entry but the elector's own `ballot_commit` and `ballot_reveal` ever writes `commits` or `reveals`, and no entry removes or changes what they hold.
11. **Results change by a close, or by an applied correction, and then never again.** A ballot's `result` goes from null to `passed`, `failed` or `lapsed` in exactly one `ballot_close` entry. Besides that, exactly two changes exist, each made by one `correction_apply` and each final: null to `voided` (an open ballot, by a `void_ballot`), and `passed` to `undone` (by an `undo_ballot`). `failed`, `lapsed`, `voided` and `undone` never change; no result ever becomes `passed` except by the ballot's own close. `corrected` is set exactly with `voided` or `undone`. Ballot ids are never reused, also after the ballot left the state (B3 reads `S.retired`).
12. **Window order.** For every ballot, on the ballot's own clock (`ballot_time`, section 7.8; the entry's time for a ballot never paused): every commit has `ballot_time ≤ commit_until`; every reveal has `commit_until + REVEAL_GAP ≤ ballot_time ≤ reveal_until`; the close has `ballot_time > reveal_until`, or comes when every elector has revealed. No commit, reveal or close of a ballot was accepted while a stay of that ballot, a pending `void_ballot` of it, or a halt, was in force at that entry (an amendment ballot and the ballot that removes a custodian aside, which nothing pauses). So no vote is revealed before `REVEAL_GAP` of wall time has passed since the last moment a commitment could be stamped. And every `stay` and every `void_ballot` of a ballot was posted while that ballot's clock was before the first second of its reveal window: no reveal of the ballot existed then, and none is accepted while the act pauses it.
13. **Decision.** A closed ballot has `result = lapsed` exactly when the votes revealed did not reach the quorum of its base (`quorum_base()`), or it is a sanction on a Master Builder (a `reinstate` aside) with fewer than two votes; a lapsed ballot had no effect, and left its petition, or released its exam, as before it opened. Otherwise it has `result = passed` only if `decide(kind, yes, no, quorum_base())` was true at its close **and** its effect was applied. A ballot never has `result = passed` without its effect, nor an effect without `result = passed`, except for the two bookkeeping marks on an exam (`ballot_failed`, `lapsed`) and the removal of a decided petition. A ballot with `result = undone` had its effect and lost it: the facts of its `undo` record are back at their `before` values, except that an undone admission leaves a `voided` record and not the earlier one.
14. **Every ended ballot can be closed.** For an open ballot with `ballot_time(b, now) > reveal_until`, or whose electors have all revealed, at a `now` at which the ledger is not halted, the ballot is not stayed and no `void_ballot` of it is pending, a `ballot_close` by an eligible signer is never refused. A halt lasts at most 14 days and the next begins at least 90 days after it began; a ballot is stayed at most once, for at most 14 days; a `void_ballot` is pending for at most 21 days and one second, and a ballot is its target again only when custodians other than its poster withdrew the earlier one: no single custodian keeps a ballot open forever (section 12, point 56, for several who overrule one another). A ballot of kind `custodian`, a ballot that adds a witness and an advancement to the 3rd degree are never kept open by a stay or a void.
15. **Eternal values.** `S.pins["canon/eternal.toml"]` and `S.declaration_sha256` equal their genesis values in every state, and `S.prior_pins` never has the key `canon/eternal.toml`.
16. **Pins change only by ballot.** After genesis, `S.pins` changes only in a `ballot_close` of a passed amendment, by setting one path to that ballot's `new_sha256`, or, for `new_sha256 = ZERO_HASH`, by removing a path that is not in `GENESIS_PINS`; and only when the pin of that path was, at that close, the one the ballot froze at its opening. No genesis pin is ever removed. `S.epoch` is the number of passed amendments of `@protocol`. The history `amendments` absorbed one record per such close, in order. No key of `S.pins` is `ledger`, starts with `ledger/` up to case, or equals another key up to case. The pin of `canon/degrees.toml` is always the digest of a well-formed table that was available to the verifier that accepted it, at the opening of the ballot that pinned it and at its close.
17. **Append-only records.** `S.hashes`, `S.retired` and `S.degree_tables` only grow, and their existing elements never change; the count of every history only grows, by one for each record it absorbs, and its accumulator changes exactly then (section 4.11). `S.corrections` only grows, `S.witness_marks` only gains names, `S.notes` gains a record at its end and loses records only at its front, beyond the newest 200, and no record of `S.custodians` is ever removed, or added after the genesis but by a `custodian_claim_apply`. `S.claims` only grows; a claim's `objected`, `objector` and `applied` are set at most once, never both `objected` and `applied`. `S.acts` never decreases. A member record is never removed; it is replaced only by a new admission of the same login (invariant 19). A record of `S.recoveries` is never removed; it is replaced only by a later request of the same login.
18. **One name, one key, one account, one role.** No two keys of `S.members` and `S.witnesses`, taken together, are the same login up to case. No public key (compared by its point, so under either key type) is held by two of: a member record (any status), a witness, a custodian, a reserved petition, an open ballot that adds a witness, a recovery that is alive, an alive claim (each custodian and claim holding two). No name, up to case, is held by two of the same (recoveries aside) and a live invitation. No `github_id` is held by two of: a member record (any status), a live invitation, a reserved petition. The single exception is a returning login, whose earlier record (departed, expelled or voided) shares the name and may share the account with its new invitation and then with its new petition, and may share the key with that petition. No two live invitations, no two reserved petitions, and no live invitation and reserved petition are the same login up to case.
19. **Membership needs a ballot.** Every record in `S.members` that was not created by the genesis was created by the close of a passed admission ballot; its `github_id` and `sponsors` are the `github_id` of the invitation its petition was filed under and the petition's valid sponsors as frozen when that ballot opened, every sponsor was then an active Master Builder under no ban, and its `key` is the petition's key or, after that, the new key of the member's latest accepted `rekey` or applied recovery. A record has `founder = true` exactly when the genesis named its login as a founder and every admission of the login since then was of the same `github_id`. When a record replaces an earlier one, the earlier one was `departed`, `expelled` or `voided` at that moment, and no exam of the login is left in `S.exams`; the new record keeps `founder`, `past_seats`, `sponsor_ban_until`, `fraud_history` and a suspension still running exactly when the two records have the same `github_id`, and otherwise nothing.
20. **Degrees move one step.** Within one record, `degree` rises only by exactly 1 at the close of a passed advancement ballot (to at most 32), or from 32 to 33 in a `council_draw`; and it falls only by exactly 1, at the `correction_apply` of an `undo_ballot` on the advancement ballot that last raised it, while the record still holds exactly the degree and the date that ballot gave it. A record is created at degree 3 (genesis) or 1 (admission). `since[d]` is set exactly when degree `d` is reached, and removed exactly when the advancement to `d` is undone. A ballot changes only the membership it was opened on.
21. **Departure and an undone admission end the membership.** Once a record has `status = departed` or `status = voided`, no entry changes its degree or seat, and its status changes in two cases only. A `departed` record (every `depart` sets `left`) goes back to the status, the `status_since` and the seat it had before that entry, at the `rekey_recover_apply` of a recovery of that key of the same membership, and `left` becomes null; every such recovery was asked in time for that departure (alive at it; or, at it, the latest recovery of the membership, not applied, whose request, stop by the old key or voiding by the Masters, whichever is latest, came at most 90 days before it; or asked within 30 days after it), or followed a recovery in time for that departure, within 150 days of that recovery's request or of the old key's stop of it, so that one follow-up may follow another; the seat comes back only into a vacancy. A departure no such recovery reverses is never reversed. A `voided` record becomes `expelled` only at the close of a passed `expel_for_fraud` ballot that was opened before 90 days had passed since the undo. Otherwise the login returns only through a new invitation, a new `petition` and a passed admission ballot, which replaces the record at degree 1. A record becomes `voided` only at the `correction_apply` of an `undo_ballot` on the admission ballot that created it, only while it is `active` at the 1st degree, and never while a sanction ballot on it is open.
22. **Expulsion ends by ballot only.** A record with `status = expelled` changes status only at the close of a passed `reinstate` ballot on it, or by being replaced through a passed admission ballot. `status_since` of an expelled record never moves while it stays expelled.
23. **Sanctions fit the standing.** Every passed sanction found its member, at the close, in a standing its measure allows (`SANCTION_ON`): `suspend` an active member, `expel` an active or suspended one, `expel_for_fraud` an active, suspended or voided one, `reinstate` a suspended or expelled one. No passed sanction was opened by its own subject, and each was opened by a Master Builder, and by an Arbiter where three active Arbiters other than the subject existed at its opening.
24. **Sponsor budget.** Immediately after every accepted `invite` or `vouch` by `a`, `sponsorships(a, now) ≤ 4`. No `vouch` is accepted on a petition whose admission ballot is open.
25. **Frozen exams.** After `exam_open`, an exam's `candidate`, `degree`, `beacon_round`, `opened`, `pool`, `k` and `work_ref` never change (until a new `exam_open` replaces the record), `k ≥ 1`, and `beacon_round > 0`. The candidate is never in `pool`. After `exam_draw`, `ranking` never changes and is a permutation of the distinct logins of `pool`; `examiners` is always a subset of `ranking`, and `len(examiners) = k` unless the exam has lapsed. Each examiner reports at most once, and a recused examiner has never reported. No exam is at once passed and failed, and an exam that has passed stops being passed only when its advancement ballot is lost on the votes (`ballot_failed`), cannot be applied (`lapsed`), or was applied and then undone (`lapsed`).
26. **One ballot per passed exam.** An exam is `consumed` by at most one open or closed ballot at a time: a second `ballot_open` consumes it only after the first lapsed for want of a quorum or a `void_ballot` ended it, each with no effect. Every advancement ballot was opened by its candidate or by an examiner of the exam it consumed. A record's `degree` rises by advancement only through a ballot that consumed a passed exam, with at least one examiner and a strict majority of `pass`, for exactly that degree and that membership.
27. **Lots are fixed in advance, and drawn in time.** For every exam, `beacon_round = drand_round(time of its exam_open) + 9600`, and its `exam_draw` has `drand_time(beacon_round) ≤ time`, comes before the exam expires, and comes at most 7 days after `drand_time(beacon_round)` on the effective clock. The same holds for every `council_call` and its `council_draw`, without the expiry. A call that was not drawn in time is replaced by the next `council_call`. Every beacon used is absorbed, once, by the history `beacons`.
28. **The Council.** `len(seats(now)) ≤ 33` at every `now`: a seat is counted for its whole term, whatever the standing of its holder, a draw never seats more members than the vacancies counted at that draw, and a reversed departure takes back its seat only while fewer than 33 are seated. `past_seats` is 0 or 1 for every record: a login is drawn to the Council at most once, also across re-admission. Everyone seated was, at the draw, active, not dormant and of the 32nd degree. `S.council_pool` is empty whenever `S.council_call` is null.
29. **Checkpoints are true.** Every `witness` entry, and so every record the history `checkpoints` absorbed, has `upto_seq` one less than its own `seq`, `head = S.hashes[upto_seq]`, `state_sha256` equal to the state digest (section 4.11) of the state after entry `upto_seq` (in a replay with `trusted = 0`), and, when `root` is not null, `root = merkle_root(S.hashes[0..upto_seq])`. Its `witness` was a key of `S.witnesses` when the entry was applied. Between two checkpoints of one witness lies at least one entry that is not a checkpoint, and at least one hour.
30. **Bounded repetition.** Two accepted `work` entries of one membership are at least 24 hours apart. A member's `activity` is strictly increasing and holds at most one time per UTC calendar day, none more than 1,800 days older than its last, and every time in it is the time of an entry that member signed (or of the genesis or admission that created the record).
31. **Founders hold no power by title, save the fallback.** The `founder` flag is read by four rules: the examiner pool of section 7.3, where it restricts who may examine a founder; the Sunset and the founder's fallback, which count the Masters who are not founders (sections 7.9 and 6.31); and the claim of the Custodian office (CL1), the one act only a founder signs, and only while no custodian key is live, before the Sunset, with fewer than three active Master Builders who are not founders and never by a founder against whose custodian key a removal ballot passed (CL6), which one Master Builder who is not a founder voids (CO3). `light` and `fraud_history` are read by no rule. `github_id` is read by the account rule alone (G13, I8, A4) and gives no power.
32. **No stranger writes without a second party.** No entry is signed by a key that the ledger did not already know, except a petition under a live invitation and the request for the recovery of a key. Precisely: the signer key of every accepted entry is the key of a member record or of a witness, or the custodian key or the revoke key of a custodian, or the new key of a recovery that an earlier entry recorded (`rekey_recover_apply`), in the state before it, with three exceptions: the genesis, a `petition` and a `rekey_recover`. Every accepted `petition` of a login was preceded by an accepted `invite` of exactly that login, signed by an active Master Builder under no ban, at most 30 days earlier, with no other petition of that login between the two. Every accepted `rekey_recover` names a recoverable member record (section 5.2), new and proved key, and changes no key. Every key in `S.known_keys` signed, in the entry that registered it, either that entry or a proof of possession inside it.
33. **Every petition has its inviter.** `vouches[0]` of every record of `S.petitions` is the `by` of the invitation the petition was filed under, unless that inviter's own admission was undone since (section 6.19.8, which strikes a voided member from every petition), and the record's `github_id` is that invitation's. `S.invitations` never holds two keys that are the same login up to case, and never holds a live invitation of a login that has a reserved petition.
34. **A key changes by its holder's hand, or by a recovery.** The `key` of a member record changes only (a) in a `rekey` entry of that member, signed by the key being replaced and proved by the key that replaces it, or (b) in a `rekey_recover_apply`, signed by the new key that an accepted `rekey_recover` named and proved, at or after the end of its notice (21 days from the request after a freeze; 30 days from the completion of its co-signatures without one; 45 days whenever the co-signers it needs were lowered; 45 days from the drop moment, 30 days after the request, for a request that was dropped (section 6.26: the co-signatures given by then, counted as at least one where another Master Builder exists, were fewer than it needed): after a freeze always, and for an open recovery when those given then suffice, else from the later co-signature that made them suffice) and at most 60 days after the start of that notice; with, at that entry, at least `cosigners_needed` co-signers who are active Master Builders and are not the member (two after a freeze and three without one or for a final recovery, or as many other active Master Builders as exist; after the drop, those given by then, and at least one where another Master Builder exists), who for an open recovery that did not drop are not all the member's sponsors while another Master Builder exists; with no `rekey_object` by the key the ledger held in between (which a final recovery does not take); with the freeze it followed, if any, neither withdrawn nor voided before it; and, for an open recovery, without the oppositions that void it. No correction and no custodian entry changes a key. A witness's key never changes while the witness is in `S.witnesses`. Two accepted changes of the key of one record are at least 30 days apart when the later one is a `rekey`.
35. **Keys do not return.** `S.known_keys` only grows, and holds the point of every key held by anyone in the state: of every member record, witness, petition, open ballot that adds a witness and recovery. The new key of every accepted `rekey` and of every accepted `rekey_recover` was not in it before that entry: neither ever registers a key that any earlier entry registered, under either key type. In particular a key replaced by a `rekey` or by a recovery is never the key of that record again.

36. **Custodians come from the genesis, or from a founder's claim.** Every record of `S.custodians` was created by entry 0, with two keys that proved possession there, or by a `custodian_claim_apply` of a founder, at least 30 days and at most 60 days after a `custodian_claim` of that founder in which its two new keys proved possession, nobody objected, and at whose application no custodian key was live, the Sunset was not reached, fewer than three active Master Builders who were not founders existed and no removal ballot had passed against a custodian key of that founder. Afterwards only `alive` (by a `custodian_alive` the custodian key signs, at most once in 24 hours) and `revoked` with `removed` (once, while the key is live: by a `custodian_revoke` the revoke key signs, or by the close of a passed ballot of kind `custodian`) ever change. No other entry adds a record to `S.custodians`, and none changes a custodian's name, key, revoke key or linked member: no ballot, no lot and no correction appoints a custodian. A custodian's name and its two keys are held by nobody else, forever (invariant 18). On a ledger whose genesis named no custodian, `S.custodians` and `S.corrections` are empty in every state until a founder's claim is applied.
37. **A removed, revoked or lapsed custodian key never signs again.** If a custodian's key is not live at some time (section 4.8), whether by silence, by its revoke key, by a ballot of the Master Builders, by the Sunset or by the end of its term, it is not live at any later time, and no entry with a time at or after `custodian_end` has that key, or the custodian's revoke key, as its signer key. `S.sunset`, once set, never changes, and no custodian signs an entry after the one that set it, nor any entry dated more than 2,555 days after the genesis or the `custodian_claim_apply` that named it. Once no custodian key is live, no entry of the six custodian types is accepted until a founder's claim is applied (section 6.33), and none ever after the Sunset.
38. **Corrections never grant.** Let `e` be an accepted entry of one of the seven types `correction`, `correction_cosign`, `correction_apply`, `correction_withdraw`, `correction_object`, `custodian_alive` and `custodian_revoke`, and `S`, `S'` the states before and after it. Then, without exception:
    1. `S'.members` has exactly the logins of `S.members`: nobody is admitted and no record is removed.
    2. For every member, `degree' ≤ degree`; the set of degrees dated in `since'` is a subset of that of `since`; `key`, `sponsors`, `seat_until`, `founder`, `github_id`, `sponsor_ban_until` and `fraud_history` are unchanged; and `status' = status`, or `status = active` and `status' = voided`. No status is restored, no suspension or ban is lifted or laid, nobody is seated.
    3. Every pair `(name, key)` of `S'.witnesses` is one of `S.witnesses`: no witness is added and no witness key changes.
    4. `S'.pins`, `S'.prior_pins`, `S'.declaration_sha256`, `S'.degree_tables`, `S'.council_call` and `S'.council_pool` equal those of `S`, and so do the histories `amendments`, `beacons` and `checkpoints`.
    5. `S'.petitions` has no login that `S.petitions` lacks, and each petition's `vouches'` is a subset of its `vouches`, with its key, time and account unchanged; every record of `S'.invitations` is one of `S.invitations`. No petition, sponsor or invitation is created.
    6. `S'.ballots` has exactly the ids of `S.ballots`, less those the entry retired (C14r), which every accepted entry may do. For every ballot: `commits`, `reveals`, `electors`, `kind`, `subject`, `frozen` and the two deadlines are unchanged; and `(result, result')` is one of `(x, x)`, `(null, voided)`, `(passed, undone)`. No ballot is opened or closed, no vote is added, removed or altered, no elector is added or removed, and no result becomes `passed`.
    7. `S'.exams` has exactly the keys of `S.exams`; no exam that was not `passed()` in `S` is `passed()` in `S'`; no report is added, removed or changed.
    8. No custodian key that was not live becomes live, and no record of `S.custodians` is added.

    The only other effects are in `S.corrections`, in `S.notes` (and the history `notes`) and in `alive` and `revoked` of `S.custodians`; `S.sunset`, which any accepted entry may set (C14s), and the counts of the day and `S.acts`, which every accepted entry moves (C14a); the activity credited to a Master who objects; and three removals that follow from the rules above: the seats of examiners that pass on from a frozen member or from a member whose admission is undone (exactly as their own `exam_recuse` would move them), the `consumed` mark of an exam whose advancement ballot is voided, and the `lapsed` mark of an exam whose advancement is undone. So no correction admits, advances, appoints, reinstates or sanctions anyone, adds a witness, or changes a vote. What a correction takes away it takes from one ballot's facts: an open ballot's effect (never yet had), or a passed admission or advancement closed at most 90 days before the correction was posted. It pauses ballots (a stay, a halt, a pending void) and never decides one: the electorate of every ballot, the votes cast in it and the count of them are the same with and without any correction, and a member whose admission is undone still reveals the vote they sealed.
39. **A frozen member can always depart, and so can anyone during a halt.** At every time, a member whose status is not in `GONE` can have a `depart` accepted, a `rekey` under the rules of section 6.18, and a `rekey_object` against a recovery of their key that is alive and not final, whatever corrections are in force and however many entries the actor has that day. A member whose key is frozen can also have a `ballot_commit` and a `ballot_reveal` accepted in every ballot in which an unfrozen elector could.
40. **No deadline is rewritten.** The `until` of a correction, the `commit_until`, `reveal_until` and `opened` of a ballot, the `opened` of an exam and the `time` of an invitation or a petition never change. Pauses are intervals subtracted when a duration is counted (section 7.8).
41. **Earlier answers stand.** For `j < n` and `T` the time of `e[j + 1]`: `in_force(c, t)`, `pending(c, t)` and `custodian_status(c, t)` for every `t < T`, and `effective(a, t, ballot)` for every `a ≤ t ≤ T`, are the same on `S_j` and on `S_n`, for the records `S_j` holds. No lapse or end of an act depends on an entry being applied (section 7.8).
42. **One at a time.** At most one `freeze_key` is in force on a login, and two freezes of one login begin at least 90 days apart unless custodians other than its poster withdrew the earlier one. Two holds of one login begin at least 90 days apart unless custodians other than its poster withdrew the earlier one. A ballot has at most one `stay` record; at most one `void_ballot` is pending on it at a time, and at most one `void_ballot` record and one `undo_ballot` record of it were not overruled. No ballot of kind `amendment` or `custodian`, no ballot that adds a witness and no advancement to the 3rd degree has any of the three. Two halts begin at least 90 days apart, so their intervals never overlap. No act is in force for more than its days: 30 for a freeze, 14 for a stay, a halt and a hold. No act is posted within 90 days of the moment objections voided the same act on the same target.
43. **Bounded corrections.** Immediately after an accepted correction that is not a note, at most 5 corrections have a time less than 30 days before it, and at most `⌈5 / n⌉` of them are by the custodian who signed it, `n` being the custodian keys live at that entry; immediately after an accepted `freeze_key`, and after the entry that starts the notice of an open recovery, at most `max(1, n div 10)` logins have their key frozen (by a freeze in force or a recovery under way), `n` being the active members at that time; no custodian has more than 10 notes with times on one UTC calendar day; `S.notes` holds at most 200 records.
44. **Recusal.** No `stay`, `void_ballot` or `undo_ballot` is on a ballot that adds a witness or advances a member to the 3rd degree. No `hold_room` has as its target the member its own custodian is linked to (a `freeze_key` may). No `stay`, `void_ballot` or `undo_ballot` is on a ballot that the member its custodian is linked to opened, is the subject of, or (for an admission) sponsored; the same held, at their entries, for every custodian who co-signed a noticed act and, at its application, for every signer whose key was live and for the custodian who applied it.
45. **Objections.** In every correction, `objections` holds each login at most once, never the member its custodian is linked to, never the member of a custodian who had co-signed it by then, and never its `subject`; every objector was a Master Builder and an active member whose key was not frozen when they objected, and objected within 90 days of the correction or, for a noticed act that was applied, of its application. `void` is set by exactly one `correction_object` entry, the one at which the count reached `max(1, ⌈E / 5⌉)`, never on a noticed act that was already applied, and never changes. A note is no record of `S.corrections`: it has no objection, no `void` and no `withdrawn`. `withdrawn` is set at most once, by a `correction_withdraw` of the custodian who posted the correction, or by one that brought the custodians with a live key in `withdrawals` to `S.custodian_threshold`.
46. **Grounds and reasons.** Every correction and every note has one ground of `GROUNDS` and a `reason_sha256` of 64 hexadecimal characters; a `freeze_key` has the ground `key_compromised`, a `halt` the ground `attack_in_progress`, and the ground `moderation` is that of every note and of nothing else. That the reason's text is in the tree is a gate (section 8.5), not an invariant of replay.
47. **An applied correction is never applied twice.** Every noticed act has `applied` null or set by exactly one `correction_apply` entry, and no `correction_apply` naming it is accepted afterwards. A ballot's `corrected` is set at most once, so a ballot is voided or undone at most once in its life, and a ballot that was voided is never undone nor the reverse. An immediate act is never "applied": no `correction_apply` or `correction_cosign` names one.
48. **Notice.** Every accepted `correction_apply` has a time `t` with `T + 14 d ≤ t ≤ T + 21 d`, `T` being the time of the correction it applies, in wall time; at that entry the correction was not void and not withdrawn, the key of the custodian who posted it was live, at least `S.custodian_threshold` of its signers had a live key, and every precondition of its act held. Between the correction and its application nothing but the record of the correction was changed by it.
49. **An undo is a compare-and-swap.** Every ballot with `result = undone` had, at the entry that undid it, every fact of its `undo` record equal to the recorded `after` value; the entry changed all of those facts or (when refused) none; and the ballot had closed as `passed` at most 90 days before the correction was posted; it was an admission, or an advancement to a degree other than the 3rd; and, for an admission, no sanction ballot on its member was open at the entry that undid it. Every ballot with `result = voided` was open at the entry that voided it and was never closed, and no vote of it was revealed after the `void_ballot` was posted.
50. **Removal by ballot.** A custodian record has `removed` set only by the close of a ballot of kind `custodian` whose subject names it, that passed by more yes than no votes with the quorum of its electorate, and at whose close the key was live; the member the custodian is linked to was not in that electorate and did not open it. No ballot of that kind was ever stayed, voided or undone, and its three windows were counted in wall time.
51. **Recoveries.** At most one recovery of a login is alive at a time, and two requests of one login are at least 90 days apart. Every record of `S.recoveries` was created by a `rekey_recover` accepted while a `freeze_key` of that login was in force (`freeze` is its `seq`) or while none was (`freeze` is null). `objected` is set at most once, by a `rekey_object` signed by the key the ledger then held for the member, never on a final recovery, and a recovery with `objected` set is never applied; `void` is set at most once, by the `rekey_oppose` that brought its oppositions to `max(1, ⌈E / 5⌉)`, only on an open recovery, and a recovery with `void` set is never applied; `notice` is set at most once, only on an open recovery; `applied` is set at most once (invariant 34). No co-signer of a recovery is the member it recovers or one of its opposers.
52. **One digest.** The state digest (section 4.11) of `Sᵢ` is a function of `e[0..i]` and of the degree tables alone. It is the same whether the entries were replayed in one pass or applied to the state of a prefix, read from files or built in memory, on every runtime and whatever the order in which a map or a set was filled; asking the state about any time changes nothing in it; an entry that is refused leaves it as it was; and an entry that is accepted changes it (`head` moves). Two states with equal stored facts have equal digests, and a change of any single stored fact, `hashes` and the two indexes of the history aside (`retired`, `degree_tables`), changes the digest. The digest a verifier keeps from one entry to the next, hashing again only the records that changed, is the digest computed from nothing.

53. **Bounded writing.** For every actor and every UTC calendar day, at most 20 accepted entries of that actor dated that day are not exempt (C12a). At every time, at most 3 open ballots of the kinds other than `amendment` and `custodian` have the same `opened_by`, and at most 3 open amendment ballots. No ballot of a kind of `REOPEN_KINDS` was opened within 90 days of the close of a ballot of the same kind, subject key and opener that `failed` or `lapsed`, unless it re-ran that ballot. `S.day_entries` holds counts of the day `S.day` only.
54. **Who opened what.** Every ballot of kind `amendment`, `witness` or `custodian` was opened by a member of the 3rd degree or higher; every admission ballot by a sponsor frozen in it; every advancement ballot by its candidate or an examiner of its exam; no sanction ballot by its subject. Every ballot of a kind other than `amendment` has `commit_until = opened + 7 d` and `reveal_until = commit_until + REVEAL_GAP + 3 d`.
55. **Nobody is given a key they did not show.** Every witness in `S.witnesses`, every founder after the first and every custodian was registered with a key that signed, in the entry that registered it, a message naming the role, the name and the key; the first founder's key signed the genesis.

56. **The game never waits on one omission**. A sanction on a Master Builder (a `reinstate` aside) was opened with at least two electors and, if it was decided, by at least two votes. Every ballot that re-ran a lapsed one did so once, within 30 days of its close, with the same kind and subject and at least 7 days to commit, the lapsed ballot had given at least 7 days to commit too, and no ballot re-ran a re-run. An exam that timed out had no effect on its candidate's next exam but to leave out its silent examiners, unless nobody else could be drawn. In the Founding Phase, an admission ballot opened with one sponsor while two or more Masters were active had a petition at least 30 days old on the effective clock.
57. **Every elector keeps the vote**. Every electorate holds every eligible member of its rung, dormant or not, and `base ≤ len(electors)`; `base ≥ 1` whenever `electors` is not empty.
58. **The successors hold four powers and no more**. Every entry that a member below the 3rd degree signed and that only a Master Builder may sign (`invite`, `vouch`, and the sponsors and examiners and electors that count them) was signed or counted while a succession was in force, no Master Builder was present and the member was of the highest degree present; no member below the 3rd degree ever opened or voted in an amendment, witness, sanction or custodian ballot, objected, co-signed or opposed a recovery. A succession claim was signed while no active Master Builder who is neither dormant nor silent existed (`present_masters` empty), and was canceled by the first entry, within its 90 days, of a Master Builder who after it was active and neither dormant nor silent, if any; an entry of a silent Master that is no revealed vote and no report cancels nothing.
59. **Retirement is invisible to the rules.** Replaying a ledger with C14r left out accepts exactly the entries a replay with it accepts; the two states differ only by the ballots kept, `S.retired` and the history `ballots`, and a refusal differs at most in its message (UB0 and B2r name the retirement where UB1 and B2a would name the missing record). A ballot that leaves the state ended more than 111 days before the entry that retires it, so before every entry that could read it: the undo of section 6.19.8 (posted within 90 days of the close and applied within 21 days of its posting), the re-run (B2a to B2e, within 30 days of the close) and the opener's wait (B7a, 90 days); every other rule reads open ballots only.
60. **Silence is recorded, and removes no vote.** `missed` and `heard` change only by the effects of section 7.7 (a ballot's close, the report that decides an exam, a lapse for want of a replacement, an `exam_open` after a timeout, a vote, a report), and only in records of degree 3 or higher, or of any degree while a succession is in force. `missed` never holds more than 2 times, and two of them are at least 7 days apart. Only a ballot that gave at least 7 days to commit records a call, and only a revealed vote answers a ballot. Every electorate holds its silent members, and every revealed vote of one is counted; `silent(now)` is read only by `present_masters`, the cancel of C14b, `successors`, the rungs LR2 and LR3 and the present lists of an admission and of an advancement.

The following plausible statements are **not** invariants; see section 12: "every elector of an open ballot is still a member in good standing" (point 5), "an expelled member regains standing only by re-admission" (false by design: `reinstate`), "a custodian cannot touch another custodian's member" (point 25), "an immediate act needs as many custodian keys as `custodian_threshold`" (point 24), "an objection reverses a noticed act that was applied" (false by design: section 6.21), "a recovery cannot be asked for by a stranger" (true only with the gate of section 9.3: point 35), "a recovery always has a co-signer" (false for the only Master Builder: point 62), "a departure is final" (false within the reach of a recovery: invariant 21), "after an undone advancement the member keeps the examination" (false by design: section 6.19.8).

---

## 11. Known differences from the Whitepaper

References are to sections of [WHITEPAPER.md](WHITEPAPER.md). In every case the code is what the ledger enforces.

### 11.1 Disagreements

None is known. The Whitepaper, the Constitution and the Custodian's charter (`docs/governance/CUSTODIAN.md`) state the rules of this document, in prose and often in summary (section 11.2). Should a disagreement be found, this document and the code are the statement of what the ledger accepts, the disagreement is listed here, and under the Constitution's own opening rule the text is corrected by amendment.

### 11.2 Rules the Whitepaper states only in summary

The Whitepaper explains intent and gives the rules in prose; where a reader needs the exact rule, this document is the statement. In particular the Whitepaper does not spell out:

1. the order of the checks and the refusal messages (sections 5 and 6);
2. the one form of a degree table and its size (section 8.4), beyond the content rules and the statement that a malformed table cannot be ratified;
3. that a ballot is bound to the membership it was opened on (sections 4.2 and 6.4), beyond saying that a ballot never changes a member who left;
4. `fraud_history` and `last_work`, two fields of a member record (section 4.2).

---

## 12. Open points for implementers

Each point is a place where the current behavior deserves a second look before the protocol is frozen: it is a deliberate choice that could have gone another way, a dependency outside this document, or a gap this revision did not close. None of them makes two conforming implementations disagree; a second implementation must reproduce the behavior described.

### 12.1 Encoding and determinism

1. **Strings are ASCII.** `ledger.strict_value`. No field of the protocol needs more today (logins, hashes, URLs, paths, a fraternity name). A future field of human text would have to choose between this alphabet and a wider one, and a wider one brings back the questions this rule removes: key order above U+FFFF, normalization, escapes.
2. **A file is not canonical.** `ledger.load`. Whitespace is free, `-0` is zero, and members may be in any order, so files with different bytes can be the same entry; identity is the entry hash. The size limit is measured on the file by the loader and on the canonical encoding by `ledger.apply`, so a file padded with whitespace beyond the limit is refused by the loader although `apply` would accept its value.
3. **The digest commits to sections, and costs what changed.** `State.digest`, `ledger.state_digest`, `ledger._retire`. The state document (section 4.11) holds a Merkle root per section and a hash chain per history, so a checkpoint hashes again only the records that changed since the last one and the roots of their sections. Two costs still grow with the fraternity rather than with history: each digest walks every live record once to see whether it changed (a comparison of a version, not a hash), and a section in which one record changed has its root computed over all its leaves (two hashes per record). The live state is bounded by what the rules read: the ballots that ended in the last 111 days, the newest 200 notes, one record per member, exam, custodian, correction, recovery and claim. Three sets still grow with history and stay because rules read them: `S.corrections` (bounded by the rate of corrections), `S.known_keys` (one point per key ever registered) and the lapsed invitations and petitions, which a new one of the same login replaces. `S.retired` grows by one short id per ballot, and is in memory only. An authenticated tree with O(log n) updates per changed record would remove the second cost; it was left out because RFC 6962 over sorted keys is simpler to implement from this text and the measured cost is small (`tests/bench_replay.py`).
4. **The degree table has its own grammar; two other files do not.** `canon._parse_tables`. Section 8.4 defines every byte string that is a degree table, so the verdict on a table does not rest on a TOML library. `network.toml`, a file of the pinned core read when the code is loaded, and `canon/eternal.toml`, whose Declaration the tree gate and the tools digest, are read with the TOML parser of the runtime. Replay reads neither: the Declaration reaches it as a digest in the genesis, and the canonical repository and the founder's account are read by the gates only.

### 12.2 Rules

5. **Frozen electorates keep absent electors.** `ledger._ballot_open`, `ledger.decide`. Members who leave, are suspended, are expelled or go dormant after a ballot opens stay in its base, which raises the quorum they can no longer help to meet; the ballot then lapses and its re-run does not wait for them (B9). A login admitted again while a ballot is open votes with its old place in that electorate. Members who are dormant when it opens are electors and are not in the base.
6. **An examiner who leaves stalls the exam, for 60 days.** `ledger._exam_draw`, `ledger._exam_recuse`. The pool is not checked again at the draw, and an examiner who has departed, been suspended or been expelled can neither report nor recuse. If that leaves no majority, the exam times out after 60 days with no penalty: the candidate opens another at once, without the silent examiners. The 60 days are the cost; a shorter report window would bind diligent examiners too.
7. **Fallback sets can be smaller.** `ledger.electorate`: for an advancement to degree 2, the fallback rung (Master Builders) is a subset of the primary one (2° and above); falling back changes who is present, and so the quorum base, but removes no voter, because the voters of the first rung keep the vote (section 7.1). `ledger.examiner_pool` returns the last non-empty rung, not the largest, when none can seat `k`; the last rung is a superset of the others but for the successors' rung, which is non-empty only when no Master is present.
8. **A ballot nobody closes stays open.** `ledger._ballot_close`. Closing is an entry someone must sign, when the reveal window has ended or every elector has revealed. Until then the ballot blocks another ballot on the same subject, keeps a petition reserved, keeps a consumed exam consumed, and counts among the three open ballots of its opener. Witnesses close ended ballots automatically; without a witness a member must.
9. **A suspension follows the account, not the person.** `ledger._depart`, `ledger._close_admission`. A suspended member may depart (Landmark VII) and be invited again 90 days later; the new record of the same GitHub account is suspended until the day the old suspension ends. A person who returns under the same login with another GitHub account (point 19) carries nothing over: no suspension, no ban, no record of fraud. The protocol leaves that judgment to the inviter and to the admission ballot.
10. **Reinstatement and a pending invitation or petition.** `ledger._close_sanction`. An expelled member who has been invited again and is then reinstated keeps the invitation until it lapses, though the petition it would allow is refused (P1). One who has already petitioned keeps the petition until it lapses or its ballot fails; meanwhile the petition holds its key, and either record counts in its sponsors' budgets.
11. **What can be pinned.** `ledger._open_amendment`. Any path outside `ledger/` and `canon/eternal.toml` can be pinned, including `canon/history/…` and paths that do not exist; an amendment may re-pin a path to its current value, and may remove a pin an amendment added (M7a). An opener has at most three ballots open at a time of the kinds other than amendment and custodian, and three amendment ballots besides (B7b).
12. **Number of genesis witnesses.** `ledger._genesis`. Only the 32 KiB limit of entry 0 bounds it.

### 12.3 Governed files and gates

13. **What stands outside the pinned core.** `src/openmasonry/protocol.manifest`. Code outside the manifest changes by code-owner review alone. The three workflows are inside it and no other may exist unless a ratified manifest lists it, so a second job named `judge` needs an amendment; what still rests outside the protocol is the repository's ruleset (which check is required, and from which source; `docs/operations/LAUNCH.md`), the actions the workflows call (pinned by commit inside the pinned files, but hosted elsewhere) and the runner's Python itself: the judge runs the runner's `python3`, whatever version the image carries, and only prints that version. The witness node is outside it too; it imports only pinned modules and refuses to sign when the digest of its own copy of the core differs from the pin, but its own file is not covered by that digest. The digest is over working-tree bytes, so line-ending conversion changes it.
14. **The prior-pin window uses ledger time.** `govern.check_tree`. The 30 days are measured against the time of the last entry, so on a quiet ledger the old text stays lawful indefinitely, and on a busy one it expires on schedule. A newly governed path that does not exist yet is a violation at once.
15. **Beacons are compared, not verified.** `beacon.audit`, `beacon.fetch`. The gate trusts the `randomness` field served by a relay over HTTPS and does not verify the drand signature of the round. If every relay fails, `fetch` raises an error that `verify.verify_report` does not catch: the command ends with a traceback and a non-zero status (through `om verify`, with one line and status 1). Offline, any 64 hexadecimal characters are a lawful beacon.
16. **Identity is a moment in time.** `identity.pr_problems`. The key list is the one GitHub serves, when the judge runs, for the login the account has that day; nothing records what was served, beyond the `github_id` the entry itself states. A member who renames the account keeps the membership under the login of the record, which then names another account or none: the gate follows the numeric id, and the tools must find the login of the day. The petitioner's account id comes from the pull request event when the judge runs (`--pr-author-id`), and from a lookup of the author's login otherwise. The function replays with a verifier that accepts every signature, so it must only run after a full replay.
17. **Degree tables come from the verifier's tree, and from the pull request's archive.** `canon.degrees_for`, `canon.archives`. They are identified by digest, so no verifier can read a different table, but a clone that lacks `canon/history/{digest}.toml` cannot replay past the entry that needs it, and the judge reads them from the base branch (section 9.6).
18. **Changing how the digest is computed.** `govern.protocol_digest`, `govern.parse_manifest`. The list of the core changes through the judge (section 8.3), because the old code and the new code compute the same digest for the same tree. That stops being true for a change of the computation itself: another framing or hash, another path or form of the manifest, another set of required paths, or a judge workflow that reads the list from somewhere else. The old code then gives the new tree one digest and the new code another, and a pin has one value at a time, so no single amendment satisfies the judge before the merge and the audit after it; the prior-pin window (section 8.5) covers one earlier value of the pin, not the gap. Such a change still needs the ruleset's bypass, or a version of the code that accepts both computations for a while. Workflows in a subdirectory of `.github/workflows/` cannot be listed at all: the tree gate looks at the names directly in the directory.
19. **What "one account" does not ask.** `ledger._invite`, `State.id_holders`. An account is held by a member record of any status, for good: a member who departs and whose GitHub account is later renamed cannot return under the new login, and nobody else can be invited with that id, unless the login of the old record is used. A returning login is not required to carry the id of its earlier record: `alice` may be invited again with another `github_id` (the account that holds the login today), and the new admission then records that id, frees the old one and inherits nothing of the earlier record. Witnesses name no account. Replay compares the numbers the entries state; that a login is the account with that id is the gate of section 9.3, at the moment of the merge.
20. **An invitation outlives its inviter's standing.** `ledger._petition_checks`. P0 looks only at the invitation's age. An inviter who departs, is suspended, is expelled or comes under a ban after inviting leaves a live invitation behind; the petition is accepted, and the inviter simply does not count as a sponsor when the ballot opens (A2).
21. **A rekey needs the old key.** `ledger._rekey`. Rotation is self-service: the member signs with the key being replaced. A member whose key is lost cannot rekey and goes through a recovery (sections 6.26 to 6.30); a thief who holds the key and controls the member's GitHub account can rekey (the gate of section 9.3 asks that the new key be listed for the login and that the pull request come from the account the ledger records for the member; a thief with the key alone cannot pass it). The protocol defines no revocation of a key by ballot; a custodian can freeze a key for 30 days (section 6.19.1), which stops the thief's entries (a `depart`, a `rekey_object`, a sealed vote and its reveal, and the entries of an amendment ballot or of the ballot that removes a custodian aside), but not a `rekey` by whoever holds the key, also while a recovery of that key is under way. The limit of one rekey in 30 days also binds the rightful holder who wants to undo a thief's rekey, and it is counted per record, so it starts anew after a re-admission.
22. **Only a rekey looks at the history of keys.** `State.known_keys`. A `petition` and a witness ballot ask whether a key is held today (P7, W6), not whether it was ever registered: a key that a member replaced, or the key of a lapsed petition, may be registered again by a petition or proposed for a witness, though never by a `rekey`. `known_keys` includes keys that were only proposed (a refused petition, a failed witness ballot).
23. **What a hardware-backed key proves.** `crypto.signature_valid`. The rules of section 13 check the signature a token makes and that it reports user presence. Nothing in an entry proves that the key lives in a token at all: a software key can be dressed as `sk-ssh-ed25519@openssh.com` and can set the flag itself, and no attestation is recorded or checked. Any flags byte with the user-presence bit is accepted, user verification or not, and the counter is signed but not compared with earlier ones (it need not increase). The application is pinned to `ssh:`, so a key made with another application string must be made again.

### 12.4 Custodians and corrections

24. **One custodian key is enough for an immediate act.** `ledger._correction`. `custodian_threshold` is read for the two noticed acts (CS5, AP5) and for a withdrawal by custodians other than the poster (section 6.20): a freeze, a stay, a halt and a hold are each the act of a single custodian key, also when the genesis names three custodians and a threshold of two. A noticed act is **posted** by one key too, and from that moment a `void_ballot` pauses its ballot (K1b, R1b, X1b), before any second custodian has signed. With a threshold of 1, which is what a genesis with one custodian has, a noticed act is the act of one key from its posting to its application.
25. **Recusal is about one's own member, and about what ends the office.** `ledger._recused`, `ledger.party_to`, `ledger.sunset_ballot`. A custodian cannot hold the member it is linked to out of the rooms, nor stay, void or undo a ballot that member is party to. Nothing stops it from doing so to the member another custodian is linked to. A custodian **may** freeze the key of its own member: with a single custodian that is the only way that member's key, if stolen, is ever frozen. Recusal looks at the opener, the subject and the sponsors of a ballot; it does not look at who voted, so a custodian may void or undo a ballot in which its own member was an elector. No custodian touches a ballot that adds a witness or advances a member to the 3rd degree; nothing recuses a custodian from freezing the key of a candidate for the 3rd degree, of an elector of such a ballot or of a witness, which objections and the cap of FK4 are left to check.
26. **Three acts rest between repetitions; the others rest only after objections.** `ledger._act_freeze_witness`, `ledger._act_hold_room`, `ledger._correction` (N7). A key is frozen again only 90 days after the last freeze began, a member is put under a room hold again only 90 days after the last hold began (HR4), and a halt follows a halt after 90 days; so, holds that other custodians withdrew aside, a member is kept out of the rooms by holds for at most 14 days in any 90, and only a sanction ballot keeps them out longer. A witness can be frozen again as soon as the previous freeze has ended, unless objections voided it, which leaves 90 days; otherwise only the five corrections in 30 days, and each custodian's share of them, bound the repetition.
27. **A frozen key still votes.** `ledger.FREEZE_ALLOWED`, `ledger.electors_for`. A freeze is not a status: the member stays in `active(now)`, in every electorate (also of ballots opened during the freeze) and in the pool of examiners frozen at an `exam_open`, and commits and reveals in every ballot. If the key is in a thief's hands, the thief casts that one vote in each ballot until a recovery is applied; the freeze stops everything else but a `depart`, a `rekey`, a `rekey_object` and the entries of an amendment ballot or of the ballot that removes a custodian (section 5.2, rule 11). A seat of examiner the member cannot fill passes on at the draw.
28. **What a halt lets through is a list and two kinds of ballot.** `ledger.HALT_ALLOWED`, `ledger._unstoppable`. A witness's checkpoint is accepted during a halt; its other three types are not, so nothing is closed and no lot is drawn, except the close of an amendment or of a ballot that removes a custodian. A halt therefore also delays the `exam_draw` of an exam whose beacon round has passed; the exam's clock, and the 7 days of its draw, are paused with it (section 7.8). Every entry of a recovery is accepted. A halt therefore cannot hold back the amendment that repairs the flaw it was posted for, nor a member's new key.
29. **The Sunset looks at entries and at a flag.** `ledger.sunset_reached`. The condition is evaluated when an entry is applied, not between entries, so a custodian's own entry can be the one at which it is first seen. "Not a founder" is the `founder` flag of the member record, which follows the login through a new admission under the same GitHub account; it does not follow the person to another login or another GitHub account. At the Sunset every noticed act still pending is `ended`, and no correction exists from then on: the only custodians are those of the genesis and of a founder's claim, and no claim is made after the Sunset (CL3). The term of 2,555 days is counted from the genesis, or from the application of the claim that named the key, and ends the keys whether or not anything has taken their place.
30. **A room hold is only an interval.** `ledger.room_held`. The protocol does not tie a hold to an open sanction ballot; it is in force for its 14 days unless it is ended. Whether a hold without a pending case should lapse is left to the rule of the rooms and to objections.
31. **What a note and a reason may say.** `ledger._act_note`, `govern.missing_reasons`. The target of a note is a short free string and may name an account; the reason is a file of up to 64 KiB whose content no rule reads. Both are public forever in the entries, though the state keeps only the newest 200 notes and a tree is lawful without the reason of a correction older than the pull request being judged. Nothing in the protocol keeps personal data out of them.
32. **Nobody may be left to object.** `ledger._correction_object`. `E` leaves out the custodian's own member, the members of its co-signers and the target. On a ledger with one or two Masters `E` can be 0: the number needed is then 1, and no one is eligible to give it. Until more Masters exist, a correction is checked by publicity and by the right to fork; that includes a `void_ballot` and an `undo_ballot`, which a single custodian key can then post and apply. An objection made after a noticed act was applied is recorded and reverses nothing.
33. **Custodian acts can be backdated like any entry.** The clock gate (section 9.2) lets an entry be stamped up to six hours before it is merged, never before the previous entry. A halt, a stay or a freeze can therefore begin up to six hours before anyone could see it, though it cannot reach back over an entry already in the ledger.
34. **A pending void pauses the ballot.** `State.void_span`, `ledger._not_stayed`. So that a stay and a notice compose, a ballot takes no commitment, no reveal and no close while a `void_ballot` of it is pending, and its clock stands still. One custodian key can thus hold a ballot for up to 21 days beyond a stay (35 days in all), until the act is applied, expires, is withdrawn or meets enough objections; both acts are posted only before the first second of the reveal window, so no vote is known to anyone when the pause begins. The alternative, to let the close race the application, would make the outcome depend on which pull request is merged first.
35. **Replay lets any new key ask for a recovery.** `ledger._rekey_recover`. At any time, replay accepts a `rekey_recover` for a recoverable member signed by any key that is new to the ledger (a recovery never needs a custodian; of a member who departed, RR3a asks only for time: 30 days). That the asker is the member is the gate of section 9.3, at the request and at its application, and after it the co-signers, the notice and the objection of the old key. A request that passed the gate uses the member's one request in 90 days and, after a freeze, holds the member's key frozen for up to 60 days; the member's remedy is `rekey_object`, which needs the old key, and the Masters' remedy is an objection to the freeze, or an opposition where there is none.
36. **A noticed act is posted once per ballot, unless other custodians withdrew it.** `ledger._once` (VB3, UB7). Whatever became of the first (a missing co-signature, a wrong ground, a withdrawal by its own poster, an expiry, objections), no second `void_ballot` and no second `undo_ballot` names the same ballot. It is what makes an objection final and what bounds the pause of point 34; it also makes a custodian's slip final, except where enough other custodians withdraw it (point 56).
37. **What an undone admission leaves behind.** `ledger._undo_ballot`. The member stays in the electorates frozen before the undo and still reveals the votes sealed there; a petition under an open admission ballot keeps the voided member among the sponsors that ballot froze, and the member admitted by it will name them; the record still counts in its sponsors' budgets for a year, like any admitted member (section 7.5). Nobody is banned and no fraud is recorded by the undo: where fraud is the ground, that judgment is a sanction ballot's, opened before 90 days have passed since the undo. A `freeze_key` in force on the login is not ended by the undo, and goes on over a new admission of the login until it ends by itself.
38. **What an undone advancement leaves behind.** `ledger._undo_ballot`. The member loses one degree and the exam for it. Nothing else follows: the member stays in the electorates and examiner seats they entered at the higher degree (as in point 5), keeps an exam already passed for the degree above (usable once the lost degree is earned again), and, if the lost degree was the 3rd, keeps their live invitations while no longer counting as a sponsor (A2, RA5 and `may_sponsor` look at the degree on the day).
39. **A freeze the Masters voided rests for 90 days.** `ledger._act_freeze_key` (FK3), `ledger._correction` (N7). Objections that void a freeze keep the same key from being frozen for 90 days, so that a custodian does not answer each objection with a new freeze; a key that is in fact stolen then stays unfrozen for that time, and the Masters who objected carry that judgment. A freeze that other custodians withdrew leaves no wait.
40. **A frozen Master has no voice against corrections.** `ledger.FREEZE_ALLOWED`. A frozen member cannot object, so each freeze removes one possible objector; the protection is the cap of FK4, which counts keys held by a recovery too. With 20 to 29 active members two keys can be frozen at once. The cap bounds the freezes, the custodians' choice, and never holds back a recovery (RR10, RC6): with recoveries under way more keys than the cap can be frozen, each by a request that only the member's GitHub account can make (section 9.3), co-signed where other Master Builders exist, and ended by the old key's objection (`rekey_object`, once) if the member did not ask for it.
41. **A removal ballot can be decided by very few.** `ledger._open_custodian`, `ledger.decide`. The electorate leaves out the custodian's own member and the rule is a simple majority with the usual quorum. On a ledger with two Masters, one of them linked to the custodian, the other alone opens the ballot and removes the key with one vote in a little over seven days; with one Master, nobody can.
42. **The ground of a noticed act is not checked against the ledger.** `ledger._correction`. `void_ballot` and `undo_ballot` take any of the four grounds; that `key_compromised` is used only where votes were cast by a stolen key, and that no ground is disagreement with an outcome, is for the public reason to show and for the objectors to judge.
43. **The undo window is measured where the act is posted.** `ledger._check_undo` (UB6). A correction posted on the 90th day after a close is applied up to 21 days later, so a ballot can lose its effect up to 111 days after it closed.
44. **A recovery and the old key's other powers.** `ledger._signer`, `ledger._depart`. While a recovery is under way the holder of the old key can still `depart` (Landmark VII) and `rekey`, besides objecting; a `rekey` leaves the recovery under way, and its application then replaces the newer key; a `depart` is reversed by the application, and stands when no recovery is applied. After a recovery the member cannot `rekey` for 30 days (Q4).
45. **The custodian message binds the member.** `ledger.custodian_message`. The proof of a custodian key covers the name, the linked member and the key; the proof of a revoke key covers the name, the custodian key and the revoke key. Neither covers the fraternity or the genesis, so a pair of proofs could be copied into the genesis of another ledger, where it would name a custodian the copier cannot control. The founder message and the witness message are the same in this: each names the role, the name and the key, and no ledger.

### 12.5 The digest, the vectors and the client rule

46. **A checkpoint says which version of the document it states** (Z4a). The body carries `state_version`, and this core accepts 2 and nothing else. A later core that writes another version of the document (a new stored field, another encoding) judges each checkpoint by the version it names, so the checkpoints already in a ledger keep verifying.
47. **What the client's memory is and is not.** `actions.canonical_guard`, `ledger.head_verdict`. It is a file on one machine, written by the tools and readable and writable by anything that runs as the user: it protects against a rewound repository, not against malware on the person's own machine, and deleting it starts again from `first`. It is kept per user and per genesis, not per clone: a clone whose remote is pointed at another fraternity the same user accepted earlier raises nothing. It holds a head and no history, so a canonical ledger shorter than the mark is told from a rewritten one only by what the working copy still holds; a clone that was reset onto the shorter history reports `behind`, signs nothing, and reports `rollback` only when another entry stands at the remembered `seq`. A first verification on a new device trusts what it sees. And `--accept-genesis` accepts a fork of the same genesis as readily as another genesis: the flag is the person's word, and nothing in the protocol asks for it.
48. **A head dated ahead is judged by the reader's clock.** `ledger.future_head`. The tolerance is ten minutes, five times what the judge allows a new entry. A reader whose clock is slow raises the alarm wrongly, and one whose clock is fast misses it. In the audit workflow the check is part of the `--online` step, whose failures open a capture alarm only after three consecutive failed audits (so that a drand outage is not an alarm): a post-dated head on `main` is therefore reported by the audit at once and alarmed on the third run, unless a witness or a member raises it first.
49. **What the vectors do not reach.** `tests/make_vectors.py` (section 14). The vectors replay small ledgers; they hold no Council lot, no `custodian_revoke`, no `correction_cosign` and no `rekey_object`, no final recovery, no objection to a founder's claim, no successor's examination, no hardware-backed key, no ledger longer than a few dozen entries, and nothing of the gates of section 9 (replay only). They pin one degree table by digest, the one of this repository's `canon/history/`; a second implementation needs that file. Their refusal messages are the reference's, which section 1.5 says an implementation SHOULD, not MUST, reproduce.
50. **Light looks back 1,800 days from the member's newest point.** `Member.credit`. The window is counted from the latest credited entry, not from the time Light is asked about, and it changes the value of Light for a member with more than 1,800 days of activity (by less than 0.26 in the worst case, one point every day). No rule reads Light.
51. **A checkpoint covers exactly the entries before it.** `ledger._witness` (Z1). A witness cannot checkpoint an older position, and two witnesses that checkpoint the same head compete for one `seq`: the second is refused and is made again one entry later. A checkpoint costs the records that changed since the digest before it (point 3), so many witnesses add little; a witness signs one at most once an hour, and only over a new entry (Z6, Z7).

### 12.6 Limits, pauses and recoveries without a custodian

52. **A path is never held by a bogus text.** `ledger.subject_key`. The slot of an amendment is the path and the text, so an amendment on a path never keeps another text off it; the first to pass changes the pin and the others fail at their close. Without a waiting period on amendments, a Master who opens bogus amendments over and over costs electors attention and nothing else: three open at a time, each voted down. Its remedy is the vote, or a sanction of the abuse.
53. **A final recovery with few Masters rests on fewer peers, for longer.** `ledger.cosigners_needed`, `ledger.lowered`. The recovery that the old key cannot stop needs three co-signers, or as many other Master Builders who answered within a year as exist (point 76), with a notice of 45 days when that is fewer. (Three flat locked a thief's victim out for good on a ledger of fewer than four Masters.) With one other Master, that Master's word and the 45 days decide it; with none, the identity gate alone (point 62). The drop lowers any request the same way once it has waited 30 days for its co-signatures (section 6.26): with one other Master Builder who answers, a recovery rests on that one co-signer and 45 days of notice.
54. **An opposition is counted where it is made.** `ledger._rekey_oppose`. `E` is every active Master Builder but the member at the entry of the opposition, co-signers included, so a co-signature never changes the number; a change in who is an active Master Builder between two oppositions can. With up to five other Master Builders one opposition voids any open recovery.
55. **A sanction ballot open through the window lets an undo expire.** `ledger._check_undo` (AP6a). The undo of an admission is not applied while a sanction ballot on its member is open, and the application has seven days. A Master Builder who opens such a ballot in that week, on any measure, makes the undo expire, and no second undo names the same ballot (point 36). The members then judge the record themselves, by that ballot or another: the rule lets a ballot of the members prevail over a correction, also when it is opened to that end.
56. **Custodians who overrule one another repeat an act.** `ledger._overruled`, `ledger._once`, `ledger._act_freeze_key`, `ledger._act_hold_room`. A correction withdrawn by custodians other than its poster leaves no wait and frees its target for the same act again. No custodian repeats an act alone that way, but where the genesis names several, they can take turns: one posts a `void_ballot`, a freeze or a hold, the others withdraw it, another posts it again. Each round is public and costs corrections of the five in 30 days, and the ballot stays paused meanwhile. Stays remain one per ballot.
57. **Costs that grow with the state.** `State.key_holders`, `State.entries_root`, `ledger.sunset_reached`. Whether a key is held is answered by a scan of the members, witnesses, custodians, petitions, open ballots and recoveries, with one decode of 32 bytes for each, and not by an index. A checkpoint that carries `root` costs O(log n) hashes over a frontier of the entry hashes (section 2.4), and the state digest the records that changed (point 3). The Sunset condition is evaluated at every entry until it is met, once four witnesses exist: a scan of the members that stops at the seventh active Master Builder who is not a founder, with dormancy read from the newest point of activity alone. The 90-day and three-ballot rules of an opener scan the ballots the state keeps, which are the open ones and those that ended in the last 111 days. All are linear in the size of the live state and bounded per entry by the rate limits; none is indexed.
58. **A departure leaves its mark.** `Member.left`, `ledger._depart`, `ledger._rekey_recover` (RR3a). Every departure records what it changed, because the ledger cannot tell a departure signed by the member from one signed by whoever else holds the key, frozen or not. The mark stays on the record when no recovery is applied, and nothing removes it but a new admission. A request for a recovery of a departed record is accepted within 30 days of the departure (`DEPART_RECOVER_DAYS`), or after them when it follows a recovery asked in time for this departure (`Recovery.departure`: asked within the 30 days, or, at the departure, the latest recovery of the membership, not applied, alive or asked, stopped or voided at most 90 days before; or itself such a follow-up), whatever ended that one, within `DEPART_FOLLOW_DAYS` = 150 days of its request or of the old key's stop of it (RR5 and RR6 put the follow-up 90 days after them at the earliest, so it has 60 days); a recovery asked before the departure goes on. So whoever holds a stolen key cannot make a departure stand by signing it, whether the recovery asked in time expires for want of a co-signer, is opposed, or is stopped, and a member who left in earnest is free once no recovery asked in time is in play: never later than 150 days after the end of the last one, and an old recovery whose request, stop or voiding, whichever is latest, came more than 90 days before the departure never reaches it. A chain of follow-ups, each within 150 days of the one before, keeps the departure reversible as long as it lasts, and nothing bounds its length: a link that expires, is opposed or is stopped by the old key ends that link, never the chain, so the Masters' opposition does not end it either. Only whoever controls the member's GitHub account extends it: each link is a `rekey_recover` that the identity gate (section 9.3) takes only from the account the ledger records for the member, with a new key that account lists, so a thief who holds the old key alone cannot, and a link costs that account one entry every 90 to 150 days and nothing else (a link that is only kept alive needs no co-signer and no notice). Only the link that completes needs its co-signers (after the drop, those given by then, at least one where another Master Builder exists) and its notice of 45 days, unopposed; its application restores the record at its degree, with no admission ballot, also after a departure that ended an open sanction, which must then be opened again. A departure with no recovery in play (none alive, or stopped or voided less than 90 days before, at the departure, and none asked within the 30 days after it) is final after 30 days. A login that departed, waited 90 days and holds a new invitation or petition while such a recovery is still alive has the old record restored at the application; the petition then finds a member under its login and is refused (P1, A4).
59. **What `--since` trusts.** `verify.verify_report`, `ledger.replay` (`trusted`). The judge takes on trust the signatures and the checkpoint digests of the entries the base branch already holds: it judged them when they were added. An entry that reached `main` around the judge is therefore found by the audit (`verify --tree --online` without `--since`), which checks every signature and every digest, and not by the judge of the next pull request, which builds on it.
60. **A voided record answers for fraud for 90 days only, and the window is asked at the opening.** `ledger._open_sanction` (SN2a). An `expel_for_fraud` ballot on a voided record is opened before 90 days have passed since the undo and may close after them; while it is open the login is not invited (I5). Fraud found later has no ballot to state it: the record stays `voided`, no sponsor is banned, and the login may be invited again.
61. **The daily limit is a backstop.** `ledger.ENTRIES_PER_DAY`. No member reaches 20 counted entries in a day by lawful acts under the other limits (section 5.4); the number bounds what a stolen or careless key can add, and it is one number for a member, a witness and a custodian. A witness that closes ballots and draws lots is exempt for those types, so on a ledger with many ballots ending on one day the limit is not what bounds a witness.
62. **The only Master Builder.** `ledger._rekey_recover`, `identity.pr_problems`. Where the member is the only active Master Builder, a recovery needs no co-signer, with or without a custodian: replay accepts the request of any new key, and what stands between a stranger and the membership is the gate of section 9.3 (the pull request must come from the member's GitHub account, which must list the new key), the 45 days of notice and the objection of the old key. Whoever takes over the GitHub account of such a member, while the member has lost the key or does not watch the ledger for 45 days, takes the membership. A member who still holds the key and watches stops one request with one entry, and not the next: asked 90 days after the stop, it cannot be stopped by the old key and applies after its 45 days of notice unless a Master Builder opposes it, so the thief takes the membership in about 135 days even when the member watches (for the only Master, nobody can oppose it). With a second Master Builder who answered within a year the request needs that co-signer; a second one who answered nothing in that time is not waited for (point 76), and the request then rests on the same safeguards. **With one member, the GitHub account is the root of trust**: that is stuck by nature, and the documents say so (`docs/operations/RECOVERY.md`, section 9).

### 12.7 Liveness: what moves, and what is stuck by nature

63. **The founder's fallback can be taken by a stolen key where no other Master stands.** `ledger._custodian_claim`. One objection of an active Master Builder who is not a founder voids a claim; where none exists (the Founding Phase of one founder), a stolen founder key with the founder's GitHub account claims the office after 30 days, and the Sunset and the term bound it. The founder's remedy is the revoke key of the claimed custodian, which the thief holds too; the members' remedy is the removal ballot once Masters exist, after which that founder never claims again. "More locks, always possible" was the founder's choice.
64. **A succession can be claimed in a Master's absence.** `ledger._succession_claim`. A Master who is away for more than a year (dormant) and does not sign within the 90 days of the claim finds successors on return; they hold four powers and none of them touches the law, the witnesses, a sanction or the Custodian, and the Master's first entry restores them as the highest degree present. A Master who is away less than a year blocks a claim by being active and answering what they are called to: one who is called twice in 180 days, the two calls ending at least 7 days apart, and answers neither is silent (section 7.7), is no Master present for the succession, and lifts it only by a revealed vote or a report.
65. **A re-run lowers the quorum to those who answered.** `ledger._rerun_of` (B9). A ballot timed for an absence lapses, and its re-run can pass with the votes of those who were there; the absent keep the vote for at least seven more days, and every ballot is public. Two ballots of at least seven days each are the time an absent member has to answer (B2f, B2g: a ballot that gave less than seven days to commit is never re-run, and calls nobody, so a short ballot neither lowers a quorum nor makes anyone silent); that is the price of "one person's omission never locks the game".
66. **The tree gate trusts the base branch's tree** (`--base-root`), except for the genesis. What is unlawful already in `main` is a warning for a pull request that did not change it; the pull request that adds entry 0 is held to the tree in full. The audit of `main` still refuses it, so the alarm is raised every day; but a ledger-only pull request goes through while it stands. A code pull request that leaves an unratified file as it is goes through the gate too, and is held by the code-owner review.
67. **The candidate check is not a required status.** `tyler.yml`, job `candidate`. It runs the pull request's code, which the judge never does, and on `pull_request`, whose runs from first-time contributors wait for approval; a required check would hold their petitions. It binds through the code-owner review of the core and the electors' own `verify --candidate-root`.
68. **The protocol epoch is a counter, not a rule.** `State.epoch`. This core reads it nowhere. The epoch moves at the close of the ballot that pins a new core (also one that re-pins the same digest), and the new core is merged afterwards, within the `PRIOR_PIN_DAYS` = 30 days in which the text before it stays lawful; the entries merged in between were judged by the old core. A later core that changes a rule therefore branches on a fixed time or `seq` written in the text the ballot pinned, later than the last moment the ballot can close plus those 30 days (for instance `if time >= T:`), and never on the epoch alone: a rule applied from `S.epoch >= N` would replay those entries under the new rule, and the `candidate` check of the merge would fail. No rule bounds when a passed ballot is closed (section 6.7), so the opener chooses `T` with the windows of the ballot and a margin; a close that comes later still is caught by the `candidate` check, and the text is amended again with a later `T`.
69. **Stuck by nature, and the way out.** Each of these is no defect of a rule but of the world, and the documents name the way out. *Nobody holds a key*: nothing can be signed; a recovery genesis (`docs/operations/RECOVERY.md`, section 7). *A veto deadlock among very few members* (two Masters who blackball each other's candidates, or vote down each other's amendments): the rules are being followed; the way out is the fork (Landmark VII). *The host or the judge is dead and no administrator is left*: move house (section 4 of the runbooks) and judge by hand (section 10). *A head dated far in the future was merged around the gate*: every notice period bends; restore `main` from a clone that holds the true history. *A merged core refuses its own history*: revert to the prior pin within its 30 days, or a recovery genesis; the `candidate` check exists so that this does not happen. *One member*: the GitHub account is the root of trust (point 62). *No Master Builder, and the drand beacon retired*: every lot needs a round of `DRAND_CHAIN` (sections 6.9 and 6.13); without one the lot of every exam lapses 7 days after its round, so no exam passes and nobody advances. A succession can still be claimed and its successors invite and sponsor, so admissions go on, but nobody reaches the 3rd degree again, so no amendment is opened and the chain, which is in the pinned core, can never be changed; the way out is a recovery genesis or the fork. (While Master Builders exist, an amendment of `@protocol` names another beacon.) *A custodian threshold above the live keys*: a genesis that named three custodians with a threshold of two, of whom one key is left live (the others silent, revoked or removed), still takes that key's immediate acts, but no noticed act can be applied (AP5) and no correction can be withdrawn by custodians other than its poster (section 6.20), for want of a second key; the threshold is fixed by the genesis, and the way out is the end of that last key (silence, revoke key, removal ballot), after which a founder may claim the office where section 6.31 allows it, and the claim sets the threshold to one (section 6.33). *Fewer than 20 active members*: `max(1, n div 10)` is 1, so only one key is frozen at a time by a freeze (FK4): a freeze in force, or a recovery under way, holds back every other freeze until it ends; it never holds back a recovery (RR10, RC6, point 71).
70. **The same login invited again by the same inviter.** `ledger._invite`, `ledger.sponsorships`. A new invitation of a login replaces the lapsed one, so a lapsed invitation of that login stops counting in its inviter's budget as soon as the login is invited again. Replay alone therefore lets one Master invite the same login again and again, each time with a wrong account id, and so keep it from another inviter for 30 days at a time at the cost of one unit of budget. What stops it is the identity gate (section 9.3): the login of an `invite` must be, today, the GitHub account with the id the entry states. Under manual judging (`docs/operations/RECOVERY.md`, section 10) that step is never skipped.
71. **One login can hold the single freeze slot.** `ledger._freeze_room` (FK4, FK3). With fewer than 20 active members one key is frozen at a time, and a recovery under way counts. A login that a custodian key freezes again every 90 days (FK3), and that asks for a recovery after each freeze which nobody co-signs (under way, and so counted, to day 90 of that freeze: section 6.26), holds the one slot without a pause, for as long as that custodian key and that login act together. What it holds back is every freeze of another login, and nothing else: no recovery is held back by the cap (RR10, RC6), so the open recovery of another Master starts its notice at its co-signature whatever is frozen, and a recovery needs no freeze. A key stolen while the slot is held is therefore stopped by its own recovery, not by a freeze. The way out of the held slot is an objection to the freeze (by a Master who is not the custodian's member), the custodian's revoke key, or the removal ballot (section 6.4.6).
72. **A sole Master who never answers is found late, and is silent until they answer.** `ledger._exam_open`, `Member.silent`. The call of an exam that timed out is recorded at the next `exam_open` of the same candidate and degree, after its pool is frozen, so the second missed call of a sole Master may need a third exam, whose pool is that Master again, before a succession can be claimed. A silence ends only by a revealed vote or a report: a `work` does not end it. A silent Master who returns reveals a vote in any ballot of which they are an elector (an amendment they open and vote no in is enough: the reveal answers, and a failed ballot changes nothing), or reports in an exam they were drawn for; the Guide tells a Master who counts as silent, and that `work` does not end it (`docs/operations/RECOVERY.md`, section 9).
73. **An examination can call a Master at once.** `ledger._exam_report`, `ledger._call`. The report that decides an exam ends the call of every examiner (section 6.10), and at the 2nd degree, with two examiners, one `fail` decides. So a Master drawn twice beside the same other Master, the two draws at least 7 days apart, can be made silent by that Master's two `fail` reports, each given seconds after its draw, within 7 days and some hours of the first draw, with no time to answer either call. The bound: it needs two exams whose lots seat both of them (each at least 7 days after the other), two candidates failed in public, and a victim who revealed no vote and made no report in the 180 days before (one answer in that time makes them immune); the victim ends the silence at once by a late report in either exam, which is accepted while that exam has neither lapsed nor expired (60 days from its opening), or by any revealed vote; and silence removes no vote: it only stops the victim from being waited for (section 7.7). A ballot cannot do the same: one that gives less than 7 days to commit calls nobody (point 65).
74. **The lowered lot seats a silent member beside one who answers.** `ledger.examiner_pool` (section 7.3). When no rung seats `k`, the lot draws everyone any rung holds, and LR1 keeps a silent member of the target degree or higher. So a silent member can be drawn beside one who answers; the exam then waits for a report that never comes and times out after 60 days, and the next lot of the same candidate leaves the silent member out (`skip`, E8). The usual cost is that one exam: a sponsor Master and a silent Master above a 1st-degree member, the old lot seating the sponsor alone, now seat both, and the lot after the timeout seats the sponsor alone. It can be more where an exam lapsed undrawn before it (no `skip` carried) and the silent member's older call expires meanwhile: because a lot is frozen before the call of the exam that timed out is recorded (point 72), the silent member is, at that instant, not silent and the sole successor, and is drawn alone again (in the shape the tests pin, three exams, about six months, before the next degree's member examines). It is the price of the rule that no lot alternates between two members who never answer: drawn one at a time they were never silent together, and a 1st-degree member behind them was never examined and never a successor. The union only adds members to the pool and removes no vote, so nobody becomes the sole examiner by it. Every lot after a timeout is now such a union too, though a rung seats `k` (point 75).
75. **After a timeout the lot seats everyone any rung holds.** `ledger.examiner_pool` (`wide`), `ledger._exam_open` (E8). An exam that timed out (its examiners never reported, or its lot was never drawn) makes the next lot of the same candidate and degree the union of the rungs, without the silent examiners of the exams before (`skip`), and seats all of it. So every member who never answers is called by the next exam, and within about three exams (180 days) all of them are silent and the succession reaches the member below them; drawn `k` at a time from one rung, three inert Masters (four at the 2nd degree) were never silent together, and the member below them was never examined (section 7.3). The cost: a member who answers, seated beside members who never do, waits one more timeout (60 days) before the next lot leaves them out; in a large lodge one timeout seats every Master, and a pass then needs a majority of all of them, so a second timeout can follow before the lot narrows to those who answered. A sponsor, kept out of the usual rungs, can be seated after a timeout, and in a lot of two or three one `fail` decides, costing the candidate a 90-day retry; that sponsor is an elector of the advancement and holds the same veto there through the blackball. In a founder's lot after a timeout the union seats the founding cohort too: when it kept the cohort out while the others seated `k`, an inert founder Master was called only when every other Master was skipped, then carried as skipped and never called again, so he never fell silent, and a returning founder below the 3rd degree (the title follows the GitHub account: `founder` in section 4.2) among him and other inert Masters was never examined and never a successor. So after a timeout the founders may grade one of their own; a majority of `pass` among all the seated is still needed, and the advancement blackball still binds them. A member whom `skip` did not leave out (the lot fell back to the skipped, because nobody else was left) is not carried as skipped to the next lot. The union never seats fewer than the first rung that seats `k` and removes no vote, so nobody becomes the sole examiner or passes an exam alone by it (a majority of `pass` among all the seated is still needed).
76. **A recovery waits only for the Masters who answered within a year.** `ledger.answering_masters`, `ledger.cosigners_needed`, `ledger.dropped`, `ledger.only_sponsors` (section 6.26). A Master who signs a work a year and answers nothing (no vote revealed, no report, and the 3rd degree reached more than 365 days ago) is not counted among the co-signers a recovery needs, nor in the drop's "never fewer than one", nor as the non-sponsor `only_sponsors` asks for. Without it, a lost key, or a departure signed by a thief holding the key alone, was never undone while every other Master was inert. The cost: **in a lodge whose other Masters answered nothing for a year, a recovery rests on what point 62 accepts for the only Master**: the identity gate of section 9.3 (the pull request from the member's GitHub account, which must list the new key), the 45 days of notice, the old key's objection, and the opposition of any Master Builder, inert ones included, who keep that power. Whoever controls the member's GitHub account, with a new key that account lists, takes the membership in 45 days if nobody watches the ledger, and in about 135 days even when the member watches: the old key stops one request, and the next one, asked 90 days after the stop, cannot be stopped by it and applies after 45 days of notice unless a Master Builder opposes it (an inert Master keeps that power, but in such a lodge only one who answers is likely to use it). One other Master who answered within the year closes that path: the final request then needs that Master's co-signature. A Master who answers again, or one who reached the 3rd degree within the year, is counted again at once, and a recovery that then lacks the co-signature is not applied and is not shown `ready` (section 4.10).
77. **The waiver to one sponsor counts the Masters present.** `ledger.sponsors_required` (section 7.5). After 30 days a petition needs one sponsor while fewer than seven Master Builders are present (neither dormant nor silent), not only in the Founding Phase. Without it, a Master among six or more peers who sign a work a year and answer nothing needed a second sponsor nobody gave and admitted nobody until the law was changed. The cost: a lodge of seven or more Masters in which fewer than seven answer admits on one sponsor after 30 days, as the Founding Phase does; every Master still votes on the admission, the blackball stands, and the silent are not waited for in its quorum (section 7.1), as before. Making the inert silent takes calls: two ballots of seven days or more, at least seven days apart, which every Master is called to.

---

## 13. Signatures

This section defines the signature predicate `sig_ok(payload, sig, actor, key)` of section 1.6. Its verdict is `crypto.signature_valid(payload, sig, key)` and nothing else; `actor` takes no part in it. It is a pure function of its three arguments: it reads no file and runs no program, so every platform reaches the same verdict. OpenSSH is used only to *make* signatures (`crypto.sign`). `ledger.apply` calls it through `crypto.verify` (the same verdict behind a local cache, which also refuses a `sig` that is not ASCII) and raises `Invalid(seq, "bad signature")` when it returns anything but true. A `sig` that holds a character outside the alphabet of section 2.2 (a carriage return, for example) is refused by the encoding rules (C2) before the predicate is consulted; every other malformed `sig` is an invalid signature like any other, never a separate error.

`payload` is the signed payload of the entry (canonical JSON of the entry without `sig`), `sig` is the entry's `sig` string, and `key` is the key the ledger holds for the entry's actor. The same predicate checks the proof of a `rekey` (section 6.18) and of a `rekey_recover` (section 6.26): there `payload` is the proof message, `sig` is `body.proof` and `key` is the new key. For a `rekey_recover` and a `rekey_recover_apply` the entry itself is checked against the new key too. It also checks the two proofs of each custodian of a genesis (section 6.1): `payload` is the custodian message or the revoke message, `sig` is `proof` or `revoke_proof`, and `key` is the custodian key or the revoke key.

A key has one of two **types** (section 2.6, S4): **plain** (`ssh-ed25519`) or **hardware-backed** (`sk-ssh-ed25519@openssh.com`, the key of a FIDO token as OpenSSH uses it, `PROTOCOL.u2f`). The type of `key` selects the form of the blob (S2) and what the Ed25519 signature covers (S3); the armor (S1) and the Ed25519 check itself are the same for both. A signature in the form of one type is never valid for a key of the other type, also when the two keys have the same point.

The rules below are complete: a `sig` is valid if and only if all of them hold. Together they give each signature a key makes exactly one accepted `sig` string (for a plain key, the Ed25519 signature `R ‖ S`; for a hardware-backed key, `R ‖ S` with the flags and the counter it was made with), and they leave nobody but the holder of the key able to produce a second valid `sig` for the same payload. (The key holder can always sign the same payload again, with another nonce or another counter; that is a new signature, not a re-spelling of the old one.)

### S1. Armor (`crypto._armor`, `crypto._dearmor`)

`sig` is ASCII text with this grammar, where `LF` is the single byte `0x0A`:

```
sig        = begin body end
begin      = "-----BEGIN SSH SIGNATURE-----" LF
end        = "-----END SSH SIGNATURE-----" LF
body       = plain-body / sk-body
plain-body = 3( 70b64 LF ) 32b64 "==" LF          ; a plain key: 306 characters in all
sk-body    = 4( 70b64 LF ) 19b64 "=" LF           ; a hardware-backed key: 363 characters in all
b64        = "A"-"Z" / "a"-"z" / "0"-"9" / "+" / "/"
```

The body is the base64 (RFC 4648 §4, with padding) of the blob of S2, cut into lines of 70 characters, as `ssh-keygen -Y sign` writes it: 244 characters for the 181-byte blob of a plain key, 300 for the 224-byte blob of a hardware-backed key. Nothing may come before `begin` or after the `LF` that ends `end`. There is no carriage return, no space or tab, no blank line, no other line length, and the unused low bits of the last base64 character before the padding are zero.

The rule is enforced as a round trip rather than as a parser: `_dearmor` decodes the base64 between the two fixed lines and accepts the result only if `_armor(blob) == sig`, byte for byte. Any text that is not the canonical armor of its own blob is refused. Which of the two bodies is required follows from the blob, and the blob from the type of `key` (S2).

### S2. Blob (`crypto._sshsig`, `crypto._sshsig_sk`)

The blob is the SSHSIG structure of OpenSSH's `PROTOCOL.sshsig`, with every field pinned. A `string` is a 4-byte big-endian length followed by that many bytes.

**For a plain key:**

| Offset | Bytes | Field | Required value |
|---:|---:|---|---|
| 0 | 6 | magic | `SSHSIG` |
| 6 | 4 | version | `00 00 00 01` |
| 10 | 4 | length of the public key | `00 00 00 33` (51) |
| 14 | 15 | key type, as a string | `00 00 00 0b` `ssh-ed25519` |
| 29 | 4 | length of the key | `00 00 00 20` (32) |
| 33 | 32 | `A` | the 32 bytes of `key` (S4) |
| 65 | 15 | namespace, as a string | `00 00 00 0b` `openmasonry` |
| 80 | 4 | reserved, as a string | `00 00 00 00` (empty) |
| 84 | 10 | hash algorithm, as a string | `00 00 00 06` `sha512` |
| 94 | 4 | length of the signature | `00 00 00 53` (83) |
| 98 | 15 | signature type, as a string | `00 00 00 0b` `ssh-ed25519` |
| 113 | 4 | length of `R ‖ S` | `00 00 00 40` (64) |
| 117 | 64 | `R ‖ S` | the Ed25519 signature (S3) |

The blob is exactly these 181 bytes, with nothing after them. `signature_valid` takes the last 64 bytes of the decoded blob as `R ‖ S`, builds the blob above from `key` and those 64 bytes (`_sshsig`), and requires the two to be equal.

**For a hardware-backed key** the public key field holds the key blob of that type (S4), and the signature field holds, after the Ed25519 signature, the two values the token signed with, as `PROTOCOL.u2f` lays them out:

| Offset | Bytes | Field | Required value |
|---:|---:|---|---|
| 0 | 6 | magic | `SSHSIG` |
| 6 | 4 | version | `00 00 00 01` |
| 10 | 4 | length of the public key | `00 00 00 4a` (74) |
| 14 | 30 | key type, as a string | `00 00 00 1a` `sk-ssh-ed25519@openssh.com` |
| 44 | 4 | length of the key | `00 00 00 20` (32) |
| 48 | 32 | `A` | the 32 bytes of `key` (S4) |
| 80 | 8 | application, as a string | `00 00 00 04` `ssh:` |
| 88 | 15 | namespace, as a string | `00 00 00 0b` `openmasonry` |
| 103 | 4 | reserved, as a string | `00 00 00 00` (empty) |
| 107 | 10 | hash algorithm, as a string | `00 00 00 06` `sha512` |
| 117 | 4 | length of the signature | `00 00 00 67` (103) |
| 121 | 30 | signature type, as a string | `00 00 00 1a` `sk-ssh-ed25519@openssh.com` |
| 151 | 4 | length of `R ‖ S` | `00 00 00 40` (64) |
| 155 | 64 | `R ‖ S` | the Ed25519 signature (S3) |
| 219 | 1 | `flags` | one byte, with bit `0x01` (user presence) set (S3) |
| 220 | 4 | `counter` | any four bytes: the token's signature counter, big-endian |

The blob is exactly these 224 bytes. The flags and the counter are inside the signature field (its length, 103, counts them) and outside the string `R ‖ S`. `signature_valid` takes the last four bytes of the decoded blob as `counter`, the byte before them as `flags` and the 64 bytes before that as `R ‖ S`, builds the blob above from `key` and those three values (`_sshsig_sk`), and requires the two to be equal.

In both forms, a different version, key type, namespace, hash algorithm or signature type, a reserved field that is not empty, an application other than `ssh:`, a key other than the expected one, a missing or shortened flags or counter field, and trailing bytes anywhere (after the blob, after the counter, or inside the string `R ‖ S`) are all refused by that one comparison.

The hash algorithm is pinned to `sha512` (`crypto.HASH`), the default of `ssh-keygen -Y sign`. A signature made with `-O hashalg=sha256` is refused, although OpenSSH accepts it.

### S3. Ed25519 (`crypto.ed25519_verify`)

The key never signs the payload itself. The SSHSIG signed data `M` (`crypto._signed_data`) is 103 bytes:

```
M = "SSHSIG" ‖ string("openmasonry") ‖ string("") ‖ string("sha512") ‖ string(SHA-512(payload))
```

The **message** `m` the Ed25519 signature covers depends on the type of the key:

```
plain key:             m = M                                                        (103 bytes)
hardware-backed key:   m = SHA-256("ssh:") ‖ flags ‖ counter ‖ SHA-256(M)           (69 bytes)
```

For a hardware-backed key (`crypto._sk_signed`), `SHA-256("ssh:")` is the 32-byte hash of the four bytes of the application, `flags` is the one byte and `counter` the four bytes of the blob (S2), exactly as they stand there. They are covered by the signature, so neither can be changed in a `sig` without the key.

With `p = 2^255 − 19`, `L = 2^252 + 27742317777372353535851937790883648493`, `B` the base point of RFC 8032 §5.1, `A` the point of the key (S4), `R` the first 32 bytes of the signature and `S` the last 32 read as a little-endian integer, the signature is accepted if and only if:

1. `A` is a valid key (S4);
2. `S < L`;
3. with `k = SHA-512(R ‖ A ‖ m)` read as a little-endian integer and reduced modulo `L`, the canonical encoding (RFC 8032 §5.1.2) of the point `[S]B − [k]A` is equal, byte for byte, to `R`;
4. for a hardware-backed key, bit `0x01` of `flags` is set (`crypto.SK_USER_PRESENT`): the token reports that a person was present, that is, touched it, for this signature. The other bits of `flags` are not constrained (bit `0x04`, user verification, may be set or not), and `counter` is not constrained.

Condition 3 is the equation `[S]B = R + [k]A` of RFC 8032 §5.1.7 **without** multiplication by the cofactor 8, together with the requirement that `R` be the canonical encoding of a curve point: a point has one canonical encoding, so the 32 bytes of `R` match only if `R` decodes, canonically, to exactly `[S]B − [k]A`. An `R` with `y ≥ p`, an `R` that is not on the curve, and `S + L` in place of `S` are all refused.

Because `A` has order `L` (S4), reducing `k` modulo `L` changes nothing, and every accepted `R` is in the prime-order group, so the equations with and without the cofactor agree on every signature this protocol accepts.

Condition 4 is stricter than `ssh-keygen -Y verify`, which accepts a signature made without a touch (a key created with `no-touch-required`); OpenSSH is also willing to verify a key of any application, which S4 refuses. In the other direction the protocol accepts nothing that OpenSSH refuses: `tests/test_signatures.py` builds hardware-key signatures from software keys, has `ssh-keygen -Y verify` accept them, and checks every mutation against both.

**What is not claimed.** These rules establish that the holder of the key signed, and that the signed flags byte says a person was present. They do not establish that the key is held by a hardware token: no attestation of the token is recorded in the ledger or checked by any rule, and a software key can be registered under this type and can set the flag in what it signs. The type is a statement by the member about how they keep their key.

### S4. Keys (`crypto.valid_public_key`, called by `ledger.ed25519`)

A key is accepted when it is registered (`ledger.ed25519`: the founders and witnesses of the genesis, a petition, a witness ballot, the new key of a `rekey`), and again whenever a signature is checked (`crypto._parse_key`), only if:

1. it is the text of one of the two types, with no options, comment or line break (`ledger.KEY_RE`): `ssh-ed25519`, one space and exactly 68 base64 characters; or `sk-ssh-ed25519@openssh.com`, one space, exactly 99 base64 characters and one `=`;
2. the base64 decodes to exactly the key blob of its type and encodes back to the same characters (`crypto._parse_key`):
   - plain, 51 bytes: `00 00 00 0b` `ssh-ed25519` `00 00 00 20` followed by the 32 key bytes;
   - hardware-backed, 74 bytes: `00 00 00 1a` `sk-ssh-ed25519@openssh.com` `00 00 00 20`, the 32 key bytes, then the application as a string, which MUST be `00 00 00 04` `ssh:` (`crypto.SK_APPLICATION`). A longer application such as `ssh:work`, an empty one, and bytes after it are refused;
3. the 32 bytes are the canonical encoding of a curve point (`crypto._decode`, RFC 8032 §5.1.3): with `y` the low 255 bits read as a little-endian integer and the top bit the sign of `x`, `y < p`, the equation `x² = (y² − 1) / (d·y² + 1)` has a root modulo `p`, and the sign bit is not set when `x = 0`;
4. the point has order exactly `L`: it is not the identity, and `[L]A` is the identity (`crypto._key_point`).

Rules 3 and 4 are the same for both types. Because of the round trip of rule 2, a key has exactly one text form, and the only two keys with the same point are the plain one and the hardware-backed one; the ledger treats those two as the same key (section 2.6).

Every key made by `ssh-keygen -t ed25519`, and every key made by `ssh-keygen -t ed25519-sk` with the default application, is `[a]B` and passes. Rule 4 refuses the eight points of small order, for which anyone can produce signatures, and every point with a small-order component, on which the equations with and without the cofactor (and `k` with and without reduction) can disagree.

---

## 14. Conformance vectors

`tests/vectors/` holds small ledgers, each with the outcome every conforming implementation must reach. They are the shared test of section 1.5: an implementation that accepts and refuses these ledgers as stated, and reaches the stated state digests, agrees with the reference on everything they exercise. What they do not exercise is listed in section 12, point 49.

### 14.1 The file format

Each file is one JSON object, ASCII, with exactly four members:

| Member | Value |
|---|---|
| `name` | The name of the vector. The file is `valid-{name}.json` or `invalid-{name}.json`, with `_` written as `-`. |
| `description` | What the ledger does, in a sentence or two. |
| `entries` | The ledger, in order: element `i` is entry `i`. An element is either a JSON object, the entry itself, or a **string**, the exact text of the entry's file, used where the text is the point (a duplicate key, a number with a fraction, an integer out of range). |
| `expect` | `{"valid": true, "seq": N, "head": …, "state_sha256": …}` or `{"valid": false, "seq": N, "error": …}`. |

In a valid vector, `seq` is the `seq` of the last entry, `head` its entry hash (section 2.3) and `state_sha256` the state digest (section 4.11) of the state the whole ledger leaves. In an invalid vector, `seq` is the `seq` of the entry that is refused, which is always the last one, every entry before it being lawful; and `error` is the refusal message of the reference implementation, exactly as this document states it, without the prefix `entry {seq}: `.

### 14.2 How to run them

For each file:

1. Take the degree table whose digest every vector pins: the file `canon/history/cc5055199c8213648f536a6856c9d6879944c48be7151593ad279f73b84b7b32.toml` of this repository (section 8.4). It is the one input of replay the vectors do not carry (section 1.6). The other five pins of each genesis are arbitrary digests: replay opens no governed file.
2. If any element of `entries` is a string, read the ledger as the loader of section 2.7 reads a directory: element `i` is the content of the file `entry_name(i)`, `{i // 1000:04d}/{i:06d}.json` (a string as it is, an object in any JSON text of it). A refusal by the loader is the outcome, at the index of the file. Otherwise apply the objects directly; both ways give the same verdict (section 2.7).
3. Replay from the empty state with the real signature predicate of section 13. The keys are Ed25519 keys and every signature in a vector is a real one, so a vector also tests the armor, the blob and the curve arithmetic; three vectors are refused for the signature alone.
4. Compare. For a valid vector: no refusal, `S.seq = seq`, `S.head = head` and `digest(S) = state_sha256`. For an invalid one: entries `0` to `seq − 1` are accepted and entry `seq` is refused; the message SHOULD equal `error` (section 1.5).

The digest is the strong half of the comparison: it covers every stored fact of the final state, so an implementation that accepts every entry and keeps one field wrong fails the vector.

### 14.3 The vectors

Valid (28):

| File | What it holds |
|---|---|
| `valid-founding-with-custodians` | A genesis with three founders, a witness and two custodians (threshold 2) with their four proofs; a `custodian_alive`. |
| `valid-admission-passes` | `invite`, `petition`, `vouch`, an admission ballot with three commits, three reveals and a close by the witness: a member of the 1st degree. |
| `valid-admission-blackballed` | The same with one black ball in three: the ballot fails and the petition is removed. |
| `valid-exam-and-advancement` | `exam_open`, `exam_draw` with a beacon, an `exam_recuse` and its replacement, two `exam_report`, and an advancement ballot to the 2nd degree. |
| `valid-amendment-with-prior-pin` | A passed amendment: the pin, the prior pin with its window, the amendment record. |
| `valid-sanction-suspends` | A sanction ballot that suspends a member, who then departs. |
| `valid-witness-added-and-checkpoints` | A witness ballot that adds a witness, whose key signed the proof of possession in the subject; a checkpoint with `root` and `anchor` by the new witness, and one without them by the first. |
| `valid-rekey-replaces-a-key` | A `rekey` with its proof, and the member's next entry under the new key. |
| `valid-freeze-halt-stay-and-the-effective-clock` | A `freeze_key`, a `stay`, a `halt` and two withdrawals; a commit accepted two days after the stored deadline, a reveal by the frozen member, and a close on the ballot's own clock, three days later than the stored windows say (section 7.8). |
| `valid-void-of-an-open-ballot` | A `void_ballot` posted, and applied after its 14 days. |
| `valid-undo-with-an-objection` | An `undo_ballot` of a passed admission, one objection (two would void it), and its application: the record is `voided`. |
| `valid-custodian-removed-by-ballot` | A ballot of kind `custodian` that passes by simple majority. |
| `valid-key-recovery` | `freeze_key`, `rekey_recover`, two `rekey_cosign`, `rekey_recover_apply` after 21 days, and an entry under the recovered key. |
| `valid-frozen-elector-votes` | A `freeze_key` on an elector of an open amendment ballot, who still commits and reveals: two thirds are not reached and the amendment fails. |
| `valid-note-on-the-moderation-ground` | A `note` on the ground `moderation`: a record of `S.notes`, none of `S.corrections`. |
| `valid-recovery-without-a-custodian` | No custodian: a `rekey_recover` without a freeze, one `rekey_oppose` (too few to void it), three `rekey_cosign`, the third of which freezes the old key and starts 30 days of notice, and the application. |
| `valid-sole-master-recovers-without-a-custodian` | One founder and no custodian: the request starts its notice itself, 45 days because the co-signers were lowered to none, and the new key applies the recovery with no co-signer. |
| `valid-ballot-lapses-then-closes-early` | An admission ballot with one vote of three electors lapses and leaves the petition; the sponsor opens another, which is closed as soon as all three have revealed, before the reveal window ends. |
| `valid-custodian-key-through-its-term` | A custodian key kept alive every 180 days signs in the last second of its term, 2,555 days after the genesis. |
| `valid-founder-takes-up-the-office-again` | The genesis custodian falls silent for 181 days; its founder claims the office with two new proved keys; after 30 days the claim is applied, and the new custodian records a note. |
| `valid-succession-after-the-last-master-departs` | The only Master admits two members and departs; a 1st-degree member claims the succession; 90 days later she invites, and the invited login petitions. |
| `valid-lapsed-ballot-re-run` | An amendment ballot of three Masters lapses with one vote; its re-run, at once, passes with that one vote. |
| `valid-exam-times-out-without-penalty` | An examiner never reports; 60 days and one second after the exam opened, the candidate opens another at once, without the silent examiner in its pool: the new lot seats everyone any rung holds (the six other Master Builders, the sponsors among them, all six drawn). |
| `valid-founding-phase-second-sponsor-waived` | Two Masters; 30 days after the petition the inviter alone opens the admission ballot, and both vote. |
| `valid-amendment-removes-a-pin` | An amendment pins a new path, a second removes that pin (64 zeros), and a third pins a new `@protocol`: the epoch becomes 1. |
| `valid-case-twin-fails-at-its-close` | Two amendments open on `docs/x.md` and `Docs/x.md`, neither pinned yet; the first to close pins its path, and the second fails at its close (step 0 of section 6.4.3). |
| `valid-dropped-recovery-after-a-freeze` | A recovery after a freeze that nobody co-signs for 30 days: the drop starts its 45 days of notice at once (the old key stays frozen), one co-signature on day 50 is enough, and the new key applies it on day 77 (section 6.26, the drop). |
| `valid-departure-reversed-by-the-recovery-that-follows` | A request, then a departure signed with the old key; the request expires; the follow-up 90 days later is accepted (RR3a, `follows`), and its application reverses the departure. |

Invalid (36), each with the check that refuses it:

| File | Refused by |
|---|---|
| `invalid-bad-prev` | C7 |
| `invalid-time-goes-backwards` | C8 |
| `invalid-wrong-signer` | C12: a valid signature by another member's key |
| `invalid-signature-rewrapped` | C12: the armor wrapped at 76 columns (section 13, S1) |
| `invalid-signature-s-plus-l` | C12: `S + L` in the place of `S` (section 13, S3) |
| `invalid-float-in-body` | the loader (section 2.7, rule 6): `1.5` |
| `invalid-integer-out-of-range` | the loader: `9007199254740992` |
| `invalid-duplicate-key` | the loader: `seq` twice |
| `invalid-unknown-field` | C10 |
| `invalid-oversized-entry` | C4: a canonical encoding above 8,192 bytes |
| `invalid-petition-without-invitation` | P0 |
| `invalid-second-reveal` | the elector already revealed |
| `invalid-frozen-member-acts` | the freeze gate of section 5.2 |
| `invalid-entry-during-a-halt` | the halt gate of section 5.2 |
| `invalid-correction-by-a-lapsed-key` | section 5.2: a custodian key silent for more than 180 days |
| `invalid-apply-before-the-notice-ends` | AP4: one second before the notice is over |
| `invalid-undo-after-a-conflicting-change` | AP7: the member departed during the notice, so the comparison fails and nothing is undone |
| `invalid-checkpoint-with-a-wrong-state-digest` | Z5 |
| `invalid-witness-ballot-with-a-bad-proof` | W7: the proof of possession was signed by another key |
| `invalid-amendment-opened-by-an-apprentice` | M0 |
| `invalid-fourth-open-ballot` | B7b |
| `invalid-checkpoint-without-a-new-entry` | Z6: a second checkpoint an hour after the first, with no entry in between |
| `invalid-twenty-first-entry-in-a-day` | C12a: the twenty-first checkpoint of a witness in one UTC day |
| `invalid-note-on-another-ground` | N5 of section 6.19 |
| `invalid-room-hold-again-within-ninety-days` | HR4: a second hold of the same login 15 days after the first began |
| `invalid-recovery-long-after-a-departure` | RR3a: a recovery asked 30 days and one second after the departure |
| `invalid-correction-after-the-term` | section 5.2: a custodian key one second after its term of 2,555 days |
| `invalid-void-posted-after-the-reveal-opened` | VB3a: the first second of the reveal window |
| `invalid-claim-applied-before-its-notice` | CA3: one second before the 30 days of a founder's claim are over |
| `invalid-sanction-on-a-master-by-one-elector` | B8a: of two Masters, one opens the expulsion of the other |
| `invalid-successor-invites-before-ninety-days` | I3: a successor invites one second before the succession is in force |
| `invalid-checkpoint-without-a-state-version` | C10: the body of a `witness` entry without `state_version` |
| `invalid-exam-drawn-after-its-lot-lapsed` | F3a: one second more than 7 days after the beacon round |
| `invalid-second-re-run` | B2c: a re-run that lapsed is re-run again |
| `invalid-frozen-key-signs-during-a-dropped-recovery` | the freeze gate (section 5.2): the old key signs a `work` while a dropped recovery after a freeze is under notice, after the freeze ran out |
| `invalid-short-ballot-re-run` | B2g: the re-run of an amendment ballot that gave 2 days to commit |

### 14.4 How they are kept true

The vectors are generated, not written by hand: `tests/make_vectors.py` builds them with fixed keys (derived from names, and signed in pure Python, so that no tool but the code under test is involved), fixed times and fixed beacons, and asks the reference implementation for each outcome. `tests/test_vectors.py` generates them again in memory and compares them with the committed files byte for byte, so a change of the protocol that moves a hash, a digest or a refusal fails until the files are generated again on purpose (`PYTHONPATH=src python3 -m tests.make_vectors`); it then replays every committed file with real signature verification, and checks that each refusal is a message this document states. A vector that changes is a change of the protocol, and is reviewed as one.

---

## 15. Rooms (derived, outside replay)

Each degree `k` (1 to 33) has a **room**: the private repository `degree-NN` of the organization, read by the team `degree-NN` and by every higher team (`NN` is `k` on two digits). Who sits in which team is a **rule**, not a choice (Constitution Art. XV.3, `docs/governance/ROOMS.md`). The rule is `src/openmasonry/rooms.py`, a file of the pinned core (section 8.3), so it changes only by an amendment of `@protocol`. **Replay never reads it**: no entry is accepted or refused because of it, nothing of it enters the state or its digest, and a verifier that does not implement it is still conforming for sections 2 to 14. It is pinned so that the program that applies the rule cannot be changed by review alone. The program that applies it (`ops/rooms/sync.py`) and the Observatory (`metrics.py`, `observatory.py`) are outside the core.

### 15.1 The roll

`room_access(S, now)` maps each login `m` of `S.members` to `m.degree` when both hold:

| # | Condition |
|---|---|
| RM1 | `m.standing(now) = active`: not suspended (a suspension whose term is served counts as active, section 4.2), expelled, departed or voided. |
| RM2 | `room_held(S, m, now)` is false: no `hold_room` correction on `m` is in force at `now` (section 6.19). |

Nothing else counts: a **dormant** member keeps access (dormancy only leaves the quorum count), and neither a frozen key, a pending recovery, an open sanction ballot nor a Council seat changes it. Room `k` is read by every login of `room_access` whose degree is at least `k` (`readers`). The roll is public: `om rooms --json` prints it (`om.rooms/1`, below).

`github_ids(S)` maps each member to `m.github_id`, the numeric GitHub user id recorded at genesis (founders) or by the `invite` entry (section 6.17); `last_signed(S, entries)` maps each member to the time of the latest entry whose `actor` is that member, entries of `CUSTODIAN_SIGNED` aside.

### 15.2 The plan

`sync_plan(desired, actual, pending, history, protected, github_ids, signed)` returns the ordered list of actions that makes the organization match `desired` (= `room_access`). Its inputs other than the ledger's are what the organization reports, as plain data: `actual` maps a GitHub id to `{login, teams, member}` (the room teams the account is in, as degrees, and whether it is a member of the organization), `pending` lists the open invitations (`{invitation, id, login, role}`, `id` none when the sync program did not send it), `history` maps a GitHub id to the latest invitation that was declined, expired or canceled (`{failed_at, reason}`), `protected` is a set of logins (compared without case) and GitHub ids. Each action is an object with `op`, `id` (GitHub id), `login` (the login the request names: GitHub's current one for an account that exists) and, as it applies, `member` (the ledger login), `team`, `from`, `invitation`, `why`.

1. **Match by id.** A login of `desired` whose GitHub id is 0 is a `hold` (`the ledger records no GitHub id for this member`). Two logins of `desired` with one id are an error (the ledger forbids it: section 6.17). Accounts are matched by id and never by login: a member who renamed the account is found under the new login, and an account that took the old login is a stranger.
2. **Protected.** Nothing is ever planned for an id or a login of `protected` (the owners of the organization, applications, the custodian account): a member who is protected is a `hold`, a stranger who is protected is left alone, and an invitation to a protected login or with a role other than `direct_member` is left alone.
3. For each `(id, login, k)` of `desired`, in ascending id:
   - an account of `actual` that is a member, or sits in a room team: nothing when its teams are exactly `{k}`; otherwise `move` to `degree-k` from the other room teams it sits in (in that order: the new team is joined before an old one is left, so no step loses access to a room the member keeps);
   - else, an invitation pending for that id: `hold` (`an invitation is pending`);
   - else, a `history` entry for that id and no `signed[login]` strictly after its `failed_at`: `hold`, stating the failure. **A member asks for a new invitation by signing any entry after the failure**; nothing else re-sends a declined or expired one;
   - else `invite` the id into `degree-k`.
4. Every account of `actual` whose id is not in `desired` (and is not protected) is a `remove` from the organization.
5. Every pending invitation with role `direct_member` whose id is none or not in `desired` is a `cancel`.
6. The actions are ordered `remove`, `cancel`, `move`, `invite`, `hold` (losing access before anyone gains it), each group by ascending id, then invitation. A `hold` performs nothing.

The function is pure: the same inputs give the same list.

### 15.3 The sync program (not part of the core)

`ops/rooms/sync.py` applies the plan through the GitHub REST API with an installation token of an App that has the organization's Members permission and nothing else (`ops/rooms/README.md`). Before any request it replays the canonical ledger and refuses if the ledger is invalid or empty, if its head is a future head (section 9.7) or if `head_verdict` against the mark it keeps (section 9.7) is not `first` or `ok`. Each request is checked against a closed list (reads of the organization's teams, members and invitations; writes only to the membership of the 33 room teams and of the organization, with the plain member role, never for a protected login); the **mass guard**: a run makes at most `max(3, ⌈10% of the people in the room teams⌉)` additions (an invitation, or the join of a first team) and as many removals (a removal from the organization, or a canceled invitation), each counted apart and taken in a fixed order, by team and then by ledger login; the changes beyond them are deferred to the next run, which plans again from the ledger. An owner may lift the cap for one run (`--force-mass`); such a run prints the text of a `note` correction, which the Custodian records in the ledger. At most 40 invitations are sent in a run and 50 in 24 hours, the rest waiting for a later run. Each run writes, beside its private state, two files for the Observatory that name nobody the ledger does not: `actual.json` (`om.rooms-actual/1`: the members of each room team, by the login the ledger records for their GitHub id, any other account only as an unnamed count, the owners and every installed application) and `runs.jsonl`, to which one line per run is appended and never rewritten, in counts only (what the run planned, deferred and did). None of this is a rule of the fraternity: it bounds what a stolen token or a bug can do through this program.

### 15.4 `om rooms` (`om.rooms/1`)

`{schema, name, head, entries, time, rooms, counts}`: `rooms` holds 33 objects `{room, degree, readers, count}` (the sorted logins of `readers`), and `counts` is `{with_access, without_access, rooms_open}`, where `without_access` counts the members who are neither departed, expelled nor voided and have no access (suspended, or held). `om observatory --rooms-actual FILE` adds `actual`: for each room, the logins the ledger derives that GitHub does not grant (`missing`) and those GitHub grants that it does not derive (`extra`), the owners and applications (who read every room by their role and are listed, not counted), teams named like no room, and the number of `differences`; and, when a `runs.jsonl` lies beside that file, `runs`: its lines, oldest first, each with the public fields of a run (time, whether it applied or was forced, the `seq` and head it read, its result, its additions, removals and deferred changes, whether a note is required, and its actions counted by operation and result). The Observatory never measures what happens inside a room.
