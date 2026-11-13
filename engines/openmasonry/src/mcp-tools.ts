/**
 * Publishes an engine as MCP tools through the official SDK, one tool per capability.
 *
 * A tool is named after its capability id, with each character outside
 * [A-Za-z0-9_-] turned into `_` (`entry.draft` becomes `entry_draft`). Success
 * carries the parsed result twice: as `structuredContent` and as JSON text.
 * Failure sets `isError` and carries only `{ code, message, details? }`, so the
 * cause behind it (an `om` message, a stack) stays on this side.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  type CallToolResult,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";

import { CapabilityError, type Engine, type Principal } from "./capability.js";

const NAME_LIMIT = 64;

export function mcpToolName(capability: string): string {
  return capability.replace(/[^A-Za-z0-9_-]/g, "_");
}

/** The tool list of one engine, and the way back from a tool name to its capability. */
export interface ToolIndex {
  readonly tools: readonly Tool[];
  capabilityOf(tool: string): string | undefined;
}

/** Computed once per engine. Two capabilities that map to one name, or a name over the limit, are a build error. */
export function indexTools(engine: Engine): ToolIndex {
  const owner = new Map<string, string>();
  const tools: Tool[] = [];
  for (const { id } of engine.catalog()) {
    const name = mcpToolName(id);
    const clash = owner.get(name);
    if (clash !== undefined) throw new TypeError(`${clash} and ${id} would both be published as ${name}`);
    if (name.length < 1 || name.length > NAME_LIMIT) throw new TypeError(`${id}: a tool name must have 1 to ${NAME_LIMIT} characters`);
    owner.set(name, id);
    const { description, inputSchema, outputSchema, title, hints } = engine.detail(id);
    tools.push({
      name,
      description,
      inputSchema: inputSchema as Tool["inputSchema"],
      outputSchema: outputSchema as Tool["outputSchema"],
      title,
      annotations: {
        readOnlyHint: hints.readOnly,
        destructiveHint: hints.destructive,
        idempotentHint: hints.idempotent,
        openWorldHint: hints.openWorld,
      },
    });
  }
  return Object.freeze({ tools: Object.freeze(tools), capabilityOf: (tool: string) => owner.get(tool) });
}

/** The only thing a client learns about a failure. */
function failure(error: unknown): CallToolResult {
  const known = error instanceof CapabilityError ? error : new CapabilityError("FAILED");
  const body = known.details === undefined
    ? { code: known.code, message: known.message }
    : { code: known.code, message: known.message, details: known.details };
  return { isError: true, content: [{ type: "text", text: JSON.stringify(body) }] };
}

export interface ToolServerOptions {
  /** Set once by the transport for the whole connection; no request can change it. */
  readonly principal: Principal | null;
  /** Fires when the HTTP request this server answers goes away; it cancels every call in flight. */
  readonly signal?: AbortSignal;
}

export function toolServer(engine: Engine, options: ToolServerOptions, index: ToolIndex = indexTools(engine)): Server {
  const identity = { name: engine.name, version: engine.version };
  const mcp = new Server(identity, { capabilities: { tools: {} } });
  mcp.setRequestHandler(ListToolsRequestSchema, () => ({ tools: [...index.tools] }));
  mcp.setRequestHandler(CallToolRequestSchema, async ({ params }, extra): Promise<CallToolResult> => {
    const capability = index.capabilityOf(params.name);
    if (capability === undefined) throw new McpError(ErrorCode.InvalidParams, `Tool ${params.name} not found`);
    const signal = options.signal ? AbortSignal.any([extra.signal, options.signal]) : extra.signal;
    try {
      const output = await engine.call(capability, params.arguments ?? {}, { principal: options.principal, signal });
      const structured = output as Record<string, unknown>;
      return { content: [{ type: "text", text: JSON.stringify(structured) }], structuredContent: structured };
    } catch (error) {
      return failure(error);
    }
  });
  return mcp;
}
