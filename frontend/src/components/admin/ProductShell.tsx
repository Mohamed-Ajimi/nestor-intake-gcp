import type { ReactNode } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import agenicLogo from "@/assets/agenic-logo.png";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/lib/auth-context";
import { ADMIN_NAV } from "@/components/admin/adminNav";

type Item = { to: string; label: string; exact: boolean };

export function ProductShell({
  product,
  items,
  children,
}: {
  product: string;
  items: Item[];
  children: ReactNode;
}) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const navigate = useNavigate();
  const { session, isSuperadmin } = useAuth();

  const isActive = (to: string, exact: boolean) =>
    exact ? pathname === to : pathname === to || pathname.startsWith(to + "/");

  async function handleLogout() {
    if (!supabase) return;
    await supabase.auth.signOut();
    navigate({ to: "/auth/login" });
  }

  return (
    <div className="flex min-h-screen bg-paper">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-ink px-5 py-6 md:flex">
        <Link
          to="/admin"
          className="font-mono text-[11px] uppercase tracking-wider text-ink/60 hover:text-ink"
        >
          ← Terug naar overzicht
        </Link>

        <Link to="/admin" className="mt-6 block">
          <img src={agenicLogo} alt="Agenic" className="h-6 w-auto" />
          <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.2em] text-ink/50">
            Agenic ›
          </p>
          <p className="font-serif text-xl lowercase text-ink">
            nestor {product}
          </p>
        </Link>

        <nav className="mt-8 flex flex-col gap-1">
          {items.map((item) => {
            const active = isActive(item.to, item.exact);
            return (
              <Link
                key={item.to}
                to={item.to}
                className={
                  "flex items-center gap-3 px-3 py-2 font-mono text-xs uppercase tracking-wider transition-colors " +
                  (active
                    ? "bg-paper2 text-ink"
                    : "text-ink/60 hover:bg-ink/5 hover:text-ink")
                }
              >
                <span className={active ? "mark-green" : "mark-outline"} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Superadmin-only management section — gebruikers / spaces / templates (Phase 5).
            Hidden for non-superadmins (UX gating only; backend remains authoritative). */}
        {isSuperadmin && (
          <nav className="mt-8 flex flex-col gap-1 border-t border-ink/15 pt-4">
            <p className="px-3 pb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-ink/40">
              Beheer
            </p>
            {ADMIN_NAV.map((item) => {
              const active = isActive(item.to, item.exact);
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={
                    "flex items-center gap-3 px-3 py-2 font-mono text-xs uppercase tracking-wider transition-colors " +
                    (active ? "bg-paper2 text-ink" : "text-ink/60 hover:bg-ink/5 hover:text-ink")
                  }
                >
                  <span className={active ? "mark-green" : "mark-outline"} />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        )}

        <div className="mt-auto border-t border-ink pt-4">
          <p className="truncate text-sm font-medium text-ink">
            {session?.email}
          </p>
          <button
            onClick={handleLogout}
            className="mt-3 font-mono text-xs uppercase tracking-wider text-ink/60 underline-offset-2 hover:text-ink hover:underline"
          >
            Uitloggen
          </button>
        </div>
      </aside>
      <main className="flex-1 px-6 py-8 md:px-10 md:py-10">{children}</main>
    </div>
  );
}
