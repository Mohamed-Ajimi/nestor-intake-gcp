import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { ProductShell } from "@/components/admin/ProductShell";
import { ADMIN_NAV } from "@/components/admin/adminNav";
import { SpaceFormModal } from "@/components/admin/SpaceFormModal";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
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
import {
  deactivateSpace,
  listSpaces,
  reactivateSpace,
  type Space,
} from "@/lib/api/admin";

// Screen 3 — Space management (USER-03 / D-10). Create/edit name+slug, deactivate (with
// confirm) / reactivate. There is NO delete affordance anywhere — the only
// destructive-styled control is the reversible deactivate action.

export const Route = createFileRoute("/admin/spaces")({
  component: SpacesPage,
});

function SpacesPage() {
  const { t } = useTranslation("admin");
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Space | null>(null);
  const [confirmSpace, setConfirmSpace] = useState<Space | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    const res = await listSpaces();
    if (!res.success) {
      setError(res.error);
      setLoading(false);
      return;
    }
    setSpaces(res.data);
    setLoading(false);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      const res = await listSpaces();
      if (cancelled) return;
      if (!res.success) {
        setError(res.error);
        setLoading(false);
        return;
      }
      setSpaces(res.data);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(s: Space) {
    setEditing(s);
    setFormOpen(true);
  }

  async function handleReactivate(s: Space) {
    setBusyId(s.id);
    const res = await reactivateSpace(s.id);
    setBusyId(null);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    toast.success(t("spaces.toast.reactivated"));
    void load();
  }

  async function handleConfirmDeactivate() {
    if (!confirmSpace) return;
    const target = confirmSpace;
    setConfirmSpace(null);
    setBusyId(target.id);
    const res = await deactivateSpace(target.id);
    setBusyId(null);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    toast.success(t("spaces.toast.deactivated"));
    void load();
  }

  return (
    <ProductShell product="beheer" items={ADMIN_NAV}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
            spaces
          </h1>
          <p className="mt-1 font-sans text-sm italic text-ink/60">
            {t("spaces.subtitle")}
          </p>
        </div>
        <Button onClick={openCreate}>{t("spaces.new")}</Button>
      </div>

      <div className="mt-6">
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : error ? (
          <div className="py-12 text-center text-sm text-red-600">{error}</div>
        ) : spaces.length === 0 ? (
          <div className="mt-6 border border-ink/20 bg-paper2/40 p-12 text-center">
            <p className="mb-4 font-mono text-sm text-ink/60">⌀ {t("spaces.empty.title")}</p>
            <p className="mb-6 text-sm text-ink/50">
              {t("spaces.empty.body")}
            </p>
            <Button onClick={openCreate}>{t("spaces.new")}</Button>
          </div>
        ) : (
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-ink/30 font-mono text-[10px] uppercase tracking-wider text-ink/70">
                <th className="px-4 py-2 text-left">{t("spaces.table.name")}</th>
                <th className="px-4 py-2 text-left">{t("spaces.table.slug")}</th>
                <th className="px-4 py-2 text-left">{t("spaces.table.status")}</th>
                <th className="px-4 py-2 text-right">{t("spaces.table.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {spaces.map((s) => {
                const active = s.status === "active";
                return (
                  <tr key={s.id} className="border-b border-ink/10 hover:bg-ink/5">
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openEdit(s)}
                        className="text-left font-sans font-medium text-ink hover:underline"
                      >
                        {s.name}
                      </button>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-ink/70">{s.slug ?? "—"}</td>
                    <td className="px-4 py-3">
                      {active ? (
                        <span className="badge-outline">
                          <span className="mark-green" />
                          {t("spaces.status.active")}
                        </span>
                      ) : (
                        <span className="badge-dashed text-ink/50">
                          <span className="mark-outline" />
                          {t("spaces.status.deactivated")}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button variant="ghost" size="sm" onClick={() => openEdit(s)}>
                          {t("spaces.action.edit")}
                        </Button>
                        {active ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busyId === s.id}
                            onClick={() => setConfirmSpace(s)}
                          >
                            {t("spaces.action.deactivate")}
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busyId === s.id}
                            onClick={() => handleReactivate(s)}
                          >
                            {t("spaces.action.reactivate")}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <SpaceFormModal
        open={formOpen}
        onOpenChange={setFormOpen}
        initial={editing}
        onSaved={() => void load()}
      />

      <AlertDialog
        open={Boolean(confirmSpace)}
        onOpenChange={(o) => !o && setConfirmSpace(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("spaces.confirm.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("spaces.confirm.body")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("spaces.action.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDeactivate}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t("spaces.action.deactivate")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ProductShell>
  );
}
