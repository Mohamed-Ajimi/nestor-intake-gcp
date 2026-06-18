import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/sales/")({
  beforeLoad: () => {
    throw redirect({ to: "/admin/sales/projects" });
  },
});
