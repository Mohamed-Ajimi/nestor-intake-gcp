import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import { nl } from "date-fns/locale";
import { toast } from "sonner";
import { ArrowLeft, Copy, ExternalLink } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { ClientFormModal } from "@/components/admin/ClientFormModal";
import { ProductBadge, type ProductKey } from "@/components/admin/ProductBadge";

export const Route = createFileRoute("/admin/pulse/clients/$id")({
  component: ClientDetailPage,
});

type SalesOrgSummary = {
  id: string;
  name: string;
  member_count: number;
  invite_count: number;
};

type ClientFull = {
  id: string;
  name: string;
  country: string | null;
  website: string | null;
  industry: string | null;
  vat_number: string | null;
  primary_contact_name: string | null;
  primary_contact_email: string | null;
  primary_contact_phone: string | null;
  primary_contact_role: string | null;
  created_at: string;
  archived_at: string | null;
};

type IntakeRow = {
  id: string;
  title: string | null;
  status: string | null;
  product_slug: string;
  client_intake_token: string | null;
  updated_at: string;
  delivered_at: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Concept",
  submitted: "Ingediend",
  reviewed: "Gereviewd",
  validated_by_client: "Gevalideerd",
  decomposed: "Gedecomposeerd",
  in_research: "In onderzoek",
  delivered: "Geleverd",
  archived: "Gearchiveerd",
};

function StatusPill({ status }: { status: string | null }) {
  if (!status) return <span className="font-mono text-xs text-ink/40">—</span>;
  return (
    <span className="inline-flex items-center border border-ink px-2 py-0.5 font-mono text-[11px] uppercase tracking-wider text-ink">
      {(STATUS_LABEL[status] ?? status).toUpperCase()}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-1 border-b border-ink/10 py-3 last:border-b-0 sm:grid-cols-[120px_1fr]">
      <div className="font-sans text-sm font-normal text-ink/70">{label}</div>
      <div className="font-sans text-sm text-ink">{children}</div>
    </div>
  );
}

function ClientDetailPage() {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState<ClientFull | null>(null);
  const [intakes, setIntakes] = useState<IntakeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [salesOrg, setSalesOrg] = useState<SalesOrgSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!supabase) return;
      setLoading(true);
      const [{ data: c, error: cErr }, { data: is, error: iErr }] = await Promise.all([
        supabase
          .schema("public" as never)
          .from("clients")
          .select(
            "id, name, country, website, industry, vat_number, primary_contact_name, primary_contact_email, primary_contact_phone, primary_contact_role, created_at, archived_at",
          )
          .eq("id", id)
          .single(),
        supabase
          .schema("nestor")
          .from("intakes")
          .select("id, title, status, product_slug, client_intake_token, updated_at, delivered_at")
          .eq("client_id", id)
          .order("updated_at", { ascending: false }),
      ]);
      if (cancelled) return;
      if (cErr || !c) {
        setError(cErr?.message ?? "Klant niet gevonden");
        setLoading(false);
        return;
      }
      setClient(c as ClientFull);
      setIntakes((is ?? []) as IntakeRow[]);
      if (iErr) setError(iErr.message);
      setLoading(false);

      // Match Sales-org by name (case-insensitive)
      const { data: orgs } = await (supabase as any)
        .schema("nestor")
        .from("organizations")
        .select("id, name, memberships:organization_memberships(count)")
        .eq("type", "client_company")
        .ilike("name", (c as ClientFull).name);
      const match = ((orgs ?? []) as Array<{
        id: string;
        name: string;
        memberships?: { count: number }[];
      }>)[0];
      if (match) {
        const { data: inviteData } = await (supabase as any)
          .schema("sales")
          .rpc("list_invitations", { p_organization_id: match.id });
        const invites = (inviteData ?? []) as Array<{ status: string }>;
        if (!cancelled) {
          setSalesOrg({
            id: match.id,
            name: match.name,
            member_count: match.memberships?.[0]?.count ?? 0,
            invite_count: invites.length,
          });
        }
      } else if (!cancelled) {
        setSalesOrg(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, reloadTick]);


  const copyLink = async (token: string | null) => {
    if (!token) {
      toast.error("Geen intake-token beschikbaar");
      return;
    }
    const url = `${window.location.origin}/intake/${token}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link gekopieerd");
    } catch {
      toast.error("Kopiëren mislukt");
    }
  };

  const meta = useMemo(() => {
    if (!client) return "";
    return [client.country, client.industry].filter(Boolean).join(" · ");
  }, [client]);

  if (loading) {
    return <div className="py-12 text-sm text-ink/60">Laden…</div>;
  }
  if (error || !client) {
    return (
      <div>
        <Link
          to="/admin/pulse/clients"
          className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
        >
          <ArrowLeft className="mr-1 inline h-3.5 w-3.5" />
          Klanten
        </Link>
        <p className="mt-6 text-sm text-red-600">{error ?? "Niet gevonden"}</p>
      </div>
    );
  }

  return (
    <div>
      <Link
        to="/admin/pulse/clients"
        className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
      >
        <ArrowLeft className="mr-1 inline h-3.5 w-3.5" />
        Klanten
      </Link>
      <h1 className="mt-3 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
        {client.name}
      </h1>
      {meta && (
        <p className="mt-1 font-mono text-xs uppercase tracking-wider text-ink/60">{meta}</p>
      )}
      <section className="mt-8 border border-ink/15 p-5">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink/60">
          Producten gebruikt
        </h2>
        <div className="mt-4 flex flex-col gap-3">
          {(() => {
            const pulseCount = intakes.filter((i) => i.product_slug === "pulse").length;
            const pulseActive = intakes.filter(
              (i) => i.product_slug === "pulse" && i.status && !["delivered", "archived"].includes(i.status),
            ).length;
            const rows: Array<{ p: ProductKey; active: boolean; text: string }> = [
              {
                p: "pulse",
                active: pulseCount > 0,
                text:
                  pulseCount === 0
                    ? "—"
                    : `${pulseCount} intake${pulseCount === 1 ? "" : "s"}${pulseActive > 0 ? " — in onderzoek" : ""}`,
              },
              {
                p: "sales",
                active: Boolean(salesOrg),
                text: salesOrg
                  ? `Pilot live · ${salesOrg.invite_count} user${salesOrg.invite_count === 1 ? "" : "s"} uitgenodigd · ${salesOrg.member_count} geactiveerd`
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
          <div className="mb-4 border border-ink/10 bg-paper2/40 p-4">
            <h2 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink">
              Contact
            </h2>
            <Row label="Naam">
              {client.primary_contact_name || <span className="text-ink/30">—</span>}
            </Row>
            <Row label="Functie">
              {client.primary_contact_role || <span className="text-ink/30">—</span>}
            </Row>
            <Row label="Email">
              {client.primary_contact_email ? (
                <a
                  href={`mailto:${client.primary_contact_email}`}
                  className="underline hover:text-ink"
                >
                  {client.primary_contact_email}
                </a>
              ) : (
                <span className="text-ink/30">—</span>
              )}
            </Row>
            <Row label="Telefoon">
              {client.primary_contact_phone ? (
                <a
                  href={`tel:${client.primary_contact_phone}`}
                  className="underline hover:text-ink"
                >
                  {client.primary_contact_phone}
                </a>
              ) : (
                <span className="text-ink/30">—</span>
              )}
            </Row>
          </div>
          <div className="border border-ink/10 p-4">

            <h2 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink">
              Klant-info
            </h2>
            <Row label="Naam">{client.name}</Row>
            <Row label="Land">{client.country || "—"}</Row>
            <Row label="Industrie">{client.industry || "—"}</Row>
            <Row label="Website">
              {client.website ? (
                <a
                  href={client.website}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 underline hover:text-ink"
                >
                  {client.website.replace(/^https?:\/\//, "")}
                  <ExternalLink className="h-3 w-3" />
                </a>
              ) : (
                "—"
              )}
            </Row>
            <Row label="Aangemaakt">
              {format(new Date(client.created_at), "d MMMM yyyy", { locale: nl })}
            </Row>
            <Row label="VAT">{client.vat_number || "—"}</Row>
            <Row label="Aantal intakes">{intakes.length}</Row>
          </div>

          <div className="mt-4 flex flex-col gap-2">
            <Button variant="outline" onClick={() => setEditOpen(true)}>
              Bewerken
            </Button>
          </div>
        </aside>

        <main>
          <div className="flex items-baseline justify-between border-b border-ink/30 pb-2">
            <h2 className="font-serif text-2xl font-normal lowercase text-ink">
              intakes voor {client.name}
            </h2>
            <span className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
              {intakes.length} totaal
            </span>
          </div>

          {intakes.length === 0 ? (
            <p className="py-8 text-sm italic text-ink/60">
              Nog geen intakes voor deze klant.
            </p>
          ) : (
            <div>
              <div className="grid grid-cols-[1fr_120px_160px_140px_auto] gap-x-4 border-b border-ink/30 py-2 font-mono text-[11px] uppercase tracking-wider text-ink/70">
                <div>Titel</div>
                <div>Product</div>
                <div>Status</div>
                <div>Laatst bewerkt</div>
                <div className="text-right">Acties</div>
              </div>
              {intakes.map((i) => (
                <div
                  key={i.id}
                  className="grid cursor-pointer grid-cols-[1fr_120px_160px_140px_auto] items-center gap-x-4 border-b border-ink/10 py-3 transition-colors hover:bg-ink/5"
                  onClick={() =>
                    navigate({ to: "/admin/pulse/intakes/$id", params: { id: i.id } })
                  }
                >
                  <div className="font-sans text-sm text-ink">
                    {i.title || "Zonder titel"}
                  </div>
                  <div className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
                    {i.product_slug}
                  </div>
                  <div>
                    <StatusPill status={i.status} />
                  </div>
                  <div className="font-sans text-sm text-ink/60">
                    {formatDistanceToNow(new Date(i.updated_at), {
                      addSuffix: true,
                      locale: nl,
                    })}
                    {i.delivered_at && (
                      <div className="text-xs text-ink/50">
                        Geleverd: {format(new Date(i.delivered_at), "d MMM yyyy", { locale: nl })}
                      </div>
                    )}
                  </div>
                  <div
                    className="flex justify-end gap-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => copyLink(i.client_intake_token)}
                    >
                      <Copy className="h-3.5 w-3.5" />
                      Kopieer link
                    </Button>
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
                + Nieuwe intake voor {client.name}
              </Link>
            </Button>
          </div>
        </main>
      </div>
      <ClientFormModal
        open={editOpen}
        onOpenChange={setEditOpen}
        initial={{
          id: client.id,
          name: client.name,
          country: client.country ?? "BE",
          website: client.website ?? "",
          industry: client.industry ?? "",
          vat_number: client.vat_number ?? "",
        }}
        onSaved={() => setReloadTick((t) => t + 1)}
      />
    </div>
  )
}
