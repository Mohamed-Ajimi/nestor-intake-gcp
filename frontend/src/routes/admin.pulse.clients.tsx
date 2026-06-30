import { createFileRoute, useNavigate } from "@tanstack/react-router";
import React, { useEffect, useMemo, useState } from "react";
import { Search, Users } from "lucide-react";
import { Input } from "@/components/ui/input";
import { StatusPill, STATUS_LABEL } from "@/components/intake/_status";
import { listIntakes } from "@/lib/api/intakes";
import { listSpaces } from "@/lib/api/admin";

export const Route = createFileRoute("/admin/pulse/clients")({
  // Optional search key: return `{ client?: string }` (key omitted when absent) rather
  // than `{ client: string | undefined }` (a REQUIRED key with a possibly-undefined value),
  // so Links/navigates to this route — and its `$id` child, which inherits this search —
  // need not pass `search`. The param is not read anywhere; this is type hygiene only.
  validateSearch: (s: Record<string, unknown>): { client?: string } =>
    typeof s.client === "string" ? { client: s.client } : {},
  component: ClientsPage,
});

type Project = {
  id: string;
  client_name: string | null;
  status: string | null;
};

// In the GCP model there is no `public.clients` — the org IS the space. A "klant" row
// is therefore a space with at least one Pulse intake, enriched from the seam.
type SpaceRow = {
  id: string;
  name: string;
  projects: Project[];
  project_count: number;
  status_counts: Record<string, number>;
};

function statusSummary(counts: Record<string, number>) {
  return Object.entries(counts)
    .map(([k, v]) => `${v} ${STATUS_LABEL[k]?.toLowerCase() ?? k}`)
    .join(", ");
}

function ClientsPage() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<SpaceRow[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

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
      if (!intakesRes.success) {
        setError(intakesRes.error);
        setLoading(false);
        return;
      }

      const bySpace: Record<string, Project[]> = {};
      for (const i of intakesRes.data) {
        if (!bySpace[i.space_id]) bySpace[i.space_id] = [];
        bySpace[i.space_id].push({
          id: i.id,
          client_name: i.client_name,
          status: i.status,
        });
      }

      const enriched: SpaceRow[] = spacesRes.data
        .map((s) => {
          const projects = bySpace[s.id] ?? [];
          const status_counts: Record<string, number> = {};
          for (const p of projects) {
            const st = p.status ?? "draft";
            status_counts[st] = (status_counts[st] ?? 0) + 1;
          }
          return {
            id: s.id,
            name: s.name,
            projects,
            project_count: projects.length,
            status_counts,
          };
        })
        // Match legacy behaviour: only spaces with at least one Pulse-project.
        .filter((s) => s.project_count > 0);

      setError(null);
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
      [c.name, ...c.projects.map((p) => p.client_name ?? "")]
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
            placeholder="zoek op klant of naam…"
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
                <th className="px-4 py-2 text-left">Projecten</th>
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
                    </tr>
                    {isOpen && (
                      <tr className="border-b border-ink/10 bg-paper2/40">
                        <td colSpan={3} className="px-12 py-4">
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
                                    {p.client_name || "Zonder naam"}
                                  </div>
                                </div>
                                <StatusPill status={p.status} />
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
