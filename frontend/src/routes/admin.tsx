import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { onAuthStateChanged, type User } from "firebase/auth";
import { auth } from "@/lib/firebase";

// Firebase resolves `auth.currentUser` only after the first onAuthStateChanged
// tick (Open Q2). This promise resolves with the initial auth state so the
// guard can await it instead of racing a not-yet-populated currentUser.
function authReady(): Promise<User | null> {
  if (auth.currentUser) return Promise.resolve(auth.currentUser);
  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      resolve(user);
    });
  });
}

export const Route = createFileRoute("/admin")({
  // UX gating only — the authoritative control is the backend
  // get_current_identity dependency (plans 02/03). This guard is
  // defense-in-depth; live behavior is validated in GCP at/after Phase 12 (D-09).
  beforeLoad: async () => {
    const user = await authReady();
    if (!user) {
      throw redirect({ to: "/auth/login" });
    }
  },
  component: AdminLayout,
});

function AdminLayout() {
  return <Outlet />;
}
