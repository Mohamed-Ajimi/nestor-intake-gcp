import { cn } from "@/lib/utils";

export type ProductKey = "pulse" | "sales" | "echo" | "flux" | "consumer";

const STYLES: Record<ProductKey, string> = {
  pulse: "bg-ink/10 text-ink",
  sales: "bg-pink-500/10 text-pink-600",
  echo: "bg-blue-500/10 text-blue-600",
  flux: "bg-purple-500/10 text-purple-600",
  consumer: "bg-amber-500/10 text-amber-700",
};

const MUTED: Record<ProductKey, string> = {
  pulse: "bg-ink/5 text-ink/30",
  sales: "bg-pink-500/5 text-pink-500/40",
  echo: "bg-blue-500/5 text-blue-500/40",
  flux: "bg-purple-500/5 text-purple-500/40",
  consumer: "bg-amber-500/5 text-amber-600/40",
};

export function ProductBadge({
  product,
  muted = false,
  className,
}: {
  product: ProductKey;
  muted?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-[0.12em]",
        muted ? MUTED[product] : STYLES[product],
        className,
      )}
    >
      {product}
    </span>
  );
}
