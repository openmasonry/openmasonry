# Moderation log

The moderation log of OpenMasonry is **the ledger itself**. No table is kept by hand.

- Every act of the Custodian in the ledger is a **correction**: a signed entry with a ground and a public reason archived under `ledger/reasons/`.
- Every moderation act done on GitHub (hiding a comment, locking a thread, blocking an account that is not a member, limiting interactions, an emergency measure, a use of the ruleset bypass) is recorded in the ledger as a `correction` entry of the act **`note`**, on the ground `moderation`: what was done, to what, and under which published rule. A note changes nothing in the ledger; it is the record. It is kept apart from the corrections: it counts toward none of their limits, it cannot be objected to or withdrawn, and a Custodian signs at most ten in a UTC day. The state keeps the newest 200 notes; every note stays in its own entry forever.

## How to read it

- `om corrections` lists every correction and the notes the state keeps, with its ground, the digest and the path of its public reason, its status and its objections. An immediate act is `active`, `lapsed`, `withdrawn`, `void`, `released` or `ended`; a noticed act is `pending`, `ready`, `applied`, `expired`, `withdrawn`, `void` or `ended`; a note is `recorded`.
- The public Observatory (built, not published yet) shows the same list. It is computed only from the ledger, so anyone can reproduce it.
- The entries themselves are in `ledger/entries/`, and each reason is the file `ledger/reasons/<sha256>.md`.

## How to answer it

- A Master Builder objects to a correction with `om object` ([Custodian's charter](CUSTODIAN.md), section 6). A note is not objected to: what it records happened on GitHub, and it is answered by appeal.
- Anyone affected appeals in a public issue labeled `appeal`.

While no custodian key is live, no note can be signed: the owner of the repository who moderates meanwhile reports each act in a public issue, and nothing is recorded in the ledger until a custodian key is live again ([Custodian's charter](CUSTODIAN.md), section 10).

A note and a reason name no person beyond a login, and never the identity of a person who reported harm.
