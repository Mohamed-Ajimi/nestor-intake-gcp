// run-research v3 Ã¢ÂÂ altijd 3 bronnen per vraag (SerpAPI + SearchAPI + Apify rag-web-browser)
// Domain-specifieke crawlers (self-storage URLs, etc.) als BONUS toegevoegd, niet als vervanging.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

async function nestorRest<T>(method: string, path: string, body?: any, options: any = {}): Promise<T> {
  const resp = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    method,
    headers: {
      "apikey": SERVICE_KEY,
      "Authorization": `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      "Accept-Profile": "nestor",
      "Content-Profile": "nestor",
      "Prefer": options.prefer || "return=representation",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`Nestor REST ${method} ${path}: ${resp.status} ${await resp.text()}`);
  return await resp.json() as T;
}

async function uploadToStorage(bucket: string, path: string, content: string, contentType = "application/json"): Promise<void> {
  const resp = await fetch(`${SUPABASE_URL}/storage/v1/object/${bucket}/${path}`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${SERVICE_KEY}`,
      "Content-Type": contentType,
      "x-upsert": "true",
    },
    body: content,
  });
  if (!resp.ok) throw new Error(`Storage upload failed ${bucket}/${path}: ${resp.status} ${await resp.text()}`);
}

async function serpApi(query: string, timeWindow?: string, timeoutMs = 30000): Promise<any> {
  const key = Deno.env.get("SERPAPI_API_KEY");
  if (!key) return { provider: "serpapi", query, error: "no_key", results: [] };
  if (!query?.trim()) return { provider: "serpapi", query, error: "empty", results: [] };
  const params = new URLSearchParams({ api_key: key, engine: "google", q: query, num: "10", hl: "nl", gl: "be" });
  if (timeWindow) params.set("tbs", timeWindow);
  try {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), timeoutMs);
    const r = await fetch(`https://serpapi.com/search?${params}`, { signal: c.signal });
    clearTimeout(t);
    if (!r.ok) return { provider: "serpapi", query, error: `HTTP ${r.status}`, results: [] };
    const d = await r.json();
    const results: any[] = [];
    for (const x of (d.organic_results || []).slice(0, 10)) results.push({ title: x.title, url: x.link, snippet: x.snippet, date: x.date, kind: "organic" });
    for (const x of (d.news_results || []).slice(0, 5)) results.push({ title: x.title, url: x.link, snippet: x.snippet, date: x.date, kind: "news" });
    if (d.answer_box?.snippet) results.unshift({ title: d.answer_box.title || "AnswerBox", url: d.answer_box.link, snippet: d.answer_box.snippet, kind: "answer_box" });
    return { provider: "serpapi", query, time_window: timeWindow, results };
  } catch (e: any) { return { provider: "serpapi", query, error: e.message, results: [] }; }
}

async function searchApi(query: string, timeoutMs = 30000): Promise<any> {
  const key = Deno.env.get("SEARCHAPI_API_KEY");
  if (!key) return { provider: "searchapi", query, error: "no_key", results: [] };
  if (!query?.trim()) return { provider: "searchapi", query, error: "empty", results: [] };
  const params = new URLSearchParams({ api_key: key, engine: "google", q: query, num: "10", hl: "nl", gl: "be" });
  try {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), timeoutMs);
    const r = await fetch(`https://www.searchapi.io/api/v1/search?${params}`, { signal: c.signal });
    clearTimeout(t);
    if (!r.ok) return { provider: "searchapi", query, error: `HTTP ${r.status}`, results: [] };
    const d = await r.json();
    const results: any[] = [];
    for (const x of (d.organic_results || []).slice(0, 10)) results.push({ title: x.title, url: x.link, snippet: x.snippet, kind: "organic" });
    return { provider: "searchapi", query, results };
  } catch (e: any) { return { provider: "searchapi", query, error: e.message, results: [] }; }
}

async function apifyRagWebBrowser(query: string, timeoutMs = 90000): Promise<any> {
  const key = Deno.env.get("APIFY_API_TOKEN");
  if (!key) return { provider: "apify-rag-web-browser", query, error: "no_key", results: [] };
  if (!query?.trim()) return { provider: "apify-rag-web-browser", query, error: "empty", results: [] };
  try {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), timeoutMs);
    const r = await fetch(
      `https://api.apify.com/v2/acts/apify~rag-web-browser/run-sync-get-dataset-items?token=${key}&timeout=80`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: query.slice(0, 300),
          maxResults: 4,
          outputFormats: ["markdown"],
        }),
        signal: c.signal,
      }
    );
    clearTimeout(t);
    if (!r.ok) return { provider: "apify-rag-web-browser", query, error: `HTTP ${r.status}: ${(await r.text()).slice(0,200)}`, results: [] };
    const items = await r.json();
    const results = (Array.isArray(items) ? items : []).map((it: any) => ({
      title: it.metadata?.title || it.searchResult?.title || it.metadata?.url || "(no title)",
      url: it.metadata?.url || it.metadata?.redirectedUrl || it.searchResult?.url,
      snippet: (it.markdown || it.text || it.searchResult?.description || "").slice(0, 1500),
      full_text: (it.markdown || it.text || "").slice(0, 8000),
      kind: "rag_web_browser",
    }));
    return { provider: "apify-rag-web-browser", query, results };
  } catch (e: any) { return { provider: "apify-rag-web-browser", query, error: e.message, results: [] }; }
}

async function apifyWebsiteCrawler(urls: string[], timeoutMs = 180000): Promise<any> {
  const key = Deno.env.get("APIFY_API_TOKEN");
  if (!key) return { provider: "apify-crawler", query: urls, error: "no_key", results: [] };
  if (!urls?.length) return { provider: "apify-crawler", query: urls, error: "no_urls", results: [] };
  try {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), timeoutMs);
    const r = await fetch(
      `https://api.apify.com/v2/acts/apify~website-content-crawler/run-sync-get-dataset-items?token=${key}&timeout=160`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          startUrls: urls.map(u => ({ url: u })),
          maxCrawlDepth: 1,
          maxCrawlPages: 8,
          crawlerType: "playwright:adaptive",
          excludeUrlGlobs: [],
          saveMarkdown: true,
          textExtractor: "crawlee",
          proxyConfiguration: { useApifyProxy: true },
        }),
        signal: c.signal,
      }
    );
    clearTimeout(t);
    if (!r.ok) return { provider: "apify-crawler", query: urls, error: `HTTP ${r.status}: ${(await r.text()).slice(0,200)}`, results: [] };
    const items = await r.json();
    const results = (Array.isArray(items) ? items : []).map((it: any) => ({
      title: it.title || it.url, url: it.url,
      snippet: (it.markdown || it.text || "").slice(0, 1500),
      full_text: (it.markdown || it.text || "").slice(0, 8000),
      kind: "crawl",
    }));
    return { provider: "apify-crawler", query: urls, results };
  } catch (e: any) { return { provider: "apify-crawler", query: urls, error: e.message, results: [] }; }
}

async function apifyMapsReviews(locationUrls: string[], timeoutMs = 180000): Promise<any> {
  const key = Deno.env.get("APIFY_API_TOKEN");
  if (!key) return { provider: "apify-maps-reviews", query: locationUrls, error: "no_key", results: [] };
  if (!locationUrls?.length) return { provider: "apify-maps-reviews", query: locationUrls, error: "no_urls", results: [] };
  try {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), timeoutMs);
    const r = await fetch(
      `https://api.apify.com/v2/acts/compass~google-maps-reviews-scraper/run-sync-get-dataset-items?token=${key}&timeout=160`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          startUrls: locationUrls.map(u => ({ url: u })),
          maxReviews: 30, language: "nl", reviewsSort: "newest",
        }),
        signal: c.signal,
      }
    );
    clearTimeout(t);
    if (!r.ok) return { provider: "apify-maps-reviews", query: locationUrls, error: `HTTP ${r.status}: ${(await r.text()).slice(0,200)}`, results: [] };
    const items = await r.json();
    const results = (Array.isArray(items) ? items : []).map((it: any) => ({
      title: `${it.name || "Location"} Ã¢ÂÂ ${it.stars || "?"}Ã¢ÂÂ door ${it.reviewerName || "anoniem"}`,
      url: it.reviewUrl || it.url,
      snippet: (it.text || it.textTranslated || "").slice(0, 800),
      stars: it.stars, date: it.publishedAtDate, kind: "map_review",
    }));
    return { provider: "apify-maps-reviews", query: locationUrls, results };
  } catch (e: any) { return { provider: "apify-maps-reviews", query: locationUrls, error: e.message, results: [] }; }
}

// v3: GENERIEK plan Ã¢ÂÂ ALTIJD 3 bronnen per vraag. Plus domain-specifieke BONUS-calls.
function planQueries(question: any): Array<{ label: string; runner: () => Promise<any> }> {
  const text = (question.question_text || "").toLowerCase();
  const q = (question.question_text || "").slice(0, 300);

  // Generieke baseline Ã¢ÂÂ ALTIJD voor elke vraag
  const plan: Array<{ label: string; runner: () => Promise<any> }> = [
    { label: "serp_generic", runner: () => serpApi(q) },
    { label: "search_generic", runner: () => searchApi(q) },
    { label: "apify_rag_web_browser", runner: () => apifyRagWebBrowser(q) },
  ];

  // Domain-specifieke BONUS Ã¢ÂÂ toegevoegd aan het generieke plan, niet als vervanging.
  // (Behoudt eerdere self-storage logica voor backwards compat.)
  if (text.includes("verliezen klanten") || text.includes("frictie") || text.includes("ik heb opslag nodig")) {
    plan.push({
      label: "apify_maps_reviews_storage",
      runner: () => apifyMapsReviews([
        "https://www.google.com/maps/place/Shurgard+Self-Storage+Antwerpen",
        "https://www.google.com/maps/place/City+Box+Antwerpen",
      ]),
    });
  }
  if (text.includes("aanpalende") || text.includes("transport") || text.includes("verzekering")) {
    plan.push(
      { label: "apify_crawler_pelican", runner: () => apifyWebsiteCrawler(["https://pelican.nl/", "https://pelican.nl/diensten"]) },
      { label: "apify_crawler_stashbee", runner: () => apifyWebsiteCrawler(["https://www.stashbee.com/", "https://www.stashbee.com/help"]) },
    );
  }
  if (text.includes("unmanned") || text.includes("shurgard") || text.includes("stashbee") || text.includes("pelican")) {
    plan.push({ label: "apify_crawler_shurgard", runner: () => apifyWebsiteCrawler(["https://www.shurgard.be/"]) });
  }

  return plan;
}

function formatResultsAsMarkdown(label: string, result: any, question_text: string): string {
  let md = `# ${label}\n\nQuestion: ${question_text}\n\nProvider: ${result.provider}\n`;
  if (result.query) md += `Query: \`${typeof result.query === 'string' ? result.query : JSON.stringify(result.query)}\`\n`;
  if (result.error) { md += `\n**ERROR**: ${result.error}\n`; return md; }
  if (!result.results?.length) { md += `\n_(geen resultaten)_\n`; return md; }
  md += `\nResults: ${result.results.length}\n\n---\n\n`;
  for (const r of result.results) {
    md += `## ${r.title || "(no title)"}\n`;
    if (r.url) md += `URL: ${r.url}\n`;
    if (r.date) md += `Date: ${r.date}\n`;
    if (r.stars !== undefined) md += `Stars: ${r.stars}\n`;
    if (r.kind) md += `Type: ${r.kind}\n`;
    md += `\n${r.snippet || r.full_text || "(geen snippet)"}\n\n---\n\n`;
  }
  return md;
}

async function runResearch(intakeId: string) {
  try {
    const intakes: any[] = await nestorRest<any[]>("GET", `intakes?id=eq.${intakeId}&select=*`);
    if (!intakes.length) throw new Error("Intake not found");

    await nestorRest("PATCH", `intakes?id=eq.${intakeId}`, { status: "in_research" });

    const questions: any[] = await nestorRest<any[]>(
      "GET",
      `research_questions?intake_id=eq.${intakeId}&status=eq.open&select=*&order=priority.asc.nullslast`
    );

    if (!questions.length) {
      console.log("No open research_questions found.");
      return;
    }

    for (const question of questions) {
      const queries = planQueries(question);
      console.log(`[Q${question.priority}] ${queries.length} queries gepland`);
      const settledResults = await Promise.allSettled(queries.map(q => q.runner()));

      for (let i = 0; i < queries.length; i++) {
        const { label } = queries[i];
        const settled = settledResults[i];
        const result = settled.status === "fulfilled" ? settled.value : { provider: label, error: settled.reason?.message || "unknown", results: [] };

        const filename = `${intakeId}/research/${question.id}/${label}.json`;
        const rawJson = JSON.stringify(result, null, 2);
        try {
          await uploadToStorage("nestor-uploads", filename, rawJson);
        } catch (e: any) {
          console.error(`Upload failed ${filename}:`, e.message);
        }

        const textContent = formatResultsAsMarkdown(label, result, question.question_text);

        await nestorRest("POST", "research_artifacts", {
          intake_id: intakeId,
          research_question_id: question.id,
          source: result.provider || label,
          artifact_type: "search_result",
          filename: `${label}.json`,
          storage_bucket: "nestor-uploads",
          storage_path: filename,
          byte_size: rawJson.length,
          mime_type: "application/json",
          text_content: textContent,
          embed_status: "pending",
          notes: `Auto-generated by run-research v3 for question priority ${question.priority}. Query: ${typeof result.query === 'string' ? result.query : JSON.stringify(result.query).slice(0, 200)}`,
        });
      }
    }

    console.log("Research run complete.");
  } catch (err: any) {
    console.error("runResearch failed:", err.message);
  }
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS });

  try {
    const body = await req.json();
    const intakeId = body.intake_id;
    if (!intakeId) return jsonError("Missing intake_id", 400);

    // @ts-ignore EdgeRuntime global
    EdgeRuntime.waitUntil(runResearch(intakeId));

    return new Response(JSON.stringify({
      accepted: true, intake_id: intakeId,
      message: "Research run started in background. ~5-10 min per vraag (Serp + Search + Apify rag-web-browser). Embedding handled by embed-pending-search worker.",
    }), { status: 202, headers: { ...CORS, "Content-Type": "application/json" } });
  } catch (err: any) {
    return jsonError(err.message || "Unknown error", 500);
  }
});

function jsonError(msg: string, status = 500) {
  return new Response(JSON.stringify({ error: msg }), {
    status, headers: { ...CORS, "Content-Type": "application/json" },
  });
}
