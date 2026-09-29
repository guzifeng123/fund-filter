import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PLAYWRIGHT_WEB_PORT ?? 3100);
const apiPort = Number(process.env.PLAYWRIGHT_API_PORT ?? 8100);
const realApi = process.env.PLAYWRIGHT_REAL_API === "1";
const externalServers = process.env.PLAYWRIGHT_EXTERNAL_SERVERS === "1";
const realApiDatabaseUrl = process.env.PLAYWRIGHT_DATABASE_URL
  ?? "sqlite:///C:/Users/39187/Desktop/基金/output/playwright/real-api.db";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: {
    timeout: 10_000
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: [
    ["list"],
    ["html", { outputFolder: "../../output/playwright/html-report", open: "never" }]
  ],
  outputDir: "../../output/playwright/test-results",
  workers: realApi ? 1 : undefined,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  },
  webServer: externalServers
    ? undefined
    : realApi
    ? [
        {
          command: `python -m uvicorn app.main:app --app-dir ../api --host 127.0.0.1 --port ${apiPort}`,
          port: apiPort,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            ...process.env,
            DATABASE_URL: realApiDatabaseUrl,
            FUND_SYNC_SCHEDULER_ENABLED: "false",
            CORS_ORIGINS: `http://127.0.0.1:${port}`
          }
        },
        {
          command: `node ../../node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port ${port}`,
          port,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            ...process.env,
            NEXT_PUBLIC_API_BASE: `http://127.0.0.1:${apiPort}/api`
          }
        }
      ]
    : {
        command: `node ../../node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port ${port}`,
        port,
        reuseExistingServer: false,
        timeout: 120_000
      },
  projects: realApi
    ? [
        {
          name: "real-api-chromium",
          testMatch: /real-api\.spec\.ts/,
          use: { ...devices["Desktop Chrome"] }
        },
        {
          name: "real-api-mobile-chromium",
          testMatch: /real-api\.spec\.ts/,
          use: { ...devices["Pixel 5"] }
        },
        {
          name: "real-api-firefox",
          testMatch: /real-api\.spec\.ts/,
          use: { ...devices["Desktop Firefox"] }
        }
      ]
    : [
        {
          name: "chromium",
          testIgnore: /real-api\.spec\.ts/,
          use: { ...devices["Desktop Chrome"] }
        }
      ]
});
