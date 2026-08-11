# Phase 22: Verification Report as a Page + Citation Hygiene — Context

**Gathered:** 2026-08-11
**Status:** Ready for planning
**Source:** Operator UAT walkthrough of Phase 21 (verbatim in `21-UAT.md`) + two clarifying rulings

<domain>
## Phase Boundary

Phase 21 made the verification report *reachable* from the run page, behind an inline toggle. The
operator walked it, judged the content good, and rejected the container: a dropdown is the wrong
home for a document this long. This phase moves the report onto its own route, restyles it as a
dashboard, makes citations hoverable with the list collapsed by default, collapses duplicate
citations to one number per source, and removes the now-redundant activity feed from the intake
detail page.

**In scope:** the verification report's route, layout and styling; citation display (hover, collapse,
dedupe); the read-time citation identity fix; the write-time source-identity fix; removal of the
embedded `ResearchRunProgress` from the intake detail page.

**Out of scope:** the run feed itself (Phase 21, shipped); the research engine; anything that
triggers or changes a run. DEF-21-03 (empty stage summaries) and DEF-21-04 (`workshop` has no
divider) are known, ruled, and remain deferred — do not absorb them into this phase.
</domain>

<decisions>
## Implementation Decisions

### D-22-1 — The report gets its own page, not a dropdown (LOCKED)

**Operator, verbatim:** *"verification report should open its own page not a dropdown (too long)"*

The report moves off `/admin/pulse/runs/:runId` onto its own route. What remains on the run page is
navigation to it, not the report body. The Phase 21 availability rule
(`canHaveVerificationReport(status)`, `frontend/src/lib/research/verificationGate.ts`) still governs
whether that navigation is offered — it is tested and must be reused, not reimplemented.

**Consequence for Phase 21's DEF-21-02:** the six deferred UAT steps assumed an inline toggle with
the feed surviving beneath it. **B2, B3 and B4 become obsolete as written** once the report is its
own page — there is no longer a feed for it to sit beside. B1, B5 and B6 survive in spirit (the
page loads; offered on failed/cancelled; absent on queued/running). This must be reconciled
explicitly in Phase 22's own UAT rather than left to rot as stale criteria.

### D-22-2 — Restyle as a dashboard (LOCKED, design open)

**Operator, verbatim:** *"verification report contains very good information , so style it better ,
like a dashboard"*

The *content* is endorsed — this is a presentation change, not an information change. Do not drop,
summarise away, or reorder sections on the assumption they are noise. The funnel, verdict sections
and cost block all stay. **The visual direction is NOT yet decided** and belongs in a UI-SPEC before
planning.

### D-22-3 — Citations: hover preview, list collapsed by default (LOCKED)

**Operator, verbatim:** *"the citation should show when you hover over them , and the list of
citation should be hidden by default and user can expand and see"*

- Hovering a `[n]` marker shows **title + publication date + quality tier only** (operator ruling
  2026-08-11). Lightweight metadata already present on the citation object, so hover is instant and
  makes **no network call**.
- Clicking still opens the full `CitationPanel` with the stored `snapshot_text` — unchanged
  behaviour, unchanged security posture.
- The full citation **list** is collapsed by default and expandable.

⚠ `publication_date` is a **retrieval-date proxy** (`source.fetched_at`), not a publication date —
`numbering.py`'s own docstring requires it be labelled "retrieved", never "published". A hover card
that says "Published" would violate the operator's "NO ESTIMATES — facts only" bar (C1).

### D-22-4 — Duplicate citations collapse to one number per source (LOCKED, both layers)

**Operator, verbatim:** *"there are alot of duplicate citations is there a reason for that , why not
remove duplicates and have 1 number for it?"*

**Root cause, established from the code before planning:** `_assign_numbers`
(`citations/numbering.py:225`) already dedupes correctly — it reuses a number when it sees a source
again. The duplication is created one layer up at source INSERT
(`citations/extractor.py:289-322`), where the conflict key is `(tenant_id, content_hash)` — a hash
of the **snapshot text**, not the URL. Two consequences:
1. Two providers fetching the same page with even slightly different extracted text produce two
   `source` rows, hence two numbers.
2. When there is no snapshot at all, the code comments *"No snapshot to hash — skip dedupe and
   insert plainly"* — so every citation of a snapshot-less source inserts a fresh row, every time.

Same family as V-01's exact-string merge key.

**Operator ruling 2026-08-11: BOTH layers, read-time first.**
- **This phase:** group by normalized URL when building the citation list, so one URL renders as one
  number. Reversible, no migration, and it fixes the report the operator is looking at now.
- **Next:** change the INSERT conflict key to a normalized URL so new runs stop creating duplicates.
  Sequenced deliberately — the write-side change touches ingest and earns its own validation.

Normalization must prefer `resolved_url` where present, then strip `www.`, a trailing slash, and
tracking params. **Normalization has to be one function used by both layers**, or read and write
will disagree about identity — which is the defect being fixed, reintroduced one level down.

⚠ Read-time dedupe changes DISPLAY only. Cost and corroboration metrics still count the duplicate
rows until the write-side lands. Do not claim otherwise in the UI.

### D-22-5 — Remove the activity feed from the intake detail page (LOCKED)

**Operator, verbatim:** *"activity shouldnt show on the intake page , we already have a open run
button that opens it in a different page and it is exactly the same so no need to have it there"*

Remove the embedded `ResearchRunProgress` from `admin.pulse.intakes.$id.tsx`. The "Open run" link
stays and is the single way in.

⚠ **This REVERSES Phase 21's R2**, which deliberately kept that card (21-CONTEXT, explicitly out of
scope). The operator reversed it with the reversal stated in front of them. Recorded so a later
reader does not read the removal as a Phase 21 regression. Verify nothing else on the intake page
depends on that component before deleting it.

### Claude's Discretion

- Route shape for the report page (a sibling of the run route is the obvious fit).
- Where the citation list's expand/collapse control sits, and its default collapsed height.
- Hover implementation (the repo already has Radix primitives — reuse, do not add a dependency).
- Whether the read-time dedupe lives in the API response builder or the frontend, provided the
  normalization function is shared with the eventual write-side fix.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The report and its citations
- `frontend/src/components/intake/VerificationReport.tsx` — the component being re-homed and restyled
- `frontend/src/components/intake/CitationPanel.tsx` — `renderCitationMarker` + the click panel; carries the superadmin-by-placement security contract
- `frontend/src/lib/api/research.ts` — `Citation` / `CitationSource` types and `getSource`
- `tribunal/nestor_pulse_sdk/citations/numbering.py` — `_assign_numbering` already dedupes by `source_id`; the determinism ORDER BY is a pinned contract, do not touch it
- `tribunal/nestor_pulse_sdk/citations/extractor.py` (lines 289-322) — where duplicate `source` rows are born

### The pages
- `frontend/src/routes/admin.pulse.runs.$runId.tsx` — where the toggle lives today
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` — where the embedded feed is being removed from
- `frontend/src/lib/research/verificationGate.ts` + `.test.ts` — the Phase 21 availability rule; REUSE

### Phase 21 rulings that still bind
- `.planning/phases/21-.../21-UAT.md` — the operator's verbatim walkthrough and DEF-21-02's six steps
- `.planning/phases/21-.../deferred-items.md` — DEF-21-01 (lint stays deferred), DEF-21-03, DEF-21-04
</canonical_refs>

<specifics>
## Specific Ideas

- The operator's complaint about the dropdown was **length**, not discoverability — they found it
  fine. Length is the problem to solve.
- "Very good information" is an endorsement of content. A restyle that hides or truncates sections
  to look tidier would be solving the wrong problem.
</specifics>

<deferred>
## Deferred Ideas

- **The write-side source-identity fix** — ruled in scope as a sequenced follow-up (D-22-4). If it
  does not fit this phase, it is a named next phase, not a dropped idea.
- **Backfilling existing duplicate `source` rows** — not requested; read-time dedupe makes it
  unnecessary for display.
- **DEF-21-01** (lint red tree-wide) — operator ruled it stays deferred and out of Phase 21;
  it stays out of 22 too unless separately raised.
- **DEF-21-03 / DEF-21-04** — known Phase 21 defects, deliberately not carried here.
</deferred>

---

*Phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat*
*Context gathered: 2026-08-11 from the operator's Phase 21 UAT walkthrough + two clarifying rulings*
