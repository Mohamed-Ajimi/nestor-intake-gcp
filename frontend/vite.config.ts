import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  // Phase 12 / INFRA-05 (D-08): target the Nitro `node-server` preset.
  nitro: { preset: "node-server" },

  // Vite-specific options must live under the `vite` key when any Lovable-specific
  // key (e.g. `nitro`) is present — the package only merges `options.vite` into the
  // final Vite config; top-level non-Lovable keys are silently ignored.
  vite: {
    server: {
      // Allow the Replit proxied preview domain (and any other host) in dev.
      allowedHosts: true,

      // Proxy /api/* → mock backend on port 3001 (strips the /api prefix).
      // Keeps all traffic through port 5000 so the browser can reach the backend
      // via Replit's proxy. VITE_API_BASE_URL=/api makes apiFetch use relative paths.
      proxy: {
        "/api": {
          target: "http://localhost:3001",
          rewrite: (path: string) => path.replace(/^\/api/, ""),
        },
      },
    },
  },
});
