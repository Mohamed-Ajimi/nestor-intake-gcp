// transcribe-audio
// Download audio uit Supabase Storage, stuurt naar OpenAI Whisper-1, schrijft chunks naar transcripts.
//
// Required env: OPENAI_API_KEY
// Invocation: POST { "source_id": "uuid" }

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
);

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") ?? "";

type WhisperSegment = {
  id: number;
  start: number;
  end: number;
  text: string;
};

type WhisperResponse = {
  text: string;
  language?: string;
  segments?: WhisperSegment[];
};

// Chunk segments tot blokken van ~500 woorden voor embedding-friendly chunks
function chunkSegments(segments: WhisperSegment[], maxWords = 500): Array<{
  text: string; start_ms: number; end_ms: number;
}> {
  const out: Array<{ text: string; start_ms: number; end_ms: number }> = [];
  let buf: string[] = [];
  let wc = 0;
  let startMs = 0;
  let endMs = 0;

  for (const seg of segments) {
    const words = seg.text.trim().split(/\s+/).length;
    if (buf.length === 0) startMs = Math.round(seg.start * 1000);
    buf.push(seg.text.trim());
    endMs = Math.round(seg.end * 1000);
    wc += words;
    if (wc >= maxWords) {
      out.push({ text: buf.join(" "), start_ms: startMs, end_ms: endMs });
      buf = []; wc = 0;
    }
  }
  if (buf.length > 0) out.push({ text: buf.join(" "), start_ms: startMs, end_ms: endMs });
  return out;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  if (!OPENAI_API_KEY) {
    return new Response(
      JSON.stringify({ error: "OPENAI_API_KEY not configured" }),
      { status: 503, headers: { "content-type": "application/json" } }
    );
  }

  let body: { source_id?: string };
  try { body = await req.json(); }
  catch { return new Response("Invalid JSON", { status: 400 }); }

  const sourceId = body.source_id;
  if (!sourceId) return new Response("Missing source_id", { status: 400 });

  const { data: source, error: srcErr } = await supabase
    .from("intake_sources").select("*").eq("id", sourceId).single();
  if (srcErr || !source) return new Response("Source not found", { status: 404 });
  if (source.kind !== "audio" && source.kind !== "video") {
    return new Response(`Unsupported source kind: ${source.kind}`, { status: 400 });
  }

  // Download from Storage
  const { data: file, error: dlErr } = await supabase.storage
    .from(source.storage_bucket).download(source.storage_path);
  if (dlErr || !file) return new Response(`Download failed: ${dlErr?.message}`, { status: 500 });

  // Send to Whisper
  const formData = new FormData();
  formData.append("file", file, source.file_name ?? "audio.m4a");
  formData.append("model", "whisper-1");
  formData.append("response_format", "verbose_json");
  formData.append("language", source.language ?? "nl");

  const resp = await fetch("https://api.openai.com/v1/audio/transcriptions", {
    method: "POST",
    headers: { "Authorization": `Bearer ${OPENAI_API_KEY}` },
    body: formData
  });
  if (!resp.ok) {
    return new Response(`Whisper ${resp.status}: ${await resp.text()}`, { status: 500 });
  }
  const transcript: WhisperResponse = await resp.json();

  // Chunk + insert
  const segments = transcript.segments ?? [{ id: 0, start: 0, end: 0, text: transcript.text }];
  const chunks = chunkSegments(segments);

  const rows = chunks.map((c, i) => ({
    intake_id: source.intake_id,
    source_id: sourceId,
    chunk_index: i,
    text: c.text,
    start_ms: c.start_ms,
    end_ms: c.end_ms,
    language: transcript.language ?? source.language ?? "nl",
    token_count: c.text.split(/\s+/).length
  }));

  if (rows.length > 0) {
    const { error: insErr } = await supabase.from("transcripts").insert(rows);
    if (insErr) return new Response(`Insert failed: ${insErr.message}`, { status: 500 });
  }

  await supabase.from("intakes")
    .update({ status: "transcribed" })
    .eq("id", source.intake_id);

  return new Response(
    JSON.stringify({
      ok: true,
      intake_id: source.intake_id,
      source_id: sourceId,
      chunks_inserted: rows.length,
      total_words: transcript.text.split(/\s+/).length
    }),
    { headers: { "content-type": "application/json" } }
  );
});
