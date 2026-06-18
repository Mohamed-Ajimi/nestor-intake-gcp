import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useActiveSkillRun, useSkillRunFull, type ActiveSkillRun } from "@/components/intake/SkillRunProgress";
import { format, formatDistanceToNow } from "date-fns";
import { nl } from "date-fns/locale";
import { toast } from "sonner";
import { ArrowLeft, Copy, Loader2, Pencil, X, Save, Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import { supabase } from "@/lib/supabase";
import type { IntakeField, IntakeSchema } from "@/lib/intake-types";
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
import { Skeleton } from "@/components/ui/skeleton";
import { NextStepBanner, type BusyKey } from "@/components/intake/NextStepBanner";
import { ResearchArtifactsBlock } from "@/components/intake/ResearchArtifacts";
import { FinalReportBlock } from "@/components/intake/FinalReportBlock";
import { ContextPackBlock } from "@/components/intake/ContextPackBlock";
import {
  derivePhase,
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


const STATUS_OPTIONS: { value: string; label: string }[] = [
 { value: "draft", label: "Concept" },
 { value: "submitted", label: "Ingediend" },
 { value: "reviewed", label: "Gereviewd" },
 { value: "validated_by_client", label: "Gevalideerd" },
 { value: "decomposed", label: "Gedecomposeerd" },
 { value: "in_research", label: "In onderzoek" },
 { value: "delivered", label: "Geleverd" },
 { value: "archived", label: "Gearchiveerd" },
];

const STATUS_LABEL: Record<string, string> = Object.fromEntries(
 STATUS_OPTIONS.map((s) => [s.value, s.label]),
);

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

const STATUS_BANNER: Record<string, string> = {
 draft: "Klant is nog aan het invullen. Link gedeeld maar nog niet ingediend.",
 submitted: "Klant heeft ingediend. Klaar voor jouw review.",
 reviewed: "Door jou gereviewd. Wacht op klant-validatie.",
 validated_by_client: "Klant heeft gevalideerd. Klaar voor decompositie.",
 decomposed: "Decompositie gedaan. Klaar voor onderzoek.",
 in_research: "Nestor onderzoekt.",
 delivered: "Geleverd aan klant.",
 archived: "Gearchiveerd.",
};

const STATUS_HINT: Record<string, string> = {
 reviewed:
 "Klant ziet de wijzigingen pas wanneer je 'Stuur voor validatie' klikt (komt in volgende update).",
 validated_by_client: "Klaar voor decompositie.",
};

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

// Phase machine lives in @/lib/intake-phase. The detail-page derives a single
// Phase from intake + latest intake-skill-run + hasResearchArtifacts.


function StatusPill({ status }: { status: string | null }) {
 if (!status) return null;
 const v = STATUS_VARIANT[status] ?? { cls: "badge-outline" };
 const label = (STATUS_LABEL[status] ?? status).toUpperCase();
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
 return format(new Date(d), "d MMM yyyy 'om' HH:mm", { locale: nl });
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
 const reviewState = useAIReview(reviewData?.parsed ?? {});
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
          triggered_at: optimisticRunStartedAt,
          completed_at: null,
          applied_at: null,
          error: null,
        }
      : activeRun ?? null;
  const activeRunId = activeRun?.id;
  const activeRunStatus = activeRun?.status;
  const activeRunTriggeredAt = activeRun?.triggered_at;
  // Track which run we've already consumed into review-mode so we don't loop.
  const [consumedRunId, setConsumedRunId] = useState<string | null>(null);
  useEffect(() => {
    if (!activeRunTriggeredAt) return;
    if (optimisticRunStartedAt && activeRunTriggeredAt < optimisticRunStartedAt) return;
    setOptimisticRunStartedAt(null);
    setSkillLoading(false);
  }, [activeRunId, activeRunStatus, activeRunTriggeredAt, optimisticRunStartedAt]);

  // hasArtifacts — lightweight count (head, no rows)
  const [hasArtifacts, setHasArtifacts] = useState(false);
  useEffect(() => {
    if (!supabase || !intake?.id) return;
    let cancelled = false;
    void supabase
      .schema("nestor")
      .from("research_artifacts")
      .select("id", { count: "exact", head: true })
      .eq("intake_id", intake.id)
      .neq("source", "context-pack-generator")
      .then(({ count }) => {
        if (!cancelled) setHasArtifacts((count ?? 0) > 0);
      });
    return () => {
      cancelled = true;
    };
  }, [intake?.id, intake?.status]);

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
        ? { status: activeRun.status, applied_at: activeRun.applied_at }
        : null,
      hasArtifacts,
    );
  }, [intake, activeRun, hasArtifacts]);

  // Auto-fetch full skill-run output ONLY when we're in the review phase.
  const shouldFetchFull =
    phase === "awaiting_review" &&
    !!activeRun &&
    activeRun.id !== consumedRunId &&
    !reviewMode;
  const { data: fullRun } = useSkillRunFull(activeRun?.id, shouldFetchFull);

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
 });
 setSuccessUrl(`${window.location.origin}/intake/${token}`);
 } catch (e) {
 toast.error(`Versturen mislukt: ${(e as Error).message}`);
 } finally {
 setSubmittingReview(false);
 }
 };

 const load = useCallback(async () => {
 if (!supabase) {
 setError("Supabase niet geconfigureerd.");
 setLoading(false);
 return;
 }
 setLoading(true);
 const { data: intakeData, error: iErr } = await supabase
 .schema("nestor")
 .from("intakes")
 .select(
        `id, title, status, product_slug, template_id, client_id, client_intake_token, client_validation_token, client_results_token, final_report_artifact_id,
         validation_link_sent_at, results_link_sent_at, context_pack_artifact_id,
         conducted_at, conducted_by, client_validated_at, delivered_at, created_at, updated_at,
 product:products!intakes_product_slug_fkey(slug, name, tagline),
 template:intake_templates!intakes_template_id_fkey(id, name, version, schema)`,
 )
 .eq("id", id)
 .single();
 if (iErr || !intakeData) {
 setError(iErr?.message ?? "Intake niet gevonden.");
 setLoading(false);
 return;
 }
 const intakeRow = intakeData as unknown as Intake;
 setIntake(intakeRow);

 const [clientRes, answersRes] = await Promise.all([
 supabase
 .schema("public" as never)
 .from("clients")
 .select("id, name, country, website")
 .eq("id", intakeRow.client_id)
 .single(),
 supabase
 .schema("nestor")
 .from("intake_answers")
 .select("field_key, value, edited_by_client, client_edited_at, updated_at")
 .eq("intake_id", id),
 ]);
 if (clientRes.data) setClient(clientRes.data as Client);
 const rows = (answersRes.data as AnswerRow[]) ?? [];
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

 const sections = intake?.template?.schema?.sections ?? [];

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
 if (!intake?.client_intake_token) {
 toast.error("Geen intake-token beschikbaar");
 return;
 }
 const url = `${window.location.origin}/intake/${intake.client_intake_token}`;
 try {
 await navigator.clipboard.writeText(url);
 toast.success("Link gekopieerd");
 } catch {
 toast.error("Kopiëren mislukt");
 }
 };

 const handleStatusChange = async (newStatus: string) => {
 if (!supabase || !intake) return;
 setUpdatingStatus(true);
 const { error: e } = await supabase
 .schema("nestor")
 .from("intakes")
 .update({ status: newStatus })
 .eq("id", intake.id);
 setUpdatingStatus(false);
 if (e) {
 toast.error("Status niet bijgewerkt");
 return;
 }
 setIntake({ ...intake, status: newStatus });
 toast.success("Status bijgewerkt");
 };

 const loadSkillRuns = useCallback(async () => {
 if (!supabase || !intake) return;
 setLoadingRuns(true);
 const { data } = await supabase
 .schema("nestor")
 .from("skill_runs")
 .select("id, skill_name, status, model, cost_estimate_usd, triggered_at, completed_at, applied_at, error_message")
 .eq("intake_id", intake.id)
 .order("triggered_at", { ascending: false });
 setSkillRuns((data as SkillRun[]) ?? []);
 setLoadingRuns(false);
 }, [intake]);

 const toggleHistory = () => {
 const next = !historyOpen;
 setHistoryOpen(next);
 if (next && skillRuns === null) loadSkillRuns();
 };

  // History accordion-only: skill runs zijn niet automatisch geladen op page-load.
  // De ['active-skill-run'] hook geeft al de laatste run-status — meer is niet nodig
  // tenzij de gebruiker de history-accordion opent.

  const runSkill = async () => {
    if (!supabase || !intake || !SUPABASE_URL || !SUPABASE_ANON_KEY) return;
    setSkillLoading(true);
    const startedAt = new Date().toISOString();
    setOptimisticRunStartedAt(startedAt);
    try {
      // Fire-and-forget: use raw fetch and never read/parse the 60-120s response body.
      // Status/progress comes only from the lightweight skill_runs poll below.
      void fetch(`${SUPABASE_URL}/functions/v1/apply-intake-skill`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          apikey: SUPABASE_ANON_KEY,
          Authorization: `Bearer ${session?.access_token ?? SUPABASE_ANON_KEY}`,
        },
        body: JSON.stringify({ intake_id: intake.id }),
      })
        .then((response) => {
          if (response.body) void response.body.cancel().catch(() => undefined);
          if (!response.ok) {
            toast.error(`Skill kon niet gestart worden: HTTP ${response.status}`);
            setOptimisticRunStartedAt(null);
            setSkillLoading(false);
          }
        })
        .catch((e) => {
        console.error(e);
        toast.error(`Skill kon niet gestart worden: ${(e as Error).message}`);
        setOptimisticRunStartedAt(null);
        setSkillLoading(false);
      });
      queryClient.invalidateQueries({ queryKey: ["active-skill-run", intake.id] });
      toast.message("Nestor analyseert je intake — dit duurt 90–120s.");
    } catch (e) {
      toast.error(`Skill mislukt: ${(e as Error).message}`);
      setOptimisticRunStartedAt(null);
      setSkillLoading(false);
    }
  };

  // ============== Phase-driven CTA handlers ==============
  const [busy, setBusy] = useState<Partial<Record<BusyKey, boolean>>>({});
  const setBusyKey = (k: BusyKey, v: boolean) =>
    setBusy((b) => ({ ...b, [k]: v }));

  const origin = () => (typeof window !== "undefined" ? window.location.origin : "");

  const copyLinkGeneric = async (url: string | null, missingMsg: string) => {
    if (!url) {
      toast.error(missingMsg);
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link gekopieerd");
    } catch {
      toast.error("Kopiëren mislukt");
    }
  };

  const onCopyIntakeLink = () =>
    copyLinkGeneric(
      intake?.client_intake_token ? `${origin()}/intake/${intake.client_intake_token}` : null,
      "Geen intake-token",
    );
  const onCopyValidationLink = () =>
    copyLinkGeneric(
      intake?.client_validation_token
        ? `${origin()}/intake/${intake.client_validation_token}`
        : null,
      "Geen validatie-token",
    );
  const onCopyResultsLink = () =>
    copyLinkGeneric(
      intake?.client_results_token ? `${origin()}/results/${intake.client_results_token}` : null,
      "Geen resultaten-token",
    );

  const onOpenAIReview = () => {
    const el = document.querySelector("[data-ai-review-block]");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    else toast("AI-review is nog niet geladen — wacht even.");
  };

  const onSendValidationMail = async () => {
    if (!supabase || !intake) return;
    setBusyKey("sendValidation", true);
    const { error } = await supabase.functions.invoke("send-pulse-mail", {
      body: { intake_id: intake.id, mail_type: "validation_request" },
    });
    setBusyKey("sendValidation", false);
    if (error) {
      toast.error(`Verzenden mislukt: ${error.message}`);
      return;
    }
    toast.success("Validatie-link verstuurd");
    await load();
  };

  const onSendValidationReminder = async () => {
    if (!supabase || !intake) return;
    setBusyKey("sendReminder", true);
    const { error } = await supabase.functions.invoke("send-pulse-mail", {
      body: { intake_id: intake.id, mail_type: "validation_reminder" },
    });
    setBusyKey("sendReminder", false);
    if (error) toast.error(`Verzenden mislukt: ${error.message}`);
    else toast.success("Herinnering verstuurd");
  };

  const onGenerateContextPack = async () => {
    if (!supabase || !intake) return;
    setBusyKey("generateContextPack", true);
    const { error } = await supabase.functions.invoke("generate-context-pack", {
      body: { intake_id: intake.id },
    });
    setBusyKey("generateContextPack", false);
    if (error) {
      toast.error(`Context Pack mislukt: ${error.message}`);
      return;
    }
    toast.success("Context Pack gegenereerd");
    await load();
  };

  const onStartAutoResearch = async () => {
    if (!supabase || !intake) return;
    if (
      !confirm(
        "Start automatische research?\n\nGebruikt SerpAPI + SearchAPI + eventueel Apify (~€0.05–0.20, 2–5 min).",
      )
    )
      return;
    setBusyKey("startResearch", true);
    const { error } = await supabase.functions.invoke("run-research", {
      body: { intake_id: intake.id },
    });
    if (!error) {
      await supabase
        .schema("nestor")
        .from("intakes")
        .update({ status: "in_research" })
        .eq("id", intake.id);
    }
    setBusyKey("startResearch", false);
    if (error) {
      toast.error(`Research mislukt: ${error.message}`);
      return;
    }
    toast.success("Research gestart — refresh over enkele minuten");
    await load();
  };

  const onStartManualResearch = async () => {
    if (!supabase || !intake) return;
    await handleStatusChange("in_research");
  };

  const onDownloadContextPack = () => {
    const el = document.querySelector("[data-context-pack-block]");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    else toast("Scroll naar Context Pack hieronder.");
  };

  const onUploadFinalReport = () => {
    const el = document.querySelector("[data-final-report-block]");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    else toast("Scroll naar het klant-rapport blok hieronder.");
  };

  const onSendResultsMail = async () => {
    if (!supabase || !intake) return;
    setBusyKey("sendResults", true);
    const { error } = await supabase.functions.invoke("send-pulse-mail", {
      body: { intake_id: intake.id, mail_type: "results_ready" },
    });
    setBusyKey("sendResults", false);
    if (error) {
      toast.error(`Verzenden mislukt: ${error.message}`);
      return;
    }
    toast.success("Resultaten-link verstuurd");
    await load();
  };

  const onArchive = async () => {
    if (!intake) return;
    if (!confirm("Project archiveren?")) return;
    setBusyKey("archive", true);
    await handleStatusChange("archived");
    setBusyKey("archive", false);
  };

  // When the polled run flips to 'succeeded' for a run we haven't consumed yet,
  // fetch the full row once and enter review-mode.
  useEffect(() => {
    if (!fullRun || !activeRun) return;
    if (activeRun.id === consumedRunId) return;
    const parsed = (fullRun as { output_parsed?: ParsedSkillOutput }).output_parsed;
    if (!parsed) return;
    const costUsd = (fullRun as { cost_estimate_usd?: number | null }).cost_estimate_usd ?? null;
    const costEur = costUsd != null ? costUsd * 0.92 : null;
    setReviewData({ runId: activeRun.id, parsed, costEur });
    setReviewMode(true);
    setConsumedRunId(activeRun.id);
    loadSkillRuns();
  }, [fullRun, activeRun, consumedRunId, loadSkillRuns]);


  const exitReviewMode = async () => {
    setReviewMode(false);
    setReviewData(null);
    await load();
  };

  const handleSemanticSearch = async () => {
    if (!supabase || !intake || !searchQuery.trim()) return;
    setSearching(true);
    try {
      const { data, error } = await supabase.functions.invoke("semantic-search", {
        body: { intake_id: intake.id, query: searchQuery.trim(), limit: 10 },
      });
      if (error) throw error;
      setSearchResults(data?.results ?? []);
    } catch (e) {
      toast.error(`Zoeken mislukt: ${(e as Error).message}`);
    } finally {
      setSearching(false);
    }
  };


 const handleCancel = () => {
 if (hasChanges) {
 if (!confirm("Niet-opgeslagen wijzigingen worden verwijderd. Doorgaan?")) return;
 }
 setDraft(initial);
 setEditMode(false);
 };

 const handleSave = async () => {
 if (!supabase || !intake) return;
 if (!hasChanges) {
 toast("Geen wijzigingen");
 setEditMode(false);
 return;
 }
 setSaving(true);
 try {
 for (const key of changedKeys) {
 const val = draft[key];
 if (isEmptyVal(val)) {
 const { error: delErr } = await supabase
 .schema("nestor")
 .from("intake_answers")
 .delete()
 .eq("intake_id", intake.id)
 .eq("field_key", key);
 if (delErr) throw delErr;
 } else {
 const { error: upErr } = await supabase
 .schema("nestor")
 .from("intake_answers")
 .upsert(
 { intake_id: intake.id, field_key: key, value: val },
 { onConflict: "intake_id,field_key" },
 );
 if (upErr) throw upErr;
 }
 }
 toast.success("Wijzigingen opgeslagen");
 setEditMode(false);
 await load();
 } catch (e) {
 toast.error(`Opslaan mislukt: ${(e as Error).message}`);
 } finally {
 setSaving(false);
 }
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
 Deze intake bestaat niet of werd verwijderd.
 </p>
 <Link
 to="/admin/pulse/intakes"
 className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-ink hover:underline"
 >
 <ArrowLeft className="h-4 w-4" />
 Terug naar lijst
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
 ? `${client?.name ?? "Onbekende klant"} — ${projectNameStr}`
 : intake.title || intake.product?.name || "";
 const intakeUrl = intake.client_intake_token
 ? `${typeof window !== "undefined" ? window.location.origin : ""}/intake/${intake.client_intake_token}`
 : null;
 const statusHint = intake.status ? STATUS_HINT[intake.status] : undefined;
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
 className="inline-flex items-center gap-1 text-xs font-medium text-ink/60 hover:text-ink"
 >
 <ArrowLeft className="h-3.5 w-3.5" />
 Intakes
 </Link>
 <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
 <div>
 <h1 className="text-xl font-semibold tracking-tight text-ink">{headerTitle}</h1>
              <p className="mt-0.5 text-xs text-ink/60">
                Laatst bewerkt {formatDistanceToNow(new Date(intake.updated_at), { addSuffix: true, locale: nl })}
                {intake.delivered_at && (
                  <>
                    <span className="mx-2 text-ink/30">·</span>
                    Geleverd op {format(new Date(intake.delivered_at), "d MMM yyyy", { locale: nl })}
                  </>
                )}
              </p>
 </div>
 <div className="flex flex-wrap items-center gap-2">
 <div className="flex flex-col">
 <select
 value={intake.status ?? ""}
 disabled={updatingStatus}
 onChange={(e) => handleStatusChange(e.target.value)}
 className="border border-ink/10 bg-paper px-2.5 py-1.5 text-xs font-medium text-ink/80 focus:border-ink focus:outline-none"
 >
 {STATUS_OPTIONS.map((o) => (
 <option key={o.value} value={o.value}>
 {o.label}
 </option>
 ))}
 </select>
 </div>
  <StatusPill status={intake.status} />

 {!editMode ? (
 <button
 type="button"
 onClick={() => setEditMode(true)}
 className="inline-flex items-center gap-1.5 bg-ink px-3 py-1.5 text-xs font-medium text-paper hover:bg-ink/80"
 >
 <Pencil className="h-3.5 w-3.5" />
 Bewerken
 </button>
 ) : (
 <>
 <button
 type="button"
 onClick={handleCancel}
 className="inline-flex items-center gap-1.5 border border-ink/10 bg-paper px-3 py-1.5 text-xs font-medium text-ink/70 hover:bg-ink/5"
 >
 <X className="h-3.5 w-3.5" />
 Annuleren
 </button>
 <button
 type="button"
 onClick={handleSave}
 disabled={saving}
 className="inline-flex items-center gap-1.5 bg-ink px-3 py-1.5 text-xs font-medium text-paper hover:bg-ink/80 disabled:opacity-50"
 >
 {saving ? (
 <Loader2 className="h-3.5 w-3.5 animate-spin" />
 ) : (
 <Save className="h-3.5 w-3.5" />
 )}
 Opslaan
 </button>
 </>
 )}
 </div>
 </div>
 {statusHint && (
 <p className="mt-2 text-xs text-ink/60">{statusHint}</p>
 )}
 </div>

     <NextStepBanner
       phase={currentPhase}
       validationLinkSentAt={intake.validation_link_sent_at}
       resultsLinkSentAt={intake.results_link_sent_at}
       deliveredAt={intake.delivered_at}
       activeRun={bannerActiveRun}
       busy={busy}
       onRunSkill={runSkill}
       onCopyIntakeLink={onCopyIntakeLink}
       onOpenAIReview={onOpenAIReview}
       onSendValidationMail={onSendValidationMail}
       onCopyValidationLink={onCopyValidationLink}
       onSendValidationReminder={onSendValidationReminder}
       onGenerateContextPack={onGenerateContextPack}
       onStartAutoResearch={onStartAutoResearch}
       onStartManualResearch={onStartManualResearch}
       onDownloadContextPack={onDownloadContextPack}
       onUploadFinalReport={onUploadFinalReport}
       onSendResultsMail={onSendResultsMail}
       onCopyResultsLink={onCopyResultsLink}
       onArchive={onArchive}
     />


     {showSemanticSearch && (
       <section className="border border-ink/20 bg-paperLight p-4 mb-6">
         <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60 mb-2">
           Zoek in research data (semantic)
         </div>
         <div className="flex gap-2">
           <input
             type="text"
             value={searchQuery}
             onChange={(e) => setSearchQuery(e.target.value)}
             onKeyDown={(e) => e.key === "Enter" && handleSemanticSearch()}
             placeholder="bv. 'klanten klagen over toegangscode' of 'pricing transparantie concurrenten'"
             className="flex-1 border border-ink/30 px-3 py-2 font-mono text-sm bg-paper"
           />
           <button
             type="button"
             onClick={handleSemanticSearch}
             disabled={searching}
             className="font-mono text-xs uppercase tracking-wider bg-ink text-paperLight px-4 py-2 disabled:opacity-50"
           >
             {searching ? "…" : "🔍 Zoek"}
           </button>
         </div>
         {searchResults.length > 0 && (
           <div className="mt-4 space-y-2">
             <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
               {searchResults.length} resultaten — meest relevante eerst
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


    <div className="mb-6">
      <IntakeWorkflowStepper
      status={intake.status}
      clientValidatedAt={intake.client_validated_at}
      submittedAt={intake.updated_at}
      />
    </div>


  {/* HandoffBlock verwijderd: alle handoff-acties zitten nu in NextStepBanner per fase. */}

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

 {editMode && (
 <div className="mb-6 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-4">
 <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">BEWERKEN</div>
 <div className="text-ink font-sans">
 Wijzigingen zijn niet opgeslagen tot je op Opslaan klikt.
 </div>
 </div>
 )}

 {!editMode && !reviewMode && intake.status && STATUS_BANNER[intake.status] && (
 <div className="mb-6 border border-ink/10 bg-paper2 px-4 py-3 text-sm text-ink/70">
 {STATUS_BANNER[intake.status]}
 </div>
 )}

 <div className="grid grid-cols-1 gap-8 lg:grid-cols-[320px_1fr]">
 <aside className="hidden lg:block">
 <nav className="sticky top-28 space-y-1">
 <p className="mb-2 font-mono text-xs uppercase tracking-wider text-ink/60">
 Secties
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
 <section className="border border-ink/10 bg-paper p-6">
 <h2 className="text-sm font-semibold uppercase tracking-wide text-ink/60">
 Intake-info
 </h2>
 <dl className="mt-4">
 <Meta label="Klant">
 {client ? (
 <Link to="/admin/pulse/clients" className="text-ink hover:underline">
 {client.name}
 </Link>
 ) : (
 "—"
 )}
 </Meta>
 <Meta label="Product">
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
 <Meta label="Status">
 <StatusPill status={intake.status} />
 </Meta>
                  <Meta label="Aangemaakt">{fmt(intake.created_at)}</Meta>
                  <Meta label="Laatst bewerkt">{fmt(intake.updated_at)}</Meta>
                  {(intake.status === "delivered" || intake.status === "archived") && (
                    <Meta label="Geleverd op">
                      <DeliveredAtEditor
                        intakeId={intake.id}
                        value={intake.delivered_at}
                        onSaved={(v) => setIntake({ ...intake, delivered_at: v })}
                      />
                    </Meta>
                  )}
 <Meta label="Initiële intake-link">
 <LinkRow
 url={intakeUrl}
 subtitle="Werkt zolang status = Concept"
 placeholder="—"
 />
 </Meta>
 <Meta label="Validatie-link">
 <LinkRow
 url={
 intake.client_validation_token
 ? `${typeof window !== "undefined" ? window.location.origin : ""}/intake/${intake.client_validation_token}`
 : null
 }
 subtitle="Werkt nadat je 'Verstuur voor klant-validatie' klikte"
 placeholder="Komt na 'Verstuur voor klant-validatie'"
 />
 </Meta>
 <Meta label="Validatie">
 {intake.client_validated_at ? (
 <span className="text-emerald-700">
 Klant heeft gevalideerd op {fmt(intake.client_validated_at)}
 </span>
 ) : (
 <span className="text-ink/60">Nog niet gevalideerd</span>
 )}
 </Meta>
 {intake.client_results_token && (
 <Meta
 label={
 <span className="inline-flex items-center gap-1">
 Klant-resultaten-link
 <span
 className="cursor-help text-ink/40"
 title="Wat de klant ziet: één samengevat rapport (download) + vragen-overzicht + AI-zoek. Geen toegang tot raw research files of filenames."
 >
 ⓘ
 </span>
 </span>
 }
 >
 <ResultsLinkRow
 intakeId={intake.id}
 token={intake.client_results_token}
 hasFinalReport={!!intake.final_report_artifact_id}
 onTokenChange={(t) => setIntake({ ...intake, client_results_token: t })}
 />
 </Meta>
 )}
 </dl>
 </section>

 {skillRuns && skillRuns.length > 0 && (
 <section className="border border-ink/10 bg-paper">
 <button
 type="button"
 onClick={toggleHistory}
 className="flex w-full items-center justify-between px-6 py-3 text-left text-sm font-medium text-ink/70 hover:bg-ink/5"
 >
 <span className="flex items-center gap-2">
 {historyOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
 Eerdere skill-runs
 {skillRuns && skillRuns.length > 0 && (
 <span className="text-xs text-ink/60">({skillRuns.length})</span>
 )}
 </span>
 </button>
 {historyOpen && (
 <div className="border-t border-ink/5 px-6 py-3">
 {loadingRuns ? (
 <p className="text-sm text-ink/60">Laden…</p>
 ) : skillRuns && skillRuns.length > 0 ? (
 <ul className="divide-y divide-ink/5">
 {skillRuns.map((r) => {
 const icon = r.status === "succeeded" ? "✅" : r.status === "failed" ? "❌" : "⏳";
 return (
 <li key={r.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
 <span>{icon}</span>
 <span className="font-medium text-ink/80">{r.skill_name}</span>
 <span className="text-ink/60">— {fmt(r.triggered_at)}</span>
 {r.cost_estimate_usd != null && (
 <span className="text-ink/60">— €{(r.cost_estimate_usd * 0.92).toFixed(2)}</span>
 )}
 {r.status === "failed" && r.error_message && (
  <span className="text-red-600">— fout: {r.error_message}</span>
 )}
 {r.status === "running" && (
 <span className="text-ink/60">— bezig…</span>
 )}
 </li>
 );
 })}
 </ul>
 ) : null}
 </div>
 )}
 </section>
  )}

  {showContextPack && (
    <div data-context-pack-block>
      <ContextPackBlock
        intakeId={intake.id}
        intakeStatus={intake.status}
        intakeTitle={intake.title ?? ""}
        clientName={client?.name ?? "—"}
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
          onChange={async (artifactId) => {
            setIntake({
              ...intake,
              final_report_artifact_id: artifactId,
              status:
                artifactId && intake.client_results_token && intake.status === "in_research"
                  ? "delivered"
                  : intake.status,
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
 className="scroll-mt-32"
 >
 <h2 className="border-b border-ink/30 pb-2 mb-2 font-serif text-2xl font-normal lowercase text-ink">
 {section.title}
 </h2>
 {section.description && (
 <p className="mb-4 font-sans text-sm italic text-ink/60">{section.description}</p>
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
 Gewijzigd
 </span>
 )}
 </div>
 <FieldRenderer
 field={field}
 value={draft[field.key]}
 onChange={(v) => setDraft((d) => ({ ...d, [field.key]: v }))}
 intakeId={intake.id}
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
 </ReviewProvider>
 );
}

function Meta({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
 return (
 <div className="grid grid-cols-1 gap-x-8 gap-y-1 border-b border-ink/10 py-4 last:border-b-0 sm:grid-cols-[260px_1fr]">
 <dt className="font-sans text-sm font-normal text-ink/70">{label}</dt>
 <dd className="font-sans text-ink">{children}</dd>
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
  const [date, setDate] = useState(value ? value.slice(0, 10) : "");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setDate(value ? value.slice(0, 10) : "");
  }, [value]);
  const dirty = (value ? value.slice(0, 10) : "") !== date;
  const save = async () => {
    if (!supabase || !date) return;
    setSaving(true);
    const iso = new Date(date + "T12:00:00Z").toISOString();
    const { error } = await supabase
      .schema("nestor")
      .from("intakes")
      .update({ delivered_at: iso })
      .eq("id", intakeId);
    setSaving(false);
    if (error) {
      toast.error(`Opslaan faalde: ${error.message}`);
      return;
    }
    toast.success("Leverdatum bijgewerkt");
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
            Opslaan
          </button>
        )}
      </div>
      <p className="text-xs text-ink/50">De datum die de klant ziet op de resultaten-pagina.</p>
    </div>
  );
}

function ResultsLinkRow({
 intakeId,
 token,
 hasFinalReport,
 onTokenChange,
}: {
 intakeId: string;
 token: string;
 hasFinalReport: boolean;
 onTokenChange: (t: string) => void;
}) {
 const [busy, setBusy] = useState(false);
 const url =
 typeof window !== "undefined" ? `${window.location.origin}/results/${token}` : "";

 const copy = async () => {
 try {
 await navigator.clipboard.writeText(url);
 toast.success("Link gekopieerd");
 } catch {
 toast.error("Kopiëren mislukt");
 }
 };

 const regenerate = async () => {
 if (!supabase) return;
 if (!confirm("De oude link wordt ongeldig — doorgaan?")) return;
 setBusy(true);
 try {
 const newToken = crypto.randomUUID().replace(/-/g, "").slice(0, 24);
 const updates: Record<string, unknown> = { client_results_token: newToken };
 if (hasFinalReport) updates.status = "delivered";
 const { error } = await supabase
 .schema("nestor" as never)
 .from("intakes")
 .update(updates)
 .eq("id", intakeId);
 if (error) throw error;
 onTokenChange(newToken);
 toast.success("Nieuwe link gegenereerd");
 } catch (e) {
 toast.error(`Mislukt: ${(e as Error).message}`);
 } finally {
 setBusy(false);
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
 className="inline-flex items-center gap-1 border border-ink/10 px-2.5 py-1 text-xs font-medium text-ink/70 hover:bg-ink/5"
 >
 <Copy className="h-3.5 w-3.5" />
 Kopieer
 </button>
 <button
 type="button"
 onClick={regenerate}
 disabled={busy}
 className="inline-flex items-center gap-1 border border-ink/10 px-2.5 py-1 text-xs font-medium text-ink/70 hover:bg-ink/5 disabled:opacity-50"
 >
 ↻ Genereer nieuwe link
 </button>
 </div>
 <p className="text-xs text-ink/40">Werkt zodra status = Geleverd</p>
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
 const copy = async () => {
 if (!url) return;
 try {
 await navigator.clipboard.writeText(url);
 toast.success("Link gekopieerd");
 } catch {
 toast.error("Kopiëren mislukt");
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
 className="inline-flex items-center gap-1 border border-ink/10 px-2.5 py-1 text-xs font-medium text-ink/70 hover:border-ink/10 hover:bg-ink/5"
 >
 <Copy className="h-3.5 w-3.5" />
 Kopieer
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
