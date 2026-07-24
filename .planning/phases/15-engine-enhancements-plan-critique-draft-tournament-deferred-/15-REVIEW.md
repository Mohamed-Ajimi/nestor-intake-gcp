---
status: fixed
phase: "15"
depth: standard
reviewed: 23
critical: 3
warning: 5
info: 7
fixed: 8
date: 2026-07-24
---

# Phase 15: Code Review Report (Research Engine Redesign — Operator Surfaces)

**Reviewed:** 2026-07-24
**Depth:** standard
**Files Reviewed:** 23 (16 Tribunal Python, 2 intake backend Python, 5 frontend TS)
**Status:** issues_found

## Summary

The security-critical invariants hold: the frozen hash-chain payload is untouched
(`_build_payload_dict` / `_payload_for_row` carry no Phase-15 field; `cache_creation_tokens`
lives only in the non-hashed column), `hash`/`prev_hash` are never emitted by any API
response (`AuditBody` and `_verdict_dto` omit them), `verification_verdict` gets
ENABLE + FORCE RLS with a tenant policy from day one, the intake proxies enforce the
superadmin-gate-first existence-hidden 404 discipline, the citation surface renders
`snapshot_text` only (no live-URL fetch), the markdown surfaces use ReactMarkdown without
`rehype-raw` (no HTML injection path), and all new i18n keys exist in en/fr/nl.

However, three Critical defects break the headline deliverables: the frontend
verification report reads response keys the backend never emits (the report renders empty
verdict rows and a permanent "—" cost with the pending label unreachable), the
`cost_pending` flag is dead in production because the production audit writer never
implements `mark_cost_pending` (only the test fake does), and the runs API 500s on the
DB-legal `needs_report_spec` status because the response schemas' status Literal was never
widened.

## Critical Issues

### CR-01: Verification report frontend reads fields the backend never emits — report renders empty

**File:** `frontend/src/lib/api/research.ts:74-94`, `frontend/src/components/intake/VerificationReport.tsx:46-48, 213-217, 233-243`
**Issue:** The backend `VerificationReport` (tribunal `runs/schemas.py:238-258`, shaped by
`verification/report.py:151-181`, proxied **verbatim** by the intake backend) emits:

- verdict items as `{claim_id, verdict, confidence, evidence_refs: list, reconciliation: dict}`
- cost as `true_cost: {cost_usd_total, cost_pending}`
- `unverified: {count, claims_with_verdict, total_claims}` (no `items`)

The frontend type and component instead read:

- `item.claim` / `item.evidence` / `item.effect` (`VerdictItemRow`, lines 46-48) — **none exist**, so every refuted/support/insufficient/superseded/reconciled row renders as an empty bordered `<li>` with no claim text and no skeptic evidence;
- `report.cost.pending` / `report.cost.total` (lines 233-243) — `report.cost` is `undefined`, so the cost **always** renders "Total: —" and the `costPending` label can **never** appear. This silently violates the C1 facts-only display requirement (a pending, incomplete cost is presented as a plain "—" with no pending marker);
- `report.unverified.items` — never emitted (harmless fallback, but the "honest unverified list" is reduced to a count).

**Fix:** Align `VerificationVerdictItem` / `VerificationReport` in `research.ts` with the
backend schema and render the real fields:

```ts
export type VerificationVerdictItem = {
  claim_id?: string | null;
  verdict?: string | null;
  confidence?: string | null;
  evidence_refs?: unknown[] | null;
  reconciliation?: { disputed?: boolean; relation?: string; note?: string; canonical?: string } | null;
  [k: string]: unknown;
};
export type VerificationReport = {
  // ...
  true_cost: { cost_usd_total: string | null; cost_pending: boolean };
  unverified: { count: number; claims_with_verdict: number; total_claims: number };
};
```

In `VerdictItemRow`, render `evidence_refs` entries (join/list) as the evidence block and
`reconciliation.canonical` / `reconciliation.note` as the effect/canonical block; in the
cost section read `report.true_cost.cost_pending` / `report.true_cost.cost_usd_total`.
Add a fixture-driven render test that feeds the real backend shape.

### CR-02: `run.cost_pending` is never set in production — `mark_cost_pending` exists only on the test fake

**File:** `tribunal/nestor_pulse_sdk/audit/audited_llm_client.py:767-773`, `tribunal/nestor_pulse_sdk/audit/writer.py` (whole class)
**Issue:** `end_call` marks the un-itemizable Gemini deep-research grounding fee as pending via
`getattr(self._audit, "mark_cost_pending", None)` and silently does nothing when the writer
lacks the method. The production writer `DBAuditWriter` (writer.py) defines only
`get_prev_hash_and_seq` / `insert_placeholder` / `finalize_row` / `write_full_row` — a repo
grep shows `mark_cost_pending` implemented **only** in `tests/test_cost_cache_write.py:99`
(the fake). The recorded run 4cbb5311 confirms Gemini DR responses come back **without**
`usageMetadata`, i.e. the pending path fires on essentially every production DR call — and
silently no-ops. Consequences: migration 0011's `run.cost_pending` column stays false, the
verification report's `true_cost.cost_pending` is always false, and an incomplete cost is
presented as a settled fact — the exact outcome C1 ("NULL/pending over estimates") forbids.
The optional-`getattr` design plus a fake that implements the method means the suite passes
while the feature is dead in production.
**Fix:** Implement the method on `DBAuditWriter` (own session + tenant context, mirroring the
other writers):

```python
async def mark_cost_pending(self, *, run_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    async with self._sm() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            await session.execute(
                text("UPDATE run SET cost_pending = true WHERE id = :rid"),
                {"rid": str(run_id)},
            )
```

and make it part of the mandatory writer protocol (drop the `getattr` soft-probe, or at
minimum log at ERROR when the writer lacks it).

### CR-03: `needs_report_spec` runs 500 every runs-API read — status Literal never widened

**File:** `tribunal/nestor_pulse_sdk/runs/schemas.py:62-64` (RunResponse), `:183-185` (RunMetrics)
**Issue:** The DB CHECK (`ck_run_status`, synced in `db/models/run.py:118-122`) and the
`submit_report_spec` endpoint (`runs/api.py:436-437`) both establish `needs_report_spec` as a
reachable run status (the interactive report-shaping pause). But both response schemas pin
`status` to `Literal["queued","running","completed","failed","cancelled","needs_input"]`.
`RunResponse.model_validate(run)` on a paused run raises a pydantic `ValidationError` inside
the handler → HTTP 500 on `GET /api/runs/{run_id}` and `GET /api/runs/{run_id}/metrics` for
the entire duration of the pause — precisely when the operator UI must poll to drive the
shaping panel. Worse, `GET /api/runs` (list) 500s for **everyone in the tenant** whenever any
of the 50 most recent runs is paused at `needs_report_spec`.
**Fix:** Add the literal to both schemas (and any shared status type):

```python
status: Literal[
    "queued", "running", "completed", "failed", "cancelled",
    "needs_input", "needs_report_spec",
]
```

Add a regression test that round-trips a `needs_report_spec` run through
`RunResponse.model_validate` and `list_runs`.

## Warnings

### WR-01: Two-phase `end_call` drops cache-creation tokens and server-tool counts for Anthropic — the C1 fix only landed on the atomic path

**File:** `tribunal/nestor_pulse_sdk/audit/audited_llm_client.py:721-725, 755-761, 807-823`
**Issue:** `anthropic_messages` (atomic) correctly extracts `cache_creation_input_tokens` +
`server_tool_use` counts, prices them, and persists `cache_creation_tokens`. The two-phase
`end_call` anthropic branch extracts only `input/output/cache_read` tokens: `compute()` is
called without `cache_creation_tokens` / `web_search_count` / `web_fetch_count`, and
`write_full_row` is not passed `cache_creation_tokens` (persists NULL). Any Anthropic call
routed through `start_call`/`end_call` that writes cache or uses server tools is silently
under-priced and loses the token fact — the same under-count Plan 15-02's C1 fix was meant to
eliminate.
**Fix:** In the anthropic branch of `end_call`, extract
`cache_creation = usage.get("cache_creation_input_tokens", 0) or 0` and
`web_search, web_fetch = _extract_anthropic_tool_counts(usage)`; pass all three into
`compute()` and pass `cache_creation_tokens=cache_creation` into `write_full_row`.

### WR-02: `get_run_report` selects the newest Output of ANY format — a critique corrupts the report

**File:** `tribunal/nestor_pulse_sdk/runs/api.py:950-955`
**Issue:** The report endpoint takes the latest `Output` row with **no `format` filter**, while
sibling code (`create_comparison_content_compare`, api.py:707-712) filters
`Output.format == "markdown"`. Several flows append later non-markdown Outputs to the same
run: `create_comparison_critique` persists `Output(format="critique")` on the anchor
(completed) run, content-compare persists `content_compare`, and rewrite runs carry
`synthesis_cache`/`report_spec` rows. After any of these, `GET /{run_id}/report` returns that
JSON blob as `markdown`/`sections` — corrupting the operator Report viewer and, downstream,
the intake raw-output bundle rebuilt by `_build_and_store_bundle`.
**Fix:** Add `.where(Output.run_id == run_id, Output.format == "markdown")` to the query
(keep the 409 when no markdown output exists yet).

### WR-03: Intake proxies turn tribunal 404s into 500s — unhandled `httpx.HTTPStatusError`

**File:** `backend/app/api/research_routes.py:501-507, 535-541, 574-581` (with `backend/app/research/tribunal_client.py` `raise_for_status()` in every getter)
**Issue:** The three Phase-15 proxies (`get_research_verification`, `get_research_source`,
`get_research_audit_body`) call seam getters that `raise_for_status()`. A tribunal-side 404
(RLS miss, unknown `source_id`/`audit_id`, or `run.tribunal_run_id is None` — which composes
the URL `/api/runs/None/...`) propagates as an unhandled `httpx.HTTPStatusError` → the intake
API answers **500**, not the pinned existence-hidden 404. `get_research_source` is the most
exposed: `source_id` is a free path input never validated intake-side, so every bad id is a
500. This breaks the uniform 404 denial surface the module documents and makes seam failures
indistinguishable from server faults.
**Fix:** In each proxy, guard `run.tribunal_run_id` (404 when NULL) and wrap the seam call:

```python
try:
    return tribunal_client.get_source(...)
except httpx.HTTPStatusError as exc:
    if exc.response.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Research engine unavailable") from exc
```

### WR-04: Cost-table hot-reload can crash the audit write path — no JSON/keys guard in `_load_prices`

**File:** `tribunal/nestor_pulse_sdk/audit/cost_table.py:77-84, 154-159`
**Issue:** The module contract is "never fail, never guess — return None". But
`_load_prices()` only guards `FileNotFoundError`; a malformed `cost_prices.json` (the file is
explicitly designed to be hot-edited in place — a truncated write mid-reload is the expected
failure mode) raises `json.JSONDecodeError` out of `compute()`, which is invoked inside
`anthropic_messages`/`end_call` **before** the audit row is written — so one bad edit fails
live LLM audit writes. Similarly, `entry["prompt"]`/`entry["cache_read"]`/
`entry["cache_creation_5m"]` raise `KeyError` if a hot-added entry omits a field. `_tool_fee`
already guards `JSONDecodeError`; `_load_prices` does not.
**Fix:** Wrap the parse in `try/except json.JSONDecodeError` (log warning, return the cached
`_cache["data"]` if present else `{}`), and read rate fields with `entry.get(..., 0)` +
a warning, so a bad price file degrades to NULL costs instead of exceptions.

### WR-05: `derive_quality_tier` provider fallback is dead code that contradicts its comment

**File:** `tribunal/nestor_pulse_sdk/citations/numbering.py:75-79`
**Issue:**

```python
# Provider-level fallback: an official-search provider hints tier 2 over blog.
prov = (provider or "").lower()
if prov in ("anthropic", "google", "openai", "tribunal_skeptic"):
    return 3
return 3
```

Both branches return 3 — the conditional is dead and the behavior contradicts the stated
intent ("hints tier 2 over blog"). Either the sources from search providers should be tier 2
(display bug: they all show "blog/other"), or the comment and dead branch should go.
**Fix:** `return 2` in the provider branch if the tier-2 hint is intended; otherwise delete
the conditional and the misleading comment. Add a unit test pinning the intended tier.

## Info

### IN-01: Duplicate JSON key in cost_prices.json

**File:** `tribunal/nestor_pulse_sdk/audit/cost_prices.json:84, 103`
**Issue:** `"google/deep-research-pro-preview-12-2025"` appears twice; JSON parsing silently
keeps the last. Values are identical today, but a future edit to the first block would be
silently ignored.
**Fix:** Delete one of the two blocks.

### IN-02: `_tool_fee` re-reads the price file from disk on every call; dead assignment

**File:** `tribunal/nestor_pulse_sdk/audit/cost_table.py:93-99`
**Issue:** `prices = _load_prices()` at line 93 is never used (dead code), and the function
re-opens + re-parses `cost_prices.json` on every fee lookup (up to twice per `compute()`)
instead of caching `_tool_fees` alongside the mtime cache.
**Fix:** Keep `_tool_fees` in the `_cache` entry populated by `_load_prices` (before the
underscore-strip) and drop the redundant re-read + dead assignment.

### IN-03: `gemini_generate` hardcodes `cached_tokens=0` despite google cache_read rates in the price table

**File:** `tribunal/nestor_pulse_sdk/audit/audited_llm_client.py:450-451`
**Issue:** The comment claims "Gemini does not have prompt caching", but Gemini context
caching exposes `usage_metadata.cached_content_token_count`, and `cost_prices.json` carries
non-zero `cache_read` rates for every google model. If caching is ever enabled, cached
tokens are billed at the full prompt rate (overstated cost fact).
**Fix:** `cached_tokens = getattr(usage, "cached_content_token_count", 0) or 0`.

### IN-04: Invalid DOM nesting in the D15 feed — `<div>` children of `<ul>`

**File:** `frontend/src/components/intake/ResearchRunProgress.tsx:509-536, 224-239`
**Issue:** `AgentFeed` renders `<StageSummaryCard>` (a `<div>`) and a wrapping `<div>` (agent
card + drill-down panel) as direct children of `<ul>`. Invalid HTML; React logs nesting
warnings and it is a hydration-mismatch risk under SSR (this app SSRs via Nitro).
**Fix:** Wrap both branches in `<li>` (move the `key` to the `<li>`), and drop the inner
`<li>` from `AgentCard` or convert it to a `<div>`.

### IN-05: 7-year retention computed as `7 * 365` days — ~2 days short of 7 calendar years

**File:** `tribunal/nestor_pulse_sdk/audit/gcs_blob.py:180`
**Issue:** `timedelta(days=_RETENTION_YEARS * 365)` ignores leap days, so the per-object
retain-until lands ~1-2 days before the 7-calendar-year mark the legal requirement implies.
**Fix:** Use calendar arithmetic (e.g. `retain_until = now.replace(year=now.year + 7)` with a
Feb-29 guard, or `days=7 * 366` if over-retention is acceptable under "Unlocked" mode).

### IN-06: Fixture per-stage costs omit the recorded cache-creation tokens

**File:** `tribunal/nestor_pulse_sdk/tests/fixtures/run_4cbb5311/loader.py:139-145`
**Issue:** `build_stage_detail` prices each feed item via
`_stage_cost_usd(provider, model, tokens_in, tokens_out, cache_read)` but never passes
`call.get("cache_create")`, even though the same loader persists `cache_creation_tokens` onto
the audit rows (line 250). The D15 feed's "REAL recorded" per-item and per-stage costs
understate exactly the C1 cache-creation component this phase added.
**Fix:** Thread `call.get("cache_create", 0) or 0` into `cost_table.compute` as
`cache_creation_tokens`.

### IN-07: `fmtCost` rounds facts to 2 decimals — sub-cent per-call costs display "$0.00"

**File:** `frontend/src/components/intake/ResearchRunProgress.tsx:168-173`
**Issue:** `Number(cost).toFixed(2)` shows `$0.00` for real non-zero per-item costs (many
recorded per-call costs are sub-cent), which reads as "free" on a facts-only cost surface.
Also converts the Decimal-string through a float (display-only; acceptable, but worth noting
against the no-float-money rule).
**Fix:** For per-item costs use 4 decimal places (or trim trailing zeros:
`n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}``); keep 2 decimals for run totals.

---

## Fix Log (2026-07-24)

All 3 Critical + all 5 Warning findings fixed, plus the 15-VERIFICATION.md SC4
citation-wiring gap. Info findings (IN-01..IN-07) intentionally skipped per fix
scope. One atomic commit per finding on `master`:

| Finding | Commit | Summary |
|---------|--------|---------|
| CR-01 | `6ca4e51` | research.ts + VerificationReport.tsx aligned to the real backend shape (claim_id/confidence/evidence_refs/reconciliation, true_cost, unverified counts); new i18n keys en/fr/nl |
| CR-02 | `fc86581` | `DBAuditWriter.mark_cost_pending` implemented (UPDATE run SET cost_pending=true, own session + tenant context); missing-method case logs ERROR; protocol-presence regression test |
| CR-03 | `03a91e6` | Shared `RunStatus` Literal (incl. `needs_report_spec`) backs RunResponse + RunMetrics; regression test round-trips a paused run through GET + list |
| SC4 gap | `be3fc8a` | `build_verification_report()` surfaces `number_citations()` as `citations` (+ `VerificationCitation` schema); VerificationReport.tsx wires renderCitationMarker + CitationPanel — inline markers on claim-linked rows + numbered-citations section; i18n `citationsTitle` en/fr/nl |
| WR-01 | `ec7b5ad` | Two-phase `end_call` anthropic branch prices cache_creation + web_search/web_fetch and persists cache_creation_tokens; exact-formula regression test |
| WR-02 | `e38df51` | `get_run_report` filters `Output.format == "markdown"` |
| WR-03 | `b4616ee` | Intake proxies guard `tribunal_run_id` NULL and map seam HTTPStatusError 404→404 (existence-hidden) / other→502; two regression tests |
| WR-04 | `99b7ccc` | `_load_prices` degrades on JSONDecodeError (last good table / NULL costs); rate fields via `entry.get` with warning; regression test |
| WR-05 | `554e650` | Dead provider fallback + misleading comment deleted (tier 3 pinned by existing suite) |

Verification performed: locale JSON parse + `i18n-audit.mjs` PASS (3-way parity),
frontend `tsc --noEmit` clean. Python changes are author-by-construction (no local
runtime — dev box has no Python/Docker); Cloud Build gates updated in the same
commits: `test_cost_cache_write.py` (+3 tests), `test_run_status_resilience.py`
(+1), `test_verification_report_endpoint.py` (+1), `test_research_cross_tenant.py`
(+2). Run the tribunal + intake Cloud Build suites before redeploy.

_Fixed: 2026-07-24_
_Fixer: Claude (gsd-code-fixer)_

_Reviewed: 2026-07-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
