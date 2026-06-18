import { cn } from "@/lib/utils";

type Props = {
 status: string | null;
 clientValidatedAt?: string | null;
 submittedAt?: string | null;
 className?: string;
};

const STEPS = [
 { key: "submitted", label: "Klant ingediend" },
 { key: "reviewed", label: "Door jou gereviewd" },
 { key: "validated_by_client", label: "Klant gevalideerd" },
 { key: "decomposed", label: "Decompositie" },
 { key: "in_research", label: "In onderzoek" },
 { key: "delivered", label: "Geleverd" },
] as const;

const ORDER = ["submitted", "reviewed", "validated_by_client", "decomposed", "in_research", "delivered"];

function currentIndex(status: string | null): number {
 if (!status || status === "draft" || status === "archived") return -1;
 const i = ORDER.indexOf(status);
 return i;
}

function fmtShort(d: string | null | undefined) {
 if (!d) return null;
 try {
 return new Date(d).toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
 } catch {
 return null;
 }
}

export function IntakeWorkflowStepper({ status, clientValidatedAt, submittedAt, className }: Props) {
 const cur = currentIndex(status);
 const isDelivered = status === "delivered";
 const isArchived = status === "archived";
 const isDraft = status === "draft" || !status;

 const stamps: Record<number, string | null> = {
 0: fmtShort(submittedAt ?? null),
 2: fmtShort(clientValidatedAt ?? null),
 };

 return (
 <div className={cn("w-full", className)}>
 {isArchived && (
 <div className="mb-3 border border-ink/10 bg-paper2 px-3 py-2 text-xs text-ink/60">
 Deze intake is gearchiveerd.
 </div>
 )}

 <ol className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-0">
 {STEPS.map((step, i) => {
 const isPast = cur > i || isDelivered;
 const isCurrent = !isDelivered && cur === i;
 const isFuture = !isPast && !isCurrent;
 const stamp = stamps[i];

 return (
 <li
 key={step.key}
 className="flex flex-1 items-start gap-3 sm:flex-col sm:items-center sm:gap-0"
 >
 <div className="flex w-full items-center sm:flex-col">
 <div className="hidden flex-1 sm:block">
 {i > 0 && (
 <div
 className={cn(
 "h-px w-full",
 cur > i - 1 || isDelivered
 ? "bg-ink"
 : "border-t border-dashed border-ink/10 bg-transparent",
 )}
 />
 )}
 </div>

                <div
                  className={cn(
                    "relative flex h-3 w-3 shrink-0 items-center justify-center transition-colors",
                    isPast && "bg-ink",
                    isCurrent && "bg-agenic-green border border-ink",
                    isFuture && "border border-ink bg-transparent",
                  )}
                  aria-current={isCurrent ? "step" : undefined}
                />

 <div className="hidden flex-1 sm:block">
 {i < STEPS.length - 1 && (
 <div
 className={cn(
 "h-px w-full",
 cur > i || isDelivered
 ? "bg-ink"
 : "border-t border-dashed border-ink/10 bg-transparent",
 )}
 />
 )}
 </div>
 </div>

              <div className="min-w-0 sm:mt-2 sm:px-1 sm:text-center">
                <p
                  className={cn(
                    "font-mono text-[10px] uppercase tracking-wider leading-tight",
                    isCurrent && "text-ink",
                    isPast && "text-ink/70",
                    isFuture && "text-ink/40",
                  )}
                >
                  {step.label}
                </p>
                {stamp && (isPast || isCurrent) && (
                  <p className="mt-0.5 font-mono text-[10px] text-ink/40">{stamp}</p>
                )}
              </div>
 </li>
 );
 })}
 </ol>

 {isDraft && (
 <p className="mt-3 text-xs text-ink/60">Klant is nog aan het invullen.</p>
 )}
 </div>
 );
}
