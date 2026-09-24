import { describe, it, expect } from "vitest";
import { shouldSyncActiveSpace } from "@/lib/active-space-sync";

// D-23.5-09 regression suite.
//
// The defect the client reported on the 2026-09-24 prod release: following a research
// mail's "Open onderzoek in admin →" deep link opened the intake while the top bar still
// showed whichever client was selected last. The page and the dropdown then disagreed
// about who the operator was looking at — on a screen whose whole job is telling clients
// apart.
//
// Three admin routes need the identical rule and this repo has NO component test harness,
// so a predicate left inline in TSX is proven by nothing. These arms are the proof; the
// routes are three call sites of what they pin.

describe("shouldSyncActiveSpace", () => {
  it('syncs when "All clients" is selected — the operator ruled it ALWAYS matches', () => {
    // The one case a "only switch if something else is selected" reading gets wrong.
    // D-23.5-09: null is a SELECTION to be replaced, not a wildcard to honour. Without
    // this the deep link from the mail still lands on a page whose dropdown says
    // "Alle klanten" while the intake below it belongs to exactly one client.
    expect(shouldSyncActiveSpace(null, "sp-1")).toBe(true);
  });

  it("syncs when a DIFFERENT client is selected", () => {
    expect(shouldSyncActiveSpace("sp-2", "sp-1")).toBe(true);
  });

  it("does NOT sync when the selection already matches — this is what makes the effect idempotent", () => {
    // Load-bearing, not an optimisation: the calling effect depends on activeSpaceId and
    // calls setActiveSpace. Drop this guard and the effect re-fires on the state change it
    // just caused.
    expect(shouldSyncActiveSpace("sp-1", "sp-1")).toBe(false);
  });

  it("NEVER clears the operator's selection when the intake space is unknown", () => {
    // A failed or partial read must not look like a deliberate switch to "All clients".
    expect(shouldSyncActiveSpace("sp-1", null)).toBe(false);
    expect(shouldSyncActiveSpace("sp-1", undefined)).toBe(false);
    expect(shouldSyncActiveSpace("sp-1", "")).toBe(false);
  });

  it("does nothing when neither side knows a space", () => {
    expect(shouldSyncActiveSpace(null, null)).toBe(false);
    expect(shouldSyncActiveSpace(null, undefined)).toBe(false);
    expect(shouldSyncActiveSpace(null, "")).toBe(false);
  });
});
