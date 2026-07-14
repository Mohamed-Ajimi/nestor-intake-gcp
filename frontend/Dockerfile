# syntax=docker/dockerfile:1
#
# Nestor Intake (GCP re-platform) FRONTEND image — TanStack Start SSR on Cloud Run
# (INFRA-05). Two-stage build mirroring backend/Dockerfile: a build stage that
# runs the Nitro `node-server` build, then a slim runtime stage that runs the
# emitted Node HTTP server (`node .output/server/index.mjs`) on Cloud Run's $PORT.
#
# Public config baked at BUILD TIME (Pattern 2): Vite inlines `import.meta.env.VITE_*`
# into the client bundle at build time, so the public frontend config must be
# present as ARG/ENV BEFORE `npm run build`. The only values baked here are PUBLIC:
#   * VITE_API_BASE_URL       — the (public) Cloud Run backend origin
#   * VITE_FIREBASE_API_KEY   — Firebase web apiKey is a PUBLIC project identifier,
#                               NOT a secret (see frontend/src/lib/firebase.ts comment)
#   * VITE_FIREBASE_AUTH_DOMAIN / VITE_FIREBASE_PROJECT_ID — public Firebase config
#
# DELIBERATELY OMITTED (D-08/D-09): the legacy Supabase URL / anon-key build-args are
# NOT declared as ARG/ENV anywhere in this image. With those vars unset at build time,
# frontend/src/lib/supabase.ts keeps its client null and the retained sales/legacy code
# is inert. The D-11 bundle guard below then PROVES no Supabase signature survived into
# `.output/` — the big-bang cutover is only provably Supabase-independent when the
# shipped artifact carries no Supabase URL/key.

# ---------------------------------------------------------------------------
# Stage 1 — build: install deps from the committed lockfile, run the SSR build,
# then gate on the D-11 bundle guard (fail the build NOW, not at runtime).
# ---------------------------------------------------------------------------
FROM node:22-slim AS build

WORKDIR /app

# PUBLIC build-time config → promote each ARG to ENV so Vite inlines it during
# `npm run build`. NO Supabase var is declared here (deliberate — see header).
ARG VITE_API_BASE_URL
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY \
    VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN \
    VITE_FIREBASE_PROJECT_ID=$VITE_FIREBASE_PROJECT_ID

# Install from the COMMITTED lockfile for a reproducible build (npm ci, not
# npm install). Copy manifests first so the install layer caches across source edits.
COPY package.json package-lock.json ./
RUN npm ci

# Application source, then the Nitro node-server build (emits .output/server +
# .output/public). .dockerignore keeps the local (stale cloudflare) .output out of
# the context so this is always a fresh node-server build (T-12-05).
COPY . .
RUN npm run build

# D-11 bundle guard (INFRA-05 / T-12-04): fail the build if ANY Supabase signature
# reached the shipped bundle. This is the frontend analog of the backend Dockerfile's
# build-time `python -c "import ..."` smoke check — fail NOW, not at runtime.
RUN sh scripts/ci_no_supabase_in_bundle.sh .output

# ---------------------------------------------------------------------------
# Stage 2 — runtime: carry only the built .output and run the Node SSR server.
# ---------------------------------------------------------------------------
FROM node:22-slim

WORKDIR /app

# PORT defaulted to 8080 but Cloud Run overrides it — Nitro's node-server binds
# whatever $PORT (or $NITRO_PORT) is injected at runtime.
ENV NODE_ENV=production \
    PORT=8080

# Only the self-contained Nitro output ships (no node_modules, no source).
COPY --from=build /app/.output ./.output

EXPOSE 8080

# The ONE entrypoint: the Nitro node-server. It reads $PORT injected by Cloud Run.
CMD ["node", ".output/server/index.mjs"]
