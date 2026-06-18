import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  nitro: {
    cloudflare: { nodeCompat: true, deployConfig: true }
  }
});
