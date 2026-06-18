// structure-answers
// Voor interview-intakes: leest een transcript en mapt passages naar de
// template-velden (intake_templates.schema.sections[].fields[]).
// Schrijft naar intake_answers met extracted_by='llm', confidence + source_chunk_id.
//
// Required env: ANTHROPIC_API_KEY
// Invocation: POST { "intake_id": "uuid", "respondent_id": "uuid"? }

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
);

const ANTHROPIC_API_KEY = Deno.env.get("ANTHROPIC_API_KEY") ?? "";
const MODEL = "claude-sonnet-4-6";

type TemplateField = {
  key: string;
  type: string;
  label: string;
  hint?: string;
  options?: Array<{ value: string; label: string }>;
  perspective?: string[];
};

type TemplateSchema = {
  sections: Array<{ key: string; title: string; fields: TemplateField[] }>;
};

function flattenFields(schema: TemplateSchema): TemplateField[] {
  return (schema.sections ?? []).flatMap((s) => s.fields ?? []);
}

async function callClaude(systemPrompt: string, userPrompt: string): Promise<unknown[]> {
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json"
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 8192,
      system: systemPrompt,
      messages: [{ role: "user", content: userPrompt }]
    })
  });
  if (!resp.ok) throw new Error(`Anthropic ${resp.status}: ${await resp.text()}`);
  const json = await resp.json();
  const text = json.content?.[0]?.text ?? "";
  const match = text.match(/```json\s*([\s\S]*?)\s*```/) ?? text.match(/(\[[\s\S]*\])/);
  if (!match) throw new Error(`No JSON in response: ${text.slice(0, 300)}`);
  return JSON.parse(match[1]);
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  if (!ANTHROPIC_API_KEY) {
    return new Response(
      JSON.stringify({ error: "ANTHROPIC_API_KEY not configured" }),
      { status: 503, headers: { "content-type": "application/json" } }
    );
  }

  let body: { intake_id?: string; respondent_id?: string };
  try { body = await req.json(); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  if (!body.intake_id) return new Response("Missing intake_id", { status: 400 });

  const { data: intake, error: intakeErr } = await supabase
    .from("intakes")
    .select("id, language, intake_templates(name, schema)")
    .eq("id", body.intake_id).single();

  if (intakeErr || !intake) return new Response("Intake not found", { status: 404 });

  const tpl = (intake as { intake_templates?: { schema?: TemplateSchema } }).intake_templates;
  const schema = tpl?.schema;
  if (!schema) return new Response("Template schema missing", { status: 500 });

  const fields = flattenFields(schema);

  const { data: chunks } = await supabase
    .from("transcripts")
    .select("id, chunk_index, speaker, text")
    .eq("intake_id", body.intake_id)
    .order("chunk_index");

  if (!chunks || chunks.length === 0) {
    return new Response(
      JSON.stringify({ error: "No transcripts to structure. Run transcribe-audio first." }),
      { status: 400, headers: { "content-type": "application/json" } }
    );
  }

  const transcriptText = chunks.map((c) => `[chunk:${c.id}${c.speaker ? ` (${c.speaker})` : ""}] ${c.text}`).join("\n");

  const systemPrompt = [
    "Je structureert een transcript naar gestructureerde antwoorden volgens een template-schema.",
    "Voor elk veld waarvoor het transcript een antwoord biedt, lever:",
    "  - field_key (uit het schema)",
    "  - value (juiste type: string voor text, value-code uit options voor choice, array voor multi, getal voor scale)",
    "  - confidence 0-1",
    "  - source_chunk_id (de id van de chunk die het antwoord bevat)",
    "",
    "Skip velden waarvoor het transcript geen duidelijk antwoord biedt Ã¢ÂÂ forceer geen invulling.",
    "Output: JSON array gewikkeld in ```json ... ```. Geen prose."
  ].join("\n");

  const userPrompt = [
    `# Template velden`,
    JSON.stringify(fields, null, 2),
    "",
    `# Transcript`,
    transcriptText
  ].join("\n");

  try {
    const extracted = (await callClaude(systemPrompt, userPrompt)) as Array<{
      field_key: string; value: unknown; confidence: number; source_chunk_id?: string;
    }>;

    const validKeys = new Set(fields.map((f) => f.key));
    const validRows = extracted.filter((e) => validKeys.has(e.field_key));

    const rows = validRows.map((e) => ({
      intake_id: body.intake_id!,
      respondent_id: body.respondent_id ?? null,
      field_key: e.field_key,
      value: e.value,
      confidence: e.confidence,
      source_chunk_id: e.source_chunk_id ?? null,
      extracted_by: "llm" as const
    }));

    if (rows.length === 0) {
      return new Response(JSON.stringify({ ok: true, inserted: 0 }), {
        headers: { "content-type": "application/json" }
      });
    }

    const { error } = await supabase.from("intake_answers").insert(rows);
    if (error) throw error;

    return new Response(
      JSON.stringify({ ok: true, intake_id: body.intake_id, inserted: rows.length }),
      { headers: { "content-type": "application/json" } }
    );
  } catch (e) {
    return new Response(
      JSON.stringify({ error: (e as Error).message }),
      { status: 500, headers: { "content-type": "application/json" } }
    );
  }
});
