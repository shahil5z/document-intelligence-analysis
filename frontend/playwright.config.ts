import { defineConfig, devices } from "@playwright/test";

// Runs against an already running stack (see scripts/e2e_prod_local.sh):
//   E2E_BASE_URL  the frontend, e.g. https://app.localhost:8443 (default http://localhost:3000)
//   E2E_API_URL   the API as the browser sees it (for the direct-upload assertions)
export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    // The local stack uses Caddy's own CA; the browser is not told to trust it.
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 900 } } }],
});
