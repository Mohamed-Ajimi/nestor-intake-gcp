// frontend/src/lib/research/statusLabel.ts — the ONE run-status label definition (Phase 23.6).
//
// Moved verbatim from the private copy in `routes/admin.pulse.runs.$runId.index.tsx` so the
// run page and the intake-page run history (UI-SPEC) share one definition. Do not write a
// second copy. The `t` passed in must be bound to the `intake` namespace (the keys live under
// `research.runPage.status.*` there).

/**
 * All EIGHT run statuses (D-11), each a literal `t()` call so the i18n audit's CHECK B
 * actually covers them, plus a fallback so a status this build has never heard of still
 * renders words rather than a raw key.
 */
export function statusLabel(status: string, t: (key: string) => string): string {
  switch (status) {
    case "queued":
      return t("research.runPage.status.queued");
    case "running":
      return t("research.runPage.status.running");
    case "completed":
      return t("research.runPage.status.completed");
    case "completed_degraded":
      return t("research.runPage.status.completedDegraded");
    case "failed":
      return t("research.runPage.status.failed");
    case "cancelled":
      return t("research.runPage.status.cancelled");
    case "parked":
      return t("research.runPage.status.parked");
    case "needs_input":
      return t("research.runPage.status.needsInput");
    default:
      return t("research.runPage.status.unknown");
  }
}
