import type { ReactNode } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { signOut } from "firebase/auth";
import agenicLogo from "@/assets/agenic-logo.png";
import { auth } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";
import { ActiveSpaceProvider } from "@/lib/active-space";
import { ADMIN_NAV } from "@/components/admin/adminNav";
import { SpaceSwitcher } from "@/components/admin/SpaceSwitcher";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

type Item = { to: string; labelKey: string; exact: boolean };

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
  const { t } = useTranslation("admin");

  const isActive = (to: string, exact: boolean) =>
    exact ? pathname === to : pathname === to || pathname.startsWith(to + "/");

  async function handleLogout() {
    await signOut(auth);
    navigate({ to: "/auth/login" });
  }

  return (
    <ActiveSpaceProvider>
    <div className="flex min-h-screen overflow-x-clip bg-paper">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col overflow-y-auto border-r border-ink px-5 py-6 md:flex">
        <Link
          to="/admin"
          className="font-mono text-[11px] uppercase tracking-wider text-ink/60 hover:text-ink"
        >
          {t("shell.backToOverview")}
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

        {/* Global space switcher (D-04 / TENANT-04) — superadmin-only. Mounted on the
            SAME isSuperadmin gate as the shell.manage nav below so a `user` NEVER renders it
            (absent from the DOM, not merely hidden). The selection is UX-only view-filter
            state; the backend remains the sole tenant authority. */}
        {isSuperadmin && (
          <div className="mt-6">
            <SpaceSwitcher />
          </div>
        )}

        {/* Persisting NL/FR/EN switcher (D-08 admin location) — mounted in the same
            chrome as the space switcher. Available to EVERY admin user (not superadmin-
            gated): a `user` also needs to pick their display language. `persist` writes
            the choice to their membership via PATCH /me/locale (best-effort). */}
        <div className="mt-4">
          <LanguageSwitcher persist />
        </div>

        <nav className="mt-6 flex flex-col gap-1">
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
                {t(item.labelKey)}
              </Link>
            );
          })}
        </nav>

        {/* Superadmin-only management section — gebruikers / spaces / templates (Phase 5).
            Hidden for non-superadmins (UX gating only; backend remains authoritative).
            Skipped when the primary nav already IS the manage nav (Beheer pages pass the
            same imported ADMIN_NAV constant — reference equality is intentional), so the
            gebruikers/spaces/templates links never render twice. */}
        {isSuperadmin && items !== ADMIN_NAV && (
          <nav className="mt-8 flex flex-col gap-1 border-t border-ink/15 pt-4">
            <p className="px-3 pb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-ink/40">
              {t("shell.manage")}
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
                  {t(item.labelKey)}
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
            {t("shell.logout")}
          </button>
        </div>
      </aside>
      <main className="flex-1 px-6 py-8 md:px-10 md:py-10">{children}</main>
    </div>
    </ActiveSpaceProvider>
  );
}
