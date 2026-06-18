import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const FROM_EMAIL = "Nestor Sales <nestor@agenic.be>";
const REPLY_TO = "nestor@agenic.be";
const APP_BASE_URL = Deno.env.get("APP_BASE_URL") || "https://start-bloom-flow.lovable.app";
const ADMIN_DIGEST_EMAIL = Deno.env.get("ADMIN_DIGEST_EMAIL") || "yanick@agenic.be";
const LOGO_URL = "https://inmsssedwdmgtnhaydmg.supabase.co/storage/v1/object/public/email%20bucket%20public/Agenic%20Logo%20BW%20001.png";
const FLUO_PINK = "#FF2D87";
const FLUO_GREEN = "#BFEC40";
const INK = "#141414";
const PAPER_LIGHT = "#f4f1e8";
const PAPER = "#ece9e0";

const DEDUP_HOURS = 12;

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS_HEADERS });

  try {
    const resendKey = Deno.env.get("RESEND_API_KEY");
    if (!resendKey) return jsonError("RESEND_API_KEY not configured", 500);

    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

    let force = false;
    try {
      if (req.method === "POST") {
        const body = await req.json().catch(() => ({}));
        force = body?.force === true;
      }
    } catch (_) { /* ignore */ }

    async function salesRest<T>(method: string, path: string, body?: any): Promise<T> {
      const resp = await fetch(`${supabaseUrl}/rest/v1/${path}`, {
        method,
        headers: {
          "apikey": serviceKey,
          "Authorization": `Bearer ${serviceKey}`,
          "Content-Type": "application/json",
          "Accept-Profile": "sales",
          "Content-Profile": "sales",
          "Prefer": "return=representation",
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Sales REST ${method} ${path} failed: ${resp.status} ${txt}`);
      }
      return await resp.json() as T;
    }

    const nowIso = new Date().toISOString();
    const dedupCutoffIso = new Date(Date.now() - DEDUP_HOURS * 60 * 60 * 1000).toISOString();
    const sevenDaysIso = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();

    const preps: any[] = await salesRest<any[]>(
      "GET",
      `meeting_preps?meeting_datetime=gte.${nowIso}&meeting_datetime=lte.${sevenDaysIso}&status=neq.gearchiveerd&order=meeting_datetime.asc&select=*`
    );

    const sent: any[] = [];
    const failed: any[] = [];
    const skipped: any[] = [];

    for (const prep of preps) {
      // ATOMIC CLAIM: UPDATE met conditional WHERE.
      // Als geen rij teruggegeven Ã¢ÂÂ een andere worker heeft het al geclaimd binnen dedup-window.
      // Postgres row-lock zorgt voor serialisatie tussen parallelle requests.
      let claimedRows: any[] = [];
      try {
        if (force) {
          claimedRows = await salesRest<any[]>(
            "PATCH",
            `meeting_preps?id=eq.${prep.id}`,
            { last_reminder_sent_at: nowIso }
          );
        } else {
          claimedRows = await salesRest<any[]>(
            "PATCH",
            `meeting_preps?id=eq.${prep.id}&or=(last_reminder_sent_at.is.null,last_reminder_sent_at.lt.${dedupCutoffIso})`,
            { last_reminder_sent_at: nowIso }
          );
        }
      } catch (err: any) {
        failed.push({ prep_id: prep.id, error: `Atomic claim failed: ${err.message}` });
        continue;
      }

      if (!claimedRows || claimedRows.length === 0) {
        const hoursAgo = prep.last_reminder_sent_at
          ? ((Date.now() - new Date(prep.last_reminder_sent_at).getTime()) / (60 * 60 * 1000)).toFixed(1)
          : "?";
        skipped.push({
          prep_id: prep.id,
          klant_email: prep.klant_email,
          reason: `Already claimed (last reminder ${hoursAgo}h ago, dedup window: ${DEDUP_HOURS}h)`,
        });
        continue;
      }

      // Geclaimd Ã¢ÂÂ nu de mail versturen.
      try {
        const meetingDate = new Date(prep.meeting_datetime);
        const daysUntil = Math.ceil((meetingDate.getTime() - Date.now()) / (24 * 60 * 60 * 1000));
        const resultsLink = `${APP_BASE_URL}/sales/results/${prep.results_token}`;

        const html = renderReminderMail(prep, resultsLink, daysUntil);
        const subject = daysUntil === 0
          ? `[Vandaag] Meeting met ${prep.prospect_company_name}`
          : `[Over ${daysUntil} dag${daysUntil === 1 ? "" : "en"}] Meeting met ${prep.prospect_company_name}`;

        const resendResp = await fetch("https://api.resend.com/emails", {
          method: "POST",
          headers: { "Authorization": `Bearer ${resendKey}`, "Content-Type": "application/json" },
          body: JSON.stringify({
            from: FROM_EMAIL,
            to: [prep.klant_email],
            reply_to: REPLY_TO,
            subject,
            html,
          }),
        });

        if (resendResp.ok) {
          const data = await resendResp.json();
          sent.push({
            prep_id: prep.id,
            klant_email: prep.klant_email,
            prospect: prep.prospect_company_name,
            days_until: daysUntil,
            resend_id: data.id,
          });
        } else {
          const err = await resendResp.text();
          failed.push({ prep_id: prep.id, error: `${resendResp.status} ${err}` });
          // Send faalde Ã¢ÂÂ reset last_reminder_sent_at zodat we het later opnieuw kunnen proberen
          try {
            await salesRest("PATCH", `meeting_preps?id=eq.${prep.id}`, {
              last_reminder_sent_at: prep.last_reminder_sent_at,
            });
          } catch (_) { /* ignore reset failure */ }
        }
      } catch (err: any) {
        failed.push({ prep_id: prep.id, error: err.message });
        try {
          await salesRest("PATCH", `meeting_preps?id=eq.${prep.id}`, {
            last_reminder_sent_at: prep.last_reminder_sent_at,
          });
        } catch (_) { /* ignore */ }
      }
    }

    // Admin digest: alleen als er echt iets verstuurd is
    if (sent.length > 0) {
      const digestPreps = preps.filter(p => sent.some(s => s.prep_id === p.id));
      const digestHtml = renderAdminDigest(digestPreps, APP_BASE_URL);
      await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: { "Authorization": `Bearer ${resendKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          from: FROM_EMAIL,
          to: [ADMIN_DIGEST_EMAIL],
          reply_to: REPLY_TO,
          subject: `Nestor Sales Ã¢ÂÂ ${sent.length} meeting${sent.length === 1 ? "" : "s"} komende week`,
          html: digestHtml,
        }),
      });
    }

    return new Response(JSON.stringify({
      success: true,
      total: preps.length,
      sent_count: sent.length,
      failed_count: failed.length,
      skipped_count: skipped.length,
      dedup_window_hours: DEDUP_HOURS,
      forced: force,
      sent,
      failed,
      skipped,
    }), { headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });

  } catch (err: any) {
    return jsonError(err?.message || "Unknown error", 500);
  }
});

function baseLayout(inner: string, tagText: string = "NESTOR SALES Ã¢ÂÂ REMINDER"): string {
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:${PAPER};font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:#1e1e1e;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:${PAPER};padding:40px 20px;">
    <tr><td align="center">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="560" style="background:${PAPER_LIGHT};border:1px solid rgba(20,20,20,0.15);">
        <tr><td style="background:${FLUO_GREEN};height:4px;line-height:4px;font-size:4px;">&nbsp;</td></tr>
        <tr><td style="padding:28px 32px 20px;border-bottom:1px solid rgba(20,20,20,0.1);">
          <div style="font-family:'SF Mono',Monaco,Consolas,monospace;font-size:10px;text-transform:uppercase;letter-spacing:1.8px;color:${FLUO_PINK};margin-bottom:10px;font-weight:600;">${tagText}</div>
          <img src="${LOGO_URL}" alt="AGENIC" style="display:block;height:28px;width:auto;border:0;outline:none;" />
        </td></tr>
        <tr><td style="padding:32px;">${inner}</td></tr>
        <tr><td style="padding:16px 32px 24px;border-top:1px solid rgba(20,20,20,0.1);font-size:11px;color:rgba(20,20,20,0.5);">
          Vragen? <a href="mailto:nestor@agenic.be" style="color:rgba(20,20,20,0.6);text-decoration:underline;">nestor@agenic.be</a><br>
          <span style="font-family:'SF Mono',Monaco,Consolas,monospace;font-size:10px;">Agenic Ã¢ÂÂ Nestor Sales</span>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>`;
}

function primaryButton(label: string, link: string): string {
  return `<a href="${link}" style="display:inline-block;background:${INK};color:${PAPER_LIGHT};text-decoration:none;padding:14px 32px;font-family:'SF Mono',Monaco,Consolas,monospace;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;">${label}</a>`;
}

function renderReminderMail(prep: any, link: string, daysUntil: number): string {
  const dateFormatted = new Date(prep.meeting_datetime).toLocaleDateString("nl-BE", {
    weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit"
  });

  const urgencyTitle = daysUntil === 0
    ? "vandaag is de meeting"
    : daysUntil === 1
    ? "morgen heb je je meeting"
    : `over ${daysUntil} dagen heb je je meeting`;

  const battlecardStatus = prep.status === "geleverd"
    ? `<p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 24px;">Je battlecard is klaar om opnieuw door te nemen.</p>`
    : `<p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 24px;"><em>Heads-up: je battlecard wordt nog afgerond. Je krijgt een aparte mail zodra hij beschikbaar is.</em></p>`;

  return baseLayout(`
    <h1 style="font-family:Georgia,'Times New Roman',serif;font-size:28px;font-weight:normal;margin:0 0 16px;">${urgencyTitle}</h1>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 16px;">
      ${escape(prep.klant_name)}, je meeting met <strong>${escape(prep.prospect_company_name)}</strong>${prep.decision_maker_name ? ` (${escape(prep.decision_maker_name)})` : ""} staat gepland op <strong>${dateFormatted}</strong>.
    </p>
    ${battlecardStatus}
    ${prep.status === "geleverd" ? `<p style="margin:0 0 24px;">${primaryButton("Open je battlecard &rarr;", link)}</p>` : ""}
    <p style="font-size:12px;color:rgba(20,20,20,0.4);line-height:1.4;margin:24px 0 0;border-top:1px solid rgba(20,20,20,0.08);padding-top:16px;">
      Tips voor je laatste prep:<br>
      Ã¢ÂÂ¢ Bekijk blok 5 (Talking points) en blok 8 (Vragen om te stellen)<br>
      Ã¢ÂÂ¢ Check blok 9 (Risk flags) en mitigaties<br>
      Ã¢ÂÂ¢ Lees blok 10 (Next-step recommendation) voor je ideale uitkomst
    </p>
  `, "NESTOR SALES Ã¢ÂÂ REMINDER");
}

function renderAdminDigest(preps: any[], baseUrl: string): string {
  const rows = preps.map((p: any) => {
    const meetingDate = new Date(p.meeting_datetime);
    const dateFormatted = meetingDate.toLocaleDateString("nl-BE", {
      weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"
    });
    return `<tr>
      <td style="padding:8px 12px;border-bottom:1px solid rgba(20,20,20,0.1);font-size:13px;">
        <strong>${escape(p.klant_name)}</strong><br>
        <span style="color:rgba(20,20,20,0.5);font-size:11px;">${escape(p.klant_company)}</span>
      </td>
      <td style="padding:8px 12px;border-bottom:1px solid rgba(20,20,20,0.1);font-size:13px;">${escape(p.prospect_company_name)}</td>
      <td style="padding:8px 12px;border-bottom:1px solid rgba(20,20,20,0.1);font-size:13px;">${dateFormatted}</td>
      <td style="padding:8px 12px;border-bottom:1px solid rgba(20,20,20,0.1);font-size:11px;text-transform:uppercase;font-family:'SF Mono',Monaco,Consolas,monospace;">${p.status}</td>
      <td style="padding:8px 12px;border-bottom:1px solid rgba(20,20,20,0.1);font-size:12px;">
        <a href="${baseUrl}/admin/sales/projects/${p.id}" style="color:${FLUO_PINK};text-decoration:underline;">Open &rarr;</a>
      </td>
    </tr>`;
  }).join("");

  return baseLayout(`
    <h1 style="font-family:Georgia,'Times New Roman',serif;font-size:28px;font-weight:normal;margin:0 0 16px;">deze week ${preps.length} meeting${preps.length === 1 ? "" : "s"}</h1>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 24px;">
      Overzicht van de Nestor Sales-projecten met meetings de komende 7 dagen. Klanten kregen ook een reminder met hun battlecard-link.
    </p>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
      <thead>
        <tr style="background:rgba(20,20,20,0.04);">
          <th style="text-align:left;padding:8px 12px;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(20,20,20,0.6);font-family:'SF Mono',Monaco,Consolas,monospace;">Klant</th>
          <th style="text-align:left;padding:8px 12px;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(20,20,20,0.6);font-family:'SF Mono',Monaco,Consolas,monospace;">Prospect</th>
          <th style="text-align:left;padding:8px 12px;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(20,20,20,0.6);font-family:'SF Mono',Monaco,Consolas,monospace;">Meeting</th>
          <th style="text-align:left;padding:8px 12px;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(20,20,20,0.6);font-family:'SF Mono',Monaco,Consolas,monospace;">Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `, "NESTOR SALES Ã¢ÂÂ DIGEST");
}

function escape(s: string | null): string {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
}

function jsonError(msg: string, status = 500) {
  return new Response(JSON.stringify({ error: msg }), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}
