import { createFileRoute, Outlet } from "@tanstack/react-router";
import { ProductShell } from "@/components/admin/ProductShell";

export const Route = createFileRoute("/admin/pulse")({
  component: PulseLayout,
});

function PulseLayout() {
  return (
    <ProductShell
      product="pulse"
      items={[
        { to: "/admin/pulse/intakes/new", labelKey: "nav.pulseNewIntake", exact: true },
        { to: "/admin/pulse/intakes", labelKey: "nav.pulseIntakes", exact: false },
        { to: "/admin/pulse/clients", labelKey: "nav.pulseClients", exact: false },
        { to: "/admin/pulse/search", labelKey: "nav.pulseSearch", exact: true },
      ]}
    >
      <Outlet />
    </ProductShell>
  );
}
