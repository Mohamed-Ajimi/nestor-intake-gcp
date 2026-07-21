// Phase-machine for the intake detail page.
// Pure helper — no React, no Supabase.

export type Phase =
  | "awaiting_client_submission"
  | "awaiting_skill_run"
  | "awaiting_review"
  | "awaiting_validation_send"
  | "awaiting_client_validation"
  | "awaiting_context_pack"
  | "awaiting_research_start"
  | "in_research"
  | "awaiting_report_upload"
  | "awaiting_results_send"
  | "completed"
  | "archived";

export type PhaseIntakeInput = {
  status: string | null;
  validation_link_sent_at: string | null;
  results_link_sent_at: string | null;
  context_pack_artifact_id: string | null;
  final_report_artifact_id: string | null;
};

export type PhaseSkillRunInput = {
  status: string | null;
  applied_at: string | null;
} | null;

export function derivePhase(
  intake: PhaseIntakeInput,
  latestIntakeSkillRun: PhaseSkillRunInput,
  hasResearchArtifacts: boolean,
): Phase {
  const status = intake.status ?? "draft";

  if (status === "draft") return "awaiting_client_submission";

  if (status === "submitted") {
    if (!latestIntakeSkillRun || latestIntakeSkillRun.status !== "succeeded") {
      return "awaiting_skill_run";
    }
    if (!latestIntakeSkillRun.applied_at) return "awaiting_review";
    // skill applied but status not yet bumped — treat as validation_send
    return "awaiting_validation_send";
  }

  if (status === "reviewed") {
    return intake.validation_link_sent_at
      ? "awaiting_client_validation"
      : "awaiting_validation_send";
  }

  if (status === "validated_by_client") {
    return intake.context_pack_artifact_id
      ? "awaiting_research_start"
      : "awaiting_context_pack";
  }

  if (status === "decomposed") {
    return hasResearchArtifacts ? "in_research" : "awaiting_research_start";
  }

  if (status === "in_research") {
    // Phase 16 (RUN-01, Pitfall 6/10): the `in_research` visibility is now driven by the
    // intake STATUS alone — the mirrored `research_runs` row (not `research_artifacts`) is
    // this flow's progress source, and there is NO artifact writer this milestone, so
    // `hasResearchArtifacts` stays false and this branch returns `in_research`. This change
    // is ADDITIVE: the `final_report_artifact_id` and `hasResearchArtifacts` branches below
    // are retained for the later (Phase 18+) report-upload flow. A merely-COMPLETED research
    // run does NOT auto-advance to `awaiting_report_upload` — that transition is owned by the
    // report-upload phase, not by run completion.
    if (intake.final_report_artifact_id) return "awaiting_results_send";
    if (hasResearchArtifacts) return "awaiting_report_upload";
    return "in_research";
  }

  if (status === "delivered") {
    return intake.results_link_sent_at ? "completed" : "awaiting_results_send";
  }

  return "archived";
}

// Visibility-helpers gebruikt door de detail-route
export function phaseShowsIntakeSections(phase: Phase): boolean {
  return phase !== "awaiting_client_submission";
}
export function phaseShowsAIReview(phase: Phase): boolean {
  return phase === "awaiting_review";
}
export function phaseShowsContextPack(phase: Phase): boolean {
  return [
    "awaiting_research_start",
    "in_research",
    "awaiting_report_upload",
    "awaiting_results_send",
    "completed",
    "archived",
  ].includes(phase);
}
export function phaseShowsResearch(phase: Phase): boolean {
  return [
    "in_research",
    "awaiting_report_upload",
    "awaiting_results_send",
    "completed",
    "archived",
  ].includes(phase);
}
export function phaseShowsFinalReport(phase: Phase): boolean {
  return [
    "awaiting_report_upload",
    "awaiting_results_send",
    "completed",
    "archived",
  ].includes(phase);
}
export function phaseShowsSemanticSearch(phase: Phase): boolean {
  return phaseShowsResearch(phase);
}
