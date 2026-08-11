# Phase 22: Verification Report as a Page + Citation Hygiene — Research

**Researched:** 2026-08-11
**Domain:** TanStack Router file-route mechanics; Python read-path citation identity; frontend dead-code removal
**Confidence:** HIGH (every load-bearing claim was verified by executing code or reading it — see Sources)

---

## Summary

Three of the five research questions had answers that contradict the assumptions carried into
the phase, and all three were settled empirically rather than argued.

**First, the renumbering hazard is real but it does not live where it was expected.** The
verification report page carries **zero pre-baked `[n]`** — every marker on it is rendered at
paint time from `citation.n`. The *deliverable* report markdown is the opposite: `[n]` is baked
into it at synthesis time by `apply_citation_anchors` and frozen forever. So read-time dedupe
cannot desynchronise the page from itself; it can only desynchronise the page from the frozen
deliverable, and only if it **renumbers**. The strategy that avoids this entirely is to dedupe
*after* numbering and keep each survivor's original `n` — never renumber. The displayed list
becomes sparse (1, 2, 4, 7) and that is the correct trade.

**Second, the established root cause is wrong for the path that actually runs.** CONTEXT.md
D-22-4 says the conflict key is "a hash of the snapshot TEXT, not the URL". That is true of
`_upsert_source` in the abstract, but the live Tribunal path calls it with
`snapshot_text=url` (`extractor.py:1100`) — so on every real run the key **is already
`sha256(url)`**. The defect is not text-vs-URL; it is **raw URL vs normalized URL**, and the
dominant duplicate generator is almost certainly Gemini's `vertexaisearch.cloud.google.com`
grounding redirects, where every citation of the same publisher page carries a different opaque
redirect token. This makes `resolved_url` **load-bearing, not a refinement**: strip `www.`, a
trailing slash and UTM params from two different redirect tokens and you still have two
distinct strings. The plan must not promise dedupe it cannot deliver.

**Third, the route rename is safe and needs no `to:` edits.** This was proved by running the
actual `@tanstack/router-generator` against a scratch copy of `src/routes/` with the rename
applied. Both files register as leaves under `AdminPulseRoute` with no parent and no `Outlet`;
the `to` union keeps `'/admin/pulse/runs/$runId'` **without** a trailing slash, so both existing
call sites stay valid untouched.

**Primary recommendation:** Put the read-time dedupe in the engine at
`verification/report.py::build_verification_report`, immediately after `number_citations`, with
the normalization function in a new pure module `citations/dedupe.py`. Collapse by normalized
URL, keep the lowest `n`, never renumber, and carry an additive alias list so no verdict row
loses its marker. Ship the write-time fix as its own phase.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-22-1 — The report gets its own page, not a dropdown (LOCKED)**
> *"verification report should open its own page not a dropdown (too long)"*

The report moves off `/admin/pulse/runs/:runId` onto its own route. What remains on the run page
is navigation to it, not the report body. The Phase 21 availability rule
(`canHaveVerificationReport(status)`, `frontend/src/lib/research/verificationGate.ts`) still
governs whether that navigation is offered — it is tested and must be reused, not reimplemented.

**Consequence for Phase 21's DEF-21-02:** B2, B3 and B4 become obsolete as written. B1, B5 and B6
survive in spirit (the page loads; offered on failed/cancelled; absent on queued/running). This
must be reconciled explicitly in Phase 22's own UAT.

**D-22-2 — Restyle as a dashboard (LOCKED, design open — now RESOLVED by 22-UI-SPEC.md)**
> *"verification report contains very good information , so style it better , like a dashboard"*

The *content* is endorsed — presentation change only. Do not drop, summarise away, or reorder
sections. The funnel, verdict sections and cost block all stay.

**D-22-3 — Citations: hover preview, list collapsed by default (LOCKED)**
> *"the citation should show when you hover over them , and the list of citation should be hidden
> by default and user can expand and see"*

- Hover shows **title + publication date + quality tier only**; no network call.
- Clicking still opens the full `CitationPanel` with stored `snapshot_text` — unchanged.
- The full citation **list** is collapsed by default and expandable.

⚠ `publication_date` is a **retrieval-date proxy** (`source.fetched_at`) — label it "retrieved",
never "published".

**D-22-4 — Duplicate citations collapse to one number per source (LOCKED, both layers)**
> *"there are alot of duplicate citations is there a reason for that , why not remove duplicates
> and have 1 number for it?"*

Operator ruling 2026-08-11: **BOTH layers, read-time first.**
- **This phase:** group by normalized URL when building the citation list, so one URL renders as
  one number. Reversible, no migration.
- **Next:** change the INSERT conflict key to a normalized URL. Sequenced deliberately.

Normalization must prefer `resolved_url` where present, then strip `www.`, a trailing slash, and
tracking params. **Normalization has to be one function used by both layers.**

⚠ Read-time dedupe changes DISPLAY only. Cost and corroboration metrics still count the duplicate
rows until the write-side lands. Do not claim otherwise in the UI.

**D-22-5 — Remove the activity feed from the intake detail page (LOCKED)**
> *"activity shouldnt show on the intake page , we already have a open run button that opens it in
> a different page and it is exactly the same so no need to have it there"*

Remove the embedded `ResearchRunProgress` from `admin.pulse.intakes.$id.tsx`. The "Open run" link
stays. ⚠ This REVERSES Phase 21's R2, with the reversal stated in front of the operator. Verify
nothing else on the intake page depends on that component before deleting it.

### Claude's Discretion

- Route shape for the report page (a sibling of the run route is the obvious fit).
- Where the citation list's expand/collapse control sits, and its default collapsed height.
- Hover implementation (reuse Radix primitives — do not add a dependency).
- Whether the read-time dedupe lives in the API response builder or the frontend, **provided the
  normalization function is shared with the eventual write-side fix.**

### Deferred Ideas (OUT OF SCOPE)

- **The write-side source-identity fix** — ruled in scope as a sequenced follow-up (D-22-4). If it
  does not fit this phase, it is a named next phase, not a dropped idea.
- **Backfilling existing duplicate `source` rows** — not requested.
- **DEF-21-01** (lint red tree-wide) — stays deferred.
- **DEF-21-03 / DEF-21-04** — known Phase 21 defects, deliberately not carried here.
</user_constraints>

---

## Project Constraints (from CLAUDE.md)

| Directive | Applies to this phase |
|-----------|----------------------|
| **Frontend installs use `npm ci`, never `npm install`** | Yes — the lockfile IS committed (`frontend/package-lock.json`, 547 KB, present) |
| `frontend/src/components/ui/` (shadcn) is not modified directly | Yes — `hover-card.tsx`, `collapsible.tsx`, `sheet.tsx`, `skeleton.tsx` are consumed, never edited |
| Tenant isolation enforced server-side at the API layer; no cross-tenant access | Yes — the new route resolves its intake only via `locateResearchRun`, never from a URL param |
| All writes mediated by the backend | N/A — this phase is read-only on the frontend |
| Scope ceiling: flow ends at `decomposed`; `run-research` never invoked | Yes — the new page adds no verb and no trigger |
| Prettier: `printWidth` 100, semicolons, double quotes, `trailingComma: "all"` | Yes |
| `@/` path alias; never relative `../../` cross-directory imports | Yes |
| Errors: RETURN-NO-THROW; user notification via `sonner` toast | Yes — `getVerification` already conforms |
| GSD workflow enforcement — no direct repo edits outside a GSD command | Yes |

⚠ **CLAUDE.md is stale on one point already corrected elsewhere:** its Technology Stack section
describes a Supabase frontend. The research surfaces in this phase are on the GCP path
(`apiFetch` → Cloud Run). Trust the code.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Citation identity (which rows are "the same source") | **API / Engine** (tribunal Python) | — | D-22-4 requires ONE normalization function shared with the Python write path. A TS function cannot be shared with a Python `INSERT`. |
| Deduped citation list + count | **API / Engine** (`build_verification_report`) | — | Makes `citations.length` the single computed value that stat tile 5 and the collapsed-list count both read (UI-SPEC §3.2). |
| `[n]` marker rendering + hover preview | **Browser / Client** | — | Pure presentation over an in-memory `Citation`; no network call (D-22-3). |
| Citation snapshot retrieval (click-through) | **API / Backend** (existing proxy) | Browser | Unchanged — `getSource` → superadmin proxy → tribunal `GET /api/sources/{id}`. Stored snapshot only, never a live re-fetch (T-15-15). |
| Route resolution + auth placement | **Frontend Server / Router** | API | Superadmin-only *by placement* under `admin.pulse`; the API existence-hides independently. |
| Report section layout, nav rail, collapse state | **Browser / Client** | — | Local component state; no persistence. |
| Run activity feed | **Browser / Client** on the run page only | — | D-22-5 removes the second mount; the SSE stream that fed it dies with the unmount. |

---

## Standard Stack

### Core — NO NEW DEPENDENCIES

Verified present in `frontend/package.json` and vendored in `frontend/src/components/ui/`:

| Package | Version in package.json | Purpose | Vendored wrapper |
|---------|------------------------|---------|-----------------|
| `@radix-ui/react-hover-card` | `1.1.17` | the `[n]` preview | `src/components/ui/hover-card.tsx` ✓ |
| `@radix-ui/react-collapsible` | `1.1.14` | the collapsed citation list | `src/components/ui/collapsible.tsx` ✓ |
| `@radix-ui/react-dialog` | `1.1.20` | hosts the page-level `Sheet` | `src/components/ui/sheet.tsx` ✓ |
| — | — | loading states | `src/components/ui/skeleton.tsx` ✓ |
| `@tanstack/react-router` | `1.168` (installed) | routing | — |
| `lucide-react` | `0.575` | `ChevronRight`/`ChevronDown`/`ArrowLeft` | — |

**Backend / engine:** no new Python dependencies. URL normalization uses `urllib.parse`
(`urlparse`, `urlunparse`, `parse_qsl`, `urlencode`) — already imported in
`citations/numbering.py:54` and `citations/redirect_resolver.py`.

**Installation:** none. `npm ci` only if `node_modules` needs restoring.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `HoverCard` | `@/components/ui/tooltip` | Tooltip is for a short label on a control; this is a rich multi-line record preview. HoverCard also handles the pointer safe-area between trigger and card, which a tooltip does not. **Use HoverCard.** |
| proportional `div` funnel bars | `recharts` (installed) | recharts is installed but a `div` with a percentage width matches the house language, costs zero bundle weight, and needs no responsive container. **Use divs.** |
| engine-side dedupe | frontend-side dedupe | Frontend-side is architecturally excluded — see Pitfall 1. |
| engine-side dedupe | intake-backend proxy (`research_routes.py:916`) | The proxy's contract is that tribunal JSON "is returned verbatim" (docstring at `research_routes.py:893`). Adding a transform there breaks a stated contract and puts citation semantics in a service that owns none. **No.** |

## Package Legitimacy Audit

**Not applicable — this phase installs zero external packages.**

Every primitive it consumes is already declared in `frontend/package-lock.json` and already
vendored under `frontend/src/components/ui/`. No registry is contacted, no `npx shadcn add` is
run, and the engine side adds only stdlib imports. There is therefore no slopcheck surface and no
`checkpoint:human-verify` install gate for the planner to insert.

If a later plan revision does introduce a package, run the Package Legitimacy Gate before adding
it to any table.

---

## Architecture Patterns

### System Architecture Diagram

```
                        ┌─────────────────────────────────────────┐
   RUN EXECUTION        │  persist_tribunal_claims                │
   (once, ~$45)         │  extractor.py:1095  _upsert_source(     │
                        │      url=<raw provider url>,            │
                        │      snapshot_text=url  ◄── the key IS  │
                        │      resolved_url=<publisher url|None>) │   the URL today
                        └───────────────┬─────────────────────────┘
                                        │ writes `source` rows
                                        ▼
                        ┌─────────────────────────────────────────┐
                        │  DB: claim / claim_source / source      │
                        │  (immutable once the run ends)          │
                        └───────┬─────────────────────┬───────────┘
                                │                     │
        WRITE TIME  ────────────┘                     └──────────── READ TIME
        (synthesis, once)                                          (every page load)
                │                                                          │
                ▼                                                          ▼
   number_citations_with_claims()                            number_citations()
   pipeline.py:4394                                          verification/report.py:661
                │                                                          │
     ┌──────────┴──────────┐                                               │
     ▼                     ▼                                    ┌──────────┴──────────┐
 anchor_number_map    numbered[]                                │  ★ NEW: dedupe seam │
 (prefix → n)              │                                    │  collapse_citations │
     │                     │                                    │  (normalized URL)   │
     ▼                     ▼                                    └──────────┬──────────┘
 apply_citation_      synthesize_report(                                   │
 anchors(text, map)   numbered_citations=…)                     shape_verification_report()
 pipeline.py:4533     steps.py:1153/1396                                   │
     │                     │                                               ▼
     └────────┬────────────┘                              GET /api/runs/{id}/verification
              ▼                                                            │
   ┌────────────────────────────┐                                          ▼
   │ DELIVERABLE report.md      │                     backend proxy (research_routes.py:876)
   │ [n] BAKED IN + ## Sources  │                          "returned verbatim"
   │ ★ FROZEN — unreachable     │                                          │
   │   from any read path       │                                          ▼
   └────────────────────────────┘                          getVerification() → VerificationReport
                                                                           │
                                        ┌──────────────────────────────────┼──────────────────┐
                                        ▼                                  ▼                  ▼
                              verdict-row markers            collapsed citation list    stat tile 5
                              (from citation.n)              (from citation.n)          (citations.length)
                              ── all resolved at PAINT time, none pre-baked ──
```

**The one thing to read off this diagram:** the two `[n]` producers are on opposite sides of the
run boundary. The left branch runs once and its output is frozen. The right branch runs on every
page load. They agree today because they share `_CLAIM_SOURCE_SQL` + `_assign_numbers` and the
rows never change. Anything inserted on the right that *renumbers* breaks that agreement.

### Pattern 1: Dedupe AFTER numbering, never inside it

**What:** collapse the `numbered` list by normalized URL, keeping each group's lowest `n`.
**When to use:** always, for this phase.
**Why:** three separate contracts forbid doing it inside `number_citations`:

1. `test_citation_numbering.py::test_numbering_is_deterministic_and_all_resolve` asserts
   `ns == list(range(1, len(first) + 1))` — **numbers must be CONTIGUOUS 1..N**. Dropping entries
   inside `number_citations` creates gaps and goes red.
2. `test_citation_numbering.py::TestAssignNumbers::test_numbers_sources_at_first_appearance`
   asserts `set(numbered[0]) == {"n", "source_id", "title", "url", "provider",
   "publication_date", "quality_tier", "single_source", "first_claim_id",
   "first_claim_position"}` — an **exact 10-key entry shape**. Adding a `resolved_url` key there
   goes red. `numbering.py:249-251` already records this constraint in a comment.
3. `number_citations_with_claims` feeds the deliverable's anchors and `## Sources` list. Touching
   it changes the ~$45 output, which D-22-4's "read-time first" ruling explicitly defers.

### Pattern 2: keep the original `n`, do not renumber

**What:** the emitted list is sparse — e.g. `[1] [2] [4] [7]` — and that is correct.
**Why:** the deliverable markdown's `[n]` markers were baked by `apply_citation_anchors`
(`pipeline.py:4533`) and cannot be updated by any read path. Renumbering would make `[7]` on the
verification page a different source from `[7]` in the report the operator downloaded. Keeping
the original numbers means every number shown on the page also exists in the deliverable and
points at the same URL.

**Cost of the choice, stated honestly:** gaps are visible. An operator may ask "where is 3?". The
answer — "3 was a duplicate of 1" — is true and defensible. The alternative answer, "the report
and the page disagree about what 7 means", is not.

### Pattern 3: an additive alias list so no verdict row loses its marker

**What:** each surviving entry carries the claim ids of the duplicates it absorbed.
**Why this is mandatory, not a nicety:** `VerificationReport.tsx:210-220` builds
`citationsByClaim` keyed on `first_claim_id`. If claim Y's *only* source was a dropped duplicate,
claim Y renders **no marker at all** — a silent regression on a verdict row that has one today.
Emitting `also_claim_ids` and indexing on it as well keeps every row's marker.

`VerificationCitation` carries `model_config = {"extra": "allow"}` (`runs/schemas.py:463`), so an
additive field rides through the pydantic model and the verbatim proxy without a schema fight.

**Do NOT emit a `duplicate_count`.** UI-SPEC §1.6 bars "N duplicates removed" from the page, and
a field that exists is a field somebody will render.

### Anti-Patterns to Avoid

- **Renumbering to 1..N on read.** Silently contradicts the frozen deliverable. See Pattern 2.
- **Deduping in `VerificationReport.tsx`.** Architecturally excluded — see Pitfall 1.
- **Adding a transform to `backend/app/api/research_routes.py:876`.** Its docstring commits to
  returning the tribunal JSON verbatim; citation semantics do not belong in the intake service.
- **Deleting `frontend/src/components/intake/ResearchRunProgress.tsx`.** The run page imports
  `useActiveResearchRun` from it (`admin.pulse.runs.$runId.tsx:11`). The file survives D-22-5.
- **A card-grid "tile dashboard".** Rejected by operator ruling (UI-SPEC "Visual Direction —
  RESOLVED"). Reintroducing it reverses a ruling.

---

## Research Question 1 — The read-time citation dedupe

### 1a. Where it should live: **the engine's Python read path**

`tribunal/nestor_pulse_sdk/verification/report.py::build_verification_report`, immediately after
line 661 (`citations = await number_citations(session, run.id)`), with the normalization function
in a new pure module `tribunal/nestor_pulse_sdk/citations/dedupe.py`.

**The full traced path, verified:**

```
VerificationReport.tsx:227   getVerification(intakeId, runId)
  → research.ts:393          apiFetch GET /intakes/{id}/research/{runId}/verification
    → backend/app/api/research_routes.py:876   get_research_verification  (superadmin gate,
                                               space scope, existence-hidden 404)
      → tribunal_client.get_verification(...)  research_routes.py:916
        → tribunal GET /api/runs/{id}/verification
          → verification/report.py:629  build_verification_report
            → verification/report.py:661  number_citations(session, run.id)   ★ SEAM
            → verification/report.py:663  shape_verification_report(citations=…)
              → report.py:608  "citations": list(citations)
```

**Three pieces of evidence, each independently sufficient:**

1. **CONTEXT.md's own constraint excludes the frontend.** D-22-4: *"Normalization has to be one
   function used by both layers, or read and write will disagree about identity — which is the
   defect being fixed, reintroduced one level down."* The write layer is
   `citations/extractor.py::_upsert_source` — Python. A TypeScript function cannot be imported by
   a Python `INSERT`. Putting normalization in the frontend **guarantees** the divergence D-22-4
   forbids.

2. **`resolved_url` is not on the wire and cannot get there cheaply.**
   `VerificationCitation` (`runs/schemas.py:443-465`) declares `url` but **not** `resolved_url`,
   and `_CLAIM_SOURCE_SQL` (`numbering.py:147-159`) selects `s.url` only. So the browser cannot
   "prefer `resolved_url`" today at all. Getting it there means a backend change — at which point
   the dedupe belongs there too.
   *(The frontend `Citation` TS type at `research.ts:173-183` does not even declare `url`, though
   the backend does emit it. That is a pre-existing type gap, not a runtime one.)*

3. **One computed value.** UI-SPEC §3.2 requires stat tile 5 and the collapsed-list count to read
   from one value, "not two independent `.length` calls that can drift". Server-side dedupe makes
   `report.citations.length` that value by construction — the frontend needs no dedupe code and
   therefore cannot drift.

**The cost, stated:** this requires deploying the tribunal read service. That is a **read-path**
change — it touches no paid run stage and cannot corrupt a run. But it is a deploy, and this
repo's memory carries a standing "built but never deployed" trap. The planner must schedule the
deploy explicitly and must confirm which Cloud Run service serves `GET /api/runs/{id}/verification`
before assuming one. **[ASSUMED — service name not verified in this session]**

### 1b. Exact URL normalization specification

New module `tribunal/nestor_pulse_sdk/citations/dedupe.py`:

```python
def normalize_source_url(
    url: str | None,
    resolved_url: str | None = None,
    resolution_status: str | None = None,
) -> str | None:
    """The ONE source-identity key. Used by the read path now and the write path next."""
```

Steps, in order:

| # | Step | Detail | Rationale |
|---|------|--------|-----------|
| 1 | **Pick the input** | `resolved_url` when `resolution_status == "resolved"` **and** `resolved_url` is a non-empty string; otherwise `url`. | D-22-4. `'unresolved'` means resolution was attempted and failed — its `resolved_url` is None anyway, but gating on the status makes the intent explicit and survives a future partial write. |
| 2 | **Guard** | Non-string, empty, or `urlparse` failure → return `None`. Never raise. | Read-path code that raises takes down a report the operator already paid for. Matches `_domain`'s `except Exception` idiom (`numbering.py:82`). |
| 3 | **Trim** | `.strip()`. | — |
| 4 | **Scheme** | Lowercase. **Then drop it from the key** (treat `http` and `https` as one source). | The same document served over both schemes is one source. ⚠ This goes beyond CONTEXT.md's literal list — see Assumption A1. |
| 5 | **Host** | Lowercase; strip a leading `www.`; drop a default port (`:80` on http, `:443` on https). | D-22-4 names `www.`. Case and default ports are free and safe — DNS is case-insensitive. |
| 6 | **Fragment** | Drop entirely. | A fragment addresses a position *within* one document, never a different document. |
| 7 | **Query** | Drop tracking params (list below). Sort the survivors by `(key, value)` and re-encode. | D-22-4 names tracking params. Sorting makes `?a=1&b=2` and `?b=2&a=1` one key. |
| 8 | **Path** | Strip **one** trailing `/` unless the path is exactly `/`, in which case use `""`. Do **not** lowercase — paths are case-sensitive on most origins. | D-22-4 names the trailing slash. Lowercasing paths would merge genuinely different documents. |
| 9 | **Assemble** | `f"{host}{path}"` + `f"?{query}"` when query is non-empty. | Scheme-free by step 4. |

**Tracking parameters to strip** (exact list — a closed set, not a prefix rule):

```
utm_source utm_medium utm_campaign utm_term utm_content utm_id utm_name utm_reader
gclid gbraid wbraid dclid msclkid fbclid yclid twclid ttclid igshid
mc_cid mc_eid _hsenc _hsmi vero_id vero_conv
ref_src ref_url spm scm
```

⚠ **`ref` is deliberately NOT in that list.** It is a real, meaningful query parameter on plenty
of sites (git hosts, docs sites, APIs). Stripping it would merge distinct documents — the
opposite failure from the one being fixed, and a worse one. `ref_src` / `ref_url` (Twitter) are
unambiguous and are stripped. **[ASSUMED — the tracking list is judgment, not a verified
standard; see Assumption A2]**

**Do NOT** do any of these — each merges genuinely different documents:
- lowercase the path
- strip `index.html` / `default.aspx`
- normalize percent-encoding
- strip *all* query parameters
- resolve relative paths or `..` segments

### 1c. ⚠ THE RENUMBERING HAZARD — answered

**Question asked:** *does the report body carry pre-baked numbers, or are markers resolved from
the same list at render time?*

**Answer: both, on two different surfaces, and that is the whole finding.**

| Surface | `[n]` source | Mutable at read time? |
|---------|-------------|----------------------|
| **Verification report page** (this phase) | `citation.n`, rendered by `renderCitationMarker` (`CitationPanel.tsx:38-50`) at paint time. Call sites: `VerificationReport.tsx:110` (verdict rows) and `:375` (the list). | **Yes** — it is recomputed on every page load. |
| **Deliverable report markdown** (the ~$45 output) | Baked at synthesis by `apply_citation_anchors(synthesis_text, prefix_to_n)` — `pipeline.py:4533`. The `## Sources` list is rendered from `numbered_citations` at `synthesis/steps.py:1153, 1396`. | **No** — frozen the moment the run finishes. |

**Is there any pre-baked `[n]` on the verification report page?** No. The only markdown it renders
is `MdText` over `evidence_refs`, `reconciliation.canonical` and the amber note
(`VerificationReport.tsx:122, 134, 138`) — skeptic-authored evidence text that never passed
through `apply_citation_anchors`. Verified by reading every render path in the component.

**So the drift is cross-surface, not intra-surface.** Both branches derive from the same
`_CLAIM_SOURCE_SQL` + `_assign_numbers`, and the run's rows are immutable afterwards, so read-time
numbering reproduces write-time numbering byte-identically — a contract stated at
`numbering.py:302-310` and pinned by
`test_citation_numbering.py::test_with_claims_returns_the_identical_numbered_list`.
**Renumbering on read is the one thing that breaks it.**

**Required strategy — dedupe after numbering and REMAP, never renumber:**

1. Group `numbered` by `normalize_source_url(url, resolved_url, resolution_status)`.
2. Canonical entry per group = the one with the **lowest `n`** (deterministic: `_assign_numbers`
   walks the pinned ORDER BY, so first appearance is stable).
3. Emit only canonical entries, **keeping their original `n`**. Entries whose normalized URL is
   `None` (unparseable) are **kept as-is, never merged** — an unparseable URL is not evidence that
   two rows are the same source.
4. On each canonical entry, add `also_claim_ids: list[str]` — the `first_claim_id` of every
   duplicate it absorbed.
5. Frontend: extend the `citationsByClaim` loop (`VerificationReport.tsx:210-220`) to index the
   entry under `first_claim_id` **and** every id in `also_claim_ids`.

**Residual, stated so nobody discovers it later:** for a claim whose source was absorbed, the page
now shows `[3]` where the deliverable body wrote `[8]` for the same sentence. Both numbers point
at the same URL, and `[8]` still exists in the deliverable's own `## Sources` list. Nothing
dangles on either surface. This is the smallest residual any strategy leaves.

### 1d. Other consumers of `number_citations` — verified exhaustively

Repo-wide grep for `number_citations` / `number_citations_with_claims`, excluding tests and the
stale worktree at `.claude/worktrees/agent-af281d695d9b34c35/`:

| Consumer | File:line | Impact of a dedupe placed *after* the call in `build_verification_report` |
|----------|-----------|------------------------------------------------------------------------|
| `build_verification_report` | `verification/report.py:661` | **This is the seam.** Intended. |
| `_load_citation_context` | `pipeline/tribunal/pipeline.py:4394` (`_with_claims`) | **None** — different function, different call, write-time only. |
| `## Sources` renderer | `synthesis/steps.py:1153, 1396` (via `numbered_citations`) | **None** — fed from the pipeline's own call. |
| anchor prefix map | `anchors.py::anchor_number_map` ← `pipeline.py:4395` | **None** — built from `claim_to_n`, not from the entry list. |
| fact ledger | `list_run_claims` → `build_ledger` | **None** — reads `claim` rows only; never touches citations. |
| cost / corroboration metrics | — | **None found.** No consumer of the citations list was located in `runs/api.py` or the cost path. Cost comes from `run.cost_usd_total` (`report.py:667`), independent of citations. |

**Conclusion: exactly one production consumer is affected, and it is the intended one.** The
`## Sources` list in the deliverable, the anchors, the fact ledger and every cost figure are all
upstream of the seam and are untouched.

---

## Research Question 2 — The write-time fix

### 2a. ⚠ CORRECTION: the established root cause is wrong for the live path

CONTEXT.md D-22-4 states the conflict key is *"a hash of the snapshot TEXT, not the URL"* and that
*"dedupe is skipped entirely when there is no snapshot"*.

Both are true of `_upsert_source` read in isolation. **Neither describes the path that runs.**

- The live Tribunal path is `persist_tribunal_claims`, and `pipeline/tribunal/pipeline.py:13`
  states it outright: *"persist_tribunal_claims (NOT extract_and_persist_citations) is the
  persistence path."*
- `persist_tribunal_claims` calls `_upsert_source(..., snapshot_text=url)` at
  `extractor.py:1100` — with the comment `# minimal snapshot; Phase 2 can enrich`.
- Therefore `chash = sha256(url)`. **The conflict key is already the URL** — the exact URL string.
- And because `deduped_urls` never contains an empty string, `chash` is never `None` on this path,
  so **the "no snapshot → skip dedupe" branch (`extractor.py:289-310`) is never taken.**

`extract_and_persist_citations` — the function whose `snapshot_text=report` really does key on
report text — is called only from `pipeline/orchestrator.py:92`, the legacy degraded-parallel
orchestrator, not from the Tribunal pipeline.

**What the defect actually is:** the key is the **raw, un-normalized** URL, and `resolved_url` is
deliberately excluded from it (`_upsert_source` docstring, `extractor.py:262-266`: *"NEITHER is
part of `content_hash` … so supplying them CANNOT change source dedupe"*).

**Why this matters enormously for the fix's expected yield:** the dominant duplicate generator is
almost certainly Gemini's grounding redirects. `extractor.py:1053-1060` documents that *"for the
Gemini streams EVERY url is a `https://vertexaisearch.cloud.google.com/grounding-api-redirect/…`
redirect"*. Every citation of the same publisher page carries a **different opaque redirect
token**, so every one is already a unique string. Stripping `www.`, a trailing slash and UTM
params from two different redirect tokens collapses **nothing**.

**Consequence the plan must absorb:** `resolved_url` is not a refinement of the normalization —
it is the load-bearing part. And it is only populated when:
- `is_redirect_url(url)` is true, i.e. host == `vertexaisearch.cloud.google.com`
  (`redirect_resolver.py:150-173`), **and**
- the best-effort HEAD resolution succeeded inside its 30 s deadline
  (`NESTOR_REDIRECT_RESOLVE_DEADLINE_S`, kill-switchable via
  `NESTOR_REDIRECT_RESOLVE_ENABLED`).

A redirect marked `'unresolved'` **cannot be deduped by any normalization**. The plan must not
claim "duplicates removed" — only "duplicates that are resolvable to a common publisher URL are
merged". This is a real ceiling on the read-time fix, and it is honest to state it up front.

### 2b. What the write-time change requires

**Current backing index** (`alembic/versions/0003_citation_schema.py:66-70`):

```python
op.create_index(
    "idx_source_tenant_content_hash", "source", ["tenant_id", "content_hash"],
    unique=True, postgresql_where=sa.text("content_hash IS NOT NULL"),
)
op.create_index("idx_source_tenant_url", "source", ["tenant_id", "url"])   # NOT unique
```

`ON CONFLICT (tenant_id, content_hash) WHERE content_hash IS NOT NULL`
(`extractor.py:320-321`) requires exactly that partial unique index.

**A migration is unavoidable.** Postgres `ON CONFLICT` needs a unique index on plain columns or an
`IMMUTABLE` expression. The normalization must live in Python (D-22-4's shared-function rule), and
Python is not expressible as a Postgres index expression without duplicating the logic in SQL —
which is the divergence D-22-4 exists to prevent. So the key must be a **plain column written by
Python**:

```python
# alembic/versions/0019_source_normalized_url.py
op.add_column("source", sa.Column("normalized_url", sa.Text(), nullable=True))
op.create_index(
    "idx_source_tenant_normalized_url", "source", ["tenant_id", "normalized_url"],
    unique=True, postgresql_where=sa.text("normalized_url IS NOT NULL"),
)
op.drop_index("idx_source_tenant_content_hash", table_name="source")   # ← see the trap below
```

Existing rows keep `normalized_url = NULL`; NULLs never collide in a unique index, so **no
backfill is required to deploy** — which matches CONTEXT.md's deferral of backfilling.

### 2c. ⚠ The sharpest trap in the write-time work

**The old partial unique index MUST be dropped in the same migration.**

If both unique indexes survive, `ON CONFLICT (tenant_id, normalized_url)` does not cover a
violation of `idx_source_tenant_content_hash`. Two **different** URLs whose snapshot text is
byte-identical would then raise an unhandled `IntegrityError` **inside the final persistence
transaction of a ~$45 run**. That case is not hypothetical: it is the exact scenario
`extractor.py:19` documents as working today (*"identical-content URLs from different providers
dedupe automatically"*).

Note the interaction with 2a: on the live path `snapshot_text=url`, so identical snapshot text
implies identical URL — the collision would not fire for `persist_tribunal_claims`. But it
**would** fire for `extract_and_persist_citations` (`orchestrator.py:92`), where every URL in one
provider report shares the whole report as its snapshot. Dropping the old index is required for
that path to survive.

**Second-order behaviour change to validate on a real run:** `ON CONFLICT … DO NOTHING` means the
**first** row wins and keeps its `title`, `provider`, `resolved_url` and `resolution_status`
(`extractor.py:250-274`). Merging more rows means more cases where the surviving row's provider
attribution and title are the *earlier* one's. That changes which provider is credited for a
source — visible in the report, and not something a unit test can rule on.

### 2d. Verdict: the write-time fix does **not** fit Phase 22

**Reason, not preference:**

1. It requires an **Alembic migration** plus a **unique-index drop that changes dedupe semantics
   for a case that currently works** (2c). The repo's own memory records that migrations here need
   a privilege bootstrap the IaC does not cover.
2. It changes the **paid ingest path** — the transaction that persists a ~$45 run. Phase 22 is
   otherwise entirely read-path and UI. Mixing an ingest change into it means a UI regression and
   an ingest regression share one blast radius.
3. Its correctness **cannot be established without a run.** The provider-attribution change (2c)
   and the actual duplicate-collapse yield (2a) are both only observable on real data.
4. **CONTEXT.md already sequenced it this way.** D-22-4: *"Next: change the INSERT conflict key…
   Sequenced deliberately — the write-side change touches ingest and earns its own validation."*
   Deferred Ideas: *"If it does not fit this phase, it is a named next phase, not a dropped idea."*

**What Phase 22 must still deliver toward it:** the shared `normalize_source_url` in
`citations/dedupe.py`, written to be importable by `_upsert_source` unchanged. That satisfies
D-22-4's ONE-function requirement without shipping the write path. The follow-up phase imports it
rather than re-deriving it.

**Named follow-up:** *Phase 23 — Source identity at write time (normalized-URL conflict key).*

---

## Research Question 3 — Route mechanics — VERIFIED BY EXECUTION

This was not reasoned about. `@tanstack/router-generator` (present in `frontend/node_modules/`)
was executed against a scratch copy of `src/routes/` with the Phase 22 rename applied and a stub
`admin.pulse.runs.$runId.verification.tsx` added. **The repo working tree was not modified** —
the copy, the generated tree and the temp dir all lived under the session scratchpad and were
deleted afterwards. `git status --porcelain` confirms no source file changed.

### 3a. Both routes register as LEAVES — no `Outlet`, no scar

Generated `routeTree.gen.ts`:

```ts
'/admin/pulse/runs/$runId/': {
  id: '/admin/pulse/runs/$runId/'
  path: '/runs/$runId'
  fullPath: '/admin/pulse/runs/$runId/'
  preLoaderRoute: typeof AdminPulseRunsRunIdIndexRouteImport
  parentRoute: typeof AdminPulseRoute        // ← NOT a new parent
}
'/admin/pulse/runs/$runId/verification': {
  id: '/admin/pulse/runs/$runId/verification'
  path: '/runs/$runId/verification'
  fullPath: '/admin/pulse/runs/$runId/verification'
  preLoaderRoute: typeof AdminPulseRunsRunIdVerificationRouteImport
  parentRoute: typeof AdminPulseRoute        // ← same parent, sibling leaves
}
```

Both are direct children of `AdminPulseRoute`, which already renders `<ProductShell>` around its
own outlet. **No `<Outlet/>` is needed anywhere, and the `intake.$id.tsx:41-49`
`useMatches` + conditional-`Outlet` workaround must not be reproduced.** The UI-SPEC §1.1 analysis
is confirmed.

This also matches an existing precedent in the repo: `admin.pulse.intakes.index.tsx`,
`admin.pulse.intakes.new.tsx` and `admin.pulse.intakes.$id.tsx` all exist with **no**
`admin.pulse.intakes.tsx`, and all three register with `parentRoute: typeof AdminPulseRoute`.

### 3b. Index routes and the trailing slash — the `to:` literals stay valid

The generator emits **three** path unions and they differ:

| Union | Value for the index route | Consumed by |
|-------|--------------------------|-------------|
| `FileRoutesByFullPath` / `fullPaths` | `'/admin/pulse/runs/$runId/'` — **with** slash | `fullPath` lookups |
| `FileRoutesByTo` / **`to`** | `'/admin/pulse/runs/$runId'` — **no** slash | **`Link to=` and `navigate({to})`** |
| `FileRoutesById` / `id` | `'/admin/pulse/runs/$runId/'` — **with** slash | `routeId` lookups |

**So both existing call sites remain valid with no edit:**
- `frontend/src/components/intake/ResearchRunProgress.tsx:218` — `<Link to="/admin/pulse/runs/$runId" params={{ runId }}>`
- `frontend/src/components/research/RunActions.tsx:192` — `navigate({ to: "/admin/pulse/runs/$runId", params: { runId: freshId } })`

Both resolve against the `to` union, which keeps the un-slashed form. **The UI-SPEC's warning was
prudent; the empirical answer is that no `to` value needs changing.** The planner should still
keep `tsc --noEmit` as the gate — but must not write an acceptance criterion that *asserts* the
call sites were edited, because they should not be.

### 3c. ⚠ The generator rewrites the route id inside the renamed file

Observed: the generator changed the renamed file's own declaration from

```ts
export const Route = createFileRoute("/admin/pulse/runs/$runId")({
```
to
```ts
export const Route = createFileRoute("/admin/pulse/runs/$runId/")({   // ← trailing slash added
```

This happens automatically when the generator runs (on `vite dev` / `vite build`). A plan that
renames the file and hand-edits `routeTree.gen.ts` without running the generator will leave a
mismatched id. **The plan must run a generation step**, either by starting the dev server /
running a build, or by invoking the generator directly.

### 3d. Is `tsc --noEmit` a sufficient gate? Yes — and the baseline is GREEN

```
$ cd frontend && npx tsc --noEmit ; echo $?
0
```

**Current value: exit 0, zero diagnostics.** So `npx tsc --noEmit` exits 0 in `frontend/` is a
*satisfiable* acceptance criterion — it is green today and must stay green.

It is sufficient for the route question specifically because the `to` union is a literal string
union: a `to` value that no longer exists is a type error, not a runtime surprise. It does **not**
cover the runtime match (does `/admin/pulse/runs/abc` actually render the index route?). That is
covered by the structural evidence in 3a/3b plus the `admin.pulse.intakes` precedent, and should
be confirmed once in UAT rather than asserted by a gate.

⚠ `npm run lint` is **not** available as a gate — DEF-21-01, `frontend/scripts/c.ts` makes
`eslint .` exit 1 tree-wide regardless. Do not write a lint criterion.

---

## Research Question 4 — Removing the embedded feed (D-22-5)

### 4a. The three handlers — each has exactly ONE caller

Verified by grep over `frontend/src/routes/admin.pulse.intakes.$id.tsx`:

| Handler | Defined | Called | Becomes dead? |
|---------|---------|--------|---------------|
| `onRetryResearch` | 801 | **1223 only** | **Yes** |
| `onResumeResearch` | 817 | **1224 only** | **Yes** |
| `onCancelResearch` | 838 | **1225 only** | **Yes** |
| `onStartAutoResearch` | 783 | **1250** (`NextStepBanner`) | **No — SURVIVES** |

All three dying call sites are inside the single `<ResearchRunProgress …>` element at lines
1220-1226.

### 4b. Full dead-code inventory

| Item | Location | Action |
|------|----------|--------|
| `<ResearchRunProgress>` element + its `RESEARCH_SURFACE_STATUSES` guard | `admin.pulse.intakes.$id.tsx:1220-1226` | **Delete** |
| `RESEARCH_SURFACE_STATUSES` const | `:174` — used only at `:1220` | **Delete** |
| `onRetryResearch` / `onResumeResearch` / `onCancelResearch` | `:801`, `:817`, `:838` | **Delete** |
| `import { ResearchRunProgress } …` | `:54` | **Delete** |
| `cancelResearch`, `resumeResearch` in the named import | `:55` | **Delete those two names only** |
| `triggerResearch` in the same import | `:55` | **KEEP** — used at `:786` by `onStartAutoResearch` |

### 4c. ⚠ Do NOT delete `ResearchRunProgress.tsx`

The **file** must survive. `frontend/src/routes/admin.pulse.runs.$runId.tsx:11` imports
`useActiveResearchRun` from it, and the run page is the surface this phase is *keeping*.

But note the resulting state, because it is unusual and the plan should decide about it
explicitly rather than leave it implicit:

- After D-22-5, `admin.pulse.intakes.$id.tsx:54` was the **only** render site of the
  `ResearchRunProgress` *component* in the entire app. The component function becomes
  **unrendered but still compiled**.
- That component also mounts `VerificationReport` at `ResearchRunProgress.tsx:694` — the second,
  now-orphaned copy of the very toggle D-22-1 is replacing. It dies with the component.
- `export { triggerResearch }` at `ResearchRunProgress.tsx:938` already has **zero importers**
  (the intake route imports `triggerResearch` from `@/lib/api/research` directly). Pre-existing
  dead re-export; flag it, do not require its removal.

**Recommended:** keep the file, keep and export `useActiveResearchRun`, and let the plan make an
explicit call on whether to delete the unrendered component body. Deleting it is cleaner but
removes ~350 lines including `VerificationReport`'s second mount — a larger diff than D-22-5
strictly requires.

### 4d. No orphaned state, subscriptions or queries on the intake page

Verified:

- `useActiveResearchRun(intakeId)` is called **inside** `ResearchRunProgress` (`:603`), not by the
  intake route. Grep for `useActiveResearchRun` in `admin.pulse.intakes.$id.tsx` returns **zero
  hits**. Unmounting the component ends its SSE stream; nothing is left dangling.
- `bannerActiveRun` (`admin.pulse.intakes.$id.tsx:261-272`, passed to `NextStepBanner` at `:1240`)
  comes from `useActiveSkillRun` — a **skill** run, not a research run. **Completely unaffected.**
- `AuditBodyPanel` keeps its other importer (`admin.pulse.runs.$runId.tsx:12`). Its doc comment at
  `:45` says "imported only from ResearchRunProgress" — **that comment is already stale** and
  should be corrected if the file is touched.

### 4e. Locale keys — no action required, and no criterion is satisfiable here

`frontend/scripts/i18n-audit.mjs` CHECK A tests **3-way key parity**, CHECK B tests that every
literal `t("key")` **resolves**, CHECK C bans two-arg fallbacks. **None of them detects an orphaned
key.** So removing the render site orphans no gate.

**Current baseline (measured):**
```
$ cd frontend && node scripts/i18n-audit.mjs
RESULT: PASS — A/B/C clean (107 CHECK D advisories)   exit 0
```
107 CHECK D advisories exist **today** and CHECK D never fails the build. A criterion of "zero
i18n advisories" would be unsatisfiable; "the audit exits 0 / RESULT: PASS" is satisfiable and is
the right gate.

⚠ The one locale change this phase **does** require is the `citation.published` →
`citation.retrieved` rename (UI-SPEC §2.3). Verified present in all three locales at **line 648**
of `en`, `fr` and `nl` `intake.json`. It must be renamed in **all three in the same commit** as the
`CitationPanel.tsx:123` edit, or CHECK B goes red.

---

## Research Question 5 — Test surface

### 5a. Measured baselines (state these, do not assume)

| Gate | Command | **Current value** |
|------|---------|-------------------|
| Frontend types | `cd frontend && npx tsc --noEmit` | **exit 0**, zero diagnostics |
| Frontend unit tests | `cd frontend && npx vitest run` | **6 files, 61 tests, 61 passed**, exit 0 |
| i18n audit | `cd frontend && node scripts/i18n-audit.mjs` | **PASS (A/B/C clean), exit 0**, 107 CHECK D advisories |
| Frontend lint | `cd frontend && npm run lint` | **RED tree-wide (DEF-21-01) — not a usable gate** |
| Engine fast gate | `gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml` | **44 test files in the WANTED list** (counted) |

### 5b. Existing tests that touch citations, the report, or these routes

| Test file | Touches | In the 44-file fast gate? | Impact |
|-----------|---------|--------------------------|--------|
| `test_citation_numbering.py` | `_assign_numbers`, `number_citations`, tier heuristic | **NO** — DB-bound, skip-clean without `DATABASE_URL` | **Must stay green.** Pins contiguous 1..N and the exact 10-key entry shape. The recommended design does not touch `numbering.py`, so it should be untouched. |
| `test_citation_anchors.py` | `apply_citation_anchors`, `anchor_number_map`, prefix collisions | **YES** | **Unaffected** — write-path only. |
| `test_citation_roundtrip.py` | `_upsert_source` dedupe, `number_citations` round-trip | **NO** — DB-bound | Unaffected in Phase 22; **central to the write-time follow-up phase.** |
| `test_citation_resolution.py` | redirect resolution | NO | Unaffected. |
| `test_source_resolution.py` | parses migration 0016 (pure) | **YES** | Unaffected in Phase 22; a **precedent to copy** for the follow-up's migration test. |
| `test_verification_report_endpoint.py` | the `/verification` endpoint shape | **NO** | **Will need updating** if the emitted citation list changes shape (the additive `also_claim_ids`). |
| `test_verification_buckets.py` | report bucket classing | NO | Unaffected. |
| `test_suite_hygiene.py` | every `test_*.py` — duplicate bindings, `ast`-lift ban, floor of 80 modules | **YES** | A new test file is safe (98 files on disk, floor 80) **provided** it binds no name twice in one namespace and injects no module globals. |
| `verificationGate.test.ts` | `canHaveVerificationReport` — 10 tests | vitest | **Unaffected** — the rule is imported, not reimplemented (D-22-1). |
| `feedRows.test.ts` | run-feed row derivation | vitest | **Unaffected** — the feed stays on the run page. |

### 5c. ⚠ The determinism contract — precisely what must not break

Two assertions in `test_citation_numbering.py` are the real contract, and the second is stronger
than the ORDER BY the CONTEXT.md warned about:

```python
# test_numbering_is_deterministic_and_all_resolve
assert first == second                                  # byte-identical across calls
ns = [e["n"] for e in first]
assert ns == list(range(1, len(first) + 1))             # ← CONTIGUOUS 1..N, no gaps
```

```python
# TestAssignNumbers::test_numbers_sources_at_first_appearance
assert set(numbered[0]) == {                            # ← EXACT 10-key entry shape
    "n", "source_id", "title", "url", "provider", "publication_date",
    "quality_tier", "single_source", "first_claim_id", "first_claim_position",
}
```

The recommended design keeps both green **by construction**: `numbering.py` is not edited at all,
and the dedupe lives one layer downstream in `build_verification_report`. `resolved_url` is
fetched by a **separate** RLS-scoped read rather than added to `_CLAIM_SOURCE_SQL`, precisely so
the entry shape stays at 10 keys.

### 5d. New tests this phase needs

**Engine (pure — must be added to the `WANTED` list in `tribunal/cloudbuild.test-engine.yaml`,
taking it from 44 to 45):**

`tribunal/nestor_pulse_sdk/tests/test_citation_dedupe.py`
- normalization: `resolved_url` preferred when `resolution_status == "resolved"`; falls back to
  `url` when the status is `'unresolved'` or NULL
- normalization: `www.` stripped, trailing slash stripped, fragment dropped, default port dropped,
  host lower-cased, path case **preserved**
- normalization: each listed tracking param stripped; `ref` **preserved**; surviving params sorted
- normalization: `None` / non-string / unparseable input → `None`, never raises
- collapse: two entries with the same normalized URL → one entry, **keeping the lower `n`**
- collapse: **numbers are NOT renumbered** — assert the surviving `n` values are the originals and
  that gaps are present in the deliberately-duplicated fixture
- collapse: `also_claim_ids` carries the absorbed entries' `first_claim_id`s
- collapse: entries normalizing to `None` are kept separate, never merged
- collapse: determinism — repeated calls on the same input are byte-identical

**Frontend (vitest — 61 → ~70):**

`frontend/src/lib/research/citationIndex.test.ts` (extract the `citationsByClaim` builder from
`VerificationReport.tsx:210-220` into a pure module so it can be asserted, following the
`verificationGate.ts` precedent verbatim)
- a claim id present only in `also_claim_ids` still resolves to its canonical citation
- an entry with no `first_claim_id` is skipped without throwing
- the deduped count used by stat tile 5 and the collapsed-list trigger is one value

⚠ **Do NOT write a test that asserts the engine's dedupe from the frontend.** The frontend
receives an already-deduped list; a frontend test of dedupe logic would be testing code that no
longer exists there.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Hover preview on `[n]` | a custom `onMouseEnter` + absolutely-positioned div | `@/components/ui/hover-card` (Radix) | Pointer safe-area between trigger and card, collision flipping, focus-open, Esc-close, `aria-describedby` wiring — all free, all things a hand-roll gets wrong. |
| Collapsible citation list | `useState` + conditional render | `@/components/ui/collapsible` (Radix) | Supplies `aria-expanded` and the trigger/content association. |
| The click-through panel host | a hand-positioned fixed div | `@/components/ui/sheet` (Radix Dialog) | Focus trap + restore, Esc, scroll lock. **And it must be page-level, not inside the collapsible** — UI-SPEC §2.6. |
| URL parsing / query manipulation | regex over the URL string | `urllib.parse` (`urlparse`, `parse_qsl`, `urlencode`) | IPv6 hosts, credentials, ports, percent-encoding, empty-value params. A regex gets all five wrong. |
| Availability rule for the report | a new status check on the new page | `canHaveVerificationReport` from `@/lib/research/verificationGate` | D-22-1 mandates reuse; it has 10 passing tests and a long docstring explaining why the set is enumerated. **Exactly one call site per page.** |
| Terminal-status set | a fourth local copy | `RESEARCH_TERMINAL` from `@/lib/api/research` | `research.ts:300` explains why it is exported. |
| Route tree | hand-editing `routeTree.gen.ts` | the generator (`vite dev` / `vite build`) | It rewrites the `createFileRoute` id inside the renamed file too — see 3c. |

**Key insight:** the two things this phase is most tempted to hand-roll — URL identity and hover
behaviour — are both dense with edge cases that only show up on real data or with a keyboard. The
stdlib and Radix have already paid for those edge cases.

---

## Common Pitfalls

### Pitfall 1: deduping in the frontend
**What goes wrong:** two normalization implementations — one TS for display, one Python for the
INSERT — that disagree about identity.
**Why it happens:** CONTEXT.md lists frontend placement under "Claude's Discretion", which reads
like permission. But the same decision attaches the condition *"provided the normalization
function is shared with the eventual write-side fix"*, and a TS function cannot be shared with a
Python `INSERT`.
**How to avoid:** engine-side, in `citations/dedupe.py`.
**Warning sign:** a `normalizeUrl` function appearing anywhere under `frontend/src/`.

### Pitfall 2: renumbering to a clean 1..N
**What goes wrong:** the verification page's `[7]` becomes a different source from the
deliverable's `[7]`. Silent, and only discovered by an operator cross-referencing two documents.
**Why it happens:** gaps look like a bug, so the "obvious" tidy-up is to renumber.
**How to avoid:** keep the original `n`. Add a code comment saying why the gaps are intentional —
a future editor will try to close them.
**Warning sign:** any `enumerate(..., start=1)` or `n = i + 1` in the dedupe code.

### Pitfall 3: expecting the read-time fix to collapse most duplicates
**What goes wrong:** the plan promises "duplicates removed", ships, and the operator sees roughly
the same list because the duplicates were unresolved Gemini redirect tokens.
**Why it happens:** the established root cause ("snapshot text") implies simple URL normalization
is enough. The live path already keys on the URL — see 2a.
**How to avoid:** prefer `resolved_url`, and state the ceiling in the plan: only redirects that
resolved can be merged.
**Warning sign:** an acceptance criterion asserting a specific reduction ("N → M citations"). That
number is not knowable before a run and would be unsatisfiable.

### Pitfall 4: a verdict row silently losing its marker
**What goes wrong:** a claim whose only source was an absorbed duplicate renders no `[n]` at all.
**Why it happens:** `citationsByClaim` (`VerificationReport.tsx:210-220`) keys strictly on
`first_claim_id`; dropping an entry drops that key.
**How to avoid:** the `also_claim_ids` alias list, indexed on both sides.
**Warning sign:** a fixture with two claims citing the same URL where the second claim's row has
no marker.

### Pitfall 5: touching `_CLAIM_SOURCE_SQL` or `_assign_numbers`
**What goes wrong:** `test_numbering_is_deterministic_and_all_resolve` or
`test_numbers_sources_at_first_appearance` goes red — and because both are **DB-bound and skip in
the 44-file fast gate**, the break may not surface until much later.
**How to avoid:** do not edit `numbering.py`. Read `resolved_url` with a separate query.
**Warning sign:** a diff to `numbering.py` in a phase whose ruling was "read-time first".

### Pitfall 6: deleting `ResearchRunProgress.tsx`
**What goes wrong:** `admin.pulse.runs.$runId.tsx:11` loses `useActiveResearchRun` and the run
page — the surface this phase is keeping — stops compiling.
**How to avoid:** remove the *element* from the intake page; keep the *file*.
**Warning sign:** `tsc --noEmit` going from 0 to non-zero right after the D-22-5 commit.

### Pitfall 7: writing an acceptance criterion that asserts the `to:` literals changed
**What goes wrong:** the criterion is unsatisfiable — the `to` union keeps the un-slashed form, so
the correct outcome is that those two lines are **not** edited (3b).
**How to avoid:** gate on `npx tsc --noEmit` exiting 0, not on a diff to those files.
**Warning sign:** a grep-count criterion over `ResearchRunProgress.tsx` or `RunActions.tsx`. This
is the Phase 21 failure pattern the team lead flagged.

### Pitfall 8: renaming the file without running the generator
**What goes wrong:** the file's own `createFileRoute("/admin/pulse/runs/$runId")` no longer matches
its generated id `'/admin/pulse/runs/$runId/'` (3c).
**How to avoid:** run a build or dev server, or invoke the generator, as an explicit plan step.

---

## Code Examples

### The dedupe seam — `verification/report.py`

```python
# tribunal/nestor_pulse_sdk/verification/report.py — inside build_verification_report,
# replacing the single line at :661.
#
# ⚠ The dedupe sits HERE, DOWNSTREAM of number_citations, and never inside it. Three
# pinned contracts live in citations/numbering.py that dropping an entry would break:
# contiguous 1..N, the exact 10-key entry shape, and byte-identical agreement with the
# numbering the ~$45 deliverable was written against.
citations = await number_citations(session, run.id)

# resolved_url is NOT on the numbering entry (and must not be added -- the entry shape
# is pinned). One extra RLS-scoped read, keyed on the ids we already hold.
resolution = await _source_resolution(session, [c["source_id"] for c in citations])

# D-22-4 read-time layer: one URL, one number. Numbers are PRESERVED, never reassigned --
# the deliverable's [n] markers were baked at synthesis and can no longer be updated, so a
# renumbering here would make the same number mean two different sources across the two
# documents. Gaps in the displayed list are the intended, honest cost.
citations = collapse_citations_by_url(citations, resolution)
```

### The collapse — `citations/dedupe.py` (new, pure)

```python
def collapse_citations_by_url(
    numbered: list[dict[str, Any]],
    resolution: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> list[dict[str, Any]]:
    """One number per normalized URL. NUMBERS ARE PRESERVED, NEVER REASSIGNED.

    `resolution` maps source_id -> (resolved_url, resolution_status). Absent or
    incomplete is fine: a source with no entry normalizes from its raw `url`.

    Entries whose URL will not normalize are KEPT SEPARATE. An unparseable URL is
    not evidence that two rows are the same source, and merging on "both failed to
    parse" would collapse unrelated citations -- the opposite defect, and a worse one.

    PURE: no DB, no I/O. Never raises.
    """
    resolution = resolution or {}
    by_key: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []

    for entry in numbered or ():
        sid = str(entry.get("source_id") or "")
        resolved_url, status = resolution.get(sid, (None, None))
        key = normalize_source_url(entry.get("url"), resolved_url, status)

        if key is None:
            out.append(entry)          # unmergeable -- kept, unchanged
            continue

        canonical = by_key.get(key)
        if canonical is None:
            # First appearance in the pinned ORDER BY == the lowest n. Deterministic.
            canonical = dict(entry)
            canonical["also_claim_ids"] = []
            by_key[key] = canonical
            out.append(canonical)
            continue

        # A duplicate. Its number disappears from the list; its CLAIM must not lose
        # its marker, so the claim id rides along on the survivor.
        cid = entry.get("first_claim_id")
        if cid and cid != canonical.get("first_claim_id"):
            if cid not in canonical["also_claim_ids"]:
                canonical["also_claim_ids"].append(cid)

    return out
```

### The frontend index — extend, do not replace

```ts
// frontend/src/components/intake/VerificationReport.tsx:210-220, extended.
// The backend now sends ONE entry per source; `also_claim_ids` carries the claim ids of
// the duplicates it absorbed. Without indexing those too, a verdict row whose only source
// was absorbed renders no [n] at all -- a silent regression on a row that has one today.
const citationsByClaim = new Map<string, Citation[]>();
for (const c of citations) {
  const ids = [c.first_claim_id, ...(c.also_claim_ids ?? [])];
  for (const cid of ids) {
    if (typeof cid !== "string" || !cid) continue;
    const list = citationsByClaim.get(cid);
    if (list) list.push(c);
    else citationsByClaim.set(cid, [c]);
  }
}
```

---

## Runtime State Inventory

This phase renames a route file and changes a read path. Five categories, each answered:

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| **Stored data** | **None.** The read-time dedupe writes nothing. No `source`, `claim` or `claim_source` row is created, updated or deleted. Verified: the recommended change is confined to `build_verification_report`, which `report.py:634-638` documents as *"Reads ONLY persisted rows"*. | None |
| **Live service config** | **None.** No n8n workflow, Datadog service name, Tailscale ACL or Cloudflare tunnel references the route path or the citation shape. Verified by grepping the repo for `/admin/pulse/runs` — only the two `to:` literals and `routeTree.gen.ts`. | None |
| **OS-registered state** | **None.** No scheduled task, pm2 process or systemd unit references either surface. | None |
| **Secrets / env vars** | **None added or renamed.** The phase touches no secret. Two *existing* engine env knobs bound how much the dedupe can achieve and must not be changed here: `NESTOR_REDIRECT_RESOLVE_ENABLED` and `NESTOR_REDIRECT_RESOLVE_DEADLINE_S` (`redirect_resolver.py:60-63`) — if resolution is off, `resolved_url` is always NULL and dedupe yield collapses (see 2a). | None — but **read** their deployed values before judging the fix's yield |
| **Build artifacts** | **`frontend/src/routeTree.gen.ts` is a generated, committed artifact and WILL change.** It is not stale-safe: renaming the route file without regenerating leaves the tree and the file's own `createFileRoute` id disagreeing (3c). | **Regenerate** via `vite build` / `vite dev`, and commit the result |

⚠ **Bookmarked URLs.** `/admin/pulse/runs/:runId` keeps working — the index route serves the same
path (3b). No redirect is needed and none should be added.

---

## Environment Availability

Probed on this machine, 2026-08-11:

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | frontend build, tsc, vitest | ✓ | v22.14.0 | — |
| npm | `npm ci` | ✓ | 10.9.2 | — |
| `frontend/node_modules` | tsc, vitest, generator | ✓ | installed | `npm ci` (lockfile committed) |
| `frontend/package-lock.json` | `npm ci` | ✓ | 547 KB | — |
| `@tanstack/router-generator` | route tree regeneration | ✓ | in node_modules | — |
| `typescript` (`npx tsc`) | the type gate | ✓ | runs, exit 0 | — |
| `vitest` | frontend tests | ✓ | 61 tests pass | — |
| `node scripts/i18n-audit.mjs` | the i18n hard gate | ✓ | PASS, exit 0 | — |
| Radix hover-card / collapsible / sheet | UI-SPEC contracts 1-3 | ✓ | vendored in `src/components/ui/` | — |
| **PostgreSQL** | `test_citation_numbering.py`, `test_citation_roundtrip.py`, `test_verification_report_endpoint.py` | **✗** | — | Those files **skip cleanly** without `DATABASE_URL`; they are not in the 44-file fast gate either way |
| **Python / pytest locally** | engine tests | **Partial** | gcloud's bundled Python has pip+venv; a scratchpad venv runs the full gate in ~50 s (per project memory) | Cloud Build `cloudbuild.test-engine.yaml` |
| **Docker** | — | **✗** | — | Not needed by this phase |

**Missing dependencies with no fallback:** none — nothing in this phase is blocked.

**Missing dependencies with fallback:**
- Postgres: the DB-bound citation tests cannot run locally. **They are also not in the fast gate**,
  so the plan must not write a criterion asserting they ran. If the plan wants them proved, it
  needs an explicit DB-backed step and a stated cost.

---

## Validation Architecture

### Test Framework

| Property | Frontend | Engine |
|----------|----------|--------|
| Framework | vitest (via `@lovable.dev/vite-tanstack-config`) | pytest |
| Config file | `frontend/vite.config.ts` (no separate vitest config) | `tribunal/cloudbuild.test-engine.yaml` (the 44-file WANTED list) |
| Quick run command | `cd frontend && npx vitest run` | `python -m pytest nestor_pulse_sdk/tests/test_citation_dedupe.py -x` |
| Full suite command | `cd frontend && npx vitest run && npx tsc --noEmit && node scripts/i18n-audit.mjs` | `gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml --project="$GOOGLE_PROJECT"` |

### Phase Requirements → Test Map

This phase carries **no REQUIREMENTS.md ids**. Its sources of record are `22-CONTEXT.md`,
`22-UI-SPEC.md` and `21-UAT.md`. The decisions are mapped instead:

| Decision | Behavior | Test Type | Automated Command | File Exists? |
|----------|----------|-----------|-------------------|-------------|
| D-22-1 | The report lives at `/admin/pulse/runs/$runId/verification`; both routes typecheck | type | `cd frontend && npx tsc --noEmit` | ✅ (green today) |
| D-22-1 | Availability rule is imported, not reimplemented | unit | `npx vitest run src/lib/research/verificationGate.test.ts` | ✅ 10 tests |
| D-22-2 | Layout only — no content dropped | **manual-only** | — | ❌ **UAT.** A DOM-shape assertion would pin the styling this phase is deliberately changing. |
| D-22-3 | Hover shows title + retrieved date + tier; no network call | **manual-only** | — | ❌ **UAT.** Hover intent + Radix portal behaviour is not worth a jsdom harness for one component; there is no RTL setup in this repo today. |
| D-22-3 | `citation.retrieved` resolves in all three locales; `citation.published` is gone everywhere | integration | `cd frontend && node scripts/i18n-audit.mjs` | ✅ (PASS today) |
| D-22-4 | Normalization: `resolved_url` preferred, `www.`/slash/tracking stripped, `ref` kept | unit | `pytest nestor_pulse_sdk/tests/test_citation_dedupe.py -x` | ❌ **Wave 0** |
| D-22-4 | One entry per normalized URL, **numbers preserved, not renumbered** | unit | same | ❌ **Wave 0** |
| D-22-4 | `also_claim_ids` keeps every verdict row's marker | unit | `npx vitest run src/lib/research/citationIndex.test.ts` | ❌ **Wave 0** |
| D-22-4 | `numbering.py` is untouched | unit | `pytest nestor_pulse_sdk/tests/test_citation_anchors.py -x` (in the fast gate) | ✅ |
| D-22-5 | Nothing else on the intake page depends on the removed component | type | `cd frontend && npx tsc --noEmit` | ✅ |

### Sampling Rate

- **Per task commit:** `cd frontend && npx tsc --noEmit` (≈15 s) — the cheapest gate that catches
  the route rename, the dead-code removal and the `Citation` type change.
- **Per wave merge:** `cd frontend && npx vitest run && npx tsc --noEmit && node scripts/i18n-audit.mjs`
  (≈30 s total).
- **Engine wave merge:** `gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml`
  — **45 files** once `test_citation_dedupe.py` is added to the WANTED list.
- **Phase gate:** all four green before `/gsd:verify-work`; then operator UAT for D-22-2/D-22-3.

### Wave 0 Gaps

- [ ] `tribunal/nestor_pulse_sdk/tests/test_citation_dedupe.py` — covers D-22-4 engine side
- [ ] Add that file to the `WANTED` list in `tribunal/cloudbuild.test-engine.yaml` (44 → 45)
- [ ] `frontend/src/lib/research/citationIndex.ts` — extract the `citationsByClaim` builder out of
      `VerificationReport.tsx:210-220` so it is assertable (follow the `verificationGate.ts`
      precedent verbatim)
- [ ] `frontend/src/lib/research/citationIndex.test.ts` — covers the alias indexing
- [ ] Add `url?: string | null` and `also_claim_ids?: string[]` to the frontend `Citation` type
      (`research.ts:173-183`). `url` is already emitted by the backend but undeclared in TS.

*No framework install is needed — vitest and pytest are both already in place.*

---

## Security Domain

`security_enforcement` is not set to `false` in `.planning/config.json`, so it is enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | **no** (inherited) | The new route adds no auth surface. Superadmin **by placement** under `admin.pulse`, plus `_superadmin_gate` on every verb server-side (`research_routes.py:880`). |
| V3 Session Management | no | No session change. |
| V4 Access Control | **yes** | Existence-hidden 404 (never 403) on cross-tenant/cross-space, already enforced at `research_routes.py:896-908`. The new page must resolve its intake **only** via `locateResearchRun(runId)` and accept **no** intake id from a query parameter (T-15.3-71 / TENANT-02). |
| V5 Input Validation | **yes** | `runId` is a URL param reaching an API call. Existing behaviour is sufficient — the server 404s an unknown id. ⚠ The new `normalize_source_url` parses **remote-host-supplied** strings (`resolved_url` is a `Location` header, `extractor.py:109-115`): it must never raise, and it must not be used to build a request. |
| V6 Cryptography | no | None introduced. `_content_hash` (SHA-256) is untouched in Phase 22. |
| V7 Error Handling / Logging | **yes** | RETURN-NO-THROW; failure surfaces as `verification.loadError` + a `sonner` toast, never a throw. |
| V12 Files / Resources | **yes** | `CitationPanel` renders stored `snapshot_text` only — **never a live-URL re-fetch** (T-15-15 SSRF, T-15-16b). Unchanged and must stay unchanged. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation | Status |
|---------|--------|---------------------|--------|
| SSRF via a citation URL | Information Disclosure | Render stored `snapshot_text`; never fetch `url` client-side | **Already enforced** — `research.ts:423-431`. Hover shows title/date/tier only, so it adds no fetch. |
| Cross-tenant read via a guessed `runId` | Information Disclosure | Server-side space scope + existence-hidden 404 | Already enforced; the new route adds no caller |
| Tenant hint smuggled in a URL param | Elevation of Privilege | Resolve the intake server-side from the run id only | **Must be preserved** — reuse the run page's cold-open block verbatim |
| A remote `Location` header reaching a parser | Tampering | `normalize_source_url` must be total: guard non-strings, catch parse failures, return `None` | **New — this phase must implement it** |
| Stored XSS via `title` in the hover card | Tampering | React escapes text children by default; `title` is rendered as a text node, **never** through `MdText`/`ReactMarkdown` | ⚠ **Watch this.** `rehype-raw` is a project dependency. Do not render `citation.title` as markdown. |
| Unlabelled modal for screen readers | — (a11y, not security) | `sr-only` `SheetTitle` | UI-SPEC §2.6 |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Model emits its own `[n]` | Python assigns every `[n]` from DB ordering; the model writes opaque `[[c:xxxxxxxx]]` anchors | Phase 15.2 (D-05/D-06) | The report body's numbers are **baked at synthesis** — the fact that makes renumbering on read unsafe |
| Source dedupe on snapshot text | (unchanged in code) but the live path passes `snapshot_text=url`, so it is **already URL-keyed** | Phase 15.4-ish, undocumented in CONTEXT.md | Reframes D-22-4 from "text vs URL" to "raw vs normalized URL" |
| Redirect URLs stored as-is | `resolved_url` + `resolution_status` stored beside the redirect (migration 0016) | Phase 15.4 (D-V01-11) | The only lever that can dedupe Gemini grounding redirects |
| Verification report inline on the intake card | Report on the run page behind a toggle | Phase 21 | Phase 22 moves it again, to its own route |

**Deprecated / outdated:**
- `verification.hideAction` — becomes unused once the toggle becomes a `<Link>`. **Leave it in all
  three locales**; CHECK A tests parity, not usage, and deleting it from one file goes red.
- `AuditBodyPanel.tsx:45`'s comment "imported only from ResearchRunProgress" — already stale
  (`admin.pulse.runs.$runId.tsx:12` imports it too).
- `export { triggerResearch }` at `ResearchRunProgress.tsx:938` — zero importers, already dead.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| **A1** | Dropping the **scheme** from the identity key (treating `http://x/a` and `https://x/a` as one source) is correct. CONTEXT.md's literal list names only `www.`, trailing slash and tracking params. | RQ1 §1b step 4 | Low. Two rows that should merge stay separate (a smaller fix), or — much less likely — two genuinely different documents merge. **Recommend confirming with the operator**, since it widens a locked ruling. |
| **A2** | The tracking-parameter list is complete enough, and excluding `ref` is right. | RQ1 §1b step 7 | Low. A missed tracking param leaves a duplicate uncollapsed; stripping `ref` would wrongly merge distinct docs. The list is judgment, not a standard. |
| **A3** | Gemini grounding redirects are the **dominant** duplicate generator. Strongly implied by `extractor.py:1053-1060` ("EVERY url is a redirect") plus URL-keyed dedupe, but **not measured** — no run has been inspected for this. | RQ2 §2a | Medium. If wrong, the read-time fix still helps but the yield estimate is off. **Cheapest resolution: read one run's citation list from the audit bucket** (`gcloud storage cat`, read-only, no spend) and count how many URLs share a resolved publisher host. |
| **A4** | The Cloud Run service serving `GET /api/runs/{id}/verification` was not identified in this session. | RQ1 §1a | Medium — a wrong service name means the dedupe is built and never deployed, which this repo has done before. **Verify before writing the deploy task.** |
| **A5** | `test_verification_report_endpoint.py` will need updating for the additive `also_claim_ids`. Inferred from the filename and the additive-field change; the file's assertions were not read. | RQ5 §5b | Low. Worst case an extra edit. |
| **A6** | The `Citation` TS type omitting `url` is a type gap only, not a runtime gap — the backend declares `url` on `VerificationCitation` (`runs/schemas.py:456`) and `number_citations` emits it. Not confirmed against a live payload. | RQ1 §1a | Low, and it does not affect the recommendation (dedupe is server-side either way). |

**Everything not listed here was verified by executing or reading the code in this session.**

---

## Open Questions

1. **Should the sparse `[n]` list be explained to the operator on-screen?**
   - *What we know:* gaps (1, 2, 4, 7) are the correct outcome, and UI-SPEC §1.6 bars any
     "N duplicates removed" figure.
   - *What's unclear:* whether an operator seeing gaps reads them as a bug.
   - *Recommendation:* ship without an explanation — a note about deduping edges toward the
     "N duplicates removed" claim D-22-4 forbids. Raise it in UAT and let the operator rule.

2. **Delete the now-unrendered `ResearchRunProgress` component body, or leave it?**
   - *What we know:* the file must survive for `useActiveResearchRun` (§4c). After D-22-5 the
     component has zero render sites.
   - *What's unclear:* whether the operator wants the ~350-line removal in this phase.
   - *Recommendation:* leave the body in Phase 22 and record it as a named cleanup item.
     D-22-5's ask is "don't show it on the intake page", which the element removal satisfies in
     full. A large deletion in the same commit widens the blast radius for no operator-visible gain.

3. **How much will the read-time dedupe actually collapse?**
   - *What we know:* only redirects that resolved can merge (§2a).
   - *What's unclear:* the real number on real data.
   - *Recommendation:* measure it **before** planning acceptance criteria, using the read-only
     audit-bucket path (`gcloud storage cat`) — no build, no spend. Then write criteria that state
     a *property* ("no two entries share a normalized URL"), never a *count*.

---

## Sources

### Primary (HIGH confidence — executed or read in this session)

**Executed:**
- `@tanstack/router-generator` (from `frontend/node_modules/`) run against a scratch copy of
  `src/routes/` with the Phase 22 rename applied — produced the route registrations quoted in §3a
  and the `to`-union evidence in §3b. Repo tree unmodified (`git status --porcelain` verified).
- `cd frontend && npx tsc --noEmit` → exit 0
- `cd frontend && npx vitest run` → 6 files / 61 tests / 61 passed
- `cd frontend && node scripts/i18n-audit.mjs` → RESULT: PASS, exit 0, 107 CHECK D advisories

**Read (engine):**
- `tribunal/nestor_pulse_sdk/citations/numbering.py` — full file (`_CLAIM_SOURCE_SQL:147-159`,
  `_assign_numbers:190-261`, `number_citations:264-295`, `number_citations_with_claims:298-313`)
- `tribunal/nestor_pulse_sdk/citations/anchors.py` — full file (`apply_citation_anchors:297-335`,
  `anchor_number_map:159-174`)
- `tribunal/nestor_pulse_sdk/citations/extractor.py` — full file (`_upsert_source:228-355`,
  `persist_tribunal_claims:839-1200`, the `snapshot_text=url` call at `:1095-1104`)
- `tribunal/nestor_pulse_sdk/citations/redirect_resolver.py:150-173` (`is_redirect_url`), `:60-63`
  (env knobs)
- `tribunal/nestor_pulse_sdk/verification/report.py:600-671` (`build_verification_report`)
- `tribunal/nestor_pulse_sdk/runs/schemas.py:430-500` (`VerificationCitation`, `VerificationReport`)
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py:4375-4540` (`_load_citation_context`,
  `_write_final_report`, the D-05 post-pass)
- `tribunal/nestor_pulse_sdk/alembic/versions/0003_citation_schema.py:55-70, 174-175`
- `tribunal/nestor_pulse_sdk/tests/test_citation_numbering.py:55-120, 285-360`
- `tribunal/nestor_pulse_sdk/tests/test_suite_hygiene.py:1-60`
- `tribunal/cloudbuild.test-engine.yaml:80-560` (the 44-file WANTED list, counted)
- `backend/app/api/research_routes.py:863-940` (the verbatim proxy)

**Read (frontend):**
- `frontend/src/lib/api/research.ts` — full file
- `frontend/src/components/intake/VerificationReport.tsx` — full file
- `frontend/src/routes/admin.pulse.runs.$runId.tsx` — full file
- `frontend/src/routes/admin.pulse.intakes.$id.tsx:54-55, 174, 780-845, 1205-1252`
- `frontend/src/components/intake/ResearchRunProgress.tsx:158, 210-225, 574-603, 694, 703, 938`
- `frontend/src/components/research/RunActions.tsx:185-200`
- `frontend/src/components/intake/CitationPanel.tsx:38-50, 118-128`
- `frontend/src/lib/research/verificationGate.ts` — full file
- `frontend/src/routes/intake.$id.tsx:30-52` (the `Outlet` scar)
- `frontend/src/routeTree.gen.ts:44, 210-211, 260-266, 291-301, 665-715`
- `frontend/src/locales/{en,fr,nl}/intake.json:648` (`citation.published`)
- `frontend/package.json`, `frontend/scripts/i18n-audit.mjs:8-13`

**Authority documents:**
- `.planning/phases/22-.../22-CONTEXT.md` (D-22-1 … D-22-5)
- `.planning/phases/22-.../22-UI-SPEC.md` (approved 6/6)
- `./CLAUDE.md`
- `.planning/config.json`

### Secondary (MEDIUM confidence)
- None. No claim in this document rests on a secondary source.

### Tertiary (LOW confidence)
- None. Where a claim could not be verified it is in the **Assumptions Log**, not stated as fact.

⚠ **Excluded from all evidence:** `.claude/worktrees/agent-af281d695d9b34c35/` — a stale worktree
carrying an older copy of the engine. Every grep in this research filtered it out. A planner
grepping the repo will hit it; its line numbers do not match the live tree.

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|------|-------|--------|
| Route mechanics (RQ3) | **HIGH** | The actual generator was executed; the answer is quoted output, not inference |
| Renumbering hazard (RQ1c) | **HIGH** | Every `[n]` render path on both surfaces was read end to end |
| Dedupe placement (RQ1a) | **HIGH** | Follows from CONTEXT.md's own shared-function constraint plus the verified absence of `resolved_url` on the wire |
| Root-cause correction (RQ2a) | **HIGH** | `snapshot_text=url` read directly at `extractor.py:1100`; the "not extract_and_persist_citations" note read at `pipeline.py:13` |
| Dedupe **yield** (RQ2a) | **MEDIUM** | The mechanism is certain; the magnitude is inferred, not measured — Assumption A3 |
| Write-time requirements (RQ2b/c) | **HIGH** | Index read from migration 0003; the two-unique-index trap follows directly from `ON CONFLICT` semantics |
| Dead-code inventory (RQ4) | **HIGH** | Every call site and importer enumerated by grep |
| Test surface (RQ5) | **HIGH** | All three baselines executed; the WANTED list counted, not estimated |
| Normalization detail (RQ1b) | **MEDIUM** | The steps are standard practice; the exact tracking list and the scheme decision are judgment — A1, A2 |
| Deploy target (RQ1a) | **LOW** | Service name not verified — A4 |

**Research date:** 2026-08-11
**Valid until:** 2026-09-10 (30 days — the codebase is the source of truth and moves slowly; but
re-verify the three baselines in §5a if any other phase lands first)

---

*Phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat*
*Authority: `22-CONTEXT.md` (D-22-1 … D-22-5), then `22-UI-SPEC.md`. Where this research and
CONTEXT.md disagree on a DECISION, CONTEXT.md wins. Where they disagree on a FACT ABOUT THE CODE —
as they do on D-22-4's root cause (§2a) — the code wins, and the correction is flagged for the
operator rather than applied silently.*
