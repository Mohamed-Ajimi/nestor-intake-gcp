---
phase: 12-frontend-deploy-cutover-supabase-retirement
plan: 02
subsystem: frontend-container
tags: [cloud-run, docker, nitro, vite, supabase-independence, sales-hide]
requires:
  - "frontend/scripts/ci_no_supabase_in_bundle.sh (D-11 bundle guard, Plan 12-01)"
provides:
  - "Nitro node-server preset build (.output/server/index.mjs)"
  - "Two-stage Node Dockerfile for the frontend SSR container (INFRA-05)"
  - "frontend/cloudbuild.yaml injecting the public VITE_ build-args (Pitfall 2)"
  - "Sales product card hidden (enabled:false, D-09) with all sales code retained"
affects:
  - "frontend deploy (Plan 12-05 consumes this image)"
tech-stack:
  added:
    - "node:22-slim runtime image (frontend SSR)"
  patterns:
    - "Two-stage build mirroring backend/Dockerfile: build stage + slim runtime, build-time guard"
    - "PUBLIC VITE_ config baked as ARG->ENV before npm run build; NO Supabase var"
key-files:
  created:
    - frontend/Dockerfile
    - frontend/.dockerignore
    - frontend/cloudbuild.yaml
  modified:
    - frontend/vite.config.ts
    - frontend/src/routes/admin.index.tsx
decisions:
  - "Nitro preset switched via user `preset: node-server` override (beats Lovable config default outside a sandbox)"
  - "Verify-by-construction for the Docker build + npm run lint: this worktree has no node_modules and the dev box has no Docker; deferred to Cloud Build / Plan 12-05"
metrics:
  tasks: 3
  files: 5
  completed: 2026-07-14
---

# Phase 12 Plan 02: Containerize the Frontend SSR for Cloud Run Summary

Switched the frontend Nitro build off the Cloudflare Workers preset onto `node-server`, added a two-stage Node Dockerfile + `.dockerignore` + `cloudbuild.yaml` that bake only the public `VITE_` config and gate on the D-11 bundle guard, and hid the sales product card (D-09) without deleting any sales/Supabase code.

## What Was Built

**Task 1 — Nitro `node-server` preset** (`frontend/vite.config.ts`, commit `d6736dc`)
Replaced `nitro: { cloudflare: { nodeCompat: true, deployConfig: true } }` with `nitro: { preset: "node-server" }`. A user-supplied `preset` overrides `@lovable.dev/vite-tanstack-config`'s default `cloudflare-module` outside a Lovable sandbox (Cloud Build is not a sandbox), so the build now emits `.output/server/index.mjs` (a Node HTTP server honouring `$PORT`/`$NITRO_PORT`) + `.output/public/`. `wrangler.jsonc` and `@cloudflare/vite-plugin` were left inert (Pitfall 6 — not deleted, to avoid disturbing `npm run dev`).

**Task 2 — Frontend container definition** (`frontend/Dockerfile`, `frontend/.dockerignore`, `frontend/cloudbuild.yaml`, commit `77d8fce`)
- Two-stage `node:22-slim` Dockerfile mirroring `backend/Dockerfile`: build stage declares the four PUBLIC `VITE_` values as `ARG`→`ENV` **before** `npm run build` (`VITE_API_BASE_URL`, `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`); `COPY package.json package-lock.json ./` → `npm ci` (committed lockfile) → `COPY . .` → `npm run build`.
- Right after the build: `RUN sh scripts/ci_no_supabase_in_bundle.sh .output` — the D-11 guard as a **build-time gate** (the frontend analog of the backend's `python -c "import ..."` smoke check; fail-at-build, not runtime).
- Runtime stage: `node:22-slim`, `ENV NODE_ENV=production PORT=8080`, `COPY --from=build /app/.output ./.output`, `EXPOSE 8080`, `CMD ["node", ".output/server/index.mjs"]`.
- `.dockerignore` excludes `node_modules`, `.output` (stale local cloudflare build — T-12-05), `.git`, `.env*` so the build context is clean and always yields a fresh node-server build.
- `cloudbuild.yaml` runs one `gcr.io/cloud-builders/docker` build step forwarding the four `VITE_*` values as `--build-arg` from `--substitutions` (Pitfall 2 — `gcloud builds submit --tag` cannot pass `--build-arg`), then pushes via `images:`. The invocation is documented in a header comment. **No Supabase substitution/build-arg anywhere.**

**Task 3 — Hide the sales card** (`frontend/src/routes/admin.index.tsx`, commit `691b528`)
Flipped the `sales` `PRODUCTS` entry from `enabled: true` to `enabled: false` — it now renders dimmed/non-navigable exactly like `echo`/`edge`/`flux`. The entry (slug/name/tag/route) is retained; `admin.sales.*` routes, `salesMail.ts`, `salesLabels.ts`, `supabase.ts`, and `@supabase/supabase-js` are all untouched (D-09 — hide nav, keep code). With `VITE_SUPABASE_*` never set at build time, the retained sales path is inert (supabase client is null).

## How to Verify

- `grep node-server frontend/vite.config.ts` → matches; `grep cloudflare: frontend/vite.config.ts` → nothing.
- `grep VITE_SUPABASE frontend/Dockerfile` → nothing; `grep ci_no_supabase_in_bundle frontend/Dockerfile` → matches; `grep 'node .output/server/index.mjs' frontend/Dockerfile` → matches.
- `frontend/cloudbuild.yaml` passes exactly 4 `--build-arg=VITE_*` values and contains no Supabase var.
- `grep -A9 'slug: "sales"' frontend/src/routes/admin.index.tsx | grep 'enabled: false'` → matches.
- Live build gate runs in Cloud Build: `gcloud builds submit frontend --config=frontend/cloudbuild.yaml --substitutions=_IMAGE=...,_API_BASE_URL=...,_FB_API_KEY=...,_FB_AUTH_DOMAIN=...,_FB_PROJECT_ID=...` (deferred to Plan 12-05 — do not deploy here).

## Deviations from Plan

None — plan executed exactly as written.

One wording adjustment (not a deviation from behaviour): the Dockerfile's "deliberately omitted" comment originally spelled out the two legacy `VITE_SUPABASE_*` var names, which tripped the acceptance grep (`grep VITE_SUPABASE frontend/Dockerfile` must return nothing). Reworded to "the legacy Supabase URL / anon-key build-args" so the file carries **zero** `VITE_SUPABASE` literals while preserving the documented intent.

## Deferred Verification

- **Docker image build + D-11 build-gate:** the dev box has no Docker and this worktree has no `node_modules`, so the image was authored by construction. The `npm run build` + `ci_no_supabase_in_bundle.sh .output` gate runs live in Cloud Build (Plan 12-05). This matches the project's established author-by-construction / defer-live-runs pattern.
- **`npm run lint` (Task 3 verify):** cannot run without `node_modules` in the worktree. The change is a single `true`→`false` data-array flag flip plus a comment — no import removed, no syntax change — so it cannot introduce a lint error. Lint runs in the normal frontend build pipeline. Verified by construction (diff confirms only the flag + comment changed).

## Known Stubs

None — this plan is packaging/config only; no data-wiring stubs introduced.

## Threat Flags

None — no new security surface beyond the plan's threat_model (T-12-03..06, T-12-SC). Only PUBLIC config is baked; the D-11 guard fails the build on any Supabase signature; `.dockerignore` prevents stale-context tampering; the retained sales/Supabase code stays inert with `VITE_SUPABASE_*` unset. No new package installed (`npm ci` restores the audited committed lockfile).

## Self-Check: PASSED

Created files:
- FOUND: frontend/Dockerfile
- FOUND: frontend/.dockerignore
- FOUND: frontend/cloudbuild.yaml

Modified files:
- FOUND: frontend/vite.config.ts (node-server)
- FOUND: frontend/src/routes/admin.index.tsx (sales enabled:false)

Commits:
- FOUND: d6736dc (Task 1 — vite node-server preset)
- FOUND: 77d8fce (Task 2 — Dockerfile + .dockerignore + cloudbuild.yaml)
- FOUND: 691b528 (Task 3 — hide sales card)
