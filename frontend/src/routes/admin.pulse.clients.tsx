import { createFileRoute, useNavigate } from "@tanstack/react-router";
import React, { useEffect, useMemo, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { nl } from "date-fns/locale";
import { Search, Users } from "lucide-react";
import { supabase, supabasePublic } from "@/lib/supabase";
import { Input } from "@/components/ui/input";

export const Route = createFileRoute("/admin/pulse/clients")({
  validateSearch: (s: Record<string, unknown>) => ({
    client: typeof s.client === "string" ? s.client : undefined,
  }),
  component: ClientsPage,
});

type Project = {
  id: string;
  title: string | null;
  status: string | null;
  updated_at: string;
  created_at: string;
  delivered_at: string | null;
};

type ClientRow = {
  id: string;
  name: string;
  primary_contact_name: string | null;
  primary_contact_email: string | null;
  primary_contact_phone: string | null;
  primary_contact_role: string | null;
  projects: Project[];
  project_count: number;
  status_counts: Record<string, number>;
  last_activity: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "concept",
  concept: "concept",
  submitted: "ingediend",
  reviewed: "gereviewd",
  validated_by_client: "gevalideerd",
  validated: "gevalideerd",
  decomposed: "gedecomposeerd",
  in_research: "in onderzoek",
  delivered: "geleverd",
  archived: "gearchiveerd",
};

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="font-mono text-xs text-ink/40">—</span>;
  return (
    <span className="inline-flex items-center border border-ink px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink">
      {(STATUS_LABEL[status] ?? status).toUpperCase()}
    </span>
  );
}

function statusSummary(counts: Record<string, number>) {
  return Object.entries(counts)
    .map(([k, v]) => `${v} ${STATUS_LABEL[k] ?? k}`)
    .join(", ");
}

function ClientsPage() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!supabase || !supabasePublic) {
        setError("Supabase niet geconfigureerd.");
        setLoading(false);
        return;
      }
      setLoading(true);

      const { data: intakes, error: iErr } = await supabase
        .schema("nestor")
        .from("intakes")
        .select("id, title, status, updated_at, created_at, delivered_at, client_id")
        .eq("product_slug", "pulse")
        .order("updated_at", { ascending: false });

      if (cancelled) return;
      if (iErr) {
        setError(iErr.message);
        setLoading(false);
        return;
      }
      if (!intakes || intakes.length === 0) {
        setClients([]);
        setLoading(false);
        return;
      }

      const clientIds = [
        ...new Set(
          (intakes as Array<{ client_id: string | null }>)
            .map((i) => i.client_id)
            .filter((x): x is string => Boolean(x)),
        ),
      ];

      const { data: clientsData, error: cErr } = await supabasePublic
        .schema("public")
        .from("clients")
        .select(
          "id, name, primary_contact_name, primary_contact_email, primary_contact_phone, primary_contact_role",
        )
        .in("id", clientIds);

      if (cancelled) return;
      if (cErr) {
        setError(cErr.message);
        setLoading(false);
        return;
      }

      const byClient: Record<string, Project[]> = {};
      for (const i of intakes as Array<Project & { client_id: string | null }>) {
        if (!i.client_id) continue;
        if (!byClient[i.client_id]) byClient[i.client_id] = [];
        byClient[i.client_id].push({
          id: i.id,
          title: i.title,
          status: i.status,
          updated_at: i.updated_at,
          created_at: i.created_at,
          delivered_at: (i as Project).delivered_at ?? null,
        });
      }

      const enriched: ClientRow[] = (clientsData ?? []).map((c) => {
        const projects = (byClient[c.id] ?? []).sort((a, b) =>
          b.updated_at.localeCompare(a.updated_at),
        );
        const status_counts: Record<string, number> = {};
        for (const p of projects) {
          const s = p.status ?? "draft";
          status_counts[s] = (status_counts[s] ?? 0) + 1;
        }
        return {
          id: c.id,
          name: c.name,
          primary_contact_name: (c as ClientRow).primary_contact_name ?? null,
          primary_contact_email: (c as ClientRow).primary_contact_email ?? null,
          primary_contact_phone: (c as ClientRow).primary_contact_phone ?? null,
          primary_contact_role: (c as ClientRow).primary_contact_role ?? null,
          projects,
          project_count: projects.length,
          status_counts,
          last_activity: projects[0]?.updated_at ?? null,
        };
      });

      enriched.sort((a, b) =>
        (b.last_activity ?? "").localeCompare(a.last_activity ?? ""),
      );

      setClients(enriched);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return clients;
    return clients.filter((c) =>
      [c.name, c.primary_contact_name, c.primary_contact_email]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [clients, search]);

  function toggleExpand(id: string) {
    setExpanded((prev) => (prev === id ? null : id));
  }

  return (
    <div>
      <div>
        <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
          klanten
        </h1>
        <p className="mt-1 font-sans text-sm italic text-ink/60">
          Alleen klanten met minstens één Pulse-project.
        </p>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="zoek op naam, contact of email…"
            className="h-9 pl-8"
          />
        </div>
      </div>

      <div className="mt-6">
        {loading ? (
          <div className="py-12 text-center text-sm text-ink/60">Laden…</div>
        ) : error ? (
          <div className="py-12 text-center text-sm text-red-600">{error}</div>
        ) : filtered.length === 0 ? (
          clients.length === 0 ? (
            <div className="mt-6 border border-ink/20 bg-paper2/40 p-12 text-center">
              <p className="mb-4 font-mono text-sm text-ink/60">
                ⌀ Nog geen klanten met Pulse-projecten
              </p>
              <p className="mb-6 text-sm text-ink/50">
                Klanten verschijnen hier zodra je hun eerste intake aanmaakt.
              </p>
              <button
                onClick={() => navigate({ to: "/admin/pulse/intakes/new" })}
                className="bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper"
              >
                + Nieuwe intake aanmaken
              </button>
            </div>
          ) : (
            <div className="flex flex-col items-center py-16 text-center">
              <Users className="h-8 w-8 text-ink/30" />
              <p className="mt-3 text-sm text-ink/70">Geen klanten gevonden.</p>
            </div>
          )
        ) : (
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-ink/30 font-mono text-[10px] uppercase tracking-wider text-ink/70">
                <th className="w-6 px-4 py-2 text-left"></th>
                <th className="px-4 py-2 text-left">Klant</th>
                <th className="px-4 py-2 text-left">Contact</th>
                <th className="px-4 py-2 text-left">Projecten</th>
                <th className="px-4 py-2 text-left">Laatste activiteit</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => {
                const isOpen = expanded === c.id;
                return (
                  <React.Fragment key={c.id}>
                    <tr
                      onClick={() => toggleExpand(c.id)}
                      className="cursor-pointer border-b border-ink/10 hover:bg-ink/5"
                    >
                      <td className="px-4 py-3 text-ink/40">
                        <span
                          className={
                            "inline-block transition-transform " +
                            (isOpen ? "rotate-90" : "")
                          }
                        >
                          ▶
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate({
                              to: "/admin/pulse/clients/$id",
                              params: { id: c.id },
                            });
                          }}
                          className="text-left font-sans font-medium text-ink hover:underline"
                        >
                          {c.name}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-sm text-ink/80">
                        {c.primary_contact_name || c.primary_contact_email ? (
                          <div>
                            {c.primary_contact_name && (
                              <div>{c.primary_contact_name}</div>
                            )}
                            {c.primary_contact_email && (
                              <div className="text-xs text-ink/50">
                                {c.primary_contact_email}
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-ink/30">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-ink">
                        <div>
                          {c.project_count}{" "}
                          {c.project_count === 1 ? "project" : "projecten"}
                        </div>
                        {c.project_count > 0 && (
                          <div className="text-xs text-ink/50">
                            {statusSummary(c.status_counts)}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-ink/70">
                        {c.last_activity
                          ? formatDistanceToNow(new Date(c.last_activity), {
                              addSuffix: true,
                              locale: nl,
                            })
                          : "—"}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="border-b border-ink/10 bg-paper2/40">
                        <td colSpan={5} className="px-12 py-4">
                          <div className="mb-3 font-mono text-[10px] uppercase tracking-wider text-ink/60">
                            Projecten ({c.project_count})
                          </div>
                          <div className="space-y-2">
                            {c.projects.map((p) => (
                              <button
                                key={p.id}
                                onClick={() =>
                                  navigate({
                                    to: "/admin/pulse/intakes/$id",
                                    params: { id: p.id },
                                  })
                                }
                                className="flex w-full items-center gap-4 border border-ink/15 bg-paper px-4 py-3 text-left hover:bg-ink/5"
                              >
                                <div className="flex-1">
                                  <div className="font-medium text-ink">
                                    {p.title || "Zonder titel"}
                                  </div>
                                  <div className="text-xs text-ink/50">
                                    {formatDistanceToNow(new Date(p.updated_at), {
                                      addSuffix: true,
                                      locale: nl,
                                    })}
                                    {p.delivered_at && (
                                      <>
                                        {" · Geleverd: "}
                                        {new Date(p.delivered_at).toLocaleDateString("nl-BE", {
                                          day: "numeric",
                                          month: "short",
                                          year: "numeric",
                                        })}
                                      </>
                                    )}
                                  </div>
                                </div>
                                <StatusBadge status={p.status} />
                                <span className="text-ink/40">→</span>
                              </button>
                            ))}
                          </div>
                          <button
                            onClick={() =>
                              navigate({
                                to: "/admin/pulse/intakes/new",
                                search: { client_id: c.id } as never,
                              })
                            }
                            className="mt-3 font-mono text-[10px] uppercase tracking-wider text-ink/60 hover:text-ink"
                          >
                            + Nieuwe intake voor {c.name}
                          </button>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
