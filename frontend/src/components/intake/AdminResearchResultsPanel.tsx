import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { supabase } from "@/lib/supabase";
import {
  ResearchResultsPanel,
  type RRPArtifact,
  type RRPClient,
  type RRPIntake,
  type RRPQuestion,
} from "./ResearchResultsPanel";

export function AdminResearchResultsPanel({
  intake,
  client,
  onTokenChange,
}: {
  intake: RRPIntake;
  client: RRPClient;
  onTokenChange: (token: string) => void;
}) {
  const [questions, setQuestions] = useState<RRPQuestion[]>([]);
  const [artifacts, setArtifacts] = useState<RRPArtifact[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    const [qRes, aRes] = await Promise.all([
      supabase
        .schema("nestor" as never)
        .from("research_questions")
        .select("id, question_text, question_type, priority, rationale, status")
        .eq("intake_id", intake.id)
        .order("priority", { ascending: true, nullsFirst: false }),
      supabase
        .schema("nestor" as never)
        .from("research_artifacts")
        .select(
          "id, research_question_id, source, artifact_type, filename, storage_path, byte_size, mime_type, created_at",
        )
        .eq("intake_id", intake.id)
        .order("created_at", { ascending: false }),
    ]);
    setQuestions((qRes.data as RRPQuestion[]) ?? []);
    setArtifacts((aRes.data as RRPArtifact[]) ?? []);
    setLoading(false);
  }, [intake.id]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <section className="border border-ink bg-paperLight p-6">
        <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-ink/60">
          <Loader2 className="h-4 w-4 animate-spin" /> Resultaten laden…
        </div>
      </section>
    );
  }

  return (
    <ResearchResultsPanel
      mode="admin"
      intake={intake}
      client={client}
      questions={questions}
      artifacts={artifacts}
      onTokenChange={onTokenChange}
    />
  );
}
