/**
 * Prints the JSON entry that registers the local stdio server with an MCP
 * client, in the usual `mcpServers` shape. It writes no file: the person pastes
 * the entry into their client's configuration.
 *
 * OM_ROOT defaults to the repository this engine lives in. OM_LOGIN, OM_KEY and
 * OM_HOME are passed on when the current environment sets them.
 */
import { fileURLToPath } from "node:url";

const here = (relative: string) => fileURLToPath(new URL(relative, import.meta.url));

const env: Record<string, string> = { OM_ROOT: process.env.OM_ROOT || here("../../..").replace(/\/$/, "") };
for (const key of ["OM_LOGIN", "OM_KEY", "OM_HOME"]) {
  const set = process.env[key];
  if (set) env[key] = set;
}

const servers = { openmasonry: { command: process.execPath, args: [here("./serve-stdio.js")], env } };
process.stdout.write(`${JSON.stringify({ mcpServers: servers }, null, 2)}\n`);
