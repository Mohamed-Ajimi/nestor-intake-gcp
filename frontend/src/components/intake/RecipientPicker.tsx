import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { listSpaceMembers, type IntakeMailType, type SpaceMember } from "@/lib/api/intakes";

// RecipientPicker — the one genuinely new UI element of Plan 10-04. A controlled shadcn
// Dialog that, on open, loads the intake's ACTIVE members (listSpaceMembers → GET
// /intakes/{id}/members) and renders each as a preselected checkbox row (D-07 — one click
// = legacy behavior). Confirm returns the selected MEMBERSHIP ids to the caller, which
// posts them to the send endpoint (sendIntakeMail).
//
// SECURITY (D-06 / T-10-11): there is NO free-text address field — the operator can only
// pick from server-provided membership rows; the backend re-validates every id.
//
// Analog: InviteUserDialog.tsx (shadcn Dialog + reset-on-open + sonner toasts).

export function RecipientPicker({
  open,
  onOpenChange,
  intakeId,
  type,
  busy = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  intakeId: string;
  type: IntakeMailType;
  busy?: boolean;
  onConfirm: (membershipIds: string[]) => void;
}) {
  const { t } = useTranslation("intake");
  // Title/CTA copy keyed on the mail type so one picker serves all four send verbs.
  const TYPE_COPY: Record<IntakeMailType, { title: string; confirm: string }> = {
    intake: {
      title: t("recipients.titleIntake"),
      confirm: t("recipients.confirmIntake"),
    },
    validation: {
      title: t("recipients.titleValidation"),
      confirm: t("recipients.confirmValidation"),
    },
    reminder: {
      title: t("recipients.titleReminder"),
      confirm: t("recipients.confirmReminder"),
    },
    results: {
      title: t("recipients.titleResults"),
      confirm: t("recipients.confirmResults"),
    },
  };
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<SpaceMember[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loadError, setLoadError] = useState<string | null>(null);

  // Load the intake's active members whenever the dialog (re)opens, preselecting all (D-07).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setMembers([]);
    setSelected(new Set());
    (async () => {
      const res = await listSpaceMembers(intakeId);
      if (cancelled) return;
      if (!res.success) {
        setLoadError(res.error);
        toast.error(t("recipients.loadFailed", { error: res.error }));
        setLoading(false);
        return;
      }
      setMembers(res.data);
      setSelected(new Set(res.data.map((m) => m.id))); // preselect all active members
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, intakeId, t]);

  const isEmpty = !loading && !loadError && members.length === 0;
  const copy = TYPE_COPY[type];

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleConfirm() {
    onConfirm(Array.from(selected));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle className="font-serif text-2xl font-normal lowercase">
            {copy.title}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <p className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
            {t("recipients.recipientsLabel")}
          </p>

          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : loadError ? (
            <p className="text-sm text-red-600">{t("recipients.loadError")}</p>
          ) : isEmpty ? (
            // D-07 empty guard — no active members, so nothing to send to.
            <div className="border border-dashed border-ink/30 bg-paper2/40 p-4 text-center">
              <p className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
                {t("recipients.noMembers")}
              </p>
              <p className="mt-1 text-sm text-ink/60">{t("recipients.inviteFirst")}</p>
            </div>
          ) : (
            <div className="grid gap-2">
              {members.map((m) => {
                // Backend filters email-less members out of the read (WR-02), so `email` is
                // always present here; the no-name fallback is a defensive last resort.
                // S1 (round-3, D2): show "Naam · email" inline; no duplicate email when
                // the member has no name (the email already IS the label then).
                return (
                  <label
                    key={m.id}
                    className="flex cursor-pointer items-center gap-3 border border-ink/20 bg-paper px-3 py-2 hover:bg-ink/5"
                  >
                    <Checkbox
                      checked={selected.has(m.id)}
                      onCheckedChange={() => toggle(m.id)}
                    />
                    <span className="font-sans text-sm text-ink">
                      {m.name ?? m.email ?? t("recipients.noName")}
                      {m.name && m.email && <span className="text-ink/50"> · {m.email}</span>}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            {t("recipients.cancel")}
          </Button>
          <div className="flex flex-col items-end gap-1">
            <Button
              type="button"
              onClick={handleConfirm}
              disabled={busy || loading || isEmpty || selected.size === 0}
            >
              {busy ? t("recipients.sending") : copy.confirm}
            </Button>
            {isEmpty && (
              <span className="font-mono text-[10px] normal-case tracking-normal text-ink/50">
                {t("recipients.inviteToSend")}
              </span>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
