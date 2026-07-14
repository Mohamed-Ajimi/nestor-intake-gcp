// frontend/src/lib/intake-types.ts — the intake domain types.
//
// Phase 11 (i18n): the canonical JSON now carries every display string as a
// LocalizedString (`{ nl, fr?, en? }`) — the SOURCE shape. `localizeSchema`
// (lib/i18n/localizeSchema.ts) flattens the source schema to the RESOLVED scalar
// shape at load time, so FieldRenderer/FieldDisplay/IntakeForm keep reading
// `field.label` etc. as plain strings. nl is the guaranteed fallback (D-05).
//
// - `Localized*` types describe the multi-locale SOURCE served by
//   `GET /intakes/templates` (backend/app/data/pulse_intake_v1.json).
// - The un-prefixed `IntakeField`/`IntakeSection`/`IntakeSchema` types describe the
//   RESOLVED scalar shape every consumer uses after localizeSchema runs.

/** A display string in the source schema: either a plain string (legacy/edge) or a
 * per-locale object. nl is required; fr/en optional and fall back to nl (D-05). */
export type LocalizedString = string | { nl: string; fr?: string; en?: string };

export type ValidationRule = {
  min_length?: number;
  max_length?: number;
  min?: number;
  max?: number;
  pattern?: string;
};

export type FieldType =
  | "text"
  | "longtext"
  | "email"
  | "tel"
  | "date"
  | "select"
  | "radio"
  | "list"
  | "file"
  | "files"
  | "download"
  | "proposal_list"
  | "boolean";

// ---------------------------------------------------------------------------
// RESOLVED scalar shape (post-localizeSchema) — consumed by the form components.
// ---------------------------------------------------------------------------

export type FieldOption = {
  value: string;
  label: string;
  description?: string;
  allow_text?: boolean;
  text_placeholder?: string;
};

export type IntakeField = {
  key: string;
  type: FieldType;
  label: string;
  help?: string;
  placeholder?: string;
  required?: boolean;
  soft_required?: boolean;
  soft_required_message?: string;
  validation?: ValidationRule;
  rows?: number;
  min_length?: number;
  options?: FieldOption[];
  examples?: { good?: string[]; bad?: string[] };
  // list
  min_items?: number;
  max_items?: number;
  item?: IntakeField | { type: "object"; fields: IntakeField[] };
  // file
  storage_bucket?: string;
  storage_path_prefix?: string;
  storage_path?: string;
  display_filename?: string;
  max_files?: number;
  max_size_mb?: number;
  accept?: string[];
};

export type IntakeSection = {
  id: string;
  title: string;
  description?: string;
  soft_gate?: boolean;
  optional?: boolean;
  admin_only?: boolean;
  fields: IntakeField[];
  phase?: "intake" | "validation";
};

export type IntakeSchema = {
  schema_version: string;
  title: string;
  subtitle?: string;
  estimated_minutes?: number;
  save_as_you_go?: boolean;
  sections: IntakeSection[];
  submit: {
    label: string;
    confirmation_title: string;
    confirmation_message: string;
  };
};

// ---------------------------------------------------------------------------
// SOURCE multi-locale shape (as served by GET /intakes/templates).
// Every display string is a LocalizedString; localizeSchema flattens to the
// resolved shape above.
// ---------------------------------------------------------------------------

export type LocalizedFieldOption = {
  value: string;
  label: LocalizedString;
  description?: LocalizedString;
  allow_text?: boolean;
  text_placeholder?: LocalizedString;
};

export type LocalizedIntakeField = {
  key: string;
  type: FieldType;
  label?: LocalizedString;
  help?: LocalizedString;
  placeholder?: LocalizedString;
  required?: boolean;
  soft_required?: boolean;
  soft_required_message?: LocalizedString;
  validation?: ValidationRule;
  rows?: number;
  min_length?: number;
  options?: LocalizedFieldOption[];
  examples?: { good?: string[]; bad?: string[] };
  // list
  min_items?: number;
  max_items?: number;
  item?: LocalizedIntakeField | { type: "object"; fields: LocalizedIntakeField[] };
  // file
  storage_bucket?: string;
  storage_path_prefix?: string;
  storage_path?: string;
  display_filename?: string;
  max_files?: number;
  max_size_mb?: number;
  accept?: string[];
};

export type LocalizedIntakeSection = {
  id: string;
  title: LocalizedString;
  description?: LocalizedString;
  soft_gate?: boolean;
  optional?: boolean;
  admin_only?: boolean;
  fields: LocalizedIntakeField[];
  phase?: "intake" | "validation";
};

export type LocalizedIntakeSchema = {
  schema_version: string;
  title: LocalizedString;
  subtitle?: LocalizedString;
  estimated_minutes?: number;
  save_as_you_go?: boolean;
  sections: LocalizedIntakeSection[];
  submit: {
    label: LocalizedString;
    confirmation_title: LocalizedString;
    confirmation_message: LocalizedString;
  };
};

export type IntakePayload = {
  intake: {
    id: string;
    product_slug: string;
    status: string;
    title: string;
    created_at: string;
    updated_at: string;
  };
  client: { id: string; name: string };
  template: { id: string; name: string; version: number; schema: IntakeSchema };
  answers: Record<string, unknown>;
  editable: boolean;
  phase?: "intake" | "validation";
};
