// Supabase Edge Function: apply-intake-skill v2 Ã¢ÂÂ structured JSON output

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const ANTHROPIC_API_KEY = Deno.env.get("ANTHROPIC_API_KEY")!;
const CLAUDE_MODEL = "claude-sonnet-4-5";

const NESTOR_INTAKE_SKILL_PROMPT = `Je bent de Nestor Intake Decomposer. Je principes:

- Scherpte boven volledigheid. Max 5 kernvragen, liever 3 scherpe.
- Aantal kernvragen volgt de intake Ã¢ÂÂ niet meer toevoegen om aan 5 te komen.
- Decision vs exploration. Elke vraag krijgt een type-label.
- Opties isoleren bij decision-vragen.
- Impliciete aannames opgraven.
- Best effort + gaps flaggen.
- Counter-bias bij intake.
- Blinde vlekken in 3 axes: Upstream, Downstream, Perspectief.
- 5 extra vragen zijn een gift, geen padding. Liever 2 goede dan 5 brave.
- Niet braaf zijn. Slechte vraag? Zeg dat en herformuleer.

De 4 Nestor domeinen (strikte filter):
- competitor (Competitor Intelligence)
- customer (Customer Insight)
- trend (Trend Spotting)
- positioning (Positioning Strategy)

Elke kandidaat-vraag moet binnen 1 domein passen. Anders herformuleren of schrappen.

Je output is STRIKT JSON in dit formaat (geen markdown wrapper, geen uitleg eromheen, alleen het JSON-object):

{
  "decision_or_goal": {
    "current": "de huidige waarde uit intake",
    "suggested": "jouw scherpere herformulering (1-2 zinnen)",
    "rationale": "waarom de herformulering beter is"
  } OR null als geen verandering nodig,
  
  "audience_description": { current, suggested, rationale } OR null,
  "company_intro": { current, suggested, rationale } OR null,
  
  "research_questions_refined": [
    {
      "original_index": 0 (0-based index in originele questions array),
      "current": "originele vraag",
      "suggested": "jouw scherpere herformulering",
      "type": "decision" of "exploration",
      "domain": "competitor" of "customer" of "trend" of "positioning",
      "rationale": "waarom deze framing"
    }
  ],
  
  "additional_questions": [
    {
      "text": "voorgestelde extra vraag",
      "rationale": "waarom relevant Ã¢ÂÂ wat kan dit openbreken"
    }
  ] (max 5 items, liever minder en scherp),
  
  "dropped_questions": [
    {
      "original": "vraag uit intake die niet past",
      "reason": "waarom geschrapt Ã¢ÂÂ bv. 'valt buiten Nestor-scope, hoort bij product-team'"
    }
  ] (alleen als van toepassing),
  
  "bias_radar": "markdown tekst Ã¢ÂÂ gedetecteerde voorkeursrichting + voorgestelde opposition-vraag",
  
  "blind_spots": {
    "upstream": "markdown bullets Ã¢ÂÂ oorzaken/inputs die de uitkomst bepalen maar niet bevraagd worden",
    "downstream": "markdown bullets Ã¢ÂÂ gevolgen/tweede-orde-effecten",
    "perspectief": "markdown bullets Ã¢ÂÂ stakeholders wiens blik ontbreekt"
  },
  
  "gaps_flagged": "markdown tekst Ã¢ÂÂ wat ontbreekt in de intake (scope, deadline, budget, etc.)"
}

ALLES is optioneel: als een suggestie niet meerwaarde biedt, return null voor dat veld. Verzin geen suggesties die niet scherper zijn dan het origineel.

Return UITSLUITEND het JSON-object. Geen ingeleidende tekst, geen markdown code-blocks, geen uitleg achteraf.`;

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function formatIntakeAsMarkdown(intake: any, client: any, template: any, answers: Record<string, any>): string {
  const sections = template?.schema?.sections ?? [];
  let md = `# Intake Ã¢ÂÂ ${client?.name ?? "(onbekende klant)"}\n\n`;
  md += `**Klantnaam**: ${client?.name ?? ""}\n`;
  md += `**Projectnaam (intake-titel)**: ${intake?.title ?? ""}\n`;
  md += `**Product**: ${intake?.product_slug ?? ""}\n\n---\n\n`;

  for (const section of sections) {
    if (section.id === "nda") continue;
    if (section.phase === "validation") continue; // skip validation-only sections
    md += `## ${section.title}\n`;
    if (section.description) md += `*${section.description}*\n\n`;

    for (const field of section.fields ?? []) {
      const value = answers[field.key];
      if (value === undefined || value === null || value === "") continue;
      if (field.type === "download") continue;

      md += `**${field.label ?? field.key}**: `;

      if (field.type === "list" && Array.isArray(value)) {
        md += "\n";
        for (let i = 0; i < value.length; i++) {
          const item = value[i];
          if (typeof item === "string") {
            md += `  ${i}. ${item}\n`;
          } else if (typeof item === "object") {
            md += `  ${i}. ${JSON.stringify(item)}\n`;
          }
        }
      } else if (field.type === "radio" && typeof value === "object") {
        md += `${value.choice}${value.text ? ` (${value.text})` : ""}\n`;
      } else if (field.type === "file" || field.type === "files") {
        md += `[bestand(en) geuploaded]\n`;
      } else if (typeof value === "object") {
        md += `${JSON.stringify(value)}\n`;
      } else {
        md += `${value}\n`;
      }
    }
    md += "\n";
  }

  return md;
}

function estimateCostUsd(inputTokens: number, outputTokens: number): number {
  const inputCost = (inputTokens / 1_000_000) * 3;
  const outputCost = (outputTokens / 1_000_000) * 15;
  return Number((inputCost + outputCost).toFixed(4));
}

function extractJson(text: string): any {
  // Strip code-block wrappers if present
  let cleaned = text.trim();
  cleaned = cleaned.replace(/^```json\s*/i, "").replace(/^```\s*/, "").replace(/```\s*$/, "").trim();
  // Find first { and last }
  const start = cleaned.indexOf("{");
  const end = cleaned.lastIndexOf("}");
  if (start === -1 || end === -1) {
    throw new Error("No JSON object found in Claude output");
  }
  const jsonStr = cleaned.substring(start, end + 1);
  return JSON.parse(jsonStr);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  let runId: string | null = null;
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

  try {
    const body = await req.json();
    const { intake_id, skill_name = "nestor-intake" } = body;

    if (!intake_id) {
      throw new Error("Missing intake_id in request body");
    }

    const { data: runRow, error: runErr } = await supabase
      .schema("nestor")
      .from("skill_runs")
      .insert({
        intake_id,
        skill_name,
        skill_version: "v2",
        status: "running",
        prompt_system: NESTOR_INTAKE_SKILL_PROMPT,
        model: CLAUDE_MODEL,
      })
      .select("id")
      .single();

    if (runErr) throw runErr;
    runId = runRow.id;

    const { data: intake, error: intakeErr } = await supabase
      .schema("nestor")
      .from("intakes")
      .select(`id, title, product_slug, template_id, client_id, template:intake_templates!intakes_template_id_fkey(id, name, version, schema)`)
      .eq("id", intake_id)
      .single();

    if (intakeErr) throw intakeErr;

    const { data: client, error: clientErr } = await supabase
      .from("clients")
      .select("id, name, country, website, industry")
      .eq("id", intake.client_id)
      .single();

    if (clientErr) throw clientErr;

    const { data: answersRows, error: answersErr } = await supabase
      .schema("nestor")
      .from("intake_answers")
      .select("field_key, value")
      .eq("intake_id", intake_id);

    if (answersErr) throw answersErr;

    const answers: Record<string, any> = {};
    for (const r of answersRows) answers[r.field_key] = r.value;

    const userMessage = formatIntakeAsMarkdown(intake, client, intake.template, answers);

    await supabase.schema("nestor").from("skill_runs").update({ prompt_user: userMessage }).eq("id", runId);

    const anthropicRes = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: CLAUDE_MODEL,
        max_tokens: 8192,
        system: NESTOR_INTAKE_SKILL_PROMPT,
        messages: [
          {
            role: "user",
            content: `Pas de nestor-intake skill toe op deze intake. Output: STRIKT JSON volgens het schema in de system-prompt. Geen markdown, geen uitleg, alleen het JSON-object.\n\n---\n\n${userMessage}`,
          },
        ],
      }),
    });

    if (!anthropicRes.ok) {
      const errText = await anthropicRes.text();
      throw new Error(`Anthropic API error ${anthropicRes.status}: ${errText}`);
    }

    const anthropicData = await anthropicRes.json();
    const rawOutput = anthropicData.content?.[0]?.text ?? "";
    const usage = anthropicData.usage ?? {};
    const inputTokens = usage.input_tokens ?? 0;
    const outputTokens = usage.output_tokens ?? 0;
    const cost = estimateCostUsd(inputTokens, outputTokens);

    let parsedOutput: any = null;
    let parseError: string | null = null;
    try {
      parsedOutput = extractJson(rawOutput);
    } catch (e) {
      parseError = e instanceof Error ? e.message : String(e);
    }

    await supabase
      .schema("nestor")
      .from("skill_runs")
      .update({
        status: parseError ? "failed" : "succeeded",
        output: rawOutput,
        output_parsed: parsedOutput,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        cost_estimate_usd: cost,
        error_message: parseError,
        completed_at: new Date().toISOString(),
      })
      .eq("id", runId);

    return new Response(
      JSON.stringify({
        success: !parseError,
        run_id: runId,
        output: rawOutput,
        output_parsed: parsedOutput,
        parse_error: parseError,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        cost_estimate_usd: cost,
        model: CLAUDE_MODEL,
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);

    if (runId) {
      await supabase
        .schema("nestor")
        .from("skill_runs")
        .update({
          status: "failed",
          error_message: errorMessage,
          completed_at: new Date().toISOString(),
        })
        .eq("id", runId);
    }

    return new Response(
      JSON.stringify({ success: false, error: errorMessage, run_id: runId }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
