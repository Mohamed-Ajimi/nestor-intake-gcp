import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Check, Copy } from "lucide-react";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Mail } from "lucide-react";
import { inviteUser, sendInviteMail, type Space } from "@/lib/api/admin";

// Screen 1 — Invite user (USER-01 / D-01 / D-02 / D-03). The role is server-fixed to
// "user" and shown read-only (D-01a) — there is NO role control. On success the dialog
// renders the one-time action link in a copyable monospace field AND a "send invitation
// mail" action (D-10) — the copy-link fallback stays (D-04); the link is never persisted
// client-side (T-5-19).

export function InviteUserDialog({
  open,
  onOpenChange,
  spaces,
  onInvited,
  resolveMembershipId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  spaces: Space[];
  onInvited?: () => void;
  // Resolve the just-invited user's MEMBERSHIP id (the invite response only carries a uid).
  // Backed by the parent's freshly-reloaded user list; returns null until the row is visible.
  resolveMembershipId?: (email: string, spaceId: string) => string | null;
}) {
  const { t } = useTranslation("admin");
  const inviteSchema = z.object({
    email: z.string().email(t("invite.invalidEmail")),
    spaceId: z.string().min(1, t("invite.chooseSpace")),
  });
  const [email, setEmail] = useState("");
  const [spaceId, setSpaceId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [actionLink, setActionLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [sendingMail, setSendingMail] = useState(false);
  const [mailSent, setMailSent] = useState(false);

  // Reset all state whenever the dialog (re)opens.
  useEffect(() => {
    if (open) {
      setEmail("");
      setSpaceId("");
      setSubmitting(false);
      setFieldError(null);
      setActionLink(null);
      setCopied(false);
      setSendingMail(false);
      setMailSent(false);
    }
  }, [open]);

  const activeSpaces = spaces.filter((s) => s.status === "active");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFieldError(null);

    const parsed = inviteSchema.safeParse({ email: email.trim(), spaceId });
    if (!parsed.success) {
      setFieldError(parsed.error.issues[0]?.message ?? t("invite.invalidInput"));
      return;
    }

    setSubmitting(true);
    const result = await inviteUser({ email: parsed.data.email, spaceId: parsed.data.spaceId });
    setSubmitting(false);

    if (!result.success) {
      // Map the backend 409 duplicate-account case to the documented copy; otherwise
      // surface the backend detail in a toast + a generic inline message.
      const isDuplicate = /409|bestaat al|already exists/i.test(result.error);
      if (isDuplicate) {
        setFieldError(t("invite.duplicateAccount"));
      } else {
        setFieldError(t("invite.inviteFailed"));
        toast.error(result.error);
      }
      return;
    }

    setActionLink(result.data.action_link);
    onInvited?.();
  }

  async function handleCopy() {
    if (!actionLink) return;
    try {
      await navigator.clipboard.writeText(actionLink);
      setCopied(true);
      toast.success(t("invite.linkCopied"));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("invite.copyFailed"));
    }
  }

  // Send the invitation mail (D-10) — regenerates a fresh action link server-side and mails
  // it. The membership id is resolved from the parent's reloaded user list (the invite
  // response only carries a uid). Copy-link stays as the fallback (D-04).
  async function handleSendMail() {
    const membershipId = resolveMembershipId?.(email.trim(), spaceId) ?? null;
    if (!membershipId) {
      toast.error(t("invite.resolveFailed"));
      return;
    }
    setSendingMail(true);
    const res = await sendInviteMail(membershipId);
    setSendingMail(false);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    // WR-04 / D-16: the backend returns HTTP 200 + `{ success: false }` on a Resend
    // transport failure (or missing RESEND_API_KEY). `res.success` is only the transport
    // flag — inspect the body-level flag so a failed send doesn't toast success.
    if (!res.data.success) {
      toast.error(t("invite.mailNotSent"));
      return;
    }
    setMailSent(true);
    toast.success(t("invite.mailSent"));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        {actionLink ? (
          // -------------------- Success state: copyable action link --------------------
          <>
            <DialogHeader>
              <DialogTitle className="font-serif text-2xl font-normal lowercase">
                {t("invite.createdTitle")}
              </DialogTitle>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <p className="text-sm text-ink/70">{t("invite.createdBody")}</p>
              <div className="grid gap-2">
                <input
                  readOnly
                  value={actionLink}
                  onFocus={(e) => e.currentTarget.select()}
                  className="w-full border border-ink bg-paperLight px-3 py-2 font-mono text-xs text-ink outline-none"
                />
                <div className="flex items-center justify-between gap-3">
                  <span className="badge-dashed">
                    {mailSent ? t("invite.badgeMailSent") : t("invite.badgeDeliverManual")}
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={handleSendMail}
                      disabled={sendingMail}
                    >
                      <Mail />
                      {sendingMail
                        ? t("invite.sending")
                        : mailSent
                          ? t("invite.resend")
                          : t("invite.sendMail")}
                    </Button>
                    <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
                      {copied ? <Check /> : <Copy />}
                      {t("invite.copyLink")}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>{t("invite.close")}</Button>
            </DialogFooter>
          </>
        ) : (
          // -------------------- Form state --------------------
          <form onSubmit={handleSubmit}>
            <DialogHeader>
              <DialogTitle className="font-serif text-2xl font-normal lowercase">
                {t("invite.formTitle")}
              </DialogTitle>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <div className="grid gap-1.5">
                <Label
                  htmlFor="invite-email"
                  className="font-mono text-[11px] uppercase tracking-wider text-ink/70"
                >
                  {t("invite.emailLabel")}
                </Label>
                <Input
                  id="invite-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoFocus
                />
              </div>

              <div className="grid gap-1.5">
                <Label className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
                  {t("invite.spaceLabel")}
                </Label>
                <Select value={spaceId} onValueChange={setSpaceId}>
                  <SelectTrigger>
                    <SelectValue placeholder={t("invite.spacePlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {activeSpaces.map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Role is server-fixed to "user" and rendered read-only (D-01a) — NOT a control. */}
              <p className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
                {t("invite.roleFixed")}
              </p>

              {fieldError && <p className="text-sm text-red-600">{fieldError}</p>}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={submitting}
              >
                {t("invite.cancel")}
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? t("invite.creating") : t("invite.createInvite")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
