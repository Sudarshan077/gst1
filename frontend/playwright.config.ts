import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  retries: 1,
  // All specs share one dev server (:9094) and one backend (:8084); parallel
  // workers contend for the OTP-login step and flake (monitor RETRY 8.11).
  workers: 1,
  webServer: {
    command: "npm run dev -- --port 9094",
    url: "http://127.0.0.1:9094",
    reuseExistingServer: true,
    timeout: 120_000,
  },
  use: {
    baseURL: "http://127.0.0.1:9094",
    trace: "retain-on-failure",
    headless: true,
    launchOptions: {
      args: ["--disable-gpu", "--no-sandbox"],
    },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
