/**
 * Capture the README screenshots.
 *
 * Expects the demo stack to be running:
 *   uv run --project backend python scripts/seed_demo.py
 *   cd backend && DATABASE_PATH=../scripts/.demo/demo.sqlite \
 *     uv run python -m uvicorn app.main:server --port 8200
 *   cd frontend && NEXT_PUBLIC_API_URL=http://127.0.0.1:8200 npx next dev --port 3200
 *
 * Then:  node scripts/capture_screenshots.mjs
 *
 * Writes 2x PNGs to docs/screenshots/.
 */
import { chromium } from "@playwright/test";
import { fileURLToPath } from "url";
import path from "path";
import fs from "fs";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const OUT = path.join(ROOT, "docs", "screenshots");
const APP = process.env.DEMO_URL ?? "http://127.0.0.1:3200";

fs.mkdirSync(OUT, { recursive: true });

/** Poll the React Flow transform until the auto-fit animation settles. */
async function canvasIdle(page) {
  const read = () =>
    page.locator(".react-flow__viewport").getAttribute("style").catch(() => null);
  let previous = await read();
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(120);
    const current = await read();
    if (current && current === previous) return;
    previous = current;
  }
}

async function openThread(page, name) {
  // Arm the waiter before clicking, or the response can land first.
  const loaded = page.waitForResponse(
    (r) => r.url().includes("/history/") && r.ok(),
  );
  await page.getByRole("button", { name, exact: false }).first().click();
  await loaded;
  await page.waitForTimeout(600);
  await canvasIdle(page);
}

async function openDebate(page) {
  const loaded = page.waitForResponse((r) => r.url().endsWith("/tree") && r.ok());
  await page.getByText(/rounds$/).first().click();
  await loaded;
  await page.waitForTimeout(900);
  await canvasIdle(page);
}

async function shoot(page, file) {
  const target = path.join(OUT, file);
  await page.screenshot({ path: target });
  console.log(`  ${file}`);
}

const shots = [
  {
    file: "conversation-tree.png",
    async run(page) {
      await openThread(page, "Monolith or micros");
      await page.getByRole("button", { name: "Tree", exact: true }).click();
      // Auto-fit zooms to the active checkpoint, which clips the root; fit the
      // whole tree so the branch reads as a branch.
      await page.locator(".react-flow__controls-fitview").click();
      await page.waitForTimeout(700);
      await canvasIdle(page);
    },
  },
  {
    file: "debate-lanes.png",
    async run(page) {
      await openThread(page, "Is RAG a bri");
      await openDebate(page);
    },
  },
  {
    file: "arena-chat.png",
    async run(page) {
      await openThread(page, "Is RAG a bri");
      await openDebate(page);
      await page.getByRole("button", { name: "Arena", exact: true }).click();
      await page.waitForTimeout(1200);
      // The transcript opens at the synthesis; scroll back to the first round
      // so the shot shows the models answering in parallel, which is the point.
      await page.mouse.move(1000, 500);
      await page.mouse.wheel(0, -20000);
      await page.waitForTimeout(1200);
    },
  },
];

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
  deviceScaleFactor: 2,
  colorScheme: "dark",
});
const page = await context.newPage();

console.log("capturing:");
for (const shot of shots) {
  await page.goto(APP);
  await page.evaluate(() => {
    localStorage.clear();
    localStorage.setItem("crucible_is_dark", "true");
  });
  await page.reload();
  await page.getByRole("button", { name: "New Session" }).waitFor();
  await page.waitForTimeout(800);
  await shot.run(page);
  await shoot(page, shot.file);
}

await browser.close();
console.log(`\nwrote ${shots.length} screenshots to docs/screenshots/`);
