// Tally Ã¢ÂÂ Supabase intake-webhook (DB-driven mapping)
// Generic over alle Tally forms; configuratie staat in tally_form_mappings,
// tally_field_mappings en tally_option_mappings.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
);

const SECRET =
  Deno.env.get("TALLY_WEBHOOK_SECRET") ??
  Deno.env.get("INTAKE_WEBHOOK_SECRET") ??
  "";

type TallyField = {
  key: string;
  label: string;
  type: string;
  value: unknown;
  options?: Array<{ id: string; text: string }>;
};

type TallyPayload = {
  eventId: string;
  eventType: string;
  createdAt: string;
  data: {
    responseId: string;
    submissionId?: string;
    respondentId?: string;
    formId: string;
    formName?: string;
    fields: TallyField[];
  };
};

function stripQuestionPrefix(key: string): string {
  return key.replace(/^question_/, "");
}

function resolveOptionsToText(field: TallyField): unknown {
  if (Array.isArray(field.value)) {
    return field.value.map((v) => {
      if (field.options) {
        const opt = field.options.find((o) => o.id === v);
        return opt?.text ?? v;
      }
      return v;
    });
  }
  if (typeof field.value === "string" && field.options) {
    const opt = field.options.find((o) => o.id === field.value);
    if (opt) return opt.text;
  }
  return field.value;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

  const provided =
    req.headers.get("x-webhook-secret") ??
    new URL(req.url).searchParams.get("secret") ??
    "";
  if (!SECRET || provided !== SECRET) return new Response("Unauthorized", { status: 401 });

  let payload: TallyPayload;
  try { payload = await req.json() as TallyPayload; }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  if (payload.eventType !== "FORM_RESPONSE") {
    return new Response(JSON.stringify({ ignored: payload.eventType }), {
      headers: { "content-type": "application/json" }
    });
  }

  const formId = payload.data.formId;
  if (!formId) return new Response("Missing formId", { status: 400 });

  // 1. Load mapping configuration uit DB
  const [{ data: formMapping }, { data: fieldMaps }, { data: optionMaps }] = await Promise.all([
    supabase.from("tally_form_mappings")
      .select("tally_form_id, template_slug, template_version")
      .eq("tally_form_id", formId).maybeSingle(),
    supabase.from("tally_field_mappings")
      .select("tally_field_id, field_key, is_hidden")
      .eq("tally_form_id", formId),
    supabase.from("tally_option_mappings")
      .select("field_key, option_label, option_value")
      .eq("tally_form_id", formId)
  ]);

  if (!formMapping) {
    return new Response(
      JSON.stringify({ error: "Form not registered in tally_form_mappings", formId }),
      { status: 404, headers: { "content-type": "application/json" } }
    );
  }

  const fieldMap = new Map<string, { fieldKey: string; isHidden: boolean }>();
  for (const fm of fieldMaps ?? []) {
    fieldMap.set(fm.tally_field_id, { fieldKey: fm.field_key, isHidden: fm.is_hidden });
  }

  // option label Ã¢ÂÂ value-code, gegroepeerd per field_key
  const optionMap = new Map<string, Map<string, string>>();
  for (const om of optionMaps ?? []) {
    if (!optionMap.has(om.field_key)) optionMap.set(om.field_key, new Map());
    optionMap.get(om.field_key)!.set(om.option_label, om.option_value);
  }

  // 2. Resolve elk field uit TallyÃ¢ÂÂs payload
  type Resolved = { fieldKey: string; value: unknown; isHidden: boolean };
  const resolved: Resolved[] = [];

  for (const f of payload.data.fields) {
    if (f.value === null || f.value === undefined || f.value === "") continue;

    // Strip prefix; voor multi-key (zoals OPWQ2A_<uuid> of 4kga6o_<uuid>) probeer we eerst exact, dan eerste segment
    const stripped = stripQuestionPrefix(f.key);
    const parts = stripped.split("_");
    const candidate = parts[0]; // bv "OPWQ2A" of "4kga6o" of "Vlkpel"

    // Skip checkbox-individual booleans: hebben prefix matchend met een veld + extra suffix
    if (parts.length > 1 && fieldMap.has(candidate)) {
      const m = fieldMap.get(candidate)!;
      // Als het de hidden field is (intake_id) gebruiken we de waarde direct
      if (m.isHidden) {
        resolved.push({ fieldKey: m.fieldKey, value: f.value, isHidden: true });
      }
      // Anders: checkbox-individual booleans Ã¢ÂÂ negeren (aggregate field-key heeft de array al)
      continue;
    }

    // Normale top-level field
    const m = fieldMap.get(candidate);
    if (!m) continue; // unknown field, skip

    if (m.isHidden) {
      resolved.push({ fieldKey: m.fieldKey, value: f.value, isHidden: true });
      continue;
    }

    const text = resolveOptionsToText(f);

    // Single-choice unwrap: array van 1 element Ã¢ÂÂ scalar (behalve voor checkboxes)
    let v: unknown = text;
    const isMulti = f.type === "CHECKBOXES" || f.type === "MULTI_SELECT";
    if (Array.isArray(v) && v.length === 1 && !isMulti) v = v[0];

    // Translate via option-map
    const omap = optionMap.get(m.fieldKey);
    if (omap) {
      if (Array.isArray(v)) {
        v = v.map((x) => (typeof x === "string" && omap.get(x)) ? omap.get(x)! : x);
      } else if (typeof v === "string" && omap.has(v)) {
        v = omap.get(v)!;
      }
    }

    resolved.push({ fieldKey: m.fieldKey, value: v, isHidden: false });
  }

  // 3. intake_id ophalen
  const intakeIdRow = resolved.find((r) => r.fieldKey === "intake_id");
  const intakeId =
    (intakeIdRow?.value as string | undefined) ??
    new URL(req.url).searchParams.get("intake_id") ?? undefined;

  if (!intakeId) {
    return new Response(
      JSON.stringify({ error: "Missing intake_id" }),
      { status: 400, headers: { "content-type": "application/json" } }
    );
  }

  const { data: intake, error: intakeErr } = await supabase
    .from("intakes").select("id").eq("id", intakeId).single();
  if (intakeErr || !intake) {
    return new Response(`Intake not found: ${intakeId}`, { status: 404 });
  }

  // 4. Idempotency via responseId == invitation_token
  const responseId = payload.data.responseId ?? payload.data.submissionId;
  if (responseId) {
    const { data: existing } = await supabase
      .from("intake_respondents")
      .select("id").eq("invitation_token", responseId).maybeSingle();
    if (existing) {
      return new Response(JSON.stringify({
        ok: true, status: "already_processed",
        respondent_id: existing.id, response_id: responseId
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
  }

  // 5. Insert respondent + answers
  const answers = resolved.filter((r) => !r.isHidden);
  const companyRoleAns = answers.find((a) => a.fieldKey === "company_role");
  const domainAns = answers.find((a) => a.fieldKey === "domain");

  const { data: respondent, error: respErr } = await supabase
    .from("intake_respondents")
    .insert({
      intake_id: intakeId,
      display_name: (companyRoleAns?.value as string) ?? null,
      domain: (domainAns?.value as string) ?? null,
      is_anonymous: false,
      completed_at: new Date().toISOString(),
      invitation_token: responseId ?? null
    })
    .select("id").single();

  if (respErr || !respondent) {
    return new Response(`Respondent insert failed: ${respErr?.message}`, { status: 500 });
  }

  if (answers.length > 0) {
    const rows = answers.map((a) => ({
      intake_id: intakeId,
      respondent_id: respondent.id,
      field_key: a.fieldKey,
      value: a.value,
      extracted_by: "human" as const
    }));
    const { error: ansErr } = await supabase.from("intake_answers").insert(rows);
    if (ansErr) return new Response(`Answers insert failed: ${ansErr.message}`, { status: 500 });
  }

  return new Response(
    JSON.stringify({
      ok: true,
      template_slug: formMapping.template_slug,
      intake_id: intakeId,
      respondent_id: respondent.id,
      answers_inserted: answers.length
    }),
    { status: 200, headers: { "content-type": "application/json" } }
  );
});
