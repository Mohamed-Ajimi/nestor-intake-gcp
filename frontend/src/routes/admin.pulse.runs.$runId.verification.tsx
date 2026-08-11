import { useEffect, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { ArrowLeft } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { getIntake } from "@/lib/api/intakes";
import { locateResearchRun } from "@/lib/api/research";
import { VerificationReport } from "@/components/intake/VerificationReport";

// frontend/src/routes/admin.pulse.runs.$runId.verification.tsx — the verification report as its
// own page (D-22-1). The operator's complaint was LENGTH, not discoverability: a document this
// long does not belong in a dropdown on the run page. So this route changes where the document
// lives and nothing about how it is reached.
//
// WHY THIS IS A LEAF SIBLING, NOT A CHILD. This file and `admin.pulse.runs.$runId.index.tsx` are
// siblings, and `admin.pulse.runs.$runId.tsx` deliberately DOES NOT EXIST. With that third file
// absent the generator registers BOTH of these under `AdminPulseRoute`, which already renders
// <ProductShell> around its own child slot — so neither page needs a child slot of its own.
// Recreate `admin.pulse.runs.$runId.tsx` and you promote the run page from a leaf to a layout
// route, at which point it renders only itself and this page silently becomes unreachable. This
// repo already carries a live scar from exactly that mistake at `routes/intake.$id.tsx:41-50`,
// where a child-render workaround had to be bolted on because child pages "could never render".
// The sibling naming is what makes that workaround unnecessary here. There is also an in-repo
// precedent: `admin.pulse.intakes.index.tsx` / `.new.tsx` / `.$id.tsx` all exist with no
// `admin.pulse.intakes.tsx`.
//
// WHY THE INTAKE ID IS RESOLVED, NEVER ACCEPTED (T-15.3-71 / TENANT-02). The page learns its
// intake ONLY from `locateResearchRun(runId)`. It takes no intake id from a query parameter: a
// bookmarked link will not have one, and a URL-supplied tenant hint is precisely the shape of
// input tenant isolation forbids. The cold open below is copied from the run page so the two
// cannot drift.
//
// SECURITY. Superadmin-only BY PLACEMENT under `admin.pulse`, which inherits the admin guard,
// and by API — every verb this page calls is superadmin-gated and space-scoped server-side and
// existence-hides as a 404. This route adds NO verb, NO parameter and NO new caller: it reuses
// the two reads the run page already made.
//
// WHY THIS PAGE DOES NOT RE-DERIVE THE RUN'S STATUS. The Phase 21 availability rule still
// governs whether the NAVIGATION to this page is offered, and that navigation lives on the run
// page, which holds the status and keeps the rule's single call site. This page deliberately has
// no second copy of it, for two reasons. First, `locateResearchRun` returns exactly two ids and
// no run state on purpose — a status here would be a second source of truth that can disagree
// with the run page's stream (D-05). Second, the only other way to learn a status would be to
// stream the intake's LATEST run, which for a historical run is a DIFFERENT run, so it would
// gate run X's report on run Y's state. A deep link to a run with no verdicts is therefore
// answered by the report's own data: the endpoint returns 200 with empty lists and the report
// renders its own empty state. That is honest and needs no gate.
//
// WHY THIS PAGE IS NOT SHAPED LIKE THE RUN PAGE. The run page is a fixed-height column with one
// internal scrolling region and a footer ticker. This page scrolls naturally in the document
// flow, like every other admin page: no nested scrolling region, no ticker, no stream, no feed.
// A document that scrolls with the page is what makes browser find-in-page, deep anchors and
// print work — all three of which a nested scrolling region breaks, and all three of which
// matter for a long report (22-UI-SPEC §1.2). It also declares no announcing region: the run
// page owns the product's single one (T-15.3-82) and a second would double-announce.

export const Route = createFileRoute("/admin/pulse/runs/$runId/verification")({
  component: VerificationReportPage,
});

function VerificationReportPage() {
  const { runId } = Route.useParams();
  const { t } = useTranslation("intake");

  // ── Cold open: resolve run → intake before anything else can be read. ───────────────
  const [intakeId, setIntakeId] = useState<string | null>(null);
  const [locating, setLocating] = useState(true);
  const [locateFailed, setLocateFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLocating(true);
    setLocateFailed(false);
    setIntakeId(null);
    void locateResearchRun(runId).then((res) => {
      if (cancelled) return;
      if (res.success && res.data?.intake_id) {
        setIntakeId(res.data.intake_id);
      } else {
        // A denial here is existence-hidden by design — the page cannot and must not
        // distinguish "no such run" from "not yours". One message covers both.
        setLocateFailed(true);
      }
      setLocating(false);
    });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // The client name for the header. Purely cosmetic — a failure leaves the crumb out and must
  // never block the report itself from rendering.
  const [clientName, setClientName] = useState<string | null>(null);
  useEffect(() => {
    if (!intakeId) return;
    let cancelled = false;
    void getIntake(intakeId).then((res) => {
      if (cancelled) return;
      if (res.success) setClientName(res.data?.client_name ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [intakeId]);

  if (locating) {
    return (
      <div>
        <Skeleton className="h-4 w-48" />
        <Skeleton className="mt-3 h-8 w-96" />
        <Skeleton className="mt-8 h-64 w-full" />
      </div>
    );
  }

  if (locateFailed || !intakeId) {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <p className="text-sm text-ink/60">{t("research.runPage.notFound")}</p>
        <Link
          to="/admin/pulse/intakes"
          className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-ink hover:underline"
        >
          <ArrowLeft className="h-4 w-4" />
          {t("research.runPage.backToIntakes")}
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl">
      {/* ── Header (22-UI-SPEC §1.5). Reuses the run page's structure verbatim so the two read
          as one product. The 4px left rule is the report's inherited identity mark, moved off
          the old inline container and onto the page header. */}
      <header className="border-l-4 pl-4" style={{ borderLeftColor: "#FF2D87" }}>
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink/50">
              <span>{t("research.runPage.breadcrumbProduct")}</span>
              <span className="px-1.5">·</span>
              <Link to="/admin/pulse/intakes" className="hover:text-ink">
                {t("research.runPage.breadcrumbIntakes")}
              </Link>
              {clientName && (
                <>
                  <span className="px-1.5">·</span>
                  <Link
                    to="/admin/pulse/intakes/$id"
                    params={{ id: intakeId }}
                    className="hover:text-ink"
                  >
                    {clientName}
                  </Link>
                </>
              )}
              <span className="px-1.5">·</span>
              <Link to="/admin/pulse/runs/$runId" params={{ runId }} className="hover:text-ink">
                {t("research.runPage.breadcrumbRun")}
              </Link>
              <span className="px-1.5">·</span>
              {/* The current crumb: present so the trail is complete, unlinked because it is
                  where the operator already is. */}
              <span>{t("verification.title")}</span>
            </div>

            <h1 className="mt-1 font-serif text-xl font-semibold leading-tight text-ink">
              {t("verification.title")}
            </h1>

            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-ink/50">
              <span>{t("research.runPage.metaRun", { id: runId.slice(0, 8) })}</span>
              {clientName && <span>{clientName}</span>}
            </div>
          </div>

          <Link
            to="/admin/pulse/runs/$runId"
            params={{ runId }}
            className="inline-flex shrink-0 items-center gap-2 border border-ink/30 px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t("verification.backToRun")}
          </Link>
        </div>
      </header>

      {/* The report owns its own loading, error and empty states. Between this plan and 22-07 it
          still renders its own bordered container and title beneath this header; that duplication
          is expected and 22-07 removes it. */}
      <div className="mt-8">
        <VerificationReport intakeId={intakeId} runId={runId} />
      </div>
    </div>
  );
}
