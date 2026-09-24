/**
 * Should the top-bar client dropdown follow the intake currently on screen?
 *
 * Pure — no React, no network, no i18n (cf. `intake-writable.ts`, `intake-bulk.ts`).
 *
 * Why this exists
 * ---------------
 * The client tested the 2026-09-24 release and followed the research mail's deep link
 * into the admin. The intake opened, but the top bar still showed whichever client was
 * selected last — so the page and the dropdown disagreed about who the operator was
 * looking at, on a screen whose entire job is telling clients apart.
 *
 * Why a module and not three inline `if`s
 * ---------------------------------------
 * Three routes need the identical rule (the intake detail page and the two run pages),
 * and this repo has NO component test harness — a predicate left inline in TSX is proven
 * by nothing. Same argument plan 08 wrote for `intake-bulk.ts`. The colocated
 * `.test.ts` is what makes the rule checkable at all.
 *
 * Why a null active space SYNCS
 * -----------------------------
 * D-23.5-09, the operator's words: it should ALWAYS match and preload. So "All clients"
 * is a SELECTION to be replaced, not a wildcard to honour. This is the one case the
 * obvious reading ("only switch when something else is selected") gets wrong, and it is
 * the case the deep link from the mail actually lands in.
 *
 * Why a missing intake space NEVER clears the selection
 * ----------------------------------------------------
 * A failed or partial read must not look like a deliberate switch to "All clients".
 * Silence beats a wrong answer here: leaving the operator's own choice alone is always
 * defensible, silently widening their view to every client is not.
 *
 * Why the equality guard matters
 * ------------------------------
 * It is what makes the calling effect idempotent. The effect depends on `activeSpaceId`
 * and calls `setActiveSpace`; after one sync the predicate is false, so the effect
 * cannot re-fire on the state change it just caused.
 *
 * SECURITY (T-06-13), carried verbatim from `active-space.tsx`
 * -----------------------------------------------------------
 * The active space id is UX STATE, NEVER an authorization input. `withActiveSpace()`
 * appends `?space_id=<id>` to read paths so a superadmin — already authorized for all
 * spaces — can narrow what is displayed; the backend re-derives a regular user's space
 * from the verified token and ignores the param, so this can never widen access. The
 * value written here comes from a read the caller ALREADY passed, so it can reference no
 * space the caller could not already see. The three calling routes sit behind
 * `AdminLayout`'s superadmin wall already — add no fourth client-side role check (plan
 * 23.5-01's decision, reaffirmed by plan 08).
 *
 * @param activeSpaceId  the current top-bar selection, or null for "All clients"
 * @param intakeSpaceId  the space of the intake on screen; null/undefined/"" when unknown
 */
export function shouldSyncActiveSpace(
  activeSpaceId: string | null,
  intakeSpaceId: string | null | undefined,
): boolean {
  if (!intakeSpaceId) return false;
  return intakeSpaceId !== activeSpaceId;
}
