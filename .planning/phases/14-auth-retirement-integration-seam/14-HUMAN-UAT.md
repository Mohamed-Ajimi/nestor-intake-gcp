---
status: partial
phase: 14-auth-retirement-integration-seam
source: [14-VERIFICATION.md]
started: 2026-07-21T00:05:00Z
updated: 2026-07-21T00:05:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live intake→tribunal HTTP seam call (real minted nestor-run token)
expected: A POST to `https://tribunal-api-ybkr7metoq-ew.a.run.app/api/orgs/ensure` with an
identity token minted AS `nestor-run@project-cb01b861-cb4a-438d-b9a.iam.gserviceaccount.com`
(audience = the service URL, no path), headers `X-Nestor-Tenant-Id: 1464b60d-0c20-4c4e-bcf0-27b0301bdba5`,
`X-Acting-User-Id: <your id>`, `X-Acting-User-Email: <your email>`, body `{}` returns **200**
with `tenant_id == the header value` (idempotent no-op against the existing smoke org).
One-liner (Cloud Shell or this repo's shell — writes one idempotent row at most):

    TOKEN=$(gcloud auth print-identity-token \
      --impersonate-service-account=nestor-run@project-cb01b861-cb4a-438d-b9a.iam.gserviceaccount.com \
      --audiences="https://tribunal-api-ybkr7metoq-ew.a.run.app" --include-email) && \
    curl -s -w "\nHTTP %{http_code}\n" -X POST "https://tribunal-api-ybkr7metoq-ew.a.run.app/api/orgs/ensure" \
      -H "Authorization: Bearer $TOKEN" \
      -H "X-Nestor-Tenant-Id: 1464b60d-0c20-4c4e-bcf0-27b0301bdba5" \
      -H "X-Acting-User-Id: operator-uat" -H "X-Acting-User-Email: tools@epicimpact.be" \
      -H "Content-Type: application/json" -d "{}"

note: If impersonation is denied (no serviceAccountTokenCreator on nestor-run), this item
defers to Phase 16's trigger route — the admit path is already proven by-construction
(invoker binding verified live + seam gate 8/8 green + unauthenticated 403 proven live).
result: PASS 2026-07-22 — closed by Phase 16's first real intake-originated seam call:
research run 4cbb5311-9f5f-4504-84bb-b0dda2aedf48 (tribunal run 9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63)
on intake e08620c5. The live trigger minted a real nestor-run identity token, POSTed create_run
through the seam (engine_status=queued), polled /metrics every ~3s (all 200), and the run reached
`completed` (~48 min). Negative proof same day: a direct call with an operator identity token was
rejected with "invalid internal caller token" — the seam admits only nestor-api.

### 2. TRIBUNAL_SERVICE_URL present on live nestor-api
expected: `gcloud run services describe nestor-api` shows env
`TRIBUNAL_SERVICE_URL=https://tribunal-api-ybkr7metoq-ew.a.run.app`
result: pass — verified 2026-07-21 by orchestrator via read-only gcloud describe
(`{'name': 'TRIBUNAL_SERVICE_URL', 'value': 'https://tribunal-api-ybkr7metoq-ew.a.run.app'}`)

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
