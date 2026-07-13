import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/storage.ts — the typed storage seam over the Phase-5
// token-attaching transport (`apiFetch` in client.ts). It replaces every direct
// browser→`supabase.storage` call on the intake surface with a backend-mediated
// path, so the anon-key browser→storage route is removed (T-06-27).
//
// SCOPE: finalized in Phase 9. The browser NEVER authors an object key or names a
// storage container (DOC-02 / D-05): uploads send only the `file` and a `category`,
// and the backend authors the stored key ({space}/{intake}/{category}/{uuid}-{name}).
// Delete and signed-url are intake-scoped — the seam carries the `intakeId` and
// the server enforces ownership + prefix. All calls surface a typed
// `ApiResult.error` (the UI shows the error via toast and degrades gracefully —
// no throw, no direct storage).
//
// Mirrors `intakes.ts` / `admin.ts`: import the transport, never fork it.

/** Metadata returned by the backend after a successful upload. */
export type UploadedFileMeta = {
  path: string;
  filename: string;
  size: number;
  uploaded_at: string;
  mime_type?: string | null;
};

/** A short-lived signed download URL minted by the backend. */
export type SignedDownloadUrl = {
  url: string;
  expires_in: number;
};

/**
 * Upload a single file through the backend storage seam.
 *
 * The browser sends only the `file` and a `category` — the server authors the
 * stored key (DOC-02 / D-05). The multipart boundary is set by the browser
 * because `apiFetch` skips the JSON Content-Type default for FormData bodies.
 */
export function uploadFile(args: {
  intakeId: string;
  file: Blob;
  filename: string;
  category: string;
  contentType?: string;
}): Promise<ApiResult<UploadedFileMeta>> {
  const form = new FormData();
  form.append("file", args.file, args.filename);
  form.append("category", args.category);
  if (args.contentType) form.append("content_type", args.contentType);
  return apiFetch<UploadedFileMeta>(
    `/intakes/${encodeURIComponent(args.intakeId)}/storage/uploads`,
    { method: "POST", body: form },
  );
}

/**
 * Remove one or more stored objects through the backend storage seam.
 * Fire-and-forget friendly: callers may ignore the result for cleanup.
 * Intake-scoped — the server enforces ownership + prefix on each path.
 */
export function removeFile(args: {
  intakeId: string;
  paths: string[];
}): Promise<ApiResult<{ removed: number }>> {
  return apiFetch<{ removed: number }>(
    `/intakes/${encodeURIComponent(args.intakeId)}/storage/objects`,
    {
      method: "DELETE",
      body: JSON.stringify({ paths: args.paths }),
    },
  );
}

/**
 * Mint a short-lived signed download URL through the backend storage seam.
 * Replaces the legacy direct-storage `createSignedUrl(path, ttl)` call.
 * Intake-scoped — the server enforces ownership + prefix on the requested path.
 */
export function signedDownloadUrl(args: {
  intakeId: string;
  path: string;
  expiresIn?: number;
}): Promise<ApiResult<SignedDownloadUrl>> {
  const params = new URLSearchParams({
    path: args.path,
    expires_in: String(args.expiresIn ?? 300),
  });
  return apiFetch<SignedDownloadUrl>(
    `/intakes/${encodeURIComponent(args.intakeId)}/storage/signed-url?${params.toString()}`,
    { method: "GET" },
  );
}
