import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { IntakeField, IntakeSection } from "@/lib/intake-types";
import { Sparkles, RotateCcw, Check } from "lucide-react";

export type Proposals = Record<string, any>;

export type SimpleProposal = {
  current?: string | null;
  suggested: string;
  rationale?: string;
};

export type RefinedQuestion = {
  original_index?: number;
  current?: string | null;
  suggested: string;
  rationale?: string;
  type?: string;
  domain?: string;
};

const SIMPLE_DIFF_KEYS = new Set([
  "decision_or_goal",
  "audience_description",
  "company_intro",
  "output_size",
  "output_form",
]);

export function getSimpleProposal(
  proposals: Proposals | null | undefined,
  key: string,
): SimpleProposal | null {
  if (!proposals) return null;
  const p = proposals[key];
  if (!p || typeof p !== "object" || typeof p.suggested !== "string") return null;
  return p as SimpleProposal;
}

export function getRefinedQuestions(
  proposals: Proposals | null | undefined,
): RefinedQuestion[] {
  if (!proposals) return [];
  const arr = proposals.research_questions_refined;
  return Array.isArray(arr) ? arr : [];
}

function answerToString(value: any): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object" && "choice" in value) {
    return String(value.choice ?? "");
  }
  return String(value);
}

export function isFieldChanged(
  fieldKey: string,
  currentAnswer: any,
  proposals: Proposals | null | undefined,
): boolean {
  if (!proposals) return false;
  if (fieldKey === "research_questions") {
    const refined = getRefinedQuestions(proposals);
    const items: any[] = Array.isArray(currentAnswer) ? currentAnswer : [];
    return refined.some((rq) => {
      if (!rq.suggested || rq.current == null) return false;
      if (rq.suggested === rq.current) return false;
      const idx = rq.original_index;
      if (idx == null || idx < 0) return false;
      const cur = items[idx];
      const text = typeof cur === "string" ? cur : (cur?.text ?? "");
      return text !== rq.current;
    });
  }
  if (!SIMPLE_DIFF_KEYS.has(fieldKey)) return false;
  const p = getSimpleProposal(proposals, fieldKey);
  if (!p) return false;
  if (p.suggested === p.current) return false;
  return answerToString(currentAnswer) !== (p.current ?? "");
}

export function sectionHasChange(
  section: IntakeSection,
  answers: Record<string, any>,
  proposals: Proposals | null | undefined,
): boolean {
  return section.fields.some((f) => isFieldChanged(f.key, answers[f.key], proposals));
}

// =================== Card ===================

function DiffCard({
  label,
  original,
  suggested,
  rationale,
  onRevert,
  meta,
  confirmed,
  onConfirm,
}: {
  label?: string;
  original: string;
  suggested: string;
  rationale?: string;
  onRevert: () => void | Promise<void>;
  meta?: string;
  // Confirmation is LIFTED state (keyed per card in IntakeForm) so it survives
  // section navigation — local useState reset on unmount, so cards re-asked for
  // confirmation after every next/back (live-UAT issue 2026-07-13).
  confirmed: boolean;
  onConfirm: () => void;
}) {
  const [reverting, setReverting] = useState(false);
  const { t } = useTranslation("intake");

  if (confirmed) {
    return (
      <div className="mt-2 flex items-center gap-2 border border-ink/30 bg-paper2 px-3 py-2 font-mono text-[11px] uppercase tracking-wider text-ink/60">
        <Check className="h-3.5 w-3.5 text-emerald-700" />
        {t("validationDiff.confirmedBadge")}
      </div>
    );
  }

  return (
    <div className="mt-3 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4 text-ink">
      <div className="mb-3 flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-ink">
        <Sparkles className="h-3.5 w-3.5" />
        {t("validationDiff.changedByNestor")}
        {label && <span className="text-ink/60"> · {label}</span>}
        {meta && <span className="text-ink/40"> · {meta}</span>}
      </div>

      <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-ink/60">
        {t("validationDiff.original")}
      </div>
      <div className="border border-ink/30 bg-paper p-3 text-sm whitespace-pre-wrap text-ink/70">
        {original || <span className="italic text-ink/40">{t("validationDiff.empty")}</span>}
      </div>

      <div className="mt-3 mb-1 font-mono text-[10px] uppercase tracking-wider text-ink/60">
        {t("validationDiff.proposal")}
      </div>
      <div className="border border-ink/30 bg-paper p-3 text-sm whitespace-pre-wrap text-ink">
        {suggested}
      </div>

      {rationale && (
        <p className="mt-3 text-sm">
          <span className="mr-2 font-mono text-[10px] uppercase tracking-wider text-ink/60">
            {t("validationDiff.why")}
          </span>
          <span className="font-sans italic text-ink/70">{rationale}</span>
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={reverting}
          onClick={async () => {
            setReverting(true);
            try {
              await onRevert();
            } finally {
              setReverting(false);
            }
          }}
          className="inline-flex items-center gap-1.5 border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-50"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          {reverting ? t("validationDiff.busy") : t("validationDiff.revert")}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="inline-flex items-center gap-1.5 border border-ink bg-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90"
        >
          <Check className="h-3.5 w-3.5" />
          {t("validationDiff.keep")}
        </button>
      </div>
    </div>
  );
}

// =================== Per-field renderer ===================

export function ValidationDiffForField({
  field,
  answer,
  proposals,
  onRevert,
  confirmedKeys,
  onConfirmKey,
}: {
  field: IntakeField;
  answer: any;
  proposals: Proposals | null | undefined;
  onRevert: (key: string, value: any) => Promise<void> | void;
  // Lifted confirmation state (see DiffCard): survives section navigation.
  confirmedKeys: ReadonlySet<string>;
  onConfirmKey: (cardKey: string) => void;
}) {
  const { t } = useTranslation("intake");
  if (!proposals) return null;

  if (field.key === "research_questions") {
    const refined = getRefinedQuestions(proposals);
    const items: any[] = Array.isArray(answer) ? answer : [];
    const changed = refined.filter((rq) => {
      if (!rq.suggested || rq.current == null) return false;
      if (rq.suggested === rq.current) return false;
      const idx = rq.original_index;
      if (idx == null || idx < 0) return false;
      const cur = items[idx];
      const text = typeof cur === "string" ? cur : (cur?.text ?? "");
      return text !== rq.current;
    });
    if (changed.length === 0) return null;
    return (
      <div className="space-y-3">
        {changed.map((rq, i) => {
          const idx = rq.original_index!;
          const meta = [rq.type, rq.domain].filter(Boolean).join(" · ");
          return (
            <DiffCard
              key={`rq-${idx}-${i}`}
              label={t("validationDiff.questionLabel", { index: idx + 1 })}
              meta={meta || undefined}
              original={rq.current ?? ""}
              suggested={rq.suggested}
              rationale={rq.rationale}
              confirmed={confirmedKeys.has(`${field.key}:rq-${idx}`)}
              onConfirm={() => onConfirmKey(`${field.key}:rq-${idx}`)}
              onRevert={async () => {
                const cur = items[idx];
                const isObj = cur && typeof cur === "object";
                const next = [...items];
                if (isObj) {
                  next[idx] = { ...cur, text: rq.current ?? "" };
                } else {
                  next[idx] = rq.current ?? "";
                }
                await onRevert(field.key, next);
              }}
            />
          );
        })}
      </div>
    );
  }

  if (!SIMPLE_DIFF_KEYS.has(field.key)) return null;
  const p = getSimpleProposal(proposals, field.key);
  if (!p) return null;
  if (p.suggested === p.current) return null;
  if (answerToString(answer) === (p.current ?? "")) return null;

  return (
    <DiffCard
      original={p.current ?? ""}
      suggested={p.suggested}
      rationale={p.rationale}
      confirmed={confirmedKeys.has(field.key)}
      onConfirm={() => onConfirmKey(field.key)}
      onRevert={async () => {
        // For radio fields with allow_text, preserve text
        if (field.type === "radio" && typeof answer === "object" && answer !== null) {
          await onRevert(field.key, { ...answer, choice: p.current ?? "" });
        } else {
          await onRevert(field.key, p.current ?? "");
        }
      }}
    />
  );
}
