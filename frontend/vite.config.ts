import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  // Phase 12 / INFRA-05 (D-08): target the Nitro `node-server` preset so the SSR
  // build emits a plain Node HTTP server (`.output/server/index.mjs`) for the
  // Cloud Run container (`node .output/server/index.mjs`, respects $PORT/$NITRO_PORT).
  nitro: { preset: "node-server" },

  server: {
    // Allow the Replit proxied preview domain (and any other host) in dev.
    allowedHosts: true,

    // Proxy /api/* → mock backend on port 3001 (path rewrite strips the /api prefix).
    // This keeps all traffic on port 5000 so the browser can reach the backend through
    // Replit's proxy — setting VITE_API_BASE_URL=/api makes apiFetch use relative paths.
    proxy: {
      "/api": {
        target: "http://localhost:3001",
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ""),
      },
    },
  },
});
