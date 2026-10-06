import { createFileRoute, Outlet } from "@tanstack/react-router";
import { ProductShell } from "@/components/admin/ProductShell";
import { PULSE_NAV } from "@/components/admin/adminNav";

export const Route = createFileRoute("/admin/pulse")({
  component: PulseLayout,
});

function PulseLayout() {
  return (
    <ProductShell product="pulse" items={PULSE_NAV}>
      <Outlet />
    </ProductShell>
  );
}
