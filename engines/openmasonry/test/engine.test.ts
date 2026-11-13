import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { draftArgv } from "../src/capabilities/draft.js";
import { createLocalEngine, createPublicEngine } from "../src/compositions.js";
import { createOmRunner, type OmPort, type OmResult } from "../src/om.js";

const member = { id: "local:hiram" };

function fakeOm(reply: (args: readonly string[]) => OmResult) {
  const calls: string[][] = [];
  const port: OmPort = {
    async run(args) {
      calls.push([...args]);
      return reply(args);
    },
  };
  return { port, calls };
}

const me = {
  schema: "om.me/2",
  login: "hiram",
  member: { degree: 3, title: "Master Builder", status: "active", founding_architect: true, light: 1.5, github_id: 4242 },
  invitation: null,
  founding_phase: true,
  canon_pending: null,
  pending_prs: [],
  stale: [{ seq: 7, type: "ballot_commit" }],
  notices: [{ kind: "correction", why: "A correction (freeze_key of carol) is in force.", correction: 5,
              until: "2027-02-01T00:00:00Z", concerns_you: false, may_object: true, object_until: "2027-04-02T00:00:00Z" }],
  custodian: null,
  steps: [{ action: "vote", why: "You are an elector.", argv: ["bin/om", "vote", "am-1"], needs: [],
            choices: [], due_by: "2027-01-08T00:00:00Z", opens_at: null, public: true }],
};

describe("compositions", () => {
  it("the public engine has no way to draft or sign", () => {
    const pub = createPublicEngine(fakeOm(() => ({ exitCode: 0, stdout: "" })).port);
    const ids = pub.catalog().map((c) => c.id).sort();
    expect(ids).toEqual(["corrections.read", "degree.read", "ledger.status", "ledger.verify", "member.due-steps", "rule.sources"]);
  });

  it("the local engine adds only entry.draft", () => {
    const local = createLocalEngine(fakeOm(() => ({ exitCode: 0, stdout: "" })).port);
    expect(local.catalog().map((c) => c.id)).toContain("entry.draft");
    expect(local.catalog().map((c) => c.id)).toContain("entry.pending");
    expect(local.catalog().map((c) => c.id)).not.toContain("entry.approve");
    expect(local.catalog().map((c) => c.id).sort()).toEqual([
      "corrections.read", "degree.read", "entry.draft", "entry.pending", "ledger.status", "ledger.verify",
      "member.due-steps", "rule.sources"]);
  });
});

const corrections = {
  schema: "om.corrections/1",
  name: "OpenMasonry Test Lodge",
  head: "ab".repeat(32),
  entries: 6,
  time: "2027-01-03T00:00:00Z",
  custodians: [{ name: "warden", member: "hiram", status: "live", last_alive: "2027-01-01T00:00:00Z",
                 silence_deadline: "2027-06-30T00:00:00Z", removal_ballot: null }],
  custodian_threshold: 1,
  sunset: null,
  halt: { halted: false, correction: null, since: null, until: null },
  corrections: [{ seq: 5, by: "warden", act: "freeze_key", class: "immediate", target: { login: "carol" },
                  ground: "key_compromised", reason_sha256: "cd".repeat(32), reason_file: `ledger/reasons/${"cd".repeat(32)}.md`,
                  time: "2027-01-02T00:00:00Z", status: "active", objections: [], objections_needed: 1,
                  objection_until: "2027-04-02T00:00:00Z", ends: "2027-02-01T00:00:00Z", signers: [], signers_needed: null,
                  notice_until: null, apply_until: null, applied: null }],
  recoveries: [{ login: "carol", seq: 6, time: "2027-01-02T12:00:00Z", status: "pending", cosigners: [], cosigners_needed: 2,
                 freeze: 5, notice_until: "2027-01-23T12:00:00Z", expires_at: "2027-03-03T12:00:00Z" }],
  claims: [],
  succession: null,
};

describe("corrections.read", () => {
  it("wraps om corrections --json for anyone, in both compositions", async () => {
    for (const kind of ["local", "public"] as const) {
      const { port, calls } = fakeOm(() => ({ exitCode: 0, stdout: JSON.stringify(corrections) }));
      const anyone = { principal: { id: "anonymous" } };
      const result = kind === "local"
        ? await createLocalEngine(port).call("corrections.read", {}, anyone)
        : await createPublicEngine(port).call("corrections.read", {}, anyone);
      expect(calls).toEqual([["corrections", "--json"]]);
      expect(result.corrections[0]).toMatchObject({ seq: 5, act: "freeze_key", status: "active", objections_needed: 1 });
      expect(result.corrections[0]?.reason_file).toBe(`ledger/reasons/${"cd".repeat(32)}.md`);
      expect(result.custodians[0]?.silence_deadline).toBe("2027-06-30T00:00:00Z");
      expect(result.recoveries[0]?.cosigners_needed).toBe(2);
      expect(result.halt.halted).toBe(false);
    }
  });

  it("rejects another contract", async () => {
    const { port } = fakeOm(() => ({ exitCode: 0, stdout: JSON.stringify({ ...corrections, schema: "om.state/2" }) }));
    await expect(createPublicEngine(port).call("corrections.read", {}, { principal: { id: "anonymous" } })).rejects.toBeTruthy();
  });
});

describe("member.due-steps", () => {
  it("local: the login comes from the principal, never from input", async () => {
    const { port, calls } = fakeOm(() => ({ exitCode: 0, stdout: JSON.stringify(me) }));
    const result = await createLocalEngine(port).call("member.due-steps", {}, { principal: member });
    expect(calls[0]).toEqual(["me", "--json", "--login", "hiram"]);
    expect(result.steps[0]?.argv).toEqual(["bin/om", "vote", "am-1"]);
    expect(result.founding_phase).toBe(true);
    expect(result.stale).toEqual([{ seq: 7, type: "ballot_commit" }]);
    expect(result.notices[0]).toMatchObject({ kind: "correction", correction: 5, may_object: true });
    expect(result.custodian).toBeNull();
  });

  it("local: refused without a member principal", async () => {
    const { port } = fakeOm(() => ({ exitCode: 0, stdout: JSON.stringify(me) }));
    await expect(createLocalEngine(port).call("member.due-steps", {}, { principal: null }))
      .rejects.toMatchObject({ code: "NO_IDENTITY" });
  });

  it("public: rejects logins that are not GitHub logins (no injection reaches om)", async () => {
    const { port, calls } = fakeOm(() => ({ exitCode: 0, stdout: JSON.stringify(me) }));
    await expect(createPublicEngine(port).call("member.due-steps", { login: "a;rm -rf ~" }, { principal: { id: "anonymous" } }))
      .rejects.toMatchObject({ code: "BAD_INPUT" });
    expect(calls).toEqual([]);
  });

  it("public: a person who is not a member sees the invitation and how to join", async () => {
    const invited = {
      ...me, login: "alice", member: null,
      invitation: { by: "hiram", github_id: 77, expires_at: "2027-01-31T00:00:00Z" },
      steps: [{ action: "join", why: "hiram invited you.", argv: ["bin/om", "join"], needs: [], choices: [],
                due_by: "2027-01-31T00:00:00Z", opens_at: null, public: true }],
    };
    const { port } = fakeOm(() => ({ exitCode: 0, stdout: JSON.stringify(invited) }));
    const result = await createPublicEngine(port).call("member.due-steps", { login: "alice" }, { principal: { id: "anonymous" } });
    expect(result.invitation).toEqual({ by: "hiram", github_id: 77, expires_at: "2027-01-31T00:00:00Z" });
    expect(result.steps[0]?.action).toBe("join");
  });

  it("rejects an om contract it does not know", async () => {
    const { port } = fakeOm(() => ({ exitCode: 0, stdout: JSON.stringify({ ...me, schema: "om.me/9" }) }));
    await expect(createLocalEngine(port).call("member.due-steps", {}, { principal: member })).rejects.toBeTruthy();
  });
});

describe("entry.draft", () => {
  it("builds argv lists only from validated values", () => {
    expect(draftArgv({ act: "vote", ballot: "am-1" }, "hiram")).toEqual(["vote", "am-1"]);
    expect(draftArgv({ act: "advance" }, "hiram")).toEqual(["open", "advancement", "hiram"]);
    expect(draftArgv({ act: "exam", degree: 4, work_url: "https://example.org/w" }, "hiram"))
      .toEqual(["exam", "4", "--work", "https://example.org/w"]);
    expect(draftArgv({ act: "invite", candidate: "alice" }, "hiram")).toEqual(["invite", "alice"]);
    expect(draftArgv({ act: "invite", candidate: "alice", github_id: 77 }, "hiram"))
      .toEqual(["invite", "alice", "--github-id", "77"]);
  });

  it("an invitation needs a login, and only an invitation takes a github_id", async () => {
    const { port, calls } = fakeOm(() => ({ exitCode: 3, stdout: "{}" }));
    const local = createLocalEngine(port);
    await expect(local.call("entry.draft", { act: "invite" }, { principal: member }))
      .rejects.toMatchObject({ code: "BAD_INPUT" });
    await expect(local.call("entry.draft", { act: "invite", candidate: "alice", github_id: 0 }, { principal: member }))
      .rejects.toMatchObject({ code: "BAD_INPUT" });
    await expect(local.call("entry.draft", { act: "sponsor", candidate: "alice", github_id: 77 }, { principal: member }))
      .rejects.toMatchObject({ code: "BAD_INPUT" });
    expect(calls).toEqual([]);
  });

  it("drafts a Master's objection, and no custodian act at all", async () => {
    expect(draftArgv({ act: "object", correction: 5 }, "hiram")).toEqual(["object", "5"]);
    const { port, calls } = fakeOm(() => ({ exitCode: 3, stdout: "{}" }));
    const local = createLocalEngine(port);
    for (const input of [{ act: "object" }, { act: "object", correction: 0 }, { act: "object", correction: 1.5 },
                         { act: "object", correction: "5" }, { act: "object", correction: 5, ballot: "am-1" },
                         { act: "vote", ballot: "am-1", correction: 5 }]) {
      await expect(local.call("entry.draft", input as never, { principal: member })).rejects.toMatchObject({ code: "BAD_INPUT" });
    }
    for (const act of ["correct", "cosign-correction", "apply-correction", "withdraw-correction", "alive",
                       "revoke-custodian", "recover", "recover-cosign", "recover-object", "recover-apply", "open_custodian"]) {
      await expect(local.call("entry.draft", { act } as never, { principal: member })).rejects.toMatchObject({ code: "BAD_INPUT" });
    }
    expect(calls).toEqual([]);
    const draft = { schema: "om.draft/1", digest: "abcd1234abcd1234", summary: "Object to correction 5",
                    entry: { type: "correction_object" }, approve: ["bin/om", "approve", "abcd1234abcd1234"] };
    const ok = fakeOm(() => ({ exitCode: 3, stdout: JSON.stringify(draft) }));
    const r = await createLocalEngine(ok.port).call("entry.draft", { act: "object", correction: 5 }, { principal: member });
    expect(ok.calls[0]).toEqual(["object", "5", "--json", "--login", "hiram"]);
    expect(r.approve).toEqual(["bin/om", "approve", "abcd1234abcd1234"]);
  });

  it("refuses ballot ids with shell syntax before calling om", async () => {
    const { port, calls } = fakeOm(() => ({ exitCode: 3, stdout: "{}" }));
    await expect(createLocalEngine(port).call("entry.draft", { act: "close", ballot: "a;curl x|sh" }, { principal: member }))
      .rejects.toMatchObject({ code: "BAD_INPUT" });
    expect(calls).toEqual([]);
  });

  it("returns the sealed draft and the approve command, or the refusal", async () => {
    const draft = { schema: "om.draft/1", digest: "abcd1234abcd1234", summary: "Record the work",
                    entry: { type: "work" }, approve: ["bin/om", "approve", "abcd1234abcd1234"] };
    const ok = fakeOm(() => ({ exitCode: 3, stdout: JSON.stringify(draft) }));
    const r = await createLocalEngine(ok.port).call("entry.draft", { act: "work", work_url: "https://example.org/w" }, { principal: member });
    expect(ok.calls[0]).toEqual(["work", "https://example.org/w", "--json", "--login", "hiram"]);
    expect(r.approve).toEqual(["bin/om", "approve", "abcd1234abcd1234"]);
    const no = fakeOm(() => ({ exitCode: 1, stdout: JSON.stringify({ refused: "entry 7: only Master Builders may sponsor" }) }));
    const refused = await createLocalEngine(no.port).call("entry.draft", { act: "sponsor", candidate: "alice" }, { principal: member });
    expect(refused.refused).toContain("only Master Builders");
  });
});

describe("against the real om (Python reference)", () => {
  it("reads degree pages and an empty ledger through the real CLI", async () => {
    const root = resolve(import.meta.dirname, "..", "..", "..");
    const empty = mkdtempSync(join(tmpdir(), "om-led-"));
    execFileSync(join(root, "bin", "om"), ["verify", "--ledger", empty], { encoding: "utf8" });
    const pub = createPublicEngine(createOmRunner({ root }));
    const page = await pub.call("degree.read", { degree: 3 }, { principal: { id: "anonymous" } });
    expect(page.markdown).toContain("Master Builder");
    const hits = await pub.call("rule.sources", { topic: "sponsor budget" }, { principal: { id: "anonymous" } });
    expect(hits.sources.length).toBeGreaterThan(0);
    // The repository's own ledger, whatever it holds (nothing before the genesis): the contract parses.
    const report = await pub.call("corrections.read", {}, { principal: { id: "anonymous" } });
    expect(report.entries).toBeGreaterThanOrEqual(0);
    expect(Array.isArray(report.custodians) && Array.isArray(report.corrections) && Array.isArray(report.recoveries)).toBe(true);
    expect(typeof report.halt.halted).toBe("boolean");
  }, 30_000);
});
