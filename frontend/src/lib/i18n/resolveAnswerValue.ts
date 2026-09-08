import { pick } from "@/lib/i18n/localizeSchema";

// frontend/src/lib/i18n/resolveAnswerValue.ts — the READ-BOUNDARY resolve pass (DEF-23.2-16).
//
// `localizeSchema` flattens the TEMPLATE's display strings at load time. This is its
// counterpart for the ANSWERS: the intake skill now emits every string it authors as a
// localized `{nl, fr, en}` object, and the AI review panel persists that raw object into
// `answers.value_json`. Every read boundary handed it straight to the renderers, so
// `FieldRenderer`'s `<textarea value={value ?? ""}>` displayed `[object Object]` and
// `FieldDisplay`'s scalar branch did the same via `String(value)`.
//
// Resolving on READ (rather than fixing the write path) is deliberate: it repairs intakes
// that are ALREADY broken in the database, with no migration and no change to how the
// skill output is stored.
//
// WHY THERE IS NO SECOND LOCALE-SELECTION IMPLEMENTATION HERE:
// locale choice is delegated entirely to `pick()` (see its docstring in localizeSchema.ts,
// which is load-bearing). A second resolver would be free to drift on the fallback, and the
// two halves of the same screen would then disagree about which language "no preference"
// means. `pick()`'s restriction to the three locale keys is also the discriminator this
// function depends on: `undefined` means "NOT a localized value", which is what lets a
// stakeholder row `{name, role, email}` and a radio-with-other `{choice, text}` survive
// untouched instead of having one of their fields promoted to the whole answer.
//
// No React, no i18next dependency — a pure transform (mirrors localizeSchema.ts).

/**
 * Resolve any localized text nested anywhere inside an intake answer value.
 *
 * - array          -> every element resolved
 * - localized text -> the scalar variant for `lang` (this is the only rewrite performed)
 * - other object   -> recursed over its values, keys and shape preserved
 * - anything else  -> returned unchanged (string, number, boolean, null, undefined)
 *
 * Recursing over every node is safe precisely because the ONLY rewrite is
 * "localized-text object -> string"; no other node changes type or shape.
 *
 * REFERENCE PRESERVATION: when nothing in a container changed, the ORIGINAL reference is
 * returned. The admin intake page seeds both `initial` and `draft` from this result and
 * diffs them to find edited fields, so rebuilding untouched objects would make every
 * answer read as dirty. The tests assert this with `toBe`, not `toEqual`.
 */
export function resolveAnswerValue(value: unknown, lang: string): unknown {
  // Arrays first, so an array is never handed to `pick()`.
  if (Array.isArray(value)) {
    let changed = false;
    const out = value.map((item) => {
      const resolved = resolveAnswerValue(item, lang);
      if (resolved !== item) changed = true;
      return resolved;
    });
    return changed ? out : value;
  }

  if (typeof value === "object" && value !== null) {
    // Localized text wins over recursion. If an object carried BOTH locale keys and other
    // keys, the whole object resolves to text — a deliberate tie-break, and not a shape we
    // produce: the skill emits a locale object with locale keys only.
    const picked = pick(value, lang);
    if (picked !== undefined) return picked;

    const source = value as Record<string, unknown>;
    let changed = false;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(source)) {
      const resolved = resolveAnswerValue(source[key], lang);
      if (resolved !== source[key]) changed = true;
      out[key] = resolved;
    }
    return changed ? out : value;
  }

  // Strings pass through (`pick()` would too, but this avoids the call), as do numbers,
  // booleans, null and undefined.
  return value;
}
