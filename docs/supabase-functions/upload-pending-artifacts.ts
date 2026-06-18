import { createClient } from 'jsr:@supabase/supabase-js@2';

Deno.serve(async (req: Request) => {
  if (req.method !== 'POST') {
    return new Response('Use POST', { status: 405 });
  }

  const body = await req.json().catch(() => ({}));
  const intakeId: string | undefined = body.intake_id;
  const sourceFilter: string = body.source_filter ?? 'apify-%';

  if (!intakeId) {
    return new Response(JSON.stringify({ error: 'intake_id required' }), { status: 400, headers: { 'Content-Type': 'application/json' } });
  }

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );

  // Fetch artifacts that need uploading
  const { data: artifacts, error: fetchErr } = await supabase
    .schema('nestor')
    .from('research_artifacts')
    .select('id, source, filename, storage_bucket, storage_path, text_content, mime_type')
    .eq('intake_id', intakeId)
    .like('source', sourceFilter)
    .not('text_content', 'is', null);

  if (fetchErr) {
    return new Response(JSON.stringify({ error: fetchErr.message }), { status: 500, headers: { 'Content-Type': 'application/json' } });
  }

  const results: any[] = [];
  for (const a of artifacts ?? []) {
    try {
      const blob = new Blob([a.text_content ?? ''], { type: a.mime_type ?? 'text/markdown' });
      const { error: upErr } = await supabase.storage
        .from(a.storage_bucket ?? 'nestor-uploads')
        .upload(a.storage_path, blob, { upsert: true, contentType: a.mime_type ?? 'text/markdown' });
      results.push({ id: a.id, filename: a.filename, ok: !upErr, error: upErr?.message ?? null });
    } catch (e) {
      results.push({ id: a.id, filename: a.filename, ok: false, error: String(e) });
    }
  }

  const ok = results.filter(r => r.ok).length;
  const failed = results.length - ok;

  return new Response(
    JSON.stringify({ intake_id: intakeId, total: results.length, ok, failed, results }, null, 2),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
});
