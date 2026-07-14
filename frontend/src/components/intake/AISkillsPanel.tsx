import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Loader2, Sparkles } from "lucide-react";
import * as skills from "@/lib/api/skills";
import { getIntakeSources, type IntakeSourceView } from "@/lib/api/sources";
import type { ApiResult } from "@/lib/api/client";
import type { SkillDispatch } from "@/lib/api/skills";

type Props = {
  intakeId: string;
  intakeStatus: string | null;
};

// These enrichment skills are meaningful once the client has submitted and up to the
// milestone ceiling (`decomposed`). They stay hidden while the intake is still a draft.
const VISIBLE_STATUSES = new Set(["submitted", "reviewed", "validated_by_client", "decomposed"]);

const panelCls = "mb-6 border border-ink/30 border-l-4 bg-paperLight px-6 py-5";
const btnCls =
  "inline-flex items-center gap-2 border border-ink bg-transparent px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-60 disabled:hover:border";

type SkillKey = "structure" | "extract" | "embeddings" | "transcribe";

export function AISkillsPanel({ intakeId, intakeStatus }: Props) {
  const { t } = useTranslation("intake");
  const [busy, setBusy] = useState<SkillKey | null>(null);
  // The intake's audio sources feed the transcribe CTA real source ids (12-03). The read
  // is space-scoped server-side (existence-hidden) — the seam renders whatever it returns.
  const [audioSources, setAudioSources] = useState<IntakeSourceView[]>([]);
  // Which audio source's transcribe is currently in-flight (drives the per-button spinner).
  const [transcribingId, setTranscribingId] = useState<string | null>(null);

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
    try {
      // ApiResult return-no-throw: never throw on an API error, surface via sonner.
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

  return (
    <div className={panelCls} style={{ borderLeftColor: "#DFF940" }}>
      <div className="mb-2 flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-ink/60">
        <Sparkles className="h-3.5 w-3.5" />
        {t("aiSkills.title")}
      </div>
      <div className="mb-4 font-sans text-[15px] leading-relaxed text-ink">
        {t("aiSkills.intro")}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={btnCls}
          disabled={busy !== null}
          onClick={() =>
            run(
              "structure",
              t("aiSkills.structureStarted"),
              () => skills.structureAnswers(intakeId),
            )
          }
        >
          {busy === "structure" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("aiSkills.structureBtn")}
        </button>
        <button
          type="button"
          className={btnCls}
          disabled={busy !== null}
          onClick={() =>
            run(
              "extract",
              t("aiSkills.extractStarted"),
              () => skills.extractInsights(intakeId),
            )
          }
        >
          {busy === "extract" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("aiSkills.extractBtn")}
        </button>
        <button
          type="button"
          className={btnCls}
          disabled={busy !== null}
          onClick={() =>
            run(
              "embeddings",
              t("aiSkills.embeddingsStarted"),
              () => skills.generateEmbeddings(intakeId),
            )
          }
        >
          {busy === "embeddings" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("aiSkills.embeddingsBtn")}
        </button>
        {/* Transcribe: one enabled button per audio source (each wired to its real source
            id via the 12-03 sources read). When the intake has no audio source yet, a single
            disabled CTA with an explanatory title stands in. The transcribe dispatch itself
            already exists (`skills.transcribeSource`); this only feeds it real source ids. */}
        {audioSources.length === 0 ? (
          <button
            type="button"
            className={btnCls}
            disabled
            title={t("aiSkills.transcribeDisabledTitle")}
          >
            {t("aiSkills.transcribeBtn")}
          </button>
        ) : (
          audioSources.map((source) => (
            <button
              key={source.id}
              type="button"
              className={btnCls}
              disabled={busy !== null}
              onClick={() => {
                setTranscribingId(source.id);
                void run(
                  "transcribe",
                  t("aiSkills.transcribeStarted"),
                  () => skills.transcribeSource(intakeId, source.id),
                ).finally(() => setTranscribingId(null));
              }}
            >
              {busy === "transcribe" && transcribingId === source.id && (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              )}
              {t("aiSkills.transcribeSourceBtn", {
                name: source.file_name ?? t("aiSkills.transcribeSourceFallback"),
              })}
            </button>
          ))
        )}
      </div>
      <p className="mt-3 font-mono text-[11px] uppercase tracking-wide text-ink/40">
        {t("aiSkills.progressNote")}
      </p>
    </div>
  );
}
