# Phase 14: Auth Retirement + Integration Seam - Research

**Researched:** 2026-07-20
**Domain:** Retiring a standalone FastAPI auth stack + building a Cloud Run internal service-to-service seam (OIDC ID-token, space→tenant identity mapping, cross-tenant denial across an HTTP boundary)
**Confidence:** HIGH — grounded in both codebases read directly (intake `backend/`, re-homed `tribunal/`), the v1.1 `.planning/research/` set, and Phase 13's shipped artifacts (SUMMARY/REVIEW/PROOF).

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Retirement depth (in-repo copy ONLY)**
- **D-01 (copy-only scope — hard constraint):** All retirement/deletion applies ONLY to the copy in this repo (`tribunal/`). The original Tribunal+ADK app at `C:\Users\ajimimo\Desktop\MOELD\Nestor\` must stay intact and working — frozen reference per Phase 13 D-01, never edited or deleted (mirrors the v1.0 Supabase "independence-only" philosophy).
- **D-02 (hard-delete, not unmount):** In `tribunal/`, delete the retired files outright: `orgs/api.py`, `account/`, the `web/` static UI (incl. `Login.jsx`), `/api/auth/config`, `auth/identity_platform.py`, plus `firebase-admin` from requirements and `IDENTITY_PLATFORM_*` secrets/env from deploy scripts + IaC. Git history keeps everything recoverable.
- **D-03 (dev/eval surfaces retired in the same sweep):** The demo router, compare endpoints, and eval-oriented critique module are removed too — after Phase 14 the deployed API exposes only what the intake backend calls (runs, audit, sources, uploads, health). **Gate: the planner verifies the import graph before each deletion — anything `pipeline/` (or other kept code) imports stays.** Note: Phase 15's plan-critique is NEW pipeline code; do not confuse it with the deleted eval critique surface.
- Provisioning logic that survives (org/project rows created server-side) may be salvaged from `orgs/provision.py` internals even though the user-facing bootstrap endpoint is deleted.

**Internal trust model**
- **D-04 (defense-in-depth, not IAM-only):** Cloud Run IAM restricts invocation to the intake runtime SA, AND the `InternalCallerProvider` in-app verifies the Google-signed OIDC token (audience = Tribunal service URL, caller email = intake runtime SA) before accepting the `tenant_id` from the request. A mis-set IAM binding must not silently open tenants — this is the broken-RLS bug class the project explicitly guards against.
- **D-05 (audit chain records the human):** The intake backend forwards the acting superadmin's user id + email on every seam call (e.g. `X-Acting-User-*` headers — exact names = discretion); `InternalCallerProvider` maps them into the EXISTING `AuthClaims` fields (`app_user_id`, `email`). The legally load-bearing audit chain then attributes each run to the real human (EU AI Act Art. 12 story). **Hard constraint: reuse existing claim/payload fields only — the frozen audit `canonical_json` payload must not gain/rename fields (hash-chain break).**

**Carried-in from Phase 13 review**
- **D-04b (WR-03 runtime-SA separation — deferred here from Phase 13):** Tribunal services and the migrate job currently run as the intake runtime SA (`nestor-run@...`). Phase 14 gives Tribunal its own dedicated least-privilege SA(s); the "IAM invoker = intake runtime SA" gate (D-04) is only meaningful once caller SA ≠ callee SA. Read `13-REVIEW.md` § WR-03 for the full finding.

**Intake-side seam scope**
- **D-06 (minimal client in Phase 14):** The intake backend gains HTTP client machinery (OIDC identity-token minting for the Cloud Run audience, acting-user headers) plus `ensure_org(space_id)` / `ensure_project` lazy provisioning — idempotent, exercised by a proof call. Run-trigger/status-poll/report-fetch methods are Phase 16.
- **D-07 (full run through the seam as live proof):** The operator live session triggers ONE real research run server-to-server via the intake backend (hand-built brief, no UI): provisioning → run → completed green, PLUS negative proofs (unauthenticated call rejected, wrong-SA rejected, cross-tenant denied). **This absorbs the Phase-13 deferred queue-path proof earmarked as Phase 16's first step — remove it from Phase 16's backlog when this passes.**

**Denial-suite placement**
- **D-08 (each layer tested in its native harness):** DB-level RLS denial tests on `tribunal.*` tables go in Tribunal's own suite (asyncpg harness, `tribunal/cloudbuild.test*.yaml`); seam-level tests (provider rejects missing/mismatched tenant, GUC-leak denial across the HTTP boundary) go in `backend/tests/` (sync pg8000 harness, `cloudbuild.test.yaml`). Both Cloud Build suites together form the CI gate. No driver mixing between harnesses.

### Claude's Discretion
- Header names and exact wire contract for tenant + acting-user propagation; OIDC verification library/mechanics; how the provider threads request data to `verify_id_token`.
- Fate of `auth/local_dev.py` and copied tests covering deleted modules (keep what the surviving test harness needs; delete the rest).
- How the no-UI proof run is invoked (temporary script/endpoint/management command + runbook step).
- `project_id` persistence: recommended stateless idempotent `ensure_*` (org.id = space_id is deterministic; project discoverable by tenant) — Phase 16 owns the `research_runs` table.
- Exact GUC-leak test design and how the two-suite CI gate is wired into the runbook.

### Deferred Ideas (OUT OF SCOPE)
- **Run-trigger/poll/report-fetch client methods + `research_runs` table** — Phase 16 (built against Phase 15's final report shape).
- **Phase-13 queue-path proof as Phase 16's first step** — absorbed by this phase's D-07 full seam-proof run; strike it from Phase 16's backlog once green.
- **Surfacing Tribunal's interactive pauses in the admin UI** — FUT-02 (already tracked).
- Also out of this phase (per ROADMAP): research-trigger UI + progress bridge + emails (Phase 16), engine enhancements (Phase 15), cost-cap enforcement (ENGINE-03, Phase 16), any client-facing surface, `research_runs` intake table (Phase 16). **The original Nestor repo is NEVER touched (D-01).**
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEAM-01 | Tribunal's standalone logins/orgs/UI are retired; only the intake backend can call it (server-to-server internal auth) | `## Standard Stack` (OIDC via `google.oauth2.id_token`), `## Architecture Patterns` P1 (`InternalCallerProvider` at `set_auth_provider()`), P2 (Cloud Run internal-only + IAM invoker + dedicated SA), `## Retirement Inventory` (exact delete list + import-graph gate) |
| SEAM-02 | Intake spaces map 1:1 onto Tribunal orgs; every run is space-scoped end-to-end (cross-tenant denial suite extended to Tribunal data) | `## Architecture Patterns` P3 (identity mapping `space_id`=`org.id`, lazy `ensure_org`/`ensure_project`), P4 (two-suite denial gate), `## Common Pitfalls` (GUC-name mismatch across HTTP boundary) |
</phase_requirements>

## Summary

Phase 14 turns the re-homed Tribunal (proven green in Phase 13, single "Nestor Pulse" GCP project) from a standalone app into a strictly-internal engine that only the intake backend can drive. There are three workstreams, all low-invention:

1. **Retire Tribunal's identity surface (SEAM-01).** Tribunal was built as a self-contained Identity-Platform app: a `set_auth_provider()` global slot, an `IdentityPlatformProvider` that verifies Firebase JWTs and requires a `tenant_id` custom claim + an `app_user` row, and an `orgs/bootstrap` + `account` + `web/` login UI to make those exist. All of that is deleted in the `tribunal/` copy and replaced by a single `InternalCallerProvider` installed at the *existing* swap point (`auth/deps.py:37`). The critical insight from the code: `set_auth_provider()` + the `AuthClaims` dataclass + `get_db_session`'s RLS wiring were *deliberately designed* to be provider-swappable (the D-10 abstraction), so the retirement is a provider swap, not surgery on the RLS boundary. `get_db_session` keeps working untouched — it just reads `user.tenant_id` from a different (internally-trusted) provider.

2. **Space→tenant seam (SEAM-02).** The chosen mapping (v1.1 ARCHITECTURE §B.2) is *identity mapping*: `space_id` **is** the Tribunal `org.id` (same UUID — both systems use client-supplied UUIDs, no server sequences), so there is no mapping table. The intake backend gains a minimal `tribunal_client.py` that mints a Google-signed OIDC ID token (audience = the internal Tribunal service URL), forwards the acting superadmin's identity via headers, and calls idempotent `ensure_org(space_id)` / `ensure_project(space_id)` (salvaged from `orgs/provision.py` internals). Run-trigger/poll/report methods are explicitly Phase 16 (D-06).

3. **Two-layer trust + two-suite denial gate (D-04, D-08).** Defense-in-depth: Cloud Run IAM restricts invocation to a *dedicated* Tribunal-invoker binding for the intake runtime SA, AND `InternalCallerProvider` re-verifies the OIDC token (audience + caller email) before trusting the request's `tenant_id`. WR-03 (Phase 13) is closed here by giving Tribunal its own least-privilege SA so "caller SA ≠ callee SA" becomes true and the IAM invoker gate is actually meaningful. The cross-tenant denial suite is extended in *both* harnesses (Tribunal asyncpg for `tribunal.*` RLS; intake pg8000 for the seam/GUC-leak boundary).

**Primary recommendation:** Do the provider swap at `auth/deps.py:37` with a new `InternalCallerProvider` that (a) is installed in `server.py` at startup, (b) reads the OIDC token from `request` and verifies `aud`==Tribunal-service-URL + caller-email==intake-SA via `google.oauth2.id_token.verify_oauth2_token`, and (c) reads `X-Nestor-Tenant-Id` + `X-Acting-User-Id`/`X-Acting-User-Email` headers into the *existing* `AuthClaims(tenant_id, app_user_id, email, raw_provider_user_id)` fields — never adding/renaming a field. Hard-delete the retired modules in one sweep after an import-graph check, give Tribunal a dedicated SA, and prove the whole thing with one real server-to-server run + three negative proofs in the operator session.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Verify caller is the intake backend (not the browser) | API / Backend — Tribunal (`InternalCallerProvider`) | Cloud Run IAM (invoker binding) | Defense-in-depth (D-04): IAM is the outer gate, in-app OIDC verification is the inner gate; neither alone may open a tenant |
| Superadmin authentication (the human) | API / Backend — intake (`get_current_identity`) | — | The intake backend is the security boundary; it already authenticated the superadmin via Identity Platform. Tribunal never runs `verify_id_token` for a human again |
| Mint the service-to-service credential | API / Backend — intake (`tribunal_client`) | GCP metadata server (ADC) | ID token minted with `google.oauth2.id_token` using the attached SA's ADC; audience = Tribunal service URL |
| space→tenant identity mapping | API / Backend — intake (`ensure_org`/`ensure_project`) | DB — Tribunal `org`/`project` rows | `space_id` = `org.id` deterministically; intake drives provisioning server-side (no user-facing bootstrap) |
| Tenant-scoped DB reads/writes inside a run | DB — Tribunal RLS (`app.tenant_id` GUC) | — | Unchanged Phase-13 wiring; `get_db_session` sets the GUC from the trusted `AuthClaims.tenant_id` |
| Cross-tenant denial (DB layer) | DB — Tribunal RLS + asyncpg test harness | — | Native to `tribunal.*` schema; tested in Tribunal's own suite (D-08) |
| Cross-tenant denial (HTTP seam / GUC-leak) | API / Backend — intake pg8000 test harness | — | The GUC-name mismatch cannot leak across the boundary because there is no shared session — proven at the seam (D-08) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `google-auth` | ≥2.38 (present transitively) | Mint + verify Cloud Run OIDC ID tokens (`google.oauth2.id_token.fetch_id_token` / `verify_oauth2_token`) | Google's official auth library; the documented service-to-service pattern. **Already in the intake image transitively via `google-cloud-storage>=3,<4`** — do NOT pin separately (CLAUDE-style dep discipline; the codebase's `google-cloud-storage` comment says exactly this). `[CITED: docs.cloud.google.com/run/docs/authenticating/service-to-service]` |
| `httpx` | ≥0.27,<1 | The intake→Tribunal HTTP transport (`tribunal_client.py`) | Already the intake backend's HTTP client (used in `app/mail/resend.py`); consistent with established patterns. `[VERIFIED: backend/pyproject.toml]` |
| `fastapi` | ≥0.137 | Tribunal `InternalCallerProvider` reads `request`; no new framework | Both codebases are FastAPI. `[VERIFIED: pyproject.toml both sides]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `google.auth.transport.requests.Request()` | (part of google-auth) | Transport object passed to `fetch_id_token`/`verify_oauth2_token` | Every seam call — construct once per client, reuse |
| `sqlalchemy` (asyncpg) | existing Tribunal pin | `ensure_org`/`ensure_project` salvaged internals still run on Tribunal's async session | Only inside Tribunal (the provisioning endpoints); the intake side calls them over HTTP |

### Removed / retired (this phase)
| Library | Action | Why |
|---------|--------|-----|
| `firebase-admin==6.9.0` | **Remove** from `tribunal/requirements.txt` | Only `auth/identity_platform.py` + `orgs/provision.py`'s `_firebase_set_claims` use it; both retired. Verify no other importer before removal (import-graph gate, D-03). `[VERIFIED: grep tribunal/requirements.txt:43]` |

**Installation:** No new packages to install. The seam uses `google-auth` (already transitively present via `google-cloud-storage`) and `httpx` (already a direct intake dependency). This phase is **net-negative** on dependencies (removes `firebase-admin` from the Tribunal side).

**Version verification (run before finalizing the plan):**
```bash
# Confirm google-auth is resolvable in the intake image (it arrives via google-cloud-storage)
pip index versions google-auth        # intake side — should already resolve; do NOT add a separate pin
grep -n "firebase-admin" tribunal/requirements.txt   # confirm the single occurrence before deleting
```

## Package Legitimacy Audit

> This phase installs **no new external packages**. It removes one (`firebase-admin` from the Tribunal side) and relies on already-present, already-vetted dependencies. The audit below is for completeness.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `google-auth` | PyPI | 10+ yrs | very high | github.com/googleapis/google-auth-library-python | not run (no new install) | Already present (transitive via google-cloud-storage) — [ASSUMED clean, first-party Google] |
| `httpx` | PyPI | 6+ yrs | very high | github.com/encode/httpx | not run (no new install) | Already a direct intake dep — [ASSUMED clean] |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck was not run because this phase adds no packages. The two libraries referenced are pre-existing, first-party (Google) / widely-adopted (Encode) dependencies already vetted in the intake image. If the planner introduces any new package, run the Package Legitimacy Gate before install.*

## Architecture Patterns

### System Architecture Diagram

```
                         BROWSER (superadmin, Identity Platform session)
                              │  (this phase: NO browser→Tribunal path at all)
                              ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  INTAKE BACKEND  (Cloud Run: nestor-api, SA = nestor-run@...)     │
   │                                                                    │
   │  get_current_identity → Identity(role=superadmin, space_id)       │
   │           │                                                        │
   │           ▼                                                        │
   │  research/tribunal_client.py                                       │
   │    1. mint OIDC ID token: fetch_id_token(req, aud=TRIBUNAL_URL)    │  ── ADC (metadata server)
   │    2. headers: Authorization: Bearer <id_token>                    │
   │               X-Nestor-Tenant-Id: <space_id>                       │
   │               X-Acting-User-Id / X-Acting-User-Email: <superadmin> │
   │    3. httpx POST /api/orgs/ensure ; /api/projects/ensure          │
   └───────────────────────────────┬──────────────────────────────────┘
                                    │  server-to-server HTTPS (internal only)
                                    ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  CLOUD RUN IAM  (outer gate, D-04)                                 │
   │   tribunal-api invoker binding = ONLY nestor-run@... (intake SA)   │
   │   --no-allow-unauthenticated  → rejects unauthenticated / wrong-SA │
   └───────────────────────────────┬──────────────────────────────────┘
                                    ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  TRIBUNAL API  (Cloud Run: tribunal-api, SA = tribunal-run@... D-04b) │
   │                                                                    │
   │  InternalCallerProvider (installed at set_auth_provider, deps.py:37)│
   │    inner gate (D-04): verify_oauth2_token(id_token)                 │
   │        assert aud == TRIBUNAL_SERVICE_URL                           │
   │        assert email == nestor-run@... (intake SA)                  │
   │    then build AuthClaims(                                           │
   │        tenant_id = X-Nestor-Tenant-Id,        # = space_id         │
   │        app_user_id = X-Acting-User-Id,        # the human (D-05)   │
   │        email = X-Acting-User-Email,           # the human (D-05)   │
   │        raw_provider_user_id = "<intake-seam>" )                     │
   │           │                                                        │
   │           ▼  (UNCHANGED Phase-13 wiring)                           │
   │  get_db_session → SET LOCAL app.tenant_id = claims.tenant_id       │
   │           │                                                        │
   │           ▼                                                        │
   │  ensure_org / ensure_project (salvaged from orgs/provision.py)     │
   │      org.id = space_id (idempotent get-or-create)                  │
   │      project (tenant_id = space_id, idempotent)                    │
   └───────────────────────────────┬──────────────────────────────────┘
                                    ▼
              TRIBUNAL SCHEMA (tribunal.*, RLS keyed app.tenant_id)
              — separate schema, separate Alembic line, no shared session
```

**Retired in this phase (deleted from the deployed surface):** `Login.jsx` / `web/` static mount, `/api/auth/config`, `account/` (`/api/me`), `orgs/api.py` (`/api/orgs/bootstrap`), `demo/` router, `compare` + eval-critique endpoints, `auth/identity_platform.py`.

### Recommended structure (files this phase touches)
```
tribunal/nestor_pulse_sdk/
├── auth/
│   ├── deps.py                 # KEEP — set_auth_provider swap point (line 37); get_db_session UNTOUCHED
│   ├── provider.py             # KEEP — AuthProvider ABC + AuthClaims (reuse fields, D-05)
│   ├── internal_caller.py      # NEW — InternalCallerProvider (implements AuthProvider)
│   ├── identity_platform.py    # DELETE (D-02) — Firebase JWT verifier
│   └── local_dev.py            # DISCRETION — keep only if surviving test harness needs it
│   └── middleware.py           # KEEP — RequestIDMiddleware + AuthError handler still used
├── server.py                   # MODIFY — install InternalCallerProvider; strip account/orgs/demo/web/auth-config routers
├── orgs/
│   ├── api.py                  # DELETE (D-02) — /api/orgs/bootstrap user-facing endpoint
│   └── provision.py            # SALVAGE — keep the org/project get-or-create internals (drop firebase claim call); expose ensure_org/ensure_project endpoints for the seam
├── account/                    # DELETE (D-02) — /api/me
├── demo/                       # DELETE (D-03)
└── projects/api.py             # REVIEW — keep an ensure/create path (seam needs a project_id); strip anything only the retired UI called

tribunal/infrastructure/cloud-run/
├── deploy-api.sh               # MODIFY — SA → tribunal-run@... (D-04b); drop IDENTITY_PLATFORM_* env/secrets
├── deploy-worker.sh            # MODIFY — SA → tribunal-run@... (D-04b)
tribunal/requirements.txt       # MODIFY — remove firebase-admin
infra/*.tf                      # MODIFY — dedicated tribunal-run SA + least-priv bindings; Tribunal invoker = nestor-run@...; drop IDENTITY_PLATFORM_* secrets

backend/app/research/           # NEW dir
└── tribunal_client.py          # NEW — OIDC minting + ensure_org/ensure_project (minimal, D-06)
backend/tests/
├── test_tribunal_seam_denial.py       # NEW — seam-level denial (missing/mismatched tenant, wrong-SA, GUC-leak)
└── conftest.py                         # EXTEND if new fixtures needed
```

### Pattern 1: Provider swap at the existing bind point (SEAM-01)
**What:** Implement `InternalCallerProvider(AuthProvider)` and install it once at startup. This is the D-10 abstraction working exactly as designed — the whole point of `set_auth_provider()` is that "swapping to WorkOS = `set_auth_provider(WorkOSProvider(...))` and nothing else upstream changes" (`deps.py:44`).
**When to use:** Always — this is the SEAM-01 keystone.
**Example:**
```python
# tribunal/nestor_pulse_sdk/auth/internal_caller.py  (NEW)
# Source: pattern derived from auth/provider.py (AuthProvider ABC) + auth/deps.py
#         (get_current_user stashes request.state.user) + D-04/D-05.
from google.auth.transport import requests as ga_requests
from google.oauth2 import id_token as ga_id_token
from nestor_pulse_sdk.auth.provider import AuthClaims, AuthProvider, AuthError

class InternalCallerProvider(AuthProvider):
    """Trusts ONLY the intake backend. Verifies the Google-signed OIDC token
    (audience = this Tribunal service URL, caller email = intake runtime SA),
    then reads tenant + acting-user from headers into the EXISTING AuthClaims
    fields (D-05: no new/renamed field — the audit canonical_json is frozen)."""

    def __init__(self, service_url: str, allowed_caller_email: str) -> None:
        self._aud = service_url                    # e.g. https://tribunal-api-....run.app
        self._caller = allowed_caller_email        # nestor-run@<project>.iam.gserviceaccount.com
        self._transport = ga_requests.Request()

    async def verify_id_token(self, token: str) -> AuthClaims:  # noqa: D401
        # NOTE: get_current_user passes the bearer token string; the provider needs
        # the request headers too. Threading is discretion — simplest is to make the
        # provider read request.headers via a small wrapper dep OR pass a struct.
        try:
            claims = ga_id_token.verify_oauth2_token(token, self._transport, self._aud)
        except Exception as exc:  # ValueError on bad aud/sig/expiry
            raise AuthError("invalid internal caller token", status_code=401) from exc
        if claims.get("email") != self._caller or not claims.get("email_verified"):
            raise AuthError("caller is not the intake backend", status_code=403)
        # tenant + acting-user come from headers (set by tribunal_client). Read them
        # in a thin dependency and pass through — mapped into EXISTING fields only.
        ...  # returns AuthClaims(tenant_id=<space_id>, app_user_id=<acting>, email=<acting>, raw_provider_user_id="intake-seam")

    async def lookup_user(self, app_user_id): return None   # unused in the seam
    async def sign_out(self, app_user_id): return None      # unused in the seam
```
> **Threading caveat (discretion, D-04):** `get_current_user(request)` currently extracts only the bearer token and calls `provider.verify_id_token(token)`. The provider also needs the `X-Nestor-Tenant-Id` / `X-Acting-User-*` headers. Cleanest options: (a) add a thin `get_internal_claims(request)` dependency that reads headers + calls the provider, installed as a `dependency_overrides[get_current_user]` (mirrors the existing `LOCAL_DEV_AUTH` override in `server.py:116-124`), or (b) have `get_current_user` stash `request` and let the provider read `request.state`. Option (a) reuses an existing, proven override mechanism.

### Pattern 2: Cloud Run internal-only + dedicated invoker binding (SEAM-01, D-04, D-04b)
**What:** Tribunal API stays `--no-allow-unauthenticated` (already true from Phase 13) and gets an explicit `run.invoker` binding for ONLY the intake runtime SA. Tribunal also gets its **own** runtime SA (`tribunal-run@...`) so caller ≠ callee.
**When to use:** SEAM-01 IAM layer + closes WR-03.
**Example:**
```bash
# Give Tribunal a dedicated least-privilege runtime SA (D-04b / WR-03 fix)
gcloud iam service-accounts create tribunal-run \
  --project="$PROJECT" --display-name="Tribunal engine runtime (least-priv)"
# Grants: cloudsql.client; secretAccessor on the 6 Tribunal secrets; objectAdmin on the audit bucket.
# NO identitytoolkit.admin, NO intake superadmin DB-password secret, NO nestor uploads bucket.

# Deploy scripts: --service-account="tribunal-run@${PROJECT}.iam.gserviceaccount.com"

# Invoker binding: ONLY the intake runtime SA may call the Tribunal API (D-04 outer gate)
gcloud run services add-invoker-policy-binding tribunal-api \
  --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:nestor-run@${PROJECT}.iam.gserviceaccount.com"
```
> **Why WR-03 matters here:** with both services running as `nestor-run@...`, the "IAM invoker = intake SA" gate is a no-op (a service can always invoke itself). The gate only *means* something once the callee runs as a different SA. Do the SA split and the invoker binding together, or D-04 is theater. `[CITED: 13-REVIEW.md § WR-03]`

### Pattern 3: Identity mapping — `space_id` IS `org.id`, lazy idempotent provisioning (SEAM-02)
**What:** No mapping table. The intake `space_id` (a UUID = `nestor.organizations.id`) is used verbatim as the Tribunal `org.id`. `ensure_org(space_id)` is an idempotent get-or-create; `ensure_project` provisions one project per space lazily. Both salvage the `orgs/provision.py` internals **minus the Firebase claim write**.
**When to use:** SEAM-02 keystone; exercised by the D-07 proof.
**Example (server-side, salvaged):**
```python
# Salvaged from orgs/provision.py ensure_org_for_user — STRIP the _firebase_set_claims call
# and the app_user creation (intake owns users). Keep the get-or-create Org + Project shape.
org = await session.get(Org, uuid.UUID(space_id))
if org is None:
    org = Org(id=uuid.UUID(space_id), name=..., slug=...)   # id == space_id (identity mapping)
    session.add(org); await session.flush()
await set_tenant_context(session, space_id)                  # RLS before touching project (FORCED table)
# project: one per space, idempotent (discoverable by tenant_id — stateless per discretion note)
```
> **project_id persistence (discretion):** ARCHITECTURE recommends the stateless idempotent form — `org.id` is deterministic (= space_id) and the project is discoverable by `tenant_id`, so Phase 14 need not persist a `project_id` intake-side. Phase 16 owns the `research_runs` table where `tribunal_project_id` will later live. **Recommendation: return the `project_id` from `ensure_project` and let Phase 16 persist it; do not add an intake column now.**

### Pattern 4: Two-suite cross-tenant denial gate (SEAM-02, D-08)
**What:** RLS denial on `tribunal.*` tables lives in Tribunal's asyncpg suite; seam/GUC-leak denial lives in the intake pg8000 suite. The intake denial pattern to clone is `backend/tests/test_intake_cross_tenant.py` — it drives the REAL routers over a testcontainer, fabricates `Identity` via `dependency_overrides[get_current_identity]`, and asserts EXACT 404 (never `in (403,404)`) for cross-tenant, plus 403 for null-space.
**When to use:** The CI gate for the whole phase (both Cloud Build configs must be green).
**Seam tests to add (intake side):**
- Provider rejects a request with a *missing* `X-Nestor-Tenant-Id` → 400/401 (no unset-GUC query ever runs).
- Provider rejects a request whose OIDC `email` ≠ intake SA → 403 (wrong-SA).
- Provider rejects an unauthenticated request (no bearer) → 401.
- **GUC-leak denial:** a call carrying intake's `app.current_space_id` semantics (space-A) MUST NOT be able to read space-B Tribunal data — because there is *no shared session*, the seam is HTTP-only and the tenant comes from the verified header. The test proves that setting the wrong tenant header for space-A never returns space-B rows (the whole point of Pitfall 2's firewall).

### Anti-Patterns to Avoid
- **Rewriting `get_db_session` or the `AuthClaims` shape.** The RLS boundary is proven; only the *provider* changes. Touching `get_db_session` re-opens the highest-leverage security surface for no reason. `[CITED: auth/deps.py:145-173]`
- **Adding or renaming an `AuthClaims` field to carry the human.** D-05 hard constraint: map the superadmin into the EXISTING `app_user_id`/`email` fields. A new field ripples into the frozen audit `canonical_json` → hash-chain break (Pitfall 7, legal). `[CITED: PITFALLS.md Pitfall 7]`
- **Trusting IAM alone (or the app alone).** D-04 requires BOTH. A mis-set IAM binding must not silently open tenants — that's the broken-RLS bug class the project exists to kill.
- **Leaving Tribunal on the intake SA.** WR-03: the invoker gate is meaningless until Tribunal has its own SA. Also a real security exposure — the Tribunal worker drives LLM calls over untrusted research content (prompt-injection → SSRF class), and that process currently holds the intake superadmin DB password + `identitytoolkit.admin`. `[CITED: 13-REVIEW.md WR-03]`
- **Soft-unmounting instead of hard-deleting.** D-02 requires outright deletion in `tribunal/` (git history is the recovery path). A commented-out router is the "auth guard disabled // TEMP" anti-pattern this project already got burned by.
- **Deleting something `pipeline/` imports.** D-03 gate: run the import-graph check before every deletion. Salvage `orgs/provision.py` internals; the *endpoint* dies, the *provisioning function* lives.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Verify a Google-signed OIDC ID token | Custom JWKS fetch + RS256 verify | `google.oauth2.id_token.verify_oauth2_token(token, Request(), audience)` | Handles key rotation, `aud`/`iss`/`exp`, signature. Hand-rolled JWKS is the classic auth footgun. `[CITED: google-auth docs]` |
| Mint a service-to-service credential | Manual SA-key signing / JWT assembly | `google.oauth2.id_token.fetch_id_token(Request(), audience)` (ADC) | Keyless — uses the attached SA via the metadata server. Org policy disables SA JSON keys anyway. `[CITED: docs.cloud.google.com/run/docs/authenticating/service-to-service]` |
| Restrict who can call the Tribunal API | App-level allowlist only | Cloud Run `--no-allow-unauthenticated` + `run.invoker` binding | IAM is the outer, network-level gate; app verification is the inner gate (D-04 defense-in-depth) |
| space→tenant mapping | A `space_id ↔ tenant_id` lookup table | Identity mapping (same UUID) | Both systems use client-supplied UUIDs; a join adds a failure mode for zero benefit (ARCHITECTURE §B.2) |
| Cross-tenant denial proof | New bespoke test scaffold | Clone `test_intake_cross_tenant.py` fixtures/shape | Proven EXACT-404 discipline, real-router-over-testcontainer, `dependency_overrides` identity fabrication |
| Org/project row creation | Fresh insert logic | Salvage `orgs/provision.py` internals (minus firebase) | The get-or-create + RLS-context ordering (flush Org before FORCED child tables) is subtle and already correct |

**Key insight:** This phase is almost entirely *deletion + a provider swap + one small HTTP client*. The invention budget is near zero — every piece has an existing, proven analog on one side or the other. The risk is not in what to build but in what to accidentally break (the RLS boundary, the audit chain shape, the IAM gate's meaningfulness).

## Runtime State Inventory

> This is a retirement/refactor phase (deleting auth surfaces, renaming SA, changing IAM). Runtime state beyond the repo files:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | Tribunal `org` / `app_user` / `project` rows created during Phase 13 proof runs (self-provisioned tenants `5b0b574f…`, `260563e6…`, LUKOIL `1315ea6a`). These `app_user` rows become orphaned once the auth model is retired (no login path). `org`/`project` rows are harmless (identity mapping reuses `org.id`). | **None blocking** — leave the proof `org`/`project`/`run`/`audit_log` rows (they're valid tenant data; audit chain must stay intact per Pitfall 7). Do NOT delete `app_user` rows if the audit `canonical_json` or any FK references them — verify before any cleanup. Recommendation: leave all Phase-13 rows untouched. |
| **Live service config** | Cloud Run `tribunal-api` / `tribunal-worker` currently deployed as `nestor-run@...` with `IDENTITY_PLATFORM_*`-adjacent env. IAM invoker bindings on `tribunal-api`. These live in the deployed service config, not fully in git (IaC drift, carried concern). | **Re-deploy** both services with the new `tribunal-run@...` SA; **add** the `run.invoker` binding for `nestor-run@...`; **remove** any `IDENTITY_PLATFORM_*` env/secret refs from the service config. Operator runbook step (dev box has no Docker; images via Cloud Build). |
| **OS-registered state** | None — no Task Scheduler / cron / launchd entries reference Tribunal auth. | None — verified: this is a Cloud-Run-only service; no local OS registration. |
| **Secrets/env vars** | `IDENTITY_PLATFORM_*` secrets (Web API key, smoke-user pw) in Secret Manager, referenced by the retired `identity_platform.py` / `/api/auth/config`. `firebase-admin` credential path (ADC). New: a dedicated `tribunal-run` SA (identity, not a secret). | **Remove** `IDENTITY_PLATFORM_*` from Tribunal deploy scripts + IaC (D-02). Confirm no *other* service reads them before deleting the Secret Manager entries (the intake side has its own Identity Platform usage — do NOT delete intake's IdP config). Verify the `Nestor_*` provider secrets stay (still used by the engine). |
| **Build artifacts / installed packages** | `firebase-admin==6.9.0` baked into the Tribunal API/worker images. Cloud Build produces the images; they carry the retired module until rebuilt. | **Rebuild** both Tribunal images via Cloud Build after removing `firebase-admin` + deleting `identity_platform.py`, then redeploy. A stale image still importing the deleted module would fail at boot — the import-graph gate (D-03) must confirm nothing else imports it first. |

**The canonical question — after every file is updated, what runtime state still carries the old model?** Answer: (1) the deployed Cloud Run service config (SA identity + IAM invoker + secret refs) — fixed by redeploy; (2) the built images (carry `firebase-admin` until rebuilt) — fixed by Cloud Build rebuild; (3) `IDENTITY_PLATFORM_*` Secret Manager entries — removed after confirming no other reader. Proof-run DB rows are intentionally left intact (audit-chain safety).

## Common Pitfalls

### Pitfall 1: GUC-name mismatch leaks across a *carelessly* merged boundary (SEAM-02 core)
**What goes wrong:** Intake RLS reads `app.current_space_id`; Tribunal RLS reads `app.tenant_id`. If any code path ever runs a Tribunal query inside an intake session (shared DB session), Tribunal's policy reads the unset `app.tenant_id` and either raises or — if someone "fixes" it permissively — reintroduces the `USING(true)` cross-tenant bug.
**Why it happens:** The two systems made the same design decision with different names.
**How to avoid:** The chosen architecture already prevents this — **the seam is HTTP-only; there is no shared DB session.** The intake backend never opens a `tribunal.*` transaction. The `InternalCallerProvider` receives `tenant_id` (= space_id) via a verified header, and `get_db_session` sets `app.tenant_id` on Tribunal's *own* session. Phase 14's denial suite must *prove* non-leakage across this boundary (D-08 seam tests).
**Warning signs:** Any `current_setting` error in Tribunal logs under a seam call; a cross-space read returning foreign rows in the denial test. `[CITED: PITFALLS.md Pitfall 2]`

### Pitfall 2: Retiring auth strands code that assumes `app_user`/`project` rows exist
**What goes wrong:** `get_db_session` historically 403'd without a matching `app_user` row; `create_run` 404s without a `project`; `run.project_id` is `NOT NULL`.
**Why it happens:** Identity was baked into Tribunal's data model, not a thin layer.
**How to avoid:** The `InternalCallerProvider` supplies `tenant_id` directly (= space_id) — no `app_user` lookup needed for RLS. `ensure_project` guarantees a `project_id` exists before any run (Phase 16 triggers). This phase provisions org+project via the salvaged internals so the NOT-NULL FK is always satisfiable. **Verify:** does `get_db_session` (or anything downstream) still require an `app_user` row? If so, that check must be removed/relaxed for the internal-caller path. `[CITED: PITFALLS.md Pitfall 3, provider.py:99-114]`
**Warning signs:** `403 Missing/absent app_user`, `NOT NULL violation on run.project_id`, a `run.tenant_id` that isn't a valid `organizations.id`.

### Pitfall 3: The D-04 gate is theater if caller SA == callee SA (WR-03)
**What goes wrong:** With both services on `nestor-run@...`, the "invoker = intake SA" binding is meaningless (a service can invoke itself), and a compromised Tribunal worker holds intake-admin capabilities.
**How to avoid:** Provision `tribunal-run@...` (least-priv) and point both deploy scripts + all three TF resources at it, THEN add the invoker binding. Do them together. `[CITED: 13-REVIEW.md WR-03]`
**Warning signs:** `gcloud run services get-iam-policy tribunal-api` shows the invoker is the same SA the service runs as; the negative "wrong-SA rejected" proof (D-07) can't actually be constructed because there's no *other* SA to test with.

### Pitfall 4: OIDC `aud` mismatch (the #1 service-to-service failure)
**What goes wrong:** ID token audience must be the **service URL without a path** (`https://tribunal-api-xxx.run.app`), not the full endpoint URL. A path in the audience → 401.
**How to avoid:** Mint with `fetch_id_token(req, "https://tribunal-api-xxx.run.app")`; verify with the same base URL. Capture the real deployed URL from `gcloud run services describe` — never guess it. `[CITED: docs.cloud.google.com/run/docs/authenticating/service-to-service]`
**Warning signs:** Consistent 401 on every seam call despite a valid-looking token; `aud` in the decoded token includes `/api/...`.

### Pitfall 5: Deleting a module `pipeline/` still imports (D-03 gate)
**What goes wrong:** A "clean sweep" deletes the eval-critique or compare module, but `pipeline/tribunal/*` (Phase 15's substrate) imports something from it → import error at boot.
**How to avoid:** Run the import-graph check before each deletion (`grep -rn "from nestor_pulse_sdk.<module>" tribunal/nestor_pulse_sdk/` excluding the module itself + tests-for-deleted). Salvage `orgs/provision.py` internals; delete only the *endpoints*. Note Phase 15's plan-critique is NEW code — don't confuse it with the deleted eval critique surface. `[CITED: CONTEXT D-03]`
**Warning signs:** `ImportError` / `ModuleNotFoundError` in the Cloud Build image smoke or at service boot.

### Pitfall 6: Threading request headers to the provider without breaking `get_current_user`
**What goes wrong:** `get_current_user(request)` calls `provider.verify_id_token(token)` with only the token string; the provider also needs `X-Nestor-Tenant-Id` / `X-Acting-User-*`.
**How to avoid:** Prefer a `dependency_overrides[get_current_user]` internal dep that reads headers + drives the provider — reuses the exact mechanism `server.py:116-124` already uses for `LOCAL_DEV_AUTH`. Keep `AuthClaims` field-shape frozen (D-05). `[VERIFIED: server.py:116-124, deps.py:88-138]`
**Warning signs:** Provider can't see the tenant header; tenant read from the wrong place; a new `AuthClaims` field sneaks in.

## Code Examples

### Minting the OIDC token + calling the seam (intake side)
```python
# backend/app/research/tribunal_client.py  (NEW, minimal — D-06)
# Source: docs.cloud.google.com/run/docs/authenticating/service-to-service
import httpx
from google.auth.transport import requests as ga_requests
from google.oauth2 import id_token as ga_id_token

_TRANSPORT = ga_requests.Request()

def _mint_id_token(service_url: str) -> str:
    # audience = service URL WITHOUT a path (Pitfall 4)
    return ga_id_token.fetch_id_token(_TRANSPORT, service_url)

def ensure_org(service_url: str, space_id: str, acting_user_id: str, acting_email: str) -> None:
    tok = _mint_id_token(service_url)
    resp = httpx.post(
        f"{service_url}/api/orgs/ensure",
        headers={
            "Authorization": f"Bearer {tok}",
            "X-Nestor-Tenant-Id": space_id,        # space_id IS org.id (identity mapping)
            "X-Acting-User-Id": acting_user_id,    # the human (D-05)
            "X-Acting-User-Email": acting_email,   # the human (D-05)
        },
        json={},
        timeout=30.0,
    )
    resp.raise_for_status()
```

### Verifying the caller (Tribunal side)
```python
# Inside InternalCallerProvider.verify_id_token / a get_internal_claims dep
# Source: google.oauth2.id_token.verify_oauth2_token
from google.oauth2 import id_token as ga_id_token
from google.auth.transport import requests as ga_requests

info = ga_id_token.verify_oauth2_token(bearer_token, ga_requests.Request(), TRIBUNAL_SERVICE_URL)
if info.get("email") != INTAKE_RUNTIME_SA_EMAIL or not info.get("email_verified"):
    raise AuthError("caller is not the intake backend", status_code=403)
# tenant + acting-user from headers → EXISTING AuthClaims fields (D-05, no new field)
```

### Seam denial test shape (clone of the intake pattern)
```python
# backend/tests/test_tribunal_seam_denial.py  (NEW)
# Clone the dependency_overrides + EXACT-404 discipline from test_intake_cross_tenant.py.
# Assert: missing tenant header -> 400/401; wrong-SA OIDC email -> 403; unauthenticated -> 401;
#         space-A header never returns space-B tribunal rows (GUC-leak firewall).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Tribunal standalone: Firebase JWT + `tenant_id` claim + `orgs/bootstrap` + Login UI | Internal-only API: intake backend is the sole authenticated caller; OIDC service-to-service | This phase (SEAM-01) | Tribunal never runs `verify_id_token` for a human again |
| Both Cloud Run services run as `nestor-run@...` (intake SA) | Dedicated `tribunal-run@...` least-priv SA (WR-03 fix) | This phase (D-04b) | The IAM invoker gate becomes meaningful; Tribunal can't reach intake admin surfaces |
| `space_id ↔ tenant_id` (conceptually two ids) | Identity mapping: `space_id` **is** `org.id` (same UUID) | v1.1 architecture decision | No mapping table, no join, no drift |

**Deprecated/outdated (removed this phase):**
- `auth/identity_platform.py` (Firebase verifier) — replaced by `InternalCallerProvider`.
- `orgs/api.py` `/api/orgs/bootstrap`, `account/` `/api/me`, `web/`+`Login.jsx`, `/api/auth/config`, `demo/`, compare/eval-critique endpoints — the deployed surface shrinks to runs/audit/sources/uploads/health + the two `ensure` seam endpoints.
- `firebase-admin` dependency.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `google-auth` resolves in the intake image transitively (via `google-cloud-storage>=3,<4`) — no separate pin needed | Standard Stack | LOW — if absent, add an explicit pin after slopcheck; verified the codebase comment states it arrives transitively but not that `id_token` submodule is importable in that exact build. Confirm with `python -c "from google.oauth2 import id_token"` in a Cloud Build step. |
| A2 | `verify_oauth2_token(token, Request(), aud)` with an `email`/`email_verified` check is sufficient to identify the caller SA on Cloud Run | Patterns/Code | LOW-MED — this is the documented pattern, but confirm the ID token minted by `fetch_id_token` for a Cloud-Run-attached SA actually carries `email`/`email_verified` (it does for SA-issued OIDC tokens; verify in the proof session by logging decoded claims once). |
| A3 | Nothing besides `identity_platform.py` + `orgs/provision.py` imports `firebase-admin` in `tribunal/` | Standard Stack / Retirement | MED — a stray importer would break the image at boot. **Mitigated by the D-03 import-graph gate (mandatory before deletion).** |
| A4 | `get_db_session` / downstream run code does not hard-require an `app_user` row once the provider supplies `tenant_id` directly | Pitfalls 2 | MED — `provider.py` docstrings mention a 403 on missing `app_user`; the planner must grep the actual `get_db_session` + run paths for an `app_user` existence check and relax it for the internal-caller path. |
| A5 | The Phase-13 proof `app_user` rows are not referenced by the frozen audit `canonical_json` (safe to leave orphaned) | Runtime State Inventory | MED — leaving them is the safe default (no deletion). Only becomes a risk if someone tries to *clean them up* and an FK/audit reference blocks it. Recommendation: leave all Phase-13 rows untouched. |
| A6 | Deleting `IDENTITY_PLATFORM_*` Secret Manager entries won't break the intake side | Runtime State Inventory | MED — intake has its OWN Identity Platform usage (superadmin auth). Only the *Tribunal* deploy's references are removed; the Secret Manager entries themselves should be deleted ONLY after confirming no other reader. Recommendation: remove from Tribunal deploy config; defer deleting the secret entries to a later cleanup unless provably unused. |

**These assumptions are the items discuss-phase / the planner should confirm.** A3/A4 are the highest-value to verify early (they gate the delete sweep and the provider correctness).

## Open Questions

1. **How does the provider receive the tenant/acting-user headers?**
   - What we know: `get_current_user(request)` today passes only the token; the `LOCAL_DEV_AUTH` override mechanism (`server.py:116-124`) is a proven way to swap the current-user dep.
   - What's unclear: whether to override `get_current_user` with a header-reading internal dep, or thread `request` into the provider.
   - Recommendation (discretion): override `get_current_user` with `get_internal_claims(request)` — reuses the existing override slot, keeps `AuthClaims` frozen, and keeps the provider testable.

2. **Does `ensure_project` need one project per space, per intake, or per run?**
   - What we know: `run.project_id` is NOT NULL; ARCHITECTURE says "one per space is enough for v1."
   - Recommendation: one project per space (idempotent, discoverable by `tenant_id`). Return `project_id`; let Phase 16 persist it on `research_runs`. Do not add an intake column now (D-06 boundary).

3. **Exact secret-cleanup scope for `IDENTITY_PLATFORM_*`.**
   - What we know: remove them from Tribunal deploy scripts + IaC (D-02).
   - What's unclear: whether the Secret Manager *entries* are safe to delete (intake may share IdP config under different secret names).
   - Recommendation: remove references from Tribunal config now; delete the secret entries only after a "no other reader" grep across both deploy surfaces (A6).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `gcloud` CLI | SA creation, IAM invoker binding, redeploy | ✓ | operator machine | — |
| Cloud Build | Rebuild Tribunal images (no local Docker) | ✓ | — | none needed (established Phase-13 path) |
| Local Docker / Python | Run backend tests locally | ✗ | — | Tests run via Cloud Build (both suites); by-construction authoring on dev box |
| Terraform apply | IaC for SA + bindings | ✗ (downloads blocked; state never adopted — IaC drift) | — | **Author IaC by construction; do the live changes via gcloud runbook.** Reconcile TF as by-construction only (do NOT `terraform apply` — CR-02 landmine: it would rotate DB passwords) |
| `google.oauth2.id_token` submodule | OIDC minting/verify | ✓ (via google-auth, transitive) | ≥2.38 | Confirm importable in the image (A1) — add explicit `google-auth` pin only if the smoke import fails |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** local Docker/Python (→ Cloud Build); Terraform apply (→ gcloud runbook + by-construction IaC; **never apply** — CR-02).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (both suites); intake = sync pg8000 harness, Tribunal = async asyncpg harness |
| Config file | intake `cloudbuild.test.yaml`; Tribunal `tribunal/cloudbuild.test.yaml` + `tribunal/cloudbuild.test-critical.yaml` |
| Quick run command | intake seam tests: `pytest backend/tests/test_tribunal_seam_denial.py -x` (via Cloud Build; not local) |
| Full suite command | Both Cloud Build test configs green (the CI gate, D-08) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEAM-01 | Unauthenticated call to Tribunal API rejected | integration | Cloud Run IAM (`--no-allow-unauthenticated`) + provider 401 test | ❌ Wave 0 (`test_tribunal_seam_denial.py`) |
| SEAM-01 | Wrong-SA OIDC token rejected (403) | integration | `pytest backend/tests/test_tribunal_seam_denial.py -k wrong_sa` | ❌ Wave 0 |
| SEAM-01 | Retired endpoints (`/api/me`, `/api/orgs/bootstrap`, `/app`, `/api/auth/config`, demo) return 404 | integration | Tribunal suite: assert routes absent after strip | ❌ Wave 0 (Tribunal side) |
| SEAM-02 | Missing tenant header → no unset-GUC query runs (400/401) | integration | `pytest ... -k missing_tenant` | ❌ Wave 0 |
| SEAM-02 | Cross-tenant denial on `tribunal.*` tables (RLS) | integration | Tribunal asyncpg suite (clone existing RLS isolation test) | ❌ Wave 0 (Tribunal side) |
| SEAM-02 | GUC-leak: space-A header never returns space-B tribunal rows | integration | `pytest ... -k guc_leak` | ❌ Wave 0 |
| SEAM-02 | `ensure_org`/`ensure_project` idempotent (org.id = space_id) | integration | Tribunal suite + D-07 live proof | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** targeted seam test (`pytest backend/tests/test_tribunal_seam_denial.py -x` via Cloud Build).
- **Per wave merge:** both Cloud Build test configs (intake + Tribunal critical).
- **Phase gate:** both suites green + the D-07 live proof (1 real server-to-server run + 3 negative proofs) before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `backend/tests/test_tribunal_seam_denial.py` — seam denial (missing/mismatched tenant, wrong-SA, unauthenticated, GUC-leak) — clone `test_intake_cross_tenant.py` fixtures.
- [ ] Tribunal-side RLS denial test for `tribunal.*` (extend the existing schema-isolation/RLS test in Tribunal's suite).
- [ ] Tribunal-side "retired routes absent" assertion (part of the strip verification).
- [ ] No new framework install — pytest already present both sides.

## Security Domain

> `security_enforcement` treated as enabled (not `false` in config). This phase IS a security phase — it defines the trust boundary between two services.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Service-to-service OIDC (`verify_oauth2_token`, aud + caller-email check); no human auth on Tribunal |
| V3 Session Management | no | Stateless per-request OIDC; no sessions on the seam |
| V4 Access Control | yes | Two-layer (Cloud Run IAM invoker + in-app OIDC verification), D-04 defense-in-depth; RLS at DB (`app.tenant_id` GUC) |
| V5 Input Validation | yes | Tenant + acting-user come from verified header/token, never request body; `space_id` parsed as UUID (fail-loud) |
| V6 Cryptography | yes (delegated) | OIDC signature verification via google-auth (never hand-rolled JWKS); audit hash-chain untouched (D-05 frozen payload) |
| V7 Error/Logging | yes | Audit chain records the acting human (D-05, EU AI Act Art. 12); no acting-user in logs beyond audit |

### Known Threat Patterns for {internal Cloud Run seam + multi-tenant RLS}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Browser or third party calls Tribunal directly | Spoofing / Elevation | `--no-allow-unauthenticated` + invoker binding = intake SA ONLY (D-04 outer gate) |
| Mis-set IAM binding silently opens tenants | Elevation | In-app OIDC re-verification (aud + caller email) — IAM is necessary, not sufficient (D-04 inner gate) |
| Caller forges a `tenant_id` for another space | Tampering / Info Disclosure | `tenant_id` trusted only from the verified internal caller; RLS `app.tenant_id` GUC enforces at DB; denial suite proves non-leak |
| GUC-name mismatch reintroduces `USING(true)` | Info Disclosure | No shared session; HTTP-only seam; two-suite denial gate proves the boundary (Pitfall 1/2) |
| Compromised Tribunal worker reaches intake admin surfaces | Elevation | Dedicated `tribunal-run@...` least-priv SA (WR-03 fix) — no intake superadmin secret, no identitytoolkit.admin |
| Audit chain break via renamed field | Tampering (repudiation of the legal record) | D-05 hard constraint: reuse EXISTING `AuthClaims` fields; frozen `canonical_json` (Pitfall 7) |

## Sources

### Primary (HIGH confidence — read directly this session)
- `tribunal/nestor_pulse_sdk/auth/deps.py` — `set_auth_provider()` (line 37), `get_current_user`, `get_db_session` RLS boundary
- `tribunal/nestor_pulse_sdk/auth/provider.py` — `AuthProvider` ABC + `AuthClaims` (fields for D-05)
- `tribunal/nestor_pulse_sdk/server.py` — router mounts to strip (account, orgs, demo, `/api/auth/config`, `/app` static), the `LOCAL_DEV_AUTH` override mechanism
- `tribunal/nestor_pulse_sdk/orgs/provision.py` + `orgs/api.py` — provisioning internals to salvage; bootstrap endpoint to delete
- `tribunal/nestor_pulse_sdk/runs/api.py` — `create_run` project_id requirement (`NOT NULL` FK)
- `tribunal/infrastructure/cloud-run/deploy-api.sh` / `deploy-worker.sh` — current SA = intake SA, `--no-allow-unauthenticated`, secret refs
- `backend/tests/test_intake_cross_tenant.py` — the denial-suite pattern to clone (EXACT-404, dependency_overrides, real-router-over-testcontainer)
- `backend/app/core/config.py`, `backend/app/auth/identity.py`, `backend/app/ai/clients.py`, `backend/app/mail/resend.py` — intake httpx/settings/identity patterns
- `backend/pyproject.toml` — `google-cloud-storage>=3,<4` (google-auth transitive), `httpx`, `anthropic`, `fastapi`
- `.planning/research/ARCHITECTURE.md` §B.1–B.2, Part D/E — seam design, identity mapping, build order
- `.planning/research/PITFALLS.md` Pitfalls 2, 3, 7 — GUC mismatch, stranded auth, audit-chain fragility
- `.planning/phases/13-*/13-REVIEW.md` § WR-03 (SA separation), CR-01/02/03 (carried context)
- `.planning/phases/13-*/13-04-SUMMARY.md` — Phase 13 shipped state (single project, proof rows, deferrals into Phase 14)

### Secondary (MEDIUM confidence)
- `docs.cloud.google.com/run/docs/authenticating/service-to-service` + `google.oauth2.id_token` docs — OIDC minting/verify, aud = service URL without path (verified via web search this session)

### Tertiary (LOW confidence — flagged for validation)
- A1/A2 (google-auth `id_token` importable + ID token carries `email`/`email_verified` in this exact image) — verify with a one-line import + a decoded-claims log in the proof session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; OIDC pattern is Google's documented standard; both codebases read directly.
- Architecture (provider swap, identity mapping, two-layer trust): HIGH — grounded in the actual `set_auth_provider`/`AuthClaims`/`get_db_session` code and the v1.1 ARCHITECTURE decisions.
- Pitfalls: HIGH — carried from PITFALLS.md + Phase 13 REVIEW, all cited to source.
- Retirement inventory: MEDIUM — the delete list is explicit (D-02/D-03), but the import-graph gate (A3) and the `app_user`-requirement relaxation (A4) must be verified against live code before the sweep.

**Research date:** 2026-07-20
**Valid until:** ~2026-08-20 (stable domain; the one time-sensitive external fact — the google-auth service-to-service API — is a mature, slow-moving Google library). Re-verify A1–A4 at plan time regardless.
