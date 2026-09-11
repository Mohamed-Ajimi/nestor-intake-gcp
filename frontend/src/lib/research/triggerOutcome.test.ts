import { describe, expect, it } from "vitest";

import type { ApiResult } from "@/lib/api/client";
import type { TriggerResearchResponse } from "@/lib/api/research";
import { classifyTriggerOutcome } from "@/lib/research/triggerOutcome";

/**
 * D-23.4-07 — the over-cap trigger must never read as success.
 *
 * The backend answers an over-cap trigger with HTTP **202** and a body of
 * `{"research_run_id": null, "status": "needs_investigation", "attempts": N}`. Because it
 * is a 202 and not a 4xx, `ApiResult.success` is `true`, so the two call sites that only
 * branched on `success` showed a green toast and did nothing. This suite pins the
 * classifier that both of them now route through.
 *
 * The discriminator is the ABSENCE of a `research_run_id`, NOT the `status` string: a
 * server-side relabelling must not be able to resurrect the silent branch.
 */
describe("classifyTriggerOutcome", () => {
  it("classifies a transport/HTTP failure as error", () => {
    const res: ApiResult<TriggerResearchResponse> = {
      success: false,
      error: "Research is already running for this intake",
    };
    expect(classifyTriggerOutcome(res)).toBe("error");
  });

  it("classifies a 202 carrying a run id as started", () => {
    const res: ApiResult<TriggerResearchResponse> = {
      success: true,
      data: { research_run_id: "abc", status: undefined },
    };
    expect(classifyTriggerOutcome(res)).toBe("started");
  });

  it("classifies the over-cap 202 body as needs_investigation", () => {
    const res: ApiResult<TriggerResearchResponse> = {
      success: true,
      data: { research_run_id: null, status: "needs_investigation", attempts: 3 },
    };
    expect(classifyTriggerOutcome(res)).toBe("needs_investigation");
  });

  it("classifies a 202 with no run id and no status as needs_investigation", () => {
    const res: ApiResult<TriggerResearchResponse> = {
      success: true,
      data: { research_run_id: null },
    };
    expect(classifyTriggerOutcome(res)).toBe("needs_investigation");
  });

  it("lets a real run id win over a needs_investigation label", () => {
    const res: ApiResult<TriggerResearchResponse> = {
      success: true,
      data: { research_run_id: "abc", status: "needs_investigation" },
    };
    expect(classifyTriggerOutcome(res)).toBe("started");
  });
});
