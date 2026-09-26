import { Page, expect } from "@playwright/test";

/** Matches the fixture built by e2e/seed_db.py. */
export const MAIN_THREAD_TITLE = "E2E Reference Thread";
export const DEBATE_THREAD_TITLE = "E2E Debate Thread";

/** Mirrored from backend/app/services/tree.py and CustomTreeNode.tsx. */
export const LOD_THRESHOLD = 0.6;
export const NODE_SPACING_X = 260;

/**
 * Open the app with a clean slate.
 *
 * The app persists the active thread, the active debate and the panel state in
 * localStorage, so without this each spec would inherit the previous one's view.
 */
export async function openApp(page: Page) {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await expect(page.getByRole("button", { name: "New Session" })).toBeVisible();
}

/** Click a thread in the sidebar and wait for its tree to finish loading. */
export async function openThread(page: Page, title: string) {
  const treeResponse = page.waitForResponse(
    (r) => r.url().includes("/history/") && r.status() === 200,
  );
  await page.getByRole("button", { name: title, exact: false }).first().click();
  await treeResponse;
  await expect(nodes(page).first()).toBeVisible();
  await waitForCanvasIdle(page);
}

export function nodes(page: Page) {
  return page.locator(".react-flow__node");
}

/**
 * Wait until the canvas stops moving.
 *
 * Auto-fit animates the viewport for 500ms, and Playwright refuses to click an
 * element that is still in motion ("element is not stable"). Polling the
 * transform is more reliable than a fixed sleep.
 */
export async function waitForCanvasIdle(page: Page) {
  const read = () => viewport(page).getAttribute("style");
  let previous = await read();
  for (let i = 0; i < 25; i++) {
    await page.waitForTimeout(100);
    const current = await read();
    if (current === previous) return;
    previous = current;
  }
}

/** The debate lane headers overlay, above the canvas. */
export function laneHeaders(page: Page) {
  return page.locator(".react-flow").locator("xpath=preceding-sibling::div[1]");
}

/** Switch to the tree view via the segmented control. */
export async function showTree(page: Page) {
  const tree = page.getByRole("button", { name: "Tree", exact: true });
  if ((await tree.getAttribute("aria-pressed")) !== "true") await tree.click();
  await expect(tree).toHaveAttribute("aria-pressed", "true");
}

/**
 * Zoom in until nodes are guaranteed to be in detail mode.
 *
 * Auto-fit can land within a rounding error of LOD_THRESHOLD, which would make
 * any assertion about node *text* flip depending on layout noise.
 */
export async function ensureDetailZoom(page: Page) {
  const button = page.locator(".react-flow__controls-zoomin");
  for (let i = 0; i < 8; i++) {
    if ((await getZoom(page)) > LOD_THRESHOLD + 0.1) return;
    await button.click();
    await page.waitForTimeout(120);
  }
  throw new Error(`could not zoom above ${LOD_THRESHOLD + 0.1}`);
}

/**
 * A node that is fully inside the canvas, not already selected, and carries a
 * preview long enough that selecting it visibly expands the node.
 */
export async function clickableNode(page: Page) {
  await waitForCanvasIdle(page);
  const pane = (await page.locator(".react-flow__pane").boundingBox())!;
  const candidates = await page.evaluate(
    ({ x, y, w, h }) =>
      [...document.querySelectorAll(".react-flow__node")]
        .map((el, index) => {
          const r = el.getBoundingClientRect();
          return {
            index,
            selected: el.classList.contains("selected"),
            length: (el as HTMLElement).innerText.length,
            inside:
              r.left > x + 4 &&
              r.right < x + w - 4 &&
              r.top > y + 4 &&
              r.bottom < y + h - 4,
          };
        })
        .filter((n) => n.inside && !n.selected && n.length > 40),
    { x: pane.x, y: pane.y, w: pane.width, h: pane.height },
  );
  if (!candidates.length) throw new Error("no unselected node is fully in view");
  return nodes(page).nth(candidates[0].index);
}

export function viewport(page: Page) {
  return page.locator(".react-flow__viewport");
}

/** Current React Flow zoom, read off the viewport transform. */
export async function getZoom(page: Page): Promise<number> {
  const transform = await viewport(page).getAttribute("style");
  const match = transform?.match(/scale\(([\d.]+)\)/);
  return match ? Number(match[1]) : 1;
}

/** Zoom out until below `target`, using React Flow's own control. */
export async function zoomOutTo(page: Page, target: number) {
  const button = page.locator(".react-flow__controls-zoomout");
  for (let i = 0; i < 12; i++) {
    if ((await getZoom(page)) < target) return;
    await button.click();
    await page.waitForTimeout(120);
  }
  throw new Error(`could not zoom below ${target}; stuck at ${await getZoom(page)}`);
}

/** Bounding boxes of every rendered node, in viewport pixels. */
export async function nodeBoxes(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll(".react-flow__node")].map((el) => {
      const r = el.getBoundingClientRect();
      return {
        text: (el as HTMLElement).innerText.replace(/\s+/g, " ").trim(),
        left: r.left,
        right: r.right,
        top: r.top,
        bottom: r.bottom,
      };
    }),
  );
}

/** Node fill/border/text colours, for theme assertions. */
export async function nodeColors(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll(".react-flow__node > div")].slice(0, 6).map((el) => {
      const s = getComputedStyle(el as HTMLElement);
      return `${s.backgroundColor}|${s.color}`;
    }),
  );
}

/** The backend the suite runs against (see playwright.config.ts). */
export const BACKEND_URL = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT ?? 8123}`;

/** Start from an empty, throwaway session so live tests never touch the fixture threads. */
export async function newSession(page: Page) {
  await page.getByRole("button", { name: "New Session" }).click();
  await expect(page.getByPlaceholder(/Ask the arena/i)).toBeVisible();
}

/** Add a model to the arena selection (gpt-5.4 is selected by default). */
export async function addModel(page: Page, family: string, name: string) {
  // The default model is applied once /models answers; selecting before that
  // would stop the default from being added at all.
  await expect(page.getByText("GPT-5.4", { exact: true }).first()).toBeVisible();
  const familyButton = page.getByRole("button", { name: new RegExp(`^${family} \\d+ models$`) });
  if ((await page.getByRole("button", { name }).count()) === 0) await familyButton.click();
  await page.getByRole("button", { name }).first().click();
}

/** The thread the app currently has open, as persisted by useThreads. */
export async function currentThreadId(page: Page): Promise<string> {
  const id = await page.evaluate(() => localStorage.getItem("crucible_thread_id"));
  if (!id) throw new Error("no thread is open");
  return id;
}

export async function send(page: Page, text: string) {
  await page.getByPlaceholder(/Ask the arena/i).fill(text);
  await page.getByRole("button", { name: "Send", exact: true }).click();
}

/** Open the debate dialog for `prompt`, set the round count and start it. */
export async function startDebate(page: Page, prompt: string, rounds: number) {
  await page.getByPlaceholder(/Ask the arena/i).fill(prompt);
  await page.getByRole("button", { name: "Start debate" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Max rounds").fill(String(rounds));
  await dialog.getByRole("button", { name: "Start Debate" }).click();
  // Starting a debate shows the tree; the status banner lives in the Arena view.
  await page.getByRole("button", { name: "Arena", exact: true }).click();
  await expect(page.getByText(new RegExp(`DEBATE · ROUND \\d+/${rounds}`))).toBeVisible();
}

/** The status chip in the debate banner. */
export function debateStatus(page: Page) {
  // Scoped to the banner: the sidebar's debate rows carry a status chip too.
  return page
    .getByText(/DEBATE · ROUND/)
    .locator("..")
    .getByText(/^(running|pausing after this round|paused|converged|completed|interrupted)$/);
}
