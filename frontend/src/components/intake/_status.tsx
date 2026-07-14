import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

// frontend/src/components/intake/_status.tsx — shared intake-status display atoms.
//
// Extracted verbatim from admin.pulse.intakes.index.tsx so the admin list and the
// user-facing intake list render the SAME label copy + badge variants (single source
// of truth). Labels live in the COMMON catalog (`common:status.*`, nl/fr/en at key
// parity, WR-04) so both the admin and the client-facing surfaces localize with the
// rest of the page; an unknown status code falls back to the raw code.

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
  const { t } = useTranslation("common");
  if (!status) {
    return <span className="badge-outline text-ink/40">—</span>;
  }
  const label = t(`status.${status}`, { defaultValue: status }).toUpperCase();
  const v = STATUS_VARIANT[status] ?? { cls: "badge-outline" };
  return (
    <span className={cn(v.cls)}>
      {v.mark === "green" && <span className="mark-green" />}
      {v.mark === "ink" && <span className="mark-ink" />}
      {label}
    </span>
  );
}
