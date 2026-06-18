import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { nl } from "date-fns/locale";
import { toast } from "sonner";
import { Copy, Files, Inbox, MoreHorizontal, Search, Trash2 } from "lucide-react";
import { supabase, supabasePublic } from "@/lib/supabase";
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
import {
 DropdownMenu,
 DropdownMenuContent,
 DropdownMenuItem,
 DropdownMenuSeparator,
 DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
 AlertDialog,
 AlertDialogAction,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/pulse/intakes/")({
 component: IntakesPage,
});

type IntakeRow = {
 id: string;
 title: string | null;
 status: string | null;
 product_slug: string;
 updated_at: string;
 client_id: string | null;
 client_name: string;
 client_intake_token?: string | null;
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

type StatusVariant = {
  cls: string;
  mark?: "ink" | "green" | null;
};

const STATUS_VARIANT: Record<string, StatusVariant> = {
  draft: { cls: "badge-dashed" },
  submitted: { cls: "badge-ink" },
  reviewed: { cls: "badge-outline", mark: "green" },
  validated_by_client: { cls: "badge-ink", mark: "green" },
  decomposed: { cls: "badge-outline" },
  in_research: { cls: "badge-outline", mark: "green" },
  delivered: { cls: "badge-ink" },
  archived: { cls: "badge-outline text-ink/40 border-ink/40" },
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


function StatusPill({ status }: { status: string | null }) {
  if (!status) {
    return <span className="badge-outline text-ink/40">—</span>;
  }
  const label = (STATUS_LABEL[status] ?? status).toUpperCase();
  const v = STATUS_VARIANT[status] ?? { cls: "badge-outline" };
  return (
    <span className={cn(v.cls)}>
      {v.mark === "green" && <span className="mark-green" />}
      {v.mark === "ink" && <span className="mark-ink" />}
      {label}
    </span>
  );
}
function IntakesPage() {
 const navigate = useNavigate();
 const [intakes, setIntakes] = useState<IntakeRow[]>([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [statusFilter, setStatusFilter] = useState<string>("all");
 const [search, setSearch] = useState("");

 useEffect(() => {
  async function loadIntakes() {
    setLoading(true);

    if (!supabase || !supabasePublic) {
      setError("Supabase niet geconfigureerd.");
      setIntakes([]);
      setLoading(false);
      return;
    }

    // 1. Haal Pulse-intakes op
    const { data: intakesData, error: intakesErr } = await supabase
      .schema('nestor')
      .from('intakes')
      .select('id, title, status, updated_at, client_id, product_slug')
      .eq('product_slug', 'pulse')
      .order('updated_at', { ascending: false });

    if (intakesErr) {
      console.error('Intakes fetch error:', intakesErr);
      setError(intakesErr.message);
      setIntakes([]);
      setLoading(false);
      return;
    }

    // 2. Verzamel unieke client_ids
    const clientIds = [...new Set(
      (intakesData || [])
        .map(i => i.client_id)
        .filter(Boolean)
    )];

    // 3. Haal client-namen op uit public.clients
    let clientMap: Record<string, string> = {};
    if (clientIds.length > 0) {
      const { data: clientsData, error: clientsErr } = await supabasePublic
        .schema('public')
        .from('clients')
        .select('id, name')
        .in('id', clientIds);

      if (clientsErr) {
        console.error('Clients fetch error:', clientsErr);
      } else {
        clientMap = Object.fromEntries(
          (clientsData || []).map(c => [c.id, c.name])
        );
      }
    }

    // 4. Verrijk intakes met client_name
    const intakesWithClients = (intakesData || []).map(i => ({
      ...i,
      client_name: i.client_id ? clientMap[i.client_id] || '—' : '—'
    }));

    
    setError(null);
    setIntakes(intakesWithClients as IntakeRow[]);
    setLoading(false);
  }

  loadIntakes();
 }, []);

 const filtered = useMemo(() => {
 const q = search.trim().toLowerCase();
 return intakes.filter((r) => {
 if (statusFilter !== "all" && (r.status ?? "") !== statusFilter) return false;
 if (q) {
 const hay = `${r.client_name ?? ""} ${r.title ?? ""}`.toLowerCase();
 if (!hay.includes(q)) return false;
 }
 return true;
 });
 }, [intakes, statusFilter, search]);

 const [confirmDelete, setConfirmDelete] = useState<IntakeRow | null>(null);
 const [busyId, setBusyId] = useState<string | null>(null);

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

 const duplicateIntake = async (row: IntakeRow) => {
 if (!supabase) return;
 setBusyId(row.id);
 try {
 const { data: src, error: sErr } = await supabase
 .schema("nestor")
 .from("intakes")
 .select("client_id, product_slug, template_id, title")
 .eq("id", row.id)
 .single();
 if (sErr || !src) throw sErr ?? new Error("Niet gevonden");
 const token = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
 const baseTitle = (src as { title: string | null }).title ?? "Intake";
 const { data: created, error: iErr } = await supabase
 .schema("nestor")
 .from("intakes")
 .insert({
 client_id: (src as { client_id: string }).client_id,
 product_slug: (src as { product_slug: string }).product_slug,
 template_id: (src as { template_id: string }).template_id,
 status: "draft",
 title: `${baseTitle} (kopie)`,
 client_intake_token: token,
 })
 .select("id")
 .single();
 if (iErr || !created) throw iErr ?? new Error("Aanmaken mislukt");
 const newId = (created as { id: string }).id;
 const { data: answers } = await supabase
 .schema("nestor")
 .from("intake_answers")
 .select("field_key, value")
 .eq("intake_id", row.id);
 if (answers && answers.length > 0) {
 const rows = (answers as Array<{ field_key: string; value: unknown }>).map((a) => ({
 intake_id: newId,
 field_key: a.field_key,
 value: a.value,
 }));
 const { error: aErr } = await supabase
 .schema("nestor")
 .from("intake_answers")
 .insert(rows);
 if (aErr) throw aErr;
 }
 toast.success("Intake gedupliceerd");
 navigate({ to: "/admin/pulse/intakes/$id", params: { id: newId } });
 } catch (e) {
 toast.error(`Dupliceren mislukt: ${(e as Error).message}`);
 } finally {
 setBusyId(null);
 }
 };

 const deleteIntake = async (row: IntakeRow) => {
 if (!supabase) return;
 setBusyId(row.id);
 try {
 const { error: aErr } = await supabase
 .schema("nestor")
 .from("intake_answers")
 .delete()
 .eq("intake_id", row.id);
 if (aErr) throw aErr;
 const { data: deleted, error } = await supabase
 .schema("nestor")
 .from("intakes")
 .delete()
 .eq("id", row.id)
 .select("id");
 if (error) throw error;
 if (!deleted || deleted.length === 0) {
 throw new Error("Geen rechten om te verwijderen (RLS). Check delete-policy op nestor.intakes.");
 }
 setIntakes((rs) => rs.filter((r) => r.id !== row.id));
 toast.success("Intake verwijderd");
 } catch (e) {
 toast.error(`Verwijderen mislukt: ${(e as Error).message}`);
 } finally {
 setBusyId(null);
 setConfirmDelete(null);
 }
 };

 return (
 <div>
 <div className="flex flex-wrap items-start justify-between gap-4">
 <div>
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">intakes</h1>
          <p className="mt-1 text-sm text-ink/60">
            Alle Pulse intakes, gesorteerd op laatste bewerking.
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
            placeholder="Zoek klant of titel…"
            className="h-9 pl-8"
          />
        </div>
      </div>

      <div className="mt-6 border border-ink bg-paper">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent border-ink">
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">Klant</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">Titel</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">Status</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">Laatst bewerkt</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink text-right">Acties</TableHead>
            </TableRow>
          </TableHeader>
 <TableBody>
 {loading ? (
 Array.from({ length: 3 }).map((_, i) => (
 <TableRow key={i}>
 {Array.from({ length: 5 }).map((__, j) => (
 <TableCell key={j} className="px-4 py-4">
 <Skeleton className="h-4 w-full max-w-[140px]" />
 </TableCell>
 ))}
 </TableRow>
 ))
 ) : error ? (
 <TableRow>
 <TableCell colSpan={5} className="px-4 py-12 text-center text-sm text-red-600">
 {error}
 </TableCell>
 </TableRow>
 ) : filtered.length === 0 ? (
 <TableRow className="hover:bg-transparent">
 <TableCell colSpan={5} className="px-4 py-16">
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
                {r.client_name && r.client_name !== "—" ? r.client_name : <span className="text-ink/30">—</span>}
              </TableCell>
 <TableCell className="px-4 py-3 text-sm text-ink/70">
 {r.title ?? "—"}
 </TableCell>
 <TableCell className="px-4 py-3">
 <StatusPill status={r.status} />
 </TableCell>
 <TableCell className="px-4 py-3 text-sm text-ink/60">
 {formatDistanceToNow(new Date(r.updated_at), { addSuffix: true, locale: nl })}
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
 <Button
 size="sm"
 variant="outline"
 onClick={() => copyLink(r.client_intake_token ?? null)}
 >
 <Copy className="h-3.5 w-3.5" />
 Kopieer link
 </Button>
 <DropdownMenu>
 <DropdownMenuTrigger asChild>
 <Button size="sm" variant="ghost" disabled={busyId === r.id} aria-label="Meer">
 <MoreHorizontal className="h-4 w-4" />
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent align="end" className="w-44">
 <DropdownMenuItem onClick={() => duplicateIntake(r)}>
 <Files className="mr-2 h-4 w-4" /> Dupliceer
 </DropdownMenuItem>
 <DropdownMenuSeparator />
 <DropdownMenuItem
 onClick={() => setConfirmDelete(r)}
 className="text-red-600 focus:text-red-700"
 >
 <Trash2 className="mr-2 h-4 w-4" /> Verwijder
 </DropdownMenuItem>
 </DropdownMenuContent>
 </DropdownMenu>
 </div>
 </TableCell>
 </TableRow>
 ))
 )}
 </TableBody>
 </Table>
 </div>

 <AlertDialog open={!!confirmDelete} onOpenChange={(o) => !o && setConfirmDelete(null)}>
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>Intake verwijderen?</AlertDialogTitle>
 <AlertDialogDescription>
 {confirmDelete ? (
 <>
 Je staat op het punt de intake{" "}
 <span className="font-semibold text-ink">
 {confirmDelete.title ?? confirmDelete.product_slug}
 </span>{" "}
 van <span className="font-semibold text-ink">{confirmDelete.client_name ?? "—"}</span>{" "}
 permanent te verwijderen, samen met alle antwoorden. Deze actie kan niet ongedaan
 gemaakt worden.
 </>
 ) : null}
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter>
 <AlertDialogCancel>Annuleer</AlertDialogCancel>
 <AlertDialogAction
 className="bg-red-600 text-white hover:bg-red-700"
 onClick={(e) => {
 e.preventDefault();
 if (confirmDelete) deleteIntake(confirmDelete);
 }}
 >
 Verwijder
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
 </div>
 );
}
