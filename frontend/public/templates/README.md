# Shared template assets (static)

Files under `frontend/public/templates/` are served by vite at the URL root, e.g.
`frontend/public/templates/NDA/Agenic-Nestor-Overeenkomst.pdf` → `/templates/NDA/Agenic-Nestor-Overeenkomst.pdf`.

These are **shared, non-tenant** documents (NDA / service agreement, etc.). They are NOT
intake-scoped uploads, so they must NOT go through the space-scoped signed-URL storage seam
(which correctly 404s a shared `templates/...` path — see D-05/D-08). `DownloadControl`
(`frontend/src/components/intake/FieldRenderer.tsx`) detects a `templates/`-prefixed
`storage_path` and opens the static URL directly instead of requesting a signed URL.

## Expected files

The canonical intake template (`backend/app/data/pulse_intake_v1.json`, field `nda_download`)
points at:

- `NDA/Agenic-Nestor-Overeenkomst.pdf` — the Agenic × Nestor service agreement PDF.

Drop the actual PDF binary at `frontend/public/templates/NDA/Agenic-Nestor-Overeenkomst.pdf`.
It is not committed to the repo (it lived in the legacy Supabase `nestor-uploads` bucket);
the operator places it here as a static asset. Until it is present, the download button opens
`/templates/NDA/Agenic-Nestor-Overeenkomst.pdf` and the browser surfaces its own 404 — no
false storage-error toast is shown.
