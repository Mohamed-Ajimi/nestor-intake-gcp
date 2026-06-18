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
        { to: "/admin/pulse/intakes/new", label: "Nieuwe intake", exact: true },
        { to: "/admin/pulse/intakes", label: "Intakes", exact: false },
        { to: "/admin/pulse/clients", label: "Klanten", exact: false },
        { to: "/admin/pulse/search", label: "AI-zoek", exact: true },
      ]}
    >
      <Outlet />
    </ProductShell>
  );
}
