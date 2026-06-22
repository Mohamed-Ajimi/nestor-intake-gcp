// Shared superadmin nav items for the management screens (gebruikers / spaces / templates).
// Used both by the ProductShell sidebar section and as the `items` for the management
// routes' shell so the three screens are mutually reachable.

export type AdminNavItem = { to: string; label: string; exact: boolean };

export const ADMIN_NAV: AdminNavItem[] = [
  { to: "/admin/users", label: "gebruikers", exact: false },
  { to: "/admin/spaces", label: "spaces", exact: false },
  { to: "/admin/templates", label: "templates", exact: false },
];
