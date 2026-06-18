import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const VOYAGE_API_KEY = Deno.env.get("VOYAGE_API_KEY")!;

const VOYAGE_MODEL = "voyage-3-large";
const VOYAGE_DIM = 1024;
const VOYAGE_ENDPOINT = "https://api.voyageai.com/v1/embeddings";
const MAX_BATCH = 64;

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-supabase-api-version",
  "Access-Control-Max-Age": "86400",
};

async function callVoyage(inputs: string[]): Promise<number[][]> {
  const res = await fetch(VOYAGE_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${VOYAGE_API_KEY}` },
    body: JSON.stringify({
      input: inputs, model: VOYAGE_MODEL, input_type: "document", output_dimension: VOYAGE_DIM,
    }),
  });
  if (!res.ok) throw new Error(`Voyage ${res.status}: ${await res.text()}`);
  const json = await res.json();
  return (json.data as Array<{ index: number; embedding: number[] }>)
    .sort((a, b) => a.index - b.index).map((d) => d.embedding);
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (req.method !== "POST") return new Response(JSON.stringify({ error: "method" }), { status: 405, headers: { ...cors, "Content-Type": "application/json" } });

  const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, { db: { schema: "nestor" } });
  let totalEmbedded = 0;
  let totalFailed = 0;
  let batches = 0;

  try {
    while (true) {
      const { data: pending, error: fetchErr } = await supabase
        .from("search_index")
        .select("id, text_content")
        .eq("embed_status", "pending")
        .limit(MAX_BATCH);
      if (fetchErr) throw new Error("fetch pending: " + fetchErr.message);
      if (!pending || pending.length === 0) break;

      // Mark embedding
      await supabase.from("search_index").update({ embed_status: "embedding" }).in("id", pending.map((p) => p.id));

      try {
        const embs = await callVoyage(pending.map((p) => p.text_content));
        // Update each row with its embedding
        for (let i = 0; i < pending.length; i++) {
          await supabase.from("search_index")
            .update({ embedding: embs[i], embed_status: "embedded", embed_error: null, updated_at: new Date().toISOString() })
            .eq("id", pending[i].id);
        }
        totalEmbedded += pending.length;
      } catch (err) {
        const msg = (err as Error).message || String(err);
        await supabase.from("search_index")
          .update({ embed_status: "failed", embed_error: msg })
          .in("id", pending.map((p) => p.id));
        totalFailed += pending.length;
      }
      batches++;
      if (batches > 100) break; // safety
    }

    return new Response(JSON.stringify({
      success: true, embedded: totalEmbedded, failed: totalFailed, batches,
      model: VOYAGE_MODEL,
    }), { headers: { ...cors, "Content-Type": "application/json" } });
  } catch (err) {
    return new Response(JSON.stringify({ success: false, error: (err as Error).message, embedded: totalEmbedded, failed: totalFailed }), {
      status: 500, headers: { ...cors, "Content-Type": "application/json" },
    });
  }
});
