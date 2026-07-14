import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import agenicLogo from "@/assets/agenic-logo.png";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/lib/auth-context";
import { VerticalIcon } from "@/components/admin/VerticalIcon";


export const Route = createFileRoute("/admin/")({
  component: AdminHomePage,
});

type Product = {
  slug: string;
  name: string;
  tag: string;
  description: string;
  enabled: boolean;
  route: string;
};

const PRODUCTS: Product[] = [
  {
    slug: "pulse",
    name: "nestor pulse",
    tag: "Premium research",
    description:
      "De master research-engine. Custom diepgaand onderzoek voor strategische beslissingen.",
    enabled: true,
    route: "/admin/pulse/intakes",
  },
  {
    slug: "sales",
    name: "nestor sales",
    tag: "Sales prep preset",
    description:
      "Preset van Pulse, gericht op pre-sales briefings, lead-research en pitch-voorbereiding.",
    enabled: true,
    route: "/admin/sales",
  },
  {
    slug: "echo",
    name: "nestor echo",
    tag: "Consumer research preset",
    description:
      "Preset van Pulse, gericht op het ontrafelen van wat klanten echt willen, wat hen blokkeert en wat hun beslissingen drijft.",
    enabled: false,
    route: "/admin/echo/coming-soon",
  },
  {
    slug: "edge",
    name: "nestor edge",
    tag: "Competitive research preset",
    description:
      "Preset van Pulse, gericht op concurrentiebewegingen, sterktes/zwaktes en kansen om voorbij te steken.",
    enabled: false,
    route: "/admin/edge/coming-soon",
  },
  {
    slug: "flux",
    name: "nestor flux",
    tag: "Market shifts preset",
    description:
      "Preset van Pulse, gericht op trends die op je business afkomen en concrete implicaties.",
    enabled: false,
    route: "/admin/flux/coming-soon",
  },
];

function AdminHomePage() {
  const navigate = useNavigate();
  const { session } = useAuth();
  const { t } = useTranslation("common");

  async function handleLogout() {
    if (!supabase) return;
    await supabase.auth.signOut();
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
            kies een product
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
                <p className="mt-3 text-sm text-ink/70">{p.description}</p>
                {!p.enabled && (
                  <p className="mt-4 font-mono text-[10px] uppercase tracking-wider text-ink/50">
                    {t("comingSoon.badge")}
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
            Uitloggen
          </button>
        </footer>
      </div>
    </div>
  );
}
