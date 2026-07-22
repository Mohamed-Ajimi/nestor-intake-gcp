import { apiFetch, type ApiResult } from "@/lib/api/client";
import { withActiveSpace } from "@/lib/active-space";

// frontend/src/lib/api/intakes.ts — typed intake endpoint calls over the
// token-attaching `apiFetch` transport (client.ts). One thin function per plan-03
// backend route; every function returns the `ApiResult<T>` union from `apiFetch`.
//
// Mirrors `admin.ts`: import the transport, never fork it. Read paths thread
// `withActiveSpace(...)` — the superadmin view-filter (UX state only, T-06-13).

/**
 * Mirrors the backend `IntakeView` (intake_routes.py): `status` plus all FIVE phase
 * markers that `derivePhase` (intake-phase.ts) consumes.
 */
export type Intake = {
  id: string;
  space_id: string;
  status: string;
  client_name: string | null;
  validation_link_sent_at: string | null;
  results_link_sent_at: string | null;
  context_pack_artifact_id: string | null;
  final_report_artifact_id: string | null;
};

// ---------------------------------------------------------------------------
// CRUD — list / get / create / patch
// ---------------------------------------------------------------------------

/** List intakes (superadmin view filtered by the active space when set). */
export function listIntakes(): Promise<ApiResult<Intake[]>> {
  return apiFetch<Intake[]>(withActiveSpace("/intakes"), { method: "GET" });
}

export function getIntake(id: string): Promise<ApiResult<Intake>> {
  return apiFetch<Intake>(`/intakes/${id}`, { method: "GET" });
}

/**
 * Create a new intake. The backend injects `space_id` from the verified identity
 * (TENANT-02) — never sent from the client — and starts the intake in `draft`.
 */
export function createIntake(input: {
  client_name?: string;
}): Promise<ApiResult<Intake>> {
  // Thread the active space (superadmin view-filter): a superadmin has no own space, so the
  // backend creates the intake into the SELECTED client (?space_id, honored superadmin-only).
  // For a regular user the param is inert — the backend forces their own token-derived space.
  return apiFetch<Intake>(withActiveSpace("/intakes"), {
    method: "POST",
    body: JSON.stringify({ client_name: input.client_name ?? null }),
  });
}

/** Patch mutable intake fields. `client_name` only — status moves via the transition verbs. */
export function patchIntake(
  id: string,
  input: { client_name: string },
): Promise<ApiResult<Intake>> {
  return apiFetch<Intake>(`/intakes/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ client_name: input.client_name }),
  });
}

// ---------------------------------------------------------------------------
// Transitions — discrete allow-listed status verbs (empty body tolerated)
// ---------------------------------------------------------------------------

/** Advance the intake (draft→submitted, or reviewed→validated_by_client). */
export function submitIntake(id: string): Promise<ApiResult<Intake>> {
  return apiFetch<Intake>(`/intakes/${id}/submit`, { method: "POST" });
}

/** Mark a submitted intake as reviewed (submitted→reviewed). */
export function reviewIntake(id: string): Promise<ApiResult<Intake>> {
  return apiFetch<Intake>(`/intakes/${id}/review`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Report delivery — the human-report deliver / replace / read verbs (Plan 18-01)
// ---------------------------------------------------------------------------
//
// The Deliver verb is the SOLE `in_research -> delivered` transition (REPORT-01):
// uploading only STAGES a PDF (client-invisible); this call flips the status and
// sends the results-family mail. `replaceReport` repoints the report post-delivery
// (status stays `delivered`, D-04) with an OPTIONAL re-notify (recipients=[] = silent,
// D-05). `getReport` reads the delivered report view (404 unless status=='delivered').
//
// SECURITY (D-06): `recipients` are server-issued membership ids (never addresses) —
// the RecipientPicker's output; the backend re-validates each id. The WIRE body is
// snake_case (`storage_path`), NOT camelCase — mirror the backend `DeliverBody`.

/**
 * The delivered-report view returned by `GET /intakes/{id}/report` (mirrors the
 * backend `ReportView`, intake_routes.py). `delivered_at` mirrors the intake's
 * `results_link_sent_at`. All fields are nullable per the backend contract.
 */
export type ReportView = {
  filename: string | null;
  delivered_at: string | null;
  byte_size: number | null;
  mime_type: string | null;
  storage_path: string | null;
};

/**
 * Deliver the staged report (the sole `in_research -> delivered` transition, REPORT-01).
 * Links the staged storage key as the intake's final report, flips the status, and sends
 * the results-family mail to the selected members. `recipients` are membership ids (D-06);
 * the wire body is snake_case (`storage_path`).
 */
export function deliverReport(
  id: string,
  input: { storagePath: string; recipients: string[] },
): Promise<ApiResult<Intake>> {
  return apiFetch<Intake>(`/intakes/${id}/deliver`, {
    method: "POST",
    body: JSON.stringify({
      storage_path: input.storagePath,
      recipients: input.recipients,
    }),
  });
}

/**
 * Replace an already-delivered report (status stays `delivered`, D-04). Repoints
 * `final_report_artifact_id` to the newly staged key; `recipients` re-notifies the
 * selected members (D-05) — pass `[]` for a silent replace (no mail). The wire body
 * is the SAME snake_case shape as `deliverReport`.
 */
export function replaceReport(
  id: string,
  input: { storagePath: string; recipients: string[] },
): Promise<ApiResult<Intake>> {
  return apiFetch<Intake>(`/intakes/${id}/report/replace`, {
    method: "POST",
    body: JSON.stringify({
      storage_path: input.storagePath,
      recipients: input.recipients,
    }),
  });
}

/**
 * Read the delivered report view. 404 unless the intake status is exactly `delivered`
 * (REPORT-02 invisibility) — surfaced as `{ success: false }`.
 */
export function getReport(id: string): Promise<ApiResult<ReportView>> {
  return apiFetch<ReportView>(`/intakes/${id}/report`, { method: "GET" });
}

// ---------------------------------------------------------------------------
// Notification mail — members read + discrete send verbs (Plan 10-03/04)
// ---------------------------------------------------------------------------
//
// SECURITY (D-06 / T-10-11): the send endpoints take ONLY server-issued membership
// ids — never a free-text address. `listSpaceMembers` is the RecipientPicker's list
// source; the backend re-validates every id against the intake's OWN active memberships
// (a non-active-member id is a 422, never a silent drop).

/**
 * Active member of an intake's space. Mirrors the backend `MemberView`
 * (intake_routes.py `GET /intakes/{id}/members`). `name` is currently always
 * `null` (no name column on `organization_memberships`) — the picker labels on
 * `name ?? email`.
 */
export type SpaceMember = {
  id: string; // membership id — the send-endpoint recipient identifier
  // Backend `MemberView.email` is `str | None` (the DB column is nullable). The members
  // read now filters `email IS NOT NULL` server-side (WR-02), so in practice every row
  // here has a usable email — but the type mirrors the backend contract honestly.
  email: string | null;
  name?: string | null;
};

/** The four client-facing send verbs (mirrors the backend route suffixes). */
export type IntakeMailType = "intake" | "validation" | "reminder" | "results";

/** Bare success flag returned by the send endpoints (no link/token in the body). */
export type MailResult = { success: boolean };

/**
 * List the ACTIVE members of the intake's space — the RecipientPicker's source.
 * Hits `GET /intakes/{id}/members` (Plan 10-03 Task 1); a cross-space/unknown intake
 * id is a 404 (existence-hidden), surfaced as `{ success: false }`.
 */
export function listSpaceMembers(intakeId: string): Promise<ApiResult<SpaceMember[]>> {
  return apiFetch<SpaceMember[]>(`/intakes/${intakeId}/members`, { method: "GET" });
}

/**
 * Send a client-facing mail (intake / validation / reminder / results) to the selected
 * active members. `recipients` are membership ids (D-06 — never addresses); the
 * backend resolves the emails server-side and stamps the sent-at only on a 2xx send.
 */
export function sendIntakeMail(
  intakeId: string,
  type: IntakeMailType,
  recipients: string[],
): Promise<ApiResult<MailResult>> {
  return apiFetch<MailResult>(`/intakes/${intakeId}/mail/${type}`, {
    method: "POST",
    body: JSON.stringify({ recipients }),
  });
}
