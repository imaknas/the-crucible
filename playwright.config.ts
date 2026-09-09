import { defineConfig, devices } from "@playwright/test";
import path from "path";

/**
 * E2E config.
 *
 * Both servers are started against `e2e/.fixtures/e2e.sqlite`, a deterministic
 * database built by `e2e/seed_db.py`. The real `backend/checkpoints.sqlite` is
 * never opened, and the fake API keys guarantee that a test which accidentally
 * triggers generation fails loudly instead of billing a live model.
 */
const ROOT = __dirname;
const FIXTURE_DB = path.join(ROOT, "e2e", ".fixtures", "e2e.sqlite");

const BACKEND_PORT = 8123;
const FRONTEND_PORT = 3123;

export default defineConfig({
  testDir: "./e2e/tests",
  fullyParallel: false, // one shared backend + one fixture database
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "e2e/.report" }]],
  timeout: 45_000,
  expect: { timeout: 12_000 },

  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 900 },
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],

  webServer: [
    {
      command: `uv run --project backend python -m uvicorn app.main:server --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: path.join(ROOT, "backend"),
      port: BACKEND_PORT,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        DATABASE_PATH: FIXTURE_DB,
        // The fixture is pre-seeded; nothing in the suite should reach a model.
        OPENAI_API_KEY: "e2e-fixture-not-a-real-key",
        ANTHROPIC_API_KEY: "e2e-fixture-not-a-real-key",
        GOOGLE_API_KEY: "e2e-fixture-not-a-real-key",
      },
    },
    {
      command: `npx next dev --port ${FRONTEND_PORT}`,
      cwd: path.join(ROOT, "frontend"),
      port: FRONTEND_PORT,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        NEXT_PUBLIC_API_URL: `http://127.0.0.1:${BACKEND_PORT}`,
      },
    },
  ],
});
