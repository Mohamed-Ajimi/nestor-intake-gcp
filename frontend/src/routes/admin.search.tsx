import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/search")({
  beforeLoad: () => {
    throw redirect({ to: "/admin/pulse/search" });
  },
});
