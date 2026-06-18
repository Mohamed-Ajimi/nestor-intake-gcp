import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import Anthropic from "https://esm.sh/@anthropic-ai/sdk@0.27.0";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const METHOD_OVERRIDE: Record<string, string> = {
  meddpicc: "MEDDPICC Ã¢ÂÂ Metrics, Economic buyer, Decision criteria, Decision process, Paper process, Identify pain, Champion, Competition",
  spin: "SPIN Ã¢ÂÂ Situation, Problem, Implication, Need-payoff",
  challenger: "Challenger Ã¢ÂÂ Teach, Tailor, Take control",
  voss: "Voss / Tactical Empathy Ã¢ÂÂ Mirror, Label, Calibrated questions",
  pre_suasion: "Pre-Suasion (Cialdini) Ã¢ÂÂ Frame-setting via influence-principes",
};

const MEETING_TYPE_GUIDANCE: Record<string, string> = {
  discovery: "Focus op blok 4 + blok 6 (Situation + Problem).",
  demo: "Focus op blok 3, 5, en 7.",
  follow_up: "Focus op blok 8 + blok 4 verfijnd.",
  executive_pitch: "Focus op blok 1, 3, en 8.",
  renewal: "Focus op blok 2, 7 (churn-risk) en 8.",
  win_back: "Focus op blok 4, 7 en 5 (warme opener).",
};
const DEAL_STAGE_GUIDANCE: Record<string, string> = {
  new: "MEDDPICC: Identify Pain, Champion. SPIN: Situation + Problem.",
  qualified: "MEDDPICC: Metrics, Decision Criteria. SPIN: Problem + Implication.",
  proposal: "MEDDPICC: Economic Buyer, Paper Process. SPIN: Implication + Need-payoff.",
  negotiation: "MEDDPICC: Competition, Paper Process. Objections krijgt diepte.",
  decision: "MEDDPICC: alle 8 geverifieerd. Next-step = commitment.",
};
const KLANT_TYPE_GUIDANCE: Record<string, string> = {
  new_client: "Tonalty: positionering, vertrouwen, eerste indruk.",
  existing_client: "Tonalty: relatie verdiepen, expansion, retention.",
};

// ============================================================
// WEB-SEARCH HELPERS (alle returnen { provider, query, results, error? })
// ============================================================

async function searchSerpApi(query: string, timeWindow: string | null = null, timeoutMs = 30000): Promise<any> {
  const apiKey = Deno.env.get("SERPAPI_API_KEY");
  if (!apiKey) return { provider: "serpapi", query, error: "no_key", results: [] };
  if (!query?.trim()) return { provider: "serpapi", query, error: "empty_query", results: [] };

  const params = new URLSearchParams({
    api_key: apiKey, engine: "google", q: query,
    num: "10", hl: "nl", gl: "be",
  });
  if (timeWindow) params.set("tbs", timeWindow);

  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const resp = await fetch(`https://serpapi.com/search?${params}`, { signal: ctrl.signal });
    clearTimeout(t);
    if (!resp.ok) return { provider: "serpapi", query, error: `HTTP ${resp.status}`, results: [] };
    const data = await resp.json();
    const results: any[] = [];
    for (const r of (data.organic_results || []).slice(0, 8)) {
      results.push({ title: r.title, url: r.link, snippet: r.snippet, date: r.date, source: "organic" });
    }
    for (const r of (data.news_results || []).slice(0, 5)) {
      results.push({ title: r.title, url: r.link, snippet: r.snippet, date: r.date, source: "news" });
    }
    if (data.answer_box?.snippet) {
      results.unshift({ title: "Answer Box", url: data.answer_box.link, snippet: data.answer_box.snippet, source: "answer_box" });
    }
    return { provider: "serpapi", query, results, time_window: timeWindow };
  } catch (err: any) {
    return { provider: "serpapi", query, error: err.message, results: [] };
  }
}

async function searchSearchApi(query: string, timeoutMs = 30000): Promise<any> {
  const apiKey = Deno.env.get("SEARCHAPI_API_KEY");
  if (!apiKey) return { provider: "searchapi", query, error: "no_key", results: [] };
  if (!query?.trim()) return { provider: "searchapi", query, error: "empty_query", results: [] };

  const params = new URLSearchParams({
    api_key: apiKey, engine: "google", q: query,
    num: "10", hl: "nl", gl: "be",
  });
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const resp = await fetch(`https://www.searchapi.io/api/v1/search?${params}`, { signal: ctrl.signal });
    clearTimeout(t);
    if (!resp.ok) return { provider: "searchapi", query, error: `HTTP ${resp.status}`, results: [] };
    const data = await resp.json();
    const results: any[] = [];
    for (const r of (data.organic_results || []).slice(0, 8)) {
      results.push({ title: r.title, url: r.link, snippet: r.snippet, source: "organic" });
    }
    return { provider: "searchapi", query, results };
  } catch (err: any) {
    return { provider: "searchapi", query, error: err.message, results: [] };
  }
}

async function scrapeLinkedInProfile(url: string, timeoutMs = 120000): Promise<any> {
  const apiKey = Deno.env.get("APIFY_API_TOKEN");
  if (!apiKey) return { provider: "apify", query: url, error: "no_key", results: [] };
  if (!url?.trim()) return { provider: "apify", query: url, error: "empty_url", results: [] };

  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const resp = await fetch(
      `https://api.apify.com/v2/acts/harvestapi~linkedin-profile-scraper/run-sync-get-dataset-items?token=${apiKey}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profileUrls: [url] }),
        signal: ctrl.signal,
      }
    );
    clearTimeout(t);
    if (!resp.ok) {
      const txt = await resp.text();
      return { provider: "apify", query: url, error: `HTTP ${resp.status}: ${txt.slice(0, 200)}`, results: [] };
    }
    const items = await resp.json();
    return { provider: "apify", query: url, results: Array.isArray(items) ? items : [items] };
  } catch (err: any) {
    return { provider: "apify", query: url, error: err.message, results: [] };
  }
}

function formatSearchContext(label: string, result: any, maxResults = 8): string {
  if (!result || result.error) return `### ${label}\n_(geen data: ${result?.error || "unknown"})_\n`;
  if (!result.results || result.results.length === 0) return `### ${label}\n_(geen resultaten voor: "${result.query}")_\n`;
  let s = `### ${label}\nQuery: \`${result.query}\`\n`;
  for (const r of result.results.slice(0, maxResults)) {
    const snippet = (r.snippet || "").slice(0, 300);
    const date = r.date ? ` [${r.date}]` : "";
    s += `\n- **${r.title || "(no title)"}**${date}\n  ${snippet}\n  ${r.url || ""}\n`;
  }
  return s + "\n";
}

function formatLinkedInContext(label: string, result: any): string {
  if (!result || result.error) return `### ${label}\n_(geen LinkedIn-data: ${result?.error || "unknown"})_\n`;
  if (!result.results || result.results.length === 0) return `### ${label}\n_(geen LinkedIn-profile-data)_\n`;
  const p = result.results[0];
  if (!p) return `### ${label}\n_(leeg profiel)_\n`;

  let s = `### ${label}\n`;
  if (p.fullName || p.name) s += `**Naam:** ${p.fullName || p.name}\n`;
  if (p.headline) s += `**Headline:** ${p.headline}\n`;
  if (p.about || p.summary) s += `**About:** ${(p.about || p.summary).slice(0, 600)}\n`;
  if (p.location) s += `**Locatie:** ${p.location}\n`;
  if (p.followersCount) s += `**Followers:** ${p.followersCount}\n`;

  if (Array.isArray(p.experience) && p.experience.length > 0) {
    s += `\n**Recente experiences:**\n`;
    for (const exp of p.experience.slice(0, 4)) {
      s += `- ${exp.title || "?"} bij ${exp.companyName || exp.company || "?"}${exp.dateRange ? ` (${exp.dateRange})` : ""}\n`;
    }
  }
  const posts = p.posts || p.activity || [];
  if (Array.isArray(posts) && posts.length > 0) {
    s += `\n**Recente posts (laatste 5):**\n`;
    for (const post of posts.slice(0, 5)) {
      const text = (post.text || post.content || "").slice(0, 250);
      const date = post.postedAt || post.date || "";
      if (text) s += `- ${date ? `[${date}] ` : ""}${text}\n`;
    }
  }
  return s + "\n";
}

// ============================================================
// BACKGROUND WORK
// ============================================================

async function processBattlecard(prepId: string) {
  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

  async function salesRest<T>(method: string, path: string, body?: any): Promise<T | null> {
    const resp = await fetch(`${supabaseUrl}/rest/v1/${path}`, {
      method,
      headers: {
        "apikey": serviceKey, "Authorization": `Bearer ${serviceKey}`,
        "Content-Type": "application/json",
        "Accept-Profile": "sales", "Content-Profile": "sales",
        "Prefer": "return=representation",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) throw new Error(`Sales REST ${method} ${path}: ${resp.status} ${await resp.text()}`);
    return await resp.json() as T;
  }

  try {
    const preps: any[] = (await salesRest<any[]>("GET", `meeting_preps?id=eq.${prepId}&select=*`)) || [];
    if (preps.length === 0) throw new Error("Prep not found in background");
    const prep = preps[0];

    // Status -> researching
    await salesRest("PATCH", `battlecards?meeting_prep_id=eq.${prepId}`, {
      status: "researching",
      generation_started_at: new Date().toISOString(),
      generation_error: null,
    });

    // ==== Web-searches in parallel ====
    const prospectName = prep.prospect_company_name || "";
    const vertical = prep.industry_vertical || prep.prospect_sector || "";
    const linkedinUrl = prep.decision_maker_linkedin_url || "";
    const competitors = prep.competitors || "";

    const queries = {
      recent_triggers: prospectName ? `"${prospectName}" news 2026 OR 2025` : "",
      market_trends: vertical ? `${vertical} trends 2026 belgium` : "",
      linkedin: linkedinUrl,
      competitive: competitors ? `${competitors} comparison alternatives` : (prospectName ? `${prospectName} competitors` : ""),
    };

    const [recentTriggers, marketTrends, linkedinProfile, competitiveLandscape] = await Promise.all([
      searchSerpApi(queries.recent_triggers, "qdr:m3", 30000),
      searchSerpApi(queries.market_trends, null, 30000),
      scrapeLinkedInProfile(queries.linkedin, 180000), // tot 3 min voor LinkedIn
      searchSearchApi(queries.competitive, 30000),
    ]);

    const webContext = [
      formatSearchContext("Recent Triggers (90 dagen) voor " + prospectName, recentTriggers),
      formatSearchContext("Market Trends (" + vertical + ")", marketTrends),
      formatLinkedInContext("Decision Maker LinkedIn Profile", linkedinProfile),
      formatSearchContext("Competitive Landscape", competitiveLandscape),
    ].join("\n");

    // Status -> writing
    await salesRest("PATCH", `battlecards?meeting_prep_id=eq.${prepId}`, { status: "writing" });

    // ==== Build prompts ====
    const meetingTypeHint = prep.meeting_type && MEETING_TYPE_GUIDANCE[prep.meeting_type] ? `MEETING TYPE: ${prep.meeting_type}. ${MEETING_TYPE_GUIDANCE[prep.meeting_type]}` : "MEETING TYPE: niet gespecificeerd.";
    const dealStageHint = prep.deal_stage && DEAL_STAGE_GUIDANCE[prep.deal_stage] ? `DEAL STAGE: ${prep.deal_stage}. ${DEAL_STAGE_GUIDANCE[prep.deal_stage]}` : "DEAL STAGE: niet gespecificeerd.";
    const klantTypeHint = prep.klant_type && KLANT_TYPE_GUIDANCE[prep.klant_type] ? `KLANTSOORT: ${prep.klant_type}. ${KLANT_TYPE_GUIDANCE[prep.klant_type]}` : "KLANTSOORT: niet gespecificeerd.";
    const verticalHint = prep.industry_vertical ? `INDUSTRY VERTICAL: ${prep.industry_vertical}.` : "INDUSTRY VERTICAL: niet gespecificeerd.";
    const methodOverride = prep.sales_method && METHOD_OVERRIDE[prep.sales_method] ? `\n\nSALES-METHODE-VOORKEUR: ${METHOD_OVERRIDE[prep.sales_method]}.` : "";

    const additionalStakeholders = Array.isArray(prep.additional_stakeholders) ? prep.additional_stakeholders : [];
    const stakeholdersList = additionalStakeholders.length > 0
      ? additionalStakeholders.map((s: any, i: number) => `  ${i + 2}. ${s.name || "?"}${s.role ? ` (${s.role})` : ""}${s.linkedin_url ? ` Ã¢ÂÂ ${s.linkedin_url}` : ""}`).join("\n")
      : "  (Geen extra aanwezigen)";

    const systemPrompt = `Je bent senior B2B sales-strateeg voor Agenic / Nestor Sales. Schrijft een Nestor Sales briefing volgens v2-spec.

DOEL: salesperson stapt na 30 min lezen het gesprek in met begrip + scherpe vragen. Top performers brengen INZICHTEN (Challenger Sale).

WEB-SEARCH CONTEXT Ã¢ÂÂ BELANGRIJK:
Onderaan user-prompt staat real-time web-data (Google + LinkedIn). GEBRUIK actief:
- Blok 3 Recent Triggers: cite cijfers/data uit 90-dagen search
- Blok 2 Stakeholder: LinkedIn-data voor prof. context + recente posts
- Blok 7 Objections: competitive context
- Claims uit search-data Ã¢ÂÂ [H]. Inference Ã¢ÂÂ [M]. Lege context Ã¢ÂÂ [M] met training-knowledge.

DE 10 BLOKKEN Ã¢ÂÂ STRIKT, IN 4 CATEGORIEÃÂN:

=== DE CONTEXT ===
**1. Account Snapshot** (context) Ã¢ÂÂ bedrijf in 1 pagina.
**2. Stakeholder Profile** (context, MET 2 SUBSECTIES):
- Professionele context (LinkedIn carriÃÂ¨re + posts) / Persoonlijke aanknopingspunten (3-5 max)
ALS additional_stakeholders: extra subsecties per persoon.
**3. Strategische Context** (context, MET 2 SUBSECTIES):
- Markt-inzichten (1-2 verrassend, als vraag/observatie) / Recent Triggers 90 dagen (GEBRUIK WEB-DATA)

=== DE ANALYSE ===
**4. Pijnhypothese** (analyse, MET 2 SUBSECTIES):
- Op organisatie-niveau / Op persoon-niveau (observatie, niet aanname)
**5. Conversation Starters** (analyse) Ã¢ÂÂ 3-5 concrete zinnen in quotes

=== DE AANPAK ===
**6. Question Bank** (aanpak, MET 4 SUBSECTIES SPIN): Situation / Problem / Implication / Need-payoff (8-12 vragen)
**7. Likely Objections** (aanpak) Ã¢ÂÂ tot 10, ranked:
- **01. "[Bezwaar]"** [H/M]
  Ã¢ÂÂ [Response]
Gebruik product_offering + competitors.
**8. Next-Step Strategy** (aanpak) Ã¢ÂÂ Ideaal + 3 scenario's (positief/neutraal/lastig)

=== HET ONVERWACHTE ===
**9. Wat-als-scenario's** (onverwachte) Ã¢ÂÂ 4-5. ALS biggest_concern: maak Wat-als hiervoor.
**10. Possible Sensitivities** (onverwachte) Ã¢ÂÂ [!] **Topic** Ã¢ÂÂ framing-advies

CONFIDENCE: [H]=verifieerbaar/in web-context, [M]=inference. Inline na claims.
MARKERS: [v]/[!]/[?]/[x] aan begin lijst-items, GEEN emoji's.
Gebruik Ã¢ÂÂ voor mitigatie.

INTAKE-NADRUK:
${meetingTypeHint}
${dealStageHint}
${klantTypeHint}
${verticalHint}${methodOverride}

SCHRIJFSTIJL: scherp, concreet Nederlands. Max ~200 woorden/blok.

OUTPUT JSON Ã¢ÂÂ begin DIRECT:
{"blocks":{"1":{"title":"Account Snapshot","category":"context","content":"...","subsections":[]},"2":{"title":"Stakeholder Profile","category":"context","content":"...","subsections":[{"title":"[Naam] Ã¢ÂÂ Professionele context","content":"..."},{"title":"[Naam] Ã¢ÂÂ Persoonlijke aanknopingspunten","content":"..."}]},"3":{"title":"Strategische Context","category":"context","content":"...","subsections":[{"title":"Markt-inzichten","content":"..."},{"title":"Recent Triggers (90 dagen)","content":"..."}]},"4":{"title":"Pijnhypothese","category":"analyse","content":"...","subsections":[{"title":"Op organisatie-niveau","content":"..."},{"title":"Op persoon-niveau","content":"..."}]},"5":{"title":"Conversation Starters","category":"analyse","content":"...","subsections":[]},"6":{"title":"Question Bank","category":"aanpak","content":"","subsections":[{"title":"Situation","content":"..."},{"title":"Problem","content":"..."},{"title":"Implication","content":"..."},{"title":"Need-payoff","content":"..."}]},"7":{"title":"Likely Objections","category":"aanpak","content":"...","subsections":[]},"8":{"title":"Next-Step Strategy","category":"aanpak","content":"...","subsections":[]},"9":{"title":"Wat-als-scenario's","category":"onverwachte","content":"...","subsections":[]},"10":{"title":"Possible Sensitivities","category":"onverwachte","content":"...","subsections":[]}}}`;

    const userPrompt = `INTAKE-DATA:

KLANT: ${prep.klant_name || "?"}${prep.klant_role ? ` (${prep.klant_role})` : ""} bij ${prep.klant_company || "?"}

PROSPECT: ${prep.prospect_company_name} Ã¢ÂÂ ${prep.prospect_company_url || "?"} Ã¢ÂÂ sector: ${prep.prospect_sector || "?"}

MENSEN AAN TAFEL:
  1. PRIMARY: ${prep.decision_maker_name || "?"}${prep.decision_maker_role ? ` (${prep.decision_maker_role})` : ""} Ã¢ÂÂ ${prep.decision_maker_linkedin_url || "?"}
${stakeholdersList}

MEETING: ${prep.meeting_datetime || "?"} Ã¢ÂÂ ${prep.meeting_location || "?"}
Agenda: ${prep.meeting_agenda || "?"}
Deadline: ${prep.meeting_deadline || "?"}

DROPDOWNS: meeting_type=${prep.meeting_type || "?"}, deal_stage=${prep.deal_stage || "?"}, klant_type=${prep.klant_type || "?"}, industry=${prep.industry_vertical || "?"}

JOUW KANT:
- Sales-objectief: ${prep.sales_objective || "?"}
- Product/aanbod: ${prep.product_offering || "GENERIEK"}
- Hypotheses: ${prep.hypotheses || "geen"}
- Concurrenten: ${prep.competitors || "?"}

EXTRA:
- Voorgaande contact: ${prep.prior_contact_summary || "geen"}
- Grootste angst: ${prep.biggest_concern || "?"}
- Specifieke vraag: ${prep.specific_question || "geen"}
- Geografie: ${prep.geography_culture || "?"}

========================================
WEB-SEARCH RESULTS (real-time):
========================================

${webContext}
========================================

Genereer de 10-block Nestor Sales briefing. Gebruik WEB-DATA voor blok 2/3/7. Confidence-ratings [H]/[M] inline. ALLEEN JSON output.`;

    // ==== Claude call ====
    const anthropic = new Anthropic({ apiKey: Deno.env.get("ANTHROPIC_API_KEY")! });
    const completion = await anthropic.messages.create({
      model: "claude-sonnet-4-5",
      max_tokens: 14000,
      system: systemPrompt,
      messages: [{ role: "user", content: userPrompt }],
    });

    const rawText = (completion.content[0] as any)?.text || "";
    let parsed: any;
    try {
      const fenced = rawText.match(/```(?:json)?\s*([\s\S]*?)\s*```/);
      const bareJson = rawText.match(/(\{[\s\S]*\})/);
      const jsonText = fenced ? fenced[1] : (bareJson ? bareJson[1] : rawText);
      parsed = JSON.parse(jsonText);
    } catch (e: any) {
      await salesRest("PATCH", `battlecards?meeting_prep_id=eq.${prepId}`, {
        status: "failed",
        generation_error: `JSON parse: ${e.message}. Raw: ${rawText.slice(0, 800)}`,
        generation_completed_at: new Date().toISOString(),
      });
      return;
    }

    const blocks = parsed.blocks || {};

    // Build raw_markdown
    let rawMd = `# Nestor Sales Briefing Ã¢ÂÂ ${prep.prospect_company_name}\n\n`;
    if (prep.klant_name) rawMd += `Voor: ${prep.klant_name}${prep.klant_company ? ` (${prep.klant_company})` : ""}\n`;
    if (prep.meeting_datetime) rawMd += `Meeting: ${prep.meeting_datetime}\n`;
    if (prep.decision_maker_name) rawMd += `Decision maker: ${prep.decision_maker_name}${prep.decision_maker_role ? ` (${prep.decision_maker_role})` : ""}\n`;
    rawMd += `\n---\n\n`;

    const CAT_LABELS: Record<string, string> = { context: "DE CONTEXT", analyse: "DE ANALYSE", aanpak: "DE AANPAK", onverwachte: "HET ONVERWACHTE" };
    const CAT_ORDER = ["context", "analyse", "aanpak", "onverwachte"];
    const orderedKeys = Object.keys(blocks).sort((a, b) => parseInt(a) - parseInt(b));
    const byCat: Record<string, any[]> = { context: [], analyse: [], aanpak: [], onverwachte: [] };
    for (const k of orderedKeys) {
      const b = blocks[k];
      const cat = b.category || "context";
      if (!byCat[cat]) byCat[cat] = [];
      byCat[cat].push({ key: k, ...b });
    }
    for (const cat of CAT_ORDER) {
      const items = byCat[cat] || [];
      if (items.length === 0) continue;
      rawMd += `\n## ${CAT_LABELS[cat]}\n\n`;
      for (const b of items) {
        rawMd += `### ${b.key}. ${b.title}\n\n`;
        if (b.content?.trim()) rawMd += `${b.content}\n\n`;
        if (Array.isArray(b.subsections)) {
          for (const sub of b.subsections) rawMd += `**${sub.title}**\n\n${sub.content}\n\n`;
        }
      }
    }
    rawMd += `\n---\n\n_Methodologische basis: Challenger Sale, MEDDPICC, SPIN, Pre-Suasion, Tactical Empathy._\n_Nestor Sales v3 (web-search enabled)._\n`;

    const sources = {
      generated_at: new Date().toISOString(),
      queries,
      results: { recent_triggers: recentTriggers, market_trends: marketTrends, linkedin_profile: linkedinProfile, competitive_landscape: competitiveLandscape },
    };

    await salesRest("PATCH", `battlecards?meeting_prep_id=eq.${prepId}`, {
      status: "ready",
      blocks,
      raw_markdown: rawMd,
      sources,
      model_used: completion.model,
      prompt_tokens: completion.usage?.input_tokens,
      completion_tokens: completion.usage?.output_tokens,
      generation_completed_at: new Date().toISOString(),
    });
  } catch (err: any) {
    try {
      await salesRest("PATCH", `battlecards?meeting_prep_id=eq.${prepId}`, {
        status: "failed",
        generation_error: `Background error: ${err.message || String(err)}`,
        generation_completed_at: new Date().toISOString(),
      });
    } catch (_) {}
  }
}

// ============================================================
// MAIN Ã¢ÂÂ returnt direct, werk gaat in background
// ============================================================

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS_HEADERS });

  try {
    const body = await req.json();
    const prepId = body.prep_id;
    if (!prepId) return jsonError("Missing prep_id", 400);

    // Spawn background processing (geen await)
    // @ts-ignore EdgeRuntime is een global in Supabase Edge
    EdgeRuntime.waitUntil(processBattlecard(prepId));

    return new Response(JSON.stringify({
      accepted: true,
      prep_id: prepId,
      message: "Battlecard generation started in background. Check status via DB or wait for admin email.",
    }), {
      status: 202,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  } catch (err: any) {
    return jsonError(err?.message || "Unknown error", 500);
  }
});

function jsonError(msg: string, status = 500) {
  return new Response(JSON.stringify({ error: msg }), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}
