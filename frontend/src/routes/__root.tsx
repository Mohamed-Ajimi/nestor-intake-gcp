import { Outlet, Link, createRootRoute, HeadContent, Scripts } from "@tanstack/react-router";

import appCss from "../styles.css?url";

function NotFoundComponent() {
 return (
 <div className="flex min-h-screen items-center justify-center bg-background px-4">
 <div className="max-w-md text-center">
 <h1 className="text-7xl font-bold text-foreground">404</h1>
 <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
 <p className="mt-2 text-sm text-muted-foreground">
 The page you're looking for doesn't exist or has been moved.
 </p>
 <div className="mt-6">
 <Link
 to="/"
 className="inline-flex items-center justify-center bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
 >
 Go home
 </Link>
 </div>
 </div>
 </div>
 );
}

export const Route = createRootRoute({
 head: () => ({
 meta: [
 { charSet: "utf-8" },
 { name: "viewport", content: "width=device-width, initial-scale=1" },
 { name: "google", content: "notranslate" },
 { title: "Nestor — verified research that compounds" },
 { name: "description", content: "Nestor by Agenic — a research platform built on Pulse, Echo, Edge, Flux and Sales." },
 { name: "author", content: "Agenic" },
 { property: "og:title", content: "Nestor — verified research that compounds" },
 { property: "og:description", content: "Nestor by Agenic — a research platform built on Pulse, Echo, Edge, Flux and Sales." },
 { property: "og:type", content: "website" },
 { name: "twitter:card", content: "summary" },
 { name: "twitter:site", content: "@Lovable" },
 { name: "twitter:title", content: "Nestor — verified research that compounds" },
 { name: "twitter:description", content: "Nestor by Agenic — a research platform built on Pulse, Echo, Edge, Flux and Sales." },
 { property: "og:image", content: "https://pub-bb2e103a32db4e198524a2e9ed8f35b4.r2.dev/9315e1be-9ba4-4e2e-ba77-d1edbffde271/id-preview-b7085b74--bc31e1fb-a24c-404e-9877-00cd9c3dbce8.lovable.app-1777962554944.png" },
 { name: "twitter:image", content: "https://pub-bb2e103a32db4e198524a2e9ed8f35b4.r2.dev/9315e1be-9ba4-4e2e-ba77-d1edbffde271/id-preview-b7085b74--bc31e1fb-a24c-404e-9877-00cd9c3dbce8.lovable.app-1777962554944.png" },
 ],
 links: [
 { rel: "preconnect", href: "https://fonts.googleapis.com" },
 { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
 {
 rel: "stylesheet",
 href: "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:ital,wght@0,200;0,400;0,600;1,400&display=swap",
 },
 {
 rel: "stylesheet",
 href: appCss,
 },
 ],
 }),
 shellComponent: RootShell,
 component: RootComponent,
 notFoundComponent: NotFoundComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
 return (
 <html lang="en" translate="no" className="notranslate">
 <head>
 <HeadContent />
 </head>
 <body>
 {children}
 <Scripts />
 </body>
 </html>
 );
}

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { useEffect } from "react";
import { useRouter } from "@tanstack/react-router";
import { AuthProvider, useAuth, landingPathForRole } from "@/lib/auth-context";

const queryClient = new QueryClient();

function AuthRedirector() {
 const router = useRouter();
 const { session, loading, role } = useAuth();
 useEffect(() => {
 if (loading || !session) return;
 const path = window.location.pathname;
 if (path === "/admin/login" || path === "/auth/login") {
 // Wait for the role claim to resolve so a superadmin is never briefly sent to
 // /intake. Route by role: superadmin → /admin, user → /intake (avoids the
 // admin "geen toegang" wall for non-superadmins).
 if (!role) return;
 router.navigate({ to: landingPathForRole(role) });
 }
 }, [loading, session, role, router]);
 return null;
}

function RootComponent() {
 useEffect(() => {
 document.documentElement.setAttribute("translate", "no");
 document.documentElement.classList.add("notranslate");
 }, []);
 return (
 <QueryClientProvider client={queryClient}>
 <AuthProvider>
 <AuthRedirector />
 <Outlet />
 <Toaster position="top-right" />
 </AuthProvider>
 </QueryClientProvider>
 );
}
