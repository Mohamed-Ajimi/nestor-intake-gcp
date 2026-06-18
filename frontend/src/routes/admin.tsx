import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/admin")({
  component: AdminGuard,
});

function AdminGuard() {
  // TEMP: auth disabled voor testing — later weer activeren
  return <Outlet />;
}
