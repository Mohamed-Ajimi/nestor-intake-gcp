import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/pulse/")({
  beforeLoad: () => {
    throw redirect({ to: "/admin/pulse/intakes" });
  },
});
