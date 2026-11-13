/**
 * The public, read-only MCP endpoint (Streamable HTTP at /mcp).
 *
 * Settings come from the process environment only; http-settings.ts lists
 * them. A bad setting ends the process with status 1 and one line on stderr
 * that names the variable but not its value. Once listening, it writes
 * `MCP endpoint: http://<host>:<port>/mcp` to stderr; SIGTERM or SIGINT closes
 * it and exits 0.
 */
import { createPublicEngine } from "./compositions.js";
import { readEndpointSettings, SettingsError } from "./http-settings.js";
import { listenHttp } from "./http-transport.js";
import { createOmRunner } from "./om.js";

/** Never prints an unexpected error's text: it may come from a dependency and hold anything. */
function abort(error: unknown): never {
  const reason = error instanceof SettingsError ? error.message : "could not start";
  process.stderr.write(`openmasonry http: ${reason}\n`);
  process.exit(1);
}

async function start(): Promise<void> {
  const { root, ...network } = readEndpointSettings(process.env);

  // Reads only, never a draft. At most two `om` processes at a time; an identical read is served from cache for 30 s.
  const om = createOmRunner({ root, maxConcurrent: 2, cacheMs: 30_000, timeoutMs: 60_000 });

  // No caller identity on purpose: everything this engine can return is already public (the ledger and the
  // repository's texts), and it holds nothing that drafts or signs, so there is no account or token to steal.
  const endpoint = await listenHttp(createPublicEngine(om), { ...network, principal: { id: "anonymous" } });

  let stopped = false;
  const stop = (): void => {
    if (stopped) return;
    stopped = true;
    // close() cancels open calls and drops every connection, so the exit is never held up.
    endpoint.close().then(() => process.exit(0), () => process.exit(1));
  };
  // The handlers go in before the line below, which a supervisor may treat as "ready" and answer with SIGTERM.
  for (const signal of ["SIGTERM", "SIGINT"] as const) process.once(signal, stop);

  const { host, port } = endpoint.address();
  process.stderr.write(`MCP endpoint: http://${host}:${port}/mcp\n`);
}

start().catch(abort);
