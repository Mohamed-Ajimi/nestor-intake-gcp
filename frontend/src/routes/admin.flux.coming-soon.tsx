import { createFileRoute } from "@tanstack/react-router";
import { ComingSoonPage } from "@/components/admin/ComingSoonPage";

export const Route = createFileRoute("/admin/flux/coming-soon")({
  component: () => <ComingSoonPage product="flux" />,
});
