import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/templates.ts — intake template projection over the
// token-attaching `apiFetch` transport. Mirrors `admin.ts`: never fork the transport.

/** Mirrors the backend `TemplateView` (intake_routes.py). */
export type Template = {
  id: string;
  space_id: string;
  name: string;
  schema: Record<string, unknown> | null;
};

/** List the intake templates visible to the current identity. */
export function getTemplates(): Promise<ApiResult<Template[]>> {
  return apiFetch<Template[]>("/intakes/templates", { method: "GET" });
}
