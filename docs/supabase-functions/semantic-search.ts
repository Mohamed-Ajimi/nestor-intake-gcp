// semantic-search
// Tekstuele query Ã¢ÂÂ OpenAI embedding Ã¢ÂÂ match_intake_content RPC Ã¢ÂÂ resultaten.
//
// Required env: OPENAI_API_KEY
// Invocation: POST { "query": "...", "threshold": 0.7, "limit": 25, "intake_id": null }

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
);

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") ?? "";
const MODEL = "text-embedding-3-small";

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  if (!OPENAI_API_KEY) {
    return new Response(
      JSON.stringify({ error: "OPENAI_API_KEY not configured" }),
      { status: 503, headers: { "content-type": "application/json" } }
    );
  }

  let body: { query?: string; threshold?: number; limit?: number; intake_id?: string };
  try { body = await req.json(); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  if (!body.query) return new Response("Missing query", { status: 400 });

  const resp = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ model: MODEL, input: body.query, dimensions: 1536 })
  });
  if (!resp.ok) {
    return new Response(`OpenAI ${resp.status}: ${await resp.text()}`, { status: 500 });
  }
  const embJson = await resp.json();
  const queryEmbedding = embJson.data[0].embedding;

  const { data, error } = await supabase.rpc("match_intake_content", {
    query_embedding: queryEmbedding,
    match_threshold: body.threshold ?? 0.7,
    match_count: body.limit ?? 25,
    filter_intake_id: body.intake_id ?? null
  });

  if (error) {
    return new Response(
      JSON.stringify({ error: error.message }),
      { status: 500, headers: { "content-type": "application/json" } }
    );
  }

  return new Response(
    JSON.stringify({ ok: true, query: body.query, results: data ?? [] }),
    { headers: { "content-type": "application/json" } }
  );
});
