/**
 * MCP over Streamable HTTP, stateless, on node:http and the official SDK.
 *
 * The gate runs before a single body byte is read. A request passes only with
 * exactly one Host header naming an allowed host (by default the loopback
 * names; a bind elsewhere must list its hosts), no Origin or an allowed one
 * (none by default), the path `/mcp` spelled plainly, the POST method, a
 * declared length within the limit, an Accept that takes both JSON and SSE,
 * and one JSON Content-Type. The body is then read up to the limit, decoded as
 * strict UTF-8 and parsed as one JSON-RPC message (a batch is refused). Every
 * request gets its own SDK server and transport, with no session, answering in
 * JSON. A client that hangs up cancels its calls.
 *
 * Rate limiting is not done here: put a reverse proxy in front of a public bind.
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";

import type { Engine, Principal } from "./capability.js";
import { indexTools, toolServer } from "./mcp-tools.js";

const ENDPOINT = "/mcp";
const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]"]);

export interface HttpOptions {
  /** Interface to bind; `127.0.0.1` when omitted. */
  readonly host?: string;
  /** TCP port; `3000` when omitted, `0` for any free port. */
  readonly port?: number;
  /** Host header values to serve. Must be given when `host` is not a loopback address. */
  readonly hosts?: readonly string[];
  /** Browser origins to serve. When omitted, every request that carries an Origin is refused. */
  readonly origins?: readonly string[];
  /** Largest request body in bytes; 1 MiB when omitted. */
  readonly bodyLimit?: number;
  /** Who every request acts as. The public endpoint is anonymous on purpose. */
  readonly principal: Principal | null;
}

export interface HttpEndpoint {
  address(): { readonly host: string; readonly port: number };
  close(): Promise<void>;
}

/**
 * The lower-case host name of `host` or `host:port`, or null for anything that
 * carries more than that (credentials, a path, a query, a fragment).
 */
export function bareHostname(authority: string): string | null {
  if (authority === "::1") return "[::1]";
  let url: URL;
  try {
    url = new URL(`http://${authority}`);
  } catch {
    return null;
  }
  const extra = url.username || url.password || url.search || url.hash || (url.pathname === "/" ? "" : url.pathname);
  return extra ? null : url.hostname.toLowerCase();
}

export function isLoopbackHost(host: string): boolean {
  const name = bareHostname(host);
  return name !== null && LOOPBACK.has(name);
}

/** The serialized origin of an http(s) URL that is nothing but an origin, else null. */
export function bareOrigin(text: string): string | null {
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  const web = url.protocol === "http:" || url.protocol === "https:";
  const extra = url.username || url.password || url.search || url.hash || (url.pathname === "/" ? "" : url.pathname);
  return web && !extra && url.origin !== "null" ? url.origin : null;
}

interface Gate {
  readonly host: string;
  readonly port: number;
  readonly bodyLimit: number;
  readonly hosts: ReadonlySet<string>;
  readonly origins: ReadonlySet<string> | null;
}

/** Turns the options into the gate's fixed sets, or throws before anything listens. */
function buildGate(options: HttpOptions): Gate {
  const host = options.host ?? "127.0.0.1";
  const bodyLimit = options.bodyLimit ?? 1_048_576;
  if (!Number.isSafeInteger(bodyLimit) || bodyLimit < 1) throw new TypeError("bodyLimit: expected a whole number of bytes, at least 1");
  if (options.hosts === undefined && !isLoopbackHost(host)) {
    throw new TypeError("a non-loopback bind needs an explicit Host allowlist (hosts)");
  }

  const hostList = options.hosts ?? [...LOOPBACK, host];
  const hosts = new Set(hostList.map((entry) => bareHostname(entry)));
  if (hosts.has(null)) throw new TypeError("hosts: every entry must be a plain host name, optionally with a port");
  if (hosts.size === 0) throw new TypeError("hosts: the list is empty");

  let origins: Set<string | null> | null = null;
  if (options.origins !== undefined) {
    origins = new Set(options.origins.map((entry) => bareOrigin(entry)));
    if (origins.has(null)) throw new TypeError("origins: every entry must be an http or https origin with nothing after it");
    if (origins.size === 0) throw new TypeError("origins: the list is empty");
  }
  return {
    host,
    port: options.port ?? 3000,
    bodyLimit,
    hosts: hosts as Set<string>,
    origins: origins as Set<string> | null,
  };
}

/** How often a header occurs on the wire (Node folds repeats into one value). */
function occurrences(request: IncomingMessage, header: string): number {
  return request.rawHeaders.filter((value, index) => index % 2 === 0 && value.toLowerCase() === header).length;
}

/** The Host header's name, refusing an IPv6 literal without brackets (it cannot be told apart from a port). */
function hostOfRequest(header: string): string | null {
  const colons = header.length - header.replaceAll(":", "").length;
  return colons > 1 && header[0] !== "[" ? null : bareHostname(header);
}

/** True only for a plain absolute path: no query, fragment, percent escape, dot segment or leading `//`. */
function isPlainPath(target: string): boolean {
  if (target[0] !== "/" || target.startsWith("//") || target.includes("%")) return false;
  try {
    const url = new URL(target, "http://gate.invalid");
    return url.pathname === target && !url.search && !url.hash;
  } catch {
    return false;
  }
}

const QUALITY = /^(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)$/;

/** Whether an Accept header takes `type` with a nonzero weight. A range with a malformed or repeated `q` takes nothing. */
function takes(accept: string | undefined, type: string): boolean {
  if (accept === undefined) return false;
  for (const range of accept.split(",")) {
    const [name = "", ...params] = range.split(";");
    if (name.trim().toLowerCase() !== type) continue;
    const weights: string[] = [];
    for (const param of params) {
      const eq = param.indexOf("=");
      if (eq !== -1 && param.slice(0, eq).trim().toLowerCase() === "q") weights.push(param.slice(eq + 1).trim());
    }
    if (weights.length > 1) continue;
    const weight = weights[0] ?? "1";
    if (QUALITY.test(weight) && Number(weight) > 0) return true;
  }
  return false;
}

function exceedsDeclared(request: IncomingMessage, limit: number): boolean {
  const declared = request.headers["content-length"];
  return typeof declared === "string" && /^\d+$/.test(declared) && BigInt(declared) > BigInt(limit);
}

function reply(response: ServerResponse, status: number, payload: unknown, headers: Record<string, string> = {}): void {
  response.writeHead(status, { ...headers, "content-type": "application/json" });
  response.end(JSON.stringify(payload));
}

/**
 * Replies without consuming the body and drops the connection afterwards, so
 * bytes the server never read cannot be taken for the start of a new request.
 */
function turnAway(request: IncomingMessage, response: ServerResponse, status: number, payload: unknown, headers: Record<string, string> = {}): void {
  response.shouldKeepAlive = false;
  request.on("error", () => {});
  request.resume();
  response.on("finish", () => {
    if (!request.complete && !request.destroyed) request.destroy();
  });
  reply(response, status, payload, { ...headers, connection: "close" });
}

const jsonRpcError = (code: number, message: string) => ({ jsonrpc: "2.0", id: null, error: { code, message } });

type Body = { readonly text: string } | { readonly problem: "too-large" | "not-utf8" };

/** Collects the body as strict UTF-8, giving up the moment it passes `limit` bytes. */
function collectBody(request: IncomingMessage, limit: number): Promise<Body> {
  return new Promise((resolve, reject) => {
    const utf8 = new TextDecoder("utf-8", { fatal: true });
    const parts: string[] = [];
    let size = 0;
    let finished = false;

    const handlers = {
      data(chunk: Buffer) {
        if (finished) return;
        size += chunk.byteLength;
        if (size > limit) return giveUp("too-large");
        try {
          parts.push(utf8.decode(chunk, { stream: true }));
        } catch {
          giveUp("not-utf8");
        }
      },
      end() {
        if (finished) return;
        settle();
        try {
          parts.push(utf8.decode());
        } catch {
          return resolve({ problem: "not-utf8" });
        }
        resolve({ text: parts.join("") });
      },
      error(error: Error) {
        if (finished) return;
        settle();
        reject(error);
      },
      aborted() {
        handlers.error(new Error("the client closed the request"));
      },
    };
    const settle = () => {
      finished = true;
      request.off("data", handlers.data).off("end", handlers.end).off("error", handlers.error).off("aborted", handlers.aborted);
    };
    // The rest of the body is drained and dropped; the caller answers and closes the connection.
    const giveUp = (problem: "too-large" | "not-utf8") => {
      settle();
      request.on("error", () => {});
      request.resume();
      resolve({ problem });
    };

    if (request.destroyed) return handlers.aborted();
    request.on("data", handlers.data).once("end", handlers.end).once("error", handlers.error).once("aborted", handlers.aborted);
  });
}

/** The request headers for the SDK, with Accept and Content-Type rewritten to the forms the gate has already checked. */
function sdkHeaders(request: IncomingMessage): Headers {
  const forwarded = new Headers();
  for (const [name, value] of Object.entries(request.headers)) {
    for (const item of [value ?? []].flat()) forwarded.append(name, item);
  }
  forwarded.set("accept", "application/json, text/event-stream");
  forwarded.set("content-type", "application/json");
  return forwarded;
}

export async function listenHttp(engine: Engine, options: HttpOptions): Promise<HttpEndpoint> {
  const gate = buildGate(options);
  const index = indexTools(engine);
  const inFlight = new Set<AbortController>();
  const FORBIDDEN = { error: "forbidden" };

  async function answer(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const host = request.headers.host;
    if (host === undefined || occurrences(request, "host") !== 1) return turnAway(request, response, 403, FORBIDDEN);
    const hostname = hostOfRequest(host);
    if (hostname === null || !gate.hosts.has(hostname)) return turnAway(request, response, 403, FORBIDDEN);

    const origin = request.headers.origin;
    if (origin !== undefined) {
      const normalized = bareOrigin(origin);
      if (normalized === null || gate.origins === null || !gate.origins.has(normalized)) return turnAway(request, response, 403, FORBIDDEN);
    }

    const target = request.url ?? "/";
    if (!isPlainPath(target)) return turnAway(request, response, 400, { error: "invalid_request_target" });
    if (target !== ENDPOINT) return turnAway(request, response, 404, { error: "not_found" });
    if (request.method !== "POST") return turnAway(request, response, 405, { error: "method_not_allowed" }, { allow: "POST" });
    if (exceedsDeclared(request, gate.bodyLimit)) return turnAway(request, response, 413, { error: "payload_too_large" });

    const accept = request.headers.accept;
    if (!(takes(accept, "application/json") && takes(accept, "text/event-stream"))) {
      return turnAway(request, response, 406, jsonRpcError(-32000, "Not Acceptable: Client must accept both application/json and text/event-stream"));
    }
    const mediaType = request.headers["content-type"]?.split(";", 1)[0]?.trim().toLowerCase();
    if (occurrences(request, "content-type") !== 1 || mediaType !== "application/json") {
      return turnAway(request, response, 415, jsonRpcError(-32000, "Unsupported Media Type: Content-Type must be application/json"));
    }

    const cancel = new AbortController();
    inFlight.add(cancel);
    request.once("aborted", () => cancel.abort());
    response.once("finish", () => inFlight.delete(cancel));
    response.once("close", () => {
      inFlight.delete(cancel);
      if (!response.writableEnded) cancel.abort();
    });

    const mcp = toolServer(engine, { principal: options.principal, signal: cancel.signal }, index);
    let consumed = false;
    try {
      const body = await collectBody(request, gate.bodyLimit);
      if ("problem" in body) {
        return body.problem === "too-large"
          ? turnAway(request, response, 413, { error: "payload_too_large" })
          : turnAway(request, response, 400, jsonRpcError(-32700, "Parse error: Invalid UTF-8"));
      }
      consumed = true;
      let message: unknown;
      try {
        message = JSON.parse(body.text);
      } catch {
        return reply(response, 400, jsonRpcError(-32700, "Parse error: Invalid JSON"));
      }
      if (Array.isArray(message)) return reply(response, 400, jsonRpcError(-32600, "Invalid Request: Exactly one JSON-RPC message is required"));

      const transport = new WebStandardStreamableHTTPServerTransport({ enableJsonResponse: true });
      await mcp.connect(transport);
      const sdkRequest = new Request(new URL(ENDPOINT, `http://${host}`).href, { method: "POST", headers: sdkHeaders(request), signal: cancel.signal });
      const result = await transport.handleRequest(sdkRequest, { parsedBody: message });
      const payload = Buffer.from(await result.arrayBuffer());
      response.writeHead(result.status, Object.fromEntries(result.headers));
      response.end(payload);
    } catch {
      if (response.headersSent || response.destroyed) return;
      const internal = jsonRpcError(-32603, "Internal server error");
      if (consumed) reply(response, 500, internal);
      else turnAway(request, response, 500, internal);
    } finally {
      await mcp.close().catch(() => {});
    }
  }

  const listener = createServer((request, response) => {
    answer(request, response).catch(() => {
      if (!response.headersSent && !response.destroyed) turnAway(request, response, 500, { error: "internal_error" });
      else if (!response.destroyed) response.destroy();
    });
  });

  await new Promise<void>((resolve, reject) => {
    listener.once("error", reject).listen(gate.port, gate.host, () => {
      listener.off("error", reject);
      resolve();
    });
  });
  const bound = listener.address();
  const address = Object.freeze({ host: gate.host, port: bound !== null && typeof bound === "object" ? bound.port : gate.port });

  let stopping: Promise<void> | undefined;
  const close = () => {
    // Bounded on its own: calls in flight are canceled and every socket is closed, so nothing waits on a drain.
    stopping ??= new Promise<void>((resolve, reject) => {
      listener.close((error) => (error ? reject(error) : resolve()));
      for (const cancel of inFlight) cancel.abort(new Error("the HTTP endpoint is shutting down"));
      listener.closeAllConnections();
    });
    return stopping;
  };
  return Object.freeze({ address: () => address, close });
}
