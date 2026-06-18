import { BattlecardMarkdown } from "./BattlecardMarkdown";
import {
  meetingTypeLabel,
  dealStageLabel,
  klantTypeLabel,
} from "@/lib/salesLabels";

type Subsection = { title?: string; content?: string };
export type Block = {
  key: string;
  title?: string;
  category?: string;
  content?: string;
  subsections?: Subsection[];
  sources?: Array<{ url: string; title?: string | null }>;
};

const CATEGORIES = [
  { id: "context", label: "De Context" },
  { id: "analyse", label: "De Analyse" },
  { id: "aanpak", label: "De Aanpak" },
  { id: "onverwachte", label: "Het Onverwachte" },
] as const;

function BlockCard({ block }: { block: Block }) {
  return (
    <article className="border border-ink/20 bg-paperLight p-6">
      <div className="flex items-baseline gap-3 mb-4 pb-3 border-b border-ink/10">
        <span className="font-mono text-[10px] uppercase tracking-wider text-fluoPink">
          {String(block.key).padStart(2, "0")}
        </span>
        {block.title && (
          <h3 className="font-serif text-xl">{block.title}</h3>
        )}
      </div>

      {block.content && block.content.trim() && (
        <div className="mb-4">
          <BattlecardMarkdown content={block.content} />
        </div>
      )}

      {Array.isArray(block.subsections) && block.subsections.length > 0 && (
        <div className="space-y-4 mt-4">
          {block.subsections.map((sub, idx) => (
            <div key={idx} className="border-l-2 border-ink/15 pl-4">
              {sub.title && (
                <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60 mb-2">
                  {sub.title}
                </div>
              )}
              {sub.content && <BattlecardMarkdown content={sub.content} />}
            </div>
          ))}
        </div>
      )}

      {block.sources && block.sources.length > 0 && (
        <div className="mt-4 pt-3 border-t border-ink/10 text-xs text-ink/50">
          Bronnen: {block.sources.length}
        </div>
      )}
    </article>
  );
}

function CategorySection({
  label,
  blocks,
}: {
  label: string;
  blocks: Block[];
}) {
  return (
    <section>
      <div className="mb-6">
        <div className="h-1 bg-fluoGreen w-12 mb-3" />
        <h2 className="font-serif text-2xl lowercase">{label.toLowerCase()}</h2>
      </div>
      <div className="space-y-4">
        {blocks.map((b) => (
          <BlockCard key={b.key} block={b} />
        ))}
      </div>
    </section>
  );
}

export function BattlecardBlocks({
  blocks,
}: {
  blocks: Record<string, Omit<Block, "key">>;
}) {
  const orderedKeys = Object.keys(blocks).sort(
    (a, b) => parseInt(a, 10) - parseInt(b, 10),
  );

  const byCategory: Record<string, Block[]> = {
    context: [],
    analyse: [],
    aanpak: [],
    onverwachte: [],
  };

  for (const k of orderedKeys) {
    const b = blocks[k];
    if (!b) continue;
    const cat = b.category && byCategory[b.category] ? b.category : "context";
    byCategory[cat].push({ key: k, ...b });
  }

  const anyContent = CATEGORIES.some(
    (c) => (byCategory[c.id] || []).length > 0,
  );
  if (!anyContent) return null;

  return (
    <div className="space-y-12">
      {CATEGORIES.map((cat) => {
        const items = byCategory[cat.id];
        if (!items || items.length === 0) return null;
        return (
          <CategorySection key={cat.id} label={cat.label} blocks={items} />
        );
      })}

      <footer className="mt-12 pt-6 border-t border-ink/15">
        <div className="font-mono text-[10px] uppercase tracking-wider text-ink/40 mb-2">
          Methodologische basis
        </div>
        <p className="text-xs text-ink/55 leading-relaxed">
          Deze briefing is opgebouwd volgens vier decennia sales-onderzoek:
          Challenger Sale (Dixon & Adamson), MEDDPICC (Dunkel), SPIN Selling
          (Rackham), Pre-Suasion (Cialdini) en Tactical Empathy (Voss).
        </p>
        <p className="text-[10px] text-ink/40 mt-2 font-mono">
          Nestor Sales v2 · Agenic
        </p>
      </footer>
    </div>
  );
}

export type IntakeStripPrep = {
  prospect_company_name?: string | null;
  decision_maker_name?: string | null;
  meeting_type?: string | null;
  deal_stage?: string | null;
  klant_type?: string | null;
  industry_vertical?: string | null;
  meeting_datetime?: string | null;
  meeting_location?: string | null;
};

function fmtMeeting(s?: string | null) {
  if (!s) return "";
  try {
    return new Date(s).toLocaleString("nl-BE", {
      day: "numeric",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return s;
  }
}

export function BattlecardIntakeStrip({ prep }: { prep: IntakeStripPrep }) {
  return (
    <section className="mb-12 border-l-2 border-fluoPink pl-6 py-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-fluoPink mb-3">
        Briefing voor
      </div>
      <h1 className="font-serif text-3xl mb-3">
        {prep.prospect_company_name || "—"}
        {prep.decision_maker_name && (
          <span className="text-ink/60"> · {prep.decision_maker_name}</span>
        )}
      </h1>
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-2 text-sm">
        <div>
          <dt className="font-mono text-[9px] uppercase tracking-wider text-ink/50">
            Type
          </dt>
          <dd>{meetingTypeLabel(prep.meeting_type) || "—"}</dd>
        </div>
        <div>
          <dt className="font-mono text-[9px] uppercase tracking-wider text-ink/50">
            Stage
          </dt>
          <dd>{dealStageLabel(prep.deal_stage) || "—"}</dd>
        </div>
        <div>
          <dt className="font-mono text-[9px] uppercase tracking-wider text-ink/50">
            Klant
          </dt>
          <dd>{klantTypeLabel(prep.klant_type) || "—"}</dd>
        </div>
        <div>
          <dt className="font-mono text-[9px] uppercase tracking-wider text-ink/50">
            Vertical
          </dt>
          <dd>{prep.industry_vertical || "—"}</dd>
        </div>
        {prep.meeting_datetime && (
          <div className="col-span-2">
            <dt className="font-mono text-[9px] uppercase tracking-wider text-ink/50">
              Meeting
            </dt>
            <dd>
              {fmtMeeting(prep.meeting_datetime)}
              {prep.meeting_location ? ` · ${prep.meeting_location}` : ""}
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
