import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const VOYAGE_API_KEY = Deno.env.get("VOYAGE_API_KEY")!;

const VOYAGE_MODEL = "voyage-3-large";
const VOYAGE_DIM = 1024;
const VOYAGE_ENDPOINT = "https://api.voyageai.com/v1/embeddings";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-supabase-api-version",
  "Access-Control-Max-Age": "86400",
};

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (req.method !== "POST") return new Response(JSON.stringify({ error: "method" }), { status: 405, headers: { ...cors, "Content-Type": "application/json" } });

  let body: { query?: string; organization_id?: string; top_k?: number };
  try { body = await req.json(); } catch (e) {
    return new Response(JSON.stringify({ error: "invalid JSON: " + (e as Error).message }), { status: 400, headers: { ...cors, "Content-Type": "application/json" } });
  }
  if (!body.query || body.query.trim().length === 0) {
    return new Response(JSON.stringify({ error: "query required" }), { status: 400, headers: { ...cors, "Content-Type": "application/json" } });
  }
  const top_k = Math.min(Math.max(body.top_k ?? 15, 1), 50);

  // Embed query
  let queryEmbedding: number[];
  try {
    const res = await fetch(VOYAGE_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${VOYAGE_API_KEY}` },
      body: JSON.stringify({ input: [body.query], model: VOYAGE_MODEL, input_type: "query", output_dimension: VOYAGE_DIM }),
    });
    if (!res.ok) throw new Error(`Voyage ${res.status}: ${await res.text()}`);
    const json = await res.json();
    queryEmbedding = json.data[0].embedding;
  } catch (err) {
    return new Response(JSON.stringify({ success: false, error: "embed failed: " + (err as Error).message }), { status: 500, headers: { ...cors, "Content-Type": "application/json" } });
  }

  const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, { db: { schema: "nestor" } });

  const { data: matches, error: rpcErr } = await supabase.rpc("match_search_index", {
    query_embedding: queryEmbedding,
    filter_organization_id: body.organization_id ?? null,
    match_threshold: 0,
    match_count: top_k,
  });
  if (rpcErr) {
    return new Response(JSON.stringify({ success: false, error: "rpc: " + rpcErr.message }), { status: 500, headers: { ...cors, "Content-Type": "application/json" } });
  }

  // Hydrate results with intake.title, client.name, product
  const intakeIds = [...new Set((matches ?? []).map((m: any) => m.intake_id).filter(Boolean))];
  const clientIds = [...new Set((matches ?? []).map((m: any) => m.client_id).filter(Boolean))];

  const intakeMap: Record<string, any> = {};
  if (intakeIds.length > 0) {
    const { data: intakes } = await supabase.from("intakes").select("id, title, product_slug, status").in("id", intakeIds);
    for (const i of intakes ?? []) intakeMap[i.id] = i;
  }
  const clientMap: Record<string, any> = {};
  if (clientIds.length > 0) {
    const supaPub = createClient(SUPABASE_URL, SERVICE_ROLE_KEY); // public schema
    const { data: clients } = await supaPub.from("clients").select("id, name, industry").in("id", clientIds);
    for (const c of clients ?? []) clientMap[c.id] = c;
  }

  const enriched = (matches ?? []).map((m: any) => ({
    ...m,
    intake: m.intake_id ? intakeMap[m.intake_id] : null,
    client: m.client_id ? clientMap[m.client_id] : null,
  }));

  return new Response(JSON.stringify({ success: true, query: body.query, results: enriched, model: VOYAGE_MODEL }), {
    headers: { ...cors, "Content-Type": "application/json" },
  });
});
