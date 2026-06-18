import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/intakes/new")({
  validateSearch: (s: Record<string, unknown>) => ({
    client_id: typeof s.client_id === "string" ? s.client_id : undefined,
  }),
  beforeLoad: ({ search }) => {
    throw redirect({
      to: "/admin/pulse/intakes/new",
      search: search as never,
    });
  },
});
