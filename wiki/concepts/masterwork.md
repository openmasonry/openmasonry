---
title: "Masterwork"
type: concept
tags: [work, degrees, education, tradition]
sources:
  - canon/degrees.toml
  - src/openmasonry/ledger.py
  - docs/whitepaper/WHITEPAPER.md
  - raw/sources/sym-mackey-symbolism-of-freemasonry-1869.md
---

# Masterwork

In the operative craft, a journeyman proved his skill by presenting a *masterwork* to the masters of his trade before being admitted among them. Lodges kept the idea of written and practical work as proof of progress, alongside the drawing boards on which the plans are laid out.
- The **trestle board** is the board on which the master of the works draws the plans for the workmen. The manuals count it among the "jewels" of the lodge and read it as the moral plan each person draws for their own life. The whitepaper calls the ledger the "Tracing Board", and the distinction between the tracing board (a panel of symbols) and the trestle board (a drawing board) is explained in [[tracing-board]].
- A **masterwork** is the written work, study or practical contribution a member presents as proof of progress before a raising. Many lodges ask for a paper or a lecture before advancement.

**Readings**
- Written work is the visible polishing of the stone: it shows what the member has learned.
- The plan comes before the building. Without a plan, you only pile up stones.

## In OpenMasonry
- **Every raising requires a public masterwork** that improves the commons: a reviewed contribution, an essay, an audit, a runbook, a mirror, a curriculum (whitepaper §11.2). The `work` field of each degree in `canon/degrees.toml` says which. Examples: 1st = the signed Declaration plus a public reflection of 500+ words; 3rd = a substantive piece of 2,000+ words defended before three examiners; 15th = operating a verified mirror of the canonical repository for 90 days; 30th = a red-team report with at least one finding fixed.
- **In the code:** only the candidate may open their own exam; `exam_open` requires a `work_ref` that is an `http(s)` URL without spaces or quotes, and declares the future drand round `beacon_round` (`ledger._exam_open`), freezing the examiner pool and `k`. After that round, `exam_draw` ranks the whole pool with the published beacon and seats the first `k` (`ledger._exam_draw`; see [[verifiable-lottery]]). A drawn examiner with a conflict of interest may step aside with `exam_recuse` before reporting, and the next member in the lot's order takes the seat; when nobody is left, the exam lapses without penalty (`ledger._exam_recuse`). Each verdict (`exam_report`) is `pass` or `fail`, with an optional `reason` that must be the URL of the published, reasoned verdict. Passing requires a strict majority of the seated examiners; the exam fails when half or more fail it, or when the advancement ballot it supports fails on the votes (`Exam.passed`, `Exam.failed`). After a failure the candidate may open a new exam only 90 days after the failed one was opened. When 60 days pass without either majority, the exam times out with no penalty: the candidate opens a new one at once, and the silent examiners are left out of its pool whenever others can be drawn. Each passed exam supports a single advancement ballot. The `work` entry records a contribution with a mandatory `http(s)` `ref` (`ledger._work`) and adds to [[light-score]].
- The cycle sustains itself: study the art of the degree → produce the piece → the commons improve → better commons attract and form members.
- Privacy: the content stays in the author's repository and the ledger keeps only the reference or hash, which allows erasure (Whitepaper §12.3).
