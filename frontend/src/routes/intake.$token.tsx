import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/lib/supabase";
import type { IntakePayload } from "@/lib/intake-types";
import { IntakeForm } from "@/components/intake/IntakeForm";

export const Route = createFileRoute("/intake/$token")({
  component: IntakePage,
});

function IntakePage() {
  const { token } = Route.useParams();

  const { data, isLoading, error } = useQuery({
    queryKey: ["intake", token],
    queryFn: async (): Promise<IntakePayload> => {
      if (!supabase) throw new Error("Supabase not configured");
      const { data, error } = await supabase.rpc("get_intake_by_token", {
        p_token: token,
      });
      if (error) throw error;
      return data as IntakePayload;
    },
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper">
        <p className="text-sm text-ink/40">Laden…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper px-6">
        <div className="max-w-md text-center">
          <h1 className="font-serif text-3xl font-normal lowercase text-ink">Link niet beschikbaar</h1>
          <p className="mt-3 text-ink/60">
            Deze link is ongeldig of verlopen. Neem contact op met{" "}
            <a className="underline" href="mailto:nestor@agenic.be">
              nestor@agenic.be
            </a>
            .
          </p>
        </div>
      </div>
    );
  }

  return <IntakeForm payload={data} token={token} />;
}
