# OpenMasonry MCP engine

MCP access to OpenMasonry for members' agents. It uses the official [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk) ([decision 11 in ARCHITECTURE](../../docs/architecture/ARCHITECTURE.md#decision-11-mcp-engine)). It **never signs**: it reads, and it prepares sealed drafts that the person approves in a system dialog with `bin/om approve <digest>`.

| Composition | Transport | Capabilities | Who |
|---|---|---|---|
| **local** | MCP stdio | `member.due-steps`, `ledger.status`, `ledger.verify` (incl. online), `corrections.read`, `degree.read`, `rule.sources`, **`entry.draft`**, `entry.pending` | the member, on their own machine, inside their clone |
| **public** | MCP Streamable HTTP | the same six reads (`member.due-steps` takes a `login`), offline verify only; at most 2 `om` processes at a time, identical reads cached for 30 s | anyone; serve it beside a witness on any VPS |

Over MCP, tool names use `_` instead of `.` (e.g. `member_due-steps`, `corrections_read`, `entry_draft`, `entry_pending`).

`corrections_read` wraps `bin/om corrections --json` (`om.corrections/1`): every correction with its act, target, ground, the sha256 and path of its public reason, status, signers, objections and how many void it, and its notice, apply and lapse times; the custodians with their status and sign-of-life deadline; the halt; key recoveries. `member_due-steps` also returns `notices` (a halt, the person's frozen key, room hold or key recovery, a correction they may object to) and `custodian`. Notices are information, never steps: the agent never proposes an objection, a recovery co-signature or the removal of a custodian.

`entry_draft` takes an `act` named like the `action` of the steps returned by `member_due-steps`: `join`, `sponsor`, `vote`, `reveal`, `open_admission`, `advance`, `close`, `exam`, `report`, `recuse`, `draw`, `call_council`, `work`, `depart`, plus `open_sanction`, `open_amendment`, `invite` (a Master Builder invites a named login and becomes its first sponsor; it is never a due step, and the agent never suggests whom to invite) and `object` (a Master Builder objects to the correction with entry number `correction`; never a due step, drafted only when the person asks). **No custodian act is exposed** (a correction, its co-signature, application or withdrawal, a sign of life, a revocation), and neither is a key recovery: those are drafted with `bin/om` on the person's own terminal. `join` works only under a live invitation; a person without one gets the step `apply`, which carries `bin/om apply --text FILE` (they introduce themselves in a public issue, in their own words; the engine does not draft it). A vote carries **no** value: the person chooses Yes or No in the approval dialog, so the agent never learns it. The tool returns `digest`, `summary`, `entry` and the `approve` argv, or `refused` with the rule. `entry_pending` lists the person's sealed drafts. The person then runs `bin/om approve <digest>`. If your agent's harness times out long-running commands, run `bin/om approve <digest>` in your own terminal.

Every rule lives in `om` (the Python reference today, Go later). The engine calls `bin/om` with `execFile`, never a shell, after strict validation (GitHub logins, ballot ids `[a-z0-9._-]`, https URLs, sha256), passes `--` before free text, and parses versioned JSON contracts (`om.me/2`, `om.state/2`, `om.corrections/1`, `om.verify/1`, `om.degree/1`, `om.rules/1`, `om.draft/1`, `om.drafts/1`). Contracts grow by additive fields under the same schema name: `member.due-steps` also returns `founding_phase`, `canon_pending`, `notices`, `custodian` and `stale` (signed entries that lost their seq; `bin/om pending --rebase <seq>`), and `ledger.status` returns `founding_phase`, `masters` and `canon_pending`. Timeouts and aborts come back as precise errors (`OmError`) to direct callers; over MCP a canceled call returns `CANCELED` and any other failure `FAILED`, without the cause.

## Use it from your agent (local)

```bash
cd openmasonry/engines/openmasonry && npm ci && npm run build
```

```bash
npm run --silent client-entry
```

`client-entry` prints the entry that registers the stdio server in the common `mcpServers` JSON shape (the `node` binary, the absolute path of `dist/serve-stdio.js`, and `OM_ROOT`, plus `OM_LOGIN`, `OM_KEY` and `OM_HOME` when they are set). It writes nothing: copy the entry into your agent client's MCP configuration. `OM_ROOT` defaults to this clone; set it before running the command to point elsewhere. Without `OM_LOGIN` the server asks `gh api user` for the login; with neither, only the reads answer. The same server is the package's `openmasonry-mcp` binary. In a clone, agents that read the linked skills usually do not need it: the officer skills (`/om`) already drive `bin/om`.

## Serve the public endpoint (any VPS)

```bash
OM_ROOT=/srv/openmasonry OM_ENGINE_HTTP_HOST=0.0.0.0 OM_ENGINE_HTTP_ALLOWED_HOSTS=om.example.org node dist/serve-http.js
```

| Variable | Meaning |
|---|---|
| `OM_ROOT` | a clone of OpenMasonry (required) |
| `OM_ENGINE_HTTP_HOST` | bind host (default `127.0.0.1`) |
| `OM_ENGINE_HTTP_PORT` | bind port (default `3000`; `PORT` is read when it is unset) |
| `OM_ENGINE_HTTP_ALLOWED_HOSTS` | comma-separated `Host` allowlist; required when the bind host is not loopback |
| `OM_ENGINE_HTTP_ALLOWED_ORIGINS` | comma-separated browser origins; by default a request with an `Origin` is refused |
| `OM_ENGINE_HTTP_MAX_BODY_BYTES` | request body limit (default 1 MiB) |

Settings are read from the process environment only. A missing `OM_ROOT` or any malformed value stops startup with one line on stderr that names the variable, never its value. The endpoint is stateless Streamable HTTP at `/mcp` (POST only, one JSON-RPC message per request, JSON answers). Keep `OM_ROOT` up to date (`git pull` from cron, or the witness's clone), and put a reverse proxy with TLS and rate limiting in front: the engine does no rate limiting (it only caps concurrent `om` processes and caches identical reads for 30 s). The endpoint is anonymous on purpose, because it serves only what is already public. It has no draft or sign capability, so no vote, key or identity ever reaches it.

## Develop

```bash
npm run check   # typecheck, build, tests (fake om, real om, MCP in memory, over HTTP and through the built stdio and HTTP entry points)
```

`src/capability.ts` declares capabilities and calls them (input check, caller check, output check, fixed error codes); `src/compositions.ts` assembles the local and public engines; `src/mcp-tools.ts` publishes an engine as MCP tools; `src/http-transport.ts` (with `src/http-settings.ts`) and the entry points `src/serve-stdio.ts` and `src/serve-http.ts` are the transports. A failed call returns only `{ code, message, details? }` (`details` carries schema issues or the unknown capability id), never the cause. The codes are `UNKNOWN_CAPABILITY`, `BAD_INPUT`, `NO_IDENTITY`, `NOT_PERMITTED`, `BAD_OUTPUT`, `CANCELED` and `FAILED`. Dependencies are pinned exactly, and `overrides` keep every copy of `@modelcontextprotocol/sdk` and `zod` on the pinned version. Install with `npm ci`.
