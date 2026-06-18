// Edge Function: embed-artifact
// Reads a research_artifact, chunks its text, embeds via Voyage AI (voyage-3-large, 1024-dim),
// and inserts chunks into nestor.artifact_embeddings.
//
// v7: Use UPSERT with ignoreDuplicates to avoid race-conditions where 2 parallel calls
//     try to insert the same (artifact_id, chunk_index) pair.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const VOYAGE_API_KEY = Deno.env.get("VOYAGE_API_KEY")!;

const VOYAGE_MODEL = "voyage-3-large";
const VOYAGE_DIM = 1024;
const VOYAGE_ENDPOINT = "https://api.voyageai.com/v1/embeddings";

const CHUNK_SIZE = 1000;
const CHUNK_OVERLAP = 200;
const MAX_BATCH = 100;
const MAX_TOKENS_PER_REQUEST = 30000;

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function chunkText(text: string): string[] {
  const chunks: string[] = [];
  if (!text || text.length === 0) return chunks;
  if (text.length <= CHUNK_SIZE) {
    chunks.push(text);
    return chunks;
  }
  let i = 0;
  while (i < text.length) {
    const end = Math.min(i + CHUNK_SIZE, text.length);
    chunks.push(text.slice(i, end));
    if (end >= text.length) break;
    i += CHUNK_SIZE - CHUNK_OVERLAP;
  }
  return chunks;
}

function estimateTokens(s: string): number {
  return Math.ceil(s.length / 4);
}

async function callVoyage(inputs: string[]): Promise<number[][]> {
  const res = await fetch(VOYAGE_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${VOYAGE_API_KEY}`,
    },
    body: JSON.stringify({
      input: inputs,
      model: VOYAGE_MODEL,
      input_type: "document",
      output_dimension: VOYAGE_DIM,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Voyage API ${res.status}: ${errText}`);
  }
  const json = await res.json();
  const sorted = (json.data as Array<{ index: number; embedding: number[] }>)
    .sort((a, b) => a.index - b.index)
    .map((d) => d.embedding);
  return sorted;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), {
      status: 405,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  let artifact_id: string;
  try {
    const body = await req.json();
    artifact_id = body.artifact_id;
    if (!artifact_id) throw new Error("missing artifact_id");
  } catch (e) {
    return new Response(JSON.stringify({ error: "invalid body: " + (e as Error).message }), {
      status: 400,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
    db: { schema: "nestor" },
  });

  const { data: artifact, error: fetchErr } = await supabase
    .from("research_artifacts")
    .select(
      "id, intake_id, filename, storage_bucket, storage_path, mime_type, text_content, embed_status",
    )
    .eq("id", artifact_id)
    .single();

  if (fetchErr || !artifact) {
    return new Response(
      JSON.stringify({ error: "artifact not found: " + (fetchErr?.message || "unknown") }),
      { status: 404, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  // Idempotency: skip if already embedded
  if (artifact.embed_status === "embedded") {
    return new Response(
      JSON.stringify({ success: true, skipped: true, reason: "already embedded", artifact_id }),
      { headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  // Race-protection: only proceed if we can flip from 'pending' -> 'embedding'.
  // If another worker is already 'embedding', skip this call.
  const { data: claimed, error: claimErr } = await supabase
    .from("research_artifacts")
    .update({ embed_status: "embedding", embed_error: null })
    .eq("id", artifact_id)
    .in("embed_status", ["pending", "failed"])
    .select("id");

  if (claimErr) {
    return new Response(
      JSON.stringify({ error: "claim failed: " + claimErr.message }),
      { status: 500, headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  if (!claimed || claimed.length === 0) {
    // Another worker is already embedding this artifact, or it's already embedded
    return new Response(
      JSON.stringify({ success: true, skipped: true, reason: "already being embedded by another worker", artifact_id }),
      { headers: { ...cors, "Content-Type": "application/json" } },
    );
  }

  // Wipe any prior embeddings (in case of retry)
  await supabase.from("artifact_embeddings").delete().eq("artifact_id", artifact_id);

  try {
    let text = artifact.text_content as string | null;

    if (!text || text.trim().length === 0) {
      if (artifact.storage_bucket && artifact.storage_path) {
        const mime = (artifact.mime_type || "").toLowerCase();
        const isText =
          mime.startsWith("text/") ||
          mime === "application/json" ||
          artifact.filename?.match(/\.(txt|md|json|csv)$/i);

        if (isText) {
          const { data: blob, error: dlErr } = await supabase.storage
            .from(artifact.storage_bucket)
            .download(artifact.storage_path);
          if (dlErr) throw new Error("storage download: " + dlErr.message);
          text = await blob.text();
        } else {
          throw new Error(
            `mime_type ${mime} not supported for auto-embedding (text_content was empty). Provide text_content directly or upload a .txt file.`,
          );
        }
      } else {
        throw new Error("no text_content and no storage_path");
      }
    }

    const chunks = chunkText(text);
    if (chunks.length === 0) throw new Error("text produced zero chunks");

    const allEmbeddings: number[][] = [];
    let totalTokens = 0;
    let batch: string[] = [];
    let batchTokens = 0;

    const flushBatch = async () => {
      if (batch.length === 0) return;
      const embs = await callVoyage(batch);
      allEmbeddings.push(...embs);
      totalTokens += batchTokens;
      batch = [];
      batchTokens = 0;
    };

    for (const c of chunks) {
      const t = estimateTokens(c);
      if (batch.length >= MAX_BATCH || batchTokens + t > MAX_TOKENS_PER_REQUEST) {
        await flushBatch();
      }
      batch.push(c);
      batchTokens += t;
    }
    await flushBatch();

    if (allEmbeddings.length !== chunks.length) {
      throw new Error(
        `embedding count mismatch: ${allEmbeddings.length} vs ${chunks.length} chunks`,
      );
    }

    const rows = chunks.map((chunk, idx) => ({
      artifact_id: artifact.id,
      intake_id: artifact.intake_id,
      chunk_index: idx,
      chunk_text: chunk,
      chunk_tokens: estimateTokens(chunk),
      embedding: allEmbeddings[idx],
    }));

    // Use UPSERT with ignoreDuplicates as defensive idempotency.
    // If another worker raced past our claim somehow (e.g. crashed mid-way),
    // we skip rather than error.
    for (let i = 0; i < rows.length; i += 50) {
      const slice = rows.slice(i, i + 50);
      const { error: insErr } = await supabase
        .from("artifact_embeddings")
        .upsert(slice, {
          onConflict: "artifact_id,chunk_index",
          ignoreDuplicates: true,
        });
      if (insErr) throw new Error("upsert embeddings: " + insErr.message);
    }

    await supabase
      .from("research_artifacts")
      .update({
        embed_status: "embedded",
        embed_model: VOYAGE_MODEL,
        embedded_at: new Date().toISOString(),
        token_count: totalTokens,
        embed_error: null,
      })
      .eq("id", artifact_id);

    return new Response(
      JSON.stringify({
        success: true,
        artifact_id,
        chunk_count: chunks.length,
        total_tokens: totalTokens,
        model: VOYAGE_MODEL,
      }),
      { headers: { ...cors, "Content-Type": "application/json" } },
    );
  } catch (err) {
    const msg = (err as Error).message || String(err);
    await supabase
      .from("research_artifacts")
      .update({ embed_status: "failed", embed_error: msg })
      .eq("id", artifact_id);

    return new Response(JSON.stringify({ success: false, error: msg, artifact_id }), {
      status: 500,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }
});
