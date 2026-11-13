#!/usr/bin/env node
/**
 * The local MCP server (stdio), run by a member's own agent client.
 *
 * OM_ROOT is the member's clone of OpenMasonry (the working directory when
 * unset). The principal is the member's GitHub login, from OM_LOGIN or else
 * `gh api user`; it is settled once at startup and never read from a tool call.
 * With no usable login, only the reads answer.
 */
import { execFileSync } from "node:child_process";

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createLocalEngine } from "./compositions.js";
import { toolServer } from "./mcp-tools.js";
import { createOmRunner, loginPattern } from "./om.js";

function githubLogin(): string | undefined {
  if (process.env.OM_LOGIN) return process.env.OM_LOGIN;
  try {
    const out = execFileSync("gh", ["api", "user", "-q", ".login"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    return out.trim();
  } catch {
    return undefined;
  }
}

const login = githubLogin();
const member = login !== undefined && loginPattern.test(login) ? login : undefined;
if (member === undefined) {
  process.stderr.write("openmasonry: no GitHub login (set OM_LOGIN or run `gh auth login`); drafts are disabled.\n");
}

const om = createOmRunner({ root: process.env.OM_ROOT ?? process.cwd() });
const mcp = toolServer(createLocalEngine(om), { principal: member === undefined ? null : { id: `local:${member}` } });

let ended = false;
function end(): void {
  if (ended) return;
  ended = true;
  // No process.exit here: stdout gets to flush, and the event loop then runs dry by itself.
  mcp.close().catch(() => {
    process.exitCode = 1;
  });
}
// The session ends when the client closes our stdin or stdout stops accepting writes.
for (const event of ["end", "close"] as const) process.stdin.once(event, end);
process.stdout.on("error", end);

await mcp.connect(new StdioServerTransport());
