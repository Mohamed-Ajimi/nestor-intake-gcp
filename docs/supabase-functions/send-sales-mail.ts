import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const FROM_EMAIL = "Nestor Sales <nestor@agenic.be>";
const REPLY_TO = "nestor@agenic.be";
const APP_BASE_URL = Deno.env.get("APP_BASE_URL") || "https://start-bloom-flow.lovable.app";
const ADMIN_NOTIFY_EMAIL = Deno.env.get("ADMIN_NOTIFY_EMAIL") || "nestor@agenic.be";
const LOGO_URL = "https://inmsssedwdmgtnhaydmg.supabase.co/storage/v1/object/public/email%20bucket%20public/Agenic%20Logo%20BW%20001.png";
const FLUO_PINK = "#FF2D87";
const FLUO_GREEN = "#BFEC40";
const INK = "#141414";
const PAPER_LIGHT = "#f4f1e8";
const PAPER = "#ece9e0";

const VALID_TYPES = [
  "intake", "validation", "results",
  "admin_intake_submitted", "admin_validated", "admin_results_opened",
  "admin_research_ready", "admin_research_failed",
] as const;
type MailType = typeof VALID_TYPES[number];

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS_HEADERS });

  try {
    const { prep_id, mail_type } = await req.json();
    if (!prep_id || !mail_type) return jsonError("Missing prep_id or mail_type", 400);
    if (!VALID_TYPES.includes(mail_type)) {
      return jsonError(`Invalid mail_type. Must be one of: ${VALID_TYPES.join(" | ")}`, 400);
    }

    const resendKey = Deno.env.get("RESEND_API_KEY");
    if (!resendKey) return jsonError("RESEND_API_KEY not configured", 500);

    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

    async function salesRest<T>(method: string, path: string, body?: any): Promise<T | null> {
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

    const preps: any[] = (await salesRest<any[]>("GET", `meeting_preps?id=eq.${prep_id}&select=*`)) || [];
    if (preps.length === 0) return jsonError("Prep not found", 404);
    const prep = preps[0];

    // Voor admin_research_* ook battlecard ophalen (voor timing + error info)
    let battlecard: any = null;
    if (mail_type === "admin_research_ready" || mail_type === "admin_research_failed") {
      const bcs: any[] = (await salesRest<any[]>("GET", `battlecards?meeting_prep_id=eq.${prep_id}&select=*`)) || [];
      battlecard = bcs[0] || null;
    }

    let subject = "";
    let html = "";
    let updateField = "";
    let recipient = prep.klant_email;
    const adminLink = `${APP_BASE_URL}/admin/sales/projects/${prep.id}`;

    if (mail_type === "intake") {
      const link = `${APP_BASE_URL}/sales/intake/${prep.intake_token}`;
      subject = `Nestor Sales Ã¢ÂÂ Je meeting-prep voor ${prep.prospect_company_name || "je volgende meeting"}`;
      html = renderIntakeMail(prep, link);
      updateField = "intake_sent_at";
    } else if (mail_type === "validation") {
      const link = `${APP_BASE_URL}/sales/validate/${prep.validation_token}`;
      subject = `Nestor Sales Ã¢ÂÂ Validatie van je intake (${prep.prospect_company_name || "meeting-prep"})`;
      html = renderValidationMail(prep, link);
      updateField = "validation_sent_at";
    } else if (mail_type === "results") {
      const link = `${APP_BASE_URL}/sales/results/${prep.results_token}`;
      subject = `Nestor Sales Ã¢ÂÂ Je battlecard voor ${prep.prospect_company_name} is klaar`;
      html = renderResultsMail(prep, link);
      updateField = "";
    } else if (mail_type === "admin_intake_submitted") {
      recipient = ADMIN_NOTIFY_EMAIL;
      subject = `Nestor Sales Ã¢ÂÂ ${prep.klant_name || "Klant"} heeft intake ingevuld voor ${prep.prospect_company_name || "meeting"}`;
      html = renderAdminMail({
        prep, adminLink,
        title: "intake ingevuld",
        intro: `<strong>${escape(prep.klant_name || "De klant")}</strong> heeft zonet de intake ingevuld voor <strong>${escape(prep.prospect_company_name || "een meeting")}</strong>. Tijd om te reviewen en, indien nodig, aan te scherpen.`,
        cta: "Open in admin",
        tagText: "NESTOR SALES Ã¢ÂÂ ADMIN",
      });
      updateField = "";
    } else if (mail_type === "admin_validated") {
      recipient = ADMIN_NOTIFY_EMAIL;
      subject = `Nestor Sales Ã¢ÂÂ ${prep.klant_name || "Klant"} heeft gevalideerd, klaar voor research`;
      html = renderAdminMail({
        prep, adminLink,
        title: "klant heeft gevalideerd",
        intro: `<strong>${escape(prep.klant_name || "De klant")}</strong> heeft je review goedgekeurd voor <strong>${escape(prep.prospect_company_name || "de meeting")}</strong>. De prep is klaar om de research te starten.`,
        cta: "Start research Ã¢ÂÂ",
        tagText: "NESTOR SALES Ã¢ÂÂ ADMIN",
      });
      updateField = "";
    } else if (mail_type === "admin_results_opened") {
      recipient = ADMIN_NOTIFY_EMAIL;
      subject = `Nestor Sales Ã¢ÂÂ ${prep.klant_name || "Klant"} heeft de battlecard geopened`;
      html = renderAdminMail({
        prep, adminLink,
        title: "battlecard geopened",
        intro: `<strong>${escape(prep.klant_name || "De klant")}</strong> heeft zonet de battlecard voor <strong>${escape(prep.prospect_company_name || "de meeting")}</strong> geopened. Goed moment voor een korte check-in vlak voor de meeting.`,
        cta: "Open in admin",
        tagText: "NESTOR SALES Ã¢ÂÂ ADMIN",
      });
      updateField = "";
    } else if (mail_type === "admin_research_ready") {
      recipient = ADMIN_NOTIFY_EMAIL;
      subject = `Nestor Sales Ã¢ÂÂ Battlecard klaar voor ${prep.prospect_company_name || "meeting"}`;
      const blockCount = battlecard?.blocks ? Object.keys(battlecard.blocks).length : 0;
      const tokenInfo = battlecard?.completion_tokens
        ? `<br><span style="font-size:11px;color:rgba(20,20,20,0.45);">${battlecard.completion_tokens.toLocaleString()} tokens ÃÂ· ${blockCount} blokken ÃÂ· model: ${battlecard.model_used || "?"}</span>`
        : "";
      html = renderAdminMail({
        prep, adminLink,
        title: "battlecard is klaar",
        intro: `De Nestor Sales research voor <strong>${escape(prep.prospect_company_name || "de meeting")}</strong> is afgerond. ${blockCount} blokken gegenereerd, klaar om te reviewen en te leveren aan ${escape(prep.klant_name || "de klant")}.${tokenInfo}`,
        cta: "Bekijk battlecard Ã¢ÂÂ",
        tagText: "NESTOR SALES Ã¢ÂÂ RESEARCH READY",
      });
      updateField = "";
    } else if (mail_type === "admin_research_failed") {
      recipient = ADMIN_NOTIFY_EMAIL;
      subject = `Nestor Sales Ã¢ÂÂ Ã¢ÂÂ  Battlecard-generatie FAALDE voor ${prep.prospect_company_name || "meeting"}`;
      const errorMsg = battlecard?.generation_error || "Onbekende fout Ã¢ÂÂ check logs";
      html = renderAdminMail({
        prep, adminLink,
        title: "battlecard-generatie faalde",
        intro: `De research voor <strong>${escape(prep.prospect_company_name || "de meeting")}</strong> is gestopt door een fout. Open admin om opnieuw te starten of de logs te bekijken.<br><br><strong>Fout:</strong><br><code style="display:block;background:rgba(20,20,20,0.05);padding:8px;font-size:11px;margin-top:6px;font-family:'SF Mono',Monaco,Consolas,monospace;">${escape(errorMsg.slice(0, 500))}</code>`,
        cta: "Open in admin",
        tagText: "NESTOR SALES Ã¢ÂÂ RESEARCH FAILED",
      });
      updateField = "";
    }

    const resendResp = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${resendKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: FROM_EMAIL,
        to: [recipient],
        reply_to: REPLY_TO,
        subject,
        html,
      }),
    });

    if (!resendResp.ok) {
      const errText = await resendResp.text();
      return jsonError(`Resend API failed: ${resendResp.status} ${errText}`, 500);
    }

    const resendData = await resendResp.json();

    if (updateField) {
      await salesRest("PATCH", `meeting_preps?id=eq.${prep_id}`, { [updateField]: new Date().toISOString() });
    }

    return new Response(JSON.stringify({
      success: true,
      resend_id: resendData.id,
      mail_type,
      recipient,
    }), { headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });

  } catch (err: any) {
    return jsonError(err?.message || "Unknown error", 500);
  }
});

function baseLayout(inner: string, tagText: string = "NESTOR SALES"): string {
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

function fallbackLink(link: string): string {
  return `<p style="font-size:12px;color:rgba(20,20,20,0.4);line-height:1.4;margin:24px 0 0;border-top:1px solid rgba(20,20,20,0.08);padding-top:16px;">
      Werkt de knop niet? Kopieer deze link:<br>
      <span style="font-family:'SF Mono',Monaco,Consolas,monospace;font-size:11px;word-break:break-all;">${link}</span>
    </p>`;
}

function renderIntakeMail(prep: any, link: string): string {
  return baseLayout(`
    <h1 style="font-family:Georgia,'Times New Roman',serif;font-size:28px;font-weight:normal;margin:0 0 16px;">dag ${escape(prep.klant_name)}</h1>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 16px;">
      Je hebt via Agenic een Nestor Sales battlecard aangevraagd. Vul deze korte intake in zodat we voor jou de perfecte voorbereiding kunnen maken voor je volgende verkoopgesprek.
    </p>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 24px;">
      Het duurt ongeveer 5 minuten. Je kan tussendoor opslaan als concept en later afmaken.
    </p>
    <p style="margin:0 0 24px;">${primaryButton("Vul je intake in &rarr;", link)}</p>
    ${fallbackLink(link)}
  `, "NESTOR SALES Ã¢ÂÂ INTAKE");
}

function renderValidationMail(prep: any, link: string): string {
  return baseLayout(`
    <h1 style="font-family:Georgia,'Times New Roman',serif;font-size:28px;font-weight:normal;margin:0 0 16px;">dag ${escape(prep.klant_name)}</h1>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 16px;">
      Agenic heeft je intake gereviewd en, waar nodig, aangevuld of aangescherpt. Bekijk de finale versie en geef je akkoord Ã¢ÂÂ daarna start onze research voor je battlecard.
    </p>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 24px;">
      Niet akkoord met iets? Laat het ons gewoon weten via mail, we passen het aan.
    </p>
    <p style="margin:0 0 24px;">${primaryButton("Bekijk &amp; valideer &rarr;", link)}</p>
    ${fallbackLink(link)}
  `, "NESTOR SALES Ã¢ÂÂ VALIDATIE");
}

function renderResultsMail(prep: any, link: string): string {
  return baseLayout(`
    <h1 style="font-family:Georgia,'Times New Roman',serif;font-size:28px;font-weight:normal;margin:0 0 16px;">je battlecard is klaar</h1>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 16px;">
      ${escape(prep.klant_name)}, je battlecard voor de meeting met <strong>${escape(prep.prospect_company_name || "je prospect")}</strong>${prep.decision_maker_name ? ` (${escape(prep.decision_maker_name)})` : ""} staat klaar om te downloaden.
    </p>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 24px;">
      10 strategische blokken, talking points, anticipated objections en risk-flags. Klaar om mee de vergadering in te stappen.
    </p>
    <p style="margin:0 0 24px;">${primaryButton("Download je battlecard &rarr;", link)}</p>
    ${fallbackLink(link)}
  `, "NESTOR SALES Ã¢ÂÂ BATTLECARD");
}

function renderAdminMail(opts: {
  prep: any;
  adminLink: string;
  title: string;
  intro: string;
  cta: string;
  tagText: string;
}): string {
  const { prep, adminLink, title, intro, cta, tagText } = opts;

  const infoRows: string[] = [];
  if (prep.klant_name) infoRows.push(row("Klant", `<strong>${escape(prep.klant_name)}</strong>${prep.klant_company ? ` Ã¢ÂÂ ${escape(prep.klant_company)}` : ""}`));
  if (prep.klant_email) infoRows.push(row("Email", `<a href="mailto:${escape(prep.klant_email)}" style="color:#141414;">${escape(prep.klant_email)}</a>`));
  if (prep.prospect_company_name) infoRows.push(row("Prospect", `<strong>${escape(prep.prospect_company_name)}</strong>`));
  if (prep.decision_maker_name) infoRows.push(row("Decision maker", `${escape(prep.decision_maker_name)}${prep.decision_maker_role ? ` Ã¢ÂÂ ${escape(prep.decision_maker_role)}` : ""}`));
  if (prep.meeting_datetime) {
    const md = new Date(prep.meeting_datetime).toLocaleDateString("nl-BE", {
      weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit"
    });
    infoRows.push(row("Meeting", escape(md)));
  }
  if (prep.meeting_type) infoRows.push(rowMono("Type", escape(prep.meeting_type)));
  if (prep.deal_stage) infoRows.push(rowMono("Deal stage", escape(prep.deal_stage)));
  const stakes = Array.isArray(prep.additional_stakeholders) ? prep.additional_stakeholders.length : 0;
  if (stakes > 0) infoRows.push(row("Stakeholders", `<strong>${stakes + 1}</strong> personen aan tafel`));

  return baseLayout(`
    <h1 style="font-family:Georgia,'Times New Roman',serif;font-size:28px;font-weight:normal;margin:0 0 16px;">${title}</h1>
    <p style="font-size:15px;line-height:1.5;color:rgba(20,20,20,0.75);margin:0 0 16px;">${intro}</p>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:24px 0;border-top:1px solid rgba(20,20,20,0.1);border-bottom:1px solid rgba(20,20,20,0.1);padding:8px 0;">
      ${infoRows.join("")}
    </table>
    <p style="margin:24px 0 24px;">${primaryButton(escape(cta), adminLink)}</p>
    ${fallbackLink(adminLink)}
  `, tagText);
}

function row(label: string, value: string): string {
  return `<tr><td style="padding:4px 0;color:rgba(20,20,20,0.55);font-size:12px;width:130px;">${label}</td><td style="padding:4px 0;font-size:13px;">${value}</td></tr>`;
}
function rowMono(label: string, value: string): string {
  return `<tr><td style="padding:4px 0;color:rgba(20,20,20,0.55);font-size:12px;width:130px;">${label}</td><td style="padding:4px 0;font-size:13px;font-family:'SF Mono',Monaco,Consolas,monospace;">${value}</td></tr>`;
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
