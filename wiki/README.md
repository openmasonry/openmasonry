# The OpenMasonry wiki

A knowledge base about the history, symbols and institutions the project draws on, and about its own protocol. [index.md](index.md) lists every page.

## Folders

| Folder | Holds |
|---|---|
| `entities/` | people, organizations, places |
| `concepts/` | ideas, symbols, protocol mechanisms |
| `synthesis/` | cross-cutting pages (timeline, degree catalog, member journey) |
| `comparisons/` | side-by-side analyses |
| `queries/` | answers to common questions |
| `sources/` | one summary for each clip in [`../raw/sources/`](../raw/sources/) |
| `overview.md`, `index.md`, `log.md` | the overall picture, the list of pages, and notable changes |

## Writing pages

Name files in lowercase with hyphens. Each page, apart from `index.md` and `log.md`, opens with a YAML frontmatter block giving its `title`, a `type` that matches its folder (`entity`, `concept`, `synthesis`, `comparison`, `query`, `source`, or `overview` for `overview.md`), a few `tags`, and the `sources` it relies on as paths under `raw/sources/`.

Link pages with `[[slug]]`; a link must name a page that exists. Back each fact with a source and mark disputed ones as disputed. Keep legend apart from history, and never reproduce secret ritual. When a page explains the protocol, describe what the code does and name the function (for example `ledger._vouch`) rather than a line number.

A new source goes into `raw/sources/` as a clip, gets a summary page in `sources/`, and is then worked into the pages it touches and into `index.md`. If it contradicts an existing page, say so on that page. Notable changes are recorded in `log.md`.
