import { defineConfig, devices } from "@playwright/test";
import path from "path";

/**
 * E2E config.
 *
 * Both servers are started against `e2e/.fixtures/e2e.sqlite`, a deterministic
 * database built by `e2e/seed_db.py`. The real `backend/checkpoints.sqlite` is
 * never opened. CRUCIBLE_FAKE_LLM makes every model a scripted fake
 * (backend/app/services/fake_llm.py), so tests can send messages and run
 * debates end to end without network access; the fake API keys are a second
 * guard that nothing can bill a live model.
 */
const ROOT = __dirname;
const FIXTURE_DB = path.join(ROOT, "e2e", ".fixtures", "e2e.sqlite");

// Override when something else already holds these ports: with
// reuseExistingServer, Playwright would otherwise test against that process.
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8123);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 3123);

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
        CHROMA_DIR: path.join(ROOT, "e2e", ".fixtures", "chroma"),
        CRUCIBLE_FAKE_LLM: "1",
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
