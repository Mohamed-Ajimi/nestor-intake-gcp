import { cn } from "@/lib/utils";

// frontend/src/components/intake/_status.tsx — shared intake-status display atoms.
//
// Extracted verbatim from admin.pulse.intakes.index.tsx so the admin list and the
// user-facing intake list render the SAME label copy + badge variants (single source
// of truth). The Dutch labels (Concept / Ingediend / Gereviewd / Gevalideerd /
// Gedecomposeerd) are pinned by 06-UI-SPEC — do NOT change them here.

/** Status code → Dutch display label. */
export const STATUS_LABEL: Record<string, string> = {
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

/** Status code → badge classes + optional leading mark. */
export const STATUS_VARIANT: Record<string, StatusVariant> = {
  draft: { cls: "badge-dashed" },
  submitted: { cls: "badge-ink" },
  reviewed: { cls: "badge-outline", mark: "green" },
  validated_by_client: { cls: "badge-ink", mark: "green" },
  decomposed: { cls: "badge-outline" },
  in_research: { cls: "badge-outline", mark: "green" },
  delivered: { cls: "badge-ink" },
  archived: { cls: "badge-outline text-ink/40 border-ink/40" },
};

export function StatusPill({ status }: { status: string | null }) {
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
