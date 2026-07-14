import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Loader2, Sparkles } from "lucide-react";
import * as skills from "@/lib/api/skills";
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
        {/* No sources-read surface exists yet (only the transcribe dispatch), so the
            transcribe CTA is gated with an explanatory disabled state rather than a
            hand-rolled backend read. Once an intake exposes its audio sources, wire each
            source to the transcribe trigger per source id — the trigger already exists;
            only the source_id read is missing. Kept as the explicit wiring point below. */}
        <button
          type="button"
          className={btnCls}
          disabled
          title={t("aiSkills.transcribeDisabledTitle")}
          onClick={() =>
            run(
              "transcribe",
              t("aiSkills.transcribeStarted"),
              // Disabled until a sources-read surface supplies source.id; the dispatch
              // itself is ready. Passing an empty id here is unreachable (button disabled).
              () => skills.transcribeSource(intakeId, ""),
            )
          }
        >
          {t("aiSkills.transcribeBtn")}
        </button>
      </div>
      <p className="mt-3 font-mono text-[11px] uppercase tracking-wide text-ink/40">
        {t("aiSkills.progressNote")}
      </p>
    </div>
  );
}
