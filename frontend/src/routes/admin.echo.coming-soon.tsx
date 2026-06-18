import { createFileRoute } from "@tanstack/react-router";
import { ComingSoonPage } from "@/components/admin/ComingSoonPage";

export const Route = createFileRoute("/admin/echo/coming-soon")({
  component: () => <ComingSoonPage product="echo" />,
});
