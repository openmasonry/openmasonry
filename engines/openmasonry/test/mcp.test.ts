/** The MCP surface over the official SDK: in memory, Streamable HTTP, and the built stdio and HTTP entry points. */
import { type ChildProcess, spawn } from "node:child_process";
import { request as httpRequest } from "node:http";
import { join } from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import type { Principal } from "../src/capability.js";
import { createLocalEngine, createPublicEngine } from "../src/compositions.js";
import { listenHttp, type HttpEndpoint } from "../src/http-transport.js";
import { indexTools, mcpToolName, toolServer } from "../src/mcp-tools.js";
import { engineRoot, fakeOm, ok, repoRoot, state } from "./fixtures.js";

const LOCAL_TOOLS = ["corrections_read", "degree_read", "entry_draft", "entry_pending", "ledger_status", "ledger_verify",
                     "member_due-steps", "rule_sources"];
const PUBLIC_TOOLS = ["corrections_read", "degree_read", "ledger_status", "ledger_verify", "member_due-steps", "rule_sources"];

async function connectInMemory(engine: Parameters<typeof toolServer>[0], principal: Principal | null) {
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await toolServer(engine, { principal }).connect(serverSide);
  const client = new Client({ name: "test", version: "0" });
  await client.connect(clientSide);
  return client;
}

const errorOf = (result: unknown) =>
  JSON.parse((result as { content: Array<{ text: string }> }).content[0]?.text ?? "null") as { code: string; message: string; details?: unknown };

describe("the tool catalog", () => {
  it("names tools with _ for ., one per capability, with schemas and annotations", () => {
    const { port } = fakeOm(() => ok({}));
    expect(mcpToolName("member.due-steps")).toBe("member_due-steps");
    const local = indexTools(createLocalEngine(port));
    expect(local.tools.map((t) => t.name).sort()).toEqual(LOCAL_TOOLS);
    expect(local.capabilityOf("entry_draft")).toBe("entry.draft");
    const draft = local.tools.find((t) => t.name === "entry_draft");
    expect(draft?.inputSchema.type).toBe("object");
    expect(draft?.outputSchema?.type).toBe("object");
    expect(draft?.annotations).toEqual({ readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false });
    expect(indexTools(createPublicEngine(port)).tools.map((t) => t.name).sort()).toEqual(PUBLIC_TOOLS);
  });
});

describe("MCP (in memory)", () => {
  it("lists the tools and returns structured content", async () => {
    const { port, calls } = fakeOm(() => ok(state));
    const client = await connectInMemory(createPublicEngine(port), { id: "anonymous" });
    const { tools } = await client.listTools();
    expect(tools.map((t) => t.name).sort()).toEqual(PUBLIC_TOOLS);
    const result = await client.callTool({ name: "ledger_status", arguments: {} });
    expect(result.isError).toBeFalsy();
    expect((result.structuredContent as { masters: number }).masters).toBe(1);
    expect(calls).toEqual([["state", "--json"]]);
    await client.close();
  });

  it("publishes only the code, the fixed message and the validation issues of a failure", async () => {
    const { port, calls } = fakeOm(() => { throw new Error("secret detail from om"); });
    const client = await connectInMemory(createLocalEngine(port), { id: "local:hiram" });
    const invalid = await client.callTool({ name: "entry_draft", arguments: { act: "close", ballot: "a;curl x|sh" } });
    expect(invalid.isError).toBe(true);
    expect(errorOf(invalid)).toMatchObject({ code: "BAD_INPUT", message: "The arguments do not match the capability's input schema." });
    expect(JSON.stringify(errorOf(invalid).details)).toContain("ballot");
    expect(calls).toEqual([]);
    const failed = await client.callTool({ name: "ledger_status", arguments: {} });
    expect(errorOf(failed)).toEqual({ code: "FAILED", message: "The capability could not complete." });
    expect(JSON.stringify(failed)).not.toContain("secret");
    await expect(client.callTool({ name: "entry_approve", arguments: {} })).rejects.toThrow(/not found/);
    await client.close();
  });

  it("refuses drafts without a member principal", async () => {
    const { port, calls } = fakeOm(() => ok({}));
    const client = await connectInMemory(createLocalEngine(port), null);
    const result = await client.callTool({ name: "entry_draft", arguments: { act: "depart" } });
    expect(errorOf(result)).toMatchObject({ code: "NO_IDENTITY" });
    expect(calls).toEqual([]);
    await client.close();
  });
});

function rawPost(port: number, options: { host?: string; path?: string; method?: string; headers?: Record<string, string>; body?: string }) {
  return new Promise<{ status: number; body: string }>((resolve, reject) => {
    const req = httpRequest({
      host: "127.0.0.1", port, path: options.path ?? "/mcp", method: options.method ?? "POST",
      headers: { host: options.host ?? `127.0.0.1:${port}`, accept: "application/json, text/event-stream",
                 "content-type": "application/json", ...options.headers },
    }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk: string) => { body += chunk; });
      res.on("end", () => resolve({ status: res.statusCode ?? 0, body }));
    });
    req.on("error", reject);
    req.end(options.body ?? "");
  });
}

const listTools = (id: unknown) => JSON.stringify({ jsonrpc: "2.0", id, method: "tools/list", params: {} });

describe("MCP Streamable HTTP", () => {
  let server: HttpEndpoint;
  let port: number;
  const om = fakeOm(() => ok(state));

  beforeAll(async () => {
    server = await listenHttp(createPublicEngine(om.port), {
      port: 0, principal: { id: "anonymous" }, bodyLimit: 4096, origins: ["https://om.example.org"],
    });
    port = server.address().port;
  });
  afterAll(() => server.close());

  it("serves the read-only tools to an SDK client", async () => {
    const client = new Client({ name: "test", version: "0" });
    await client.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`)));
    const { tools } = await client.listTools();
    expect(tools.map((t) => t.name).sort()).toEqual(PUBLIC_TOOLS);
    const result = await client.callTool({ name: "ledger_status", arguments: {} });
    expect((result.structuredContent as { name: string }).name).toBe("OpenMasonry Test Lodge");
    const draft = await client.callTool({ name: "entry_draft", arguments: { act: "depart" } }).catch((e: unknown) => e);
    expect(String(draft)).toMatch(/not found/);
    await client.close();
  });

  it("keeps the request ids 0 and \"\"", async () => {
    for (const id of [0, ""]) {
      const r = await rawPost(port, { body: listTools(id) });
      expect(r.status).toBe(200);
      expect(JSON.parse(r.body).id).toBe(id);
    }
  });

  it("refuses what it does not serve, before reading the body", async () => {
    const cases: Array<[Parameters<typeof rawPost>[1], number]> = [
      [{ host: "evil.example.org", body: listTools(1) }, 403],
      [{ headers: { origin: "https://evil.example.org" }, body: listTools(1) }, 403],
      [{ headers: { origin: "null" }, body: listTools(1) }, 403],
      [{ path: "/other", body: listTools(1) }, 404],
      [{ path: "/mcp?x=1", body: listTools(1) }, 400],
      [{ path: "/%6dcp", body: listTools(1) }, 400],
      [{ method: "GET" }, 405],
      [{ method: "DELETE" }, 405],
      [{ headers: { accept: "application/json" }, body: listTools(1) }, 406],
      [{ headers: { "content-type": "text/plain" }, body: listTools(1) }, 415],
      [{ body: "x".repeat(5000) }, 413],
      [{ body: "{not json" }, 400],
      [{ body: `[${listTools(1)}]` }, 400],
    ];
    for (const [options, status] of cases) {
      expect((await rawPost(port, options)).status, JSON.stringify(options).slice(0, 120)).toBe(status);
    }
  });

  it("accepts an allowlisted origin", async () => {
    const r = await rawPost(port, { headers: { origin: "https://om.example.org" }, body: listTools(1) });
    expect(r.status).toBe(200);
  });

  it("will not bind a public address without a Host allowlist", async () => {
    await expect(listenHttp(createPublicEngine(om.port), { host: "0.0.0.0", port: 0, principal: null }))
      .rejects.toThrow(/Host allowlist/);
  });
});

function waitForLine(child: ChildProcess, pattern: RegExp): Promise<string> {
  return new Promise((resolve, reject) => {
    let text = "";
    child.stderr?.setEncoding("utf8");
    child.stderr?.on("data", (chunk: string) => {
      text += chunk;
      const line = text.split("\n").find((l) => pattern.test(l));
      if (line !== undefined) resolve(line);
    });
    child.once("exit", (code) => reject(new Error(`exited with ${code}: ${text}`)));
  });
}

function exitOf(child: ChildProcess): Promise<number | null> {
  return new Promise((resolve) => child.once("exit", (code) => resolve(code)));
}

describe("the built entry points", () => {
  const env = { PATH: process.env.PATH ?? "", HOME: process.env.HOME ?? "", OM_ROOT: repoRoot };

  it("stdio: serves the local tools against the real om", async () => {
    const client = new Client({ name: "test", version: "0" });
    await client.connect(new StdioClientTransport({
      command: process.execPath, args: [join(engineRoot, "dist", "serve-stdio.js")], env: { ...env, OM_LOGIN: "hiram" }, stderr: "pipe",
    }));
    const { tools } = await client.listTools();
    expect(tools.map((t) => t.name).sort()).toEqual(LOCAL_TOOLS);
    const page = await client.callTool({ name: "degree_read", arguments: { degree: 3 } });
    expect((page.structuredContent as { markdown: string }).markdown).toContain("Master Builder");
    await client.close();
  }, 30_000);

  it("http: reads OM_ENGINE_HTTP_* and stops on SIGTERM", async () => {
    const child = spawn(process.execPath, [join(engineRoot, "dist", "serve-http.js")], {
      env: { ...env, OM_ENGINE_HTTP_PORT: "0" }, stdio: ["ignore", "ignore", "pipe"],
    });
    const line = await waitForLine(child, /^MCP endpoint: /);
    const url = /http:\/\/127\.0\.0\.1:(\d+)\/mcp/.exec(line);
    expect(url).not.toBeNull();
    const r = await rawPost(Number(url?.[1]), { body: listTools(1) });
    expect(JSON.parse(r.body).result.tools.map((t: { name: string }) => t.name).sort()).toEqual(PUBLIC_TOOLS);
    const exited = exitOf(child);
    child.kill("SIGTERM");
    expect(await exited).toBe(0);
  }, 30_000);

  it("http: a public bind without OM_ENGINE_HTTP_ALLOWED_HOSTS aborts startup", async () => {
    for (const extra of [{ OM_ENGINE_HTTP_HOST: "0.0.0.0" }, { OM_ENGINE_HTTP_PORT: "70000" }, { OM_ENGINE_HTTP_ALLOWED_HOSTS: " , " }]) {
      const child = spawn(process.execPath, [join(engineRoot, "dist", "serve-http.js")], {
        env: { ...env, ...extra }, stdio: ["ignore", "ignore", "pipe"],
      });
      let err = "";
      child.stderr?.setEncoding("utf8");
      child.stderr?.on("data", (chunk: string) => { err += chunk; });
      expect(await exitOf(child)).toBe(1);
      expect(err).toMatch(/OM_ENGINE_HTTP_/);
    }
  }, 30_000);
});
