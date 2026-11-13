import { resolve } from "node:path";

import type { OmPort, OmResult } from "../src/om.js";

/** The repository root (OM_ROOT for the tests that run the real `bin/om`). */
export const repoRoot = resolve(import.meta.dirname, "..", "..", "..");
export const engineRoot = resolve(import.meta.dirname, "..");

export function fakeOm(reply: (args: readonly string[]) => OmResult | Promise<OmResult>) {
  const calls: string[][] = [];
  const port: OmPort = {
    async run(args) {
      calls.push([...args]);
      return reply(args);
    },
  };
  return { port, calls };
}

export const ok = (data: unknown): OmResult => ({ exitCode: 0, stdout: JSON.stringify(data) });

const halt = { halted: false, correction: null, since: null, until: null };

export const state = {
  schema: "om.state/2",
  name: "OpenMasonry Test Lodge",
  head: "ab".repeat(32),
  entries: 3,
  founding_phase: true,
  masters: 1,
  canon_pending: null,
  members: [{ login: "hiram", degree: 3, title: "Master Builder", founding_architect: true, github_id: 4242, status: "active",
              dormant: false, light: 1.5, last_activity: "2027-01-01T00:00:00Z", frozen_until: null, room_hold_until: null,
              recovering: false }],
  exams: [],
  invitations: [],
  petitions: [],
  checkpoints: [],
  open_ballots: [{ id: "am-1", kind: "amendment", subject: { path: "README.md" }, commit_until: "2027-01-08T00:00:00Z",
                   reveal_until: "2027-01-10T00:00:00Z", stayed_until: null }],
  custodians: [],
  custodian_threshold: 1,
  sunset: null,
  corrections: [],
  recoveries: [],
  halt,
};

export const verified = {
  schema: "om.verify/1",
  valid: true,
  entries: 3,
  head: "ab".repeat(32),
  state_sha256: "cd".repeat(32),
  message: "ledger OK",
  problems: [],
};

export const drafts = {
  schema: "om.drafts/1",
  drafts: [{ digest: "abcd1234abcd1234", seq: 4, summary: "Vote on am-1" }],
};
