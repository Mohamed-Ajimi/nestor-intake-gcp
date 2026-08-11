import { describe, it, expect } from "vitest";
import { buildCitationIndex } from "@/lib/research/citationIndex";
import type { Citation } from "@/lib/api/research";

// 22-02 Task 2 — the claim-id -> Citation[] index, pinned property by property.
//
// WHY NAMED TESTS AND NOT ONE TABLE LOOP. Copied deliberately from
// `verificationGate.test.ts`: a future edit that drops the alias half must fail a test whose
// NAME says what was lost — a marker disappearing off a verdict row. A loop over a fixture
// table would go red naming a row index, and the next reader would be free to "fix" it by
// editing the table. The names are the argument; the assertions are only the proof.

/** A minimally valid `Citation`, overridable per test. */
function mk(over: Partial<Citation> = {}): Citation {
  return {
    n: 1,
    source_id: "s1",
    title: "A source",
    publication_date: null,
    quality_tier: 3,
    single_source: false,
    ...over,
  };
}

describe("buildCitationIndex — the primary claim id", () => {
  it("a citation with first_claim_id 'c1' is reachable under key 'c1'", () => {
    const c = mk({ first_claim_id: "c1" });
    const index = buildCitationIndex([c]);
    expect(index.get("c1")).toEqual([c]);
  });

  it("preserves the semantics of the loop it replaces: only the claim's own id becomes a key", () => {
    const c = mk({ first_claim_id: "c1" });
    const index = buildCitationIndex([c]);
    expect([...index.keys()]).toEqual(["c1"]);
  });
});

describe("buildCitationIndex — the aliases (D-22-4: this is what stops a marker being lost)", () => {
  it("NO MARKER LOST: a claim whose only source was absorbed by dedupe still resolves, because also_claim_ids is indexed too", () => {
    const survivor = mk({ n: 4, first_claim_id: "c1", also_claim_ids: ["c2", "c3"] });
    const index = buildCitationIndex([survivor]);
    // c2 and c3 introduced sources the dedupe DROPPED. Keyed strictly on first_claim_id
    // their verdict rows would render no [n] at all — the silent regression D-22-4 names.
    expect(index.get("c2")).toEqual([survivor]);
    expect(index.get("c3")).toEqual([survivor]);
  });

  it("an alias resolves to the SAME object as the primary id, not a copy — one source, one number", () => {
    const survivor = mk({ first_claim_id: "c1", also_claim_ids: ["c2"] });
    const index = buildCitationIndex([survivor]);
    expect(index.get("c2")?.[0]).toBe(index.get("c1")?.[0]);
    expect(index.get("c2")?.[0]).toBe(survivor);
  });

  it("a citation with first_claim_id null but also_claim_ids ['c9'] is still reachable under 'c9'", () => {
    const c = mk({ first_claim_id: null, also_claim_ids: ["c9"] });
    const index = buildCitationIndex([c]);
    expect(index.get("c9")).toEqual([c]);
    expect(index.size).toBe(1);
  });

  it("also_claim_ids undefined behaves exactly like also_claim_ids []", () => {
    const undef = buildCitationIndex([mk({ first_claim_id: "c1", also_claim_ids: undefined })]);
    const empty = buildCitationIndex([mk({ first_claim_id: "c1", also_claim_ids: [] })]);
    expect([...undef.keys()]).toEqual([...empty.keys()]);
    expect(undef.get("c1")).toHaveLength(1);
  });

  it("an id appearing in BOTH first_claim_id and also_claim_ids of the same citation yields it once, not twice", () => {
    const c = mk({ first_claim_id: "c1", also_claim_ids: ["c1", "c2"] });
    const index = buildCitationIndex([c]);
    expect(index.get("c1")).toEqual([c]);
    expect(index.get("c2")).toEqual([c]);
  });

  it("a duplicate id repeated inside also_claim_ids alone yields the citation once", () => {
    const c = mk({ first_claim_id: null, also_claim_ids: ["c7", "c7"] });
    const index = buildCitationIndex([c]);
    expect(index.get("c7")).toEqual([c]);
  });
});

describe("buildCitationIndex — ordering", () => {
  it("two citations sharing one claim id come back in INPUT ORDER under that key", () => {
    const first = mk({ n: 2, source_id: "s2", first_claim_id: "c1" });
    const second = mk({ n: 5, source_id: "s5", first_claim_id: "c1" });
    const index = buildCitationIndex([first, second]);
    expect(index.get("c1")).toEqual([first, second]);
  });

  it("input order holds when the second citation reaches the key through an alias", () => {
    const primary = mk({ n: 1, source_id: "s1", first_claim_id: "c1" });
    const viaAlias = mk({ n: 9, source_id: "s9", first_claim_id: "c8", also_claim_ids: ["c1"] });
    const index = buildCitationIndex([primary, viaAlias]);
    expect(index.get("c1")).toEqual([primary, viaAlias]);
  });
});

describe("buildCitationIndex — malformed input never throws (T-22-04: this is engine-authored JSON)", () => {
  it("a citation with no first_claim_id and no also_claim_ids is skipped and creates no key", () => {
    const index = buildCitationIndex([mk()]);
    expect(index.size).toBe(0);
  });

  it("a non-string id inside also_claim_ids is skipped without throwing", () => {
    const c = mk({
      first_claim_id: null,
      also_claim_ids: [42, null, undefined, { id: "c1" }, "c5"] as unknown as string[],
    });
    let index: Map<string, Citation[]>;
    expect(() => {
      index = buildCitationIndex([c]);
    }).not.toThrow();
    index = buildCitationIndex([c]);
    expect([...index.keys()]).toEqual(["c5"]);
  });

  it("an empty-string id is not a claim id and creates no key", () => {
    const c = mk({ first_claim_id: "", also_claim_ids: ["", "c6"] });
    const index = buildCitationIndex([c]);
    expect([...index.keys()]).toEqual(["c6"]);
  });

  it("also_claim_ids arriving as a non-array is tolerated without throwing", () => {
    const c = mk({ first_claim_id: "c1", also_claim_ids: "c2" as unknown as string[] });
    expect(() => buildCitationIndex([c])).not.toThrow();
    expect(buildCitationIndex([c]).get("c1")).toEqual([c]);
  });
});

describe("buildCitationIndex — the empty cases", () => {
  it("buildCitationIndex(undefined) returns an empty Map", () => {
    const index = buildCitationIndex(undefined);
    expect(index.size).toBe(0);
  });

  it("buildCitationIndex([]) returns an empty Map", () => {
    const index = buildCitationIndex([]);
    expect(index.size).toBe(0);
  });
});
