import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { supabase } from "@/lib/supabase";

export const Route = createFileRoute("/auth/callback")({
  component: AuthCallback,
});

function AuthCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    if (!supabase) return;
    let cancelled = false;

    async function finalize() {
      await new Promise((r) => setTimeout(r, 100));
      const { data, error } = await supabase!.auth.getSession();
      if (cancelled) return;
      if (error || !data.session) {
        navigate({ to: "/auth/login", search: { error: "callback" } as never });
        return;
      }

      try {
        const { data: orgIds, error: rpcErr } = await (supabase as any)
          .schema("nestor")
          .rpc("user_organization_ids");
        if (rpcErr) throw rpcErr;
        const ids = (orgIds ?? []) as string[];
        if (ids.length === 0) {
          await supabase!.auth.signOut();
          navigate({ to: "/auth/login", search: { error: "no_access" } as never });
          return;
        }

        const { data: orgDetails } = await (supabase as any)
          .schema("nestor")
          .from("organizations")
          .select("id, type")
          .in("id", ids)
          .eq("type", "operator");

        if ((orgDetails ?? []).length > 0) {
          navigate({ to: "/admin" });
        } else {
          await supabase!.auth.signOut();
          navigate({ to: "/auth/login", search: { error: "no_access" } as never });
        }
      } catch {
        navigate({ to: "/auth/login", search: { error: "callback" } as never });
      }
    }

    finalize();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper2">
      <p className="font-mono text-xs uppercase tracking-wider text-ink/60">
        Inloggen...
      </p>
    </div>
  );
}
