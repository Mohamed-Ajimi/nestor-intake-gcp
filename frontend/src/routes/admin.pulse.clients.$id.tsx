import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { ProductBadge, type ProductKey } from "@/components/admin/ProductBadge";
import { StatusPill } from "@/components/intake/_status";
import { listIntakes } from "@/lib/api/intakes";
import { listSpaces, listUsers, listInvitations } from "@/lib/api/admin";

export const Route = createFileRoute("/admin/pulse/clients/$id")({
  component: ClientDetailPage,
});

// org = space in the GCP model — the route `$id` is a space id. The legacy
// `public.clients` row (country/website/contact) no longer exists; spaces are
// edited in the admin spaces area, so this page is read-only.
type SpaceDetail = {
  id: string;
  name: string;
  slug: string | null;
  status: string;
};

type IntakeRow = {
  id: string;
  client_name: string | null;
  status: string | null;
};

type UsersSummary = {
  member_count: number;
  invite_count: number;
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-1 border-b border-ink/10 py-3 last:border-b-0 sm:grid-cols-[120px_1fr]">
      <div className="font-sans text-sm font-normal text-ink/70">{label}</div>
      <div className="font-sans text-sm text-ink">{children}</div>
    </div>
  );
}

function ClientDetailPage() {
  const { t } = useTranslation("admin");
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState<SpaceDetail | null>(null);
  const [intakes, setIntakes] = useState<IntakeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [users, setUsers] = useState<UsersSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);

      const [spacesRes, intakesRes] = await Promise.all([listSpaces(), listIntakes()]);
      if (cancelled) return;

      if (!spacesRes.success) {
        setError(spacesRes.error);
        setLoading(false);
        return;
      }
      const space = spacesRes.data.find((s) => s.id === id);
      if (!space) {
        setError(t("clientDetail.notFound"));
        setLoading(false);
        return;
      }
      setClient({ id: space.id, name: space.name, slug: space.slug, status: space.status });

      if (intakesRes.success) {
        setIntakes(
          intakesRes.data
            .filter((i) => i.space_id === id)
            .map((i) => ({ id: i.id, client_name: i.client_name, status: i.status })),
        );
      } else {
        setError(intakesRes.error);
      }
      setLoading(false);

      // Space-scoped user/invite counts (replaces the legacy sales-org-by-name match
      // + the old invitations RPC). Members come from the real listUsers endpoint;
      // invites from the seam-shaped listInvitations (graceful when not yet available).
      const usersRes = await listUsers();
      if (cancelled) return;
      const inviteRes = await listInvitations(id);
      if (cancelled) return;

      const spaceMembers = usersRes.success
        ? usersRes.data.filter((u) => u.space_id === id)
        : [];
      const memberCount = spaceMembers.filter((u) => u.status === "active").length;
      const inviteCount = inviteRes.success ? inviteRes.data.length : spaceMembers.length;
      setUsers({ member_count: memberCount, invite_count: inviteCount });
    })();
    return () => {
      cancelled = true;
    };
  }, [id, t]);

  const meta = useMemo(() => {
    if (!client) return "";
    return [client.slug, client.status].filter(Boolean).join(" · ");
  }, [client]);

  if (loading) {
    return <div className="py-12 text-sm text-ink/60">{t("clientDetail.loading")}</div>;
  }
  if (error || !client) {
    return (
      <div>
        <Link
          to="/admin/pulse/clients"
          className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
        >
          ← {t("clientDetail.backToClients")}
        </Link>
        <p className="mt-6 text-sm text-red-600">{error ?? t("clientDetail.notFoundGeneric")}</p>
      </div>
    );
  }

  return (
    <div>
      <Link
        to="/admin/pulse/clients"
        className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
      >
        ← {t("clientDetail.backToClients")}
      </Link>
      <h1 className="mt-3 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
        {client.name}
      </h1>
      {meta && (
        <p className="mt-1 font-mono text-xs uppercase tracking-wider text-ink/60">{meta}</p>
      )}
      <section className="mt-8 border border-ink/15 p-5">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink/60">
          {t("clientDetail.productsUsed")}
        </h2>
        <div className="mt-4 flex flex-col gap-3">
          {(() => {
            const pulseCount = intakes.length;
            const pulseActive = intakes.filter(
              (i) => i.status && !["delivered", "archived"].includes(i.status),
            ).length;
            const salesActive = Boolean(users && users.member_count > 0);
            const rows: Array<{ p: ProductKey; active: boolean; text: string }> = [
              {
                p: "pulse",
                active: pulseCount > 0,
                text:
                  pulseCount === 0
                    ? "—"
                    : `${t("clientDetail.intakeCount", { count: pulseCount })}${pulseActive > 0 ? t("clientDetail.inResearch") : ""}`,
              },
              {
                p: "sales",
                active: salesActive,
                text: users
                  ? t("clientDetail.salesSummary", {
                      invites: users.invite_count,
                      members: users.member_count,
                    })
                  : "—",
              },
              { p: "echo", active: false, text: "—" },
              { p: "flux", active: false, text: "—" },
              { p: "consumer", active: false, text: "—" },
            ];
            return rows.map((r) => (
              <div key={r.p} className="flex items-center gap-4">
                <ProductBadge product={r.p} muted={!r.active} />
                <span
                  className={
                    "font-sans text-sm " + (r.active ? "text-ink" : "text-ink/40")
                  }
                >
                  {r.text}
                </span>
              </div>
            ));
          })()}
        </div>
      </section>
      <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-[280px_1fr]">
        <aside className="lg:sticky lg:top-8 lg:self-start">
          <div className="border border-ink/10 p-4">
            <h2 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink">
              {t("clientDetail.clientInfo")}
            </h2>
            <Row label={t("clientDetail.name")}>{client.name}</Row>
            <Row label={t("clientDetail.slug")}>{client.slug || "—"}</Row>
            <Row label={t("clientDetail.status")}>{client.status}</Row>
            <Row label={t("clientDetail.intakesTotal")}>{intakes.length}</Row>
          </div>
        </aside>

        <main>
          <div className="flex items-baseline justify-between border-b border-ink/30 pb-2">
            <h2 className="font-serif text-2xl font-normal lowercase text-ink">
              {t("clientDetail.intakesFor", { name: client.name })}
            </h2>
            <span className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
              {t("clientDetail.total", { count: intakes.length })}
            </span>
          </div>

          {intakes.length === 0 ? (
            <p className="py-8 text-sm italic text-ink/60">{t("clientDetail.noIntakes")}</p>
          ) : (
            <div>
              <div className="grid grid-cols-[1fr_160px] gap-x-4 border-b border-ink/30 py-2 font-mono text-[11px] uppercase tracking-wider text-ink/70">
                <div>{t("clientDetail.colName")}</div>
                <div>{t("clientDetail.colStatus")}</div>
              </div>
              {intakes.map((i) => (
                <div
                  key={i.id}
                  className="grid cursor-pointer grid-cols-[1fr_160px] items-center gap-x-4 border-b border-ink/10 py-3 transition-colors hover:bg-ink/5"
                  onClick={() =>
                    navigate({ to: "/admin/pulse/intakes/$id", params: { id: i.id } })
                  }
                >
                  <div className="font-sans text-sm text-ink">
                    {i.client_name || t("clientDetail.unnamed")}
                  </div>
                  <div>
                    <StatusPill status={i.status} />
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="mt-6">
            <Button asChild>
              <Link
                to="/admin/pulse/intakes/new"
                search={{ client_id: client.id } as never}
              >
                {t("clientDetail.newIntakeFor", { name: client.name })}
              </Link>
            </Button>
          </div>
        </main>
      </div>
    </div>
  );
}
