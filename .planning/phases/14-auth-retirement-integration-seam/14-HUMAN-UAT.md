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
result: deferred — operator decision 2026-07-21 ("defer uat"); closes naturally via Phase 16's
trigger route (first real intake-originated seam call). Admit path already proven
by-construction: invoker binding verified live + seam gate 8/8 green + unauthenticated 403 live.

### 2. TRIBUNAL_SERVICE_URL present on live nestor-api
expected: `gcloud run services describe nestor-api` shows env
`TRIBUNAL_SERVICE_URL=https://tribunal-api-ybkr7metoq-ew.a.run.app`
result: pass — verified 2026-07-21 by orchestrator via read-only gcloud describe
(`{'name': 'TRIBUNAL_SERVICE_URL', 'value': 'https://tribunal-api-ybkr7metoq-ew.a.run.app'}`)

## Summary

total: 2
passed: 1
issues: 0
pending: 0
skipped: 1 (deferred → Phase 16 trigger route)
blocked: 0

## Gaps
