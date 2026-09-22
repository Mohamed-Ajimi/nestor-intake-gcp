import { describe, it, expect } from "vitest";
import {
  headerState,
  partitionForArchive,
  pruneSelection,
  toggleAllVisible,
  toggleSelected,
} from "@/lib/intake-bulk";

// D-23.5-07 multi-select algebra.
//
// WHY THESE TESTS EXIST AT ALL. The route this helper serves
// (`admin.pulse.intakes.index.tsx`) has no component test harness in this repo — there is
// no React Testing Library, no jsdom render, nothing. Anything left inline in that TSX is
// proven by `tsc` and by nothing else. This module is the only part of the bulk feature a
// gate can actually see, so the selection rules live here rather than in the component.
//
// And the rules matter: the thing on the other end of this selection is an IRREVERSIBLE
// delete behind ONE typed confirmation. A helper that quietly keeps an id the operator
// cannot see on screen is a helper that deletes something they never looked at.

const ROWS = [
  { id: "a", status: "draft" },
  { id: "b", status: "archived" },
  { id: "c", status: null },
];

describe("toggleSelected", () => {
  it("adds an absent id", () => {
    expect(toggleSelected(new Set(["a"]), "b")).toEqual(new Set(["a", "b"]));
  });

  it("removes a present id", () => {
    expect(toggleSelected(new Set(["a", "b"]), "b")).toEqual(new Set(["a"]));
  });

  it("returns a NEW set and never mutates the input", () => {
    // React bails out of a re-render when the state value is reference-identical. A
    // mutating toggle would tick the box in the DOM and leave the bulk bar showing the
    // previous count — the count that sits next to the delete button.
    const before = new Set(["a"]);
    const after = toggleSelected(before, "b");
    expect(after).not.toBe(before);
    expect(before).toEqual(new Set(["a"]));
  });
});

describe("headerState", () => {
  it("is 'none' when nothing visible is selected", () => {
    expect(headerState(new Set(), ["a", "b"])).toBe("none");
  });

  it("is 'all' when every visible id is selected", () => {
    expect(headerState(new Set(["a", "b"]), ["a", "b"])).toBe("all");
  });

  it("is 'some' on a partial selection", () => {
    expect(headerState(new Set(["a"]), ["a", "b"])).toBe("some");
  });

  it("is 'none' for an empty visible list, even with ids selected elsewhere", () => {
    // The operator narrowed the filter to nothing. An 'all' header on an empty table
    // would render a ticked box above zero rows — and clicking it would then deselect
    // rows that are not on screen.
    expect(headerState(new Set(["a"]), [])).toBe("none");
  });

  it("ignores selected ids that are not visible when deciding 'all'", () => {
    expect(headerState(new Set(["a", "zzz"]), ["a"])).toBe("all");
  });
});

describe("toggleAllVisible", () => {
  it("selects every visible id from 'none'", () => {
    expect(toggleAllVisible(new Set(), ["a", "b"])).toEqual(new Set(["a", "b"]));
  });

  it("selects every visible id from 'some' — it completes, never inverts", () => {
    // Inverting a partial selection is the behaviour that surprises people: they tick two
    // rows, click the header to "select the rest", and lose the two they already had.
    expect(toggleAllVisible(new Set(["a"]), ["a", "b"])).toEqual(new Set(["a", "b"]));
  });

  it("deselects exactly the visible ids from 'all'", () => {
    expect(toggleAllVisible(new Set(["a", "b"]), ["a", "b"])).toEqual(new Set());
  });

  it("leaves selected-but-not-visible ids alone in BOTH directions", () => {
    // `hidden` was ticked before the operator changed the status filter. Selecting all
    // visible rows must not drop it, and deselecting all visible rows must not take it
    // either — the header control speaks for the rows on screen and nothing else.
    expect(toggleAllVisible(new Set(["hidden"]), ["a"])).toEqual(
      new Set(["hidden", "a"]),
    );
    expect(toggleAllVisible(new Set(["hidden", "a"]), ["a"])).toEqual(new Set(["hidden"]));
  });

  it("returns a new set", () => {
    const before = new Set(["a"]);
    expect(toggleAllVisible(before, ["a"])).not.toBe(before);
  });
});

describe("pruneSelection", () => {
  it("drops ids that are no longer in the list", () => {
    // A completed delete removes the row from state. Without this the id stays in the
    // count, the bulk bar says "3 selected" over two rows, and the next batch re-attempts
    // an intake that is already gone.
    expect(pruneSelection(new Set(["a", "gone"]), ["a", "b"])).toEqual(new Set(["a"]));
  });

  it("keeps everything when every id is still present", () => {
    expect(pruneSelection(new Set(["a", "b"]), ["a", "b", "c"])).toEqual(
      new Set(["a", "b"]),
    );
  });

  it("empties the selection when the list empties", () => {
    expect(pruneSelection(new Set(["a"]), [])).toEqual(new Set());
  });

  it("returns a new set and does not mutate the input", () => {
    const before = new Set(["a", "gone"]);
    const after = pruneSelection(before, ["a"]);
    expect(after).not.toBe(before);
    expect(before).toEqual(new Set(["a", "gone"]));
  });
});

describe("partitionForArchive", () => {
  it("splits the selection into what needs archiving and what is already archived", () => {
    const { toArchive, alreadyArchived } = partitionForArchive(
      ROWS,
      new Set(["a", "b"]),
    );
    expect(toArchive).toEqual(["a"]);
    expect(alreadyArchived).toEqual(["b"]);
  });

  it("treats a null status as needing archiving", () => {
    // `status` is nullable on the wire. A null must not be read as "already archived" —
    // that would silently skip the row and report a success count that excludes it.
    const { toArchive } = partitionForArchive(ROWS, new Set(["c"]));
    expect(toArchive).toEqual(["c"]);
  });

  it("ignores ids that are not in the row list", () => {
    // The selection can outlive a refetch by one render. A stale id must not become a
    // POST against an intake the list no longer knows about.
    const { toArchive, alreadyArchived } = partitionForArchive(ROWS, new Set(["ghost"]));
    expect(toArchive).toEqual([]);
    expect(alreadyArchived).toEqual([]);
  });

  it("returns both halves empty for an empty selection", () => {
    const { toArchive, alreadyArchived } = partitionForArchive(ROWS, new Set());
    expect(toArchive).toEqual([]);
    expect(alreadyArchived).toEqual([]);
  });

  it("preserves the ROW order, not the selection insertion order", () => {
    // The summary toast counts these and the dialog lists them; an order that depends on
    // which checkbox was clicked first makes the same batch read differently every time.
    const { toArchive } = partitionForArchive(ROWS, new Set(["c", "a"]));
    expect(toArchive).toEqual(["a", "c"]);
  });
});
