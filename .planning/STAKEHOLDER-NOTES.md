# Stakeholder Notes — open decisions

Running list of items to put in front of stakeholders. Each note states the current
behavior (verified in code), why it matters, and the decision being asked for.

---

## 2026-07-21 — Context pack regeneration: versioning edge cases

**Current behavior (verified):** every "Regenerate context pack" creates a NEW version;
old versions are kept forever as history. The research run always uses the newest
finished version automatically (the intake's pointer moves atomically with each
generation). This part is sound and needs no decision.

Three edge cases need a stakeholder call:

### 1. Old pack versions stay in semantic search
Every pack version gets embedded for semantic search, and superseded versions are never
removed — so search can return text from an outdated pack (e.g. quoting facts the
operator deliberately regenerated away).
**Decision asked:** when a pack is regenerated, should the old version's search index
entries be (a) deleted, (b) kept but flagged/deprioritized, or (c) kept as-is (status quo)?

### 2. Regenerating a pack resets the intake status to "decomposed"
Regenerating always sets the intake back to status `decomposed`, even when research is
already running or finished. Data is unaffected and duplicate research triggers are still
blocked, but the workflow display jumps backwards (the intake looks like it regressed).
**Decision asked:** should regeneration after research has started (a) be blocked,
(b) keep the current status instead of resetting it, or (c) stay as-is (accepted quirk)?

### 3. Race: starting research while a regenerate is still running
Pack generation takes ~30 seconds. If an operator clicks Regenerate and then "Start
onderzoek" before the new pack is finished, the research uses the PREVIOUS pack version.
Today the only protection is operator discipline (wait for the new pack to appear).
**Decision asked:** should the Start-research button be disabled while a context-pack
generation is in flight (recommended, small frontend guard), or is operator discipline
acceptable?
