import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "@tanstack/react-router";
import { AlertTriangle, Download, Loader2, Lock, RotateCw, StopCircle } from "lucide-react";
import { toast } from "sonner";
import {
  cancelResearch,
  getBundleUrl,
  RESEARCH_TERMINAL,
  resumeResearch,
  reVerifyChain,
  triggerResearch,
  type ResearchRun,
} from "@/lib/api/research";
import { resolveErrorKey } from "@/lib/i18n/error-codes";
// The confirm gate reuses the SAME dialog affordance the research TRIGGER and the embedded
// card already use — the house pattern for a destructive or paid research action. No new
// dialog component is introduced and `components/ui/**` is not modified (CLAUDE.md).
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

// frontend/src/components/research/RunActions.tsx — the run page's action slot: exactly the
// affordances that are LEGAL for this run's status and chain verdict, and no others.
//
// This file is where three of the four affordances the design of record drops are carried
// over (D-10). Each of them prevents a specific, named harm, and each is written so the harm
// is impossible by construction rather than by anyone remembering:
//
// 1. THE CHAIN LOCK. Three chain states, not two. A VERIFIED chain gets the raw-output
//    affordance. A chain that FAILED to verify gets a locked panel with a re-check and NO
//    raw-output affordance ANYWHERE IN THAT BRANCH — not greyed out, not disabled, ABSENT.
//    A greyed-out control is not a lock; it is a lock with the key taped to it. Serving raw
//    output whose hash chain did not verify is the repudiation risk the whole chain guard
//    exists to prevent (T-15.3-100). A chain that was never checked gets a third panel that
//    says so and offers the check. All three are additionally gated on a success-terminal
//    status, mirroring the server's own `is_research_success(status) AND verified` gate — the
//    UI must never offer a click the seam will refuse.
//
//    The local chain override matters more here than on the embedded card: this page is
//    normally opened on an OLD run whose stream closed long ago, so a successful re-check
//    would never be pushed back. Without the override the panel would sit there claiming a
//    lock that has just been lifted.
//
// 2. RESUME, AND ONLY RESUME, ON A PAUSED RUN. A paused run continues from the checkpoints
//    the engine has ALREADY PAID FOR, for free. A fresh attempt throws every one of them away
//    and re-charges from zero. That is why the two carry different names in this file and why
//    the fresh-attempt affordance enumerates the three statuses it belongs to rather than
//    being offered by default (T-15.3-103).
//
// 3. STOP ASKS FIRST. The button opens a confirmation; the request is sent from the
//    confirmation's own action handler and from nowhere else (T-15.3-102). The copy states
//    what is true and irreversible: the cost incurred so far is not refunded, and the run
//    cannot be continued afterwards — only started again from the beginning.
//
// The fourth affordance, the audit-body drill-down, hangs off the feed rather than the card,
// so it is wired on the page itself.
//
// SECURITY (T-15.3-101 / D-08): every verb called here is superadmin-gated and space-scoped
// server-side, returning an existence-hiding 404 to anyone else. This component lives under
// `components/research/` and is imported only by the admin run page. No client-facing route
// imports it, and none may.
//
// RETURN-NO-THROW (CLAUDE.md): every failure path is a toast. Nothing here throws.

const PRIMARY_BTN =
  "inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-60";
const SECONDARY_BTN =
  "inline-flex items-center gap-2 border border-ink/40 px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-60";

export function RunActions({
  intakeId,
  run,
  onReload,
}: {
  intakeId: string;
  run: ResearchRun | null;
  onReload: () => void;
}): React.JSX.Element | null {
  const { t } = useTranslation("intake");
  const navigate = useNavigate();

  // ONE busy flag for every request this component can issue. The blocks below are mutually
  // exclusive by status — a run cannot be both live and finished — so no two of these controls
  // are ever on screen together, and a second flag would be a second name for one condition.
  const [busy, setBusy] = useState(false);
  // Open-state of the confirmation. Not a busy flag: it is the dialog's own visibility.
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Local chain override — see note 1 in the module comment.
  const [localChain, setLocalChain] = useState<"verified" | "broken" | null>(null);

  if (!run) return null;

  const status = run.status;
  const isTerminal = RESEARCH_TERMINAL.has(status) || status === "needs_input";
  const isSuccess = status === "completed" || status === "completed_degraded";
  const showResume = status === "parked";
  // The fresh-attempt affordance belongs to exactly these three states and is enumerated
  // rather than defaulted, so a status added later cannot silently inherit it.
  const showFreshAttempt =
    status === "failed" || status === "cancelled" || status === "needs_input";
  const chainStatus = localChain ?? run.chain_status;

  const fail = (res: { error: string; code?: string }, fallbackKey: string) => {
    const codeKey = resolveErrorKey(res.code);
    toast.error(codeKey ? t(codeKey) : res.error || t(fallbackKey));
  };

  const handleFetchBundle = async () => {
    if (busy) return;
    setBusy(true);
    const res = await getBundleUrl(intakeId, run.id);
    setBusy(false);
    if (res.success && res.data?.url) {
      // The signed URL carries an attachment disposition server-side, so the browser saves
      // the file rather than rendering it.
      window.location.href = res.data.url;
      return;
    }
    toast.error(t("research.downloadError"));
  };

  const handleReverify = async () => {
    if (busy) return;
    setBusy(true);
    const res = await reVerifyChain(intakeId, run.id);
    setBusy(false);
    if (!res.success) {
      toast.error(t("research.reverifyError"));
      return;
    }
    if (res.data?.chain_status !== "verified") {
      setLocalChain("broken");
      toast.error(t("research.reverifyStillBroken"));
      return;
    }
    setLocalChain("verified");
  };

  const handleResume = async () => {
    if (busy) return;
    setBusy(true);
    const res = await resumeResearch(intakeId);
    setBusy(false);
    if (!res.success) {
      fail(res, "research.actions.resumeError");
      return;
    }
    toast.success(t("research.actions.resumeOk"));
    // A checkpoint continuation re-queues the SAME run, so the page stays where it is and
    // simply re-opens its stream.
    onReload();
  };

  const handleStop = async () => {
    if (busy) return;
    setBusy(true);
    const res = await cancelResearch(intakeId);
    setBusy(false);
    if (!res.success) {
      fail(res, "research.cancelError");
      return;
    }
    toast.success(t("research.cancelOk"));
    onReload();
  };

  const handleFreshAttempt = async () => {
    if (busy) return;
    setBusy(true);
    // The three-attempt cap is enforced server-side, so the affordance is always offered and
    // an over-cap request comes back as a rejection, surfaced below as a toast.
    const res = await triggerResearch(intakeId);
    setBusy(false);
    if (!res.success) {
      fail(res, "research.actions.retryError");
      return;
    }
    toast.success(t("research.actions.retryOk"));
    const freshId = res.data?.research_run_id;
    if (freshId && freshId !== run.id) {
      // A new attempt is a NEW run with its own id and its own history. Staying on this URL
      // would leave the operator watching the old run's frozen feed while the new one runs.
      void navigate({ to: "/admin/pulse/runs/$runId", params: { runId: freshId } });
      return;
    }
    onReload();
  };

  return (
    <div className="w-full space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        {showResume && (
          <button type="button" disabled={busy} onClick={handleResume} className={PRIMARY_BTN}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {t("research.resume")}
          </button>
        )}

        {showFreshAttempt && (
          <button
            type="button"
            disabled={busy}
            onClick={handleFreshAttempt}
            className={PRIMARY_BTN}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}
            {t("research.retry")}
          </button>
        )}

        {!isTerminal && (
          // Secondary styling on purpose: stopping is a rare escape hatch, not the expected
          // next action, and it must not compete with anything that moves the run forward.
          // This handler opens the gate and does nothing else.
          <button
            type="button"
            disabled={busy}
            onClick={() => setConfirmOpen(true)}
            className={SECONDARY_BTN}
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <StopCircle className="h-4 w-4" />
            )}
            {busy ? t("research.cancelling") : t("research.cancel")}
          </button>
        )}
      </div>

      {/* THE CHAIN BLOCK — success-terminal runs only, mirroring the seam's own gate. */}
      {isSuccess && chainStatus === "broken" && (
        <div className="border-l-4 bg-paper px-4 py-3" style={{ borderLeftColor: "#DC2626" }}>
          <div className="mb-1 flex items-center gap-2">
            <Lock className="h-4 w-4 text-red-600" />
            <span
              className="font-mono text-[11px] uppercase tracking-wider"
              style={{ color: "#DC2626" }}
            >
              {t("research.lockedTitle")}
            </span>
          </div>
          <div className="mb-3 font-sans text-[14px] leading-relaxed text-ink">
            {t("research.lockedBody")}
          </div>
          <button type="button" disabled={busy} onClick={handleReverify} className={PRIMARY_BTN}>
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <AlertTriangle className="h-4 w-4" />
            )}
            {t("research.reverify")}
          </button>
        </div>
      )}

      {isSuccess && chainStatus === "verified" && (
        <div>
          <button type="button" disabled={busy} onClick={handleFetchBundle} className={PRIMARY_BTN}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {t("research.download")}
          </button>
        </div>
      )}

      {isSuccess && chainStatus == null && (
        // Never checked at all: a run recorded before the chain guard existed, or one whose
        // driver died before it could stamp a verdict. The same endpoint runs the gate and
        // stamps the result, after which this block resolves into one of the two above.
        <div className="border-l-4 bg-paper px-4 py-3" style={{ borderLeftColor: "#FF2D87" }}>
          <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-ink/70">
            {t("research.unverifiedTitle")}
          </div>
          <div className="mb-3 font-sans text-[14px] leading-relaxed text-ink">
            {t("research.unverifiedBody")}
          </div>
          <button type="button" disabled={busy} onClick={handleReverify} className={PRIMARY_BTN}>
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <AlertTriangle className="h-4 w-4" />
            )}
            {t("research.verifyChain")}
          </button>
        </div>
      )}

      {/* The confirm gate. The request is issued from the confirming action's handler and
          from nowhere else; dismissing sends nothing at all. */}
      {!isTerminal && (
        <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("research.cancelConfirmTitle")}</AlertDialogTitle>
              <AlertDialogDescription>{t("research.cancelConfirm")}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t("nextStep.researchConfirmCancel")}</AlertDialogCancel>
              <AlertDialogAction onClick={handleStop}>{t("research.cancel")}</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  );
}
