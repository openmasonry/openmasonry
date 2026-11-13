/**
 * The two engines OpenMasonry ships (decision 11 in docs/architecture/ARCHITECTURE.md).
 *
 * local   served over MCP stdio on the member's own machine. Reads, plus sealed
 *         drafts for the person running it (principal `local:<login>`). It
 *         never signs.
 * public  served over MCP HTTP from any VPS, to anyone. Reads only: it holds no
 *         draft capability, so no act is ever prepared remotely and no vote or
 *         key ever reaches a server.
 */
import { assembleEngine } from "./capability.js";
import { draftPending, entryDraft } from "./capabilities/draft.js";
import { correctionsRead, degreeRead, ledgerStatus, ledgerVerify, localDueSteps, publicDueSteps, ruleSources } from "./capabilities/read.js";
import type { OmPort } from "./om.js";

export const ENGINE_VERSION = "0.1.0";

export function createLocalEngine(om: OmPort) {
  return assembleEngine({
    name: "openmasonry",
    version: ENGINE_VERSION,
    capabilities: {
      "member.due-steps": localDueSteps(om),
      "ledger.status": ledgerStatus(om),
      "ledger.verify": ledgerVerify(om, true),
      "corrections.read": correctionsRead(om),
      "degree.read": degreeRead(om),
      "rule.sources": ruleSources(om),
      "entry.draft": entryDraft(om),
      "entry.pending": draftPending(om),
    },
  });
}

export function createPublicEngine(om: OmPort) {
  return assembleEngine({
    name: "openmasonry-public",
    version: ENGINE_VERSION,
    capabilities: {
      "member.due-steps": publicDueSteps(om),
      "ledger.status": ledgerStatus(om),
      "ledger.verify": ledgerVerify(om, false),
      "corrections.read": correctionsRead(om),
      "degree.read": degreeRead(om),
      "rule.sources": ruleSources(om),
    },
  });
}
