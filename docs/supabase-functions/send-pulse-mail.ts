import { createClient } from 'jsr:@supabase/supabase-js@2';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

const LOGO_URL = 'https://inmsssedwdmgtnhaydmg.supabase.co/storage/v1/object/public/email%20bucket%20public/Agenic%20Logo%20BW%20001.png';
const BASE_URL = Deno.env.get('NESTOR_BASE_URL') ?? 'https://start-bloom-flow.lovable.app';
const ADMIN_EMAIL = Deno.env.get('NESTOR_ADMIN_EMAIL') ?? 'yanick@agenic.be';
const FROM = 'Nestor Pulse <nestor@agenic.be>';

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response(null, { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'Use POST' }, 405);

  let body: any;
  try { body = await req.json(); }
  catch { return json({ error: 'Invalid JSON' }, 400); }

  const { intake_id, mail_type, override_email } = body;
  if (!intake_id || !mail_type) return json({ error: 'intake_id and mail_type required' }, 400);

  const supa = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );

  // Fetch intake + client + organization
  const { data: intake, error: intakeErr } = await supa
    .schema('nestor')
    .from('intakes')
    .select('id, title, status, client_validation_token, client_results_token, validation_link_sent_at, results_link_sent_at, client_id')
    .eq('id', intake_id)
    .maybeSingle();

  if (intakeErr || !intake) return json({ error: 'Intake not found', detail: intakeErr?.message }, 404);

  const { data: client } = await supa
    .from('clients')
    .select('name, primary_contact_name, primary_contact_email')
    .eq('id', intake.client_id)
    .maybeSingle();

  // Build mail content based on mail_type
  let to: string | null = null;
  let subject = '';
  let html = '';
  let timestampField: 'validation_link_sent_at' | 'results_link_sent_at' | null = null;

  const projectTitle = intake.title || 'jullie project';
  const clientName = client?.name ?? 'klant';
  const firstName = client?.primary_contact_name?.split(' ')[0] ?? '';

  if (mail_type === 'validation_request' || mail_type === 'validation_reminder') {
    to = override_email ?? client?.primary_contact_email ?? null;
    if (!to) return json({ error: 'No client email available. Set primary_contact_email or pass override_email.' }, 400);
    const url = `${BASE_URL}/intake/${intake.client_validation_token}`;
    const isReminder = mail_type === 'validation_reminder';
    subject = isReminder
      ? `Herinnering Ã¢ÂÂ onderzoeksvragen wachten op validatie (${clientName})`
      : `Even valideren Ã¢ÂÂ onderzoeksvragen voor ${clientName}`;
    html = buildValidationHtml({ firstName, projectTitle, url, isReminder });
    if (!isReminder) timestampField = 'validation_link_sent_at';
  } else if (mail_type === 'results_ready') {
    to = override_email ?? client?.primary_contact_email ?? null;
    if (!to) return json({ error: 'No client email available. Set primary_contact_email or pass override_email.' }, 400);
    const url = `${BASE_URL}/results/${intake.client_results_token}`;
    subject = `Onderzoeksresultaten klaar Ã¢ÂÂ ${clientName}`;
    html = buildResultsHtml({ firstName, projectTitle, url });
    timestampField = 'results_link_sent_at';
  } else if (mail_type === 'admin_validated') {
    to = override_email ?? ADMIN_EMAIL;
    const url = `${BASE_URL}/intakes/${intake.id}`;
    subject = `[Nestor Pulse] Klant heeft gevalideerd Ã¢ÂÂ ${clientName}`;
    html = buildAdminValidatedHtml({ clientName, projectTitle, url });
  } else {
    return json({ error: `Unknown mail_type: ${mail_type}` }, 400);
  }

  // Send via Resend
  const resendKey = Deno.env.get('RESEND_API_KEY');
  if (!resendKey) return json({ error: 'RESEND_API_KEY missing' }, 500);

  const resendResp = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${resendKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ from: FROM, to: [to], subject, html }),
  });

  if (!resendResp.ok) {
    const detail = await resendResp.text();
    return json({ error: 'Resend failed', detail, status: resendResp.status }, 502);
  }

  const sendData = await resendResp.json().catch(() => ({}));

  // Update timestamp
  if (timestampField) {
    await supa
      .schema('nestor')
      .from('intakes')
      .update({ [timestampField]: new Date().toISOString() })
      .eq('id', intake_id);
  }

  return json({ ok: true, to, mail_type, resend_id: sendData?.id ?? null });
});

function json(body: any, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });
}

function styles() {
  return `
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; background: #f7f7f7; color: #141414; }
    .card { background: white; padding: 32px; border-top: 4px solid #BFEC40; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,.04); }
    .logo { max-width: 110px; height: auto; margin-bottom: 24px; }
    .tag { background: #FF2D87; color: white; padding: 4px 10px; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; font-weight: bold; display: inline-block; margin-bottom: 16px; }
    h1 { font-size: 22px; margin: 0 0 16px; line-height: 1.3; }
    p { line-height: 1.6; margin: 0 0 14px; font-size: 15px; }
    .btn { display: inline-block; background: #141414; color: white !important; text-decoration: none; padding: 14px 28px; border-radius: 4px; margin-top: 8px; font-weight: 500; }
    .footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e5e5; font-size: 12px; color: #666; line-height: 1.5; }
    ul { line-height: 1.7; }
  `;
}

function buildValidationHtml(p: { firstName: string; projectTitle: string; url: string; isReminder: boolean }) {
  const greeting = p.isReminder ? 'Korte herinnering' : `Hi ${p.firstName || 'team'}`;
  const intro = p.isReminder
    ? 'Eerder stuurden we de gevalideerde onderzoeksvragen door Ã¢ÂÂ heb je even tijd om ze door te lezen en goed te keuren?'
    : 'We hebben jullie intake doorgenomen en de onderzoeksvragen verfijnd. Plus we stelden enkele extra strategische vragen voor die jullie context scherper kunnen maken. Even bekijken en bevestigen?';
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>${styles()}</style></head>
<body><div class="card">
<img src="${LOGO_URL}" alt="Agenic" class="logo" />
<div class="tag">Nestor Pulse</div>
<h1>${greeting}</h1>
<p>${intro}</p>
<p>Het duurt ongeveer 10 minuten. Je ziet per vraag onze aangescherpte versie, plus eventuele extra vragen die we voorstellen. Per vraag kies je: <strong>goedkeuren</strong>, <strong>aanpassen</strong> of <strong>afkeuren</strong>.</p>
<p style="margin-top: 24px;"><a href="${p.url}" class="btn">Open validatie-pagina Ã¢ÂÂ</a></p>
<p style="margin-top: 24px;">Geen haast, maar zonder validatie kunnen we de research niet starten. Bij vragen of onduidelijkheden Ã¢ÂÂ gewoon reply op deze mail.</p>
<p style="margin-top: 24px;">Ã¢ÂÂ Team Agenic</p>
<div class="footer">Deze link is uniek voor jullie project (${p.projectTitle}). Niet delen met derden.</div>
</div></body></html>`;
}

function buildResultsHtml(p: { firstName: string; projectTitle: string; url: string }) {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>${styles()}</style></head>
<body><div class="card">
<img src="${LOGO_URL}" alt="Agenic" class="logo" />
<div class="tag">Nestor Pulse</div>
<h1>De onderzoeksresultaten staan klaar</h1>
<p>Hi ${p.firstName || 'team'},</p>
<p>Het onderzoek voor <strong>${p.projectTitle}</strong> is afgerond. Het volledige rapport ÃÂ©n de onderliggende research-artifacts staan klaar in jullie portaal.</p>
<p style="margin-top: 24px;"><a href="${p.url}" class="btn">Open resultaten Ã¢ÂÂ</a></p>
<p style="margin-top: 24px;">In het portaal vinden jullie:</p>
<ul>
<li>Het strategische rapport (download als PDF of DOCX)</li>
<li>De onderliggende bronnen per onderzoeksvraag</li>
<li>Een semantische zoekfunctie om alle research te doorzoeken</li>
</ul>
<p>Bij vragen of als je een werksessie wil om de resultaten samen door te lopen Ã¢ÂÂ gewoon reply op deze mail.</p>
<p style="margin-top: 24px;">Ã¢ÂÂ Team Agenic</p>
<div class="footer">Deze link blijft actief zolang het project loopt.</div>
</div></body></html>`;
}

function buildAdminValidatedHtml(p: { clientName: string; projectTitle: string; url: string }) {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>${styles()}</style></head>
<body><div class="card">
<img src="${LOGO_URL}" alt="Agenic" class="logo" />
<div class="tag">Nestor Pulse Ã¢ÂÂ Admin</div>
<h1>Klant heeft gevalideerd</h1>
<p><strong>${p.clientName}</strong> heeft de intake gevalideerd voor project &ldquo;${p.projectTitle}&rdquo;.</p>
<p>Status: <code>validated_by_client</code></p>
<p>Volgende stap: Context Pack genereren en research starten.</p>
<p style="margin-top: 24px;"><a href="${p.url}" class="btn">Open intake in admin Ã¢ÂÂ</a></p>
</div></body></html>`;
}
