// Shared sidebar nav items.
// - PULSE_NAV: the primary Pulse nav (new intake / intakes / clients / search). Used by the
//   Pulse layout AND by the management screens (users / spaces) since quick 261006-jgn, so
//   an admin on a manage page can always get back to the intakes.
// - ADMIN_NAV: the superadmin management links (users / spaces), rendered by ProductShell's
//   "Manage" block below the primary nav. PULSE_NAV and ADMIN_NAV share no `to`, so no link
//   renders twice.
// Labels are i18n keys (admin namespace) resolved via t(item.labelKey) in ProductShell.
// Keep ADMIN_NAV a SINGLE exported const — ProductShell's `items !== ADMIN_NAV` guard relies
// on reference equality (it still protects any caller that passes ADMIN_NAV as `items`).

export type AdminNavItem = { to: string; labelKey: string; exact: boolean };

export const ADMIN_NAV: AdminNavItem[] = [
  { to: "/admin/users", labelKey: "nav.manageUsers", exact: false },
  { to: "/admin/spaces", labelKey: "nav.manageSpaces", exact: false },
];

export const PULSE_NAV: AdminNavItem[] = [
  { to: "/admin/pulse/intakes/new", labelKey: "nav.pulseNewIntake", exact: true },
  { to: "/admin/pulse/intakes", labelKey: "nav.pulseIntakes", exact: false },
  { to: "/admin/pulse/clients", labelKey: "nav.pulseClients", exact: false },
  { to: "/admin/pulse/search", labelKey: "nav.pulseSearch", exact: true },
];
