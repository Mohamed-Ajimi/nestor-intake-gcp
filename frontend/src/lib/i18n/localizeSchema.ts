import type {
  IntakeField,
  IntakeSchema,
  IntakeSection,
  FieldOption,
  LocalizedFieldOption,
  LocalizedIntakeField,
  LocalizedIntakeSchema,
  LocalizedIntakeSection,
  LocalizedString,
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

/** Resolve a LocalizedString to a scalar for `lang`, with nl as the guaranteed fallback. */
function pick(value: LocalizedString | undefined, lang: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value === "string") return value; // already scalar — passthrough
  const key = lang.slice(0, 2) as "nl" | "fr" | "en";
  // nl is guaranteed present on a locale-object; fr/en optional → fall back to nl (D-05).
  return value[key] ?? value.nl;
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
