import { jsPDF } from 'jspdf';

// ---- Design tokens ---------------------------------------------------------
const INK         = [20, 20, 20]    as const;
const INK_60      = [102, 102, 102] as const;
const INK_40      = [153, 153, 153] as const;
const INK_20      = [204, 204, 204] as const;
const FLUO_PINK   = [255, 45, 135]  as const;
const FLUO_GREEN  = [191, 236, 64]  as const;
const FLUO_YELLOW = [246, 230, 0]   as const;
const FLUO_RED    = [255, 45, 58]   as const;

// Page geometry (A4 in mm)
const PAGE_W = 210;
const PAGE_H = 297;
const MARGIN = 18;
const CONTENT_W = PAGE_W - 2 * MARGIN;
const BOTTOM_LIMIT = PAGE_H - 18;

// Category mapping
const CATEGORIES = [
  { id: 'context',     label: 'de context' },
  { id: 'analyse',     label: 'de analyse' },
  { id: 'aanpak',      label: 'de aanpak' },
  { id: 'onverwachte', label: 'het onverwachte' },
] as const;

const MEETING_TYPE_LABELS: Record<string, string> = {
  discovery: 'Discovery',
  demo: 'Demo',
  follow_up: 'Follow-up',
  executive_pitch: 'Executive pitch',
  renewal: 'Renewal',
  win_back: 'Win-back',
};
const DEAL_STAGE_LABELS: Record<string, string> = {
  new: 'New',
  qualified: 'Qualified',
  proposal: 'Proposal',
  negotiation: 'Negotiation',
  decision: 'Decision',
};
const KLANT_TYPE_LABELS: Record<string, string> = {
  new_client: 'Nieuwe klant',
  existing_client: 'Bestaande klant',
};

// ---- State (cursor positie) ------------------------------------------------
type PdfCtx = {
  doc: jsPDF;
  y: number;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyObj = Record<string, any>;

function ensureSpace(ctx: PdfCtx, neededMm: number) {
  if (ctx.y + neededMm > BOTTOM_LIMIT) {
    ctx.doc.addPage();
    ctx.y = MARGIN;
  }
}

function setFont(ctx: PdfCtx, family: 'serif' | 'sans' | 'mono', style: 'normal' | 'bold' | 'italic' = 'normal') {
  const fam = family === 'serif' ? 'times' : family === 'mono' ? 'courier' : 'helvetica';
  ctx.doc.setFont(fam, style);
}

function setColor(ctx: PdfCtx, rgb: readonly [number, number, number]) {
  ctx.doc.setTextColor(rgb[0], rgb[1], rgb[2]);
}

// ---- Inline-text-renderer met markers + confidence pills -------------------
type Token =
  | { type: 'text'; value: string }
  | { type: 'marker'; symbol: 'v' | '!' | '?' | 'x' }
  | { type: 'conf'; level: 'H' | 'M' };

function tokenize(text: string): Token[] {
  const tokens: Token[] = [];
  const regex = /\[(v|!|\?|x|H|M)\]/g;
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > lastIndex) {
      tokens.push({ type: 'text', value: text.slice(lastIndex, m.index) });
    }
    const ch = m[1];
    if (ch === 'H' || ch === 'M') {
      tokens.push({ type: 'conf', level: ch });
    } else {
      tokens.push({ type: 'marker', symbol: ch as 'v' | '!' | '?' | 'x' });
    }
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) {
    tokens.push({ type: 'text', value: text.slice(lastIndex) });
  }
  return tokens;
}

const MARKER_COLORS: Record<string, readonly [number, number, number]> = {
  v: FLUO_GREEN,
  '!': FLUO_PINK,
  '?': FLUO_YELLOW,
  x: FLUO_RED,
};
const MARKER_SYMBOL: Record<string, string> = { v: 'v', '!': '!', '?': '?', x: 'x' };

function drawMarker(ctx: PdfCtx, x: number, y: number, symbol: 'v' | '!' | '?' | 'x'): number {
  const SIZE = 3.2;
  const color = MARKER_COLORS[symbol];
  ctx.doc.setFillColor(color[0], color[1], color[2]);
  ctx.doc.rect(x, y - SIZE + 0.4, SIZE, SIZE, 'F');
  ctx.doc.setTextColor(INK[0], INK[1], INK[2]);
  ctx.doc.setFont('helvetica', 'bold');
  ctx.doc.setFontSize(7);
  ctx.doc.text(MARKER_SYMBOL[symbol], x + SIZE / 2, y - 0.5, { align: 'center' });
  return SIZE + 1.2;
}

function drawConfPill(ctx: PdfCtx, x: number, y: number, level: 'H' | 'M'): number {
  const W = 3.4, H = 2.8;
  const c = level === 'H' ? INK_60 : INK_40;
  ctx.doc.setDrawColor(c[0], c[1], c[2]);
  ctx.doc.setLineWidth(0.15);
  ctx.doc.rect(x, y - H + 0.4, W, H, 'S');
  ctx.doc.setTextColor(c[0], c[1], c[2]);
  ctx.doc.setFont('courier', 'bold');
  ctx.doc.setFontSize(6.5);
  ctx.doc.text(level, x + W / 2, y - 0.6, { align: 'center' });
  return W + 1;
}

function renderRichText(ctx: PdfCtx, text: string, opts: {
  x?: number;
  width?: number;
  fontSize?: number;
  lineHeight?: number;
  color?: readonly [number, number, number];
} = {}) {
  const x0 = opts.x ?? MARGIN;
  const width = opts.width ?? CONTENT_W;
  const fontSize = opts.fontSize ?? 9;
  const lineHeight = opts.lineHeight ?? 4.6;
  const color = opts.color ?? INK;

  const lines = text.split(/\r?\n/);

  for (const rawLine of lines) {
    if (!rawLine.trim()) {
      ctx.y += lineHeight * 0.6;
      continue;
    }

    ensureSpace(ctx, lineHeight + 2);

    let lineText = rawLine;
    let bulletPrefix = '';
    const bulletMatch = lineText.match(/^(\s*[-•]\s+)/);
    if (bulletMatch) {
      bulletPrefix = bulletMatch[1].replace(/[-•]/g, '·');
      lineText = lineText.slice(bulletMatch[0].length);
    }

    let isHeading = false;
    if (lineText.startsWith('### ')) {
      isHeading = true;
      lineText = lineText.slice(4);
    } else if (lineText.startsWith('## ')) {
      isHeading = true;
      lineText = lineText.slice(3);
    }

    setFont(ctx, isHeading ? 'serif' : 'sans', isHeading ? 'bold' : 'normal');
    ctx.doc.setFontSize(isHeading ? 11 : fontSize);
    setColor(ctx, color);

    let cursorX = x0;
    let lineY = ctx.y;
    const tokens = tokenize(bulletPrefix + lineText);

    for (const tok of tokens) {
      if (tok.type === 'marker') {
        const advance = drawMarker(ctx, cursorX, lineY, tok.symbol);
        cursorX += advance;
        setFont(ctx, isHeading ? 'serif' : 'sans', isHeading ? 'bold' : 'normal');
        ctx.doc.setFontSize(isHeading ? 11 : fontSize);
        setColor(ctx, color);
        continue;
      }
      if (tok.type === 'conf') {
        const advance = drawConfPill(ctx, cursorX, lineY, tok.level);
        cursorX += advance;
        setFont(ctx, isHeading ? 'serif' : 'sans', isHeading ? 'bold' : 'normal');
        ctx.doc.setFontSize(isHeading ? 11 : fontSize);
        setColor(ctx, color);
        continue;
      }
      const parts = splitBold(tok.value);
      for (const part of parts) {
        setFont(ctx, isHeading ? 'serif' : 'sans', (isHeading || part.bold) ? 'bold' : 'normal');
        ctx.doc.setFontSize(isHeading ? 11 : fontSize);
        setColor(ctx, color);

        const words = part.text.split(/(\s+)/);
        for (const w of words) {
          if (!w) continue;
          const ww = ctx.doc.getTextWidth(w);
          if (cursorX + ww > x0 + width) {
            ctx.y = lineY + lineHeight;
            ensureSpace(ctx, lineHeight + 2);
            lineY = ctx.y;
            cursorX = x0 + (bulletPrefix ? 3 : 0);
            if (w.match(/^\s+$/)) continue;
          }
          ctx.doc.text(w, cursorX, lineY);
          cursorX += ww;
        }
      }
    }

    ctx.y = lineY + lineHeight;
  }
}

function splitBold(text: string): { text: string; bold: boolean }[] {
  const parts: { text: string; bold: boolean }[] = [];
  const regex = /\*\*([^*]+)\*\*/g;
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > lastIndex) {
      parts.push({ text: text.slice(lastIndex, m.index), bold: false });
    }
    parts.push({ text: m[1], bold: true });
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) {
    parts.push({ text: text.slice(lastIndex), bold: false });
  }
  return parts.length > 0 ? parts : [{ text, bold: false }];
}

// ---- Page parts ------------------------------------------------------------
function drawTopAccent(doc: jsPDF) {
  doc.setFillColor(FLUO_GREEN[0], FLUO_GREEN[1], FLUO_GREEN[2]);
  doc.rect(0, 0, PAGE_W, 1.5, 'F');
}

function drawCover(ctx: PdfCtx, prep: AnyObj) {
  drawTopAccent(ctx.doc);
  ctx.y = MARGIN + 20;

  setFont(ctx, 'mono', 'bold');
  ctx.doc.setFontSize(8);
  setColor(ctx, FLUO_PINK);
  ctx.doc.text('NESTOR SALES — BATTLECARD', MARGIN, ctx.y);
  ctx.y += 6;

  setFont(ctx, 'serif', 'bold');
  ctx.doc.setFontSize(14);
  setColor(ctx, INK);
  ctx.doc.text('AGENIC', MARGIN, ctx.y);
  ctx.y += 16;

  setFont(ctx, 'serif', 'bold');
  ctx.doc.setFontSize(28);
  setColor(ctx, INK);
  const prospectName = prep.prospect_company_name || 'Battlecard';
  const wrapped = ctx.doc.splitTextToSize(prospectName, CONTENT_W);
  for (const line of wrapped) {
    ctx.doc.text(line, MARGIN, ctx.y);
    ctx.y += 11;
  }
  ctx.y += 2;

  if (prep.decision_maker_name) {
    setFont(ctx, 'serif', 'normal');
    ctx.doc.setFontSize(14);
    setColor(ctx, INK_60);
    const dm = prep.decision_maker_role
      ? `${prep.decision_maker_name} · ${prep.decision_maker_role}`
      : prep.decision_maker_name;
    ctx.doc.text(dm, MARGIN, ctx.y);
    ctx.y += 7;
  }

  if (prep.meeting_datetime || prep.meeting_location) {
    setFont(ctx, 'mono', 'normal');
    ctx.doc.setFontSize(9);
    setColor(ctx, INK_60);
    const parts: string[] = [];
    if (prep.meeting_datetime) {
      const dt = new Date(prep.meeting_datetime);
      parts.push(dt.toLocaleDateString('nl-BE', {
        weekday: 'long', day: 'numeric', month: 'long',
        hour: '2-digit', minute: '2-digit'
      }));
    }
    if (prep.meeting_location) parts.push(prep.meeting_location);
    ctx.doc.text(parts.join('  ·  '), MARGIN, ctx.y);
    ctx.y += 8;
  }

  ctx.y += 6;
}

function drawIntakeStrip(ctx: PdfCtx, prep: AnyObj) {
  const startY = ctx.y;

  const fields: Array<[string, string]> = [
    ['Type', MEETING_TYPE_LABELS[prep.meeting_type] || '—'],
    ['Stage', DEAL_STAGE_LABELS[prep.deal_stage] || '—'],
    ['Klant', KLANT_TYPE_LABELS[prep.klant_type] || '—'],
    ['Vertical', prep.industry_vertical || '—'],
  ];

  const colW = CONTENT_W / 4;
  const xLeft = MARGIN + 4;

  setFont(ctx, 'mono', 'normal');
  ctx.doc.setFontSize(7);
  setColor(ctx, INK_60);
  fields.forEach(([label], i) => {
    ctx.doc.text(label.toUpperCase(), xLeft + i * colW, startY);
  });

  setFont(ctx, 'sans', 'normal');
  ctx.doc.setFontSize(9.5);
  setColor(ctx, INK);
  fields.forEach(([, value], i) => {
    const wrapped = ctx.doc.splitTextToSize(value, colW - 3);
    ctx.doc.text(wrapped[0] || '—', xLeft + i * colW, startY + 4);
  });

  const extras: string[] = [];
  const stakes = Array.isArray(prep.additional_stakeholders) ? prep.additional_stakeholders.length : 0;
  if (stakes > 0) extras.push(`${stakes + 1} personen aan tafel`);
  if (prep.meeting_deadline) extras.push(`Deadline: ${prep.meeting_deadline}`);

  if (extras.length > 0) {
    setFont(ctx, 'mono', 'normal');
    ctx.doc.setFontSize(7.5);
    setColor(ctx, INK_60);
    ctx.doc.text(extras.join('  ·  '), xLeft, startY + 11);
    ctx.y = startY + 16;
  } else {
    ctx.y = startY + 10;
  }

  ctx.doc.setDrawColor(FLUO_PINK[0], FLUO_PINK[1], FLUO_PINK[2]);
  ctx.doc.setLineWidth(0.6);
  ctx.doc.line(MARGIN, startY - 3, MARGIN, ctx.y - 1);
  ctx.y += 8;
}

function drawCategoryHeader(ctx: PdfCtx, label: string) {
  ensureSpace(ctx, 18);
  ctx.y += 6;

  ctx.doc.setFillColor(FLUO_GREEN[0], FLUO_GREEN[1], FLUO_GREEN[2]);
  ctx.doc.rect(MARGIN, ctx.y, 12, 1, 'F');
  ctx.y += 4;

  setFont(ctx, 'serif', 'normal');
  ctx.doc.setFontSize(16);
  setColor(ctx, INK);
  ctx.doc.text(label, MARGIN, ctx.y + 3);
  ctx.y += 9;
}

function drawBlockCard(ctx: PdfCtx, block: AnyObj) {
  ensureSpace(ctx, 30);

  const startY = ctx.y;
  const innerX = MARGIN + 4;
  const innerW = CONTENT_W - 8;

  ctx.y += 5;
  setFont(ctx, 'mono', 'bold');
  ctx.doc.setFontSize(8);
  setColor(ctx, FLUO_PINK);
  ctx.doc.text(String(block.key).padStart(2, '0'), innerX, ctx.y);

  setFont(ctx, 'serif', 'bold');
  ctx.doc.setFontSize(13);
  setColor(ctx, INK);
  ctx.doc.text(block.title || '', innerX + 9, ctx.y);
  ctx.y += 5;

  ctx.doc.setDrawColor(INK_20[0], INK_20[1], INK_20[2]);
  ctx.doc.setLineWidth(0.2);
  ctx.doc.line(innerX, ctx.y, innerX + innerW, ctx.y);
  ctx.y += 4;

  if (block.content && String(block.content).trim()) {
    renderRichText(ctx, block.content, {
      x: innerX, width: innerW, fontSize: 9, lineHeight: 4.4, color: INK,
    });
    ctx.y += 1;
  }

  if (Array.isArray(block.subsections) && block.subsections.length > 0) {
    for (const sub of block.subsections) {
      ensureSpace(ctx, 12);
      setFont(ctx, 'mono', 'bold');
      ctx.doc.setFontSize(7.5);
      setColor(ctx, INK_60);
      ctx.doc.text(String(sub.title || '').toUpperCase(), innerX + 2, ctx.y);
      ctx.y += 3.5;

      const subStartY = ctx.y;
      renderRichText(ctx, sub.content || '', {
        x: innerX + 4, width: innerW - 4, fontSize: 9, lineHeight: 4.4, color: INK,
      });
      ctx.doc.setDrawColor(INK_20[0], INK_20[1], INK_20[2]);
      ctx.doc.setLineWidth(0.4);
      ctx.doc.line(innerX + 2, subStartY - 2, innerX + 2, ctx.y - 1);
      ctx.y += 2;
    }
  }

  const endY = ctx.y + 3;
  ctx.doc.setDrawColor(INK_20[0], INK_20[1], INK_20[2]);
  ctx.doc.setLineWidth(0.25);
  ctx.doc.rect(MARGIN, startY, CONTENT_W, endY - startY, 'S');
  ctx.y = endY + 4;
}

function drawFoot(ctx: PdfCtx) {
  ensureSpace(ctx, 28);
  ctx.y += 6;

  ctx.doc.setDrawColor(INK_20[0], INK_20[1], INK_20[2]);
  ctx.doc.setLineWidth(0.2);
  ctx.doc.line(MARGIN, ctx.y, MARGIN + CONTENT_W, ctx.y);
  ctx.y += 5;

  setFont(ctx, 'mono', 'bold');
  ctx.doc.setFontSize(7.5);
  setColor(ctx, INK_60);
  ctx.doc.text('METHODOLOGISCHE BASIS', MARGIN, ctx.y);
  ctx.y += 4;

  setFont(ctx, 'sans', 'normal');
  ctx.doc.setFontSize(8.5);
  setColor(ctx, INK_60);
  const body = 'Deze briefing is opgebouwd volgens vier decennia sales-onderzoek: '
    + 'Challenger Sale (Dixon & Adamson), MEDDPICC (Dunkel), SPIN Selling (Rackham), '
    + 'Pre-Suasion (Cialdini) en Tactical Empathy (Voss).';
  const wrapped = ctx.doc.splitTextToSize(body, CONTENT_W);
  for (const line of wrapped) {
    ctx.doc.text(line, MARGIN, ctx.y);
    ctx.y += 4.2;
  }

  ctx.y += 2;
  setFont(ctx, 'mono', 'normal');
  ctx.doc.setFontSize(7);
  setColor(ctx, INK_40);
  ctx.doc.text('Nestor Sales v3  ·  Agenic', MARGIN, ctx.y);
}

function drawPageNumbers(doc: jsPDF) {
  const total = doc.getNumberOfPages();
  for (let p = 1; p <= total; p++) {
    doc.setPage(p);
    doc.setFont('courier', 'normal');
    doc.setFontSize(7);
    doc.setTextColor(INK_40[0], INK_40[1], INK_40[2]);
    doc.text(`${p} / ${total}`, PAGE_W - MARGIN, PAGE_H - 10, { align: 'right' });
  }
}

// ---- Public API ------------------------------------------------------------
export async function generateBattlecardPdf(prep: AnyObj, battlecard: AnyObj | null | undefined): Promise<Blob> {
  const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' });
  const ctx: PdfCtx = { doc, y: MARGIN };

  drawCover(ctx, prep || {});
  drawIntakeStrip(ctx, prep || {});

  const blocksMap: Record<string, AnyObj> = battlecard?.blocks || {};
  const orderedKeys = Object.keys(blocksMap).sort((a, b) => parseInt(a) - parseInt(b));
  const byCategory: Record<string, AnyObj[]> = { context: [], analyse: [], aanpak: [], onverwachte: [] };
  for (const k of orderedKeys) {
    const b = blocksMap[k];
    const cat = b?.category && byCategory[b.category] ? b.category : 'context';
    byCategory[cat].push({ key: k, ...b });
  }

  for (const cat of CATEGORIES) {
    const items = byCategory[cat.id];
    if (!items || items.length === 0) continue;
    drawCategoryHeader(ctx, cat.label);
    for (const block of items) {
      drawBlockCard(ctx, block);
    }
  }

  drawFoot(ctx);
  drawPageNumbers(doc);

  return doc.output('blob');
}

export default generateBattlecardPdf;
