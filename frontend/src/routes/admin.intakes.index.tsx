import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/intakes/")({
  beforeLoad: () => {
    throw redirect({ to: "/admin/pulse/intakes" });
  },
});
