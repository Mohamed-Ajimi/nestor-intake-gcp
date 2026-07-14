import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type {
  IntakeField,
  IntakePayload,
  IntakeSection,
  LocalizedIntakeSchema,
} from "@/lib/intake-types";
import { localizeSchema } from "@/lib/i18n/localizeSchema";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { FieldRenderer } from "./FieldRenderer";
import { toast } from "sonner";
import { saveAnswers, type AnswerInput } from "@/lib/api/answers";
import { submitIntake } from "@/lib/api/intakes";
import { listSkillRuns, getSkillRunFull } from "@/lib/api/skillRuns";
import {
  ValidationDiffForField,
  sectionHasChange,
  type Proposals,
} from "./ValidationDiff";

type SaveStatus = "idle" | "dirty" | "saving" | "saved" | "error";

/** Map a form value into the backend AnswerInput shape (string -> value, else value_json). */
function toAnswerInput(field_key: string, value: unknown): AnswerInput {
  if (value === null || value === undefined) return { field_key, value: null, value_json: null };
  if (typeof value === "string") return { field_key, value, value_json: null };
  return { field_key, value: null, value_json: value };
}

// `t` is threaded in from the component (this pure helper cannot call hooks).
function validateField(field: IntakeField, value: any, t: TFunction): string | null {
 const isEmpty =
 value === undefined ||
 value === null ||
 value === "" ||
 (Array.isArray(value) && value.length === 0);

 if (field.required && isEmpty) return t("validation.required");
 if (isEmpty) return null;

 if (field.type === "email" && typeof value === "string") {
 if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return t("validation.invalidEmail");
 }
 if (field.type === "longtext" && field.validation?.min_length) {
 if (typeof value === "string" && value.length < field.validation.min_length)
 return t("validation.minChars", { count: field.validation.min_length });
 }
 if (field.type === "list" && Array.isArray(value)) {
 if (field.min_items && value.length < field.min_items)
 return t("validation.minItems", { count: field.min_items });
 }
 return null;
}

function isFieldEmpty(value: any): boolean {
 return (
 value === undefined ||
 value === null ||
 value === "" ||
 (Array.isArray(value) && value.length === 0)
 );
}

function sectionMissingRequired(section: IntakeSection, answers: Record<string, any>): string[] {
 const missing: string[] = [];
 for (const f of section.fields) {
 if (f.required && isFieldEmpty(answers[f.key])) missing.push(f.key);
 }
 return missing;
}

function sectionMissingSoft(section: IntakeSection, answers: Record<string, any>): IntakeField[] {
 return section.fields.filter(
 (f) => f.soft_required && isFieldEmpty(answers[f.key]),
 );
}

export function IntakeForm({
 payload,
 token,
}: {
 payload: IntakePayload;
 token: string;
}) {
 const { t, i18n } = useTranslation("intake");
 // The backend serves the ONE canonical schema in multi-locale (LocalizedString)
 // shape; flatten it to the active locale at load, re-resolving when the language
 // changes so the form re-renders in the new locale (nl fallback, D-05).
 const schema = useMemo(
 () =>
 localizeSchema(
 payload.template.schema as unknown as LocalizedIntakeSchema,
 i18n.language,
 ),
 [payload.template.schema, i18n.language],
 );
 const editable = payload.editable;
 const intakeId = payload.intake.id;

 const storageKey = `intake-${token}`;
 const [answers, setAnswers] = useState<Record<string, any>>(() => {
 if (typeof window !== "undefined") {
 try {
 const cached = localStorage.getItem(storageKey);
 if (cached) return { ...payload.answers, ...JSON.parse(cached) };
 } catch {}
 }
 return payload.answers ?? {};
 });

 const [currentStep, setCurrentStep] = useState(0);
 const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
 const [dirtyFields, setDirtyFields] = useState<Set<string>>(() => new Set());
 const [errors, setErrors] = useState<Record<string, string>>({});
 const [softWarning, setSoftWarning] = useState<IntakeField[]>([]);
 const [submitting, setSubmitting] = useState(false);
 const [submitted, setSubmitted] = useState(payload.intake.status === "submitted");
  const [confirmDialog, setConfirmDialog] = useState(false);
  const [proposals, setProposals] = useState<Proposals | null>(null);
  const isValidationPhase = payload.phase === "validation";
  // Per-card "Houd Nestor's voorstel" confirmations, lifted out of DiffCard so they
  // survive section navigation (cards unmount on next/back — live-UAT issue 2026-07-13).
  const [confirmedDiffKeys, setConfirmedDiffKeys] = useState<ReadonlySet<string>>(new Set());
  const confirmDiffKey = (cardKey: string) =>
    setConfirmedDiffKeys((prev) => new Set(prev).add(cardKey));

  // Validation-phase AI proposals: read the latest succeeded run's parsed output
  // through the space-scoped seam (the same one-shot heavy read the admin review
  // uses). Without it the ValidationDiff affordances render nothing — the client
  // would see "gereviewd" with no visible refinements (live-UAT gap 2026-07-13).
  useEffect(() => {
    if (!isValidationPhase || proposals !== null) return;
    let cancelled = false;
    (async () => {
      const runsRes = await listSkillRuns(payload.intake.id);
      if (cancelled || !runsRes.success) return;
      // Proposals come ONLY from the apply-intake-skill run. Now that context-pack /
      // structure-answers also land `succeeded` runs (07-09 projects `skill`), require the
      // discriminator so a non-proposals run is never mistaken for the source (drop the
      // bare-latest fallback — a succeeded context-pack run must not drive proposals).
      const latest = runsRes.data.runs.find(
        (r) => r.skill === "apply-intake-skill" && r.status === "succeeded",
      );
      if (!latest) return;
      const fullRes = await getSkillRunFull(payload.intake.id, latest.id);
      if (cancelled || !fullRes.success) return;
      const parsed = fullRes.data.output_parsed;
      if (parsed && typeof parsed === "object") setProposals(parsed as Proposals);
    })();
    return () => {
      cancelled = true;
    };
  }, [isValidationPhase, proposals, payload.intake.id]);

 const sections = useMemo(
 () =>
 schema.sections.filter((s) => {
 if (s.admin_only) return false;
 return !s.phase || s.phase === (payload.phase ?? "intake");
 }),
 [schema.sections, payload.phase],
 );
 const section = sections[currentStep];
 const isLast = currentStep === sections.length - 1;

 const completedSections = useMemo(() => {
 return sections.map((s) => {
 const allRequiredFilled = sectionMissingRequired(s, answers).length === 0;
 const anyFilled = s.fields.some((f) => !isFieldEmpty(answers[f.key]));
 return allRequiredFilled && anyFilled;
 });
 }, [sections, answers]);

 const handleChange = useCallback(
 (key: string, value: any) => {
 setAnswers((prev) => {
 const next = { ...prev, [key]: value };
 try {
 localStorage.setItem(storageKey, JSON.stringify(next));
 } catch {}
 return next;
 });
 setErrors((e) => {
 const { [key]: _, ...rest } = e;
 return rest;
 });

 // Section-batch save (D-03): edits only mark the section dirty — no per-field
 // network call. The whole section's dirty batch is PATCHed on advance/leave.
 if (!editable) return;
 setDirtyFields((prev) => {
 const next = new Set(prev);
 next.add(key);
 return next;
 });
 setSaveStatus("dirty");
 },
 [storageKey, editable],
 );

 // PATCH the current section's dirty answers in one batch. Returns false on failure
 // so callers can GATE navigation (UI-SPEC Net-New 3: a failed PATCH does not advance).
 const saveCurrentSection = useCallback(async (): Promise<boolean> => {
 if (!editable) return true;
 const dirtyKeys = section.fields
 .map((f) => f.key)
 .filter((k) => dirtyFields.has(k));
 if (dirtyKeys.length === 0) return true;
 setSaveStatus("saving");
 const batch: AnswerInput[] = dirtyKeys.map((k) => toAnswerInput(k, answers[k]));
 const res = await saveAnswers(intakeId, batch);
 if (!res.success) {
 setSaveStatus("error");
 toast.error(t("save.sectionFailed"));
 return false;
 }
 setDirtyFields((prev) => {
 const next = new Set(prev);
 dirtyKeys.forEach((k) => next.delete(k));
 return next;
 });
 setSaveStatus("saved");
 return true;
 }, [editable, section, dirtyFields, answers, intakeId, t]);

 // clear localStorage when fully submitted
 useEffect(() => {
 if (submitted) {
 try {
 localStorage.removeItem(storageKey);
 } catch {}
 }
 }, [submitted, storageKey]);

 const goToSection = async (idx: number) => {
 // Persist the leaving section's dirty batch BEFORE navigating; gate on success.
 if (idx !== currentStep) {
 const ok = await saveCurrentSection();
 if (!ok) return;
 }
 setCurrentStep(idx);
 setSoftWarning([]);
 if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
 };

 const validateCurrent = (): boolean => {
 const newErrors: Record<string, string> = {};
 for (const f of section.fields) {
 const err = validateField(f, answers[f.key], t);
 if (err) newErrors[f.key] = err;
 }
 setErrors(newErrors);
 if (Object.keys(newErrors).length > 0) return false;
 const soft = sectionMissingSoft(section, answers);
 setSoftWarning(soft);
 return true;
 };

 const handleNext = async () => {
 if (!validateCurrent()) return;
 // goToSection saves the current section first and aborts on a failed PATCH.
 await goToSection(currentStep + 1);
 };

 const handleSubmit = async () => {
 // validate all sections
 let firstBadIdx = -1;
 const allErrors: Record<string, string> = {};
 sections.forEach((s, idx) => {
 for (const f of s.fields) {
 const err = validateField(f, answers[f.key], t);
 if (err) {
 allErrors[f.key] = err;
 if (firstBadIdx === -1) firstBadIdx = idx;
 }
 }
 });
 if (firstBadIdx !== -1) {
 setErrors(allErrors);
 setCurrentStep(firstBadIdx);
 toast.error(t("validation.fillRequired"));
 return;
 }
 // soft check across all sections
 const softMissing = sections.flatMap((s) =>
 s.soft_gate ? sectionMissingSoft(s, answers) : [],
 );
 if (softMissing.length > 0 && !confirmDialog) {
 setConfirmDialog(true);
 return;
 }
 await doSubmit();
 };

 const doSubmit = async () => {
 setSubmitting(true);
 setConfirmDialog(false);
 // Persist the final (current) section before the transition, gate on success.
 const saved = await saveCurrentSection();
 if (!saved) {
 setSubmitting(false);
 return;
 }
 const res = await submitIntake(intakeId);
 setSubmitting(false);
 if (!res.success) {
 toast.error(t("form.submitFailed", { error: res.error }));
 return;
 }
 setSubmitted(true);
 try {
 localStorage.removeItem(storageKey);
 } catch {}
 };

 if (submitted) {
 const isValidation = payload.phase === "validation";
 const title = isValidation
 ? t("validationPhase.doneTitle")
 : schema.submit.confirmation_title;
 const msg = isValidation
 ? t("validationPhase.doneMessage")
 : (schema.submit.confirmation_message || "").replace(
 /\{\{contact_email\}\}/g,
 String(answers.contact_email ?? ""),
 );
 return (
 <div className="flex min-h-screen items-center justify-center bg-paper px-6">
 <div className="max-w-xl text-center">
 <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-full bg-ink text-paper">
 ✓
 </div>
 <h1 className="text-3xl font-semibold tracking-tight text-ink">
 {title}
 </h1>
 <p className="mt-4 whitespace-pre-line leading-relaxed text-ink/60">{msg}</p>
 </div>
 </div>
 );
 }

 const isValidation = payload.phase === "validation";
 const displayTitle = isValidation
 ? schema.title.replace(/\s*[—-]\s*Intake\s*$/i, "") + t("validationPhase.titleSuffix")
 : schema.title;
 const displaySubtitle = isValidation
 ? t("validationPhase.subtitle")
 : schema.subtitle;

 return (
 <div className="min-h-screen bg-paper text-ink">
 <div className="mx-auto max-w-6xl px-6 py-12 md:py-16">
        {/* Header */}
        <header className="mb-10">
          <div className="flex items-start justify-between gap-4">
            <p className="font-mono text-xs uppercase tracking-widest text-ink/60">
              {t("form.brand")}
            </p>
            {/* Client form language switcher (D-08); persists post-login. */}
            <div className="w-40 shrink-0">
              <LanguageSwitcher persist />
            </div>
          </div>
          <h1 className="mt-3 font-serif text-3xl font-normal lowercase tracking-tight md:text-4xl">
            {displayTitle}
          </h1>
          {displaySubtitle && (
            <p className="mt-3 max-w-2xl text-ink/60">{displaySubtitle}</p>
          )}
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs uppercase tracking-wider text-ink/60">
            <span>{t("form.for", { name: payload.client.name })}</span>
            {schema.estimated_minutes && !isValidation && (
              <span>{t("form.estimatedTime", { minutes: schema.estimated_minutes })}</span>
            )}
          </div>
 {isValidation && (
 <div className="mt-6 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4 text-ink">
 <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">{t("validationPhase.banner")}</div>
 <p className="font-sans text-sm text-ink">
 {t("validationPhase.bannerBody")}
 </p>
 </div>
 )}
 </header>

 <div className="grid gap-8 md:grid-cols-[320px_1fr]">
 {/* Sidebar */}
 <aside className="hidden md:block">
 <nav className="sticky top-8 space-y-1">
 {sections.map((s, idx) => {
 const active = idx === currentStep;
 const done = completedSections[idx];
 const sectionDirty = s.fields.some((f) => dirtyFields.has(f.key));
 const changed = isValidationPhase && sectionHasChange(s, answers, proposals);
 return (
   <button
   key={s.id}
   type="button"
   onClick={() => goToSection(idx)}
   className={
   "flex w-full items-start gap-2 px-3 py-2 text-left font-mono text-xs uppercase tracking-wider leading-[1.4] transition-colors " +
   (active
   ? "bg-paper2 text-ink"
   : "text-ink/60 hover:bg-ink/5 hover:text-ink")
   }
   >
   <span className={"nav-mark " + (sectionDirty ? "" : active ? "nav-mark-green" : "nav-mark-ink")} />
   <span className="flex flex-1 flex-col gap-0.5">
     <span className="break-words">{s.title}</span>
     {changed && (
       <span className="mt-0.5 inline-block self-start border border-agenic-yellow bg-paperLight px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink">
         {t("form.changed")}
       </span>
     )}
   </span>
   </button>
 );
 })}
 </nav>
 </aside>

 {/* Form area */}
 <div>
 <div className="mb-4 flex items-center justify-between">
 <p className="text-sm text-ink/60">
 {t("form.step", { current: currentStep + 1, total: sections.length })}
 </p>
 <p className="text-xs text-ink/40 font-mono">
 {saveStatus === "dirty" && t("save.unsaved")}
 {saveStatus === "saving" && t("save.saving")}
 {saveStatus === "saved" && t("save.saved")}
 {saveStatus === "error" && <span className="text-red-600">{t("save.failed")}</span>}
 </p>
 </div>

  <div className="border border-ink bg-paper p-6 md:p-10">
  <div className="mb-6">
  <h2 className="font-serif text-2xl font-normal lowercase tracking-tight text-ink">
  {section.title}
  {section.optional && (
  <span className="ml-2 font-mono text-xs uppercase tracking-wider text-ink/40">
  {t("form.optional")}
  </span>
  )}
  </h2>
 {section.description && (
 <p className="mt-2 text-sm leading-relaxed text-ink/60">
 {section.description}
 </p>
 )}
 </div>

 {softWarning.length > 0 && (
 <div className="mb-6 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4">
 <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">{t("form.attention")}</div>
 <ul className="list-disc space-y-1 pl-5 text-ink font-sans">
 {softWarning.map((f) => (
 <li key={f.key}>{f.soft_required_message ?? t("form.fieldEmpty", { label: f.label })}</li>
 ))}
 </ul>
 </div>
 )}

 <div className="space-y-6">
 {section.fields.map((f) => (
 <div key={f.key}>
 <FieldRenderer
 field={f}
 value={answers[f.key]}
 onChange={(v) => handleChange(f.key, v)}
 intakeId={intakeId}
 error={errors[f.key]}
 disabled={!editable}
 />
 {isValidationPhase && (
 <ValidationDiffForField
 field={f}
 answer={answers[f.key]}
 proposals={proposals}
 confirmedKeys={confirmedDiffKeys}
 onConfirmKey={confirmDiffKey}
 onRevert={(key, value) => {
 // Revert marks the field dirty; it persists with the section batch on leave.
 handleChange(key, value);
 }}
 />
 )}
 </div>
 ))}
 </div>
 </div>

  <div className="mt-6 flex items-center justify-between">
  <button
  type="button"
  onClick={() => goToSection(Math.max(0, currentStep - 1))}
  disabled={currentStep === 0}
  className="btn-secondary disabled:opacity-40"
  >
  {t("form.previous")}
  </button>

  {isLast ? (
  <button
  type="button"
  onClick={handleSubmit}
  disabled={submitting || (!editable && !isValidation)}
  className="btn-primary"
  >
  {submitting
  ? t("form.submitting")
  : isValidation
  ? t("validationPhase.approveSubmit")
  : schema.submit.label}
  </button>
  ) : (
  <button
  type="button"
  onClick={handleNext}
  className="btn-primary"
  >
  {t("form.next")}
  </button>
  )}
  </div>
  </div>
  </div>
  </div>

  {confirmDialog && (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
  <div className="max-w-md border border-ink bg-paper p-6">
  <h3 className="font-serif text-xl lowercase">{t("confirm.title")}</h3>
  <p className="mt-2 text-sm text-ink/60">
  {t("confirm.body")}
  </p>
  <div className="mt-6 flex justify-end gap-2">
  <button onClick={() => setConfirmDialog(false)} className="btn-secondary">
  {t("confirm.cancel")}
  </button>
  <button onClick={doSubmit} className="btn-primary">
  {t("confirm.confirm")}
  </button>
  </div>
  </div>
  </div>
  )}
 </div>
 );
}
