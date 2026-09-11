import type { ApiResult } from "@/lib/api/client";
import type { TriggerResearchResponse } from "@/lib/api/research";

/**
 * What actually happened when a research trigger came back (D-23.4-07).
 *
 * `POST /intakes/{id}/research` answers an over-cap trigger with HTTP **202** and
 * `{"research_run_id": null, "status": "needs_investigation", "attempts": N}` — NOT a 4xx.
 * So `ApiResult.success` is `true` for a run that was refused, and the two call sites that
 * branched on `success` alone showed a success toast and reloaded, which read to the
 * operator as "started, nothing to see". Three outcomes, not two.
 *
 * This is a PURE module on purpose: no React, no i18n, no network. `vitest.config.ts`
 * includes only `src/**\/*.test.ts` in a `node` environment (no jsdom, no `.tsx`), so the
 * branch is only testable at all if it lives outside the components that call it.
 */
export type TriggerOutcome = "started" | "needs_investigation" | "error";

/**
 * Classify a trigger response. Rule order, and it matters:
 *
 * 1. A transport/HTTP failure is `"error"` — nothing else can be read from it.
 * 2. A truthy `research_run_id` is `"started"`.
 * 3. Everything else is `"needs_investigation"`.
 *
 * The discriminator is the ABSENCE of a run id, NOT the `status` string. A body carrying a
 * run id is a started run whatever the server labelled it (the id is the thing the UI
 * navigates to), and a body carrying none is not something to report as success — so a
 * future server-side relabelling cannot resurrect the silent branch.
 */
export function classifyTriggerOutcome(
  res: ApiResult<TriggerResearchResponse>,
): TriggerOutcome {
  if (!res.success) return "error";
  if (res.data?.research_run_id) return "started";
  return "needs_investigation";
}
