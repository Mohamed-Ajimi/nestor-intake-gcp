# Phase 11 — Deferred Items

Out-of-scope discoveries logged during execution (SCOPE BOUNDARY). Not fixed here.

## 11-05

- **`mode: "admin" | "klant"` discriminant literal** (ResearchResultsPanel.tsx and many sibling
  intake components). The CI Dutch-stopword guard regex matches `\bklant\b`, so the `"klant"`
  mode-enum value trips the guard. This is a pre-existing cross-cutting DOMAIN discriminant (a code
  identifier / data value, NOT user-visible display text) that predates the 11-05 changes and is
  threaded through many callers (`admin.pulse.intakes.$id.tsx`, token routes, etc.). Renaming it is
  an architectural change (Rule 4) touching sibling files outside this plan's declared
  `files_modified`. Options for a later plan / phase gate: (a) rename the enum to `"admin" | "client"`
  across all call sites, or (b) add a targeted guard exemption for the `mode:` discriminant literal.
  All user-visible Dutch prose in ResearchResultsPanel.tsx IS externalized; only the enum literal and
  code comments remain.

- **`frontend/src/components/intake/IntakeWorkflowStepper.tsx:126`** has a hardcoded Dutch string
  (`"Klant is nog aan het invullen."`). This file is NOT in 11-05's declared `files_modified` — it
  belongs to a sibling externalization plan's scope (11-03/11-06). Out of scope for 11-05 per the
  SCOPE BOUNDARY rule (only fix files the current task changes). Flag for the owning plan / phase gate.
