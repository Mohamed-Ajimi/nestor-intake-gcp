import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { signOut } from "firebase/auth";
import agenicLogo from "@/assets/agenic-logo.png";
import { auth } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";
import { VerticalIcon } from "@/components/admin/VerticalIcon";


export const Route = createFileRoute("/admin/")({
  component: AdminHomePage,
});

type Product = {
  slug: string;
  name: string;
  tag: string;
  enabled: boolean;
  route: string;
};

// Descriptions are localized — looked up at render time via t(`home.products.${slug}`)
// (Phase 11, WR-05). Tags are English brand labels shared across locales.
const PRODUCTS: Product[] = [
  {
    slug: "pulse",
    name: "nestor pulse",
    tag: "Premium research",
    enabled: true,
    route: "/admin/pulse/intakes",
  },
  {
    // D-09 (Phase 12): sales nav hidden — code retained but this card renders
    // dimmed/non-navigable (like echo/edge/flux). With VITE_SUPABASE_* never set
    // at build time, the retained admin.sales.* routes + salesMail/supabase code
    // are inert (supabase client is null). Do NOT delete the sales code.
    slug: "sales",
    name: "nestor sales",
    tag: "Sales prep preset",
    enabled: false,
    route: "/admin/sales",
  },
  {
    slug: "echo",
    name: "nestor echo",
    tag: "Consumer research preset",
    enabled: false,
    route: "/admin/echo/coming-soon",
  },
  {
    slug: "edge",
    name: "nestor edge",
    tag: "Competitive research preset",
    enabled: false,
    route: "/admin/edge/coming-soon",
  },
  {
    slug: "flux",
    name: "nestor flux",
    tag: "Market shifts preset",
    enabled: false,
    route: "/admin/flux/coming-soon",
  },
];

function AdminHomePage() {
  const navigate = useNavigate();
  const { session } = useAuth();
  const { t } = useTranslation("admin");

  // Firebase signOut (Phase 3 auth) — the legacy supabase.auth.signOut() was a no-op
  // here (guard returned with no client) and never ended the Firebase session (WR-06).
  async function handleLogout() {
    await signOut(auth);
    navigate({ to: "/auth/login" });
  }

  return (
    <div className="min-h-screen bg-paper px-6 py-10 md:px-16 md:py-16">
      <div className="mx-auto max-w-5xl">
        <header>
          <img src={agenicLogo} alt="Agenic" className="h-8 w-auto" />
          <p className="mt-4 font-mono text-xs uppercase tracking-[0.2em] text-ink/60">
            nestor — verified intelligence that compounds
          </p>
          <h1 className="mt-2 font-serif text-4xl lowercase tracking-tight text-ink">
            {t("home.title")}
          </h1>
        </header>

        <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2">
          {PRODUCTS.map((p) => {
            const baseClasses =
              "group block text-left border border-ink/30 p-8 bg-transparent transition-colors";
            const content = (
              <>
                <VerticalIcon
                  variant={p.slug as "pulse" | "sales" | "echo" | "edge" | "flux"}
                  className="mb-5 text-ink"
                />
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink/50">
                  {p.tag}
                </p>
                <h2 className="mt-2 font-serif text-2xl lowercase tracking-tight text-ink">
                  {p.name}
                </h2>
                <p className="mt-3 text-sm text-ink/70">{t(`home.products.${p.slug}`)}</p>
                {!p.enabled && (
                  <p className="mt-4 font-mono text-[10px] uppercase tracking-wider text-ink/50">
                    {t("comingSoon.badge", { ns: "common" })}
                  </p>
                )}
              </>
            );


            if (!p.enabled) {
              return (
                <div
                  key={p.slug}
                  className={baseClasses + " opacity-40 cursor-not-allowed"}
                >
                  {content}
                </div>
              );
            }

            return (
              <Link
                key={p.slug}
                to={p.route as any}
                className={baseClasses + " hover:bg-ink/5 cursor-pointer"}
              >
                {content}
              </Link>
            );
          })}
        </div>

        <footer className="mt-16 border-t border-ink/15 pt-6 flex items-center justify-between">
          <p className="font-mono text-xs uppercase tracking-wider text-ink/60">
            {session?.email}
          </p>
          <button
            onClick={handleLogout}
            className="font-mono text-xs uppercase tracking-wider text-ink/60 underline-offset-2 hover:text-ink hover:underline"
          >
            {t("shell.logout")}
          </button>
        </footer>
      </div>
    </div>
  );
}
