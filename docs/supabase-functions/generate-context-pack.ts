// Edge Function: generate-context-pack v4 Ã¢ÂÂ v3 + appendix met de 5 onderzoeksvragen verbatim

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const ANTHROPIC_API_KEY = Deno.env.get("ANTHROPIC_API_KEY")!;
const CLAUDE_MODEL = "claude-sonnet-4-5";
const STORAGE_BUCKET = "nestor-uploads";

const CONTEXT_PACK_SKILL_PROMPT = `Je bent de Nestor Context Pack generator. Van een gevalideerde intake maak je een gecondenseerd, scherp context-document dat aan Nestor wordt meegegeven voor research.

Principes:
- Destilleer, niet kopieer. Als de intake 2 pagina's context heeft, kook in tot wat Nestor echt nodig heeft.
- Eerlijke gaps. Als info ontbreekt, schrijf "*nog in te vullen*" in plaats van te bluffen.
- Feiten vs. hypothesen scheiden. Sectie 4 (ankers) = vastliggend. Sectie 7 (hypothesen) = te toetsen.
- Hergebruik voorzien. Schrijf secties 1, 2, 9 zo dat ze herbruikbaar zijn voor vervolgprojecten.
- Schrijf in vloeiend Nederlands, niet in bulletted lijstjes per veld. Maak er prozaÃÂ¯sche, leesbare tekst van Ã¢ÂÂ behalve waar de structuur een lijst vereist (concurrenten, stakeholders).

Output: STRIKT markdown volgens de structuur hieronder. Geen JSON. Geen ingeleidende tekst. Geen uitleg achteraf. Begin direct met de # titel.

# Context Pack Ã¢ÂÂ [klantnaam]

> Systeemcontext voor Nestor. Gelezen voor elke research-run op dit project. Intern werkdocument Ã¢ÂÂ niet voor de klant.

## 1. Klant in een alinea
[max 4 zinnen, geen boilerplate, echte gezichtskenmerken Ã¢ÂÂ wie ze zijn, wat ze doen, in welke markt, wat hun eigenheid is]

## 2. Waarom dit onderzoek nu
[de trigger Ã¢ÂÂ welke druk, welke shift, welk moment. Wat gebeurt er als dit onderzoek er niet zou zijn?]

## 3. De beslissing die eraan hangt
- **Wat moet beslist worden:** [concreet]
- **Door wie:** [naam/rol indien bekend, anders "*nog in te vullen*"]
- **Tegen wanneer:** [deadline + waarom die datum]
- **Alternatieven op tafel:** [A / B / C / niets doen]
- **Kost van niets veranderen:** [wat verliest de klant bij status quo]

## 4. Strategische ankers (frames waarbinnen research moet landen)
[positioneringskeuzes die al vastliggen, randvoorwaarden, commerciÃÂ«le hoofddoelen, tijdshorizonten. FEITEN, geen hypothesen Ã¢ÂÂ expliciet scheiden van sectie 7.]

## 5. Scope & segmentatie
- **Geografisch:** [per vraag indien verschillend]
- **Doelgroep(en):** [segmenten met onderscheidingen]
- **In scope:** [expliciet]
- **Out of scope:** [expliciet Ã¢ÂÂ wat de klant NIET wil dat we aanraken]

## 6. Concurrenten / benchmarkset
[De expliciete lijst van concurrenten die de klant noemt + eventueel door jou aangevulde context-spelers. Per concurrent een korte typering: positie t.o.v. klant (groter/kleiner/equivalent), waarom relevant voor benchmarking, eventuele gevoeligheid (bv. "niet direct contacten voor primary research").]

Indien klant een dataclatste benadering hanteert (bv. "vergelijken met Nederland en Duitsland"), benoem ook die geografische peers expliciet.

Formaat: bullet-lijst, een per concurrent, met inleidende zin per item.

## 7. Wat de klant al gelooft (hypothesen om te stress-testen)
[aannames uit de intake + bias-richtingen. NIET vaststaand. Geef per aanname kort aan waarom ze wankel zou kunnen zijn.]

## 8. Bronnen & data die de klant meebrengt
[interne rapporten, eerdere studies, sales-data, opgenomen gesprekken. Met: hoe recent, onder welke voorwaarden, wie heeft toegang.]

## 9. Stakeholders & gevoeligheden
- **Primair contact klant:** [naam + rol + bereikbaarheid]
- **Decision-maker:** [naam + rol, indien anders dan primair contact]
- **NDA-status:** [getekend / in review / niet nodig]
- **Politieke/commerciÃÂ«le gevoeligheden:** [dingen die niet in het rapport mogen, concurrenten die niet genoemd mogen worden, interne dynamieken]

## 10. Taalregister & output-eisen
- **Hoe praat de klant:** [1-2 directe quotes uit intake Ã¢ÂÂ tonen toon en drempels]
- **Output-omvang (harde constraint):** Compact (8-12 p.) / Standaard (15-25 p.) / Uitgebreid (30-50 p.) / Anders
- **Output-vorm:** Notion / PDF / Deck / Sessie+leave-behind / Anders
- **Specifieke eisen klant:** [expliciete wensen, bv. "geen aan-de-ene-kant-aan-de-andere-kant taal"]

## 11. Bekende blinde vlekken (overgenomen uit intake-skill)
**Upstream:** [factoren buiten de vraag die de uitkomst materieel bepalen]
**Downstream:** [tweede-orde-effecten die Nestor mee moet overwegen]
**Perspectief:** [stakeholders wiens blik niet in de vraag zit maar wel zou moeten]

*(Sectie 12 met de onderzoeksvragen verbatim wordt automatisch toegevoegd Ã¢ÂÂ niet zelf schrijven.)*`;

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function formatIntakeAsMarkdown(intake: any, client: any, template: any, answers: Record<string, any>, latestIntakeSkillRun: any): string {
  const sections = template?.schema?.sections ?? [];
  let md = `# Intake Ã¢ÂÂ ${client?.name ?? ""}\n\n`;
  md += `**Klantnaam**: ${client?.name ?? ""}\n`;
  md += `**Land**: ${client?.country ?? ""}\n`;
  md += `**Industrie**: ${client?.industry ?? ""}\n`;
  md += `**Website**: ${client?.website ?? ""}\n`;
  md += `**Project (intake-titel)**: ${intake?.title ?? ""}\n`;
  md += `**Product**: ${intake?.product_slug ?? ""}\n\n---\n\n`;

  for (const section of sections) {
    if (section.id === "nda") continue;
    md += `## ${section.title}\n`;
    if (section.description) md += `*${section.description}*\n\n`;

    for (const field of section.fields ?? []) {
      const value = answers[field.key];
      if (value === undefined || value === null || value === "") continue;
      if (field.type === "download") continue;

      md += `**${field.label ?? field.key}**: `;

      if (field.type === "list" && Array.isArray(value)) {
        md += "\n";
        for (const item of value) {
          if (typeof item === "string") md += `  - ${item}\n`;
          else if (typeof item === "object") md += `  - ${JSON.stringify(item)}\n`;
        }
      } else if (field.type === "proposal_list" && Array.isArray(value)) {
        md += "\n";
        for (const item of value) {
          if (item.approved) md += `  - [GOEDGEKEURD] ${item.text}${item.rationale ? ` (${item.rationale})` : ""}\n`;
          else md += `  - [niet opgenomen] ${item.text}\n`;
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

  if (latestIntakeSkillRun?.output_parsed) {
    const parsed = latestIntakeSkillRun.output_parsed;
    md += `## Strategische analyse (uit intake-skill)\n\n`;
    if (parsed.bias_radar) md += `**Bias-radar:**\n${parsed.bias_radar}\n\n`;
    if (parsed.blind_spots) {
      md += `**Blinde vlekken:**\n`;
      if (parsed.blind_spots.upstream) md += `- Upstream: ${parsed.blind_spots.upstream}\n`;
      if (parsed.blind_spots.downstream) md += `- Downstream: ${parsed.blind_spots.downstream}\n`;
      if (parsed.blind_spots.perspectief) md += `- Perspectief: ${parsed.blind_spots.perspectief}\n`;
    }
  }

  return md;
}

function estimateCostUsd(inputTokens: number, outputTokens: number): number {
  const inputCost = (inputTokens / 1_000_000) * 3;
  const outputCost = (outputTokens / 1_000_000) * 15;
  return Number((inputCost + outputCost).toFixed(4));
}

async function buildQuestionsAppendix(supabase: any, intake_id: string): Promise<string> {
  // Pak de research_questions in priority ASC volgorde
  const { data: questions } = await supabase
    .schema("nestor")
    .from("research_questions")
    .select("priority, question_type, question_text")
    .eq("intake_id", intake_id)
    .order("priority", { ascending: true });

  if (!questions?.length) return "";

  let md = "\n\n---\n\n## 12. Onderzoeksvragen (verbatim)\n\n";
  md += "_Dit zijn de exacte vragen waarop Nestor antwoord moet geven. Verbatim overgenomen Ã¢ÂÂ niet herformuleerd door Claude._\n\n";
  for (const q of questions) {
    const type = q.question_type ? ` _(${q.question_type})_` : "";
    md += `**V${q.priority}${type}**\n\n${q.question_text}\n\n`;
  }
  return md;
}

async function finalizeContextPack(
  supabase: any,
  intake_id: string,
  runId: string,
  rawOutput: string,
  client: any,
): Promise<{ artifact_id: string; storage_path: string }> {
  const today = new Date().toISOString().split("T")[0];
  const clientSlug = (client?.name ?? "client").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50);
  const filename = `context-pack-${clientSlug}-${today}.md`;
  const storagePath = `context-packs/${intake_id}/${runId}/${filename}`;

  // Append verbatim questions before upload + save
  const questionsAppendix = await buildQuestionsAppendix(supabase, intake_id);
  const fullOutput = rawOutput + questionsAppendix;

  // 1. Storage upload
  const bytes = new TextEncoder().encode(fullOutput);
  const { error: uploadErr } = await supabase.storage
    .from(STORAGE_BUCKET)
    .upload(storagePath, bytes, { contentType: "text/markdown", upsert: true });
  if (uploadErr) throw new Error(`Storage upload failed: ${uploadErr.message}`);

  // 2. research_artifact row
  const { data: artifact, error: artErr } = await supabase
    .schema("nestor")
    .from("research_artifacts")
    .insert({
      intake_id,
      source: "context-pack-generator",
      artifact_type: "note",
      filename,
      storage_bucket: STORAGE_BUCKET,
      storage_path: storagePath,
      mime_type: "text/markdown",
      text_content: fullOutput,
      byte_size: bytes.length,
      embed_status: "pending",
      notes: "Context Pack Ã¢ÂÂ auto-generated briefing voor Nestor onderzoeker (incl. verbatim onderzoeksvragen)",
    })
    .select("id")
    .single();
  if (artErr) throw new Error(`Artifact insert failed: ${artErr.message}`);

  // 3. Link to intake + bump status
  const { error: intakeUpdErr } = await supabase
    .schema("nestor")
    .from("intakes")
    .update({
      context_pack_artifact_id: artifact.id,
      status: "decomposed",
    })
    .eq("id", intake_id);
  if (intakeUpdErr) throw new Error(`Intake update failed: ${intakeUpdErr.message}`);

  // 4. Mark skill_run applied
  await supabase
    .schema("nestor")
    .from("skill_runs")
    .update({ applied_at: new Date().toISOString() })
    .eq("id", runId);

  return { artifact_id: artifact.id, storage_path: storagePath };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

  let runId: string | null = null;
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

  try {
    const body = await req.json();
    const { intake_id } = body;
    if (!intake_id) throw new Error("Missing intake_id");

    // Fetch intake + client (always needed)
    const { data: intake, error: intakeErr } = await supabase
      .schema("nestor")
      .from("intakes")
      .select(`id, title, product_slug, template_id, client_id, context_pack_artifact_id, template:intake_templates!intakes_template_id_fkey(id, name, version, schema)`)
      .eq("id", intake_id)
      .single();
    if (intakeErr) throw intakeErr;

    const { data: client, error: clientErr } = await supabase
      .from("clients")
      .select("id, name, country, website, industry")
      .eq("id", intake.client_id)
      .single();
    if (clientErr) throw clientErr;

    // Already finalized? Return existing.
    if (intake.context_pack_artifact_id) {
      const { data: existingArtifact } = await supabase
        .schema("nestor")
        .from("research_artifacts")
        .select("id, storage_path, filename")
        .eq("id", intake.context_pack_artifact_id)
        .maybeSingle();
      return new Response(JSON.stringify({
        success: true,
        already_finalized: true,
        artifact_id: existingArtifact?.id,
        storage_path: existingArtifact?.storage_path,
        filename: existingArtifact?.filename,
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } });
    }

    // Idempotency: re-use existing succeeded skill_run output if present and not applied
    const { data: existingRun } = await supabase
      .schema("nestor")
      .from("skill_runs")
      .select("id, output, input_tokens, output_tokens, cost_estimate_usd")
      .eq("intake_id", intake_id)
      .eq("skill_name", "context-pack")
      .eq("status", "succeeded")
      .is("applied_at", null)
      .not("output", "is", null)
      .order("completed_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    if (existingRun?.output) {
      runId = existingRun.id;
      const { artifact_id, storage_path } = await finalizeContextPack(
        supabase, intake_id, runId, existingRun.output, client,
      );
      return new Response(JSON.stringify({
        success: true,
        reused_run: true,
        run_id: runId,
        artifact_id,
        storage_path,
        input_tokens: existingRun.input_tokens,
        output_tokens: existingRun.output_tokens,
        cost_estimate_usd: existingRun.cost_estimate_usd,
      }), { headers: { ...corsHeaders, "Content-Type": "application/json" } });
    }

    // No reusable output Ã¢ÂÂ generate from scratch.
    const { data: runRow, error: runErr } = await supabase
      .schema("nestor")
      .from("skill_runs")
      .insert({
        intake_id,
        skill_name: "context-pack",
        skill_version: "v4",
        status: "running",
        prompt_system: CONTEXT_PACK_SKILL_PROMPT,
        model: CLAUDE_MODEL,
      })
      .select("id")
      .single();
    if (runErr) throw runErr;
    runId = runRow.id;

    const { data: answersRows } = await supabase
      .schema("nestor")
      .from("intake_answers")
      .select("field_key, value")
      .eq("intake_id", intake_id);
    const answers: Record<string, any> = {};
    for (const r of answersRows ?? []) answers[r.field_key] = r.value;

    const { data: latestIntakeSkillRun } = await supabase
      .schema("nestor")
      .from("skill_runs")
      .select("output_parsed")
      .eq("intake_id", intake_id)
      .eq("skill_name", "nestor-intake")
      .eq("status", "succeeded")
      .order("completed_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    const userMessage = formatIntakeAsMarkdown(intake, client, intake.template, answers, latestIntakeSkillRun);

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
        system: CONTEXT_PACK_SKILL_PROMPT,
        messages: [{
          role: "user",
          content: `Genereer het Context Pack op basis van deze gevalideerde intake. Output: STRIKT markdown volgens de template. Geen JSON, geen ingeleidende tekst. Sectie 12 (Onderzoeksvragen verbatim) niet zelf schrijven Ã¢ÂÂ die wordt apart toegevoegd.\n\n---\n\n${userMessage}`,
        }],
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

    await supabase.schema("nestor").from("skill_runs").update({
      status: "succeeded",
      output: rawOutput,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      cost_estimate_usd: cost,
      completed_at: new Date().toISOString(),
    }).eq("id", runId);

    const { artifact_id, storage_path } = await finalizeContextPack(
      supabase, intake_id, runId, rawOutput, client,
    );

    return new Response(JSON.stringify({
      success: true,
      reused_run: false,
      run_id: runId,
      artifact_id,
      storage_path,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      cost_estimate_usd: cost,
      model: CLAUDE_MODEL,
    }), { headers: { ...corsHeaders, "Content-Type": "application/json" } });
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    if (runId) {
      await supabase.schema("nestor").from("skill_runs").update({
        status: "failed",
        error_message: errorMessage,
        completed_at: new Date().toISOString(),
      }).eq("id", runId);
    }
    return new Response(JSON.stringify({ success: false, error: errorMessage, run_id: runId }), {
      status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
