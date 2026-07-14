import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ProductShell } from "@/components/admin/ProductShell";
import { ADMIN_NAV } from "@/components/admin/adminNav";
import { InviteUserDialog } from "@/components/admin/InviteUserDialog";
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
import { useAuth } from "@/lib/auth-context";
import {
  deactivateUser,
  listSpaces,
  listUsers,
  reactivateUser,
  sendInviteMail,
  type AdminUser,
  type Space,
} from "@/lib/api/admin";

// Screen 2 — User list + deactivate/reactivate (AUTH-04 / USER-03). All authorization is
// server-side; the role/space text here is display-only. The own-row and last-superadmin
// guardrails render Deactiveren DISABLED (default-deny surfaced as a disabled state),
// backed by the backend 409. There is NO delete affordance — only the reversible
// Deactiveren (D-10).

export const Route = createFileRoute("/admin/users")({
  component: UsersPage,
});

function UsersPage() {
  const { t } = useTranslation("admin");
  const { session } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [confirmUser, setConfirmUser] = useState<AdminUser | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    const [usersRes, spacesRes] = await Promise.all([listUsers(), listSpaces()]);
    if (!usersRes.success) {
      setError(usersRes.error);
      setLoading(false);
      return;
    }
    setUsers(usersRes.data);
    if (spacesRes.success) setSpaces(spacesRes.data);
    setLoading(false);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      const [usersRes, spacesRes] = await Promise.all([listUsers(), listSpaces()]);
      if (cancelled) return;
      if (!usersRes.success) {
        setError(usersRes.error);
        setLoading(false);
        return;
      }
      setUsers(usersRes.data);
      if (spacesRes.success) setSpaces(spacesRes.data);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const spaceName = useMemo(() => {
    const map = new Map(spaces.map((s) => [s.id, s.name]));
    return (id: string) => map.get(id) ?? id;
  }, [spaces]);

  // Count active superadmins for the last-superadmin guardrail (display-only; the backend
  // enforces the real 409).
  const activeSuperadminCount = useMemo(
    () => users.filter((u) => u.role === "superadmin" && u.status === "active").length,
    [users],
  );

  function guardrailFor(u: AdminUser): string | null {
    const isSelf = Boolean(session?.email && u.email && session.email === u.email);
    if (isSelf) return t("users.cannotDeactivateSelf");
    if (u.role === "superadmin" && u.status === "active" && activeSuperadminCount <= 1) {
      return t("users.cannotDeactivateLastSuperadmin");
    }
    return null;
  }

  async function handleReactivate(u: AdminUser) {
    setBusyId(u.id);
    const res = await reactivateUser(u.id);
    setBusyId(null);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    toast.success(t("users.reactivated"));
    void load();
  }

  // Resend the invitation mail for a member (D-10) — one endpoint serves this row action
  // and the InviteUserDialog success state. Regenerates a fresh action link server-side.
  async function handleResendInvite(u: AdminUser) {
    setBusyId(u.id);
    const res = await sendInviteMail(u.id);
    setBusyId(null);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    // WR-04 / D-16: HTTP 200 + `{ success: false }` on a Resend failure — check the
    // body-level flag, not just the transport-level `res.success`.
    if (!res.data.success) {
      toast.error(t("users.mailNotSent"));
      return;
    }
    toast.success(t("users.mailSent"));
  }

  // Resolve a membership id from the (freshly reloaded) user list so the InviteUserDialog
  // success state can send the invitation mail — the invite response carries a uid, not a
  // membership id (D-10). Matches on email + space; returns null if not yet visible.
  function resolveMembershipId(email: string, spaceId: string): string | null {
    const match = users.find(
      (u) => u.space_id === spaceId && (u.email ?? "").toLowerCase() === email.toLowerCase(),
    );
    return match?.id ?? null;
  }

  async function handleConfirmDeactivate() {
    if (!confirmUser) return;
    const target = confirmUser;
    setConfirmUser(null);
    setBusyId(target.id);
    const res = await deactivateUser(target.id);
    setBusyId(null);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    toast.success(t("users.deactivated"));
    void load();
  }

  return (
    <ProductShell product="beheer" items={ADMIN_NAV}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
            {t("users.title")}
          </h1>
          <p className="mt-1 font-sans text-sm italic text-ink/60">{t("users.subtitle")}</p>
        </div>
        <Button onClick={() => setInviteOpen(true)}>{t("users.inviteUser")}</Button>
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
        ) : users.length === 0 ? (
          <div className="mt-6 border border-ink/20 bg-paper2/40 p-12 text-center">
            <p className="mb-4 font-mono text-sm text-ink/60">{t("users.emptyTitle")}</p>
            <p className="mb-6 text-sm text-ink/50">{t("users.emptyBody")}</p>
            <Button onClick={() => setInviteOpen(true)}>{t("users.inviteUser")}</Button>
          </div>
        ) : (
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-ink/30 font-mono text-[10px] uppercase tracking-wider text-ink/70">
                <th className="px-4 py-2 text-left">{t("users.colEmail")}</th>
                <th className="px-4 py-2 text-left">{t("users.colSpace")}</th>
                <th className="px-4 py-2 text-left">{t("users.colStatus")}</th>
                <th className="px-4 py-2 text-right">{t("users.colActions")}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const active = u.status === "active";
                const guardrail = active ? guardrailFor(u) : null;
                return (
                  <tr key={u.id} className="border-b border-ink/10 hover:bg-ink/5">
                    <td className="px-4 py-3 font-sans text-sm font-medium text-ink">
                      {u.email ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-sm text-ink/80">{spaceName(u.space_id)}</td>
                    <td className="px-4 py-3">
                      {active ? (
                        <span className="badge-outline">
                          <span className="mark-green" />
                          {t("users.statusActive")}
                        </span>
                      ) : (
                        <span className="badge-dashed text-ink/50">
                          <span className="mark-outline" />
                          {t("users.statusDeactivated")}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {active ? (
                        <div className="flex flex-col items-end gap-1">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={busyId === u.id || !u.email}
                              onClick={() => handleResendInvite(u)}
                            >
                              {t("users.resendInvite")}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={Boolean(guardrail) || busyId === u.id}
                              onClick={() => setConfirmUser(u)}
                            >
                              {t("users.deactivate")}
                            </Button>
                          </div>
                          {guardrail && (
                            <span className="font-mono text-[10px] normal-case tracking-normal text-ink/50">
                              {guardrail}
                            </span>
                          )}
                        </div>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busyId === u.id}
                          onClick={() => handleReactivate(u)}
                        >
                          {t("users.reactivate")}
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <InviteUserDialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        spaces={spaces}
        onInvited={() => void load()}
        resolveMembershipId={resolveMembershipId}
      />

      <AlertDialog
        open={Boolean(confirmUser)}
        onOpenChange={(o) => !o && setConfirmUser(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("users.confirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("users.confirmBody")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("users.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDeactivate}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t("users.deactivate")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ProductShell>
  );
}
