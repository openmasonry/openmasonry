# Engine instructions (OpenMasonry MCP engine)

- The engine **never** implements a protocol rule: every capability calls `bin/om` through `src/om.ts` (`execFile`, no shell) and parses a versioned `om.*` JSON contract. A capability that reimplements a rule violates Landmark VI.
- There is **no** capability that signs, approves, submits or touches keys. Drafts are sealed by `om`; only `bin/om approve` (a system dialog for the person) signs.
- Validate every input with strict patterns before it reaches `om` (`src/om.ts` exports them).
- `createLocalEngine` (stdio, principal `local:<login>` fixed at startup) may include `entry.draft` and `entry.pending`. `createPublicEngine` (HTTP) must never include them.
- `entry.draft` drafts a member's own acts. Of everything about corrections it drafts one act, `object` (a Master Builder's objection). No custodian act (a correction, its co-signature, application or withdrawal, a sign of life, a revocation) and no key recovery is ever a capability: those are drafted with `bin/om` by the person. `corrections.read` only reads.
- The public HTTP endpoint is anonymous **by design** (it serves only public facts and has no write capability). This is a deliberate exception to the engine's fail-closed design (every capability must declare who may call it, and every input and output is validated), recorded as decision 11 in `docs/architecture/ARCHITECTURE.md`.
- Keep business logic out of the transports (`src/mcp-tools.ts`, `src/http-transport.ts`, `src/http-settings.ts`, `src/serve-stdio.ts`, `src/serve-http.ts`). Capabilities are declared with `declareCapability` (`src/capability.ts`), assembled in `src/compositions.ts`, and served through the official `@modelcontextprotocol/sdk`.
- Configuration comes from the process environment only. A malformed setting stops startup, and no diagnostic ever repeats a value.
- Pin dependencies exactly; the `overrides` keep every copy of `@modelcontextprotocol/sdk` and `zod` on the pinned version.
- Add a test with every change, and run `npm run check` before completing it.
