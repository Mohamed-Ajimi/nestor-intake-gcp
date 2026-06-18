import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/intakes/$id")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/admin/pulse/intakes/$id",
      params: { id: (params as { id: string }).id },
    });
  },
});
