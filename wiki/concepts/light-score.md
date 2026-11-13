---
title: "Light (a decaying score)"
type: concept
tags: [protocol, reputation, light, decay]
sources:
  - src/openmasonry/ledger.py
  - src/openmasonry/canon.py
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/sym-mackey-symbolism-of-freemasonry-1869.md
---

# Light (a decaying score)

Light is OpenMasonry's public measure of a member's recent service: a sum of signed activity that halves every 180 days. It is informational only and never weighs in a vote.

**Symbolic root.** In the tradition, light is the symbol of truth and knowledge (Mackey). The candidate asks for "light", and the lodge is the place where it is imparted. OpenMasonry turns this metaphor into a public measure of **recent service**.

## Exact rule (code)
```
L(m, t) = Σ_{i ∈ activity(m)} 2^( −(t − tᵢ) / H ),   H = 180 days (half-life)
```
- `ledger.Member.light`: `sum(0.5 ** ((now - t).total_seconds() / 86400 / h) for t in self.activity)`. The constant is `LIGHT_HALF_LIFE_DAYS = 180` (`canon.LIGHT_HALF_LIFE_DAYS`).
- **What counts as activity:** **every entry a member signs with their member key**, except a departure and the upkeep of a key (`depart`, `rekey`, `rekey_object`; `ledger.UNCREDITED`). That includes `work`, `invite`, `vouch`, vote commitments and reveals, exams, recusals, an objection to a correction and so on. A member gains at most **one point per UTC day**, kept at the time of the day's latest entry, and a point more than 1,800 days older than the newest is dropped (`Member.credit`, `canon.LIGHT_WINDOW_DAYS`). Entries signed by a witness key or by a custodian key credit nobody: a Custodian's corrections add no Light to the member the Custodian is linked to. Founders and admitted members receive one initial point at the moment they enter (`ledger._genesis`, `ledger._close_admission`).
- Each act is worth 1 when it happens, 0.5 after 180 days, 0.25 after 360 days, and so on.

## What Light is and is not
- It is **informational only**: it never weighs in a vote (Landmark IV; see [[decision-function]]).
- It shows who is actually serving and makes "influence without contribution" visible. A Grand Master who stops working fades from the board like any other member. It is a mirror of Landmark V's "A member who stops taking part stops being counted, and keeps the vote": Light fades, and [[dormancy]] leaves a member out of the counts, but neither ever takes the vote (see [[eternal-landmarks-of-openmasonry]]).
- It uses the same `activity` list that defines [[dormancy]].
- It appears in the public state (`openmasonry state`, `__main__.cmd_state`).

## Critical reading
Counting every signed entry, and not only `work`, also rewards the volume of protocol acts. This matches the whitepaper ("the decayed sum of their signed activity", §7.6). Since Light confers no power, the risk is reputational, not one of governance. See [[ostrom-principles]] (monitoring).
