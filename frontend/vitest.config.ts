import { defineConfig } from "vitest/config";
import tsconfigPaths from "vite-tsconfig-paths";

// Standalone vitest config — intentionally NOT extending the Cloudflare/Nitro/TanStack
// preset in vite.config.ts (that preset wires SSR + the Workers runtime, which the pure
// unit suite must not pull in). We reuse `vite-tsconfig-paths` so the `@/*` -> `./src/*`
// alias from tsconfig.json resolves identically to the app build.
export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    // derivePhase is a pure function — no DOM needed, so the lighter node env is used.
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
