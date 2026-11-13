/**
 * entry.draft — LOCAL ONLY. Prepares an act; never signs it.
 *
 * It runs the matching `om` command, which checks the act against the protocol
 * and stores the exact entry under the person's ~/.config/openmasonry/pending.
 * Only `bin/om approve <digest>`, confirmed by the person in a system dialog,
 * signs it and opens the pull request. There is no approve capability: the
 * engine cannot sign, by construction.
 *
 * The acts are a member's own. `object` (a Master Builder objects to a correction)
 * is the only one that touches corrections; the custodian acts and the key
 * recovery are not exposed here at all.
 */
import { declareCapability } from "../capability.js";
import { z } from "zod";

import { ballotIdPattern, firstLine, loginPattern, type OmPort, sha256Pattern, urlPattern } from "../om.js";

export { draftPending };
import { loginFromPrincipal } from "./read.js";

const login = z.string().regex(loginPattern);
const ballot = z.string().regex(ballotIdPattern);
const degree = z.number().int().min(1).max(33);
const url = z.string().regex(urlPattern);

/** Act names follow the Guide's step actions (`member.due-steps` → `steps[].action`). */
const ACTS = {
  join: [], invite: ["candidate"], sponsor: ["candidate"], vote: ["ballot"], reveal: ["ballot"],
  open_admission: ["candidate"], advance: [], open_sanction: ["member", "measure"],
  open_amendment: ["path", "sha256"], close: ["ballot"], exam: ["degree", "work_url"],
  report: ["candidate", "degree", "verdict"], recuse: ["candidate", "degree"], draw: [], call_council: [],
  work: ["work_url"], depart: [], object: ["correction"],
} as const satisfies Record<string, readonly string[]>;

const OPTIONAL: Partial<Record<keyof typeof ACTS, readonly string[]>> = {
  draw: ["candidate"], report: ["reason"], invite: ["github_id"],
};

type Act = keyof typeof ACTS;

/** One object root (MCP tools need it); which fields each act requires is checked below. */
export const draftInput = z
  .object({
    act: z.enum(Object.keys(ACTS) as [Act, ...Act[]]),
    candidate: login.optional(),
    /** invite: the numeric GitHub user id of the invited login (looked up by `om` when absent). */
    github_id: z.number().int().positive().max(Number.MAX_SAFE_INTEGER).optional(),
    member: login.optional(),
    ballot: ballot.optional(),
    measure: z.enum(["admonish", "suspend", "expel", "expel_for_fraud", "reinstate"]).optional(),
    path: z.string().regex(/^(?:@protocol|[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}(?:\/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}){0,9})$/).optional(),
    sha256: z.string().regex(sha256Pattern).optional(),
    degree: degree.optional(),
    work_url: url.optional(),
    verdict: z.enum(["pass", "fail"]).optional(),
    reason: url.optional(),
    /** object: the entry number (seq) of the correction the Master Builder objects to. */
    correction: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER).optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    const required: readonly string[] = ACTS[value.act];
    const optional: readonly string[] = OPTIONAL[value.act] ?? [];
    for (const name of required) {
      if ((value as Record<string, unknown>)[name] === undefined) {
        ctx.addIssue({ code: "custom", path: [name], message: `${value.act} needs ${name}` });
      }
    }
    for (const name of Object.keys(value)) {
      if (name !== "act" && !required.includes(name) && !optional.includes(name)) {
        ctx.addIssue({ code: "custom", path: [name], message: `${value.act} does not take ${name}` });
      }
    }
  });

export type DraftInput = z.infer<typeof draftInput>;

/** The argv for each act. Every value has passed a strict pattern; no shell is ever involved. */
export function draftArgv(i: DraftInput, self: string): string[] {
  const f = (name: Exclude<keyof DraftInput, "act">): string => {
    const value = i[name];
    if (value === undefined) throw new Error(`${i.act} needs ${name}`); // unreachable after validation
    return String(value);
  };
  switch (i.act) {
    case "join": return ["join"];
    case "invite": return ["invite", f("candidate"), ...(i.github_id !== undefined ? ["--github-id", String(i.github_id)] : [])];
    case "sponsor": return ["vouch", f("candidate")];
    case "vote": return ["vote", f("ballot")];
    case "reveal": return ["reveal", f("ballot")];
    case "open_admission": return ["open", "admission", f("candidate")];
    case "advance": return ["open", "advancement", self];
    case "open_sanction": return ["open", "sanction", f("member"), "--measure", f("measure")];
    case "open_amendment": return ["open", "amendment", f("path"), "--sha256", f("sha256")];
    case "close": return ["close", f("ballot")];
    case "exam": return ["exam", f("degree"), "--work", f("work_url")];
    case "report": return ["report", f("candidate"), f("degree"), f("verdict"), ...(i.reason ? ["--reason", i.reason] : [])];
    case "recuse": return ["recuse", f("candidate"), f("degree")];
    case "draw": return i.candidate ? ["draw", "--candidate", i.candidate] : ["draw"];
    case "call_council": return ["call-council"];
    case "work": return ["work", f("work_url")];
    case "depart": return ["depart"];
    case "object": return ["object", f("correction")];
  }
}

export function entryDraft(om: OmPort) {
  return declareCapability({
    title: "Draft an act (never signs)",
    description:
      "Prepares one act of the person; `act` uses the same names as the steps of member.due-steps (join, sponsor, vote, reveal, open_admission, advance, close, exam, report, recuse, draw, call_council, work, depart, plus open_sanction, open_amendment, invite and object). `invite` is never a due step: draft it only when a Master Builder names the person, and never suggest whom to invite; the inviter becomes that person's first sponsor. `join` works only under a live invitation. `object` is a Master Builder's objection to a correction (`correction` is its entry number, from corrections.read): it is never a due step, so draft it only when the person asks to object, and never propose it. No custodian act (a correction, its co-signature, application or withdrawal, a sign of life) and no key recovery is drafted here: those go through `bin/om` on the person's own terminal. The act is checked against the protocol and stored as a sealed draft; NOTHING is signed or published. " +
      "Show the summary to the person. If they agree, they run the returned `approve` command (e.g. `bin/om approve <digest>`): a system dialog asks them to confirm (for a vote, they choose Yes or No there, so you never learn it), then the exact draft is signed and a pull request opened. " +
      "If `refused` is set, explain the rule to the person instead; never try to work around it.",
    input: draftInput,
    output: z.object({
      refused: z.string().optional(),
      digest: z.string().optional(),
      summary: z.string().optional(),
      entry: z.record(z.string(), z.unknown()).optional(),
      approve: z.array(z.string()).optional(),
    }),
    allow: (principal) => loginFromPrincipal(principal?.id) !== undefined,
    hints: { readOnly: false, destructive: false, idempotent: false, openWorld: false },
    async run(input, call) {
      const login = loginFromPrincipal(call.principal?.id) as string;
      const r = await om.run([...draftArgv(input, login), "--json", "--login", login], call.signal);
      let data: { schema?: string; digest?: string; summary?: string; entry?: Record<string, unknown>;
                  approve?: string[]; refused?: string; error?: string } = {};
      try {
        data = JSON.parse(r.stdout);
      } catch {
        return { refused: firstLine(r.stdout) || `om exited with ${r.exitCode}` };
      }
      if (r.exitCode === 3 && data.schema === "om.draft/1" && data.digest && data.approve) {
        return { digest: data.digest, summary: data.summary ?? "", entry: data.entry ?? {}, approve: data.approve };
      }
      return { refused: data.refused ?? data.error ?? `om exited with ${r.exitCode}` };
    },
  });
}


/** The person's pending drafts (summaries only). Local only. */
function draftPending(om: OmPort) {
  return declareCapability({
    title: "My pending drafts",
    description: "Lists the person's sealed drafts that are waiting for approval (digest, entry number, summary).",
    input: z.object({}),
    output: z.object({ drafts: z.array(z.object({ digest: z.string(), seq: z.number().int().nullable(), summary: z.string().nullable() })) }),
    allow: (principal) => loginFromPrincipal(principal?.id) !== undefined,
    hints: { readOnly: true, destructive: false, idempotent: true, openWorld: false },
    async run(_input, call) {
      const r = await om.run(["drafts", "--json"], call.signal);
      const d = JSON.parse(r.stdout) as { schema: string; drafts: Array<{ digest: string; seq: number | null; summary: string | null }> };
      if (d.schema !== "om.drafts/1") throw new Error("om returned an unexpected drafts contract");
      return { drafts: d.drafts };
    },
  });
}
