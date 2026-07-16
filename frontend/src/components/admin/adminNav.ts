// Shared superadmin nav items for the management screens (users / spaces / templates).
// Used both by the ProductShell sidebar section and as the `items` for the management
// routes' shell so the three screens are mutually reachable.
// Labels are i18n keys (admin namespace) resolved via t(item.labelKey) in ProductShell.
// Keep this a SINGLE exported const — ProductShell's `items !== ADMIN_NAV` guard and the
// three Beheer routes rely on reference equality.

export type AdminNavItem = { to: string; labelKey: string; exact: boolean };

export const ADMIN_NAV: AdminNavItem[] = [
  { to: "/admin/users", labelKey: "nav.manageUsers", exact: false },
  { to: "/admin/spaces", labelKey: "nav.manageSpaces", exact: false },
  { to: "/admin/templates", labelKey: "nav.manageTemplates", exact: false },
];
