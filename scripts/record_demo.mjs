/**
 * Record the README demo (docs/demo.webp) in light mode.
 *
 * Expects the demo stack from scripts/seed_demo.py to be running, with a
 * production frontend build (no dev overlay, no compile pauses) and the
 * backend reading the provider keys (uvicorn alone doesn't load .env, and the
 * header would say no keys are set):
 *   cd backend && DATABASE_PATH=../scripts/.demo/demo.sqlite CHROMA_DIR=../scripts/.demo/chroma \
 *     uv run python -m uvicorn app.main:server --port 8200 --env-file .env
 *   cd frontend && NEXT_PUBLIC_API_URL=http://127.0.0.1:8200 NEXT_DIST_DIR=.next-demo npx next build \
 *     && NEXT_DIST_DIR=.next-demo npx next start -p 3200
 *
 * Then:  node scripts/record_demo.mjs      (needs ffmpeg and uv on PATH)
 *
 * Playwright records a webm; ffmpeg trims the page-load lead-in into frames,
 * and Pillow packs them into an animated WebP. GitHub READMEs play WebP and
 * GIF inline but not video, and for a UI recording WebP is about a quarter of
 * the GIF's size at better quality.
 */
import { chromium } from "@playwright/test";
import { spawnSync } from "child_process";
import { fileURLToPath } from "url";
import path from "path";
import fs from "fs";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const APP = process.env.DEMO_URL ?? "http://127.0.0.1:3200";
const WORK = path.join(ROOT, "scripts", ".demo", "video");
const OUT = path.join(ROOT, "docs", "demo.webp");
const SIZE = { width: 1440, height: 900 };
const OUT_WIDTH = Number(process.env.DEMO_WIDTH ?? 1200);
// Playwright's screencast records at 25 fps; keep every frame.
const OUT_FPS = Number(process.env.DEMO_FPS ?? 25);
const OUT_QUALITY = Number(process.env.DEMO_QUALITY ?? 40);
// Pointer and scroll animation cadence (ms per step) — one screen refresh.
const TICK = 16;

fs.rmSync(WORK, { recursive: true, force: true });
fs.mkdirSync(WORK, { recursive: true });

// Playwright videos have no pointer; draw one so viewers can follow along.
const CURSOR = () => {
  const install = () => {
    if (document.getElementById("__demo_cursor")) return;
    const dot = document.createElement("div");
    dot.id = "__demo_cursor";
    Object.assign(dot.style, {
      position: "fixed", left: "-100px", top: "-100px", width: "18px", height: "18px",
      margin: "-9px 0 0 -9px", borderRadius: "50%", background: "rgba(37,99,235,0.35)",
      border: "2px solid rgba(37,99,235,0.9)", zIndex: 2147483647, pointerEvents: "none",
      transition: "transform 120ms ease, background 120ms ease",
    });
    document.body.appendChild(dot);
    window.addEventListener("mousemove", (e) => {
      dot.style.left = `${e.clientX}px`;
      dot.style.top = `${e.clientY}px`;
    }, true);
    window.addEventListener("mousedown", () => {
      dot.style.transform = "scale(0.7)";
      dot.style.background = "rgba(37,99,235,0.7)";
    }, true);
    window.addEventListener("mouseup", () => {
      dot.style.transform = "scale(1)";
      dot.style.background = "rgba(37,99,235,0.35)";
    }, true);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
};

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: SIZE,
  colorScheme: "light",
  recordVideo: { dir: WORK, size: SIZE },
});
await context.addInitScript(CURSOR);
await context.addInitScript(() => {
  if (!sessionStorage.getItem("__demo_init")) {
    localStorage.clear();
    localStorage.setItem("crucible_is_dark", "false");
    sessionStorage.setItem("__demo_init", "1");
  }
});
const page = await context.newPage();
const started = Date.now();

const pause = (ms) => page.waitForTimeout(ms);

/** Poll the React Flow transform until auto-fit settles. */
async function canvasIdle() {
  const read = () => page.locator(".react-flow__viewport").getAttribute("style").catch(() => null);
  let previous = await read();
  for (let i = 0; i < 30; i++) {
    await pause(120);
    const current = await read();
    if (current && current === previous) return;
    previous = current;
  }
}

let cursor = { x: SIZE.width / 2, y: SIZE.height / 2 };
const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

/**
 * Move the pointer over real time with ease-in-out. mouse.move({steps}) fires
 * every step at once, so on video the cursor just teleports.
 */
async function glideTo(x, y, duration) {
  const from = cursor;
  const distance = Math.hypot(x - from.x, y - from.y);
  const ms = duration ?? Math.min(700, Math.max(300, distance * 0.7));
  const steps = Math.max(1, Math.round(ms / TICK));
  for (let i = 1; i <= steps; i++) {
    const t = easeInOut(i / steps);
    await page.mouse.move(from.x + (x - from.x) * t, from.y + (y - from.y) * t);
    await pause(TICK);
  }
  cursor = { x, y };
}
async function clickOn(locator, { settle = 500 } = {}) {
  await locator.waitFor({ state: "visible" });
  const box = await locator.boundingBox();
  await glideTo(box.x + box.width / 2, box.y + box.height / 2);
  await pause(250);
  await page.mouse.down();
  await pause(90);
  await page.mouse.up();
  await pause(settle);
}
/** Scroll `dy` pixels over `ms`, in small eased increments like a trackpad. */
async function scrollBy(dy, { ms = 700, x = 900, y = 480 } = {}) {
  if (Math.hypot(cursor.x - x, cursor.y - y) > 4) await glideTo(x, y);
  const steps = Math.max(1, Math.round(ms / TICK));
  let done = 0;
  for (let i = 1; i <= steps; i++) {
    const target = dy * easeInOut(i / steps);
    await page.mouse.wheel(0, target - done);
    done = target;
    await pause(TICK);
  }
}

/** The node of `name` lowest on the canvas: its latest reply. */
async function lowestNode(name) {
  const found = await page.locator(".react-flow__node").filter({ hasText: name }).all();
  const placed = await Promise.all(found.map(async (l) => ({ l, y: (await l.boundingBox())?.y ?? -1 })));
  return placed.sort((a, b) => b.y - a.y)[0].l;
}

// ─── Lead-in (trimmed from the output) ──────────────────────────
await page.goto(APP);
await page.getByRole("button", { name: "New Session" }).waitFor();
// The settings panel is a rail in the recording: the cards need the width.
await page.getByRole("button", { name: "Hide settings panel" }).click();
await page.mouse.move(cursor.x, cursor.y);
await pause(1200);
const leadIn = (Date.now() - started) / 1000;

// ─── 1. Three models answer at once; the conversation is a tree ──
await pause(1000);
let loaded = page.waitForResponse((r) => r.url().includes("/history/") && r.ok());
await clickOn(page.getByRole("button", { name: "Monolith or microservices?" }));
await loaded;
await pause(1400);
const tree = page.getByRole("button", { name: "Tree", exact: true });
const arena = page.getByRole("button", { name: "Arena", exact: true });
await clickOn(tree, { settle: 600 });
await clickOn(page.locator(".react-flow__controls-fitview"), { settle: 700 });
await canvasIdle();
await pause(1600);

// ─── 2. Each model continued its own conversation: read them side by side ──
await clickOn(await lowestNode("GPT-6.1 Sol"), { settle: 900 });
await clickOn(arena, { settle: 1200 });
// Full-screen scrolling is what costs bytes in the output; keep it short.
await scrollBy(-20000, { ms: TICK });
await pause(2400);
await scrollBy(20000, { ms: 1400 });
await pause(1800);

// ─── 3. An anonymous three-model debate, read node by node ───────
loaded = page.waitForResponse((r) => r.url().endsWith("/tree") && r.ok());
await clickOn(page.getByRole("button", { name: "Is RAG a bridge or an architecture?" }));
await loaded;
await canvasIdle();
await pause(1800);
const reply = await lowestNode("GPT-6.1 Sol");
await clickOn(reply, { settle: 700 });
await clickOn(reply.getByRole("button", { name: "Read in full" }), { settle: 2600 });
await clickOn(page.getByRole("dialog").getByRole("button", { name: "Close" }), { settle: 600 });

// ─── 4. The transcript ends in an argument map, not a verdict ────
await clickOn(arena, { settle: 1000 });
await scrollBy(-20000, { ms: TICK });
await pause(1600);
await scrollBy(20000, { ms: 1400 });
await pause(2400);

// ─── Encode ─────────────────────────────────────────────────────
const video = page.video();
await context.close();
await browser.close();
const webm = await video.path();

const frames = path.join(WORK, "frames");
fs.mkdirSync(frames, { recursive: true });
const run = (cmd, args) => {
  const res = spawnSync(cmd, args, { stdio: "inherit" });
  if (res.status !== 0) throw new Error(`${cmd} failed: ${args.join(" ")}`);
};
run("ffmpeg", [
  "-loglevel", "error", "-ss", String(leadIn), "-i", webm,
  "-vf", `fps=${OUT_FPS},scale=${OUT_WIDTH}:-1:flags=lanczos`,
  path.join(frames, "%04d.png"),
]);
const PACK = `
import glob, sys
from PIL import Image
frames = [Image.open(p).convert("RGB") for p in sorted(glob.glob(sys.argv[1] + "/*.png"))]
frames[0].save(sys.argv[2], save_all=True, append_images=frames[1:], loop=0,
               duration=round(1000 / int(sys.argv[3])), quality=int(sys.argv[4]), method=4)
`;
run("uv", ["run", "--no-project", "--with", "pillow", "python", "-c", PACK, frames, OUT, String(OUT_FPS), String(OUT_QUALITY)]);
const mb = (fs.statSync(OUT).size / 1024 / 1024).toFixed(1);
console.log(`wrote ${path.relative(ROOT, OUT)} (${mb} MB), source ${path.relative(ROOT, webm)}`);
