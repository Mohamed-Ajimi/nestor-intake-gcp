import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useActiveSkillRun, useSkillRunFull, type ActiveSkillRun } from "@/components/intake/SkillRunProgress";
import { format, formatDistanceToNow } from "date-fns";
import { useTranslation } from "react-i18next";
import i18n from "@/lib/i18n";
import { getDateLocale } from "@/lib/i18n/date-locale";
import { resolveErrorKey } from "@/lib/i18n/error-codes";
import { toast } from "sonner";
import { ArrowLeft, Clock, Copy, Loader2, Pencil, X, Save, Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import {
  getIntake,
  submitIntake,
  reviewIntake,
  sendIntakeMail,
  type IntakeMailType,
} from "@/lib/api/intakes";
import { RecipientPicker } from "@/components/intake/RecipientPicker";
import { listAnswers, saveAnswers, type AnswerInput } from "@/lib/api/answers";
import { listSkillRuns } from "@/lib/api/skillRuns";
import { getContextPack } from "@/lib/api/contextPack";
import * as skills from "@/lib/api/skills";
import * as storage from "@/lib/api/storage";
import { getTemplates } from "@/lib/api/templates";
import type { IntakeField, IntakeSchema, LocalizedIntakeSchema } from "@/lib/intake-types";
import { localizeSchema } from "@/lib/i18n/localizeSchema";
import { FieldDisplay, isFieldDisplayEmpty } from "@/components/intake/FieldDisplay";
import { FieldRenderer } from "@/components/intake/FieldRenderer";
import { IntakeWorkflowStepper } from "@/components/intake/IntakeWorkflowStepper";
import {
 AIReviewTopBanner,
 AIReviewInfoBanners,
 ExtraQuestionsSection,
 InlineFieldSuggestion,
 InlineResearchQuestionsSuggestions,
 RESEARCH_QUESTIONS_FIELD_KEY,
 ReviewProvider,
 ReviewSuccessModal,
 
 submitReview,
 useAIReview,
 type ParsedSkillOutput,
} from "@/components/intake/AIReviewPanel";

// Stable empty fallback for useAIReview — must be module-level, not inline `{}`.
// An inline `?? {}` creates a new object reference on every render, which fires the
// `useEffect([parsed])` inside useAIReview on every render → infinite setState loop.
const EMPTY_PARSED: ParsedSkillOutput = {};

import { Skeleton } from "@/components/ui/skeleton";
import { NextStepBanner, type BusyKey } from "@/components/intake/NextStepBanner";
import { ResearchArtifactsBlock } from "@/components/intake/ResearchArtifacts";
import { ResearchRunProgress } from "@/components/intake/ResearchRunProgress";
import { triggerResearch } from "@/lib/api/research";
import { FinalReportBlock } from "@/components/intake/FinalReportBlock";
import { ContextPackBlock } from "@/components/intake/ContextPackBlock";
import { AISkillsPanel } from "@/components/intake/AISkillsPanel";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  derivePhase,
  type PhaseSkillRunInput,
  phaseShowsAIReview,
  phaseShowsContextPack,
  phaseShowsFinalReport,
  phaseShowsResearch,
  phaseShowsSemanticSearch,
} from "@/lib/intake-phase";

import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/admin/pulse/intakes/$id")({
 component: IntakeDetailPage,
});

type Intake = {
 id: string;
 title: string | null;
 status: string | null;
 product_slug: string;
 template_id: string;
 client_id: string;
 client_intake_token: string | null;
 client_validation_token: string | null;
 client_results_token: string | null;
 final_report_artifact_id: string | null;
 validation_link_sent_at: string | null;
 results_link_sent_at: string | null;
 context_pack_artifact_id: string | null;
 conducted_at: string | null;
 conducted_by: string | null;
  client_validated_at: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
 product: { slug: string; name: string; tagline: string | null } | null;
 template: { id: string; name: string; version: number; schema: IntakeSchema } | null;
};

type Client = { id: string; name: string; country: string | null; website: string | null };

type AnswerRow = {
 field_key: string;
 value: unknown;
 edited_by_client: boolean | null;
 client_edited_at: string | null;
 updated_at: string;
};

type SkillRun = {
 id: string;
 skill_name: string;
 status: string;
 model: string | null;
 output: string | null;
 cost_estimate_usd: number | null;
 triggered_at: string;
 completed_at: string | null;
 applied_at: string | null;
 error_message?: string | null;
};


// Status values are the stable domain keys; labels/banners/hints are looked up in the
// admin catalog at render time via t("intakeDetail.status.<value>") etc. (Phase 11).
const STATUS_VALUES = [
 "draft",
 "submitted",
 "reviewed",
 "validated_by_client",
 "decomposed",
 "in_research",
 "delivered",
 "archived",
] as const;

const STATUS_VARIANT: Record<string, { cls: string; mark?: "ink" | "green" | null }> = {
 draft: { cls: "badge-dashed" },
 submitted: { cls: "badge-ink" },
 reviewed: { cls: "badge-outline", mark: "green" },
 validated_by_client: { cls: "badge-ink", mark: "green" },
 decomposed: { cls: "badge-outline" },
 in_research: { cls: "badge-outline", mark: "green" },
 delivered: { cls: "badge-ink" },
 archived: { cls: "badge-outline text-ink/40 border-ink/40" },
};

// Status banners/hints that exist in the catalog. A value absent from these sets has no
// banner/hint (guards the render sites, which only show when a catalog entry exists).
const STATUS_WITH_BANNER = new Set([
 "draft",
 "submitted",
 "reviewed",
 "validated_by_client",
 "decomposed",
 "in_research",
 "delivered",
 "archived",
]);
const STATUS_WITH_HINT = new Set(["reviewed", "validated_by_client"]);

// Phase machine lives in @/lib/intake-phase. The detail-page derives a single
// Phase from intake + latest intake-skill-run + hasResearchArtifacts.


function StatusPill({ status }: { status: string | null }) {
 const { t } = useTranslation("admin");
 if (!status) return null;
 const v = STATUS_VARIANT[status] ?? { cls: "badge-outline" };
 const label = t(`intakeDetail.status.${status}`, status).toUpperCase();
 return (
 <span className={cn(v.cls)}>
 {v.mark === "green" && <span className="mark-green" />}
 {v.mark === "ink" && <span className="mark-ink" />}
 {label}
 </span>
 );
}

function fmt(d: string | null | undefined) {
 if (!d) return "—";
 try {
 return format(new Date(d), "d MMM yyyy 'om' HH:mm", { locale: getDateLocale(i18n.language) });
 } catch {
 return d;
 }
}

function isEmptyVal(v: unknown): boolean {
 if (v === null || v === undefined) return true;
 if (typeof v === "string" && v.trim() === "") return true;
 if (Array.isArray(v) && v.length === 0) return true;
 if (typeof v === "object" && v !== null) {
 if ("choice" in (v as Record<string, unknown>)) {
 return !(v as { choice?: string }).choice;
 }
 if ("path" in (v as Record<string, unknown>)) {
 return !(v as { path?: string }).path;
 }
 }
 return false;
}

function IntakeDetailPage() {
 const { id } = Route.useParams();
  const { t, i18n } = useTranslation("admin");
  const { session } = useAuth();
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [intake, setIntake] = useState<Intake | null>(null);
 const [client, setClient] = useState<Client | null>(null);
 const [answers, setAnswers] = useState<AnswerRow[]>([]);
 const [activeSection, setActiveSection] = useState<string | null>(null);
 const sectionRefs = useRef<Record<string, HTMLElement | null>>({});

 const [editMode, setEditMode] = useState(false);
 const [draft, setDraft] = useState<Record<string, unknown>>({});
 const [initial, setInitial] = useState<Record<string, unknown>>({});
 const [saving, setSaving] = useState(false);
 // WR-04: object paths whose backend delete is deferred until the edit draft is saved.
 // A replaced/removed file in edit mode queues its old path here instead of deleting it
 // immediately, so a Cancel leaves the persisted answer's object intact. Flushed after a
 // successful save; cleared on cancel. A ref (not state) — it never drives rendering.
 const pendingRemovals = useRef<string[]>([]);
 const [updatingStatus, setUpdatingStatus] = useState(false);

 const [skillLoading, setSkillLoading] = useState(false);
 const [reviewMode, setReviewMode] = useState(false);
 const [reviewData, setReviewData] = useState<{
 runId: string;
 parsed: ParsedSkillOutput;
 costEur: number | null;
 } | null>(null);
 const [submittingReview, setSubmittingReview] = useState(false);
 const [successUrl, setSuccessUrl] = useState<string | null>(null);
  const [optimisticRunStartedAt, setOptimisticRunStartedAt] = useState<string | null>(null);
 const reviewState = useAIReview(reviewData?.parsed ?? EMPTY_PARSED);
 const [historyOpen, setHistoryOpen] = useState(false);
  const [skillRuns, setSkillRuns] = useState<SkillRun[] | null>(null);
   const [loadingRuns, setLoadingRuns] = useState(false);

  // Lightweight poll of latest nestor-intake skill_run (status only).
  // Memory-safe: never selects output/output_parsed, stops as soon as status != 'running'.
  const queryClient = useQueryClient();
  const { data: activeRun } = useActiveSkillRun(intake?.id, skillLoading);
  // (isSkillRunning removed — phase-machine + bannerActiveRun handle running state)
  const bannerActiveRun: ActiveSkillRun | null =
    skillLoading && optimisticRunStartedAt && activeRun?.status !== "running"
      ? {
          id: "starting",
          status: "running",
          skill: activeRun?.skill ?? "apply-intake-skill",
          triggered_at: optimisticRunStartedAt,
          completed_at: null,
          applied_at: null,
          error: null,
        }
      : activeRun ?? null;
  const activeRunId = activeRun?.id;
  const activeRunStatus = activeRun?.status;
  const activeRunTriggeredAt = activeRun?.triggered_at;
  // A one-shot signal that changes only when a CONTEXT-PACK run reaches a terminal
  // status, so ContextPackBlock re-reads the pack even on a re-generate of an
  // already-`decomposed` intake (where the status-driven reload would not fire). Gated on
  // the skill discriminator so an apply-intake-skill terminal never bumps it.
  const contextPackReloadSignal =
    activeRun?.skill === "context-pack" &&
    (activeRunStatus === "succeeded" || activeRunStatus === "failed")
      ? `${activeRunStatus}:${activeRunId}`
      : null;
  // Track which run we've already consumed into review-mode so we don't loop.
  const [consumedRunId, setConsumedRunId] = useState<string | null>(null);
  useEffect(() => {
    if (!activeRunTriggeredAt) return;
    if (optimisticRunStartedAt && activeRunTriggeredAt < optimisticRunStartedAt) return;
    setOptimisticRunStartedAt(null);
    setSkillLoading(false);
  }, [activeRunId, activeRunStatus, activeRunTriggeredAt, optimisticRunStartedAt]);

  // hasResearchArtifacts is FALSE this milestone: no research artifacts are created
  // pre-`decomposed` (Bucket E / Phase-Ceiling). The post-decomposed research surface
  // never renders here, so derivePhase is fed `false` (no inline DB read remains).
  const [hasArtifacts] = useState(false);

  // The phase machine must only ever see apply-intake-skill runs: enrichment skills
  // (structure-answers, extract-insights, …) also land `succeeded` runs, and feeding one
  // to derivePhase fakes "analysis ready" on a submitted intake (UAT 2026-07-16 finding).
  // When the LATEST run is a non-apply skill, fall back to the newest apply-intake-skill
  // run from the full list so a finished analysis is not forgotten either.
  const [applyRunFallback, setApplyRunFallback] =
    useState<PhaseSkillRunInput | null>(null);
  const intakeId = intake?.id;
  useEffect(() => {
    if (!intakeId || !activeRun || activeRun.skill === "apply-intake-skill") {
      setApplyRunFallback(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const res = await listSkillRuns(intakeId);
      if (cancelled || !res.success) return;
      // Don't assume server ordering — pick the apply run with the max completed_at.
      const apply = res.data.runs
        .filter((r) => r.skill === "apply-intake-skill")
        .reduce<
          (typeof res.data.runs)[number] | null
        >((best, r) => ((r.completed_at ?? "") > (best?.completed_at ?? "") ? r : best), null);
      setApplyRunFallback(
        apply ? { status: apply.status, applied_at: apply.applied_at } : null,
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [intakeId, activeRun]);

  const phase = useMemo(() => {
    if (!intake) return null;
    return derivePhase(
      {
        status: intake.status,
        validation_link_sent_at: intake.validation_link_sent_at,
        results_link_sent_at: intake.results_link_sent_at,
        context_pack_artifact_id: intake.context_pack_artifact_id,
        final_report_artifact_id: intake.final_report_artifact_id,
      },
      activeRun
        ? activeRun.skill === "apply-intake-skill"
          ? { status: activeRun.status, applied_at: activeRun.applied_at }
          : applyRunFallback
        : null,
      hasArtifacts,
    );
  }, [intake, activeRun, applyRunFallback, hasArtifacts]);

  // Auto-fetch full skill-run output ONLY when we're in the review phase.
  const shouldFetchFull =
    phase === "awaiting_review" &&
    !!activeRun &&
    activeRun.id !== consumedRunId &&
    !reviewMode;
  const { data: fullRun } = useSkillRunFull(intake?.id, activeRun?.id, shouldFetchFull);

  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<
    {
      question_priority: number;
      source: string;
      similarity: number;
      chunk_text: string;
    }[]
  >([]);


 const handleSubmitReview = async () => {
 if (!reviewData || !intake) return;
 setSubmittingReview(true);
 try {
 const token = await submitReview({
 intakeId: intake.id,
 runId: reviewData.runId,
 parsed: reviewData.parsed,
 state: reviewState,
 currentResearchQuestions: initial["research_questions"],
 });
 setSuccessUrl(`${window.location.origin}/intake/${token}`);
 } catch (e) {
 toast.error(`${t("intakeDetail.toast.sendFailed")}: ${(e as Error).message}`);
 } finally {
 setSubmittingReview(false);
 }
 };

 const load = useCallback(async () => {
 setLoading(true);
 const intakeRes = await getIntake(id);
 if (!intakeRes.success) {
 const codeKey = resolveErrorKey(intakeRes.code);
 setError(codeKey ? t(codeKey) : intakeRes.error || t("intakeDetail.error.notFound"));
 setLoading(false);
 return;
 }
 const v = intakeRes.data;

 // The seam Intake carries status + the five phase markers; the legacy intake row
 // also carried title/product/tokens/timestamps that the backend IntakeView does not
 // project. Those are token-model / post-decomposed concerns retired this milestone —
 // populate the local row from the seam and leave the rest neutral so derivePhase and
 // the answer/section rendering stay correct.
 const tmplRes = await getTemplates();
 const tmpl = tmplRes.success && tmplRes.data.length > 0 ? tmplRes.data[0] : null;
 const nowIso = new Date().toISOString();
 const intakeRow: Intake = {
 id: v.id,
 title: null,
 status: v.status,
 product_slug: "",
 template_id: tmpl?.id ?? "",
 client_id: "",
 client_intake_token: null,
 client_validation_token: null,
 client_results_token: null,
 final_report_artifact_id: v.final_report_artifact_id,
 validation_link_sent_at: v.validation_link_sent_at,
 results_link_sent_at: v.results_link_sent_at,
 context_pack_artifact_id: v.context_pack_artifact_id,
 conducted_at: null,
 conducted_by: null,
 client_validated_at: null,
 delivered_at: null,
 created_at: nowIso,
 updated_at: nowIso,
 product: null,
 template: tmpl
 ? { id: tmpl.id, name: tmpl.name, version: 1, schema: tmpl.schema as unknown as IntakeSchema }
 : null,
 };
 setIntake(intakeRow);
 setClient(
 v.client_name ? { id: "", name: v.client_name, country: null, website: null } : null,
 );

 const answersRes = await listAnswers(id);
 const rows: AnswerRow[] = answersRes.success
 ? answersRes.data.map((a) => ({
 field_key: a.field_key,
 value: a.value_json ?? a.value,
 edited_by_client: null,
 client_edited_at: null,
 updated_at: "",
 }))
 : [];
 setAnswers(rows);
 const initialMap: Record<string, unknown> = {};
 rows.forEach((r) => (initialMap[r.field_key] = r.value));
 setInitial(initialMap);
 setDraft(initialMap);
 setLoading(false);
 }, [id]);

 useEffect(() => {
 let cancelled = false;
 (async () => {
 if (!cancelled) await load();
 })();
 return () => {
 cancelled = true;
 };
 }, [load]);

 const answersMap = useMemo(() => {
 const m = new Map<string, AnswerRow>();
 answers.forEach((a) => m.set(a.field_key, a));
 return m;
 }, [answers]);

 // The template carries the RAW multi-locale schema (LocalizedString objects, Phase 11).
 // Flatten to the active locale at the consumption seam — rendering the raw objects
 // makes React throw "Objects are not valid as a React child" (CR-01). Re-resolves on
 // language change (nl fallback, D-05), mirroring IntakeForm's useMemo pattern.
 const sections = useMemo(
 () =>
 intake?.template?.schema
 ? localizeSchema(
 intake.template.schema as unknown as LocalizedIntakeSchema,
 i18n.language,
 ).sections
 : [],
 [intake?.template?.schema, i18n.language],
 );

 const allFields = useMemo(() => {
 const list: IntakeField[] = [];
 sections.forEach((s) => s.fields.forEach((f) => list.push(f)));
 return list;
 }, [sections]);

 const changedKeys = useMemo(() => {
 const set = new Set<string>();
 allFields.forEach((f) => {
 const a = JSON.stringify(draft[f.key] ?? null);
 const b = JSON.stringify(initial[f.key] ?? null);
 if (a !== b) set.add(f.key);
 });
 return set;
 }, [draft, initial, allFields]);

 const hasChanges = changedKeys.size > 0;

 useEffect(() => {
 if (!sections.length) return;
 const observer = new IntersectionObserver(
 (entries) => {
 const visible = entries
 .filter((e) => e.isIntersecting)
 .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
 if (visible[0]) setActiveSection(visible[0].target.id);
 },
 { rootMargin: "-20% 0px -70% 0px", threshold: 0 },
 );
 sections.forEach((s) => {
 const el = sectionRefs.current[s.id];
 if (el) observer.observe(el);
 });
 return () => observer.disconnect();
 }, [sections]);

 const copyLink = async () => {
 if (!intake) return;
 // Authenticated client route since Phase 6 — /intake/{id}, no legacy bearer token.
 const url = `${window.location.origin}/intake/${intake.id}`;
 try {
 await navigator.clipboard.writeText(url);
 toast.success(t("intakeDetail.toast.linkCopied"));
 } catch {
 toast.error(t("intakeDetail.toast.copyFailed"));
 }
 };

 const handleStatusChange = async (newStatus: string) => {
 if (!intake) return;
 // Status moves only via the allow-listed transition verbs (<= decomposed). Targets
 // past the milestone ceiling are intentionally unreachable from the seam (INTAKE-05).
 setUpdatingStatus(true);
 let res;
 if (newStatus === "reviewed") {
 res = await reviewIntake(intake.id);
 } else if (newStatus === "submitted" || newStatus === "validated_by_client") {
 res = await submitIntake(intake.id);
 } else {
 setUpdatingStatus(false);
 toast.error(t("intakeDetail.toast.statusUnavailable"));
 return;
 }
 setUpdatingStatus(false);
 if (!res.success) {
 const codeKey = resolveErrorKey(res.code);
 toast.error(
 codeKey ? t(codeKey) : `${t("intakeDetail.toast.statusNotUpdated")}: ${res.error}`,
 );
 return;
 }
 setIntake({ ...intake, status: res.data.status });
 toast.success(t("intakeDetail.toast.statusUpdated"));
 };

 // Read intakeId through a ref so loadSkillRuns can have a stable (empty) dep array.
 // Previously [intake] as a dep caused a new function reference on every load(), which
 // cascaded into the review-mode and terminal-status effects — causing the "Maximum
 // update depth exceeded" loop when any setState (including Popover open) triggered a
 // re-render. Stable reference = effects that list loadSkillRuns in deps fire only when
 // their other deps actually change.
 const intakeIdForRuns = useRef<string | undefined>(undefined);
 intakeIdForRuns.current = intake?.id;

 const loadSkillRuns = useCallback(async () => {
 if (!intakeIdForRuns.current) return;
 setLoadingRuns(true);
 const [res, packRes] = await Promise.all([
 listSkillRuns(intakeIdForRuns.current),
 getContextPack(intakeIdForRuns.current),
 ]);
 const mapped: SkillRun[] = res.success
 ? res.data.runs.map((r) => ({
 id: r.id,
 skill_name: r.skill || "apply-intake-skill",
 status: r.status,
 model: null,
 output: null,
 cost_estimate_usd: null,
 triggered_at: r.applied_at ?? r.completed_at ?? "",
 completed_at: r.completed_at,
 applied_at: r.applied_at,
 error_message: null,
 }))
 : [];
 // Context-pack generations surface in the same activity log. The read shape is
 // {latest, history}; latest may or may not be included in history — dedup by id.
 if (packRes.success) {
 const packs = [packRes.data.latest, ...packRes.data.history].filter(
 (p): p is NonNullable<typeof p> => p != null,
 );
 const seen = new Set<string>();
 for (const p of packs) {
 if (seen.has(p.id)) continue;
 seen.add(p.id);
 mapped.push({
 id: p.id,
 skill_name: "context-pack",
 status: "succeeded",
 model: null,
 output: null,
 cost_estimate_usd: null,
 triggered_at: p.created_at ?? "",
 completed_at: p.created_at,
 applied_at: null,
 error_message: null,
 });
 }
 }
 // Chronological ascending — the Sheet renders [...runs].reverse() (newest first).
 mapped.sort((a, b) => a.triggered_at.localeCompare(b.triggered_at));
 setSkillRuns(mapped);
 setLoadingRuns(false);
 // eslint-disable-next-line react-hooks/exhaustive-deps
 }, []);

 const toggleHistory = () => {
 const next = !historyOpen;
 setHistoryOpen(next);
 if (next && skillRuns === null) loadSkillRuns();
 };

  // History accordion-only: skill runs are not auto-loaded on page-load.
  // The ['active-skill-run'] hook already surfaces the latest run status — nothing
  // more is needed unless the user opens the history accordion.

  const runSkill = async () => {
    // Dispatch the Phase-7 apply-intake-skill run (202 + run id). The optimistic
    // "running" banner + force-poll (Phase 8 machinery above) take over from here;
    // the effect on activeRunTriggeredAt clears the optimistic state once the real
    // run row is visible, and the SSE/poll path drives progress to the review panel.
    if (!intake) return;
    setBusyKey("runSkill", true);
    try {
      const res = await skills.applyIntakeSkill(intake.id);
      if (!res.success) {
        const codeKey = resolveErrorKey(res.code);
        toast.error(codeKey ? t(codeKey) : `${t("intakeDetail.toast.aiStartFailed")}: ${res.error}`);
        return;
      }
      setOptimisticRunStartedAt(new Date().toISOString());
      setSkillLoading(true);
    } finally {
      setBusyKey("runSkill", false);
    }
  };

  // ============== Phase-driven CTA handlers ==============
  const [busy, setBusy] = useState<Partial<Record<BusyKey, boolean>>>({});
  const setBusyKey = (k: BusyKey, v: boolean) =>
    setBusy((b) => ({ ...b, [k]: v }));

  // Recipient picker (Phase 10): which client-facing mail type is being sent, if any.
  // Opening the picker sets the type; the picker self-loads the intake's active members
  // (listSpaceMembers) and returns the selected membership ids to `handleSendMail`.
  const [mailPickerType, setMailPickerType] = useState<IntakeMailType | null>(null);
  // S3: house-style archive confirmation dialog (replaces the native confirm()).
  const [archiveConfirmOpen, setArchiveConfirmOpen] = useState(false);
  // 260716-ji9: Intake-info moved out of the page flow into a header-triggered modal.
  const [infoModalOpen, setInfoModalOpen] = useState(false);
  // Map each mail type to the busy key NextStepBanner already reads.
  const MAIL_BUSY_KEY: Record<IntakeMailType, BusyKey> = {
    intake: "sendIntake",
    validation: "sendValidation",
    reminder: "sendReminder",
    results: "sendResults",
  };

  const handleSendMail = async (recipients: string[]) => {
    if (!intake || !mailPickerType) return;
    const type = mailPickerType;
    const busyKey = MAIL_BUSY_KEY[type];
    setBusyKey(busyKey, true);
    try {
      const res = await sendIntakeMail(intake.id, type, recipients);
      if (!res.success) {
        const codeKey = resolveErrorKey(res.code);
        toast.error(codeKey ? t(codeKey) : `${t("intakeDetail.toast.sendFailed")}: ${res.error}`);
        return;
      }
      // D-16: the backend returns HTTP 200 with `{ success: false }` when the Resend
      // transport fails (no sent-at stamped, no audit row). `res.success` is only the
      // transport-level flag (true on any 2xx), so we MUST inspect the body-level
      // `res.data.success` — otherwise a failed send toasts success and the operator
      // never learns the client didn't get the mail.
      if (!res.data.success) {
        toast.error(t("intakeDetail.toast.mailNotSent"));
        return; // keep the picker open so the operator can retry
      }
      toast.success(t("intakeDetail.toast.mailSent"));
      setMailPickerType(null);
      // Refresh the intake so the sent-at markers (validation/results) re-drive the phase.
      void load();
    } finally {
      setBusyKey(busyKey, false);
    }
  };

  const origin = () => (typeof window !== "undefined" ? window.location.origin : "");

  const copyLinkGeneric = async (url: string | null, missingMsg: string) => {
    if (!url) {
      toast.error(missingMsg);
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      toast.success(t("intakeDetail.toast.linkCopied"));
    } catch {
      toast.error(t("intakeDetail.toast.copyFailed"));
    }
  };

  // Since Phase 6 the client area is authenticated at /intake/{id} (no bearer tokens).
  // Validation renders on the SAME /intake/{id} page when status is `reviewed`; results
  // is /intake/{id}/results. All three copy handlers build from intake.id.
  const onCopyIntakeLink = () =>
    copyLinkGeneric(
      intake ? `${origin()}/intake/${intake.id}` : null,
      t("intakeDetail.toast.intakeNotLoaded"),
    );
  const onCopyValidationLink = () =>
    copyLinkGeneric(
      intake ? `${origin()}/intake/${intake.id}` : null,
      t("intakeDetail.toast.intakeNotLoaded"),
    );
  const onCopyResultsLink = () =>
    copyLinkGeneric(
      intake ? `${origin()}/intake/${intake.id}/results` : null,
      t("intakeDetail.toast.intakeNotLoaded"),
    );

  const onOpenAIReview = () => {
    const el = document.querySelector("[data-ai-review-block]");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    else toast(t("intakeDetail.toast.aiReviewNotLoaded"));
  };

  // Transactional email (Phase 10): each CTA opens the RecipientPicker, which self-loads
  // the intake's active members and returns the selected membership ids to `handleSendMail`.
  const onSendIntakeMail = () => setMailPickerType("intake");

  const onSendValidationMail = async () => {
    setMailPickerType("validation");
  };

  const onSendValidationReminder = async () => {
    setMailPickerType("reminder");
  };

  const onGenerateContextPack = async () => {
    // Dispatch the Phase-7 context-pack run (202 + run id). The run finalizes
    // server-side (research_artifacts row + status bump to decomposed); the page
    // reloads intake/run state when the active-run poll observes the change.
    if (!intake) return;
    setBusyKey("generateContextPack", true);
    try {
      const res = await skills.generateContextPack(intake.id);
      if (!res.success) {
        const codeKey = resolveErrorKey(res.code);
        toast.error(codeKey ? t(codeKey) : `${t("intakeDetail.toast.contextPackStartFailed")}: ${res.error}`);
        return;
      }
      toast.success(t("intakeDetail.toast.contextPackStarted"));
      setOptimisticRunStartedAt(new Date().toISOString());
      setSkillLoading(true);
    } finally {
      setBusyKey("generateContextPack", false);
    }
  };

  // Phase 16 (RUN-01/SEAM-03): fire the deep-research trigger. The confirm dialog lives in
  // NextStepBanner — this handler is only reached AFTER the operator confirms, so it POSTs
  // the 202 directly (D-03). Return-no-throw: `triggerResearch` surfaces failures as
  // `{success,error}`; on success the backend has flipped the intake to `in_research`, so
  // a `load()` re-fetch swaps the banner for the live ResearchRunProgress panel below.
  const onStartAutoResearch = async () => {
    setBusyKey("startResearch", true);
    try {
      const res = await triggerResearch(id);
      if (!res.success) {
        const codeKey = resolveErrorKey(res.code);
        toast.error(codeKey ? t(codeKey) : res.error || t("intakeDetail.toast.researchStartFailed"));
        return;
      }
      toast.success(t("intakeDetail.toast.researchStarted"));
      await load();
    } finally {
      setBusyKey("startResearch", false);
    }
  };

  // Re-trigger from the failure card in ResearchRunProgress. The 3-attempt cap (D-04) is
  // enforced server-side; an over-cap retry is rejected by the backend and surfaced here.
  const onRetryResearch = async () => {
    const res = await triggerResearch(id);
    if (!res.success) {
      const codeKey = resolveErrorKey(res.code);
      toast.error(codeKey ? t(codeKey) : res.error || t("intakeDetail.toast.researchStartFailed"));
      return;
    }
    toast.success(t("intakeDetail.toast.researchStarted"));
    await load();
  };

  const onDownloadContextPack = () => {
    const el = document.querySelector("[data-context-pack-block]");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    else toast(t("intakeDetail.toast.scrollToContextPack"));
  };

  const onUploadFinalReport = () => {
    const el = document.querySelector("[data-final-report-block]");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    else toast(t("intakeDetail.toast.scrollToFinalReport"));
  };

  const onSendResultsMail = async () => {
    setMailPickerType("results");
  };

  const onArchive = async () => {
    if (!intake) return;
    setArchiveConfirmOpen(true);
  };

  const confirmArchive = async () => {
    setArchiveConfirmOpen(false);
    setBusyKey("archive", true);
    await handleStatusChange("archived");
    setBusyKey("archive", false);
  };

  // When the polled run flips to 'succeeded' for a run we haven't consumed yet,
  // fetch the full row once and enter review-mode.
  useEffect(() => {
    if (!fullRun || !activeRun) return;
    // Review mode is ONLY driven by an apply-intake-skill run. Now that context-pack (and
    // other enrichment skills) also land `succeeded` runs, the latest run can be a
    // context-pack run — guard on the skill discriminator so it never enters review mode.
    if (activeRun.skill !== "apply-intake-skill") return;
    if (activeRun.id === consumedRunId) return;
    const parsed = (fullRun as { output_parsed?: ParsedSkillOutput }).output_parsed;
    if (!parsed) {
      // Never dead-end silently: the banner says "review ready" — tell the admin the
      // output is unusable, and consume the run id so this fires once, not in a loop.
      setConsumedRunId(activeRun.id);
      toast.error(t("intakeDetail.toast.reviewOutputMissing"));
      return;
    }
    const costUsd = (fullRun as { cost_estimate_usd?: number | null }).cost_estimate_usd ?? null;
    const costEur = costUsd != null ? costUsd * 0.92 : null;
    setReviewData({ runId: activeRun.id, parsed, costEur });
    setReviewMode(true);
    setConsumedRunId(activeRun.id);
    loadSkillRuns();
  }, [fullRun, activeRun, consumedRunId, loadSkillRuns, t]);

  // Terminal SSE event → re-fetch the intake + skill runs (D-09) so `derivePhase`
  // reflects the server-side status transition (e.g. → `decomposed`) WITHOUT a manual
  // reload — Realtime-parity UX. The `useActiveSkillRun` hook flips `activeRunStatus`
  // to a terminal value on the stream's terminal event; this effect reacts to it.
  // Guarded by a ref so each terminal run drives exactly one refresh (no loop). This
  // does NOT touch the review-mode effect above — the chain terminal → phase flips →
  // shouldFetchFull true → useSkillRunFull fetches output_parsed → review effect fires
  // stays wired.
  const refreshedRunRef = useRef<string | null>(null);
  useEffect(() => {
    if (!activeRunId || !activeRunStatus) return;
    if (activeRunStatus !== "succeeded" && activeRunStatus !== "failed") return;
    if (refreshedRunRef.current === activeRunId) return;
    refreshedRunRef.current = activeRunId;
    void load();
    void loadSkillRuns();
  }, [activeRunId, activeRunStatus, load, loadSkillRuns]);

  const exitReviewMode = async () => {
    setReviewMode(false);
    setReviewData(null);
    await load();
  };

  const handleSemanticSearch = async () => {
    // Space-scoped semantic search over artifact embeddings (Phase-7 AI-04 read half).
    // Backend returns {id, artifact_id, chunk_text, distance}; the panel renders the
    // legacy shape, so map similarity = 1 - distance and artifact_id -> source.
    if (!intake || !searchQuery.trim()) return;
    setSearching(true);
    try {
      const res = await skills.searchIntakeArtifacts(intake.id, searchQuery.trim());
      if (!res.success) {
        const codeKey = resolveErrorKey(res.code);
        toast.error(codeKey ? t(codeKey) : `${t("intakeDetail.toast.searchFailed")}: ${res.error}`);
        return;
      }
      setSearchResults(
        res.data.results.map((r) => ({
          question_priority: 0,
          source: r.artifact_id ?? "",
          similarity: r.distance === null ? 0 : 1 - r.distance,
          chunk_text: r.chunk_text,
        })),
      );
    } finally {
      setSearching(false);
    }
  };


 const handleCancel = () => {
 if (hasChanges) {
 if (!confirm(t("intakeDetail.confirm.discardChanges"))) return;
 }
 // WR-04: drop queued deletes — the stored objects the draft would have removed must
 // survive a cancel (the persisted answers still reference them).
 pendingRemovals.current = [];
 setDraft(initial);
 setEditMode(false);
 };

 const handleSave = async () => {
 if (!intake) return;
 if (!hasChanges) {
 toast(t("intakeDetail.toast.noChanges"));
 setEditMode(false);
 return;
 }
 setSaving(true);
 // Batch every changed field into one section-style PATCH (D-03). Emptied fields
 // are sent as null/null so the backend upsert clears them on (intake_id, field_key).
 const batch: AnswerInput[] = Array.from(changedKeys).map((key) => {
 const val = draft[key];
 if (isEmptyVal(val)) return { field_key: key, value: null, value_json: null };
 if (typeof val === "string") return { field_key: key, value: val, value_json: null };
 return { field_key: key, value: null, value_json: val };
 });
 const res = await saveAnswers(intake.id, batch);
 if (!res.success) {
 setSaving(false);
 const codeKey = resolveErrorKey(res.code);
 toast.error(codeKey ? t(codeKey) : `${t("intakeDetail.toast.saveFailed")}: ${res.error}`);
 return;
 }
 // WR-04: the draft is now persisted — it is finally safe to delete the objects that
 // replaced/removed files pointed at. Fire AFTER the save succeeds; a failed delete is
 // surfaced but does not undo the save (the answer no longer references the object).
 const toRemove = pendingRemovals.current;
 pendingRemovals.current = [];
 if (toRemove.length > 0) {
 const del = await storage.removeFile({ intakeId: intake.id, paths: toRemove });
 if (!del.success) {
 toast.error(`${t("intakeDetail.toast.cleanupFailed")}: ${del.error}`);
 }
 }
 setSaving(false);
 toast.success(t("intakeDetail.toast.changesSaved"));
 setEditMode(false);
 await load();
 };

 if (loading) {
 return (
 <div>
 <Skeleton className="h-8 w-64" />
 <Skeleton className="mt-3 h-4 w-96" />
 <div className="mt-8 space-y-6">
 {Array.from({ length: 4 }).map((_, i) => (
 <div key={i}>
 <Skeleton className="h-6 w-48" />
 <Skeleton className="mt-3 h-32 w-full" />
 </div>
 ))}
 </div>
 </div>
 );
 }

 if (error || !intake) {
 return (
 <div className="mx-auto max-w-md py-16 text-center">
 <p className="text-sm text-ink/60">
 {t("intakeDetail.error.notFoundOrDeleted")}
 </p>
 <Link
 to="/admin/pulse/intakes"
 className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-ink hover:underline"
 >
 <ArrowLeft className="h-4 w-4" />
 {t("intakeDetail.error.backToList")}
 </Link>
 </div>
 );
 }

 const projectNameAnswer = answersMap.get("project_name")?.value;
 const projectNameStr =
 typeof projectNameAnswer === "string" && projectNameAnswer.trim()
 ? projectNameAnswer.trim()
 : null;
 const headerTitle = projectNameStr
 ? `${client?.name ?? t("intakeDetail.unknownClient")} — ${projectNameStr}`
 : intake.title || intake.product?.name || "";
 const intakeUrl = `${typeof window !== "undefined" ? window.location.origin : ""}/intake/${intake.id}`;
 const statusHint =
 intake.status && STATUS_WITH_HINT.has(intake.status)
 ? t(`intakeDetail.statusHint.${intake.status}`)
 : undefined;
 const currentPhase = phase ?? "awaiting_client_submission";
 const showAIReview = phaseShowsAIReview(currentPhase);
 const showContextPack = phaseShowsContextPack(currentPhase);
 const showResearch = phaseShowsResearch(currentPhase);
 const showSemanticSearch = phaseShowsSemanticSearch(currentPhase) && hasArtifacts;
 const showFinalReport = phaseShowsFinalReport(currentPhase);


 return (
 <ReviewProvider parsed={reviewData?.parsed ?? {}} state={reviewState} intakeId={intake?.id} runId={reviewData?.runId}>
 <div>
 <div
 className={cn(
 "sticky top-0 z-20 -mx-6 -mt-8 mb-6 border-b bg-paper/90 px-6 py-4 backdrop-blur md:-mx-10 md:-mt-10 md:px-10",
 editMode ? "border-ink border-b-2" : "border-ink/10",
 )}
 >
 <Link
 to="/admin/pulse/intakes"
 className="inline-flex items-center gap-1 font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
 >
 <ArrowLeft className="h-3.5 w-3.5" />
 {t("intakeDetail.header.intakes")}
 </Link>
 <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
 <div>
 <h1 className="font-serif text-2xl font-normal lowercase tracking-tight text-ink">{headerTitle}</h1>
              <p className="mt-0.5 text-xs text-ink/60">
                {t("intakeDetail.header.lastEdited")}{" "}
                {formatDistanceToNow(new Date(intake.updated_at), {
                  addSuffix: true,
                  locale: getDateLocale(i18n.language),
                })}
                {intake.delivered_at && (
                  <>
                    <span className="mx-2 text-ink/30">·</span>
                    {t("intakeDetail.header.deliveredOn")}{" "}
                    {format(new Date(intake.delivered_at), "d MMM yyyy", {
                      locale: getDateLocale(i18n.language),
                    })}
                  </>
                )}
              </p>
 </div>
 <div className="flex flex-wrap items-center gap-2">
 <button
 type="button"
 onClick={() => setInfoModalOpen(true)}
 className="border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
 >
 {t("intakeDetail.info.openButton")}
 </button>
 <button
 type="button"
 onClick={toggleHistory}
 className="inline-flex items-center gap-1.5 border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
 >
 <Clock className="h-3.5 w-3.5" />
 {t("intakeDetail.history.title")}
 {skillRuns && skillRuns.length > 0 && (
 <span className="tabular-nums">({skillRuns.length})</span>
 )}
 </button>
 <div className="flex flex-col">
 <select
 value={intake.status ?? ""}
 disabled={updatingStatus}
 onChange={(e) => handleStatusChange(e.target.value)}
 className="border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink focus:outline-none"
 >
 {STATUS_VALUES.map((value) => (
 <option key={value} value={value}>
 {t(`intakeDetail.status.${value}`)}
 </option>
 ))}
 </select>
 </div>

 {!editMode ? (
 <button
 type="button"
 onClick={() => setEditMode(true)}
 className="inline-flex items-center gap-1.5 bg-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90"
 >
 <Pencil className="h-3.5 w-3.5" />
 {t("intakeDetail.action.edit")}
 </button>
 ) : (
 <>
 <button
 type="button"
 onClick={handleCancel}
 className="inline-flex items-center gap-1.5 border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
 >
 <X className="h-3.5 w-3.5" />
 {t("intakeDetail.action.cancel")}
 </button>
 <button
 type="button"
 onClick={handleSave}
 disabled={saving}
 className="inline-flex items-center gap-1.5 bg-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90 disabled:opacity-50"
 >
 {saving ? (
 <Loader2 className="h-3.5 w-3.5 animate-spin" />
 ) : (
 <Save className="h-3.5 w-3.5" />
 )}
 {t("intakeDetail.action.save")}
 </button>
 </>
 )}
 </div>
 </div>
 {statusHint && (
 <p className="mt-2 text-xs text-ink/60">{statusHint}</p>
 )}
 </div>


  {showAIReview && reviewMode && reviewData && (
 <div data-ai-review-block>
 <AIReviewTopBanner
 costEur={reviewData.costEur}
 decidedCount={reviewState?.decidedCount ?? 0}
 onCancel={() => {
 setReviewMode(false);
 setReviewData(null);
 }}
 onSubmit={handleSubmitReview}
 submitting={submittingReview}
 />
 <AIReviewInfoBanners parsed={reviewData.parsed} />
 </div>
 )}

 {successUrl && (
 <ReviewSuccessModal
 url={successUrl}
 onClose={async () => {
 setSuccessUrl(null);
 await exitReviewMode();
 }}
 />
 )}

      {/* Workflow card — full-width in the center flow, above the content sections. */}
      <div className="mb-8 border border-ink/15 bg-paper">
       <div className="px-6 pt-6 pb-4">
         <IntakeWorkflowStepper
           status={intake.status}
           clientValidatedAt={intake.client_validated_at}
           submittedAt={intake.updated_at}
         />
       </div>

       {!editMode && !reviewMode && intake.status && STATUS_WITH_BANNER.has(intake.status) && (
         <div className="border-t border-ink/10 bg-paper2 px-6 py-3 text-xs text-ink/70">
           {t(`intakeDetail.statusBanner.${intake.status}`)}
         </div>
       )}

       {/* Phase 16 (RUN-01/D-07): the operator's live window into a Tribunal run. Mounts
           on the ADMIN detail route only (T-16-12/D-08 — no client-facing research surface).
           Renders the stage list dynamically from the mirrored research_runs row. */}
       {intake.status === "in_research" && (
         <ResearchRunProgress intakeId={intake.id} onRetry={onRetryResearch} />
       )}
      </div>

      {/* 2-col layout: content left, sticky action rail (next step + AI tools + search) right on xl+ */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_272px] xl:gap-8 xl:items-start">

        <aside className="mb-6 xl:mb-0 xl:col-start-2 xl:row-start-1 xl:sticky xl:top-[88px] xl:self-start">
     <div className="border border-ink/15 bg-paper">
       <NextStepBanner
         phase={currentPhase}
         validationLinkSentAt={intake.validation_link_sent_at}
         resultsLinkSentAt={intake.results_link_sent_at}
         deliveredAt={intake.delivered_at}
         activeRun={bannerActiveRun}
         busy={busy}
         onRunSkill={runSkill}
         onSendIntakeMail={onSendIntakeMail}
         onCopyIntakeLink={onCopyIntakeLink}
         onOpenAIReview={onOpenAIReview}
         onSendValidationMail={onSendValidationMail}
         onCopyValidationLink={onCopyValidationLink}
         onSendValidationReminder={onSendValidationReminder}
         onGenerateContextPack={onGenerateContextPack}
         onStartAutoResearch={onStartAutoResearch}
         onDownloadContextPack={onDownloadContextPack}
         onUploadFinalReport={onUploadFinalReport}
         onSendResultsMail={onSendResultsMail}
         onCopyResultsLink={onCopyResultsLink}
         onArchive={onArchive}
       />


       {/* AI enrichment skills — self-gates on status (submitted → decomposed).
           Lives inside the workflow card as a secondary action block, not floating
           in the content area. */}
        <AISkillsPanel intakeId={intake.id} intakeStatus={intake.status} />

       {showSemanticSearch && (
         <section className="border-t border-ink/10 bg-paperLight p-4">
           <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60 mb-2">
             {t("intakeDetail.search.title")}
           </div>
           <div className="flex gap-2">
             <input
               type="text"
               value={searchQuery}
               onChange={(e) => setSearchQuery(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && handleSemanticSearch()}
               placeholder={t("intakeDetail.search.placeholder")}
               className="flex-1 border border-ink/30 px-3 py-2 font-mono text-sm bg-paper"
             />
             <button
               type="button"
               onClick={handleSemanticSearch}
               disabled={searching}
               className="font-mono text-xs uppercase tracking-wider bg-ink text-paperLight px-4 py-2 disabled:opacity-50"
             >
               {searching ? "…" : `🔍 ${t("intakeDetail.search.button")}`}
             </button>
           </div>
           {searchResults.length > 0 && (
             <div className="mt-4 space-y-2">
               <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
                 {t("intakeDetail.search.results", { count: searchResults.length })}
               </div>
               {searchResults.map((r, i) => (
                 <div key={i} className="border-l-2 border-fluoYellow pl-3 py-2">
                   <div className="text-[10px] font-mono text-ink/60 mb-1">
                     V{r.question_priority} · {r.source} · score {(r.similarity * 100).toFixed(0)}%
                   </div>
                   <div className="text-sm">{r.chunk_text}</div>
                 </div>
               ))}
             </div>
           )}
         </section>
       )}

     </div>
        </aside>

        <div className="min-w-0 xl:col-start-1 xl:row-start-1">
 {editMode && (
 <div className="mb-6 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4">
 <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">
 {t("intakeDetail.editBanner.title")}
 </div>
 <div className="text-ink font-sans">
 {t("intakeDetail.editBanner.body")}
 </div>
 </div>
 )}

 <div className="grid grid-cols-1 gap-8 lg:grid-cols-[240px_1fr]">
 <aside className="hidden lg:block">
 <nav className="sticky top-28 space-y-1">
 <p className="mb-2 font-mono text-xs uppercase tracking-wider text-ink/60">
 {t("intakeDetail.sections.nav")}
 </p>
 {sections.map((s) => {
 const isActive = activeSection === s.id;
 const hasContent = s.fields.some(
 (f) => !isFieldDisplayEmpty(f, answersMap.get(f.key)?.value),
 );
 return (
 <a
 key={s.id}
 href={`#${s.id}`}
 className={cn(
 "flex w-full items-start gap-2 px-3 py-2 font-mono text-xs uppercase tracking-wider leading-[1.4] transition-colors",
 isActive ? "bg-paper2 text-ink" : "text-ink/60 hover:bg-ink/5 hover:text-ink",
 )}
 >
 <span className={"nav-mark " + (isActive ? "nav-mark-green" : "nav-mark-ink")} />
 <span className="flex-1 break-words">{s.title}</span>
 </a>
 );
 })}
 </nav>
 </aside>

 <main className="min-w-0 space-y-10">

  {showContextPack && (
    <div data-context-pack-block>
      <ContextPackBlock
        intakeId={intake.id}
        intakeStatus={intake.status}
        intakeTitle={intake.title ?? ""}
        clientName={client?.name ?? "—"}
        reloadSignal={contextPackReloadSignal}
      />
    </div>
  )}

    {showFinalReport && (
      <div data-final-report-block>
        <FinalReportBlock
          intakeId={intake.id}
          finalReportArtifactId={intake.final_report_artifact_id}
          intakeStatus={intake.status}
          hasResultsToken={!!intake.client_results_token}
          onChange={async () => {
            // The Deliver/Replace verb owns the transition (18-01) — reload the intake
            // from the backend view so the phase machine advances from the AUTHORITATIVE
            // status/final_report_artifact_id/results_link_sent_at, never a client-side fake.
            const res = await getIntake(intake.id);
            if (!res.success) return;
            setIntake({
              ...intake,
              status: res.data.status,
              final_report_artifact_id: res.data.final_report_artifact_id,
              results_link_sent_at: res.data.results_link_sent_at,
            });
          }}
        />
      </div>
    )}


   {showResearch && (
     <ResearchArtifactsBlock
       intakeId={intake.id}
       intakeStatus={intake.status}
       onStartResearch={() => handleStatusChange("in_research")}
     />
   )}


   {sections.map((section) => {
   const hasProposalList = section.fields.some((f) => f.type === "proposal_list");
 const allEmpty =
 !editMode &&
 section.fields.every((f) => isFieldDisplayEmpty(f, answersMap.get(f.key)?.value));
 if (allEmpty && !reviewMode) return null;
 return (
 <section
 key={section.id}
 id={section.id}
 ref={(el) => {
 sectionRefs.current[section.id] = el;
 }}
 className="scroll-mt-32 border border-ink/10 bg-paper p-6"
 >
 <h2 className="border-b border-ink/30 pb-2 mb-2 font-serif text-2xl font-normal text-ink">
 {section.title}
 </h2>
 {section.description && (
 <p className="mb-4 font-sans text-sm text-ink/60">{section.description}</p>
 )}
 {reviewMode && reviewData && hasProposalList ? (
 <div className="mt-4">
 <ExtraQuestionsSection state={reviewState} inline />
 </div>
 ) : editMode ? (
 <div className="mt-4 space-y-6">
 {section.fields.map((field) => {
 if (field.type === "download") return null;
 const changed = changedKeys.has(field.key);
 return (
 <div
 key={field.key}
 className={cn(
 "p-3 -mx-3",
 changed && "border border-ink border-l-4 border-l-agenic-yellow bg-paperLight",
 )}
 >
 <div className="flex items-center gap-2 mb-1">
 {changed && (
 <span className="border border-ink bg-agenic-yellow px-2 py-0.5 font-mono text-xs uppercase tracking-wider text-ink">
 {t("intakeDetail.field.changed")}
 </span>
 )}
 </div>
 <FieldRenderer
 field={field}
 value={draft[field.key]}
 onChange={(v) => setDraft((d) => ({ ...d, [field.key]: v }))}
 intakeId={intake.id}
 onDeferRemove={(paths) => {
 pendingRemovals.current.push(...paths);
 }}
 onUndoDeferRemove={(paths) => {
 pendingRemovals.current = pendingRemovals.current.filter((p) => !paths.includes(p));
 }}
 />
 </div>
 );
 })}
 </div>
 ) : (
 <dl className="mt-3">
 {section.fields.map((field) => {
 const a = answersMap.get(field.key);
 return (
 <div key={field.key}>
 <FieldDisplay
 field={field}
 value={a?.value}
 intakeId={intake.id}
 editedByClient={a?.edited_by_client ?? false}
 clientEditedAt={a?.client_edited_at ?? null}
 />
 {reviewMode && reviewData && (
 <>
 <InlineFieldSuggestion fieldKey={field.key} currentValue={a?.value} />
 {field.key === RESEARCH_QUESTIONS_FIELD_KEY && (
 <InlineResearchQuestionsSuggestions />
 )}
 </>
 )}
 </div>
 );
 })}
 </dl>
 )}
 </section>
 );
  })}
 </main>
 </div>

        </div>

      </div>

     {/* Phase-10 recipient picker — mounted once; the active mail type controls its open state. */}
     {mailPickerType && (
       <RecipientPicker
         open={mailPickerType !== null}
         onOpenChange={(o) => {
           if (!o) setMailPickerType(null);
         }}
         intakeId={intake.id}
         type={mailPickerType}
         busy={Boolean(busy[MAIL_BUSY_KEY[mailPickerType]])}
         onConfirm={handleSendMail}
       />
     )}

     {/* S3: archive confirmation — hand-rolled fixed-overlay dialog (house modal style). */}
     {archiveConfirmOpen && (
       <div
         className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
         onClick={() => setArchiveConfirmOpen(false)}
       >
         <div
           role="alertdialog"
           className="w-full max-w-md border border-ink bg-paper p-6 shadow-lg"
           onClick={(e) => e.stopPropagation()}
         >
           <h2 className="font-serif text-2xl font-normal lowercase text-ink">
             {t("intakeDetail.archiveDialog.title")}
           </h2>
           <p className="mt-3 font-sans text-sm leading-relaxed text-ink/70">
             {t("intakeDetail.archiveDialog.body")}
           </p>
           <div className="mt-6 flex justify-end gap-2">
             <button
               type="button"
               onClick={() => setArchiveConfirmOpen(false)}
               className="border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
             >
               {t("intakeDetail.archiveDialog.cancel")}
             </button>
             <button
               type="button"
               onClick={confirmArchive}
               className="bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85"
             >
               {t("intakeDetail.archiveDialog.confirm")}
             </button>
           </div>
         </div>
       </div>
     )}

     {/* 260716-ji9: Intake-info modal — the dl moved verbatim from the first page section;
         same house overlay convention as the archive dialog, but wider + scrollable. */}
     {infoModalOpen && (
       <div
         className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
         onClick={() => setInfoModalOpen(false)}
       >
         <div
           role="dialog"
           className="max-h-[85vh] w-full max-w-2xl overflow-y-auto border border-ink bg-paper p-6 shadow-lg"
           onClick={(e) => e.stopPropagation()}
         >
           <h2 className="border-b border-ink/30 pb-2 mb-2 font-serif text-2xl font-normal text-ink">
             {t("intakeDetail.info.title")}
           </h2>
           <dl className="mt-4">
             <Meta label={t("intakeDetail.info.client")}>
               {client ? (
                 <Link to="/admin/pulse/clients" className="text-ink hover:underline">
                   {client.name}
                 </Link>
               ) : (
                 "—"
               )}
             </Meta>
             <Meta label={t("intakeDetail.info.product")}>
               {intake.product ? (
                 <>
                   <span className="text-ink">{intake.product.name}</span>
                   {intake.product.tagline && (
                     <span className="text-ink/60"> ({intake.product.tagline})</span>
                   )}
                 </>
               ) : (
                 intake.product_slug
               )}
             </Meta>
             <Meta label={t("intakeDetail.info.status")}>
               <StatusPill status={intake.status} />
             </Meta>
             <Meta label={t("intakeDetail.info.createdAt")}>{fmt(intake.created_at)}</Meta>
             <Meta label={t("intakeDetail.info.lastEdited")}>{fmt(intake.updated_at)}</Meta>
             {(intake.status === "delivered" || intake.status === "archived") && (
               <Meta label={t("intakeDetail.info.deliveredOn")}>
                 <DeliveredAtEditor
                   intakeId={intake.id}
                   value={intake.delivered_at}
                   onSaved={(v) => setIntake({ ...intake, delivered_at: v })}
                 />
               </Meta>
             )}
             <Meta label={t("intakeDetail.info.initialIntakeLink")}>
               <LinkRow
                 url={intakeUrl}
                 subtitle={t("intakeDetail.info.initialIntakeLinkSubtitle")}
                 placeholder="—"
               />
             </Meta>
             <Meta label={t("intakeDetail.info.validationLink")}>
               <LinkRow
                 url={`${typeof window !== "undefined" ? window.location.origin : ""}/intake/${intake.id}`}
                 subtitle={t("intakeDetail.info.validationLinkSubtitle")}
                 placeholder="—"
               />
             </Meta>
             <Meta label={t("intakeDetail.info.validation")}>
               {intake.client_validated_at ? (
                 <span className="text-emerald-700">
                   {t("intakeDetail.info.validatedOn", { date: fmt(intake.client_validated_at) })}
                 </span>
               ) : (
                 <span className="text-ink/60">{t("intakeDetail.info.notYetValidated")}</span>
               )}
             </Meta>
             <Meta
               label={
                 <span className="inline-flex items-center gap-1">
                   {t("intakeDetail.info.resultsLink")}
                   <span
                     className="cursor-help text-ink/40"
                     title={t("intakeDetail.info.resultsLinkTooltip")}
                   >
                     ⓘ
                   </span>
                 </span>
               }
             >
               <ResultsLinkRow
                 intakeId={intake.id}
                 hasFinalReport={!!intake.final_report_artifact_id}
               />
             </Meta>
           </dl>
           <div className="mt-6 flex justify-end">
             <button
               type="button"
               onClick={() => setInfoModalOpen(false)}
               className="border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
             >
               {t("intakeDetail.info.close")}
             </button>
           </div>
         </div>
       </div>
     )}


     {/* Run-history Sheet — slides in from the right */}
     <Sheet open={historyOpen} onOpenChange={(o) => {
       if (!o) setHistoryOpen(false);
       else { setHistoryOpen(true); if (skillRuns === null) loadSkillRuns(); }
     }}>
       <SheetContent
         side="right"
         className="w-full max-w-sm bg-paper border-l border-ink/15 p-0 flex flex-col"
       >
         <SheetHeader className="border-b border-ink/10 px-6 py-5">
           <SheetTitle className="font-mono text-[11px] uppercase tracking-wider text-ink/60 font-normal">
             {t("intakeDetail.history.title")}
             {skillRuns && skillRuns.length > 0 && (
               <span className="ml-2 tabular-nums text-ink/40">({skillRuns.length})</span>
             )}
           </SheetTitle>
         </SheetHeader>

         <div className="flex-1 overflow-y-auto">
           {loadingRuns ? (
             <div className="flex items-center gap-2 px-6 py-8 text-sm text-ink/50">
               <Loader2 className="h-4 w-4 animate-spin" />
               {t("intakeDetail.history.loading")}
             </div>
           ) : !skillRuns || skillRuns.length === 0 ? (
             <p className="px-6 py-8 text-sm text-ink/40">
               {t("intakeDetail.history.empty")}
             </p>
           ) : (
             <ol className="divide-y divide-ink/5">
               {[...skillRuns].reverse().map((r) => {
                 const label = t(`intakeDetail.history.skill.${r.skill_name}`, r.skill_name);
                 const isOk   = r.status === "succeeded";
                 const isFail = r.status === "failed";
                 const isRun  = r.status === "running" || r.status === "queued";
                 return (
                   <li key={r.id} className="px-6 py-4 space-y-1.5">
                     <div className="flex items-center justify-between gap-2">
                       <span className="font-mono text-[11px] uppercase tracking-wider text-ink">
                         {label}
                       </span>
                       <span className={[
                         "font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5",
                         isOk   ? "bg-green-50 text-green-700"  : "",
                         isFail ? "bg-red-50 text-red-600"      : "",
                         isRun  ? "bg-amber-50 text-amber-700"  : "",
                         !isOk && !isFail && !isRun ? "bg-ink/5 text-ink/40" : "",
                       ].filter(Boolean).join(" ")}>
                         {isOk
                           ? t("intakeDetail.history.done")
                           : isFail
                             ? t("intakeDetail.history.failed")
                             : isRun
                               ? t("intakeDetail.history.busy")
                               : r.status}
                       </span>
                     </div>
                     <p className="font-sans text-xs text-ink/50">{fmt(r.triggered_at)}</p>
                     {r.cost_estimate_usd != null && (
                       <p className="font-mono text-[11px] text-ink/40">
                         €{(r.cost_estimate_usd * 0.92).toFixed(3)}
                       </p>
                     )}
                     {isFail && r.error_message && (
                       <p className="font-sans text-xs text-red-500 break-words">{r.error_message}</p>
                     )}
                   </li>
                 );
               })}
             </ol>
           )}
         </div>
       </SheetContent>
     </Sheet>
 </div>
 </ReviewProvider>
 );
}

function Meta({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
 return (
 <div className="grid grid-cols-1 gap-x-8 gap-y-1 border-b border-ink/10 py-4 last:border-b-0 sm:grid-cols-[260px_1fr]">
 <dt className="font-sans text-sm font-normal text-ink/70">{label}</dt>
 <dd className="min-w-0 font-sans text-ink">{children}</dd>
 </div>
 );
}

function DeliveredAtEditor({
  intakeId,
  value,
  onSaved,
}: {
  intakeId: string;
  value: string | null;
  onSaved: (v: string | null) => void;
}) {
  const { t } = useTranslation("admin");
  const [date, setDate] = useState(value ? value.slice(0, 10) : "");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setDate(value ? value.slice(0, 10) : "");
  }, [value]);
  const dirty = (value ? value.slice(0, 10) : "") !== date;
  const save = async () => {
    if (!date) return;
    // delivered_at sits past the decomposed ceiling (delivered phase). There is no seam
    // write for it this milestone; reflect the change locally and surface a notice.
    const iso = new Date(date + "T12:00:00Z").toISOString();
    void intakeId;
    toast.message(t("intakeDetail.deliveredAt.laterPhase"));
    onSaved(iso);
  };
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="border border-ink/30 bg-paper px-3 py-1.5 font-mono text-sm"
        />
        {dirty && (
          <button
            type="button"
            onClick={save}
            disabled={saving || !date}
            className="inline-flex items-center gap-1.5 bg-ink px-3 py-1.5 text-xs font-medium text-paper hover:bg-ink/80 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {t("common:actions.save")}
          </button>
        )}
      </div>
      <p className="text-xs text-ink/50">{t("intakeDetail.deliveredAt.hint")}</p>
    </div>
  );
}

function ResultsLinkRow({
 intakeId,
 hasFinalReport,
}: {
 intakeId: string;
 hasFinalReport: boolean;
}) {
 const { t } = useTranslation("admin");
 // Authenticated results route since Phase 6 — /intake/{id}/results (no bearer token).
 void hasFinalReport;
 const url =
 typeof window !== "undefined" ? `${window.location.origin}/intake/${intakeId}/results` : "";

 const copy = async () => {
 try {
 await navigator.clipboard.writeText(url);
 toast.success(t("intakeDetail.toast.linkCopied"));
 } catch {
 toast.error(t("intakeDetail.toast.copyFailed"));
 }
 };

 return (
 <div className="space-y-1">
 <div className="flex flex-wrap items-center gap-2">
 <code
 title={url}
 className="max-w-full truncate rounded bg-paper2 px-2 py-1 font-mono text-xs text-ink/70 hover:bg-ink/10"
 >
 {url}
 </code>
 <button
 type="button"
 onClick={copy}
 className="inline-flex items-center gap-1.5 border border-ink px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5"
 >
 <Copy className="h-3.5 w-3.5" />
 {t("intakeDetail.action.copy")}
 </button>
 </div>
 <p className="text-xs text-ink/40">{t("intakeDetail.info.resultsLinkHint")}</p>
 </div>
 );
}

function LinkRow({
 url,
 subtitle,
 placeholder,
}: {
 url: string | null;
 subtitle: string;
 placeholder: string;
}) {
 const { t } = useTranslation("admin");
 const copy = async () => {
 if (!url) return;
 try {
 await navigator.clipboard.writeText(url);
 toast.success(t("intakeDetail.toast.linkCopied"));
 } catch {
 toast.error(t("intakeDetail.toast.copyFailed"));
 }
 };
 return (
 <div className="space-y-1">
 <div className="flex flex-wrap items-center gap-2">
 {url ? (
 <>
 <code
 title={url}
 className="max-w-full truncate rounded bg-paper2 px-2 py-1 font-mono text-xs text-ink/70 hover:bg-ink/10"
 >
 {url}
 </code>
 <button
 type="button"
 onClick={copy}
 className="inline-flex items-center gap-1.5 border border-ink px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5"
 >
 <Copy className="h-3.5 w-3.5" />
 {t("intakeDetail.action.copy")}
 </button>
 </>
 ) : (
 <span className="text-sm text-ink/40">{placeholder}</span>
 )}
 </div>
 <p className="text-xs text-ink/40">{subtitle}</p>
 </div>
 );
}
