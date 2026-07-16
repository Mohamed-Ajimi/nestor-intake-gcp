import { createFileRoute, Outlet } from "@tanstack/react-router";
import { ProductShell } from "@/components/admin/ProductShell";

export const Route = createFileRoute("/admin/sales")({
  component: SalesLayout,
});

function SalesLayout() {
  return (
    <ProductShell
      product="sales"
      items={[
        { to: "/admin/sales/projects/new", labelKey: "nav.salesNewProject", exact: true },
        { to: "/admin/sales/projects", labelKey: "nav.salesProjects", exact: false },
      ]}
    >
      <Outlet />
    </ProductShell>
  );
}
