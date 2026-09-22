/**
 * The selection algebra behind the intake list's bulk Archive / Delete bar (D-23.5-07).
 *
 * Pure — no React, no network, no i18n (cf. `intake-phase.ts`, `intake-writable.ts`).
 *
 * Why this is extracted rather than left inline in the route
 * ---------------------------------------------------------
 * `admin.pulse.intakes.index.tsx` has no component test harness in this repo: there is no
 * React Testing Library, no jsdom render, no route test anywhere under `src/routes/`.
 * Selection logic written inline in that TSX would be covered by `tsc --noEmit` and by
 * absolutely nothing else. A pure module is the only part of this feature a gate can
 * actually see, and the thing on the other end of the selection is an IRREVERSIBLE delete
 * behind ONE typed confirmation — which is a poor place to be running unproven code.
 *
 * Select-all-visible operates on the FILTERED rows
 * ------------------------------------------------
 * Every function here takes the ids currently ON SCREEN, never the full list. An operator
 * who has narrowed to one status and ticks the header selects what they can see and
 * nothing else. That is the only safe reading in front of a delete button: a header
 * control that reached rows scrolled out of view — or filtered out entirely — would
 * destroy intakes the operator never looked at.
 *
 * The corollary is that ids selected under an EARLIER filter survive a later
 * select-all/deselect-all. They are still the operator's selection; the header speaks for
 * the visible rows only. `pruneSelection` is what removes ids that have genuinely left the
 * list (a completed delete, a refetch), and the route calls it whenever the rows change.
 *
 * Every function returns a NEW Set. React bails out of a re-render on a reference-identical
 * state value, so a mutating helper would tick a box in the DOM and leave the bulk bar
 * showing the previous count.
 */

/** Structural minimum the archive split needs — keeps this testable without `IntakeRow`. */
export type BulkRow = {
  id: string;
  status: string | null;
};

/** The header checkbox's three renderable states. `"some"` drives `indeterminate`. */
export type HeaderState = "none" | "some" | "all";

/** The status an archived intake carries — the same literal the backend allow-list holds. */
const ARCHIVED_STATUS = "archived";

/** Add `id` if absent, remove it if present. Never mutates `selected`. */
export function toggleSelected(
  selected: ReadonlySet<string>,
  id: string,
): Set<string> {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

/**
 * How the header checkbox should render for the rows currently on screen.
 *
 * `"none"` for an empty `visibleIds` regardless of what is selected elsewhere: a ticked
 * header above zero rows is a lie, and clicking it would then act on rows the operator
 * cannot see.
 */
export function headerState(
  selected: ReadonlySet<string>,
  visibleIds: readonly string[],
): HeaderState {
  if (visibleIds.length === 0) return "none";
  const hits = visibleIds.filter((id) => selected.has(id)).length;
  if (hits === 0) return "none";
  return hits === visibleIds.length ? "all" : "some";
}

/**
 * Select every visible id, or — when they are all already selected — deselect exactly them.
 *
 * From `"some"` this COMPLETES the selection rather than inverting it. Inverting is the
 * behaviour that surprises people: they tick two rows, click the header expecting "and the
 * rest", and lose the two they had.
 *
 * Ids that are selected but NOT visible survive both directions (see the module docstring).
 */
export function toggleAllVisible(
  selected: ReadonlySet<string>,
  visibleIds: readonly string[],
): Set<string> {
  const next = new Set(selected);
  if (headerState(selected, visibleIds) === "all") {
    for (const id of visibleIds) next.delete(id);
  } else {
    for (const id of visibleIds) next.add(id);
  }
  return next;
}

/**
 * Drop selected ids that are no longer in the list at all.
 *
 * Called whenever the rows change. Without it a completed delete leaves a phantom in the
 * count — the bulk bar reads "3 selected" over two rows, and the next batch re-attempts an
 * intake that is already gone.
 *
 * `presentIds` is the FULL row list, not the filtered one: a row hidden by a filter is
 * still there and its selection is still the operator's.
 */
export function pruneSelection(
  selected: ReadonlySet<string>,
  presentIds: readonly string[],
): Set<string> {
  const present = new Set(presentIds);
  return new Set([...selected].filter((id) => present.has(id)));
}

/**
 * Split the selection into the intakes that need archiving and the ones already archived.
 *
 * A `null` status counts as NEEDING archiving — reading it as "already archived" would
 * silently skip the row and report a success count that excludes it.
 *
 * Ids the row list does not know about are dropped entirely (a selection can outlive a
 * refetch by one render; a stale id must not become a POST against a vanished intake).
 * Both halves come out in ROW order, not selection-insertion order, so the same batch
 * reads the same way every time it is summarized.
 */
export function partitionForArchive(
  rows: readonly BulkRow[],
  selected: ReadonlySet<string>,
): { toArchive: string[]; alreadyArchived: string[] } {
  const toArchive: string[] = [];
  const alreadyArchived: string[] = [];
  for (const row of rows) {
    if (!selected.has(row.id)) continue;
    if (row.status === ARCHIVED_STATUS) alreadyArchived.push(row.id);
    else toArchive.push(row.id);
  }
  return { toArchive, alreadyArchived };
}
