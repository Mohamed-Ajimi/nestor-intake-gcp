import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { nl } from "date-fns/locale";
import { Inbox } from "lucide-react";
import { supabase } from "@/lib/supabase";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/sales/projects/")({
  component: SalesProjectsListPage,
});

type ProjectRow = {
  id: string;
  klant_name: string;
  klant_email: string;
  klant_company: string;
  klant_role: string | null;
  project_title: string | null;
  status: string;
  updated_at: string;
};

// House badge variants — aligned with the Pulse StatusPill system (badge-* + mark-*).
type SalesStatusVariant = { cls: string; mark?: "green" | null };

const STATUS_STYLES: Record<string, SalesStatusVariant> = {
  concept: { cls: "badge-dashed" },
  ingediend: { cls: "badge-ink" },
  gereviewd: { cls: "badge-outline", mark: "green" },
  gevalideerd: { cls: "badge-ink", mark: "green" },
  in_onderzoek: { cls: "badge-outline", mark: "green" },
  geleverd: { cls: "badge-ink" },
  gearchiveerd: { cls: "badge-outline text-ink/40 border-ink/40" },
};

const STATUS_LABEL: Record<string, string> = {
  concept: "CONCEPT",
  ingediend: "INGEDIEND",
  gereviewd: "GEREVIEWD",
  gevalideerd: "GEVALIDEERD",
  in_onderzoek: "IN ONDERZOEK",
  geleverd: "GELEVERD",
  gearchiveerd: "GEARCHIVEERD",
};

export function SalesStatusBadge({ status }: { status: string }) {
  const v = STATUS_STYLES[status] ?? STATUS_STYLES.concept;
  const label = STATUS_LABEL[status] ?? status.toUpperCase();
  return (
    <span className={cn(v.cls)}>
      {v.mark === "green" && <span className="mark-green" />}
      {label}
    </span>
  );
}

function SalesProjectsListPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      if (!supabase) {
        setError("Supabase niet geconfigureerd.");
        setLoading(false);
        return;
      }
      const { data, error: rpcErr } = await supabase
        .schema("sales" as never)
        .rpc("list_projects");
      if (rpcErr) {
        setError(rpcErr.message);
        setProjects([]);
      } else {
        setProjects((data ?? []) as ProjectRow[]);
      }
      setLoading(false);
    }
    load();
  }, []);

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
            projecten
          </h1>
          <p className="mt-1 text-sm text-ink/60">
            Alle Nestor Sales projecten, gesorteerd op laatste activiteit.
          </p>
        </div>
        <Button asChild>
          <Link to="/admin/sales/projects/new">+ Nieuw project</Link>
        </Button>
      </div>

      {!loading && !error && projects.length === 0 ? (
        <EmptyState onAction={() => navigate({ to: "/admin/sales/projects/new" })} />
      ) : (
        <div className="mt-6 border border-ink bg-paper">
          <Table>
            <TableHeader>
              <TableRow className="border-ink hover:bg-transparent">
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">
                  Klant
                </TableHead>
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">
                  Bedrijf
                </TableHead>
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">
                  Project
                </TableHead>
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">
                  Status
                </TableHead>
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">
                  Laatste activiteit
                </TableHead>
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink text-right">
                  Acties
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 6 }).map((__, j) => (
                      <TableCell key={j} className="px-4 py-4">
                        <Skeleton className="h-4 w-full max-w-[140px]" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : error ? (
                <TableRow>
                  <TableCell colSpan={6} className="px-4 py-12 text-center text-sm text-red-600">
                    {error}
                  </TableCell>
                </TableRow>
              ) : (
                projects.map((p) => (
                  <TableRow
                    key={p.id}
                    className="cursor-pointer"
                    onClick={() => navigate({ to: "/admin/sales/projects/$id", params: { id: p.id } })}
                  >
                    <TableCell className="px-4 py-3 text-sm">
                      <p className="font-medium text-ink">{p.klant_name}</p>
                      <p className="text-xs text-ink/50">{p.klant_email}</p>
                    </TableCell>
                    <TableCell className="px-4 py-3 text-sm text-ink/70">
                      {p.klant_company}
                    </TableCell>
                    <TableCell className="px-4 py-3 text-sm text-ink/70">
                      {p.project_title || <span className="text-ink/30">—</span>}
                    </TableCell>
                    <TableCell className="px-4 py-3">
                      <SalesStatusBadge status={p.status} />
                    </TableCell>
                    <TableCell className="px-4 py-3 text-sm text-ink/60">
                      {formatDistanceToNow(new Date(p.updated_at), {
                        addSuffix: true,
                        locale: nl,
                      })}
                    </TableCell>
                    <TableCell className="px-4 py-3 text-right">
                      <span className="font-mono text-[11px] uppercase tracking-wider text-ink hover:underline">
                        Open →
                      </span>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function EmptyState({ onAction }: { onAction: () => void }) {
  return (
    <div className="mt-10 flex flex-col items-center border border-dashed border-ink/30 px-6 py-16 text-center">
      <Inbox className="h-8 w-8 text-ink/30" />
      <p className="mt-3 font-mono text-xs uppercase tracking-wider text-ink/60">
        ⌀ Nog geen Sales-projecten
      </p>
      <p className="mt-2 max-w-sm text-sm text-ink/60">
        Maak een nieuw project aan voor een klant. Die krijgt dan een mail
        met een intake-link.
      </p>
      <button
        onClick={onAction}
        className="mt-6 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90"
      >
        + Nieuw project
      </button>
    </div>
  );
}
