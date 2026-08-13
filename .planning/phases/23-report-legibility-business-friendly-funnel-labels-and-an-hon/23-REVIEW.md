---
phase: 23-report-legibility-business-friendly-funnel-labels-and-an-hon
reviewed: 2026-08-13T14:35:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - frontend/src/components/intake/NextStepBanner.tsx
  - frontend/src/components/intake/ResearchRunProgress.tsx
  - frontend/src/components/intake/VerificationReport.tsx
  - frontend/src/lib/research/funnelLabels.ts
  - frontend/src/lib/research/funnelLabels.test.ts
  - frontend/src/lib/research/workPhase.ts
  - frontend/src/lib/research/workPhase.test.ts
  - frontend/src/locales/en/admin.json
  - frontend/src/locales/en/intake.json
  - frontend/src/locales/fr/admin.json
  - frontend/src/locales/fr/intake.json
  - frontend/src/locales/nl/admin.json
  - frontend/src/locales/nl/intake.json
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
findings:
  critical: 2
  warning: 5
  info: 3
  total: 10
status: issues_found
---

# Phase 23: Code Review Report

**Reviewed:** 2026-08-13T14:35:00Z
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 23 is frontend-only and structurally sound. The two load-bearing constraints named in the
brief both hold, and I verified them rather than taking the comments at their word:

- **ONE research SSE connection on the intake page.** `useActiveResearchRun` is called from
  exactly two places in the app — `routes/admin.pulse.intakes.$id.tsx:326` (the intake page) and
  `routes/admin.pulse.runs.$runId.index.tsx:101` (a different page). `IntakeOpenRunLink` no
  longer calls it. The gate is byte-for-byte the same `RESEARCH_SURFACE_STATUSES` test that gates
  the link's render (`admin.pulse.intakes.$id.tsx:325` vs `:1218`); it was neither widened nor
  dropped, and the argument (not the call) carries the condition, so rules-of-hooks holds. The
  link block at `:1218` is not nested under any `editMode`/`reviewMode` guard and there is no
  early return between the hook and it, so stream lifetime is genuinely unchanged.
- **`IntakeOpenRunLink` survives.** Still defined (`ResearchRunProgress.tsx:258`), still renders
  `OpenRunLink`, still rendered by the route (`:1220`).

I also confirmed the F4 mechanism is not inert: the backend stream emits a snapshot at connect
and *then* closes on a terminal status (`backend/app/api/research_routes.py:1186-1189`), so a
finished run really does reach the banner as `completed`/`completed_degraded` rather than leaving
it stuck on `unknown`. `deriveWorkPhasePresentation` is a genuine `switch` with a `default →
"unknown"`, the banner's mapping is exhaustive with a `never` guard, and no absent/unheard-of
input can resolve to `finished` or `stopped`. The CR-01 `typeof count === "number"` filter in
`VerificationReport.tsx:403` is untouched and not loosened. Locale parity is exact: all three
`intake.json` catalogs have 634 keys and all three `admin.json` catalogs have 365, with a
zero-key diff across en/nl/fr. The retired `nextStep.inResearchBody` has no remaining referent.
`tsc --noEmit` is clean, `vitest` passes 46/46 on the two new suites, `i18n-audit.mjs` reports
PASS, and ESLint surfaces only pre-existing warnings on the touched files.

What is wrong is the **content and the presentation of the F1 deliverable**. One funnel label
states the opposite of what its figure counts, in all three languages. And the ⓘ glyph that is
the whole point of the phase is placed inside a fixed-width `truncate` box that clips it away for
the majority of the rows in the default language. Both are user-facing defects in the exact
surface this phase exists to make trustworthy.

## Critical Issues

### CR-01: The `checked_incidentally_both` label says the opposite of what the figure counts — in all three languages

**File:** `frontend/src/locales/en/intake.json:641`, `frontend/src/locales/nl/intake.json:641`,
`frontend/src/locales/fr/intake.json:641` (key `verification.funnelLabel.checked_incidentally_both`)

**Issue:**
The engine's bucket is claims that were dropped for **BOTH** gate reasons and got checked anyway.
This is not inferred — it is the `else` branch of `_count_incidental` after
`NOT_FALSIFIABLE` and `NOT_LOAD_BEARING` have each been taken
(`tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py:911-916`), against a reason vocabulary
of exactly `("NOT_FALSIFIABLE", "NOT_LOAD_BEARING", "BOTH")`
(`tribunal/nestor_pulse_sdk/pipeline/tribunal/gates.py:106`).

The shipped labels say the reverse:

| lang | label | reads as |
|---|---|---|
| en | `"Checked anyway: neither reason"` | neither reason applied |
| nl | `"Toch gecheckt: geen van beide redenen"` | neither of the two reasons |
| fr | `"Vérifiées malgré tout : aucune des deux raisons"` | none of the two reasons |

Each one contradicts **its own tooltip**, three lines further down in the same file — en:
`"Of the statements checked anyway, those originally set aside for both reasons."` So the row
label and the row tooltip assert opposite facts about the same number, and the label is the one
always on screen.

The sibling key proves the intended construction was available and was simply lost here:
`funnelLabel.both` is `"Set aside: neither checkable nor load-bearing"` — correct, because
"neither X nor Y" *is* both drop reasons. Dropping the nouns turned "neither checkable nor
load-bearing" into "neither reason", which inverts the meaning.

This is worse than the raw `checked_incidentally_both` key that shipped before Phase 23: the raw
key was opaque, this is confidently wrong. On a report whose stated bar is "facts and correct
calculations only" (`VerificationReport.tsx:56-57`), a label that misstates its own figure is the
defect class this phase exists to remove.

**Fix:** restore the noun pair, mirroring `funnelLabel.both` in each language.

```json
// en/intake.json
"checked_incidentally_both": "Checked anyway: neither checkable nor load-bearing",

// nl/intake.json
"checked_incidentally_both": "Toch gecheckt: niet controleerbaar en niet doorslaggevend",

// fr/intake.json
"checked_incidentally_both": "Vérifiées malgré tout : ni vérifiables ni déterminantes",
```

### CR-02: The ⓘ tooltip is inside a fixed-width `truncate` box and is clipped off for most rows — in the default language, most of them

**File:** `frontend/src/components/intake/VerificationReport.tsx:651-654`

**Issue:**
The label and the tooltip glyph share one span:

```tsx
<span className="w-44 shrink-0 truncate font-mono text-[11px] text-ink/70">
  {label}
  {tip ? <InfoTip text={tip} /> : null}
</span>
```

`truncate` is `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`, and `w-44` is a hard
176px with `shrink-0`. The ⓘ is the **last inline child**, so for any label wider than the column
the glyph is clipped along with the tail of the label. At `text-[11px]` in IBM Plex Mono
(~0.6em advance ≈ 6.6px/char) the column holds roughly 26 characters.

Counting the labels this phase shipped against that budget:

- **nl — the default and fallback language** (`lib/i18n/index.ts`: `lng: "nl"`, `fallbackLng: "nl"`):
  roughly 13 of the 18 labels exceed it, including
  `"Terzijde: niet controleerbaar en niet doorslaggevend"` (52 chars),
  `"Toch gecheckt: geen van beide redenen"` (37),
  `"In de wachtrij maar nooit gecheckt"` (34) — the row the tooltip calls
  *"Het belangrijkste getal op deze pagina"*.
- **fr:** similar or worse — `"Écartées : ni vérifiables ni déterminantes"` (41),
  `"En file d'attente mais jamais vérifiées"` (39).
- **en:** ~6 of 18, e.g. `"Set aside: neither checkable nor load-bearing"` (44),
  `"Checked anyway: not load-bearing"` (32).

So on the language the app boots in, the operator sees a *cut-off* business phrase and **no ⓘ at
all** on the majority of rows — including the one the copy itself calls the most important number
on the page. The explanatory tooltip is the entirety of UAT-22-F1's second half ("and a tooltip
explaining them maybe"), and it is unreachable exactly where the labels are longest and therefore
where an explanation is most needed. There is also no `title` on the label span, so the truncated
text has no fallback: the full string exists only in the parent `<div>`'s `aria-label`, which is
on a role-less generic element (see WR-04).

Note this also renders `funnelLabels.ts`'s `MAX_LABEL_CHARS = 80` inert as the "layout guard" its
comment claims (`funnelLabels.ts:92`) — the real bound is ~26 characters of CSS, not 80 of JS.

**Fix:** take the glyph out of the truncating box and give the label a native tooltip of its own,
so neither the text nor the affordance can be clipped:

```tsx
<span className="flex w-44 shrink-0 items-center gap-1">
  <span className="truncate" title={label}>
    {label}
  </span>
  {tip ? <InfoTip text={tip} /> : null}
</span>
```

`shrink-0` on the ⓘ (or the flex container's default `min-width:auto` on the inner span) keeps
the glyph visible at every label length. Widening `w-44` alone does not fix this — it only moves
the cliff.

## Warnings

### WR-01: Nothing binds `KNOWN_FUNNEL_STAGES` to the locale catalogs, and the i18n gate cannot see these keys

**File:** `frontend/src/lib/research/funnelLabels.ts:74-87`, `frontend/src/lib/research/funnelLabels.test.ts`

**Issue:**
`isKnownFunnelStage`'s docstring states the contract as *"Whether the report has curated copy — a
label AND a tooltip, in all three languages"*. Nothing verifies that. The 30-test suite pins the
TypeScript array against itself and never opens a locale file; `grep` for `funnelLabel` finds only
`funnelLabels.ts`, its test, `VerificationReport.tsx` and the three catalogs — no gate.

The escape hatch is closed at both ends by things the code itself documents:

- `VerificationReport.tsx:626-631` records that DEF-22-03's i18n audit regexes cannot see a
  template-literal `t()` call. I ran `scripts/i18n-audit.mjs`: PASS, and it never mentions these
  36 keys.
- The `defaultValue` fallback then makes the failure *silent* rather than loud: a stage in
  `KNOWN_FUNNEL_STAGES` whose locale key was renamed, dropped or never written renders the
  humanized token instead of curated copy, with no error anywhere.

So the two realistic edits — the engine adds a nineteenth key and someone appends it to the array
without copy, or a catalog reshuffle drops one of the 36 paths — both ship green and regress that
row to exactly the UAT-22-F1 defect. This is the failure mode `funnelLabels.ts:1-3` says the whole
module exists to prevent ("measured by real assertions rather than asserted in a comment"), left
unmeasured at the one seam that crosses out of TypeScript.

**Fix:** add a test to `funnelLabels.test.ts` — the suite runs under `environment: "node"` and
Vite resolves JSON imports, so this costs nothing:

```ts
import en from "@/locales/en/intake.json";
import nl from "@/locales/nl/intake.json";
import fr from "@/locales/fr/intake.json";

describe("KNOWN_FUNNEL_STAGES — every curated stage has copy in all three languages", () => {
  for (const [lang, cat] of Object.entries({ en, nl, fr })) {
    for (const stage of KNOWN_FUNNEL_STAGES) {
      it(`${lang}: ${stage} has a label and a tooltip`, () => {
        expect(cat.verification.funnelLabel[stage]).toBeTruthy();
        expect(cat.verification.funnelTip[stage]).toBeTruthy();
      });
    }
  }
  it("no catalog carries a label for a stage the vocabulary does not know", () => {
    expect(Object.keys(en.verification.funnelLabel).sort())
      .toEqual([...KNOWN_FUNNEL_STAGES].sort());
  });
});
```

The last assertion is the one that catches the reverse drift, and it would have caught CR-01's
sibling class of error had the label been dropped rather than mistranslated.

### WR-02: `needs_input` gets "paused… open the run to continue it", but the run page offers only a fresh, re-charged attempt

**File:** `frontend/src/lib/research/workPhase.ts:80-82`, `frontend/src/locales/{en,nl,fr}/intake.json` (`nextStep.inResearchPausedBody`)

**Issue:**
`deriveWorkPhasePresentation` routes `parked` and `needs_input` to the same `paused` presentation,
and that presentation's copy is *"Research is paused and waiting on you. **Open the run to
continue it.**"* (nl: *"Open de run om verder te gaan."*; fr: *"Ouvrez le run pour la
poursuivre."*).

That instruction is true for `parked` and false for `needs_input`:

- `RunActions.tsx:105` — `showResume = status === "parked"`. Resume is offered for `parked` only.
- `RunActions.tsx:109` — retry is offered for `failed || cancelled || **needs_input**`.
- `RunStatusCard.tsx:270-273` says it in words: *"This side has no answer surface by design, so
  the card says so in words and its slot carries a fresh attempt rather than a continuation."*

So for `needs_input` the banner sends the operator to a page whose only action is a **new run**.
This codebase treats that distinction as expensive on purpose — `ResearchRunProgress.tsx:658-660`
and `RunStatusCard.tsx:29-33` both record that a fresh attempt "throws away every checkpoint the
engine has already paid for", against a ~$45 run. The two statuses are correctly kept apart
everywhere else in the app; the new banner is the one surface that fuses them.

**Fix:** either split the presentation, or neutralise the sentence. The smaller change is to stop
promising a continuation the banner cannot know is available:

```json
"inResearchPausedBody": "Research is paused and waiting on you. Open the run to see what it needs."
```

If the distinction is worth keeping (it is everywhere else), add a sixth
`WorkPhasePresentation` member — the `never` guard in `NextStepBanner.tsx:354` will force the new
branch to be handled rather than let it fall through:

```ts
case "parked":      return "paused";
case "needs_input": return "needs_input";
```

### WR-03: `ResearchRunProgress` is now a dead export that still opens its own SSE stream

**File:** `frontend/src/components/intake/ResearchRunProgress.tsx:621-949` (the hook call is `:638`)

**Issue:**
Nothing in `src/` imports the `ResearchRunProgress` component any more — `admin.pulse.intakes.$id.tsx`
imports `{ IntakeOpenRunLink, useActiveResearchRun }` and `admin.pulse.runs.$runId.index.tsx`
imports `{ useActiveResearchRun }`. The component and its exclusive subtree are unreachable:
`ResearchRunProgress`, `AgentFeed`, `AgentCard`, `RawOutputControls`, `StageSummaryCard`,
`StageIcon`, `toStageRows`, `fmtDurationSecs`, the local `RESEARCH_TERMINAL` set, the
`export { triggerResearch }` re-export (the route imports `triggerResearch` straight from
`@/lib/api/research`), and transitively `components/intake/AuditBodyPanel` — roughly 450 lines.

That is Phase 22's residue (D-22-5 removed the element), not Phase 23's doing, but Phase 23 is
what makes it load-bearing: this file's own header now asserts that the intake route owns the
page's single research stream, and the *only* thing enforcing that is that nobody imports line
621. Line 638 still reads `const { run } = useActiveResearchRun(intakeId);`. Anyone who re-adds
`<ResearchRunProgress intakeId={...}/>` to the intake page — a natural reading of "the embedded
card" that the surrounding comments discuss at length — silently reintroduces the second SSE
connection and the second server handler burning to `MAX_STREAM_SECONDS`, with no test and no gate
to catch it.

**Fix:** delete the dead component and its exclusive helpers (and `AuditBodyPanel`, if the run
page does not use it), leaving `useActiveResearchRun`, `OpenRunLink` and `IntakeOpenRunLink`. If
deletion is out of scope for this phase, log it as a deferred item and add a grep guard alongside
the existing 16-D-08 route-import guard:

```sh
# no route may render the embedded feed — it opens a second research stream
! grep -rn "<ResearchRunProgress" frontend/src/routes/
```

### WR-04: The funnel tooltip is mouse-only and its accessible name is on a role-less element

**File:** `frontend/src/components/intake/VerificationReport.tsx:340-346` (`InfoTip`), `:646-650` (the row `<div>`)

**Issue:**
`InfoTip` renders `<span className="ml-1 cursor-help" title={text} aria-label={text}>ⓘ</span>`.
The span has no `tabIndex` and no `role`. Two consequences:

- `title` surfaces on pointer hover only. A keyboard-only operator cannot reach it (nothing to
  focus) and neither can a touch user. The explanatory sentence — the deliverable of UAT-22-F1 —
  is available to mouse users and no one else.
- `aria-label` on an element with the implicit `generic` role is not required to be exposed, and
  in practice is dropped by several screen readers. The same applies to the row wrapper at `:646`:
  `aria-label={t("verification.funnelStage", …)}` sits on a plain `<div>` with no role, so the
  "label: count" string that is supposed to carry the row to assistive tech may never be
  announced — which also means the full, untruncated label has no reliable second route to the
  user (see CR-02).

The comment at `:327-331` argues the browser tooltip "is enough" and that `aria-label` "carries
the same sentence to a screen reader". The first is true only for mouse users; the second is not
reliably true for a role-less span.

**Fix:** make the glyph a real, focusable, named control, and give the row an announced role:

```tsx
function InfoTip({ text }: { text: string }) {
  return (
    <button
      type="button"
      tabIndex={0}
      aria-label={text}
      title={text}
      className="ml-1 shrink-0 cursor-help text-ink/40"
    >
      ⓘ
    </button>
  );
}
```

and on the row, `role="group"` (or render the row as an `<li>` inside a `<ul>`) so its
`aria-label` is exposed. This mirrors the `NextStepBanner` atom, so fixing it there too keeps the
"house pattern" claim honest — but the funnel is the surface with 18 of them.

### WR-05: `humanizeFunnelStage` replaces underscores *after* it trims and collapses whitespace, so a leading underscore drops the capital and a doubled one doubles the space

**File:** `frontend/src/lib/research/funnelLabels.ts:122-133`

**Issue:**
The pipeline order is: strip control chars → collapse whitespace → **trim** → replace `_` with
space. Because the `_`→space substitution is last, the spaces it creates are never collapsed and
never trimmed. Measured:

```
"_new_key"  -> " new key"     // leading space, and charAt(0) is a SPACE so nothing is capitalised
"a__b"      -> "A  b"         // doubled space survives
"park_"     -> "Park "        // trailing space
"__"        -> "  "           // BLANK label — two spaces
```

The last one defeats the module's own stated invariant. `funnelLabels.ts:89` — *"Never the empty
string — a blank row is not a row"* — is enforced by an `=== ""` check that runs *before* the
underscores become spaces, so an all-underscore key sails past it and renders a visually empty
label. The first case is the realistic one: a private/internal engine key prefixed with `_` is an
ordinary Python convention, and it renders lowercase with a leading space instead of the
capitalised phrase the function promises. This is the sole guard on the "unheard-of key" path that
`funnelLabels.ts:12-19` calls a contract rather than a hedge.

The suite does not catch it: `"checked   twice"` covers space collapsing, and
`humanizeFunnelStage("")`/`("   ")` cover the empty paths, but no case combines underscores with
the trim/collapse ordering.

**Fix:** substitute underscores first, then normalise once:

```ts
const cleaned = stage
  .replace(/\p{C}/gu, " ")
  .replace(/_/g, " ")
  .replace(/\s+/g, " ")
  .trim();
```

and add the cases to the suite:

```ts
it("a leading underscore does not eat the capital or leave a leading space", () => {
  expect(humanizeFunnelStage("_new_key")).toBe("New key");
});
it("an all-underscore key is treated as nameless, not rendered as blank space", () => {
  expect(humanizeFunnelStage("__")).toBe("Unnamed figure");
});
it("doubled underscores collapse to one space", () => {
  expect(humanizeFunnelStage("a__b")).toBe("A b");
});
```

## Info

### IN-01: `inResearchUnknownBody` tells the operator to open a run link that is not on the page in that exact state

**File:** `frontend/src/locales/{en,nl,fr}/intake.json` (`nextStep.inResearchUnknownBody`), `frontend/src/routes/admin.pulse.intakes.$id.tsx:1220`

**Issue:** the `unknown` presentation is reached precisely when `researchRun` is `null`, and the
same `null` makes `<IntakeOpenRunLink runId={null} />` render nothing. So the copy *"Open the run
for its live status"* points at an affordance that is absent in the state that produces it.
Transient before the first SSE frame; permanent when the intake has no run or the stream is
unavailable.

**Fix:** neutralise the instruction — e.g. *"Deep research is the current work phase. Its live
status is not available on this page right now."* — or gate the sentence on `researchRun !== null`
by passing the run id down alongside the status.

### IN-02: `MAX_LABEL_CHARS = 80` is documented as a layout guard it cannot be

**File:** `frontend/src/lib/research/funnelLabels.ts:92-93`

**Issue:** the comment reads *"The row is `w-44` and `truncate`; this cap is the first half of that
layout guard"*, but 176px of 11px monospace holds ~26 characters, so the CSS clips long before 80
is reached and the JS cap never binds on any realistic key. Harmless on its own; it is the
reasoning that produced CR-02, so it is worth correcting together with it.

**Fix:** reword to what the cap actually protects against (a pathological multi-hundred-character
key reaching the DOM at all), and stop describing it as the row's layout guard.

### IN-03: `humanizeFunnelStage`'s `slice(0, 80)` counts UTF-16 code units and can split a surrogate pair

**File:** `frontend/src/lib/research/funnelLabels.ts:132`

**Issue:** `phrase.slice(0, MAX_LABEL_CHARS)` can cut between the high and low surrogate of an
astral character, leaving a lone surrogate that renders as U+FFFD. Engine funnel keys are ASCII
today, so this is theoretical, but the function's declared job is to survive any key.

**Fix:** slice by code point, e.g. `[...phrase].slice(0, MAX_LABEL_CHARS).join("")`.

---

_Reviewed: 2026-08-13T14:35:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
