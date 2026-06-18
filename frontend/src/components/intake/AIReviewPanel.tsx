import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Sparkles, Check, X, Pencil, Loader2, AlertTriangle, Info, Copy, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

const markdownComponents = {
 p: ({ children }: { children?: ReactNode }) => (
 <p className="font-sans text-sm text-ink">{children}</p>
 ),
 ul: ({ children }: { children?: ReactNode }) => (
 <ul className="list-disc list-inside space-y-1 font-sans text-sm text-ink">{children}</ul>
 ),
 ol: ({ children }: { children?: ReactNode }) => (
 <ol className="list-decimal list-inside space-y-1 font-sans text-sm text-ink">{children}</ol>
 ),
 li: ({ children }: { children?: ReactNode }) => <li className="text-ink">{children}</li>,
 strong: ({ children }: { children?: ReactNode }) => (
 <strong className="font-semibold text-ink">{children}</strong>
 ),
 em: ({ children }: { children?: ReactNode }) => <em className="italic">{children}</em>,
 a: ({ href, children }: { href?: string; children?: ReactNode }) => (
 <a href={href} className="underline text-ink" target="_blank" rel="noreferrer">
 {children}
 </a>
 ),
};

function Markdown({ children }: { children: string }) {
 return (
 <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
 {children}
 </ReactMarkdown>
 );
}

type ReviewContextValue = {
 parsed: ParsedSkillOutput;
 state: AIReviewState;
 intakeId?: string;
 runId?: string;
};
const ReviewContext = createContext<ReviewContextValue | null>(null);

export function ReviewProvider({
 parsed,
 state,
 intakeId,
 runId,
 children,
}: {
 parsed: ParsedSkillOutput;
 state: AIReviewState;
 intakeId?: string;
 runId?: string;
 children: ReactNode;
}) {
 return (
   <ReviewContext.Provider value={{ parsed, state, intakeId, runId }}>
     {children}
   </ReviewContext.Provider>
 );
}

export function useReview() {
 return useContext(ReviewContext);
}

async function persistApprovedField(
  intakeId: string | undefined,
  runId: string | undefined,
  field_key: string,
  value: unknown,
): Promise<void> {
  if (!supabase || !intakeId) return;
  if (value === "" || value == null) return;
  const { error } = await supabase
    .schema("nestor")
    .from("intake_answers")
    .upsert(
      { intake_id: intakeId, field_key, value },
      { onConflict: "intake_id,field_key" },
    );
  if (error) throw error;
  if (runId) {
    let appliedBy: string | null = null;
    try {
      const { data } = await supabase.auth.getUser();
      appliedBy = data.user?.id ?? null;
    } catch {}
    const patch: Record<string, unknown> = {
      applied_at: new Date().toISOString(),
    };
    if (appliedBy) patch.applied_by = appliedBy;
    const { error: e1 } = await supabase
      .schema("nestor")
      .from("skill_runs")
      .update(patch)
      .eq("id", runId);
    if (e1 && appliedBy) {
      // Retry without applied_by in case the column doesn't exist
      await supabase
        .schema("nestor")
        .from("skill_runs")
        .update({ applied_at: patch.applied_at })
        .eq("id", runId);
    }
  }
}


const BLIND_SPOTS_KEYS = ["blind_spots_upstream", "blind_spots_downstream", "blind_spots_perspectief"] as const;
const REPLACEMENT_KEYS = ["bias_radar", "gaps_flagged", ...BLIND_SPOTS_KEYS] as const;

function toStr(v: unknown): string {
 if (v == null) return "";
 if (typeof v === "string") return v;
 try { return JSON.stringify(v); } catch { return String(v); }
}

function getSuggestedFor(fieldKey: string, parsed: ParsedSkillOutput): string | null {
 if (fieldKey === "bias_radar") return parsed.bias_radar ?? null;
 if (fieldKey === "gaps_flagged") return parsed.gaps_flagged ?? null;
 if (fieldKey === "blind_spots_upstream") return parsed.blind_spots?.upstream ?? null;
 if (fieldKey === "blind_spots_downstream") return parsed.blind_spots?.downstream ?? null;
 if (fieldKey === "blind_spots_perspectief") return parsed.blind_spots?.perspectief ?? null;
 return null;
}

/** Inline card for a simple field key (decision_or_goal, audience_description, company_intro)
 *  plus replacement-shape fields (bias_radar, gaps_flagged, blind_spots_*). */
export function InlineFieldSuggestion({ fieldKey, currentValue }: { fieldKey: string; currentValue?: unknown }) {
 const ctx = useReview();
 if (!ctx) return null;

 const handleDecide = async (key: string, d: Decision, valueWhenApproved: string) => {
  ctx.state.setDecision(key, d);
  try {
   if (d.state === "approved") {
    await persistApprovedField(ctx.intakeId, ctx.runId, key, valueWhenApproved);
    toast.success("Toegepast");
   } else if (d.state === "manual") {
    await persistApprovedField(ctx.intakeId, ctx.runId, key, d.value);
    toast.success("Opgeslagen");
   }
  } catch (err: any) {
   toast.error("Opslaan mislukt: " + (err?.message ?? "onbekend"));
   ctx.state.setDecision(key, { state: "pending" });
  }
 };

 // Replacement-shape fields: suggested is a plain string from a different shape.
 if ((REPLACEMENT_KEYS as readonly string[]).includes(fieldKey)) {
  const suggested = getSuggestedFor(fieldKey, ctx.parsed);
  if (!suggested) return null;
  const decision = ctx.state.decisions[fieldKey] ?? { state: "pending" as const };
  return (
   <InlineSuggestionCard
    current={toStr(currentValue)}
    suggested={suggested}
    decision={decision}
    onDecide={(d) => handleDecide(fieldKey, d, suggested)}
   />
  );
 }

 const sug = ctx.parsed[fieldKey as SimpleFieldKey];
 if (!sug || !sug.suggested) return null;
 const decision = ctx.state.decisions[fieldKey] ?? { state: "pending" as const };
 return (
  <InlineSuggestionCard
   current={sug.current ?? toStr(currentValue)}
   suggested={sug.suggested}
   rationale={sug.rationale}
   decision={decision}
   onDecide={(d) => handleDecide(fieldKey, d, sug.suggested)}
  />
 );
}


/** Inline cards for research questions — rendered right after the questions list field. */
export function InlineResearchQuestionsSuggestions() {
 const ctx = useReview();
 if (!ctx) return null;
 return <ResearchQuestionsSuggestions parsed={ctx.parsed} state={ctx.state} intakeId={ctx.intakeId} runId={ctx.runId} />;
}

export type ResearchQuestion = {
 original_index?: number;
 current?: string | null;
 suggested: string;
 type?: string;
 domain?: string;
 rationale?: string;
};

export type SuggestionTriple = {
 current?: string | null;
 suggested: string;
 rationale?: string;
};

export type AdditionalQuestion = { text: string; rationale?: string };
export type DroppedQuestion = { original: string; reason?: string };

export type ParsedSkillOutput = {
 decision_or_goal?: SuggestionTriple | null;
 audience_description?: SuggestionTriple | null;
 company_intro?: SuggestionTriple | null;
 research_questions_refined?: ResearchQuestion[];
 additional_questions?: AdditionalQuestion[];
 dropped_questions?: DroppedQuestion[];
 bias_radar?: string;
 blind_spots?: { upstream?: string; downstream?: string; perspectief?: string };
 gaps_flagged?: string;
};

export type Decision =
 | { state: "pending" }
 | { state: "approved" }
 | { state: "kept" }
 | { state: "manual"; value: string };

export type DecisionMap = Record<string, Decision>;

export const SIMPLE_FIELD_KEYS = ["decision_or_goal", "audience_description", "company_intro"] as const;
export type SimpleFieldKey = (typeof SIMPLE_FIELD_KEYS)[number];

export const SIMPLE_LABELS: Record<string, string> = {
 decision_or_goal: "Beslissing of doel",
 audience_description: "Doelgroep",
 company_intro: "Bedrijfsintro",
};

export const RESEARCH_QUESTIONS_FIELD_KEY = "research_questions";

export type ExtraQuestionState = AdditionalQuestion & { include: boolean };

export type AIReviewState = {
 decisions: DecisionMap;
 setDecision: (key: string, d: Decision) => void;
 extraQuestions: ExtraQuestionState[];
 setExtraQuestions: React.Dispatch<React.SetStateAction<ExtraQuestionState[]>>;
 decidedCount: number;
};

export function useAIReview(parsed: ParsedSkillOutput): AIReviewState {
 const buildInitialDecisions = (p: ParsedSkillOutput): DecisionMap => {
  const m: DecisionMap = {};
  SIMPLE_FIELD_KEYS.forEach((k) => {
   if (p[k]) m[k] = { state: "pending" };
  });
  (p.research_questions_refined ?? []).forEach((_, i) => {
   m[`rq_${i}`] = { state: "pending" };
  });
  REPLACEMENT_KEYS.forEach((k) => {
   if (getSuggestedFor(k, p)) m[k] = { state: "pending" };
  });
  return m;
 };
 const [decisions, setDecisions] = useState<DecisionMap>(() => buildInitialDecisions(parsed));
 const [extraQuestions, setExtraQuestions] = useState<ExtraQuestionState[]>(
 () => (parsed.additional_questions ?? []).map((q) => ({ ...q, include: false })),
 );

 // Re-initialize when a new parsed result comes in.
 useEffect(() => {
  setDecisions(buildInitialDecisions(parsed));
  setExtraQuestions((parsed.additional_questions ?? []).map((q) => ({ ...q, include: false })));
 // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [parsed]);


 const decidedCount = useMemo(
 () => Object.values(decisions).filter((d) => d.state !== "pending").length,
 [decisions],
 );

 const setDecision = (key: string, d: Decision) =>
 setDecisions((prev) => ({ ...prev, [key]: d }));

 return {
 decisions,
 setDecision,
 extraQuestions,
 setExtraQuestions,
 decidedCount,
 };
}

export async function submitReview({
 intakeId,
 runId,
 parsed,
 state,
}: {
 intakeId: string;
 runId: string;
 parsed: ParsedSkillOutput;
 state: AIReviewState;
}): Promise<string> {
 if (!supabase) throw new Error("Supabase niet geconfigureerd");
 const { decisions, extraQuestions } = state;
 const upserts: Array<{ field_key: string; value: unknown }> = [];

 for (const k of SIMPLE_FIELD_KEYS) {
 const sug = parsed[k];
 const dec = decisions[k];
 if (!sug || !dec) continue;
 if (dec.state === "approved") upserts.push({ field_key: k, value: sug.suggested });
 else if (dec.state === "manual") upserts.push({ field_key: k, value: dec.value });
 }

 const rqs = parsed.research_questions_refined ?? [];
 const refined: Array<{ text: string; type?: string; domain?: string }> = [];
 rqs.forEach((q, i) => {
 const dec = decisions[`rq_${i}`];
 if (!dec) return;
 if (dec.state === "approved") refined.push({ text: q.suggested, type: q.type, domain: q.domain });
 else if (dec.state === "manual") refined.push({ text: dec.value, type: q.type, domain: q.domain });
 else if (dec.state === "kept" && q.current)
 refined.push({ text: q.current, type: q.type, domain: q.domain });
 });
 if (refined.length > 0) {
 upserts.push({ field_key: "research_questions_refined", value: refined });
 }

 upserts.push({
 field_key: "extra_questions_proposed",
 value: extraQuestions.map((q) => ({
 text: q.text,
 rationale: q.rationale,
 approved: false,
 show_to_client: q.include,
 })),
 });

 for (const key of REPLACEMENT_KEYS) {
  const suggested = getSuggestedFor(key, parsed);
  if (!suggested) continue;
  const dec = decisions[key];
  if (!dec || dec.state === "pending" || dec.state === "kept") continue;
  if (dec.state === "approved") upserts.push({ field_key: key, value: suggested });
  else if (dec.state === "manual") upserts.push({ field_key: key, value: dec.value });
 }





 for (const row of upserts) {
 if (row.value === "" || row.value == null) continue;
 const { error } = await supabase
 .schema("nestor")
 .from("intake_answers")
 .upsert(
 { intake_id: intakeId, field_key: row.field_key, value: row.value },
 { onConflict: "intake_id,field_key" },
 );
 if (error) throw error;
 }

 const validationToken = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
 const { error: updErr } = await supabase
 .schema("nestor")
 .from("intakes")
 .update({
 client_validation_token: validationToken,
 status: "reviewed",
 updated_at: new Date().toISOString(),
 })
 .eq("id", intakeId);
 if (updErr) throw updErr;

 if (runId) {
 await supabase
 .schema("nestor")
 .from("skill_runs")
 .update({
 applied_at: new Date().toISOString(),
 applied_changes: {
 decisions,
 extra_questions_included: extraQuestions.filter((q) => q.include).length,
 },
 })
 .eq("id", runId);
 }

 return validationToken;
}

// ============== Banner (top of page) ==============

export function AIReviewTopBanner({
 costEur,
 decidedCount,
 onCancel,
 onSubmit,
 submitting,
}: {
 costEur: number | null;
 decidedCount: number;
 onCancel: () => void;
 onSubmit: () => void;
 submitting: boolean;
}) {
 return (
 <div className="mb-6 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4">
 <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">AI REVIEW MODE</div>
 <div className="flex flex-wrap items-center justify-between gap-3 text-ink font-sans">
 <div className="text-sm text-ink">
 Review elke suggestie en klik "Verstuur voor klant-validatie" wanneer klaar.
 {costEur != null && <span className="ml-1 font-mono text-xs uppercase tracking-wider text-ink/60">Cost: €{costEur.toFixed(2)}</span>}
 </div>
 <div className="flex flex-wrap items-center gap-2">
 <button
 type="button"
 onClick={onCancel}
 className="border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
 >
 Annuleer review mode
 </button>
 <button
 type="button"
 onClick={onSubmit}
 disabled={submitting || decidedCount === 0}
 className="inline-flex items-center gap-1.5 border border-ink bg-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90 disabled:opacity-50"
 >
 {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
 Verstuur voor klant-validatie
 </button>
 </div>
 </div>
 </div>
 );
}

export function AIReviewInfoBanners({ parsed }: { parsed: ParsedSkillOutput }) {
 return (
    <>
 {(parsed.dropped_questions ?? []).length > 0 && (
 <div className="mb-4 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4">
 <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">
 NESTOR SCHRAPTE DEZE VRAGEN
 </div>
 <ul className="list-disc space-y-1 pl-5 text-ink font-sans">
 {parsed.dropped_questions!.map((d, i) => (
 <li key={i}>
 <span className="text-ink">{d.original}</span>
 {d.reason && <span className="text-ink/60"> — {d.reason}</span>}
 </li>
 ))}
 </ul>
 </div>
 )}
 {parsed.gaps_flagged && (
 <div className="mb-4 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4">
 <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">
 NESTOR FLAGTE DEZE GAPS
 </div>
 <Markdown>{parsed.gaps_flagged}</Markdown>
 </div>
 )}
 </>
 );
}

// ============== Approved row (collapsible) ==============

function ApprovedRow({
  title,
  suggested,
  current,
  rationale,
  onEdit,
}: {
  title?: string;
  suggested: string;
  current: string;
  rationale?: string;
  onEdit: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 border border-ink bg-paper2 text-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-ink/5"
      >
        <div className="font-sans text-sm text-ink/60">
          {title ? `${title} · ` : ""}Aangescherpt door Nestor
        </div>
        <div className="flex items-center gap-3">
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation();
              onEdit();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                onEdit();
              }
            }}
            className="text-xs font-medium text-emerald-800 hover:underline"
          >
            Wijzig
          </span>
          <ChevronDown
            className={cn(
              "h-4 w-4 text-ink/60 transition-transform",
              open && "rotate-180",
            )}
          />
        </div>
      </button>
      {open && (
        <div className="border-t border-ink/20 px-3 py-3 space-y-3">
          {current && (
            <div>
              <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-ink/60">
                Origineel
              </div>
              <div className="whitespace-pre-wrap text-sm text-ink/70">{current}</div>
            </div>
          )}
          <div>
            <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-ink/60">
              Voorstel Nestor (huidig)
            </div>
            <div className="whitespace-pre-wrap text-sm text-ink">{suggested}</div>
          </div>
          {rationale && (
            <p className="text-sm">
              <span className="mr-2 font-mono text-[10px] uppercase tracking-wider text-ink/60">
                Waarom
              </span>
              <span className="font-sans italic text-ink/70">{rationale}</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ============== Inline suggestion card ==============

export function InlineSuggestionCard({
 title,
 current,
 suggested,
 rationale,
 decision,
 onDecide,
}: {
 title?: string;
 current: string;
 suggested: string;
 rationale?: string;
 decision: Decision;
 onDecide: (d: Decision) => void;
}) {
  if (decision.state === "approved") {
    return (
      <ApprovedRow
        title={title}
        suggested={suggested}
        current={current}
        rationale={rationale}
        onEdit={() => onDecide({ state: "pending" })}
      />
    );
  }
 if (decision.state === "kept") {
 return (
 <div className="mt-2 flex items-center justify-between border border-ink/10 bg-paper2 px-3 py-2 text-sm">
 <div className="text-ink/70">
 {title && <span className="font-medium">{title} — </span>}✗ Origineel blijft
 </div>
 <button
 type="button"
 onClick={() => onDecide({ state: "pending" })}
 className="text-xs font-medium text-ink/70 hover:underline"
 >
 Wijzig
 </button>
 </div>
 );
 }
 if (decision.state === "manual") {
 return (
      <div className="mt-2 border border-ink bg-paper2 p-3 text-sm">
        <div className="flex items-center justify-between">
          <div className="font-sans text-sm text-ink/60">{title ? `${title} · ` : ""}Manueel aangepast door admin</div>
 <button
 type="button"
 onClick={() => onDecide({ state: "pending" })}
 className="font-mono text-xs uppercase tracking-wider text-ink hover:underline"
 >
 Wijzig
 </button>
 </div>
 <p className="mt-2 whitespace-pre-wrap text-sm text-ink/80">{decision.value}</p>
 </div>
 );
 }

 return (
 <div className="mt-2 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4 text-ink">
 <div className="mb-3 font-mono text-xs uppercase tracking-wider text-ink">
 NESTOR VOORSTEL{title ? ` · ${title}` : ""}
 </div>
 <div className="border border-ink bg-paper p-4 font-mono text-base text-ink whitespace-pre-wrap">
 {suggested}
 </div>
 {rationale && (
 <p className="mt-3 text-sm">
 <span className="mr-3 font-mono text-xs uppercase tracking-wider text-ink/60">Waarom</span>
 <span className="font-sans italic text-ink/70">{rationale}</span>
 </p>
 )}
 <ManualOrChoice
 current={current}
 suggested={suggested}
 onApply={() => onDecide({ state: "approved" })}
 onKeep={() => onDecide({ state: "kept" })}
 onManual={(v) => onDecide({ state: "manual", value: v })}
 />
 </div>
 );
}

function ManualOrChoice({
 current,
 suggested,
 onApply,
 onKeep,
 onManual,
}: {
 current: string;
 suggested: string;
 onApply: () => void;
 onKeep: () => void;
 onManual: (value: string) => void;
}) {
 const [editing, setEditing] = useState(false);
 const [draft, setDraft] = useState(current || suggested);

 if (editing) {
 return (
 <div className="mt-3 space-y-2">
 <textarea
 rows={4}
 className="w-full border border-ink/10 bg-paper px-3 py-2 text-sm focus:border-ink focus:outline-none"
 value={draft}
 onChange={(e) => setDraft(e.target.value)}
 />
 <div className="flex gap-2">
 <button
 type="button"
 onClick={() => {
 if (!draft.trim()) {
 toast("Kan niet leeg zijn");
 return;
 }
 onManual(draft);
 setEditing(false);
 }}
 className="bg-ink px-3 py-1.5 text-xs font-medium text-paper hover:bg-ink/80"
 >
 Opslaan
 </button>
 <button
 type="button"
 onClick={() => setEditing(false)}
 className="border border-ink/10 bg-paper px-3 py-1.5 text-xs font-medium text-ink/70 hover:bg-ink/5"
 >
 Annuleren
 </button>
 </div>
 </div>
 );
 }

 return (
 <div className="mt-3 flex flex-wrap gap-2">
 <button
 type="button"
 onClick={onApply}
 disabled={!suggested || suggested.trim() === (current ?? "").trim()}
 className="inline-flex items-center gap-1 border border-ink bg-agenic-green px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:brightness-95 disabled:opacity-40 disabled:cursor-not-allowed"
 >
 <Check className="h-3.5 w-3.5" /> Toepassen
 </button>

 <button
 type="button"
 onClick={onKeep}
 className="inline-flex items-center gap-1 border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
 >
 <X className="h-3.5 w-3.5" /> Houden
 </button>
 <button
 type="button"
 onClick={() => {
 setDraft(current || suggested);
 setEditing(true);
 }}
 className="inline-flex items-center gap-1 border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
 >
 <Pencil className="h-3.5 w-3.5" /> Manueel aanpassen
 </button>
 </div>
 );
}

// ============== Research questions block ==============

export function ResearchQuestionsSuggestions({
 parsed,
 state,
 intakeId,
 runId,
}: {
 parsed: ParsedSkillOutput;
 state: AIReviewState;
 intakeId?: string;
 runId?: string;
}) {
 const rqs = parsed.research_questions_refined ?? [];
 if (rqs.length === 0) return null;

 const buildRefined = (overrideIdx: number, overrideDec: Decision) => {
  const refined: Array<{ text: string; type?: string; domain?: string }> = [];
  rqs.forEach((q, i) => {
   const dec = i === overrideIdx ? overrideDec : state.decisions[`rq_${i}`];
   if (!dec) return;
   if (dec.state === "approved") refined.push({ text: q.suggested, type: q.type, domain: q.domain });
   else if (dec.state === "manual") refined.push({ text: dec.value, type: q.type, domain: q.domain });
   else if (dec.state === "kept" && q.current)
    refined.push({ text: q.current, type: q.type, domain: q.domain });
  });
  return refined;
 };

 const handleDecide = async (i: number, d: Decision) => {
  const k = `rq_${i}`;
  state.setDecision(k, d);
  if (d.state === "pending") return;
  try {
   const refined = buildRefined(i, d);
   await persistApprovedField(intakeId, runId, "research_questions_refined", refined);
   toast.success("Toegepast");
  } catch (err: any) {
   toast.error("Opslaan mislukt: " + (err?.message ?? "onbekend"));
   state.setDecision(k, { state: "pending" });
  }
 };

 return (
 <div className="mt-4 space-y-3">
 <p className="font-mono text-xs uppercase tracking-wider text-ink">
 NESTOR VOORSTELLEN VOOR RESEARCH-VRAGEN
 </p>
 {rqs.map((q, i) => {
 const k = `rq_${i}`;
 const idxLabel =
 q.original_index != null ? `Vraag ${q.original_index + 1}` : `Vraag ${i + 1}`;
 const meta = [q.type, q.domain].filter(Boolean).join(" · ");
 return (
 <div key={k} className="border border-ink/10 bg-paper p-3">
 <div className="mb-1 text-xs font-medium text-ink/60">
 {idxLabel}
 {meta && <span className="text-ink/40"> · {meta}</span>}
 </div>
 {q.current && (
 <p className="text-sm text-ink/70">
 <span className="text-xs uppercase text-ink/40">Origineel: </span>
 {q.current}
 </p>
 )}
 <InlineSuggestionCard
 current={q.current ?? ""}
 suggested={q.suggested}
 rationale={q.rationale}
 decision={state.decisions[k] ?? { state: "pending" }}
 onDecide={(d) => handleDecide(i, d)}
 />
 </div>
 );
 })}
 </div>
 );
}


// ============== Extra questions section ==============

export function ExtraQuestionsSection({ state, inline }: { state: AIReviewState; inline?: boolean }) {
 if (state.extraQuestions.length === 0) {
 if (inline) {
 return <p className="mt-3 text-sm text-ink/60">Geen extra voorstellen.</p>;
 }
 return null;
 }
 const body = (
 <>
 <p className="mt-2 text-xs text-ink/60">
 Vink aan welke voorstellen de klant te zien krijgt in zijn validatie-link.
 </p>
 <ul className="mt-4 space-y-3">
 {state.extraQuestions.map((q, i) => (
 <li
 key={i}
 className={cn(
 "border p-3",
 q.include ? "border-emerald-200 bg-emerald-50/50" : "border-ink/10 bg-paper",
 )}
 >
 <label className="flex cursor-pointer items-start gap-2">
 <input
 type="checkbox"
 className="mt-1"
 checked={q.include}
 onChange={() =>
 state.setExtraQuestions((prev) =>
 prev.map((x, idx) => (idx === i ? { ...x, include: !x.include } : x)),
 )
 }
 />
 <div className="flex-1">
 <div className="text-sm font-medium text-ink">{q.text}</div>
 {q.rationale && <div className="mt-1 text-xs text-ink/60">{q.rationale}</div>}
 <div className="mt-1 text-xs text-ink/60">Klant kan opnemen?</div>
 </div>
 </label>
 </li>
 ))}
 </ul>
 </>
 );
 if (inline) return <div>{body}</div>;
 return (
 <section className="border border-ink/10 bg-paper p-6">
 <h2 className="border-b border-ink/10 pb-2 text-lg font-semibold text-ink">
 Extra vragen — voorstel Nestor
 </h2>
 {body}
 </section>
 );
}


// ============== Success modal ==============

export function ReviewSuccessModal({
 url,
 onClose,
}: {
 url: string;
 onClose: () => void;
}) {
 const copy = async () => {
 try {
 await navigator.clipboard.writeText(url);
 toast.success("Link gekopieerd");
 } catch {
 toast.error("Kopiëren mislukt");
 }
 };
 return (
 <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
 <div className="w-full max-w-lg bg-paper p-6 shadow-xl">
 <h3 className="text-base font-semibold text-emerald-900">Verstuurd voor klant-validatie</h3>
 <p className="mt-2 text-sm text-ink/60">
 De klant kan via onderstaande link de refinements bekijken en de extra Nestor-voorstellen
 aanvinken.
 </p>
 <div className="mt-4 flex flex-wrap items-center gap-2">
 <code className="break-all rounded bg-paper2 px-2.5 py-1.5 text-xs text-ink/80 ring-1 ring-ink/10">
 {url}
 </code>
 <button
 type="button"
 onClick={copy}
 className="inline-flex items-center gap-1 border border-ink/10 bg-paper px-2.5 py-1 text-xs font-medium text-ink/80 hover:bg-ink/5"
 >
 <Copy className="h-3.5 w-3.5" />
 Kopieer link
 </button>
 </div>
 <div className="mt-5 flex justify-end">
 <button
 type="button"
 onClick={onClose}
 className="bg-ink px-3 py-1.5 text-sm font-medium text-paper hover:bg-ink/80"
 >
 Sluiten
 </button>
 </div>
 </div>
 </div>
 );
}
