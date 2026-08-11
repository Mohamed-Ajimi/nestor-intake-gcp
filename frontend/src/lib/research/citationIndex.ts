// frontend/src/lib/research/citationIndex.ts — the one answer to "which [n] markers belong to
// this verdict row", extracted out of `VerificationReport.tsx` as a pure module so it can be
// measured by real assertions rather than asserted in a comment (22-02, D-22-4). Same reason
// and same shape as `verificationGate.ts`: this repo has no React test harness, so anything
// that lives inside a component is unassertable by construction.

import type { Citation } from "@/lib/api/research";

/**
 * Index a run's citation list by claim id, so a verdict row can ask for exactly its own
 * `[n]` markers.
 *
 * WHY THE ALIAS HALF EXISTS. The engine's read-time dedupe (D-22-4) emits ONE citation entry
 * per normalized source URL and DROPS the rest. A dropped entry took its `first_claim_id`
 * with it — so a verdict row whose claim introduced only that source would resolve to nothing
 * and render no `[n]` at all. That is not a cosmetic loss: it is a silent regression on a row
 * that carries a marker today, and it is invisible precisely because a missing marker looks
 * like a claim that never had a citation. `also_claim_ids` carries those absorbed claim ids
 * onto the survivor, and THIS INDEX IS WHERE THEY ARE HONOURED. Keying strictly on
 * `first_claim_id` — which is what the code this replaces did — is the defect.
 *
 * WHAT THIS MODULE IS NOT: **it does no dedupe and no URL handling whatsoever.** The list
 * arriving here is ALREADY deduped, by the engine, at `verification/report.py`. D-22-4
 * requires ONE shared normalization function, and a TypeScript function cannot be shared with
 * the Python `INSERT` that the write-side fix has to change — so a `normalizeUrl` appearing in
 * this file would be the defect, not the fix. It would also guarantee that read and write
 * disagree about source identity, which is the exact bug being closed, reintroduced one level
 * down.
 *
 * NOR DOES IT RENUMBER. Nothing here reads, assigns or reorders `citation.n`. The deliverable
 * markdown has `[n]` BAKED IN at synthesis (`apply_citation_anchors`) and frozen; renumbering
 * on the read side would desynchronise the page from that frozen document. A sparse rendered
 * sequence (1, 2, 4, 7, …) is the correct cost of dedupe, not a defect to tidy away.
 *
 * Defensive by requirement (T-22-04): `also_claim_ids` is engine-authored JSON crossing the
 * API → browser boundary, so every candidate id is type-checked before use and no input shape
 * can make this throw. Ids are only ever taken from a citation's OWN `first_claim_id` /
 * `also_claim_ids`, never derived from anything else, so a marker can never surface a citation
 * belonging to another claim (T-22-05).
 *
 * Pure: no React, no fetch, no side effects. Citations under a key are in INPUT ORDER, and a
 * citation appears at most once per key even if the same id reaches it twice.
 *
 * @param citations The run's citation list, or `undefined` before it has loaded.
 * @returns A Map from claim id to the citations introduced by that claim. Never `null`.
 */
export function buildCitationIndex(citations: Citation[] | undefined): Map<string, Citation[]> {
  const index = new Map<string, Citation[]>();
  if (!Array.isArray(citations)) return index;

  for (const c of citations) {
    if (!c) continue;

    // A non-array `also_claim_ids` is a wire shape we tolerate rather than trust.
    const aliases = Array.isArray(c.also_claim_ids) ? c.also_claim_ids : [];
    // Scoped to THIS citation: an id repeated within one entry must not push the same
    // object onto a key twice.
    const seen = new Set<string>();

    for (const candidate of [c.first_claim_id, ...aliases]) {
      if (typeof candidate !== "string" || candidate === "") continue;
      if (seen.has(candidate)) continue;
      seen.add(candidate);

      const list = index.get(candidate);
      if (list) {
        list.push(c);
      } else {
        index.set(candidate, [c]);
      }
    }
  }

  return index;
}
