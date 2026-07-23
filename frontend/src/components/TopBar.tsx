import { Bell } from "lucide-react";
import { useTranslation } from "react-i18next";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

// frontend/src/components/TopBar.tsx
// Thin sticky bar mounted at the top of the main content area (right of the sidebar
// in ProductShell; full-width on intake pages). Contains:
//   - compact language switcher (shows "NL" / "FR" / "EN")
//   - notification bell — UI placeholder only; backend not yet implemented.
//
// NOTE FOR CLAUDE CODE: the notification bell is intentionally disabled/greyed.
// Wire it up once the notifications API exists (GET /me/notifications or similar).
// The badge count should come from that endpoint.

interface TopBarProps {
  /** Pass persist=false on pre-login pages (login page). Default: true. */
  persist?: boolean;
}

export function TopBar({ persist = true }: TopBarProps) {
  const { t } = useTranslation("common");
  return (
    <div className="flex h-11 shrink-0 items-center justify-end gap-1 border-b border-ink/10 bg-paper px-6">
      {/* Compact language code button — "NL" / "FR" / "EN" */}
      <LanguageSwitcher persist={persist} compact />

      {/* Notification bell — placeholder; backend not implemented yet.
          Remove `disabled` and `title` once the notifications API is wired. */}
      <button
        type="button"
        disabled
        title={t("notifications.comingSoon")}
        aria-label={t("notifications.ariaLabel")}
        className="relative flex h-7 w-7 items-center justify-center text-ink/30 transition-colors"
      >
        <Bell className="h-4 w-4" />
        {/* Uncomment + populate from API once backend is ready:
        {unreadCount > 0 && (
          <span className="absolute right-0.5 top-0.5 flex h-3.5 w-3.5 items-center justify-center
                           rounded-full bg-ink font-mono text-[8px] text-paper">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )} */}
      </button>
    </div>
  );
}
