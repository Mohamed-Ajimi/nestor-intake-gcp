// frontend/src/lib/research/funnelLabels.ts — the gate funnel's stage vocabulary, extracted as a
// pure module so it can be measured by real assertions rather than asserted in a comment
// (23-01, UAT-22-F1).
//
// WHY THIS EXISTS. The verification report used to print the engine's raw dict keys at the
// operator — `should_have_been_checked`, `checked_incidentally_not_load_bearing` — and the
// operator's verdict on that was "it doesnt read good as we are using cariable names". A report
// is evidence, and evidence a reader has to be an engine maintainer to parse is evidence only in
// name. This module is the seam between an ENGINE IDENTIFIER and a phrase a business reader can
// act on.
//
// THE UNKNOWN KEY IS A CONTRACT, NOT A STOPGAP. `pipeline._build_funnel`'s docstring declares
// funnel keys **ADDITIVE ONLY** — the engine is free to add one at any release and Phase-15
// surfaces assert on the existing names, so nothing stops a nineteenth key arriving here
// tomorrow. `VerificationReport.tsx` renders EVERY numeric entry of that flat dict, so a key
// this build has never heard of WILL reach the screen. `humanizeFunnelStage` is therefore the
// designed behaviour for the normal state of the world after any engine release, not a defensive
// afterthought: an unheard-of key renders as a readable phrase with its real figure, never as a
// blank row, never as a crash, and never as a raw snake_case token.
//
// THE SET IS ENUMERATED ON PURPOSE. It is deliberately NOT derived from a regex over key shape
// (every funnel key is snake_case, so shape distinguishes nothing) and deliberately NOT written
// as a negation. Same argument `verificationGate.ts` makes: a negation defaults every key nobody
// has thought about INTO the "we have curated copy for this" branch, which is how a raw
// identifier or a missing-key i18n path reaches the screen. A new key belongs in this list as a
// deliberate edit made together with its locale copy, by someone who has read the engine source
// the copy is describing.
//
// THIS MODULE HOLDS NO DISPLAY COPY. Every curated label and tooltip lives in the three locale
// files (`locales/{en,nl,fr}/intake.json`, `verification.funnelLabel.*` / `verification.funnelTip.*`).
// A label map in TypeScript would be a FOURTH copy of the vocabulary, untranslated, and the one
// the i18n parity audit cannot see — so the English would silently become the product while nl
// and fr drifted. The only string this module owns is the placeholder for a nameless key.
//
// It is also pure TypeScript by requirement, not by taste: `vitest.config.ts` includes
// `src/**/*.test.ts` only, under `environment: "node"`. A React import or a `t()` call here would
// put the vocabulary beyond the reach of the suite that pins it.

/**
 * The eighteen numeric keys the engine writes into the one flat `funnel` dict, in the order the
 * engine builds them: the nine the gate stage owns, then the nine the pipeline stage adds.
 *
 * `verification_degraded` (bool) and `degradation_reasons` (list) live in the same dict and are
 * deliberately ABSENT here — they are not figures, and `VerificationReport.tsx` drops every
 * non-numeric entry before render (the CR-01 filter). Adding either here would invite a caller
 * to render them as funnel rows again.
 */
export const KNOWN_FUNNEL_STAGES: readonly string[] = [
  // ── The nine the gate stage owns (`pipeline/tribunal/gates.py` `_FUNNEL_KEYS`) ──
  "distilled", // every claim distilled out of the research, before any filtering
  "kept", // claims the materiality gates judged worth considering for a check
  "dropped", // claims gated out with no check; the four reason keys below break this down
  "not_falsifiable", // dropped: the claim cannot be proved or disproved
  "not_load_bearing", // dropped: nothing in the conclusion depends on the claim
  "both", // dropped for both reasons at once
  "selected_verify", // claims placed in the fact-check queue
  "skipped_stable", // skipped by the error-likelihood gate as a stable, widely known fact
  "gate_errors", // gate batches that errored out; their claims default to KEEP, never a silent drop
  // ── The nine the pipeline stage adds (`pipeline/tribunal/pipeline.py` `_build_funnel`) ──
  "checked", // selected AND actually checked — bucket 1 of the G-08 accounting
  "should_have_been_checked", // bucket 3: selected and NOT checked, whatever the cause. The phase's
  // most important number; ZERO on a healthy run. An unchecked claim leaves
  // its passage STANDING in the delivered prose (only a refutation triggers
  // scrubbing), so this counts passages that shipped unexamined.
  "verify_sessions", // skeptic sessions actually launched — a throughput measure (G-13), never a quality one
  "checked_incidentally", // bucket 1b: NOT selected, yet checked as a member of a selected group
  "checked_incidentally_not_falsifiable", // of those, the ones carrying that gate reason
  "checked_incidentally_not_load_bearing", // of those, the ones carrying that gate reason
  "checked_incidentally_both", // of those, the ones carrying both gate reasons
  "checked_incidentally_stable", // of those, the ones originally skipped as stable known facts
  "unresolved_anchors", // D-06: [[c:...]] anchors the writing model emitted that matched no claim and were removed
];

const KNOWN = new Set(KNOWN_FUNNEL_STAGES);

/**
 * Whether the report has curated copy — a label AND a tooltip, in all three languages — for
 * this funnel key.
 *
 * Case-sensitive on purpose: the engine emits lowercase keys, so `CHECKED` is not `checked` and
 * must not borrow its copy. A caller that gets `false` is expected to fall back to
 * `humanizeFunnelStage`, not to hide the row: the FIGURE is real even when the description is
 * missing, and dropping a row would be the report lying about its own accounting.
 */
export function isKnownFunnelStage(stage: string): boolean {
  return KNOWN.has(stage);
}

/** The label for a key with no name at all. Never the empty string — a blank row is not a row. */
const UNNAMED = "Unnamed figure";

/** The row is `w-44` and `truncate`; this cap is the first half of that layout guard (T-23-02). */
const MAX_LABEL_CHARS = 80;

/**
 * Turn any funnel key — including one this build has never seen — into a readable phrase.
 *
 * `a_brand_new_engine_key` → `A brand new engine key`.
 *
 * Deliberately NOT title-case: only the first character is raised. Title-casing would capitalise
 * every word of an engine key and produce something that looks like curated copy when it is not,
 * which is the fabrication this project bars. A humanized key should read as what it is — the
 * engine's own name, made legible — so that the missing tooltip beside it is expected rather
 * than mysterious.
 *
 * Two safety properties this function is the sole owner of (T-23-02):
 *
 * - Control characters are stripped, and the resulting whitespace runs collapse to one space, so
 *   a key carrying `\n` or `\t` cannot inject line breaks into a funnel row. Each control
 *   character becomes a SPACE rather than being deleted outright: a `\n` inside a key is a word
 *   boundary, and deleting it would fuse two words into a nonsense token an operator could
 *   misread as a real engine name. Degrading to "Checked incidentally" is more honest than
 *   degrading to "Checkedincidentally".
 * - The result is capped at {@link MAX_LABEL_CHARS} plus an ellipsis, so an absurd key cannot
 *   blow the row's layout. The ellipsis is appended only when something was actually removed, so
 *   the truncation is never claimed where it did not happen.
 *
 * The output is rendered by React as a text child and as `title` / `aria-label` attribute values,
 * all auto-escaped. It must never be routed through `dangerouslySetInnerHTML` or `ReactMarkdown`
 * (T-23-01) — an engine key is not trusted markup.
 */
export function humanizeFunnelStage(stage: string): string {
  const cleaned = stage
    // Every Unicode "Other" code point (control, format, surrogate, unassigned) becomes a
    // SPACE. Written as a property escape so this source file carries no control byte itself.
    .replace(/\p{C}/gu, " ")
    // ORDER IS LOAD-BEARING (CR/WR-05). Underscores become spaces BEFORE the collapse and the
    // trim, never after. With the replace last, the spaces it produces were never collapsed or
    // trimmed: `"__"` survived as `"  "` — a BLANK label, which is exactly the "never a blank
    // row" invariant this module exists to hold — and `"_new_key"` came out as `" new key"`,
    // leading space and no capital, because `charAt(0)` was upper-casing a space.
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (cleaned === "") return UNNAMED;
  const phrase = cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
  return phrase.length > MAX_LABEL_CHARS ? `${phrase.slice(0, MAX_LABEL_CHARS)}…` : phrase;
}
