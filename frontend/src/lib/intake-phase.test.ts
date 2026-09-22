import { describe, it, expect } from "vitest";
import {
  derivePhase,
  type Phase,
  type PhaseIntakeInput,
  type PhaseSkillRunInput,
} from "@/lib/intake-phase";

// QA-03 characterization suite (T-06-04 mitigation).
//
// derivePhase is a PURE function and is the contract that drives every admin-UI block.
// This suite OBSERVES the existing 12-Phase machine and pins each branch so that a later
// re-point of derivePhase's INPUTS (D-05 — backend read seam) cannot silently change a
// transition. It does NOT modify intake-phase.ts and is GREEN against today's behavior.
//
// Pitfall 1 / Assumption A1: the terminal skill-run value derivePhase checks is the literal
// string "succeeded"; the plan-05 read seam maps the backend SkillRun status onto this value,
// so the skill-run cases below use "succeeded" deliberately.

// Base intake with every marker null; cases override only what they exercise.
function baseIntake(status: string | null): PhaseIntakeInput {
  return {
    status,
    validation_link_sent_at: null,
    results_link_sent_at: null,
    context_pack_artifact_id: null,
    final_report_artifact_id: null,
  };
}

const TS = "2026-06-29T00:00:00.000Z";

const runSucceededUnapplied: PhaseSkillRunInput = { status: "succeeded", applied_at: null };
const runSucceededApplied: PhaseSkillRunInput = { status: "succeeded", applied_at: TS };
const runRunning: PhaseSkillRunInput = { status: "running", applied_at: null };

describe("derivePhase — characterization of all 12 Phase outcomes (QA-03)", () => {
  it("draft → awaiting_client_submission", () => {
    expect(derivePhase(baseIntake("draft"), null, false)).toBe<Phase>("awaiting_client_submission");
  });

  it("submitted + no skill run → awaiting_skill_run", () => {
    expect(derivePhase(baseIntake("submitted"), null, false)).toBe<Phase>("awaiting_skill_run");
  });

  it("submitted + skill run status != succeeded → awaiting_skill_run", () => {
    expect(derivePhase(baseIntake("submitted"), runRunning, false)).toBe<Phase>(
      "awaiting_skill_run",
    );
  });

  it("submitted + succeeded run, applied_at null → awaiting_review", () => {
    expect(derivePhase(baseIntake("submitted"), runSucceededUnapplied, false)).toBe<Phase>(
      "awaiting_review",
    );
  });

  it("submitted + succeeded run, applied_at set → awaiting_validation_send", () => {
    expect(derivePhase(baseIntake("submitted"), runSucceededApplied, false)).toBe<Phase>(
      "awaiting_validation_send",
    );
  });

  it("reviewed + validation_link_sent_at null → awaiting_validation_send", () => {
    expect(derivePhase(baseIntake("reviewed"), null, false)).toBe<Phase>("awaiting_validation_send");
  });

  it("reviewed + validation_link_sent_at set → awaiting_client_validation", () => {
    const intake = { ...baseIntake("reviewed"), validation_link_sent_at: TS };
    expect(derivePhase(intake, null, false)).toBe<Phase>("awaiting_client_validation");
  });

  it("validated_by_client + context_pack_artifact_id null → awaiting_context_pack", () => {
    expect(derivePhase(baseIntake("validated_by_client"), null, false)).toBe<Phase>(
      "awaiting_context_pack",
    );
  });

  it("validated_by_client + context_pack_artifact_id set → awaiting_research_start", () => {
    const intake = { ...baseIntake("validated_by_client"), context_pack_artifact_id: "cp-1" };
    expect(derivePhase(intake, null, false)).toBe<Phase>("awaiting_research_start");
  });

  it("decomposed + hasResearchArtifacts false → awaiting_research_start", () => {
    expect(derivePhase(baseIntake("decomposed"), null, false)).toBe<Phase>("awaiting_research_start");
  });

  it("decomposed + hasResearchArtifacts true → in_research", () => {
    expect(derivePhase(baseIntake("decomposed"), null, true)).toBe<Phase>("in_research");
  });

  it("in_research + final_report_artifact_id set → awaiting_results_send", () => {
    const intake = { ...baseIntake("in_research"), final_report_artifact_id: "rep-1" };
    expect(derivePhase(intake, null, false)).toBe<Phase>("awaiting_results_send");
  });

  it("in_research + hasResearchArtifacts true, no report → awaiting_report_upload", () => {
    expect(derivePhase(baseIntake("in_research"), null, true)).toBe<Phase>("awaiting_report_upload");
  });

  it("in_research + neither report nor artifacts → in_research", () => {
    expect(derivePhase(baseIntake("in_research"), null, false)).toBe<Phase>("in_research");
  });

  it("delivered + results_link_sent_at set → completed", () => {
    const intake = { ...baseIntake("delivered"), results_link_sent_at: TS };
    expect(derivePhase(intake, null, false)).toBe<Phase>("completed");
  });

  it("delivered + results_link_sent_at null → awaiting_results_send", () => {
    expect(derivePhase(baseIntake("delivered"), null, false)).toBe<Phase>("awaiting_results_send");
  });

  it("unknown / archived status → archived", () => {
    expect(derivePhase(baseIntake("some_unknown_status"), null, false)).toBe<Phase>("archived");
  });
});

// ---------------------------------------------------------------------------
// TOTALITY under the status override (phase 23.5 plan 01 / D-23.5-01)
// ---------------------------------------------------------------------------
//
// Until the override shipped, the reachable (status, artifact-marker) combinations were
// only the ones the three named transition verbs could produce, walking forward. The
// override lets a superadmin set ANY status directly — including BACKWARDS
// (`delivered` → `reviewed`, the operator's own example) — which leaves behind shapes the
// forward-only flow never produced: a `reviewed` intake that already carries a
// `final_report_artifact_id`, a `draft` intake that already has a context pack, and so on.
//
// derivePhase drives every block on the admin detail page, so a combination it could not
// map would either render nothing or crash the route. These cases pin that it is TOTAL.

/** The 12 members of the `Phase` union, written out so the check is a real allow-list. */
const ALL_PHASES: Phase[] = [
  "awaiting_client_submission",
  "awaiting_skill_run",
  "awaiting_review",
  "awaiting_validation_send",
  "awaiting_client_validation",
  "awaiting_context_pack",
  "awaiting_research_start",
  "in_research",
  "awaiting_report_upload",
  "awaiting_results_send",
  "completed",
  "archived",
];

/** Every `nestor.intake_status` value — the backend enum, mirrored. */
const ALL_STATUSES = [
  "draft",
  "submitted",
  "reviewed",
  "validated_by_client",
  "decomposed",
  "in_research",
  "delivered",
  "archived",
];

/** The four combinations of the two artifact markers the override can strand. */
const ARTIFACT_COMBOS: Array<{
  label: string;
  context_pack_artifact_id: string | null;
  final_report_artifact_id: string | null;
}> = [
  { label: "no artifacts", context_pack_artifact_id: null, final_report_artifact_id: null },
  { label: "context pack only", context_pack_artifact_id: "cp-1", final_report_artifact_id: null },
  { label: "report only", context_pack_artifact_id: null, final_report_artifact_id: "rp-1" },
  { label: "both artifacts", context_pack_artifact_id: "cp-1", final_report_artifact_id: "rp-1" },
];

describe("derivePhase — total over every status × artifact combination (D-23.5-01)", () => {
  for (const status of ALL_STATUSES) {
    for (const combo of ARTIFACT_COMBOS) {
      for (const run of [null, runRunning, runSucceededUnapplied, runSucceededApplied]) {
        for (const hasArtifacts of [false, true]) {
          it(`${status} + ${combo.label} + run=${run?.status ?? "none"} + artifacts=${hasArtifacts} → a Phase member`, () => {
            const intake: PhaseIntakeInput = {
              ...baseIntake(status),
              context_pack_artifact_id: combo.context_pack_artifact_id,
              final_report_artifact_id: combo.final_report_artifact_id,
            };
            // Not throwing is half the claim — the other half is that the value is a
            // member of the union, not an arbitrary string that would silently render
            // no block at all.
            const phase = derivePhase(intake, run, hasArtifacts);
            expect(ALL_PHASES).toContain(phase);
          });
        }
      }
    }
  }
});

describe("derivePhase — the shapes a backwards override leaves behind (D-23.5-01)", () => {
  // The operator's example: an intake that ran the whole way to `delivered` is overridden
  // back to `reviewed`. The report artifact and BOTH sent-at stamps survive the move — the
  // override changes the status column and nothing else. A real delivered intake has
  // `validation_link_sent_at` set (it passed through the validation step to get there), so
  // the `reviewed` branch reads it and lands on awaiting_client_validation: the page shows
  // "waiting for the client", which is the sane banner for a status that was just rewound.
  it("delivered → reviewed override (validation link already sent) → awaiting_client_validation", () => {
    const intake: PhaseIntakeInput = {
      status: "reviewed",
      validation_link_sent_at: TS,
      results_link_sent_at: TS,
      context_pack_artifact_id: "cp-1",
      final_report_artifact_id: "rp-1",
    };
    expect(derivePhase(intake, null, true)).toBe<Phase>("awaiting_client_validation");
  });

  // The same rewind on an intake whose validation link was never stamped (possible once the
  // override can also jump FORWARD past the validation step). The banner then asks the
  // operator to send the validation link — again sane, and explicitly not a crash.
  it("reviewed with a report but no validation link → awaiting_validation_send", () => {
    const intake: PhaseIntakeInput = {
      status: "reviewed",
      validation_link_sent_at: null,
      results_link_sent_at: TS,
      context_pack_artifact_id: "cp-1",
      final_report_artifact_id: "rp-1",
    };
    expect(derivePhase(intake, null, true)).toBe<Phase>("awaiting_validation_send");
  });

  // Anything → `archived` is the override's other newly-reachable target (it was reachable
  // from NOWHERE before this plan). It must land on the archived phase regardless of what
  // artifacts the intake accumulated first.
  it("archived keeps its phase whatever artifacts are present", () => {
    for (const combo of ARTIFACT_COMBOS) {
      const intake: PhaseIntakeInput = {
        ...baseIntake("archived"),
        context_pack_artifact_id: combo.context_pack_artifact_id,
        final_report_artifact_id: combo.final_report_artifact_id,
      };
      expect(derivePhase(intake, runSucceededApplied, true)).toBe<Phase>("archived");
    }
  });
});
