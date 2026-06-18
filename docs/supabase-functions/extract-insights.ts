// extract-insights
// Roept Claude (Anthropic API) aan om insights te extraheren uit een intake:
//   pain_point, goal, stakeholder, budget_signal, urgency_trigger,
//   tool_mention, competitor, sector_trend, blind_spot, opportunity,
//   risk, quote, aha_moment.
// Schrijft naar extracted_insights met confidence + supporting_text + source_*_id.
//
// Required env: ANTHROPIC_API_KEY
// Invocation: POST { "intake_id": "uuid" }

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
);

const ANTHROPIC_API_KEY = Deno.env.get("ANTHROPIC_API_KEY") ?? "";
const MODEL = "claude-sonnet-4-6";

const INSIGHT_KINDS = [
  "pain_point", "goal", "stakeholder", "budget_signal", "urgency_trigger",
  "tool_mention", "competitor", "sector_trend", "blind_spot", "opportunity",
  "risk", "quote", "aha_moment"
] as const;

type InsightKind = typeof INSIGHT_KINDS[number];

type ExtractedInsight = {
  kind: InsightKind;
  label: string;
  summary: string;
  confidence: number;
  supporting_text: string;
  source_chunk_id?: string;
  source_answer_id?: string;
};

async function loadIntakeContext(intakeId: string) {
  const [intake, transcripts, answers, client] = await Promise.all([
    supabase.from("intakes")
      .select("id, kind, language, summary, intake_templates(name, schema)")
      .eq("id", intakeId).single(),
    supabase.from("transcripts")
      .select("id, chunk_index, speaker, text")
      .eq("intake_id", intakeId).order("chunk_index"),
    supabase.from("intake_answers")
      .select("id, field_key, value, respondent_id")
      .eq("intake_id", intakeId),
    supabase.from("intakes")
      .select("clients(name, industry, sectors)")
      .eq("id", intakeId).single()
  ]);
  return {
    intake: intake.data,
    transcripts: transcripts.data ?? [],
    answers: answers.data ?? [],
    client: (client.data as { clients?: Record<string, unknown> })?.clients ?? null
  };
}

function valueText(v: unknown): string {
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.join(", ");
  return JSON.stringify(v);
}

function buildPrompt(ctx: Awaited<ReturnType<typeof loadIntakeContext>>): string {
  const lines: string[] = [];
  lines.push(`# Klantcontext`);
  if (ctx.client) {
    lines.push(`Klant: ${(ctx.client as { name?: string }).name ?? "?"}`);
    lines.push(`Industry: ${(ctx.client as { industry?: string }).industry ?? "?"}`);
  }
  const tpl = (ctx.intake as { intake_templates?: { name?: string } })?.intake_templates;
  if (tpl) lines.push(`Template: ${tpl.name}`);
  lines.push("");
  lines.push(`# Antwoorden uit de intake`);
  for (const a of ctx.answers) {
    lines.push(`[answer:${a.id}] ${a.field_key}: ${valueText(a.value)}`);
  }
  if (ctx.transcripts.length > 0) {
    lines.push("");
    lines.push(`# Transcript chunks`);
    for (const t of ctx.transcripts) {
      lines.push(`[chunk:${t.id}${t.speaker ? ` (${t.speaker})` : ""}] ${t.text}`);
    }
  }
  return lines.join("\n");
}

async function callClaude(systemPrompt: string, userPrompt: string): Promise<ExtractedInsight[]> {
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json"
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 4096,
      system: systemPrompt,
      messages: [{ role: "user", content: userPrompt }]
    })
  });
  if (!resp.ok) {
    throw new Error(`Anthropic ${resp.status}: ${await resp.text()}`);
  }
  const json = await resp.json();
  const text = json.content?.[0]?.text ?? "";
  // Verwacht JSON array tussen ```json fences
  const match = text.match(/```json\s*([\s\S]*?)\s*```/) ?? text.match(/(\[[\s\S]*\])/);
  if (!match) {
    throw new Error(`No JSON in Claude response: ${text.slice(0, 300)}`);
  }
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

  let body: { intake_id?: string };
  try { body = await req.json(); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  if (!body.intake_id) {
    return new Response("Missing intake_id", { status: 400 });
  }

  try {
    const ctx = await loadIntakeContext(body.intake_id);
    if (!ctx.intake) return new Response("Intake not found", { status: 404 });

    const userPrompt = buildPrompt(ctx);
    const systemPrompt = [
      "Je bent een strategisch consultant voor Agenic, een AI-consultancy.",
      "Je analyseert intake-data van een klant en haalt de scherpste, meest bruikbare insights eruit.",
      "Geen middelmatige observaties Ã¢ÂÂ alleen wat strategisch verschil maakt.",
      "",
      "Voor elke insight: kind (uit lijst), korte label, 1-2 zin summary, confidence 0-1,",
      "supporting_text (letterlijk citaat als beschikbaar), en source_chunk_id of source_answer_id.",
      "",
      `Geldige kinds: ${INSIGHT_KINDS.join(", ")}.`,
      "",
      "Output: JSON array, gewikkeld in ```json ... ```. Geen prose voor of na.",
      "Voorbeeld:",
      '[{"kind":"pain_point","label":"Manuele rapportage","summary":"Marketing team verliest 8u/week aan handmatige rapportages.","confidence":0.85,"supporting_text":"...","source_answer_id":"abc-123"}]'
    ].join("\n");

    const insights = await callClaude(systemPrompt, userPrompt);

    const rows = insights.map((i) => ({
      intake_id: body.intake_id!,
      kind: i.kind,
      label: i.label,
      summary: i.summary,
      confidence: i.confidence,
      supporting_text: i.supporting_text ?? null,
      source_chunk_id: i.source_chunk_id ?? null,
      source_answer_id: i.source_answer_id ?? null,
      llm_model: MODEL
    }));

    if (rows.length === 0) {
      return new Response(JSON.stringify({ ok: true, intake_id: body.intake_id, inserted: 0 }), {
        headers: { "content-type": "application/json" }
      });
    }

    const { error } = await supabase.from("extracted_insights").insert(rows);
    if (error) throw error;

    return new Response(
      JSON.stringify({
        ok: true,
        intake_id: body.intake_id,
        inserted: rows.length,
        kinds: rows.reduce((acc: Record<string, number>, r) => {
          acc[r.kind] = (acc[r.kind] ?? 0) + 1;
          return acc;
        }, {})
      }),
      { headers: { "content-type": "application/json" } }
    );
  } catch (e) {
    return new Response(
      JSON.stringify({ error: (e as Error).message }),
      { status: 500, headers: { "content-type": "application/json" } }
    );
  }
});
