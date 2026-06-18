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
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors });
  }
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), {
      status: 405,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  type Body = {
    intake_id?: string;
    query?: string;
    research_question_id?: string | null;
    top_k?: number;
    threshold?: number;
  };

  let body: Body;
  try {
    body = await req.json();
  } catch (e) {
    return new Response(JSON.stringify({ error: "invalid JSON: " + (e as Error).message }), {
      status: 400,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  if (!body.intake_id || !body.query || body.query.trim().length === 0) {
    return new Response(
      JSON.stringify({ error: "intake_id and query are required" }),
      { status: 400, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  const top_k = Math.min(Math.max(body.top_k ?? 10, 1), 50);
  const threshold = body.threshold ?? 0;

  let queryEmbedding: number[];
  let usageTokens = 0;
  try {
    const res = await fetch(VOYAGE_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${VOYAGE_API_KEY}`,
      },
      body: JSON.stringify({
        input: [body.query],
        model: VOYAGE_MODEL,
        input_type: "query",
        output_dimension: VOYAGE_DIM,
      }),
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Voyage API ${res.status}: ${errText}`);
    }
    const json = await res.json();
    queryEmbedding = json.data[0].embedding;
    usageTokens = json.usage?.total_tokens ?? 0;
  } catch (err) {
    return new Response(
      JSON.stringify({ success: false, error: "embed query failed: " + (err as Error).message }),
      { status: 500, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
    db: { schema: "nestor" },
  });

  const { data, error } = await supabase.rpc("match_artifacts", {
    query_embedding: queryEmbedding,
    filter_intake_id: body.intake_id,
    filter_question_id: body.research_question_id ?? null,
    match_threshold: threshold,
    match_count: top_k,
  });

  if (error) {
    return new Response(
      JSON.stringify({ success: false, error: "rpc failed: " + error.message }),
      { status: 500, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  return new Response(
    JSON.stringify({
      success: true,
      query: body.query,
      results: data ?? [],
      query_tokens: usageTokens,
      model: VOYAGE_MODEL,
    }),
    { headers: { ...cors, "Content-Type": "application/json" } },
  );
});
