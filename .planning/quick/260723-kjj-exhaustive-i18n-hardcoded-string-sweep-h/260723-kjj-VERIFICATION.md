---
phase: quick-260723-kjj
verified: 2026-07-23T16:00:00Z
status: human_needed
score: 7/8 must-haves verified (8th is visual/UX — needs operator to switch to EN in browser)
overrides_applied: 0
human_verification:
  - test: "Switch UI to English in a browser session, navigate to an intake detail page, open the AI-enrichment popover, open the History sheet, and hover the bell icon"
    expected: "All copy is in English: AI-skill descriptions, History status labels (completed/failed/running), skill names, and the bell tooltip. Zero Dutch fragments visible."
    why_human: "Cannot launch a browser or drive the React app to confirm live rendering; locale switching and t() runtime resolution cannot be confirmed by static grep alone."
---

# Quick 260723-kjj: Exhaustive i18n Hardcoded-String Sweep — Verification Report

**Task Goal:** Exhaustive i18n sweep — an operator with UI language set to English (or French) must see zero Dutch fragments in the intake-flow admin UI; all three locale catalogs key-consistent; context-pack history accordion removed from ContextPackBlock; reusable audit script `frontend/scripts/i18n-audit.mjs` passes.
**Verified:** 2026-07-23T16:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Commit Existence

All three executor commits exist in the repository:

| Commit | Message | Files Changed |
|--------|---------|---------------|
| e02985b | fix: translate AI-skills descriptions, History labels, notification bell | 12 files |
| b2a22ed | refactor: remove redundant context-pack history accordion | 4 files |
| cd7e63a | feat: add i18n audit script and close 3-way parity gaps | 5 files |

Working tree is clean relative to these commits (no untracked modified source files in scope).

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | An operator with UI language set to English sees zero Dutch fragments in the AI-skills popover, the History sheet, the notification bell tooltip, or anywhere else in the intake flow | ? UNCERTAIN | Static checks pass; zero Dutch in source files for intake-flow components (all Dutch hits are in `admin.sales.*`, documented exception). Runtime rendering requires human. |
| 2 | The four aiSkills.*Desc keys resolve to real translations in nl, fr and en (no inline Dutch fallback renders) | ✓ VERIFIED | All four keys (`aiSkills.structureDesc/extractDesc/embeddingsDesc/transcribeDesc`) exist with real values in all 3 locales. AISkillsPanel.tsx uses single-arg `t("aiSkills.structureDesc")` — no Dutch fallback string anywhere in that file. |
| 3 | The History sheet status labels (succeeded/failed/running) and skill names render in the active locale, not hardcoded Dutch | ✓ VERIFIED | `admin.pulse.intakes.$id.tsx:1646-1650` uses `t("intakeDetail.history.done")`, `t("intakeDetail.history.failed")`, `t("intakeDetail.history.busy")`. EN values: "✓ completed", "✗ failed", "running…". Skill labels use `t(\`intakeDetail.history.skill.${r.skill_name}\`, r.skill_name)`. No Dutch string `SKILL_LABELS` const present. |
| 4 | The notification bell tooltip and aria-label render in the active locale | ✓ VERIFIED | TopBar.tsx:32-33 uses `t("notifications.comingSoon")` and `t("notifications.ariaLabel")` via `useTranslation("common")`. EN values: "Notifications — coming soon" / "Notifications". |
| 5 | The context-pack inline history accordion is gone from the center page; context-pack runs are only visible in the header History sheet | ✓ VERIFIED | `toggleHistory`, `loadHistory`, `setHistory`, `historyOpen` — zero hits in ContextPackBlock.tsx. `loadLatest`, `reloadSignal`, `viewingPack` all present and intact (lines 289, 306, 312, 517). |
| 6 | All three locale catalogs (nl, fr, en) are key-consistent per namespace — no key present in one locale and missing in another | ✓ VERIFIED | `node scripts/i18n-audit.mjs` CHECK A: "✓ all namespaces key-consistent across nl/fr/en". Script exits 0. |
| 7 | No genuine two-argument t('key','Dutch fallback') translation calls remain in frontend/src | ✓ VERIFIED | `grep -rnoE "[^.A-Za-z]t\(\"[^\"]*\",\"[^\"]*\"" src/ | grep -vi "helvetica\|Content-Type"` returns zero lines. CHECK C in audit script: "✓ no genuine two-arg t('key','fallback') calls remain". |
| 8 | Every t('literal.key') used in src resolves to a key present in all three locales (dynamic-key false positives excepted and listed) | ✓ VERIFIED | CHECK B: "✓ every literal t() key resolves in all locales". Dynamic-key allowlist (11 entries) matches the SUMMARY exactly and is printed by the script for human review. |

**Score:** 7/8 truths fully auto-verified; 1 (truth #1, live visual rendering) requires human browser check.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/locales/en/intake.json` | aiSkills.*Desc + skillRunProgress.* keys; orphaned contextPack.historyToggle removed | ✓ VERIFIED | All four Desc keys present; skillRunProgress.title/body present; historyToggle/loading/noRuns/view absent. |
| `frontend/src/locales/en/admin.json` | intakeDetail.history.empty + status labels (done/failed/busy) + skill sub-map | ✓ VERIFIED | All keys confirmed present with English values. |
| `frontend/src/locales/en/common.json` | notifications.comingSoon + notifications.ariaLabel | ✓ VERIFIED | Both keys present with English values. |
| `frontend/src/components/intake/AISkillsPanel.tsx` | aiSkills descriptions via single-arg t() | ✓ VERIFIED | Lines 107, 118, 130, 155 use `t("aiSkills.*Desc")` — no second argument Dutch fallback. |
| `frontend/src/components/intake/ContextPackBlock.tsx` | Inline history accordion removed; latest-pack refresh intact | ✓ VERIFIED | Zero accordion symbols; loadLatest, reloadSignal, viewingPack intact. |
| `frontend/scripts/i18n-audit.mjs` | 3-way key parity + used-key coverage + hardcoded-string scan; exits 0 | ✓ VERIFIED | Script exists, runs, exits 0. CHECK A/B/C hard gates pass. 107 CHECK D advisories all justified or fixed. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `AISkillsPanel.tsx` | `locales/{nl,fr,en}/intake.json` | `t("aiSkills.structureDesc")` single-arg | ✓ WIRED | 4 desc keys exist in all 3 locales; single-arg calls confirmed in source. |
| `admin.pulse.intakes.$id.tsx` | `locales/{nl,fr,en}/admin.json` | `t("intakeDetail.history.*")` + skill template literal | ✓ WIRED | Status t() calls at lines 1646-1650; skill label via template at line 1628; keys confirmed in all 3 locales. |
| `TopBar.tsx` | `locales/{nl,fr,en}/common.json` | `useTranslation("common")` for bell title/aria-label | ✓ WIRED | `useTranslation("common")` at line 21; `t("notifications.comingSoon")` at line 32; `t("notifications.ariaLabel")` at line 33. Keys present in all 3 locales. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| i18n audit exits 0 (A/B/C clean) | `node scripts/i18n-audit.mjs` | Exit 0; PASS message | ✓ PASS |
| TypeScript clean | `npx tsc --noEmit` | No output (0 errors) | ✓ PASS |
| Zero two-arg i18n fallbacks | `grep -rnoE "[^.A-Za-z]t\(..., \"...\")` | 0 matches | ✓ PASS |
| No Dutch in intake-flow components | Grep Dutch signal words excluding sales routes | 0 hits | ✓ PASS |
| Accordion state vars removed from ContextPackBlock | `grep -n "toggleHistory\|loadHistory\|historyOpen"` | 0 matches | ✓ PASS |
| `loadLatest`/`reloadSignal` retained | `grep -n "loadLatest\|reloadSignal"` | Present at lines 44, 289, 306, 312 | ✓ PASS |
| English locale values are English | Node inline check on en/*.json | "✓ completed", "Intake analysis", "Converts answers into structured data.", etc. | ✓ PASS |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `admin.sales.projects.$id.tsx` (multiple lines) | Hardcoded Dutch strings ("Bezig…", "mislukt", etc.) | INFO | Sales product area only — explicitly documented as out-of-scope in plan SCOPE NOTE and SUMMARY "Judged exceptions" table. Not the intake-flow the operator complained about. |
| `ResearchResultsPanel.tsx:426` | `doc.text()` with hardcoded `nl-BE` locale and Dutch PDF label | INFO | Inside jsPDF answer-PDF export; no `t()` in scope. Documented as "Follow-up candidate" in SUMMARY judged exceptions. Advisory only per audit script. |

No unreferenced TBD/FIXME/XXX markers found in modified files.

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| I18N-SWEEP | ✓ SATISFIED | All four original offenders fixed, 3-way key parity established, accordion removed, audit script exits 0. |

### Human Verification Required

### 1. Live locale-switch visual check

**Test:** Log in as an operator, switch UI language to English (or French), navigate to an intake detail page. Open the AI-enrichment Sparkles popover, click the History sheet button, and hover over the bell icon in the TopBar.
**Expected:** All copy in those UI surfaces is in English (French): AI-skill descriptions ("Converts answers into structured data."), History status labels ("✓ completed", "✗ failed", "running…"), skill names ("Intake analysis", "Structure answers", etc.), and the bell tooltip ("Notifications — coming soon"). Zero Dutch fragments visible anywhere in the intake admin flow.
**Why human:** The React app cannot be launched from this verification context. `react-i18next` runtime resolution and locale-persistence through the LanguageSwitcher require a running browser session to confirm.

### Gaps Summary

No automated gaps. All hard-gate checks pass. One item deferred to human visual confirmation.

The sales product area (`admin.sales.*`) retains Dutch strings — this is a documented out-of-scope exception, not a gap for this task. The audit script CHECK D advisory flags them; the SUMMARY enumerates each with a justification. This is working as intended.

---

_Verified: 2026-07-23T16:00:00Z_
_Verifier: Claude (gsd-verifier)_
