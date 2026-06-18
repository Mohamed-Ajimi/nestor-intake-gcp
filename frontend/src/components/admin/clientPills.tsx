import { cn } from "@/lib/utils";

export const STATUS_NL: Record<string, string> = {
  draft: "concept",
  submitted: "ingediend",
  reviewed: "gereviewd",
  validated_by_client: "gevalideerd",
  decomposed: "gedecomposeerd",
  in_research: "in onderzoek",
  delivered: "geleverd",
  archived: "gearchiveerd",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-ink/10 text-ink/70",
  submitted: "bg-amber-500/10 text-amber-700",
  reviewed: "bg-amber-500/10 text-amber-700",
  validated_by_client: "bg-lime-500/15 text-lime-700",
  decomposed: "bg-amber-500/10 text-amber-700",
  in_research: "bg-lime-500/15 text-lime-700",
  delivered: "bg-emerald-500/15 text-emerald-700",
  archived: "bg-ink/10 text-ink/50",
};

export function statusPillClass(status: string) {
  return cn(
    "inline-block whitespace-nowrap font-mono text-[10px] uppercase tracking-wider px-2 py-0.5",
    STATUS_COLORS[status] ?? "bg-ink/10 text-ink/70",
  );
}

const PRODUCT_COLORS: Record<string, string> = {
  pulse: "bg-ink/10 text-ink",
  sales: "bg-pink-500/10 text-pink-600",
  echo: "bg-blue-500/10 text-blue-600",
  edge: "bg-amber-500/10 text-amber-700",
  flux: "bg-purple-500/10 text-purple-600",
};

export function ProductPill({ slug, name }: { slug: string; name?: string }) {
  const cls = PRODUCT_COLORS[slug.toLowerCase()] ?? "bg-ink/10 text-ink";
  return (
    <span
      className={cn(
        "inline-block whitespace-nowrap font-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5",
        cls,
      )}
    >
      {name ?? slug}
    </span>
  );
}
