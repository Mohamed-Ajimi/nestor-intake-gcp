import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/storage.ts — the typed storage seam over the Phase-5
// token-attaching transport (`apiFetch` in client.ts). It replaces every direct
// browser→`supabase.storage` call on the intake surface with a backend-mediated
// path, so the anon-key browser→storage route is removed (T-06-27).
//
// SCOPE: this is a Phase-9 SEAM STUB. The real GCS signed-URL / upload backend
// lands in Phase 9; until then these functions route through `apiFetch` against
// the agreed endpoint shapes and surface a typed `ApiResult.error` (the UI shows
// the error via toast and degrades gracefully — no throw, no direct storage).
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
 * Phase-9 backend endpoint (not yet implemented): the seam returns
 * `ApiResult.error` until then, which the caller surfaces via toast.
 * Multipart wiring (boundary Content-Type) is finalized in Phase 9.
 */
export function uploadFile(args: {
  intakeId: string;
  bucket: string;
  path: string;
  file: Blob;
  filename: string;
  contentType?: string;
}): Promise<ApiResult<UploadedFileMeta>> {
  const form = new FormData();
  form.append("file", args.file, args.filename);
  form.append("bucket", args.bucket);
  form.append("path", args.path);
  if (args.contentType) form.append("content_type", args.contentType);
  return apiFetch<UploadedFileMeta>(
    `/intakes/${encodeURIComponent(args.intakeId)}/storage/uploads`,
    { method: "POST", body: form },
  );
}

/**
 * Remove one or more stored objects through the backend storage seam.
 * Fire-and-forget friendly: callers may ignore the result for cleanup.
 */
export function removeFile(args: {
  bucket: string;
  paths: string[];
}): Promise<ApiResult<{ removed: number }>> {
  return apiFetch<{ removed: number }>("/storage/objects", {
    method: "DELETE",
    body: JSON.stringify({ bucket: args.bucket, paths: args.paths }),
  });
}

/**
 * Mint a short-lived signed download URL through the backend storage seam.
 * Replaces `supabase.storage.from(bucket).createSignedUrl(path, ttl)`.
 */
export function signedDownloadUrl(args: {
  bucket: string;
  path: string;
  expiresIn?: number;
}): Promise<ApiResult<SignedDownloadUrl>> {
  const params = new URLSearchParams({
    bucket: args.bucket,
    path: args.path,
    expires_in: String(args.expiresIn ?? 300),
  });
  return apiFetch<SignedDownloadUrl>(`/storage/signed-url?${params.toString()}`, {
    method: "GET",
  });
}
