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
