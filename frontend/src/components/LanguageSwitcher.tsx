import { useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { patchLocale, type SupportedLocale } from "@/lib/api/me";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { cn } from "@/lib/utils";

// frontend/src/components/LanguageSwitcher.tsx — the NL/FR/EN switcher (Phase 11, D-08).
// Composed from the same shadcn primitives as SpaceSwitcher (NOT in ui/ — that
// directory is generated). Selecting a language flips the UI instantly via
// i18n.changeLanguage; persistence depends on the mount context:
//
// - persist=true (default, post-login mounts): best-effort `PATCH /me/locale` —
//   failure is IGNORED (D-10 auto-persist; the UI already flipped, return-no-throw).
// - persist=false (pre-login mount, 11-06 login page): no session exists yet, so the
//   choice is written to localStorage for post-login reconciliation (D-09).
//
// Mount points land in 11-03/04/06 — this plan only provides the component.

/** localStorage key for the pre-login language choice (read back at post-login boot, 11-06). */
export const LOCALE_STORAGE_KEY = "nestor.preferredLocale";

const OPTIONS: SupportedLocale[] = ["nl", "fr", "en"];

// Mirrors SpaceSwitcher's TRIGGER_CLASS mono/uppercase chrome.
const TRIGGER_CLASS =
  "flex w-full items-center justify-between gap-2 border border-ink bg-paper px-3 py-2 " +
  "font-mono text-xs uppercase tracking-wider text-ink";

function rememberPreLoginChoice(lang: SupportedLocale) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, lang);
  } catch {
    /* ignore — persistence is best-effort UX state */
  }
}

export function LanguageSwitcher({ persist = true }: { persist?: boolean }) {
  const [open, setOpen] = useState(false);
  const { t, i18n } = useTranslation("common");

  const active = (i18n.resolvedLanguage ?? i18n.language ?? "nl").slice(0, 2);
  const current: SupportedLocale = active === "fr" || active === "en" ? active : "nl";

  function handleSelect(lang: SupportedLocale) {
    // Instant UI flip first — persistence is async and best-effort.
    void i18n.changeLanguage(lang);
    if (persist) {
      // D-10 auto-persist: ignore failure — the flip already happened, no toast.
      void patchLocale(lang);
    } else {
      // Pre-login: no session to PATCH against — remember for post-login reconcile.
      rememberPreLoginChoice(lang);
    }
    setOpen(false);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-label={t("language.label")}
          className={TRIGGER_CLASS}
        >
          <span className="truncate">{t(`language.${current}`)}</span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
        <Command>
          <CommandList>
            <CommandGroup>
              {OPTIONS.map((lang) => (
                <CommandItem key={lang} value={lang} onSelect={() => handleSelect(lang)}>
                  <Check
                    className={cn("h-4 w-4", current === lang ? "opacity-100" : "opacity-0")}
                  />
                  {t(`language.${lang}`)}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
