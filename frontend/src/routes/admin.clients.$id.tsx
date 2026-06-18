import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/clients/$id")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/admin/pulse/clients/$id",
      params: { id: (params as { id: string }).id },
    });
  },
});
