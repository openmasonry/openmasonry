/** Every tool against a fake `om`: the exact argv, the parsed contract, and the refusals before `om` runs. */
import { describe, expect, it } from "vitest";
import { z } from "zod";

import { assembleEngine, declareCapability } from "../src/capability.js";
import { createLocalEngine, createPublicEngine } from "../src/compositions.js";
import { drafts, fakeOm, ok, state, verified } from "./fixtures.js";

const member = { principal: { id: "local:hiram" } };
const anyone = { principal: { id: "anonymous" } };

describe("ledger.status", () => {
  it("wraps om state --json and drops the schema name", async () => {
    const { port, calls } = fakeOm(() => ok(state));
    const result = await createPublicEngine(port).call("ledger.status", {}, anyone);
    expect(calls).toEqual([["state", "--json"]]);
    expect(result.members[0]).toMatchObject({ login: "hiram", degree: 3 });
    expect(result.open_ballots[0]?.id).toBe("am-1");
    expect("schema" in result).toBe(false);
  });

  it("rejects a state that does not match its schema", async () => {
    const { port } = fakeOm(() => ok({ ...state, members: [{ login: "hiram" }] }));
    await expect(createPublicEngine(port).call("ledger.status", {}, anyone)).rejects.toMatchObject({ code: "BAD_OUTPUT" });
  });
});

describe("ledger.verify", () => {
  it("local: online re-checks the beacon only when asked", async () => {
    const { port, calls } = fakeOm(() => ok(verified));
    const local = createLocalEngine(port);
    const result = await local.call("ledger.verify", {}, member);
    await local.call("ledger.verify", { online: true }, member);
    expect(calls).toEqual([["verify", "--tree", "--json"], ["verify", "--tree", "--json", "--online"]]);
    expect(result.valid).toBe(true);
    expect(result.warnings).toEqual([]);
  });

  it("public: never goes online", async () => {
    const { port, calls } = fakeOm(() => ok(verified));
    await createPublicEngine(port).call("ledger.verify", { online: true }, anyone);
    expect(calls).toEqual([["verify", "--tree", "--json"]]);
    const verify = createPublicEngine(port).detail("ledger.verify");
    expect(verify.hints.openWorld).toBe(false);
    expect(createLocalEngine(port).detail("ledger.verify").hints.openWorld).toBe(true);
  });
});

describe("degree.read", () => {
  it("asks om for one of the 33 degrees, and refuses any other number", async () => {
    const { port, calls } = fakeOm(() => ok({ schema: "om.degree/1", degree: 4, markdown: "# Degree 4" }));
    const pub = createPublicEngine(port);
    expect(await pub.call("degree.read", { degree: 4 }, anyone)).toEqual({ degree: 4, markdown: "# Degree 4" });
    for (const degree of [0, 34, 2.5, "4"]) {
      await expect(pub.call("degree.read", { degree }, anyone)).rejects.toMatchObject({ code: "BAD_INPUT" });
    }
    expect(calls).toEqual([["learn", "4", "--json"]]);
  });
});

describe("rule.sources", () => {
  it("passes -- before the free-text topic", async () => {
    const { port, calls } = fakeOm(() => ok({ schema: "om.rules/1", topic: "--help me", sources: [] }));
    const pub = createPublicEngine(port);
    await pub.call("rule.sources", { topic: "  --help me " }, anyone);
    expect(calls).toEqual([["rules", "--json", "--", "--help me"]]);
    await expect(pub.call("rule.sources", { topic: "ab" }, anyone)).rejects.toMatchObject({ code: "BAD_INPUT" });
    await expect(pub.call("rule.sources", { topic: "x".repeat(201) }, anyone)).rejects.toMatchObject({ code: "BAD_INPUT" });
    expect(calls).toHaveLength(1);
  });
});

describe("entry.pending", () => {
  it("lists the person's sealed drafts, and needs a member principal", async () => {
    const { port, calls } = fakeOm(() => ok(drafts));
    const local = createLocalEngine(port);
    expect(await local.call("entry.pending", {}, member)).toEqual({ drafts: drafts.drafts });
    expect(calls).toEqual([["drafts", "--json"]]);
    await expect(local.call("entry.pending", {}, { principal: null })).rejects.toMatchObject({ code: "NO_IDENTITY" });
    await expect(local.call("entry.pending", {}, anyone)).rejects.toMatchObject({ code: "NOT_PERMITTED" });
    expect(calls).toHaveLength(1);
  });
});

describe("entry.draft", () => {
  it("needs a member principal, and the login always comes from it", async () => {
    const { port, calls } = fakeOm(() => ({ exitCode: 3, stdout: "{}" }));
    const local = createLocalEngine(port);
    await expect(local.call("entry.draft", { act: "depart" }, { principal: null })).rejects.toMatchObject({ code: "NO_IDENTITY" });
    await expect(local.call("entry.draft", { act: "depart" }, { principal: { id: "local:not a login" } }))
      .rejects.toMatchObject({ code: "NOT_PERMITTED" });
    await expect(local.call("entry.draft", { act: "depart", login: "mallory" }, member)).rejects.toMatchObject({ code: "BAD_INPUT" });
    expect(calls).toEqual([]);
    await local.call("entry.draft", { act: "depart" }, member);
    expect(calls).toEqual([["depart", "--json", "--login", "hiram"]]);
  });

  it("reports a non-JSON answer of om as a refusal", async () => {
    const { port } = fakeOm(() => ({ exitCode: 2, stdout: "\nom: no key configured\nmore" }));
    const r = await createLocalEngine(port).call("entry.draft", { act: "depart" }, member);
    expect(r).toEqual({ refused: "om: no key configured" });
  });
});

describe("the engine", () => {
  it("names an unknown capability", async () => {
    const { port } = fakeOm(() => ok({}));
    await expect(createPublicEngine(port).call("entry.draft" as never, {}, anyone))
      .rejects.toMatchObject({ code: "UNKNOWN_CAPABILITY", details: { capability: "entry.draft" } });
    expect(() => createPublicEngine(port).detail("entry.draft")).toThrow();
  });

  it("refuses a malformed principal", async () => {
    const { port, calls } = fakeOm(() => ok({}));
    await expect(createPublicEngine(port).call("ledger.status", {}, { principal: { id: "" } }))
      .rejects.toMatchObject({ code: "NO_IDENTITY" });
    expect(calls).toEqual([]);
  });

  it("hides the cause of a failure behind FAILED", async () => {
    const { port } = fakeOm(() => { throw new Error("secret detail"); });
    const failure = await createPublicEngine(port).call("ledger.status", {}, anyone).catch((e: unknown) => e);
    expect(failure).toMatchObject({ code: "FAILED", message: "The capability could not complete." });
  });

  it("returns CANCELED once the caller aborts", async () => {
    const { port } = fakeOm(() => new Promise(() => undefined));
    const abort = new AbortController();
    const call = createPublicEngine(port).call("ledger.status", {}, { ...anyone, signal: abort.signal });
    abort.abort();
    await expect(call).rejects.toMatchObject({ code: "CANCELED" });
    const already = createPublicEngine(port).call("ledger.status", {}, { ...anyone, signal: abort.signal });
    await expect(already).rejects.toMatchObject({ code: "CANCELED" });
  });

  it("refuses a capability whose schemas do not have an object root", () => {
    const bad = declareCapability({
      title: "t", description: "d", input: z.string(), output: z.object({}), allow: "anyone",
      hints: { readOnly: true, destructive: false, idempotent: true, openWorld: false },
      run: () => ({}),
    });
    expect(() => assembleEngine({ name: "x", version: "0", capabilities: { bad } })).toThrow(/object root/);
  });
});
