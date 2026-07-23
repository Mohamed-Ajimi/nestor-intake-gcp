import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  // Phase 12 / INFRA-05 (D-08): target the Nitro `node-server` preset so the SSR
  // build emits a plain Node HTTP server (`.output/server/index.mjs`) for the
  // Cloud Run container (`node .output/server/index.mjs`, respects $PORT/$NITRO_PORT).
  // A user-supplied `preset` overrides @lovable.dev/vite-tanstack-config's default
  // `cloudflare-module` outside a Lovable sandbox — Cloud Build is not a sandbox, so
  // this takes effect. `wrangler.jsonc` + @cloudflare/vite-plugin are left INERT
  // (Pitfall 6 — removing them risks disturbing `npm run dev`), not deleted.
  nitro: { preset: "node-server" },
  // Allow all hosts so the Replit proxied preview domain works in dev.
  server: { allowedHosts: true },
});
