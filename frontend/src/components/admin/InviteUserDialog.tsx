import { useEffect, useState } from "react";
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

const inviteSchema = z.object({
  email: z.string().email("Ongeldig e-mailadres"),
  spaceId: z.string().min(1, "Kies een space"),
});

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
      setFieldError(parsed.error.issues[0]?.message ?? "Ongeldige invoer");
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
        setFieldError("Er bestaat al een account voor dit e-mailadres.");
      } else {
        setFieldError("Uitnodiging mislukt. Probeer opnieuw.");
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
      toast.success("Link gekopieerd");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Kopiëren mislukt");
    }
  }

  // Send the invitation mail (D-10) — regenerates a fresh action link server-side and mails
  // it. The membership id is resolved from the parent's reloaded user list (the invite
  // response only carries a uid). Copy-link stays as the fallback (D-04).
  async function handleSendMail() {
    const membershipId = resolveMembershipId?.(email.trim(), spaceId) ?? null;
    if (!membershipId) {
      toast.error(
        "Kon de gebruiker niet terugvinden — stuur de uitnodiging opnieuw vanuit de gebruikerslijst.",
      );
      return;
    }
    setSendingMail(true);
    const res = await sendInviteMail(membershipId);
    setSendingMail(false);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    setMailSent(true);
    toast.success("Uitnodigingsmail verstuurd");
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        {actionLink ? (
          // -------------------- Success state: copyable action link --------------------
          <>
            <DialogHeader>
              <DialogTitle className="font-serif text-2xl font-normal lowercase">
                Uitnodiging aangemaakt
              </DialogTitle>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <p className="text-sm text-ink/70">
                Verstuur de uitnodigingsmail, of bezorg de link handmatig aan de gebruiker.
              </p>
              <div className="grid gap-2">
                <input
                  readOnly
                  value={actionLink}
                  onFocus={(e) => e.currentTarget.select()}
                  className="w-full border border-ink bg-paperLight px-3 py-2 font-mono text-xs text-ink outline-none"
                />
                <div className="flex items-center justify-between gap-3">
                  <span className="badge-dashed">
                    {mailSent ? "MAIL VERSTUURD" : "MAIL OF HANDMATIG BEZORGEN"}
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
                        ? "Versturen…"
                        : mailSent
                          ? "Opnieuw versturen"
                          : "Verstuur uitnodigingsmail"}
                    </Button>
                    <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
                      {copied ? <Check /> : <Copy />}
                      Kopieer link
                    </Button>
                  </div>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>Sluiten</Button>
            </DialogFooter>
          </>
        ) : (
          // -------------------- Form state --------------------
          <form onSubmit={handleSubmit}>
            <DialogHeader>
              <DialogTitle className="font-serif text-2xl font-normal lowercase">
                gebruiker uitnodigen
              </DialogTitle>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <div className="grid gap-1.5">
                <Label
                  htmlFor="invite-email"
                  className="font-mono text-[11px] uppercase tracking-wider text-ink/70"
                >
                  E-mailadres
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
                  Space
                </Label>
                <Select value={spaceId} onValueChange={setSpaceId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Kies een space…" />
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
                Rol: gebruiker
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
                Annuleren
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "Aanmaken…" : "Uitnodiging aanmaken"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
