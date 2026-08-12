---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
verified: 2026-08-12T13:40:00Z
status: human_needed
score: 24/24 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Walk 22-UAT.md PART A + PART B in full (A1–A5, 22-B1..22-B6, R1–R3)"
    expected: "Every check records PASS/FAIL/NOT-OBSERVABLE from live operator observation on recorded data"
    why_human: "Hover intent/feel, collapse feel, Esc/focus-trap/focus-restore, no-background-scroll and the IntersectionObserver-driven nav-rail active marking have zero automated coverage in this repo (no RTL, IntersectionObserver never fires under vitest/SSR) — recorded by design as U1–U5 in 22-UAT.md"
  - test: "Rule A3i — keep or strike the fourth hover-card line (the affordance hint)"
    expected: "An explicit operator ruling, then routed (implemented or recorded as a deferred item)"
    why_human: "Genuinely open design question flagged in 22-UI-SPEC.md and 22-UAT.md; not resolvable from code"
  - test: "Rule A4c — add an on-screen explanation for sparse citation numbering, or leave it out"
    expected: "An explicit operator ruling, then routed"
    why_human: "Genuinely open copy/UX question, deliberately left to the operator by 22-RESEARCH.md and 22-UAT.md"
  - test: "Redeploy tribunal-api once CR-01 and WR-01 fixes (commits 2666653, 61ae873) are ready to ship"
    expected: "New tribunal-api revision built from a commit at or after 61ae873, imageDigest proven"
    why_human: "Operational/deploy decision — not a code defect. The currently-deployed revision tribunal-api-00020-rjw was built at 13ddb61, which is 4 commits and BOTH post-review fixes behind current HEAD (61ae873). Production still serves the CR-01 funnel-coercion bug (fabricated 0/1 figures) until redeployed."
---

# Phase 22: Verification Report as a Page + Citation Hygiene — Verification Report

**Phase Goal:** Move the verification report onto its own dashboard-styled page, make citations
hoverable with a collapsed-by-default list, collapse duplicate citations to one number per source
(read side), and remove the redundant activity feed from the intake detail page — per operator
rulings D-22-1 … D-22-5 recorded in `22-CONTEXT.md`.

**Verified:** 2026-08-12T13:40:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Method

This is a goal-backward verification against `22-CONTEXT.md` (the D-22-* rulings), not
`.planning/REQUIREMENTS.md` — this phase carries no REQUIREMENTS.md ids by design, confirmed by the
orchestrator brief and by the plans' own frontmatter (all five `must_haves` blocks trace to D-22-1
through D-22-5, never to a `REQ-` id). I independently re-ran the fast gates rather than trusting the
SUMMARY/orchestrator claims, and read every file a must_have or a review finding named.

**Independently re-run, not merely trusted:**
- `npx tsc --noEmit` (frontend/) → **exit 0, zero output.**
- `npx vitest run` (frontend/) → **77 passed / 7 files** (`citationIndex.test.ts` 16/16), matches the
  claimed baseline exactly.
- `node scripts/i18n-audit.mjs` (run from `frontend/`, the CWD it requires) → **RESULT: PASS — A/B/C
  clean (107 CHECK D advisories)**, byte-identical count to the claimed pre-phase baseline.
- Local pytest for the engine's two Windows-only-blocked test files was **not** re-run (this machine
  has no bare `python`/`py` on PATH outside the gcloud-bundled interpreter noted in prior-session
  memory); I instead verified `test_citation_dedupe.py` contains 37 `def test_` functions (consistent
  with the reported 34/37 pass counts across two claimed runs) and that
  `test_verification_report_endpoint.py` exists. The Cloud Build engine gate
  (`18cee1fb-597d-4660-a831-5cc71c66ae7d`, SUCCESS, 1945 passed) is the authority for the engine side
  regardless.
- I did **not** re-run the Cloud Build gate or re-verify Cloud Run digests via `gcloud` (no live
  gcloud session in this agent invocation) — I verified the runbook's recorded digests and revision
  names are present and internally consistent, and cross-checked the deploy commit against git log
  (see Gaps Summary — the deploy-freshness finding is mine, not inherited from the orchestrator note).

## Goal Achievement

### Observable Truths

| # | Truth (D-22-*) | Status | Evidence |
|---|---|---|---|
| 1 | D-22-1: The report has its own route, reached only by navigation from the run page | VERIFIED | `frontend/src/routes/admin.pulse.runs.$runId.verification.tsx` is a real leaf route (`createFileRoute("/admin/pulse/runs/$runId/verification")`); `admin.pulse.runs.$runId.tsx` does not exist (renamed to `.index.tsx`), so no Outlet/layout-promotion scar. `canHaveVerificationReport` is imported and called at exactly one site, `admin.pulse.runs.$runId.index.tsx:325` — the report page itself has zero references to it, by documented design (a second gate would create a second source of truth, `verification.tsx:38-47`) |
| 2 | D-22-1: The page resolves its intake only from `locateResearchRun(runId)`, never a query param | VERIFIED | `verification.tsx:75` calls `locateResearchRun(runId)` inside the cold-open `useEffect`; no `useSearch`/query-param read anywhere in the file |
| 3 | D-22-2: Every section the report rendered before still renders, same order, nothing dropped/summarised | VERIFIED | `VerificationReport.tsx` renders sections in the E1–E9 order specified (`id="refuted"` then support/insufficient/superseded-verdicts/superseded/reconciled/unverified/citations/cost); `VerdictSection` still returns `null` on an empty list, same as pre-phase — omission-when-empty is pre-existing, not new dropping |
| 4 | D-22-2: A trust-relevant stat pair (claims checked / refuted) is visible without scrolling, and the funnel reads as proportion | VERIFIED | Six `StatTile`s render above the section list (`VerificationReport.tsx:542-566`); the funnel renders `width: (count/max)*100%` bars (`:588` region), not a `stage: count` text list |
| 5 | D-22-2: Section headings are visibly heavier than the metadata inside them, each a real `<h2>` with an id | VERIFIED | `SECTION_HEADING_CLASS` used consistently; `ReportSection` renders `<h2 id={...}-heading>` (`:221`); ids present on every section |
| 6 | D-22-3: Hovering `[n]` shows title + retrieved date + tier only, plus one affordance line — no URL/provider/snapshot | VERIFIED | `CitationPanel.tsx` `CitationMarker`'s `HoverCardContent` renders exactly title, `t("citation.retrieved", …)`, the tier glyph+label, and `t("verification.hoverClickHint")` — no URL, provider or `snapshot_text` field present |
| 7 | D-22-3: The hover makes no network call | VERIFIED | Every hover field is read off the in-memory `Citation` object passed as a prop; no `fetch`/`getSource` call inside `CitationMarker` — `getSource` is called only from the click-opened `CitationPanel` |
| 8 | D-22-3: Clicking `[n]` closes the hover card, then opens the full panel, in that order | VERIFIED | `CitationPanel.tsx:103-106`: `onClick={() => { setOpen(false); onOpen(citation); }}` — controlled `HoverCard`, deterministic order, exactly as `22-UI-SPEC.md §2.5` prescribes |
| 9 | D-22-3: No screen says "Published" about `source.fetched_at` any more | VERIFIED | `citation.published` absent from all three locale files (`grep` returns nothing); the only remaining string "Published" in `frontend/src` is inside a code *comment* explaining what NOT to render; both hover card and panel use `citation.retrieved` |
| 10 | D-22-3: Tier is legible without colour — glyph + text label, always both | VERIFIED | `CitationTierGlyph` renders three ink/outline squares plus the text label is rendered adjacent in every call site read (hover card, panel, citation-list row) |
| 11 | D-22-3: The citation list is collapsed by default, and the count is visible while collapsed | VERIFIED | `Collapsible defaultOpen={false}` (`VerificationReport.tsx:784`); the trigger row always shows `t("verification.citationsCount", { count: sourcesCited })` regardless of open state |
| 12 | D-22-3: Clicking `[n]` opens a visible panel even while the citation list stays collapsed | VERIFIED | `CitationPanel` is hoisted into a page-level `<Sheet>` (`:868-890`), rendered outside the `Collapsible` entirely, driven by `openCitation` state shared across all sections — the exact fix `22-UI-SPEC.md §2.6` and plan 22-08 required |
| 13 | D-22-4: Two citation entries whose URLs normalize to the same key collapse to one entry | VERIFIED | `collapse_citations_by_url` in `dedupe.py`, called from `report.py:738` immediately after `number_citations`; `test_citation_dedupe.py` has 37 `def test_` functions covering this, including `test_two_different_documents_on_one_host_are_not_collapsed` as the negative control |
| 14 | D-22-4: The surviving entry never has its `n` reassigned | VERIFIED (by code inspection + test names) | Dedupe seam sits downstream of `number_citations` per 22-CONTEXT's "NEVER RENUMBER" rule and D-22-4's own must_have wording; plan 22-01's SUMMARY and the module docstring both assert this is enforced by construction (survivor keeps its original key) — I did not re-derive this from a fresh property test run, so this line is verified by static reading of the seam order and existing named tests, not by an independent property proof |
| 15 | D-22-4: A claim whose only source was absorbed still resolves a marker, via `also_claim_ids` | VERIFIED | Seam traced end-to-end: `dedupe.py:292` (`also_claim_ids`) → `runs/schemas.py:477` (`also_claim_ids: list[str] = []` on `VerificationCitation`) → `research.ts:205` (`also_claim_ids?: string[]`) → `citationIndex.ts:55` (`Array.isArray(c.also_claim_ids) ? c.also_claim_ids : []`, defensively typed). `citationIndex.test.ts` 16/16 passing includes alias-indexing cases |
| 16 | D-22-4: A URL with no derivable host is never merged with another host-free URL (WR-01 fix) | VERIFIED | `dedupe.py:221-222`: `if not host: return None` — confirmed present at HEAD (commit `61ae873`). `test_two_different_hosts_do_not_collide_when_the_scheme_is_missing` (`test_citation_dedupe.py:489`) is the exact regression test the review asked for, plus `test_a_real_host_still_normalises_after_the_host_guard` as the positive-control follow-up |
| 17 | D-22-4: The "Sources cited" stat tile and the collapsed-list count read the same computed value | VERIFIED | Both read `sourcesCited`, a single `const sourcesCited = citations.length` (`VerificationReport.tsx:352`) — not two independent `.length` calls |
| 18 | D-22-4: No duplicate-collapse count or corroboration figure appears anywhere on the page | VERIFIED | No such string/computation found in `VerificationReport.tsx`; stat tile 5 is labelled "Sources cited," not "duplicates removed" |
| 19 | D-22-5: The intake detail page no longer renders the activity feed / stage list / verification report | VERIFIED | `admin.pulse.intakes.$id.tsx` imports only `IntakeOpenRunLink` from `ResearchRunProgress` (line 57); no import of `ResearchRunProgress` itself, `VerificationReport`, `AgentFeed` or `StageSummaryCard` |
| 20 | D-22-5: The "Open run" link survives and still works | VERIFIED | `IntakeOpenRunLink` rendered at `admin.pulse.intakes.$id.tsx:1188`; exported from `ResearchRunProgress.tsx:252`, wraps `useActiveResearchRun` + the existing link target, matching the module's own stated purpose |
| 21 | D-22-5: `ResearchRunProgress.tsx` still exists and still exports `useActiveResearchRun` | VERIFIED | File present, `export function useActiveResearchRun(...)` at line 157 |
| 22 | The route rename does not break existing `Link to="/admin/pulse/runs/$runId"` call sites | VERIFIED | `npx tsc --noEmit` exit 0 — this would fail to typecheck if the generated route tree disagreed with any existing `to=` literal |
| 23 | The i18n hard gate (CHECK A/B/C) stays green with the new/removed/renamed keys | VERIFIED (re-run myself) | `node scripts/i18n-audit.mjs` → `RESULT: PASS — A/B/C clean` |
| 24 | Phase 22 has a walkable operator UAT document on recorded data, and DEF-21-02's B2/B3/B4 are marked SUPERSEDED with named successors while B1/B5/B6 are CARRIED FORWARD | VERIFIED | `22-UAT.md` exists, fully structured with per-check verdict slots; `21-UAT.md` carries `SUPERSEDED by D-22-1 → 22-B2/B3/B4` and `CARRIED FORWARD → 22-B1/B5/B6` annotations at the cited lines |

**Score:** 24/24 truths verified (one, #14, verified by static/seam inspection rather than an
independently-executed property test — noted, not treated as a failure, since two named regression
tests exist and the seam order is unambiguous in the code)

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `tribunal/nestor_pulse_sdk/citations/dedupe.py` | shared `normalize_source_url` + `collapse_citations_by_url` | VERIFIED | Both exported; WR-01 host guard present at HEAD |
| `tribunal/nestor_pulse_sdk/tests/test_citation_dedupe.py` | unit coverage incl. never-renumber + host guard | VERIFIED | 37 `def test_` functions |
| `tribunal/cloudbuild.test-engine.yaml` | new test file registered in the fast gate | VERIFIED (per orchestrator-reported Cloud Build SUCCESS; not independently re-triggered) | — |
| `frontend/src/lib/research/citationIndex.ts` + `.test.ts` | pure claim→citation index, alias-aware | VERIFIED | 16/16 tests pass (re-run) |
| `frontend/src/lib/api/research.ts` | `Citation.also_claim_ids`, `funnel: Record<string, unknown>` | VERIFIED | Both present; the CR-01 fix's corrected type is at HEAD |
| `frontend/src/components/intake/CitationPanel.tsx` | `CitationMarker`, controlled HoverCard, `citation.retrieved` | VERIFIED | All present |
| `frontend/src/routes/admin.pulse.intakes.$id.tsx` | feed removed, `IntakeOpenRunLink` kept | VERIFIED | — |
| `frontend/src/components/intake/ResearchRunProgress.tsx` | `useActiveResearchRun` + `IntakeOpenRunLink` exported, file not deleted | VERIFIED | — |
| `frontend/src/routes/admin.pulse.runs.$runId.verification.tsx` | the report page, cold-open pattern | VERIFIED | — |
| `frontend/src/routes/admin.pulse.runs.$runId.index.tsx` | renamed run page, link where toggle was | VERIFIED | `canHaveVerificationReport` call site confirmed |
| `frontend/src/components/intake/VerificationReport.tsx` | instrumented-document restyle | VERIFIED | 893 lines (exceeds both plans' `min_lines` thresholds) |
| `tribunal/nestor_pulse_sdk/verification/report.py` | dedupe seam wired | VERIFIED | `collapse_citations_by_url` imported and called |
| `tribunal/nestor_pulse_sdk/runs/schemas.py` | `also_claim_ids` on `VerificationCitation` | VERIFIED | — |
| `.planning/phases/22-.../22-UAT.md` | operator walkthrough | VERIFIED (exists, unrun by design) | — |
| `infra/DEPLOY-RUNBOOK.md` § Phase 22 | derived surface, ordered deploy, digest proofs | VERIFIED | `tribunal-api-00020-rjw` and `nestor-frontend-00030-wvh` digests recorded |

### Key Link Verification

| From | To | Via | Status |
|---|---|---|---|
| `dedupe.py` | `urllib.parse` | `urlparse`/`urlsplit`/`parse_qsl`/`urlencode`, never regex | WIRED |
| `report.py` | `dedupe.py` | `from nestor_pulse_sdk.citations.dedupe import collapse_citations_by_url`, called right after `number_citations` | WIRED |
| `dedupe.py` | `runs/schemas.py` | `also_claim_ids` field name/casing identical | WIRED (confirmed by orchestrator's review + my own grep of all three sides) |
| `runs/schemas.py` | `research.ts` | `Citation.also_claim_ids?: string[]` | WIRED |
| `research.ts` | `citationIndex.ts` | `import type { Citation }`, defensive array-typeof narrowing | WIRED |
| `admin.pulse.runs.$runId.index.tsx` | `admin.pulse.runs.$runId.verification.tsx` | `Link to="/admin/pulse/runs/$runId/verification"` gated by `canHaveVerificationReport` | WIRED |
| `admin.pulse.intakes.$id.tsx` | `ResearchRunProgress.tsx` | `import { IntakeOpenRunLink }` only, never the removed component | WIRED |
| `VerificationReport.tsx` | `@/components/ui/sheet` | page-level `Sheet` hosting `CitationPanel`, outside the `Collapsible` | WIRED |
| `VerificationReport.tsx` | `citationIndex.ts` | `buildCitationIndex` replaces the inline loop | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| Stat strip / funnel | `report`, fetched via `getVerificationReport(intakeId, runId)` | `GET /api/runs/{id}/verification` → tribunal `build_verification_report` | Real engine-computed report, not static | FLOWING |
| Citation list / hover | `citations` from `report.citations` after `collapse_citations_by_url` | Same endpoint, post-dedupe | Real, deduped server-side | FLOWING |
| Funnel bars specifically | `funnelEntries` | `report.funnel` filtered `typeof === "number"` | Filters non-numeric entries out rather than fabricating them (CR-01 fix) | FLOWING (corrected) |

### Anti-Patterns Found

No `TBD`/`FIXME`/`XXX` unreferenced debt markers found in the phase's changed files. No stub returns
(`return null` as a placeholder, empty-array API stubs) found in the touched routes/components beyond
pre-existing, intentional empty-state branches that are spec-required (`verification.emptyReport`,
`verification.notAvailable` deliberately absent per the operator's own scoping — see
`22-UI-SPEC.md`/context note 3 in the brief).

**Open code-review findings, NOT treated as phase-22 must-have gaps** (confirmed still open by direct
inspection, listed for transparency since two of the eight warnings interact with a locked ruling):

| Id | File | Status | Judgment |
|---|---|---|---|
| WR-03 | `CitationPanel.tsx:249-253`, `numbering.py:253` | Open, confirmed | `single_source` still computed pre-dedupe; after collapse, a claim whose sources were duplicates of one page shows one `[n]` with no lone-source warning. Understates risk. Does not violate any must_have text, but is real and worth a follow-up — the CONTEXT.md deferral (DEF-22-06) covers the write-side fix, not this display-side inconsistency, so this specific item is not yet routed anywhere. **Flagging for the operator's attention**, not blocking. |
| WR-05 | `ResearchRunProgress.tsx:616-948` | Open, confirmed via `min_lines` reading | Matches DEF-22-01's own description exactly (deliberately deferred, file must survive). Not a gap. |
| WR-07 | `VerificationReport.tsx:566-567` | Open, confirmed | `costTotal` rendered raw (`value={costTotal ?? "—"}`) without `fmtCost`'s `$`/`.toFixed(2)` formatting used elsewhere in the product. Cosmetic, not covered by any must_have's exact wording (the stat-strip contract specifies the figure source, not its string format), but inconsistent with the run page's own cost display. Worth a small follow-up. |
| WR-01, CR-01 | — | **FIXED**, confirmed by direct code read (see Observable Truths #16 and Data-Flow row 3) | — |

### Requirements Coverage

Not applicable — per the orchestrator brief and confirmed by all ten plans' frontmatter, this phase's
`must_haves` trace exclusively to `22-CONTEXT.md`'s D-22-1 … D-22-5, with no `REQ-` ids anywhere in
the phase directory. Cross-referencing against `.planning/REQUIREMENTS.md` would be a false-gap
exercise and was not performed.

### Human Verification Required

See frontmatter `human_verification`. In summary:

1. **The full `22-UAT.md` walkthrough is unrun** — this is the expected end state of this phase (it
   was written specifically to be run post-merge, at zero spend, per plan 22-09), not a defect. Five
   interaction properties (hover intent/feel, collapse feel, Esc/focus-trap/focus-restore,
   no-background-scroll, and the `IntersectionObserver`-driven nav-rail active state) have **zero**
   automated coverage in this repository by construction (no React Testing Library, and
   `IntersectionObserver` never fires under vitest or SSR) and can only be confirmed by a human.
2. **Two explicit open rulings** (A3i: keep/strike the fourth hover line; A4c: explain sparse
   numbering on-screen or not) are genuinely undecided design questions reserved for the operator by
   `22-UI-SPEC.md` and `22-UAT.md` themselves.
3. **A deploy-freshness gap I found independently** (see Gaps Summary) — not a code defect, but an
   operational state the operator should know before relying on production: the currently-deployed
   `tribunal-api-00020-rjw` was built at commit `13ddb61`, which predates BOTH post-review fixes
   (`2666653` CR-01, `61ae873` WR-01) by 4 commits. `master`/HEAD is correct; **production still
   serves the CR-01 funnel-coercion bug** (a populated `degradation_reasons` list renders as `0`, and
   `verification_degraded: true` renders as a fabricated bar of `1`) until a redeploy ships.

### Gaps Summary

No must-have failed. All 24 observable truths derived from D-22-1 through D-22-5 verified against the
actual codebase, not against SUMMARY.md claims — I independently re-ran `tsc`, `vitest`, and the i18n
audit rather than trusting the reported numbers, and traced the full Python→pydantic→TypeScript
`also_claim_ids` seam and the `collapse_citations_by_url` wiring by reading both sides directly, per
the verification brief's explicit warning about seam defects hiding between plans. Both post-review
fixes (CR-01, WR-01) were independently confirmed present at HEAD with their named regression tests.

The one item elevated beyond a routine WARNING is **deploy freshness**: `tribunal-api-00020-rjw` (the
currently live revision) was built from `13ddb61`, four commits behind current HEAD (`61ae873`) and
missing both post-deploy review fixes. This does not fail any of this phase's must-haves — plan
22-10's must-have was "the deploy surface was derived from this phase's actual diff" and "every
service the diff touches is deployed... proven by imageDigest," both of which were true **at the time
22-10 ran**, before the review found CR-01/WR-01. But it means the operator's live UAT walkthrough
(`22-UAT.md`), if run against production right now, would exercise the CR-01 bug and could
misattribute it to a fresh defect rather than a known-fixed-but-undeployed one. **Recommend a redeploy
of `tribunal-api` before running `22-UAT.md` against production**, or explicitly note the discrepancy
if UAT proceeds anyway.

Three open code-review warnings (WR-03, WR-05, WR-07) remain unfixed but do not defeat any must_have
as written; WR-05 is exactly the deliberate DEF-22-01 deferral. WR-03 and WR-07 are real, minor,
un-routed findings surfaced here for visibility rather than as phase gaps.

---

_Verified: 2026-08-12T13:40:00Z_
_Verifier: Claude (gsd-verifier)_
