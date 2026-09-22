import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Inbox, Loader2, Search } from "lucide-react";
import { toast } from "sonner";
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
import {
  deleteIntake,
  getIntakeDeletable,
  listIntakes,
  overrideIntakeStatus,
} from "@/lib/api/intakes";
import { listSpaces } from "@/lib/api/admin";
import { useActiveSpace } from "@/lib/active-space";
import {
  headerState,
  partitionForArchive,
  pruneSelection,
  toggleAllVisible,
  toggleSelected,
} from "@/lib/intake-bulk";

export const Route = createFileRoute("/admin/pulse/intakes/")({
 component: IntakesPage,
});

type IntakeRow = {
 id: string;
 status: string | null;
 client_name: string | null;
 space_name: string;
};

const STATUS_FILTER_VALUES = [
  "all",
  "draft",
  "submitted",
  "reviewed",
  "validated_by_client",
  "decomposed",
  "in_research",
  "delivered",
  "archived",
] as const;

function IntakesPage() {
 const { t } = useTranslation("admin");
 const navigate = useNavigate();
 const [intakes, setIntakes] = useState<IntakeRow[]>([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [statusFilter, setStatusFilter] = useState<string>("all");
 // 23.5-02 (remark 3): archived intakes leave the default list. Archive is what an
 // operator reaches for INSTEAD of deleting a researched intake, so archived rows
 // accumulate — they must be out of the way by default, and still reachable.
 const [showArchived, setShowArchived] = useState(false);
 const [search, setSearch] = useState("");
 // 23.5-08 (D-23.5-07): multi-select + the bulk Archive / Delete bar. The selection
 // algebra lives in @/lib/intake-bulk — the route has no component test harness in this
 // repo, so anything written inline here would be proven by tsc and nothing else.
 //
 // NO role check is added on this page. It already sits behind AdminLayout's superadmin
 // wall (routes/admin.tsx, useAuth().isSuperadmin) and all three endpoints re-derive
 // authority from the verified token server-side, per call. A fourth check here would be
 // UX gating that can drift out of step with the wall above it (plan 23.5-01's ruling).
 const [selected, setSelected] = useState<Set<string>>(new Set());
 const [bulkBusy, setBulkBusy] = useState(false);
 const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
 const [bulkConfirmText, setBulkConfirmText] = useState("");
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
  // Refetch when the superadmin switches active space — listIntakes threads the
  // selection via withActiveSpace at call time, so re-running the effect suffices.
 }, [activeSpaceId]);

 const filtered = useMemo(() => {
 const q = search.trim().toLowerCase();
 // An EXPLICIT status=archived selection shows archived rows regardless of the toggle.
 // Written as its own named condition rather than left as a side effect of the filter
 // order: an operator who clicked "archived" asked for archived intakes, and making
 // them also find the checkbox would be a filter that silently contradicts itself.
 const archivedExplicitlySelected = statusFilter === "archived";
 return intakes.filter((r) => {
 if (statusFilter !== "all" && (r.status ?? "") !== statusFilter) return false;
 if (
 r.status === "archived" &&
 !showArchived &&
 !archivedExplicitlySelected
 ) {
 return false;
 }
 if (q) {
 const hay = `${r.client_name ?? ""} ${r.space_name}`.toLowerCase();
 if (!hay.includes(q)) return false;
 }
 return true;
 });
 }, [intakes, statusFilter, showArchived, search]);

 // A row that has left the list — deleted, or dropped by a refetch — must not stay in the
 // count. Otherwise the bulk bar reads "3 selected" over two rows and the next batch
 // re-attempts an intake that is already gone. Prunes against the FULL list, never the
 // filtered one: a row hidden by a filter is still there and its selection still stands.
 useEffect(() => {
   setSelected((prev) => {
     const next = pruneSelection(prev, intakes.map((r) => r.id));
     return next.size === prev.size ? prev : next;
   });
 }, [intakes]);

 const visibleIds = useMemo(() => filtered.map((r) => r.id), [filtered]);
 const header = headerState(selected, visibleIds);
 const selectedRows = useMemo(
   () => intakes.filter((r) => selected.has(r.id)),
   [intakes, selected],
 );
 const confirmWord = t("intakeDetail.delete.confirmWord");

 const clearSelection = () => setSelected(new Set());

 // BULK ARCHIVE. Sequential (`for ... of` with `await`), never Promise.all: each call
 // writes an audit row server-side, so a parallel storm is a burst against the same
 // transaction path for no benefit on a hand-made selection.
 const runBulkArchive = async () => {
   const { toArchive } = partitionForArchive(intakes, selected);
   if (toArchive.length === 0) {
     toast.message(t("intakesList.bulk.archiveNone"));
     return;
   }
   setBulkBusy(true);
   let done = 0;
   let failed = 0;
   for (const id of toArchive) {
     const res = await overrideIntakeStatus(id, "archived");
     if (res.success) {
       done += 1;
       // The row flips in place and then leaves the default list through the existing
       // showArchived filter — the operator watches the batch drain.
       setIntakes((prev) =>
         prev.map((r) => (r.id === id ? { ...r, status: "archived" } : r)),
       );
     } else {
       failed += 1;
     }
   }
   setBulkBusy(false);
   clearSelection();
   toast.success(t("intakesList.bulk.archiveDone", { done, failed }));
 };

 // BULK DELETE. One typed confirmation covers the batch; the word is re-checked HERE as
 // well as on the button's disabled state, because a disabled attribute is an affordance
 // and not a guard, and this action has no undo.
 const runBulkDelete = async () => {
   if (bulkConfirmText.trim() !== confirmWord) return;
   const ids = intakes.filter((r) => selected.has(r.id)).map((r) => r.id);
   setBulkBusy(true);
   let done = 0;
   let blocked = 0;
   let failed = 0;
   for (const id of ids) {
     // The eligibility read FIRST, always. The backend re-checks and would 409 anyway,
     // but this read is what lets the summary separate "refused because research is in
     // flight" from "failed" — which is the entire point of reporting three counts.
     const eligible = await getIntakeDeletable(id);
     if (!eligible.success) {
       failed += 1;
       continue;
     }
     if (!eligible.data.deletable) {
       blocked += 1;
       continue;
     }
     const res = await deleteIntake(id);
     if (res.success) {
       done += 1;
       setIntakes((prev) => prev.filter((r) => r.id !== id));
     } else {
       failed += 1;
     }
   }
   setBulkBusy(false);
   setBulkDeleteOpen(false);
   setBulkConfirmText("");
   clearSelection();
   toast.success(t("intakesList.bulk.deleteDone", { done, blocked, failed }));
 };

 return (
 <div>
 <div className="flex flex-wrap items-start justify-between gap-4">
 <div>
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
            {t("intakesList.title")}
          </h1>
          <p className="mt-1 text-sm text-ink/60">
            {activeSpaceId
              ? t("intakesList.subtitleFiltered")
              : t("intakesList.subtitleAll")}
          </p>
        </div>
        <Button asChild>
          <Link to="/admin/pulse/intakes/new">{t("intakesList.newIntake")}</Link>
        </Button>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1 border border-ink p-1">
          {STATUS_FILTER_VALUES.map((value) => (
            <button
              key={value}
              onClick={() => setStatusFilter(value)}
              className={cn(
                "px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors",
                statusFilter === value
                  ? "bg-ink text-paper"
                  : "text-ink/60 hover:bg-ink/10",
              )}
            >
              {t(`intakesList.filter.${value}`)}
            </button>
          ))}
        </div>
        {/* 23.5-02 (remark 3): archived rows are hidden by default and come back here.
            Disabled while the status filter IS `archived`, because that selection
            already shows them and a toggle that looks live but changes nothing is
            worse than one that says why it is inert. */}
        <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-ink/60">
          <input
            type="checkbox"
            checked={showArchived || statusFilter === "archived"}
            disabled={statusFilter === "archived"}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="h-3.5 w-3.5 accent-ink"
          />
          {t("intakesList.showArchived")}
        </label>
        <div className="relative ml-auto w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("intakesList.searchPlaceholder")}
            className="h-9 pl-8"
          />
        </div>
      </div>

      {/* 23.5-08 (D-23.5-07): the bulk action bar. Rendered only when something is
          selected, so the default list is unchanged for an operator who never ticks a
          box. All three controls are disabled while a batch runs — a second click on
          Archive mid-batch would interleave two sequential loops over the same ids. */}
      {selected.size > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border border-ink bg-ink/5 px-4 py-3">
          <span className="font-mono text-[11px] uppercase tracking-wider text-ink">
            {t("intakesList.bulk.selected", { n: selected.size })}
          </span>
          <div className="ml-auto flex items-center gap-2">
            {bulkBusy && (
              <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-ink/60">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t("intakesList.bulk.working")}
              </span>
            )}
            <button
              type="button"
              onClick={runBulkArchive}
              disabled={bulkBusy}
              className="border border-ink bg-paper px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-ink hover:border-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t("intakesList.bulk.archive")}
            </button>
            <button
              type="button"
              onClick={() => {
                setBulkConfirmText("");
                setBulkDeleteOpen(true);
              }}
              disabled={bulkBusy}
              className="bg-red-700 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-paper hover:bg-red-800 disabled:cursor-not-allowed disabled:bg-ink/25"
            >
              {t("intakesList.bulk.delete")}
            </button>
            <button
              type="button"
              onClick={clearSelection}
              disabled={bulkBusy}
              className="px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-ink/60 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t("intakesList.bulk.clear")}
            </button>
          </div>
        </div>
      )}

      <div className="mt-6 border border-ink bg-paper">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent border-ink">
              {/* The select-all-VISIBLE header. `indeterminate` is set through a ref
                  callback because there is no React prop for it — and it matters: a
                  "some" state that renders identically to "none" invites a click that
                  selects rows the operator did not mean to, one button away from a
                  delete. The raw input matches the show-archived toggle above rather
                  than introducing the shadcn Checkbox, so the two controls on one screen
                  do not render in two different styles. */}
              <TableHead className="w-10 px-4">
                <input
                  type="checkbox"
                  aria-label={t("intakesList.bulk.selectAll")}
                  checked={header === "all"}
                  ref={(el) => {
                    if (el) el.indeterminate = header === "some";
                  }}
                  onChange={() => setSelected(toggleAllVisible(selected, visibleIds))}
                  className="h-3.5 w-3.5 accent-ink"
                />
              </TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">{t("intakesList.colClient")}</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">{t("intakesList.colName")}</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">{t("intakesList.colStatus")}</TableHead>
              <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink text-right">{t("intakesList.colActions")}</TableHead>
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
 <p className="mt-3 text-sm font-medium text-ink">{t("intakesList.emptyTitle")}</p>
 <p className="mt-1 text-sm text-ink/60">{t("intakesList.emptyBody")}</p>
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
              {/* stopPropagation is LOAD-BEARING: the row's own onClick navigates to the
                  detail page, so without it a tick becomes a navigation and the operator
                  never builds a selection at all. */}
              <TableCell className="w-10 px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  aria-label={t("intakesList.bulk.selectRow")}
                  checked={selected.has(r.id)}
                  onChange={() => setSelected(toggleSelected(selected, r.id))}
                  className="h-3.5 w-3.5 accent-ink"
                />
              </TableCell>
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
 {t("intakesList.open")}
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

      {/* 23.5-08 (D-23.5-07): ONE typed confirmation for the whole batch. Same
          hand-rolled overlay shape as the detail page's single delete — red border,
          role="alertdialog", the confirm button dead until the word matches, and the
          match re-checked inside the handler because a disabled attribute is an
          affordance, not a guard.

          The confirm WORD is read from intakeDetail.delete.confirmWord rather than
          copied into intakesList.bulk: it is one contract with the backend (the word,
          not its translation) and a second copy is exactly how the two dialogs would
          drift apart.

          The project NAMES are listed, not just the count. "delete 7 intakes" tells the
          operator how much they are destroying; the names tell them WHAT. */}
      {bulkDeleteOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
          onClick={() => !bulkBusy && setBulkDeleteOpen(false)}
        >
          <div
            role="alertdialog"
            className="w-full max-w-md border border-red-700 bg-paper p-6 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="font-serif text-2xl font-normal lowercase text-red-700">
              {t("intakesList.bulk.deleteTitle", { n: selected.size })}
            </h2>
            <p className="mt-3 font-sans text-sm leading-relaxed text-ink/70">
              {t("intakesList.bulk.deleteBody")}
            </p>
            <ul className="mt-4 max-h-40 overflow-y-auto border border-ink/20 px-3 py-2 font-mono text-[11px] text-ink/70">
              {selectedRows.map((r) => (
                <li key={r.id}>{r.client_name ?? "—"}</li>
              ))}
            </ul>
            <input
              type="text"
              value={bulkConfirmText}
              autoFocus
              onChange={(e) => setBulkConfirmText(e.target.value)}
              placeholder={t("intakeDetail.delete.confirmPlaceholder")}
              className="mt-4 w-full border border-ink bg-paper px-3 py-2 font-mono text-sm tracking-wider text-ink focus:outline-none"
            />
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setBulkDeleteOpen(false)}
                disabled={bulkBusy}
                className="border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {t("intakesList.bulk.cancel")}
              </button>
              <button
                type="button"
                onClick={runBulkDelete}
                disabled={bulkBusy || bulkConfirmText.trim() !== confirmWord}
                className="inline-flex items-center gap-1.5 bg-red-700 px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-red-800 disabled:cursor-not-allowed disabled:bg-ink/25"
              >
                {bulkBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {t("intakesList.bulk.delete")}
              </button>
            </div>
          </div>
        </div>
      )}
 </div>
 );
}
