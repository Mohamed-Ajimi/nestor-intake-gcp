---
phase: 14-auth-retirement-integration-seam
reviewed: 2026-07-20T00:00:00Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - .gcloudignore
  - backend/app/core/config.py
  - backend/app/research/__init__.py
  - backend/app/research/tribunal_client.py
  - backend/tests/test_tribunal_client.py
  - backend/tests/test_tribunal_seam_denial.py
  - infra/DEPLOY-RUNBOOK.md
  - infra/main.tf
  - infra/variables.tf
  - tribunal/cloudbuild.seam-gate.yaml
  - tribunal/infrastructure/cloud-run/deploy-api.sh
  - tribunal/infrastructure/cloud-run/deploy-worker.sh
  - tribunal/nestor_pulse_sdk/auth/__init__.py
  - tribunal/nestor_pulse_sdk/auth/deps.py
  - tribunal/nestor_pulse_sdk/auth/internal_caller.py
  - tribunal/nestor_pulse_sdk/orgs/__init__.py
  - tribunal/nestor_pulse_sdk/orgs/api.py
  - tribunal/nestor_pulse_sdk/orgs/provision.py
  - tribunal/nestor_pulse_sdk/server.py
  - tribunal/nestor_pulse_sdk/tests/test_internal_caller.py
  - tribunal/nestor_pulse_sdk/tests/test_seam_denial.py
  - tribunal/nestor_pulse_sdk/tests/test_seam_rls_denial.py
  - tribunal/requirements.txt
findings:
  critical: 1
  warning: 8
  info: 7
  total: 16
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-07-20
**Depth:** standard
**Files Reviewed:** 23
**Status:** issues_found

## Summary

The core security seam is well constructed: `InternalCallerProvider` verifies the OIDC token
(aud + signature + expiry via `verify_oauth2_token`) BEFORE any header is trusted, the tenant
header is required with the pinned 400, wrong-SA is 403, missing bearer is 401, and the frozen
`AuthClaims` shape is preserved and guarded by a dedicated test
(`test_authclaims_shape_is_frozen`). The intake-side client mints the token keyless with the
path-free audience, and the Terraform delta (dedicated `tribunal-run` SA, repointed grants,
intake-SA-only invoker binding) matches the stated least-privilege intent. No hardcoded
secrets or credential leaks were found in any reviewed file.

However, the review found one Critical defect in the phase's own verification gate — the
runbook's Step 14.g CI denial-gate instructions are both broken (the submit command fails)
and, once "fixed" by an operator, produce a false green (the intake image skips all four seam
denial tests, and the runbook never invokes the `cloudbuild.seam-gate.yaml` that was created
precisely to close this gap) — plus eight Warnings: a redeploy trap that silently wipes the
seam env vars, event-loop-blocking token verification, a malformed-tenant 500 that breaks the
pinned status-code contract, a provisioning race that can create duplicate projects, a
wildcard CORS surface left on the now-internal engine, the single-env-var `LOCAL_DEV_AUTH`
auth bypass, optional D-05 attribution headers, and an undeclared direct dependency on
`google-auth` in both manifests.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Runbook Step 14.g documents a denial gate that cannot execute the denial tests

**File:** `infra/DEPLOY-RUNBOOK.md:1100-1108` (also `.gcloudignore:8`, `tribunal/cloudbuild.seam-gate.yaml:1-26`)
**Issue:** Step 14.g is the operator's SEAM-02 security gate, and it is wrong in three
compounding ways:

1. **The first command fails outright.** `gcloud builds submit backend
   --config=cloudbuild.test.yaml` submits `backend/` as the build source root, but
   `cloudbuild.test.yaml` step 3 does `cd backend` (repo-root-relative) — the build errors
   with `cd: backend: No such file or directory`. The `.gcloudignore` header (lines 1-3)
   states explicitly that the source root "must be the repo root, not the backend/ subdir".
   The correct invocation is `gcloud builds submit . --config=cloudbuild.test.yaml`.
2. **Even when corrected, the gate is a false green.** The runbook claims this build runs
   `backend/tests/test_tribunal_seam_denial.py`, but `.gcloudignore:8` excludes `tribunal/`
   from repo-root uploads, so `nestor_pulse_sdk.*` is not importable in that image and every
   seam denial test silently SKIPS via `importorskip` (the documented D-DEF-1 failure mode).
   An operator following the runbook would record "seam denial gate green" while zero denial
   assertions executed.
3. **The real gate is never referenced.** `tribunal/cloudbuild.seam-gate.yaml` exists
   specifically because of (2) — its header says "THIS build green == the SEAM-02 denial gate
   green" and its anti-false-green grep exists to catch exactly this skip class — yet the
   runbook (which calls itself "the enumerated source of truth for the Plan-04 operator live
   session") never mentions it. The second Step 14.g command instead runs the FULL
   `tribunal/cloudbuild.test.yaml`, which the seam-gate header itself says carries
   pre-existing non-Phase-14 failures (D-DEF-3), so it is red for unrelated reasons and
   trains the operator to ignore a red gate.

**Fix:** Rewrite Step 14.g to invoke the focused gate:
```bash
# The SEAM-02 denial gate (6/6 must EXECUTE and pass as non-superuser; skips fail the gate):
gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.seam-gate.yaml \
  --project="$GOOGLE_PROJECT"
```
and either drop the intake-side command or fix it to `gcloud builds submit .
--config=cloudbuild.test.yaml` with an explicit note that the seam denial suite SKIPS there
(D-DEF-1) and is proven by the seam-gate build only. Update the Step 14.g checklist entry
(line 1159) to match.

## Warnings

### WR-01: Re-running deploy-api.sh silently wipes the live seam env vars (fail-closed outage)

**File:** `tribunal/infrastructure/cloud-run/deploy-api.sh:51,74`
**Issue:** `TRIBUNAL_SERVICE_URL="${TRIBUNAL_SERVICE_URL:-}"` defaults to empty, and line 74
uses `--set-env-vars=...` which REPLACES the service's entire plain-env set. After Step 14.d
has set `TRIBUNAL_SERVICE_URL` live via `--update-env-vars`, any routine redeploy of
tribunal-api where the operator forgets to export `TRIBUNAL_SERVICE_URL` deploys a revision
with `TRIBUNAL_SERVICE_URL=""` — `server.py` then leaves the auth provider uninstalled and
every seam request fails (fail-closed, but a full seam outage introduced by a "re-run safe"
script whose own header claims idempotence). The comment on line 50 ("these defaults let a
re-run carry them idempotently once captured") is only true if the operator remembers to
export the variable — the failure mode is silent at deploy time.
**Fix:** Fail loudly or self-heal, e.g.:
```bash
TRIBUNAL_SERVICE_URL="${TRIBUNAL_SERVICE_URL:-$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --project="${PROJECT}" --format='value(status.url)' 2>/dev/null || true)}"
[ -n "${TRIBUNAL_SERVICE_URL}" ] || echo "WARN: TRIBUNAL_SERVICE_URL empty — seam will fail closed until Step 14.d is re-run"
```
or switch the seam pair to a separate `--update-env-vars` call so a redeploy never clears them.

### WR-02: Blocking network I/O inside the async auth dependency stalls the event loop

**File:** `tribunal/nestor_pulse_sdk/auth/internal_caller.py:97,110,156,177`
**Issue:** `InternalCallerProvider.verify_id_token` is `async def` but calls
`ga_id_token.verify_oauth2_token(token, self._transport, self._aud)`, which performs a
SYNCHRONOUS HTTPS fetch of Google's public certs (google-auth's `requests`-based transport)
on every call — `google.oauth2.id_token` does not cache certs across calls. Because
`get_internal_claims` (async) awaits it directly, every seam request blocks the entire
FastAPI event loop for the duration of an outbound TLS round trip; a slow/timing-out cert
fetch freezes ALL in-flight requests on the instance, including health probes. This is a
correctness-under-concurrency defect, not just performance.
**Fix:** Offload the blocking verify:
```python
from starlette.concurrency import run_in_threadpool
info = await run_in_threadpool(
    ga_id_token.verify_oauth2_token, token, self._transport, self._aud
)
```
(or use `google.auth.transport.requests.Request` with a caching session, or make the
dependency sync-def so FastAPI runs it on the threadpool).

### WR-03: Malformed X-Nestor-Tenant-Id returns 500, breaking the pinned malformed-request 400 contract

**File:** `tribunal/nestor_pulse_sdk/auth/internal_caller.py:179-186` (manifests at `tribunal/nestor_pulse_sdk/orgs/provision.py:98`)
**Issue:** `get_internal_claims` only checks the tenant header for PRESENCE. A present but
non-UUID value (e.g. `X-Nestor-Tenant-Id: not-a-uuid`) is accepted as verified claims, flows
into `get_db_session` → `set_tenant_context(session, "not-a-uuid")` (the RLS GUC is set to an
arbitrary attacker-chosen string inside the open transaction), and then crashes: either
`uuid.UUID(space_id)` in `ensure_org` raises an unhandled `ValueError`, or a later RLS
`current_setting('app.tenant_id')::uuid` cast errors in Postgres — both surface as 500. The
phase's own status-code doctrine ("a malformed request from an authenticated internal caller
is 400") pins exactly this class, and the denial suites never cover the present-but-garbage
case. No data leaks (the cast fails closed), but the contract and the error semantics break.
**Fix:** Validate at the seam boundary, before the claims are constructed:
```python
try:
    uuid.UUID(tenant_id)
except ValueError:
    raise AuthError(f"malformed {HEADER_TENANT_ID} header", status_code=400)
```
and add a `malformed_tenant -> EXACTLY 400` case to `test_seam_denial.py`.

### WR-04: ensure_org / ensure_project get-or-create is racy — duplicate projects or 500 under concurrency

**File:** `tribunal/nestor_pulse_sdk/orgs/provision.py:100-117,133-153`
**Issue:** Both "idempotent" functions use read-then-insert with no conflict handling:
- `ensure_org`: two concurrent calls for the same space both see `session.get(Org, ...) is
  None` and both `INSERT` the same PK → one transaction fails with `IntegrityError` → 500
  (the endpoint's documented "repeated calls are safe" contract does not hold concurrently).
- `ensure_project`: worse — the `select(...).limit(1)` + insert race creates TWO project rows
  for one space. There is no unique constraint on `Project.tenant_id` backing the
  "exactly one project per space" invariant, so once Phase 16 persists `project_id`
  intake-side, two racing superadmin clicks can bind different project ids for the same
  space permanently.
**Fix:** Add a partial/unique constraint (one project per tenant) and use
`INSERT ... ON CONFLICT DO NOTHING` + re-select (or catch `IntegrityError`, rollback to a
savepoint, and re-read) in both functions.

### WR-05: Wildcard CORS left on the now strictly-internal Tribunal API

**File:** `tribunal/nestor_pulse_sdk/server.py:59-65`
**Issue:** Phase 14 retires the entire browser-facing surface ("the Tribunal API is now a
strictly-internal engine"), yet the app still installs
`CORSMiddleware(allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])`. A
server-to-server seam needs no CORS at all; the wildcard both contradicts the intake
project's own no-permissive-CORS doctrine (`backend/app/core/config.py:127-137` explicitly
forbids `"*"`) and advertises cross-origin readability of any endpoint a future IAM/ingress
misconfiguration exposes. Retiring the browser surface without retiring its CORS grant is a
retirement gap of exactly the Phase 14 kind.
**Fix:** Delete the `app.add_middleware(CORSMiddleware, ...)` block (or gate it behind
`LOCAL_DEV_AUTH` if a local browser tool still needs it).

### WR-06: LOCAL_DEV_AUTH is a single-env-var full auth bypass reachable in deployed mode

**File:** `tribunal/nestor_pulse_sdk/server.py:51,105-117`
**Issue:** Setting `LOCAL_DEV_AUTH=1` on the deployed service replaces the entire seam
(OIDC verify + SA pinning + tenant header validation) with a fixed dev identity — the gate
"is this env check alone" per the code's own comment, and the only safeguard is an
import-time `warnings.warn`. One mistaken `--update-env-vars LOCAL_DEV_AUTH=1` (or a stale
value carried through the WR-01 `--set-env-vars` replacement semantics) silently disables
authentication on a service that fronts cross-tenant research data. Given this phase's
threat model (T-14-05: "never a silent auth downgrade"), an env flag alone is too weak a
gate for a total bypass.
**Fix:** Refuse the bypass when running on Cloud Run:
```python
if LOCAL_DEV_AUTH and os.environ.get("K_SERVICE"):
    raise RuntimeError("LOCAL_DEV_AUTH=1 is forbidden in a deployed environment")
```
(`K_SERVICE` is injected by Cloud Run and cannot be unset by the operator flow).

### WR-07: D-05 acting-user attribution headers are silently optional — audit rows can carry an empty actor

**File:** `tribunal/nestor_pulse_sdk/auth/internal_caller.py:188-196`
**Issue:** The tenant header is REQUIRED (pinned 400), but `X-Acting-User-Id` and
`X-Acting-User-Email` default to `""` when absent. A seam call missing them succeeds and
produces `AuthClaims(app_user_id="", email="", ...)`, which flows into the audit binding
(`request.state.user`) and every downstream audit row — silently voiding the D-05 "the human
is attributed" guarantee this phase names a hard legal constraint (frozen audit chain,
2026-08-02 deadline). The intake client always sends them today, but the contract as coded
permits attribution-free writes, and no test pins the behavior either way.
**Fix:** Either require both headers with the same pinned 400 as the tenant header, or (if
optional is a deliberate decision) document it in the module docstring and add a test
asserting the sentinel behavior so the choice is explicit rather than accidental.

### WR-08: google-auth is now a direct import but is undeclared/unpinned in both dependency manifests

**File:** `tribunal/requirements.txt:20-21` and `backend/pyproject.toml` (deps list; also `backend/app/research/tribunal_client.py:43-44`, `tribunal/nestor_pulse_sdk/auth/internal_caller.py:60-61`)
**Issue:** Phase 14 makes `google-auth` a DIRECT dependency on both sides —
`internal_caller.py` and `tribunal_client.py` import `google.auth.transport.requests` and
`google.oauth2.id_token` — but neither manifest declares it. `tribunal/requirements.txt`
states "every direct dep pinned with `==`" (D-09) yet relies on `google-auth` arriving
transitively (via `google-cloud-storage` / `google-adk`); `backend/pyproject.toml` goes
further and carries a now-stale instruction, "google-auth arrives transitively via
google-cloud-storage — do NOT pin it separately", written before this phase made it a direct
import. A future major-version bump of the transitive carrier can break the security seam's
token minting/verification without any manifest change flagging it.
**Fix:** Add `google-auth==<current resolved version>` to `tribunal/requirements.txt` and
`"google-auth>=2,<3"` to `backend/pyproject.toml` dependencies; update the stale Phase-9
comment.

## Info

### IN-01: Stale contradictory comment on the tribunal-api invoker gating

**File:** `infra/main.tf:1147-1148`
**Issue:** The tribunal-api block header says the invoker is "gated on the same
var.allow_unauthenticated toggle as the intake api", but the Phase-14
`tribunal_api_invoker` resource (lines 1265-1278) is deliberately UNCONDITIONAL and bound to
the intake SA only — the comment describes the retired Phase-13 posture and now contradicts
the security-relevant comment 120 lines below it.
**Fix:** Update the block header to describe the unconditional intake-SA-only binding.

### IN-02: The intake-side seam denial suite is a permanently-skipping 363-line duplicate

**File:** `backend/tests/test_tribunal_seam_denial.py:1-363`
**Issue:** With `tribunal/` in `.gcloudignore`, this file's `importorskip` guards skip all
four cases in every environment that exists today; the executing copy is
`tribunal/nestor_pulse_sdk/tests/test_seam_denial.py`, duplicated near-verbatim. Two copies
of a security suite that must stay identical will drift silently (only one is ever run).
The docstring documents the intent, but the maintenance risk stands.
**Fix:** Consider reducing the intake copy to a thin contract doc (header constants +
pointer to the executing suite), or add a checksum/needle assertion keeping the pinned
status codes in one place.

### IN-03: Bearer-parse logic duplicated; stale noqa

**File:** `tribunal/nestor_pulse_sdk/auth/internal_caller.py:142-153`, `tribunal/nestor_pulse_sdk/auth/deps.py:111-131`, `tribunal/nestor_pulse_sdk/server.py:75`
**Issue:** `_parse_bearer` re-implements the exact three-step bearer parse from
`get_current_user` (prefix check, split-max-1, empty-token) with AuthError instead of
HTTPException — a future fix to one will miss the other. Separately, `server.py:75` marks
`set_auth_provider` with `# noqa: F401` ("imported but unused") although it IS used at line
140 — the suppression is stale.
**Fix:** Extract one shared `parse_bearer(header: str) -> str` helper; drop the stale noqa.

### IN-04: tribunal_service_url is not normalized against a trailing slash

**File:** `backend/app/core/config.py:104`, `backend/app/research/tribunal_client.py:102,125`
**Issue:** A `TRIBUNAL_SERVICE_URL` ending in `/` (easy operator slip despite the runbook's
capture-from-describe guidance) produces `...//api/orgs/ensure` URLs and an audience string
that mismatches tribunal-api's own env unless both are identically mis-set — failing with an
opaque 401/403 rather than an obvious config error.
**Fix:** Add a `field_validator` that `rstrip("/")`s the value (and/or assert no trailing
slash in `_mint_id_token`).

### IN-05: Module-level google-auth transport shared across threadpool threads

**File:** `backend/app/research/tribunal_client.py:47`
**Issue:** `_TRANSPORT = ga_requests.Request()` wraps a `requests.Session`, which is not
documented thread-safe; the sync FastAPI handlers run on a threadpool, so concurrent seam
calls can drive `fetch_id_token` through the same session simultaneously. Failures would be
rare and transient (connection-pool interleaving), which is why this is Info not Warning.
**Fix:** Construct the transport per call (mints are already per-call), or guard with a lock.

### IN-06: Seam-gate pass-count grep matches substrings

**File:** `tribunal/cloudbuild.seam-gate.yaml:84`
**Issue:** `grep -E "6 passed"` matches "16 passed" / "26 passed" as substrings. Harmless at
the current 6-test count, but the anti-false-green check should be exact.
**Fix:** `grep -E "(^| )6 passed"` (or `grep -Ex` against a stricter pattern).

### IN-07: Transient Google cert-fetch failures are reported as 401

**File:** `tribunal/nestor_pulse_sdk/auth/internal_caller.py:113-116`
**Issue:** The blanket `except Exception` around `verify_oauth2_token` maps a transient
network failure fetching Google's certs (a server-side availability problem) to
`AuthError(401)`, indistinguishable from a genuinely bad token — misleading for the intake
caller's retry logic and for 401-spike alerting. Fail-closed is correct; the code is not.
**Fix:** Catch `ValueError` (the documented bad-token path) as 401 and let/raise transport
errors as 503.

---

_Reviewed: 2026-07-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
