// generate-embeddings
// Genereert pgvector embeddings via OpenAI text-embedding-3-small voor:
//   - alle transcripts van een intake
//   - alle intake_answers van een intake (text-veldwaarden)
//   - alle extracted_insights van een intake (label + summary)
// Idempotent: skipt als er al een embedding bestaat met dezelfde content_hash + model.
//
// Required env: OPENAI_API_KEY
// Invocation: POST { "intake_id": "uuid" }

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
);

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") ?? "";
const MODEL = "text-embedding-3-small";
const DIMENSIONS = 1536;

async function sha256(text: string): Promise<string> {
  const buf = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function embed(texts: string[]): Promise<number[][]> {
  if (texts.length === 0) return [];
  const resp = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ model: MODEL, input: texts, dimensions: DIMENSIONS })
  });
  if (!resp.ok) {
    throw new Error(`OpenAI ${resp.status}: ${await resp.text()}`);
  }
  const json = await resp.json();
  return json.data.map((d: { embedding: number[] }) => d.embedding);
}

function valueToText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(valueToText).join(", ");
  return JSON.stringify(v);
}

async function processOwnerTable(
  intakeId: string,
  table: string,
  textExtractor: (row: Record<string, unknown>) => string
) {
  const { data: rows, error } = await supabase
    .from(table).select("*").eq("intake_id", intakeId);
  if (error) throw error;
  if (!rows || rows.length === 0) return { table, inserted: 0, skipped: 0 };

  let inserted = 0;
  let skipped = 0;
  // Batch in groepen van 64 voor efficiency
  const BATCH = 64;
  for (let i = 0; i < rows.length; i += BATCH) {
    const slice = rows.slice(i, i + BATCH);
    const items: Array<{ row: Record<string, unknown>; text: string; hash: string }> = [];
    for (const r of slice) {
      const text = textExtractor(r).trim();
      if (!text) continue;
      const hash = await sha256(`${MODEL}:${text}`);
      items.push({ row: r, text, hash });
    }
    if (items.length === 0) continue;

    // Skip rows die al een embedding hebben met dezelfde hash
    const hashes = items.map((i) => i.hash);
    const { data: existing } = await supabase
      .from("embeddings")
      .select("owner_id, content_hash")
      .eq("owner_table", table)
      .eq("model", MODEL)
      .in("content_hash", hashes);
    const existingHashes = new Set((existing ?? []).map((e) => e.content_hash));
    const toEmbed = items.filter((i) => !existingHashes.has(i.hash));

    if (toEmbed.length === 0) {
      skipped += items.length;
      continue;
    }

    const vectors = await embed(toEmbed.map((i) => i.text));
    const insertRows = toEmbed.map((i, idx) => ({
      owner_table: table,
      owner_id: i.row.id as string,
      model: MODEL,
      embedding: vectors[idx],
      content_hash: i.hash
    }));

    const { error: insErr } = await supabase
      .from("embeddings")
      .upsert(insertRows, { onConflict: "owner_table,owner_id,model" });
    if (insErr) throw insErr;
    inserted += insertRows.length;
    skipped += items.length - toEmbed.length;
  }
  return { table, inserted, skipped };
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  if (!OPENAI_API_KEY) {
    return new Response(
      JSON.stringify({ error: "OPENAI_API_KEY not configured" }),
      { status: 503, headers: { "content-type": "application/json" } }
    );
  }

  let body: { intake_id?: string };
  try { body = await req.json(); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  const intakeId = body.intake_id;
  if (!intakeId) {
    return new Response(
      JSON.stringify({ error: "Missing intake_id" }),
      { status: 400, headers: { "content-type": "application/json" } }
    );
  }

  try {
    const results = await Promise.all([
      processOwnerTable(intakeId, "transcripts", (r) => r.text as string),
      processOwnerTable(intakeId, "intake_answers", (r) => valueToText(r.value)),
      processOwnerTable(intakeId, "extracted_insights",
        (r) => `${r.label ?? ""}\n${r.summary ?? ""}\n${r.supporting_text ?? ""}`
      )
    ]);
    return new Response(JSON.stringify({ ok: true, intake_id: intakeId, results }), {
      headers: { "content-type": "application/json" }
    });
  } catch (e) {
    return new Response(
      JSON.stringify({ error: (e as Error).message }),
      { status: 500, headers: { "content-type": "application/json" } }
    );
  }
});
