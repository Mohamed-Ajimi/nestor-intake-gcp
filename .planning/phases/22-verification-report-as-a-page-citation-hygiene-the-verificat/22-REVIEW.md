---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
reviewed: 2026-08-12T12:55:00Z
depth: standard
diff_base: 9afdf2d2c0042747b59ee8d7202f41b0ed731137
files_reviewed: 17
files_reviewed_list:
  - frontend/src/components/intake/CitationPanel.tsx
  - frontend/src/components/intake/ResearchRunProgress.tsx
  - frontend/src/components/intake/VerificationReport.tsx
  - frontend/src/lib/api/research.ts
  - frontend/src/lib/research/citationIndex.ts
  - frontend/src/lib/research/citationIndex.test.ts
  - frontend/src/locales/en/intake.json
  - frontend/src/locales/fr/intake.json
  - frontend/src/locales/nl/intake.json
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
  - frontend/src/routes/admin.pulse.runs.$runId.index.tsx
  - frontend/src/routes/admin.pulse.runs.$runId.verification.tsx
  - tribunal/cloudbuild.test-engine.yaml
  - tribunal/nestor_pulse_sdk/citations/dedupe.py
  - tribunal/nestor_pulse_sdk/runs/schemas.py
  - tribunal/nestor_pulse_sdk/tests/test_citation_dedupe.py
findings:
  critical: 1
  warning: 8
  info: 6
  total: 15
status: issues_found
---

# Phase 22: Code Review Report

**Reviewed:** 2026-08-12T12:55:00Z
**Depth:** standard (with cross-language seam tracing on the four seams named in the brief)
**Files Reviewed:** 17
**Status:** issues_found

## Summary

I traced all four seams the brief named and ran what could be run.

**What holds.** The `also_claim_ids` producer→consumer contract is sound end to end: the field name
and casing are identical on all three sides (`dedupe.py:292` → `VerificationCitation.also_claim_ids`
at `runs/schemas.py:477` → `Citation.also_claim_ids` at `research.ts:200`), the tribunal endpoint
declares `response_model=VerificationReport` so the declared field survives `extra="ignore"`, and the
intake proxy at `backend/app/api/research_routes.py:876` is annotated `-> dict` with **no**
`response_model`, so the field rides through the second hop verbatim. The join keys agree: both
`first_claim_id` (`numbering.py:254`, `cid = str(_row_get(r,"claim_id"))`) and `claim_id`
(`report.py:83`, `str(row.claim_id)`) are `str(uuid.UUID)`, and `_source_resolution` keys its map with
`str(sid)` against `collapse_citations_by_url`'s `lookup.get(str(source_id), ...)` — no
normalised-vs-unnormalised comparison anywhere on that path. The consumer tolerates absent / null /
empty / non-array / non-string-member shapes.

Measured, not assumed:
- `npx tsc --noEmit` — **clean**, 0 errors.
- `npx vitest run src/lib/research/citationIndex.test.ts` — **16 passed**.
- `pytest nestor_pulse_sdk/tests/test_citation_dedupe.py` — **34 passed** (local venv, python 3.11.9).
- `node scripts/i18n-audit.mjs` — **PASS, A/B/C clean**; none of the 107 CHECK D advisories touch a
  file in this phase.
- I did not trust the audit's green. I extracted all 142 literal `t("…")` keys from the five changed
  frontend source files and resolved each against `en`/`nl`/`fr` directly, **including every
  interpolated call**: all 142 resolve in all three locales. No raw key can render.
- `cloudbuild.test-engine.yaml`: I counted the `WANTED` list by hand — **45 paths**, matching
  `EXPECTED_FILES=45`. The registration is correct.
- Route split verified against the generated tree: `routeTree.gen.ts:726-736` registers
  `/admin/pulse/runs/$runId/` with `path: '/runs/$runId'` and `/admin/pulse/runs/$runId/verification`,
  and `fileRoutesByTo` carries `'/admin/pulse/runs/$runId'` — so the unsuffixed URL still resolves and
  all four existing `Link to="/admin/pulse/runs/$runId"` call sites typecheck. No stale route
  references in code (only in comments, IN-01).
- CRLF: I compared CR-line counts at `9afdf2d` against HEAD for every changed file. Every one was
  **already** CRLF at the base. The ~4,488 `prettier/prettier` errors are repo-wide and pre-existing.
  Filtering them out leaves **3** non-prettier lint messages across all reviewed files, all
  pre-existing and unrelated to this phase.

**The one blocker is in seam 4, and it is the coercion that was added deliberately.** `report.funnel`
is not a map of counts. It is `run.verification_summary` verbatim, and the pipeline writes a boolean
and a list of sentences into it. The new funnel bar coerces every value with `Number()` and therefore
publishes fabricated figures — most damagingly `degradation_reasons: 0` on a run that has
degradation reasons. The wire type `Record<string, number>` is the type lie that made that code
look correct.

Everything else is a WARNING: two over-merge holes in `normalize_source_url` (the failure class that
module says is worse than the one it fixes), a corroboration badge that the dedupe silently
invalidated, and a large newly-dead component.

## Critical Issues

### CR-01: The gate funnel prints fabricated numbers, and prints `0` for a non-empty degradation list

**File:** `frontend/src/components/intake/VerificationReport.tsx:371-373` (the coercion) and `:578-596`
(the bars). Type: `frontend/src/lib/api/research.ts:106`. Producers:
`tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py:1037`,
`tribunal/nestor_pulse_sdk/runs/worker.py:393-395`.

**Issue:** `report.funnel` is `run.verification_summary` passed through unchanged
(`verification/report.py:570` → `dict(funnel)`; `funnel=getattr(run,"verification_summary",None)` at
`:742`). That dict is **not** all counts. Verified in the engine source:

- `pipeline.py:1037` — `funnel["verification_degraded"] = unchecked > 0` → a **bool**.
- `_build_funnel`'s `degradation_reasons` parameter → `funnel["degradation_reasons"]` is a
  **list[str]** of the operator-facing degradation sentences.
- `worker.py:393-395` — on a parked run, `_psummary["park"] = _park` adds a **dict** as a sibling key
  on the same flat summary.

The new code coerces each value once and never filters:

```ts
const funnelEntries: Array<[string, number]> = Object.entries(report?.funnel ?? {}).map(
  ([stage, count]) => [stage, Number.isFinite(Number(count)) ? Number(count) : 0],
);
```

So the operator's funnel renders these rows beside the real gate counts:

| funnel key | actual value | rendered |
|---|---|---|
| `degradation_reasons` | `["Research stream lost…", "Fact-list fallback…", …]` | `0` (`Number(["a","b"])` is `NaN` → 0) |
| `degradation_reasons` | `[]` | `0` (`Number([])` **is** `0`) |
| `verification_degraded` | `true` | `1` (with a bar) |
| `verification_degraded` | `false` | `0` |
| `park` | `{seq, stage, reason, signature}` | `0` |

Three separate defects in one block:

1. **`degradation_reasons: 0` is a false statement about the run's most important honesty field.**
   Both the empty and the populated case print `0`, so the two are indistinguishable, and the
   populated case actively asserts there were none. On a `completed_degraded` run this is the exact
   number the operator would look for.
2. **`verification_degraded: 1` is a fabricated measurement.** In a funnel whose other rows are claim
   counts, "1" reads as *one claim*. This is what the file's own header forbids: *"⛔ NO DERIVED
   FIGURES… this project's bar is 'facts and correct calculations only'."* The coercion added for the
   bar (`T-22-20`, "so the bar geometry can never be fed a non-number") is what manufactures it —
   filtering non-numbers out of the funnel would have satisfied the same requirement without
   inventing a value.
3. **It is a regression, not merely a pre-existing gap.** At `9afdf2d` the funnel rendered
   `t("verification.funnelStage", {stage, count})` as text, so i18next interpolated the array and the
   operator saw the reasons joined by commas. This phase replaced a readable value with `0`.

The root cause is the wire type: `funnel: Record<string, number> | null` (`research.ts:106`) declares
a shape the engine does not send, so the mapping code above typechecks and reads as correct.

**Fix:** drop non-numeric rows instead of coercing them, and stop the type from lying.

```ts
// research.ts — the funnel is `run.verification_summary` verbatim and carries a bool
// (`verification_degraded`), a list (`degradation_reasons`) and, on a parked run, a dict (`park`).
funnel: Record<string, unknown> | null;
```

```ts
// VerificationReport.tsx — a funnel row is a bar only if its value IS a count. A non-number is not
// a stage with a value of zero: it is not a stage at all, and rendering it as one publishes a figure
// the report never measured.
const funnelEntries: Array<[string, number]> = Object.entries(report?.funnel ?? {}).flatMap(
  ([stage, value]) =>
    typeof value === "number" && Number.isFinite(value) && value >= 0
      ? [[stage, value] as [string, number]]
      : [],
);
```

If the intention is that `verification_degraded` and `degradation_reasons` stay visible, they belong
in prose (see WR-04), never as a bar.

## Warnings

### WR-01: `normalize_source_url` can return a host-free key that collides across different hosts

**File:** `tribunal/nestor_pulse_sdk/citations/dedupe.py:184-219`

**Issue:** Steps 5–9 assemble the key from `host + path` with no requirement that a host was found.
`urlparse` accepts `.` in a scheme, so a schemeless authority is parsed as a scheme and the host
vanishes from the key. Measured against the real function:

```
'foo.com:8080/a'  -> '8080/a'
'bar.com:8080/a'  -> '8080/a'      # collision: True
'/article/1'      -> '/article/1'
```

Two unrelated publishers collapse into one `[n]`. That is precisely the outcome the module's own
"Do NOT" block calls *"the opposite defect from the one this module fixes and strictly worse than
it"*, and `test_two_unparseable_urls_are_never_merged_with_each_other` exists to prevent the same
class on a different input. A relative key like `/article/1` is worse in aggregate: `/index`, `/en/`
or `/` are plausible on many hosts at once.

This is not reachable today, and the reason it is not is the problem: two validators in *other*
modules happen to require an absolute `http(s)` URL — `facts.py:689-693` (`scheme not in
("http","https") → skip`) and `redirect_resolver.py:171,195` for the `Location` header. `dedupe.py`
references neither, its docstring promises only totality, and the module is explicitly designated as
the function the **INSERT conflict key** will call next (DEF-22-06), where a collision merges two real
`source` rows rather than two display entries.

**Fix:** require a host, in the function that owns the definition.

```python
        # 5. Host. A key with NO host cannot identify a source: `foo.com:8080/a` and
        #    `bar.com:8080/a` both parse to scheme='<host>', netloc='' and would collide on
        #    '8080/a'. Two different publishers merging into one [n] is the over-merge this
        #    module's "Do NOT" block calls strictly worse than the defect it fixes, so an input
        #    with no derivable authority has NO identity key.
        host = (parsed.netloc or "").lower()
        if not host:
            return None
```

Add a named test in the T-22-03 group, e.g.
`test_two_hosts_with_no_scheme_do_not_collide_on_a_host_free_key`.

### WR-02: `urlparse` silently drops trailing path parameters — an undocumented over-merge

**File:** `tribunal/nestor_pulse_sdk/citations/dedupe.py:184, 206`

**Issue:** `urlparse` (unlike `urlsplit`) splits `;params` off the **last** path segment into
`parsed.params`, which this code never reads. Measured:

```
'https://example.com/a;jsessionid=ABC' -> 'example.com/a'
'https://example.com/a'                -> 'example.com/a'   # merged
```

The docstring enumerates its transformations exhaustively (steps 1–9) and the "Do NOT" block
enumerates the over-merges it refuses. Dropping path parameters appears in neither, so it is an
unintended behaviour in a function whose whole value is that its rules are written down and shared
with the write path. Session-id stripping happens to be desirable; matrix parameters that select a
document are not, and no test pins either direction.

**Fix:** use `urlsplit`, which has no `params` field, so the path is taken whole:

```python
from urllib.parse import parse_qsl, urlencode, urlsplit
...
        parsed = urlsplit(candidate)
```

`urlsplit` exposes the same `.scheme/.netloc/.path/.query/.fragment` attributes this function reads,
so nothing else changes. If the current merging is wanted instead, make it step 8b in the docstring
and pin it with a named test — but decide it, do not inherit it from a stdlib parser choice.

### WR-03: the `single_source` badge is now wrong in the direction that understates risk

**File:** `frontend/src/components/intake/CitationPanel.tsx:249-253`; producer
`tribunal/nestor_pulse_sdk/citations/numbering.py:253`

**Issue:** `single_source` is computed **before** the dedupe as
`len(sources_per_claim.get(cid, ())) == 1`, counting distinct `source_id` **rows**. After
`collapse_citations_by_url`, a claim whose three `source` rows are three copies of one page renders
exactly **one** `[n]` — and that survivor carries `single_source: false`, so the amber
`citation.singleSource` warning is **absent**. The operator sees one source and is told, by omission,
that the claim does not rest on a lone source.

The recorded deferral covers *not adding* a corroboration figure, and `VerificationReport.tsx:527`
says the strip carries *"NO corroboration claim"*. But `CitationPanel` renders one, it is now
inconsistent with the deduped display, and the error direction is the unsafe one. This is the
read/write identity split reaching a user-facing trust signal, which is more than the display-only
framing accounts for.

**Fix:** either recompute the flag over the collapsed set, or caveat it. Recomputing is cheap and
local — `collapse_citations_by_url` already knows which entries it absorbed:

```python
        # A claim whose only other "sources" were duplicates of this page DOES rest on a lone
        # source. Leaving the pre-dedupe flag on the survivor tells the operator the opposite.
        if absorbed and absorbed == canonical.get("first_claim_id"):
            canonical["single_source"] = True
```

If recomputation belongs with the write-side fix instead, add it to DEF-22-06 explicitly and add one
sentence to the panel saying the badge counts source *rows*, not distinct URLs.

### WR-04: the engine's loudest honesty fields never reach the DOM

**File:** `frontend/src/components/intake/VerificationReport.tsx:520-836` (nothing reads them);
producers `tribunal/nestor_pulse_sdk/verification/report.py:497-500, 574-575, 601`

**Issue:** Five fields are shaped by the engine, declared explicitly on the pydantic model
specifically so `extra="ignore"` cannot drop them (`runs/schemas.py:499-528` — *"a caveat that
silently vanishes at the API boundary reads to the operator as 'there is no caveat'"*), delivered to
the browser, and rendered nowhere:

- `verification_degraded_text` — the G-10 sentence ending *"do not read it as green"*
- `degradation_reasons` — D-12
- `accounting` — the G-08 three buckets, including `should_have_been_checked`, described in
  `report.py:104-106` as *"the phase's most important number"*
- `unverified_note` / `unverified_from_accounting` — the CR-02 caveat
- `unresolved_anchors_text` — D-06

This is pre-existing: `9afdf2d` did not render them either. I am reporting it because this phase
built a six-tile strip whose stated purpose is *"the trust question lifted above the fold"* and left
out the one sentence that answers it. As shipped, a `completed_degraded` run with 800 unchecked
claims renders a strip of neutral figures with nothing marking it as degraded, and — per CR-01 — its
`degradation_reasons` row prints `0`.

**Fix:** one prose block above the strip, gated the way `_degradation` gates itself (a healthy run
says nothing):

```tsx
{report.verification_degraded && report.verification_degraded_text && (
  <div className="mb-8 border-l-4 bg-amber-50 px-6 py-5" style={{ borderLeftColor: "#DC2626" }}>
    <p className="font-sans text-[13px] leading-relaxed text-amber-900">
      {report.verification_degraded_text}
    </p>
    {report.degradation_reasons?.length > 0 && (
      <ul className="mt-2 list-disc pl-5 font-sans text-[12px] text-amber-800">
        {report.degradation_reasons.map((r, i) => <li key={i}>{r}</li>)}
      </ul>
    )}
  </div>
)}
```

These are engine-authored sentences already clamped to 200 chars × 8 entries by
`_degradation_reasons`, and they are plain text children — no `MdText`, per the T-22-06 rule. This
adds no derived figure, so it does not touch the D-22-2 ruling. `accounting` needs its own decision;
flagging rather than prescribing.

### WR-05: `ResearchRunProgress` is now unreachable — 948 lines with zero render sites

**File:** `frontend/src/components/intake/ResearchRunProgress.tsx:616-948`

**Issue:** `grep -rn "<ResearchRunProgress" frontend/src` returns **no** render site. The two
remaining importers take only the helpers: `admin.pulse.intakes.$id.tsx:57` imports
`IntakeOpenRunLink`, `admin.pulse.runs.$runId.index.tsx:11` imports `useActiveResearchRun`. The
exported component and everything reachable only from it — `RawOutputControls` (`:422-460`), the four
card branches, the Stop `AlertDialog`, the `onRetry`/`onResume`/`onCancel` props (`:628-630`) which
now have **no supplier anywhere** — are dead.

I verified this is not a capability loss: `components/research/RunActions.tsx` covers
`getBundleUrl` (`:120`), `reVerifyChain` (`:134`), `resumeResearch` (`:151`), `cancelResearch`
(`:166`) and `triggerResearch` (`:181`) on the run page. So the raw-output bundle download and chain
re-verify survive — but they now exist **twice**, and only one copy can be reached. Two
implementations of a paid-run affordance where the unreachable one still compiles is how the two
drift, and the reviewer of the next change has no signal which is live.

**Fix:** delete the `ResearchRunProgress` component and everything reachable only from it, and move
`useActiveResearchRun` + `OpenRunLink` + `IntakeOpenRunLink` into their own module (e.g.
`lib/research/useActiveResearchRun.ts` and `components/research/OpenRunLink.tsx`) — which also
retires the stale `components/intake/` placement for a run-page helper and clears IN-02's
`react-refresh/only-export-components` class of warning. If deletion is out of scope for this phase,
record it as a named deferral; do not leave it as an unmarked second implementation.

### WR-06: `buildCitationIndex` cannot answer the question its docstring says it answers

**File:** `frontend/src/lib/research/citationIndex.ts:1-2, 12` and `:60`

**Issue:** The module opens *"the one answer to 'which `[n]` markers belong to this verdict row'"* and
*"so a verdict row can ask for exactly its own `[n]` markers"*. It indexes only
`first_claim_id` + `also_claim_ids`. `first_claim_id` is, by construction
(`numbering.py:222-258`), the claim that **first introduced** that source in row order — so a verdict
row whose claim cites a source some earlier claim already numbered resolves to nothing and renders no
marker. `numbering.py:200-206` states this outright:

> *"most claims cite a source some earlier claim already numbered. A map built only from
> `first_claim_id` would leave the majority of the model's anchors unresolvable."*

The alias half closes the dedupe-shaped hole (correctly, and its tests prove it), but the larger
pre-existing hole is untouched, and a reader of this module will now believe otherwise. The remedy
already exists engine-side: `number_citations_with_claims()` returns `claim_to_n`, *"EVERY claim
present in `rows`"*, built for exactly this.

Not introduced by this phase — the loop it replaced had the same coverage. Reported because the
module is new, its stated contract overstates what it does, and the honest scope is one comment edit
away.

**Fix:** either narrow the docstring —

```
 * Index a run's citation list by the claim that INTRODUCED each source. This is NOT "every
 * marker for this verdict row": a claim citing a source an earlier claim already numbered is
 * absent by construction (`numbering.py:200-206`), because the wire carries `first_claim_id`
 * only. Closing that gap means shipping `number_citations_with_claims`' `claim_to_n` map to the
 * browser, which is a separate change on the engine side.
```

— or close the gap by adding `claim_to_n` to the `VerificationReport` payload and keying off it.
Either is fine; the current pairing of a broad claim with a narrow implementation is not.

### WR-07: the new cost tile renders a raw NUMERIC string, unlike every other cost surface

**File:** `frontend/src/components/intake/VerificationReport.tsx:554-559`

**Issue:** `costTotal` is `report.true_cost.cost_usd_total`, a Postgres `NUMERIC` serialised as a
string, and it is passed straight into `StatTile value=`. So the tile renders e.g.
`44.98123456` at 24px with no currency mark. Every other cost surface in the product goes through
`lib/research/runClock.ts:37-42`:

```ts
export function fmtCost(cost: string | null, fallback: string): string {
  if (cost == null || cost === "") return fallback;
  const n = Number(cost);
  if (Number.isNaN(n)) return `$${cost}`;
  return `$${n.toFixed(2)}`;
}
```

`admin.pulse.runs.$runId.index.tsx:260` uses it for the same underlying value, so the run page and its
own verification page will print the same run's cost in two different formats. `fmtCost` is not a
derived figure — it is a two-decimal render of the measured total with the unit attached, and its
`Number.isNaN` arm already preserves an unparseable value verbatim.

**Fix:** `value={fmtCost(costTotal, "—")}` and drop the `?? "—"`. The prose cost section
(`:816-835`) has the same shape and is pre-existing; worth aligning in the same edit.

### WR-08: this phase orphaned two more locale keys than DEF-22-04 records

**File:** `frontend/src/locales/{en,nl,fr}/intake.json` — `verification.close`, `verification.loading`

**Issue:** Both were **live** at `9afdf2d` (`git show 9afdf2d:…/VerificationReport.tsx` → `:259`
`t("verification.close")`, `:267` `t("verification.loading")`). This phase removed the component's
close button (D-22-1 moved chrome to the page) and replaced its loading text with `<Skeleton>`, so
both keys now have zero source references — confirmed by grep across all `.ts`/`.tsx`.

DEF-22-04 records exactly two orphans (`intakeDetail.toast.researchResumed`,
`researchResumeFailed`), and `verification.hideAction` is a documented deliberate keep
(`admin.pulse.runs.$runId.index.tsx:318`). These two are neither. The audit cannot catch them —
CHECK A tests parity, not usage, and never flags orphans — so an incomplete deferral record is the
only thing standing between them and permanence.

**Fix:** add `verification.close` and `verification.loading` to DEF-22-04's list, or delete both from
all three locale files in the same commit (deleting from one goes red on CHECK A).

## Info

### IN-01: stale filename references after the route rename

**File:** `frontend/src/routes/admin.pulse.runs.$runId.index.tsx:17`,
`frontend/src/routes/admin.pulse.intakes.$id.tsx:806`

**Issue:** The run page's own header comment still names the file `admin.pulse.runs.$runId.tsx`, and
the intake page's D-22-5 note points readers at `routes/admin.pulse.runs.$runId.tsx` for `RunActions`.
That filename now deliberately **does not exist** — and the verification route's header (`:15-25`)
explains at length that recreating it would silently break the sibling page. A reader following the
stale pointer creates exactly the file they were warned about.

**Fix:** `…$runId.index.tsx` in both.

### IN-02: `renderCitationMarker`'s comment claims three call sites; there is one

**File:** `frontend/src/components/intake/CitationPanel.tsx:156-158`

**Issue:** *"so the three existing call sites in `VerificationReport.tsx` compile without an edit"* —
there is one (`VerificationReport.tsx:156`, inside `VerdictItemRow`); the citation list now uses
`CitationMarker` directly (`:797`). Related: `CitationPanel.tsx:160` is the file's only
non-prettier lint message (`react-refresh/only-export-components`, warn), which WR-05's module split
would clear.

**Fix:** update the count, or drop it — the sentence's point is the unchanged signature, which needs
no census.

### IN-03: `{{count}}` keys have no plural form, so a one-source run reads "1 sources"

**File:** `frontend/src/locales/{en,nl,fr}/intake.json` — `verification.citationsCount`

**Issue:** `"{{count}} sources"` / `"{{count}} bronnen"` / `"{{count}} sources"`. i18next treats
`count` as the plural selector, finds no `_one`/`_other` variant, and falls back to the base key — so
it renders, but ungrammatically at 1. The section is gated on `citations.length > 0`, so 1 is
reachable. Repo-wide convention (`research.runPage.metaEvents` predates this phase does the same), so
this is consistency-preserving rather than new.

**Fix:** if the convention is worth changing, `citationsCount_one` / `citationsCount_other` in all
three files at once. Otherwise leave it and note the convention.

### IN-04: `dedupe.py`'s "no ORM, importable without dragging a session in" is not true as packaged

**File:** `tribunal/nestor_pulse_sdk/citations/dedupe.py:19-20`; cause
`tribunal/nestor_pulse_sdk/citations/__init__.py:13-14`

**Issue:** The module body genuinely is stdlib-only, but `from nestor_pulse_sdk.citations.dedupe
import …` executes the package `__init__`, which eagerly imports `extractor` (→ `sqlalchemy`) and
`renderer` (→ `fastapi`). I hit this directly: the test module failed to collect twice in a bare venv
until both were installed. The gate is unaffected because `requirements.txt` pins both, but the
stated property — *"It is importable from either side without dragging a session in"* — does not
hold, and it is a load-bearing part of the D-22-4 argument for a shared function.

**Fix:** either soften the claim to "contains no DB code" or make `citations/__init__.py` lazy. No
behavioural impact either way.

### IN-05: an empty padded block renders when the intake has no locatable run

**File:** `frontend/src/routes/admin.pulse.intakes.$id.tsx:1186-1189`

**Issue:** The wrapper `<div className="px-6 pb-6">` renders whenever
`RESEARCH_SURFACE_STATUSES.has(intake.status)`, but `IntakeOpenRunLink` returns `null` until
`run?.id` arrives (and permanently if the stream falls back). That leaves a 24px empty block —
visible on every `in_research` page load, and permanently on an intake whose run row never resolves.

**Fix:** move the padding inside the wrapper component so the whole node disappears with the link, or
return the classed wrapper from `IntakeOpenRunLink` itself.

### IN-06: a negative funnel value would render a full-width bar

**File:** `frontend/src/components/intake/VerificationReport.tsx:588-591`

**Issue:** `width: ${(count / funnelMax) * 100}%` with a negative `count` yields an invalid CSS
width, which the browser ignores; the inner `<div className="h-2 bg-ink">` then takes its parent's
full width and reads as 100%. `_build_funnel` clamps its own arithmetic
(`min(unchecked_selected, selected)`), so this needs a malformed or hand-built funnel — but the whole
point of the T-22-20 coercion was that the bar geometry can never be fed a bad value, and the range
half of that was not done.

**Fix:** covered by CR-01's `value >= 0` filter; noted separately so it is not lost if CR-01 is fixed
some other way.

---

_Reviewed: 2026-08-12T12:55:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
