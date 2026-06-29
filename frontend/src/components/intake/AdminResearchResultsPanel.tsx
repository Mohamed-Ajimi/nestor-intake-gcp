import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
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
    // Research questions/artifacts are served by the research backend (Phase 7+),
    // out of scope this milestone. Render the (inert) panel with no data; the
    // admin detail screen only mounts this in the post-decomposed phase.
    void intake.id;
    setQuestions([]);
    setArtifacts([]);
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
