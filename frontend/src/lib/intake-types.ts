export type FieldOption = {
  value: string;
  label: string;
  description?: string;
  allow_text?: boolean;
};

export type ValidationRule = {
  min_length?: number;
  max_length?: number;
  min?: number;
  max?: number;
  pattern?: string;
};

export type IntakeField = {
  key: string;
  type:
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
    | "proposal_list";
  label: string;
  help?: string;
  placeholder?: string;
  required?: boolean;
  soft_required?: boolean;
  soft_required_message?: string;
  validation?: ValidationRule;
  rows?: number;
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
