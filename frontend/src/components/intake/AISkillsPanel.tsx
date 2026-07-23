import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChevronDown, Loader2, Sparkles } from "lucide-react";
import * as skills from "@/lib/api/skills";
import { getIntakeSources, type IntakeSourceView } from "@/lib/api/sources";
import type { ApiResult } from "@/lib/api/client";
import type { SkillDispatch } from "@/lib/api/skills";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

type Props = {
  intakeId: string;
  intakeStatus: string | null;
};

// These enrichment skills are meaningful once the client has submitted and up to the
// milestone ceiling (`decomposed`). They stay hidden while the intake is still a draft.
const VISIBLE_STATUSES = new Set(["submitted", "reviewed", "validated_by_client", "decomposed"]);

type SkillKey = "structure" | "extract" | "embeddings" | "transcribe";

export function AISkillsPanel({ intakeId, intakeStatus }: Props) {
  const { t } = useTranslation("intake");
  const [busy, setBusy] = useState<SkillKey | null>(null);
  const [audioSources, setAudioSources] = useState<IntakeSourceView[]>([]);
  const [transcribingId, setTranscribingId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const res = await getIntakeSources(intakeId);
      if (cancelled) return;
      if (res.success) {
        setAudioSources(res.data.sources.filter((s) => s.kind === "audio"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [intakeId]);

  if (!VISIBLE_STATUSES.has(intakeStatus ?? "")) return null;

  const run = async (
    key: SkillKey,
    startedMsg: string,
    trigger: () => Promise<ApiResult<SkillDispatch>>,
  ) => {
    setBusy(key);
    setOpen(false);
    try {
      const res = await trigger();
      if (!res.success) {
        toast.error(res.error || t("aiSkills.actionFailed"));
        return;
      }
      toast.success(startedMsg);
    } finally {
      setBusy(null);
    }
  };

  const isBusy = busy !== null;

  return (
    <div className="border-t border-ink/10 px-6 py-4">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-ink/50 hover:text-ink transition-colors"
            aria-label={t("aiSkills.title")}
          >
            {isBusy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {t("aiSkills.title")}
            <ChevronDown
              className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
            />
          </button>
        </PopoverTrigger>

        <PopoverContent
          className="w-72 p-0 border border-ink/20 bg-paper shadow-md"
          align="start"
          sideOffset={8}
        >
          {/* header */}
          <div className="border-b border-ink/10 px-4 py-2.5">
            <p className="font-sans text-xs leading-relaxed text-ink/60">
              {t("aiSkills.intro")}
            </p>
          </div>

          {/* action list */}
          <div className="py-1">
            <SkillItem
              label={t("aiSkills.structureBtn")}
              description={t("aiSkills.structureDesc", "Zet antwoorden om in gestructureerde data.")}
              spinning={busy === "structure"}
              disabled={isBusy}
              onClick={() =>
                run("structure", t("aiSkills.structureStarted"), () =>
                  skills.structureAnswers(intakeId),
                )
              }
            />
            <SkillItem
              label={t("aiSkills.extractBtn")}
              description={t("aiSkills.extractDesc", "Extraheer sleutelinzichten uit de antwoorden.")}
              spinning={busy === "extract"}
              disabled={isBusy}
              onClick={() =>
                run("extract", t("aiSkills.extractStarted"), () =>
                  skills.extractInsights(intakeId),
                )
              }
            />
            <SkillItem
              label={t("aiSkills.embeddingsBtn")}
              description={t("aiSkills.embeddingsDesc", "Genereer embeddings voor semantisch zoeken.")}
              spinning={busy === "embeddings"}
              disabled={isBusy}
              onClick={() =>
                run("embeddings", t("aiSkills.embeddingsStarted"), () =>
                  skills.generateEmbeddings(intakeId),
                )
              }
            />

            {/* Transcribe — one item per audio source, or a disabled placeholder */}
            {audioSources.length === 0 ? (
              <SkillItem
                label={t("aiSkills.transcribeBtn")}
                description={t("aiSkills.transcribeDisabledTitle")}
                spinning={false}
                disabled
                onClick={() => {}}
              />
            ) : (
              audioSources.map((source) => (
                <SkillItem
                  key={source.id}
                  label={t("aiSkills.transcribeSourceBtn", {
                    name: source.file_name ?? t("aiSkills.transcribeSourceFallback"),
                  })}
                  description={t("aiSkills.transcribeDesc", "Transcribeer audio naar tekst.")}
                  spinning={busy === "transcribe" && transcribingId === source.id}
                  disabled={isBusy}
                  onClick={() => {
                    setTranscribingId(source.id);
                    void run("transcribe", t("aiSkills.transcribeStarted"), () =>
                      skills.transcribeSource(intakeId, source.id),
                    ).finally(() => setTranscribingId(null));
                  }}
                />
              ))
            )}
          </div>

          {/* footer note */}
          <div className="border-t border-ink/10 px-4 py-2">
            <p className="font-mono text-[10px] uppercase tracking-wide text-ink/40">
              {t("aiSkills.progressNote")}
            </p>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SkillItem — a single row inside the popover menu
// ---------------------------------------------------------------------------
function SkillItem({
  label,
  description,
  spinning,
  disabled,
  onClick,
}: {
  label: string;
  description: string;
  spinning: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="w-full flex items-start gap-3 px-4 py-2.5 text-left hover:bg-ink/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    >
      <div className="mt-0.5 shrink-0 w-3.5 h-3.5 flex items-center justify-center">
        {spinning ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-ink" />
        ) : (
          <span className="block h-1 w-1 rounded-full bg-ink/30" />
        )}
      </div>
      <div className="min-w-0">
        <div className="font-mono text-[11px] uppercase tracking-wider text-ink leading-tight">
          {label}
        </div>
        <div className="mt-0.5 font-sans text-[11px] leading-snug text-ink/50">
          {description}
        </div>
      </div>
    </button>
  );
}
