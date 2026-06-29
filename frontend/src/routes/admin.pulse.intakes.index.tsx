import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Inbox, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { StatusPill } from "@/components/intake/_status";
import { listIntakes } from "@/lib/api/intakes";
import { listSpaces } from "@/lib/api/admin";
import { useActiveSpace } from "@/lib/active-space";

export const Route = createFileRoute("/admin/pulse/intakes/")({
 component: IntakesPage,
});

type IntakeRow = {
 id: string;
 status: string | null;
 client_name: string | null;
 space_name: string;
};

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "all", label: "Alle" },
  { value: "draft", label: "Concept" },
  { value: "submitted", label: "Ingediend" },
  { value: "reviewed", label: "Gereviewd" },
  { value: "validated_by_client", label: "Gevalideerd" },
  { value: "in_research", label: "In onderzoek" },
  { value: "delivered", label: "Geleverd" },
  { value: "archived", label: "Gearchiveerd" },
];

function IntakesPage() {
 const navigate = useNavigate();
 const [intakes, setIntakes] = useState<IntakeRow[]>([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [statusFilter, setStatusFilter] = useState<string>("all");
 const [search, setSearch] = useState("");
 // Source of truth for whether a superadmin has narrowed to a single space. The backend
 // now honors ?space_id for a superadmin (threaded via withActiveSpace in listIntakes), so
 // the subtitle tracks the REAL filter state instead of falsely claiming filtering.
 const { activeSpaceId } = useActiveSpace();

 useEffect(() => {
  let cancelled = false;
  async function loadIntakes() {
    setLoading(true);

    // Reads cross the authenticated seam (lib/api) — the backend re-derives tenant
    // authority from the verified token; the active-space param is a superadmin
    // view-filter only (TENANT-04, threaded inside listIntakes via withActiveSpace).
    const [intakesRes, spacesRes] = await Promise.all([listIntakes(), listSpaces()]);
    if (cancelled) return;

    if (!intakesRes.success) {
      setError(intakesRes.error);
      setIntakes([]);
      setLoading(false);
      return;
    }

    // Space names are best-effort enrichment; a failed lookup must not blank the list.
    const spaceName = new Map<string, string>();
    if (spacesRes.success) {
      for (const s of spacesRes.data) spaceName.set(s.id, s.name);
    }

    const rows: IntakeRow[] = intakesRes.data.map((i) => ({
      id: i.id,
      status: i.status,
      client_name: i.client_name,
      space_name: spaceName.get(i.space_id) ?? "—",
    }));

    setError(null);
    setIntakes(rows);
    setLoading(false);
  }

  loadIntakes();
  return () => {
    cancelled = true;
  };
 }, []);

 const filtered = useMemo(() => {
 const q = search.trim().toLowerCase();
 return intakes.filter((r) => {
 if (statusFilter !== "all" && (r.status ?? "") !== statusFilter) return false;
 if (q) {
 const hay = `${r.client_name ?? ""} ${r.space_name}`.toLowerCase();
 if (!hay.includes(q)) return false;
 }
 return true;
 });
 }, [intakes, statusFilter, search]);

 return (
 <div>
 <div className="flex flex-wrap items-start justify-between gap-4">
 <div>
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">intakes</h1>
          <p className="mt-1 text-sm text-ink/60">
            {activeSpaceId
              ? "Pulse intakes, gefilterd op de actieve klant."
              : "Alle Pulse intakes."}
          </p>
        </div>
        <Button asChild>
          <Link to="/admin/pulse/intakes/new">Nieuwe intake</Link>
        </Button>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1 border border-ink p-1">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s.value}
              onClick={() => setStatusFilter(s.value)}
              className={cn(
                "px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors",
                statusFilter === s.value
                  ? "bg-ink text-paper"
                  : "text-ink/60 hover:bg-ink/10",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="relative ml-auto w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Zoek klant of naam…"
            className="h-9 pl-8"
          />
        </div>
      </div>

      <div className="mt-6 border border-ink bg-paper">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent border-ink">
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">Klant</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">Naam</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">Status</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink text-right">Acties</TableHead>
            </TableRow>
          </TableHeader>
 <TableBody>
 {loading ? (
 Array.from({ length: 3 }).map((_, i) => (
 <TableRow key={i}>
 {Array.from({ length: 4 }).map((__, j) => (
 <TableCell key={j} className="px-4 py-4">
 <Skeleton className="h-4 w-full max-w-[140px]" />
 </TableCell>
 ))}
 </TableRow>
 ))
 ) : error ? (
 <TableRow>
 <TableCell colSpan={4} className="px-4 py-12 text-center text-sm text-red-600">
 {error}
 </TableCell>
 </TableRow>
 ) : filtered.length === 0 ? (
 <TableRow className="hover:bg-transparent">
 <TableCell colSpan={4} className="px-4 py-16">
 <div className="flex flex-col items-center text-center">
 <Inbox className="h-8 w-8 text-ink/30" />
 <p className="mt-3 text-sm font-medium text-ink">Nog geen intakes</p>
 <p className="mt-1 text-sm text-ink/60">
 Klik 'Nieuwe intake' om er één aan te maken.
 </p>
 </div>
 </TableCell>
 </TableRow>
 ) : (
 filtered.map((r) => (
 <TableRow
 key={r.id}
 className="cursor-pointer"
 onClick={() => navigate({ to: "/admin/pulse/intakes/$id", params: { id: r.id } })}
 >
              <TableCell className="px-4 py-3 text-sm">
                {r.space_name && r.space_name !== "—" ? r.space_name : <span className="text-ink/30">—</span>}
              </TableCell>
 <TableCell className="px-4 py-3 text-sm text-ink/70">
 {r.client_name ?? "—"}
 </TableCell>
 <TableCell className="px-4 py-3">
 <StatusPill status={r.status} />
 </TableCell>
 <TableCell
 className="px-4 py-3 text-right"
 onClick={(e) => e.stopPropagation()}
 >
  <div className="flex items-center justify-end gap-2">
 <Button asChild size="sm" variant="ghost">
 <Link to="/admin/pulse/intakes/$id" params={{ id: r.id }}>
 Open
 </Link>
 </Button>
 </div>
 </TableCell>
 </TableRow>
 ))
 )}
 </TableBody>
 </Table>
 </div>
 </div>
 );
}
