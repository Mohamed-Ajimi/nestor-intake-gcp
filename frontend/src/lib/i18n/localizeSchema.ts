import type {
  IntakeField,
  IntakeSchema,
  IntakeSection,
  FieldOption,
  LocalizedFieldOption,
  LocalizedIntakeField,
  LocalizedIntakeSchema,
  LocalizedIntakeSection,
} from "@/lib/intake-types";

// frontend/src/lib/i18n/localizeSchema.ts — the LOAD-TIME flatten pass (Pitfall 4).
//
// `GET /intakes/templates` serves ONE canonical asset whose display strings are
// LocalizedString objects (`{ nl, fr?, en? }`). This pure pass walks the source
// schema and replaces every LocalizedString with the scalar variant for `lang`,
// returning the RESOLVED scalar `IntakeSchema` that FieldRenderer/FieldDisplay/
// IntakeForm already consume. nl is the guaranteed fallback for any missing
// variant, and an already-scalar string passes through unchanged (defensive).
//
// No React, no i18next dependency — a pure transform (mirrors research-question.ts).

/**
 * Resolve a LocalizedString to a scalar for `lang`, with nl as the guaranteed fallback.
 *
 * EXPORTED since quick task 260831-lm4, because it now resolves two kinds of value,
 * not one. It was written for the TEMPLATE's display strings; the intake skill now
 * ALSO emits every string it authors as `{nl, fr, en}`, and those AI-generated values
 * land in the intake ANSWERS. Both need exactly the same rule, so there is exactly one
 * implementation of it — a second resolver would be free to drift on the fallback and
 * the two halves of the same screen would then disagree about which language "no
 * preference" means.
 *
 * `value` is typed `unknown` rather than `LocalizedString` because the answer-side
 * callers genuinely hold unknown data (an old intake's plain string, a new intake's
 * object, or null). Runtime behaviour for a LocalizedString is UNCHANGED.
 */
export function pick(value: unknown, lang: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === "string") return value; // already scalar — passthrough
  if (typeof value !== "object") return undefined;
  const obj = value as Partial<Record<string, unknown>>;
  const key = lang.slice(0, 2);
  // nl is guaranteed present on a locale-object; fr/en optional → fall back to nl (D-05).
  const preferred = obj[key] ?? obj.nl;
  if (typeof preferred === "string") return preferred;
  // Last resort, and ADDITIVE ONLY — it can fire solely where the line above would
  // have returned undefined. A model that dropped a variant must still render TEXT
  // rather than nothing; a template LocalizedString always has nl, so this is
  // unreachable on the schema path.
  //
  // Restricted to the THREE LOCALE KEYS on purpose. Scanning every value would make
  // `pick` return the first string it finds on ANY object — so a stakeholder row
  // `{name, role, email}` would resolve to a name and look like a successful
  // resolution. Callers that hand this function arbitrary answer values (see
  // `FieldDisplay`, which calls `pick(obj[textKey], …)` on raw answer objects) rely on
  // `undefined` meaning "not a localized value".
  for (const localeKey of ["nl", "fr", "en"] as const) {
    const candidate = obj[localeKey];
    if (typeof candidate === "string" && candidate.trim() !== "") return candidate;
  }
  return undefined;
}

function resolveOption(opt: LocalizedFieldOption, lang: string): FieldOption {
  return {
    value: opt.value,
    label: pick(opt.label, lang) ?? "",
    ...(opt.description !== undefined
      ? { description: pick(opt.description, lang) }
      : {}),
    ...(opt.allow_text !== undefined ? { allow_text: opt.allow_text } : {}),
    ...(opt.text_placeholder !== undefined
      ? { text_placeholder: pick(opt.text_placeholder, lang) }
      : {}),
  };
}

function resolveField(field: LocalizedIntakeField, lang: string): IntakeField {
  // Copy every non-display attribute verbatim, then overwrite the display strings.
  const {
    label,
    help,
    placeholder,
    soft_required_message,
    options,
    item,
    ...rest
  } = field;

  const resolved: IntakeField = {
    ...rest,
    label: pick(label, lang) ?? "",
  };

  const resolvedHelp = pick(help, lang);
  if (resolvedHelp !== undefined) resolved.help = resolvedHelp;

  const resolvedPlaceholder = pick(placeholder, lang);
  if (resolvedPlaceholder !== undefined) resolved.placeholder = resolvedPlaceholder;

  const resolvedSoftMsg = pick(soft_required_message, lang);
  if (resolvedSoftMsg !== undefined) resolved.soft_required_message = resolvedSoftMsg;

  if (options) resolved.options = options.map((o) => resolveOption(o, lang));

  if (item) {
    if ("type" in item && item.type === "object") {
      resolved.item = {
        type: "object",
        fields: item.fields.map((f) => resolveField(f, lang)),
      };
    } else {
      resolved.item = resolveField(item as LocalizedIntakeField, lang);
    }
  }

  return resolved;
}

function resolveSection(section: LocalizedIntakeSection, lang: string): IntakeSection {
  const { title, description, fields, ...rest } = section;
  const resolved: IntakeSection = {
    ...rest,
    title: pick(title, lang) ?? "",
    fields: fields.map((f) => resolveField(f, lang)),
  };
  const resolvedDesc = pick(description, lang);
  if (resolvedDesc !== undefined) resolved.description = resolvedDesc;
  return resolved;
}

/**
 * Flatten a multi-locale SOURCE schema to the resolved scalar shape for `lang`.
 * nl is the guaranteed fallback; already-scalar strings pass through unchanged.
 */
export function localizeSchema(
  schema: LocalizedIntakeSchema,
  lang: string,
): IntakeSchema {
  const { title, subtitle, submit, sections, ...rest } = schema;
  const resolved: IntakeSchema = {
    ...rest,
    title: pick(title, lang) ?? "",
    sections: sections.map((s) => resolveSection(s, lang)),
    submit: {
      label: pick(submit.label, lang) ?? "",
      confirmation_title: pick(submit.confirmation_title, lang) ?? "",
      confirmation_message: pick(submit.confirmation_message, lang) ?? "",
    },
  };
  const resolvedSubtitle = pick(subtitle, lang);
  if (resolvedSubtitle !== undefined) resolved.subtitle = resolvedSubtitle;
  return resolved;
}
