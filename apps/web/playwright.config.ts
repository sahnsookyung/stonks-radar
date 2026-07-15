import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.STONKS_E2E_BASE_URL ?? "http://127.0.0.1:5173";
const useExternalServer = Boolean(process.env.STONKS_E2E_BASE_URL);

export default defineConfig({
  testDir: "../../tests/frontend",
  webServer: useExternalServer
    ? undefined
    : {
        command: "npm run dev -- --host 127.0.0.1 --logLevel silent",
        url: baseURL,
        reuseExistingServer: false
      },
  use: {
    baseURL,
    trace: "on-first-retry"
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 5"] } }
  ]
});
