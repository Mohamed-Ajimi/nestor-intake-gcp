// Edge Function: save-manual-synthesis
// Accepts a markdown body, uploads to Storage, inserts research_artifact.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const STORAGE_BUCKET = "nestor-uploads";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

  try {
    const body = await req.json();
    const { intake_id, research_question_id, filename, markdown, notes } = body;
    if (!intake_id || !filename || !markdown) {
      throw new Error("Missing intake_id, filename or markdown");
    }

    const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

    const storagePath = `manual-synthesis/${intake_id}/${filename}`;
    const bytes = new TextEncoder().encode(markdown);

    // 1. Storage upload
    const { error: uploadErr } = await supabase.storage
      .from(STORAGE_BUCKET)
      .upload(storagePath, bytes, { contentType: "text/markdown", upsert: true });
    if (uploadErr) throw new Error(`Storage upload failed: ${uploadErr.message}`);

    // 2. Insert research_artifact
    const { data: artifact, error: artErr } = await supabase
      .schema("nestor")
      .from("research_artifacts")
      .insert({
        intake_id,
        research_question_id: research_question_id ?? null,
        source: "manual_synthesis",
        artifact_type: "synthesis",
        filename,
        storage_bucket: STORAGE_BUCKET,
        storage_path: storagePath,
        mime_type: "text/markdown",
        text_content: markdown,
        byte_size: bytes.length,
        embed_status: "pending",
        notes: notes ?? "Manuele synthese door Nestor Ã¢ÂÂ combineert Apify/SerpAPI/SearchAPI snippets met body-content uit gefetchte URLs",
      })
      .select("id")
      .single();
    if (artErr) throw new Error(`Artifact insert failed: ${artErr.message}`);

    return new Response(
      JSON.stringify({ success: true, artifact_id: artifact.id, storage_path: storagePath, byte_size: bytes.length }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    return new Response(JSON.stringify({ success: false, error: errorMessage }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
