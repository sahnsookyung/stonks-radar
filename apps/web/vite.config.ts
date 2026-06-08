import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const env = (globalThis as typeof globalThis & { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};

export default defineConfig({
  plugins: [react()],
  publicDir: env.STONKS_WEB_PUBLIC_DIR ?? "public",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true
      }
    }
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          router: ["@tanstack/react-router", "@tanstack/react-query"],
          i18n: ["i18next", "react-i18next"]
        }
      }
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    coverage: {
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/**/*.d.ts", "src/test/**"],
      reporter: ["text", "lcov"]
    }
  }
});
