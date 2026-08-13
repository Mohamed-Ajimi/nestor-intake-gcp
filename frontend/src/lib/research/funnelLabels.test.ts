import { describe, it, expect } from "vitest";
import {
  KNOWN_FUNNEL_STAGES,
  humanizeFunnelStage,
  isKnownFunnelStage,
} from "@/lib/research/funnelLabels";

// 23-01 Task 1 — the funnel-stage vocabulary, pinned over ALL EIGHTEEN engine keys plus the
// unknown, empty, hostile-length and control-character paths.
//
// WHY EIGHTEEN NAMED TESTS AND NOT ONE TABLE LOOP. Same argument as
// `verificationGate.test.ts`: the point of this suite is that an edit which drops a key fails a
// test whose NAME says which figure the operator just lost off the report. A loop over a fixture
// table would go red naming a row index, and the reviewer would then be free to "fix" it by
// editing the table. These names are the argument; the assertions are only the proof.

describe("KNOWN_FUNNEL_STAGES — the nine gate-owned keys (gates.py _FUNNEL_KEYS)", () => {
  it("distilled — every factual statement the research produced, before any filtering", () => {
    expect(isKnownFunnelStage("distilled")).toBe(true);
  });

  it("kept — statements the materiality gates judged worth considering for a check", () => {
    expect(isKnownFunnelStage("kept")).toBe(true);
  });

  it("dropped — statements gated out without a check; the reason rows below break this down", () => {
    expect(isKnownFunnelStage("dropped")).toBe(true);
  });

  it("not_falsifiable — dropped because the statement cannot be proved or disproved", () => {
    expect(isKnownFunnelStage("not_falsifiable")).toBe(true);
  });

  it("not_load_bearing — dropped because nothing in the conclusion depends on it", () => {
    expect(isKnownFunnelStage("not_load_bearing")).toBe(true);
  });

  it("both — dropped for both reasons at once", () => {
    expect(isKnownFunnelStage("both")).toBe(true);
  });

  it("selected_verify — statements placed in the fact-check queue", () => {
    expect(isKnownFunnelStage("selected_verify")).toBe(true);
  });

  it("skipped_stable — skipped by the error-likelihood gate as a settled, widely known fact", () => {
    expect(isKnownFunnelStage("skipped_stable")).toBe(true);
  });

  it("gate_errors — batches the filtering step could not process; their claims default to KEEP", () => {
    expect(isKnownFunnelStage("gate_errors")).toBe(true);
  });
});

describe("KNOWN_FUNNEL_STAGES — the nine pipeline-owned keys (pipeline.py _build_funnel)", () => {
  it("checked — selected for checking AND actually checked (bucket 1)", () => {
    expect(isKnownFunnelStage("checked")).toBe(true);
  });

  it("should_have_been_checked — bucket 3, the phase's most important number; these passages shipped unexamined", () => {
    expect(isKnownFunnelStage("should_have_been_checked")).toBe(true);
  });

  it("verify_sessions — skeptic sessions actually launched; a throughput measure, not a quality one", () => {
    expect(isKnownFunnelStage("verify_sessions")).toBe(true);
  });

  it("checked_incidentally — not selected, yet checked as a member of a selected group (bucket 1b)", () => {
    expect(isKnownFunnelStage("checked_incidentally")).toBe(true);
  });

  it("checked_incidentally_not_falsifiable — of those, the ones originally dropped as not testable", () => {
    expect(isKnownFunnelStage("checked_incidentally_not_falsifiable")).toBe(true);
  });

  it("checked_incidentally_not_load_bearing — of those, the ones originally dropped as not load-bearing", () => {
    expect(isKnownFunnelStage("checked_incidentally_not_load_bearing")).toBe(true);
  });

  it("checked_incidentally_both — of those, the ones originally dropped for both reasons", () => {
    expect(isKnownFunnelStage("checked_incidentally_both")).toBe(true);
  });

  it("checked_incidentally_stable — of those, the ones originally skipped as settled facts", () => {
    expect(isKnownFunnelStage("checked_incidentally_stable")).toBe(true);
  });

  it("unresolved_anchors — citation markers the writing model emitted that matched no claim and were removed", () => {
    expect(isKnownFunnelStage("unresolved_anchors")).toBe(true);
  });
});

describe("KNOWN_FUNNEL_STAGES — the exact set and its order", () => {
  // The engine writes ONE flat dict and the report renders every numeric entry of it, so the
  // set below is the whole render surface. Pinned as a literal, in order, so that adding an
  // engine key without adding its curated copy is a visible diff rather than a silent
  // fallback row on the operator's screen.
  it("is exactly the eighteen engine keys, in gate-then-pipeline order", () => {
    expect([...KNOWN_FUNNEL_STAGES]).toEqual([
      "distilled",
      "kept",
      "dropped",
      "not_falsifiable",
      "not_load_bearing",
      "both",
      "selected_verify",
      "skipped_stable",
      "gate_errors",
      "checked",
      "should_have_been_checked",
      "verify_sessions",
      "checked_incidentally",
      "checked_incidentally_not_falsifiable",
      "checked_incidentally_not_load_bearing",
      "checked_incidentally_both",
      "checked_incidentally_stable",
      "unresolved_anchors",
    ]);
  });
});

describe("isKnownFunnelStage — what falls OUT of the curated set", () => {
  it("a key this build has never seen is NOT known, and humanizes to a readable phrase instead of a raw token — _build_funnel declares funnel keys ADDITIVE ONLY, so this is the expected state of the world after any engine release, not an anomaly", () => {
    expect(isKnownFunnelStage("a_brand_new_engine_key")).toBe(false);
    expect(humanizeFunnelStage("a_brand_new_engine_key")).toBe("A brand new engine key");
  });

  it("the empty string is not a stage", () => {
    expect(isKnownFunnelStage("")).toBe(false);
  });

  it("the match is CASE-SENSITIVE — the engine emits lowercase, so CHECKED is not `checked` and must not borrow its curated copy", () => {
    expect(isKnownFunnelStage("CHECKED")).toBe(false);
  });
});

describe("humanizeFunnelStage — the degrade-safe fallback", () => {
  it("an empty key still yields a non-empty phrase, so a funnel row can never render blank", () => {
    expect(humanizeFunnelStage("")).not.toBe("");
  });

  it("a whitespace-only key is treated as empty and still yields a non-empty phrase", () => {
    expect(humanizeFunnelStage("   ")).not.toBe("");
  });

  it("an absurdly long key is capped at 80 characters plus an ellipsis, so it cannot blow the row's layout (T-23-02)", () => {
    expect(humanizeFunnelStage("x".repeat(500)).length).toBeLessThanOrEqual(81);
  });

  it("the capped form ends in an ellipsis, so the truncation is visible rather than silent", () => {
    expect(humanizeFunnelStage("x".repeat(500)).endsWith("…")).toBe(true);
  });

  it("a key at the cap is NOT truncated — the ellipsis appears only when something was actually removed", () => {
    const eighty = "y".repeat(80);
    expect(humanizeFunnelStage(eighty)).toBe("Y".repeat(1) + "y".repeat(79));
    expect(humanizeFunnelStage(eighty).endsWith("…")).toBe(false);
  });

  it("a key carrying a line break or a tab cannot inject either into the row (T-23-02)", () => {
    const out = humanizeFunnelStage("checked\nincidentally\tstable");
    expect(out).not.toContain("\n");
    expect(out).not.toContain("\t");
    expect(out).toBe("Checked incidentally stable");
  });

  it("whitespace runs collapse to a single space", () => {
    expect(humanizeFunnelStage("checked   twice")).toBe("Checked twice");
  });

  it("a curated key humanizes too — the fallback is never worse than the raw token, even for a key that also has locale copy", () => {
    expect(humanizeFunnelStage("should_have_been_checked")).toBe("Should have been checked");
  });
});
