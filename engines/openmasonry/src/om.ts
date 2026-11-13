/**
 * The port to `om`, the only place where OpenMasonry's rules live.
 *
 * The engine never reimplements a protocol rule (Landmark VI): every capability
 * calls the `om` command line of the repository (OM_ROOT) and parses its
 * versioned JSON contracts (om.me/2, om.state/2, om.corrections/1, om.verify/1,
 * om.degree/1, om.rules/1, om.draft/1, om.drafts/1). Arguments go through execFile
 * without a shell, after strict validation, so ledger text can never become shell syntax.
 *
 * Contracts grow by additive fields under the same schema name (om.me/2 gained
 * founding_phase, canon_pending, stale, invitation, member.github_id, notices and custodian;
 * om.state/2 gained founding_phase, masters, canon_pending, invitations,
 * github_id, custodians, custodian_threshold, sunset, corrections, recoveries,
 * halt, the per-member frozen_until, room_hold_until and recovering, the
 * per-ballot stayed_until, the per-custodian removal_ballot and the per-correction
 * signers, signers_needed, notice_until, apply_until and applied); the
 * capability schemas in capabilities/ type them.
 */
import { execFile } from "node:child_process";
import { resolve } from "node:path";

export const loginPattern = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
export const ballotIdPattern = /^[a-z0-9][a-z0-9._-]{0,63}$/;
export const urlPattern = /^https?:\/\/[^\s"'`<>]{1,2000}$/;
export const sha256Pattern = /^[0-9a-f]{64}$/;

export interface OmResult {
  readonly exitCode: number;
  readonly stdout: string;
}

/**
 * One item of `om pending --json` (om.pending/1): an own signed entry not yet in
 * the ledger. `stale` means another entry took its seq; `bin/om pending --rebase
 * <seq>` re-drafts it. Otherwise the state is the pull request's (or "dropped",
 * "unknown"). The engine exposes no capability for it; the type documents the contract.
 */
export interface PendingItem {
  readonly seq: number;
  readonly type: string;
  readonly pr: string | null;
  readonly state: "stale" | "dropped" | "unknown" | "OPEN" | "MERGED" | "CLOSED";
}

/** Runs `om` with an argv list. Implementations must never use a shell. */
export interface OmPort {
  run(args: readonly string[], signal?: AbortSignal): Promise<OmResult>;
}

export class OmError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OmError";
  }
}

export interface OmRunnerOptions {
  readonly root?: string;
  /** Max concurrent `om` processes (the public endpoint uses a small number). */
  readonly maxConcurrent?: number;
  /** Cache successful read results this many milliseconds (public endpoint). 0 disables. */
  readonly cacheMs?: number;
  readonly timeoutMs?: number;
}

export function createOmRunner(options: OmRunnerOptions | string = {}): OmPort {
  const opts: OmRunnerOptions = typeof options === "string" ? { root: options } : options;
  const root = opts.root ?? process.env.OM_ROOT;
  if (!root) throw new OmError("OM_ROOT must point to a clone of openmasonry");
  const bin = resolve(root, "bin", "om");
  const max = opts.maxConcurrent ?? 4;
  const cacheMs = opts.cacheMs ?? 0;
  const timeout = opts.timeoutMs ?? 120_000;
  const cache = new Map<string, { at: number; result: OmResult }>();
  let running = 0;
  const queue: Array<() => void> = [];
  const acquire = () => new Promise<void>((go) => {
    if (running < max) { running += 1; go(); } else queue.push(() => { running += 1; go(); });
  });
  const release = () => { running -= 1; queue.shift()?.(); };

  return {
    async run(args, signal) {
      const key = JSON.stringify(args);
      const hit = cacheMs > 0 ? cache.get(key) : undefined;
      if (hit && Date.now() - hit.at < cacheMs) return hit.result;
      await acquire();
      try {
        const result = await new Promise<OmResult>((done, fail) => {
          execFile(bin, [...args], { cwd: root, shell: false, timeout, maxBuffer: 16 * 1024 * 1024, signal, encoding: "utf8" },
            (error, stdout) => {
              if (!error) return done({ exitCode: 0, stdout });
              const e = error as NodeJS.ErrnoException & { code?: unknown; killed?: boolean; signal?: string | null };
              if (typeof e.code === "number") return done({ exitCode: e.code, stdout });
              if (e.killed || e.signal) return fail(new OmError(`om took too long (over ${timeout} ms) or was stopped`));
              if (e.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER") return fail(new OmError("om returned too much output"));
              if (e.code === "ABORT_ERR") return fail(new OmError("the request was canceled"));
              fail(new OmError(`om could not run from OM_ROOT (${e.code ?? "unknown error"})`));
            });
        });
        if (cacheMs > 0 && result.exitCode === 0) cache.set(key, { at: Date.now(), result });
        return result;
      } finally {
        release();
      }
    },
  };
}

/** Parses an `om` JSON contract and checks its schema name. */
export function parseContract<T>(result: OmResult, schema: string): T {
  let data: unknown;
  try {
    data = JSON.parse(result.stdout);
  } catch {
    throw new OmError(firstLine(result.stdout) || `om returned no JSON (exit ${result.exitCode})`);
  }
  if (typeof data !== "object" || data === null || (data as { schema?: unknown }).schema !== schema) {
    throw new OmError(`om returned an unexpected contract (wanted ${schema})`);
  }
  return data as T;
}

export function firstLine(text: string): string {
  return text.split("\n").find((line) => line.trim() !== "")?.trim() ?? "";
}
