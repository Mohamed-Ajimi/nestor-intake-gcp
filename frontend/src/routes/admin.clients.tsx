import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/clients")({
  validateSearch: (s: Record<string, unknown>) => ({
    client: typeof s.client === "string" ? s.client : undefined,
  }),
  beforeLoad: ({ search }) => {
    throw redirect({ to: "/admin/pulse/clients", search: search as never });
  },
});
