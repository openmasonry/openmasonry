/**
 * The capability layer: typed operations and the engine that calls them, with
 * no knowledge of MCP or of any transport.
 *
 * A capability pairs a zod schema for what it takes with a zod schema for what
 * it returns, a rule for who may call it, client hints, and a `run` function.
 * `engine.call` refuses rather than guesses at every stage: it parses the
 * input, checks the caller, runs, and parses the result. Whatever goes wrong
 * surfaces as a `CapabilityError` carrying one of a few fixed codes and
 * sentences. The underlying cause (an `om` message, a stack) stays attached
 * for in-process callers; the MCP adapter never forwards it.
 */
import { z } from "zod";

export type FailureCode =
  | "UNKNOWN_CAPABILITY"
  | "BAD_INPUT"
  | "NO_IDENTITY"
  | "NOT_PERMITTED"
  | "BAD_OUTPUT"
  | "CANCELED"
  | "FAILED";

/** The sentence that goes with each code. Callers may show it; it never varies. */
const SENTENCE: Readonly<Record<FailureCode, string>> = {
  UNKNOWN_CAPABILITY: "There is no capability with that id.",
  BAD_INPUT: "The arguments do not match the capability's input schema.",
  NO_IDENTITY: "This capability needs the caller's member identity.",
  NOT_PERMITTED: "The caller may not use this capability.",
  BAD_OUTPUT: "The capability produced a result outside its output schema.",
  CANCELED: "The call was canceled.",
  FAILED: "The capability could not complete.",
};

export interface Issue {
  readonly message: string;
  readonly path?: ReadonlyArray<string | number>;
}

/** What may be shown to any caller: schema issues, or which capability id was unknown. */
export type FailureDetails = { readonly issues: readonly Issue[] } | { readonly capability: string };

export class CapabilityError extends Error {
  readonly code: FailureCode;
  readonly details?: FailureDetails;

  constructor(code: FailureCode, extra: { details?: FailureDetails; cause?: unknown } = {}) {
    super(SENTENCE[code], "cause" in extra ? { cause: extra.cause } : undefined);
    this.name = "CapabilityError";
    this.code = code;
    if (extra.details) this.details = extra.details;
  }
}

/** The caller, fixed by the transport (stdio: `local:<login>`; HTTP: `anonymous`) and never read from arguments. */
export interface Principal {
  readonly id: string;
}

/** Handed to `run` beside the parsed input. */
export interface CallContext {
  readonly principal: Principal | null;
  readonly signal: AbortSignal;
}

/** Advice for MCP clients. Nothing enforces it. */
export interface Hints {
  readonly readOnly: boolean;
  readonly destructive: boolean;
  readonly idempotent: boolean;
  readonly openWorld: boolean;
}

/** `"anyone"`, or a predicate on the (possibly absent) principal. */
export type Allow = "anyone" | ((principal: Principal | null) => boolean);

export interface Capability<I extends z.ZodType = z.ZodType, O extends z.ZodType = z.ZodType> {
  readonly title: string;
  readonly description: string;
  readonly input: I;
  readonly output: O;
  readonly allow: Allow;
  readonly hints: Hints;
  run(input: z.output<I>, call: CallContext): z.input<O> | Promise<z.input<O>>;
}

/** Returns its argument unchanged; it exists so TypeScript infers the schema types. */
export function declareCapability<I extends z.ZodType, O extends z.ZodType>(spec: Capability<I, O>): Capability<I, O> {
  return spec;
}

/** One row of `engine.catalog()`. */
export interface CatalogEntry {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly hints: Hints;
}

/** `engine.detail(id)`: the row plus both JSON Schemas. */
export interface CatalogDetail extends CatalogEntry {
  readonly inputSchema: Record<string, unknown>;
  readonly outputSchema: Record<string, unknown>;
}

export interface CallOptions {
  readonly principal?: Principal | null;
  readonly signal?: AbortSignal;
}

// `any` only widens the capability map's static types; `call` still parses every value at run time.
type SomeCapability = Capability<any, any>;

export interface Engine<M extends Record<string, SomeCapability> = Record<string, SomeCapability>> {
  readonly name: string;
  readonly version: string;
  catalog(): CatalogEntry[];
  detail(id: string): CatalogDetail;
  call<K extends keyof M & string>(id: K, input: unknown, options?: CallOptions): Promise<z.output<M[K]["output"]>>;
}

/** Draft 2020-12 JSON Schema for one side of a capability. MCP accepts only an object at the root. */
function toSchema(id: string, side: "input" | "output", schema: z.ZodType): Record<string, unknown> {
  const json = z.toJSONSchema(schema, { target: "draft-2020-12", io: side }) as Record<string, unknown>;
  if (json.type === "object") return json;
  throw new TypeError(`${id}: the ${side} schema needs an object root`);
}

async function parseWith<S extends z.ZodType>(schema: S, value: unknown, code: "BAD_INPUT" | "BAD_OUTPUT"): Promise<z.output<S>> {
  let parsed: z.ZodSafeParseResult<z.output<S>>;
  try {
    parsed = await schema.safeParseAsync(value);
  } catch (cause) {
    throw new CapabilityError(code, { cause });
  }
  if (parsed.success) return parsed.data;
  const issues = parsed.error.issues.map((issue): Issue => {
    const where = issue.path.map((key) => (typeof key === "number" ? key : String(key)));
    return where.length > 0 ? { message: issue.message, path: where } : { message: issue.message };
  });
  throw new CapabilityError(code, { details: { issues }, cause: parsed.error });
}

/** Accepts no principal, or one with a non-empty string id; anything else is refused. */
function checkedPrincipal(candidate: Principal | null | undefined): Principal | null {
  if (candidate == null) return null;
  const ok = typeof candidate === "object" && typeof candidate.id === "string" && candidate.id.length > 0;
  if (!ok) throw new CapabilityError("NO_IDENTITY");
  return Object.freeze({ id: candidate.id });
}

/** Settles with `work`, or with CANCELED the moment `signal` fires, whichever comes first. */
function untilAborted<T>(work: () => T | Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(new CapabilityError("CANCELED", { cause: signal.reason }));
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(new CapabilityError("CANCELED", { cause: signal.reason }));
    signal.addEventListener("abort", onAbort, { once: true });
    Promise.resolve()
      .then(work)
      .then(resolve, reject)
      .finally(() => signal.removeEventListener("abort", onAbort));
  });
}

export function assembleEngine<M extends Record<string, SomeCapability>>(spec: {
  readonly name: string;
  readonly version: string;
  readonly capabilities: M;
}): Engine<M> {
  const byId = new Map<string, SomeCapability>(Object.entries(spec.capabilities));
  const details = new Map<string, CatalogDetail>();
  for (const [id, cap] of byId) {
    const detail: CatalogDetail = {
      id,
      title: cap.title,
      description: cap.description,
      hints: Object.freeze({ ...cap.hints }),
      inputSchema: toSchema(id, "input", cap.input),
      outputSchema: toSchema(id, "output", cap.output),
    };
    details.set(id, Object.freeze(detail));
  }
  const unknown = (id: string) => new CapabilityError("UNKNOWN_CAPABILITY", { details: { capability: id } });

  return {
    name: spec.name,
    version: spec.version,
    catalog() {
      return Array.from(details.values(), (d) => ({ id: d.id, title: d.title, description: d.description, hints: d.hints }));
    },
    detail(id) {
      const found = details.get(id);
      if (!found) throw unknown(id);
      return structuredClone(found);
    },
    async call(id, raw, options = {}) {
      const signal = options.signal ?? new AbortController().signal;
      try {
        const cap = byId.get(id);
        if (!cap) throw unknown(id);
        const input = structuredClone(await parseWith(cap.input, raw, "BAD_INPUT"));
        const principal = checkedPrincipal(options.principal);
        const permitted = cap.allow === "anyone" || cap.allow(principal) === true;
        if (!permitted) throw new CapabilityError(principal ? "NOT_PERMITTED" : "NO_IDENTITY");
        const context: CallContext = Object.freeze({ principal, signal });
        const result = await untilAborted(() => cap.run(input, context), signal);
        return await parseWith(cap.output, result, "BAD_OUTPUT");
      } catch (error) {
        if (error instanceof CapabilityError) throw error;
        throw new CapabilityError(signal.aborted ? "CANCELED" : "FAILED", { cause: error });
      }
    },
  };
}
