import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/admin.ts — typed admin endpoint calls over the token-attaching
// `apiFetch` transport (client.ts). One thin function per plan-04 backend route; every
// function returns the `{success,error}|{success,data}` union from `apiFetch`.
//
// Types mirror the backend response models (admin_routes.py): UserView, SpaceView,
// TemplateView, InviteResult. role/space_id here are DISPLAY-ONLY — no authorization
// decision is ever made from these client-side values (T-5-18).

// ---------------------------------------------------------------------------
// Types (mirror backend admin_routes.py response models)
// ---------------------------------------------------------------------------

export type AdminUser = {
  id: string; // membership id
  email: string | null;
  space_id: string;
  role: string;
  status: "active" | "deactivated" | string;
};

export type InviteResult = {
  uid: string;
  space_id: string;
  action_link: string;
};

export type Space = {
  id: string;
  name: string;
  slug: string | null;
  status: "active" | "deactivated" | string;
};

export type Template = {
  id: string;
  space_id: string;
  name: string;
  schema: Record<string, unknown> | null;
};

// ---------------------------------------------------------------------------
// Users — invite / list / deactivate / reactivate
// ---------------------------------------------------------------------------

/**
 * Invite a user into a space. Role is server-fixed to "user" (not sent / not selectable).
 * On success returns the one-time set-password action link (D-03) — never a password/token.
 * Backend returns 409 (duplicate active membership) → mapped to copy in the dialog.
 */
export function inviteUser(input: { email: string; spaceId: string }): Promise<ApiResult<InviteResult>> {
  return apiFetch<InviteResult>("/admin/users", {
    method: "POST",
    body: JSON.stringify({ email: input.email, space_id: input.spaceId }),
  });
}

export function listUsers(): Promise<ApiResult<AdminUser[]>> {
  return apiFetch<AdminUser[]>("/admin/users", { method: "GET" });
}

export function deactivateUser(membershipId: string): Promise<ApiResult<AdminUser>> {
  return apiFetch<AdminUser>(`/admin/users/${membershipId}/deactivate`, { method: "POST" });
}

export function reactivateUser(membershipId: string): Promise<ApiResult<AdminUser>> {
  return apiFetch<AdminUser>(`/admin/users/${membershipId}/reactivate`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Spaces — list / create / update / deactivate / reactivate (NO delete)
// ---------------------------------------------------------------------------

export function listSpaces(): Promise<ApiResult<Space[]>> {
  return apiFetch<Space[]>("/admin/spaces", { method: "GET" });
}

export function createSpace(input: { name: string; slug?: string }): Promise<ApiResult<Space>> {
  return apiFetch<Space>("/admin/spaces", {
    method: "POST",
    body: JSON.stringify({ name: input.name, slug: input.slug ?? null }),
  });
}

export function updateSpace(
  id: string,
  input: { name?: string; slug?: string },
): Promise<ApiResult<Space>> {
  return apiFetch<Space>(`/admin/spaces/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deactivateSpace(id: string): Promise<ApiResult<Space>> {
  return apiFetch<Space>(`/admin/spaces/${id}/deactivate`, { method: "POST" });
}

export function reactivateSpace(id: string): Promise<ApiResult<Space>> {
  return apiFetch<Space>(`/admin/spaces/${id}/reactivate`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Templates — list / clone / edit-schema (NO delete)
// ---------------------------------------------------------------------------

export function listTemplates(spaceId: string): Promise<ApiResult<Template[]>> {
  return apiFetch<Template[]>(`/admin/spaces/${spaceId}/templates`, { method: "GET" });
}

/**
 * Clone a default template into a space. The backend clone body is
 * `{ name, schema?, source_template_id? }` — the operator supplies the new template's
 * name (and either a source template to copy or an inline schema).
 */
export function cloneTemplate(
  spaceId: string,
  input: { name: string; sourceTemplateId?: string; schema?: Record<string, unknown> },
): Promise<ApiResult<Template>> {
  return apiFetch<Template>(`/admin/spaces/${spaceId}/templates`, {
    method: "POST",
    body: JSON.stringify({
      name: input.name,
      source_template_id: input.sourceTemplateId ?? null,
      schema: input.schema ?? null,
    }),
  });
}

export function updateTemplate(
  spaceId: string,
  templateId: string,
  schema: Record<string, unknown>,
): Promise<ApiResult<Template>> {
  return apiFetch<Template>(`/admin/spaces/${spaceId}/templates/${templateId}`, {
    method: "PATCH",
    body: JSON.stringify({ schema }),
  });
}
