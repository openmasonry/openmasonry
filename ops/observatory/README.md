# Publishing the Observatory

`bin/om observatory --out DIR` writes the Observatory: one self-contained `index.html` (no external script, style or font; inline SVG charts; light and dark by the reader's system setting; links only to the canonical repository), `metrics.json` (`om.metrics/1`), `timeline.json` (`om.timeline/1`) and `rooms.json` (`om.rooms/1`). Without `--rooms-actual` it reads the ledger and nothing else, so anyone can build the same page from a clone. With `--rooms-actual FILE` (the `actual.json` the room sync writes, `om.rooms-actual/1`), `rooms.json` and the page also show the access GitHub actually grants (the room teams, every owner of the organization and every installed application), every difference from the derived roll, and the anonymous log of the sync's runs (`runs.jsonl`, read from beside that file).

[`.github/workflows/pages.yml`](../../.github/workflows/pages.yml) is the workflow that publishes it to GitHub Pages on every push to `main`, after every run of the judge, every six hours and on demand, built only from `main`. It is part of the pinned core (`src/openmasonry/protocol.manifest`, SPEC section 8.5) from the genesis, so after the genesis it changes only by an amendment of `@protocol`. Its two actions (`actions/upload-pages-artifact` and `actions/deploy-pages`) are pinned by full commit SHA. Only its deploy job holds `pages: write` and `id-token: write`, and it runs only GitHub's own action on an artifact built from `main` with read-only permissions.

The room sync publishes `actual.json` and `runs.jsonl` to a public repository on every run ([ops/rooms/README.md](../rooms/README.md#what-it-publishes-landmark-ii)). The repository variable `ROOMS_PUBLIC_REPO` (`owner/name`) names it; the build fetches it with plain git and no credentials, checks the files as data and runs nothing from it. Without that variable the page shows the derived roll only.

## To publish it

The settings the workflow cannot make are made by hand, by an owner ([LAUNCH.md](../../docs/operations/LAUNCH.md)):

1. Settings → Pages → Source: **GitHub Actions**.
2. Settings → Environments → `github-pages` → deployment branches: `main` only. GitHub does not set it, and without it a run on another branch could deploy; a reviewer confirms it.
3. Settings → Secrets and variables → Actions → Variables: `ROOMS_PUBLIC_REPO`, the public repository where the room sync publishes.
