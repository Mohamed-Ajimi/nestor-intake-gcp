import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/organizations")({
  beforeLoad: () => {
    throw redirect({ to: "/admin" });
  },
});
