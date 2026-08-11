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

**⚠ AMENDED 2026-08-11 — the root cause recorded here on 2026-08-10 was WRONG for the path that
actually runs. Corrected by `22-RESEARCH.md`, which established it by executing the code.**

**What was originally written (and is only half true):** `_assign_numbers`
(`citations/numbering.py:225`) already dedupes correctly — it reuses a number when it sees a source
again. That part stands. The duplication is created one layer up at source INSERT
(`citations/extractor.py:289-322`), where the conflict key is `(tenant_id, content_hash)`. The
original inference was that `content_hash` is a hash of the **snapshot text**, so two providers
extracting slightly different text from the same page yield two rows.

**What is actually true:** the live Tribunal path calls `_upsert_source(snapshot_text=url)` at
`extractor.py:1100` — it passes the URL *as* the snapshot argument. **So the conflict key is already
`sha256(url)`.** The generic "different snapshot text" story does not describe this path at all, and
neither does the "no snapshot → dedupe skipped" branch.

**The real defect is raw-vs-normalized URL**, and the dominant duplicate generator is almost
certainly **Gemini's `vertexaisearch` grounding redirects**, where every citation of the same page
arrives as a different opaque token.

**This materially changes what the fix can achieve.** Stripping `www.`, trailing slashes and
tracking params collapses **none** of the redirect-token duplicates. Only `resolved_url` can — and
`resolved_url` exists only where the best-effort HEAD resolution succeeded, so there is a real
ceiling on yield that is not knowable before a run. **Do NOT write an acceptance criterion asserting
a specific reduction in citation count.** `resolved_url` is therefore load-bearing, not a
refinement: it must be preferred as the identity key wherever present.

**Scheme is excluded from the identity key** (orchestrator decision, 2026-08-11, reversible):
`http://` and `https://` of the same page are one source. This widens D-22-4's original wording and
is recorded here rather than made silently.

Same family as V-01's exact-string merge key — an identity key that is too literal.

**Operator ruling 2026-08-11: BOTH layers, read-time first.**
- **This phase:** group by normalized URL when building the citation list, so one URL renders as one
  number. Reversible, no migration, and it fixes the report the operator is looking at now.
- **Next:** change the INSERT conflict key to a normalized URL so new runs stop creating duplicates.
  Sequenced deliberately — the write-side change touches ingest and earns its own validation.

**⚠ The write-side fix does NOT fit Phase 22 — research recommends Phase 23, and the reason is a
money-loss risk, not tidiness.** It needs Alembic migration 0019, and critically the existing
`idx_source_tenant_content_hash` UNIQUE index **must be dropped in the same migration**. If it is
not, two sources with the same text but different URLs raise an unhandled `IntegrityError` **inside
the persist transaction of a ~$45 run**. Build the shared `normalize_source_url` in this phase;
land the INSERT change in its own.

Normalization must prefer `resolved_url` where present, then drop the scheme and strip `www.`, a
trailing slash, and tracking params. **Normalization has to be one function used by both layers**,
or read and write will disagree about identity — which is the defect being fixed, reintroduced one
level down. Research names the home: a shared `normalize_source_url` in `citations/dedupe.py`, built
now even though the write side lands later.

**⚠ NEVER RENUMBER — added 2026-08-11 from `22-RESEARCH.md`, and this is the highest-risk rule in
the phase.** The verification report PAGE carries zero pre-baked `[n]`; every marker renders from
`citation.n` at paint time. The **deliverable markdown is the opposite** — `apply_citation_anchors`
(`pipeline.py:4533`) bakes `[n]` at synthesis and freezes it. So dedupe cannot desynchronise the
page from itself, but it CAN desynchronise the page from the frozen deliverable — and only if it
renumbers.

Therefore: **dedupe AFTER numbering, keep each survivor's original `n`, never reassign.** The
rendered list goes sparse (1, 2, 4, 7, …) and that sparseness is the correct cost, not a defect to
tidy away. An additive `also_claim_ids` alias is required too — without it, a verdict row whose only
source was absorbed silently loses its marker.

**Where the dedupe may NOT live** (both established by running the tests):
- **Not the frontend** — a TypeScript function cannot be shared with the Python INSERT, and D-22-4
  requires one shared normalization.
- **Not inside `number_citations`** — `test_citation_numbering.py` pins CONTIGUOUS `1..N` and an
  exact 10-key entry shape, so dropping entries or adding `resolved_url` there goes red.
- **The seam is `verification/report.py:661`.**

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

**⚠ DO NOT DELETE `ResearchRunProgress.tsx` — remove the ELEMENT, keep the FILE.**
`admin.pulse.runs.$runId.tsx:11` imports `useActiveResearchRun` from that module. Deleting the file
breaks the very run page this phase is building around. Research enumerated the rest of the dead
code (imports, state, queries, subscriptions, locale keys); a partial deletion that leaves orphaned
state is the failure mode to avoid. The UI checker separately confirmed the removal strands no
capability: the intake page's retrigger/resume/stop handlers have an equivalent on the run page via
`RunActions` (`admin.pulse.runs.$runId.tsx:299`).

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
