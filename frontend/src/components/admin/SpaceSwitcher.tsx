import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown } from "lucide-react";
import { toast } from "sonner";
import { listSpaces, type Space } from "@/lib/api/admin";
import { useActiveSpace } from "@/lib/active-space";
import { Skeleton } from "@/components/ui/skeleton";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";

// frontend/src/components/admin/SpaceSwitcher.tsx — the single global "active space"
// view-filter (D-04 / TENANT-04). Superadmin-only: ProductShell mounts this ONLY inside
// its `isSuperadmin` gate, so a `user` role never renders it (T-06-21).
//
// SECURITY: the selected space_id is UX STATE, never an authorization input. Selecting a
// space writes the ActiveSpaceProvider (which persists to localStorage `nestor.activeSpaceId`
// and syncs the non-hook `withActiveSpace` accessor read by the transport), then invalidates
// every query so each list re-reads with the new `?space_id`. The backend re-derives a user's
// space from the verified token and ignores the param, so it can never widen access (T-06-22).

const TRIGGER_CLASS =
  "flex w-full items-center justify-between gap-2 border border-ink bg-paper px-3 py-2 " +
  "font-mono text-xs uppercase tracking-wider text-ink";

export function SpaceSwitcher() {
  const { t } = useTranslation("admin");
  const [open, setOpen] = useState(false);
  const { activeSpaceId, setActiveSpace } = useActiveSpace();
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "spaces"],
    queryFn: async (): Promise<Space[]> => {
      const res = await listSpaces();
      if (!res.success) throw new Error(res.error);
      return res.data;
    },
  });

  // Surface a single toast when the spaces list fails to load (matches the
  // return-no-throw toast convention used across the admin routes).
  useEffect(() => {
    if (isError) toast.error(t("spaceSwitcher.loadFailed"));
  }, [isError, t]);

  // Apply a selection: UX state only — persist + sync accessor (via the provider) and
  // invalidate every query so lists re-read with the new `?space_id`. Never navigate.
  function handleSelect(id: string | null) {
    setActiveSpace(id);
    void queryClient.invalidateQueries();
    setOpen(false);
  }

  // ----- Eyebrow + non-interactive states ---------------------------------
  const eyebrow = (
    <p className="label-mono text-ink/40">{t("spaceSwitcher.eyebrow")}</p>
  );

  if (isLoading) {
    return (
      <div className="flex flex-col gap-1">
        {eyebrow}
        <Skeleton className="h-9 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col gap-1">
        {eyebrow}
        <button type="button" disabled className={cn(TRIGGER_CLASS, "cursor-not-allowed opacity-60")}>
          <span className="truncate">{t("spaceSwitcher.loadFailed")}</span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </button>
      </div>
    );
  }

  const spaces = data ?? [];

  if (spaces.length === 0) {
    return (
      <div className="flex flex-col gap-1">
        {eyebrow}
        <button type="button" disabled className={cn(TRIGGER_CLASS, "cursor-not-allowed opacity-60")}>
          <span className="truncate">{t("spaceSwitcher.empty")}</span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </button>
      </div>
    );
  }

  const selected = activeSpaceId ? spaces.find((s) => s.id === activeSpaceId) : null;
  const label = selected ? selected.name : t("spaceSwitcher.allClients");

  return (
    <div className="flex flex-col gap-1">
      {eyebrow}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            role="combobox"
            aria-expanded={open}
            className={TRIGGER_CLASS}
          >
            <span className="truncate">{label}</span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command>
            <CommandInput placeholder={t("spaceSwitcher.searchPlaceholder")} />
            <CommandList>
              <CommandEmpty>{t("spaceSwitcher.noneFound")}</CommandEmpty>
              <CommandGroup>
                <CommandItem value="__all__" onSelect={() => handleSelect(null)}>
                  <Check
                    className={cn("h-4 w-4", activeSpaceId === null ? "opacity-100" : "opacity-0")}
                  />
                  {t("spaceSwitcher.allClients")}
                </CommandItem>
                {spaces.map((space) => (
                  <CommandItem
                    key={space.id}
                    value={space.name}
                    onSelect={() => handleSelect(space.id)}
                  >
                    <Check
                      className={cn(
                        "h-4 w-4",
                        activeSpaceId === space.id ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span className="truncate">{space.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
