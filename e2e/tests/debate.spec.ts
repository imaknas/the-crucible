import { test, expect } from "@playwright/test";
import {
  DEBATE_THREAD_TITLE,
  openApp,
  openThread,
  nodes,
  nodeBoxes,
  ensureDetailZoom,
  waitForCanvasIdle,
} from "./helpers";

/** 1 shared prompt + (2 lanes x 2 rounds) + 1 synthesis, per e2e/seed_db.py. */
const FIXTURE_NODE_COUNT = 6;

/** Open the seeded debate: its thread, then its session in the sidebar. */
async function openDebate(page: import("@playwright/test").Page) {
  await openApp(page);
  await openThread(page, DEBATE_THREAD_TITLE);
  const treeResponse = page.waitForResponse(
    (r) => r.url().includes("/debate/sessions/") && r.url().endsWith("/tree"),
  );
  await page.getByText(/rounds$/).first().click();
  await treeResponse;
  // Wait for the canvas to settle: the round bands paint from session metadata
  // and can beat the nodes onto the screen.
  await expect(nodes(page)).toHaveCount(FIXTURE_NODE_COUNT);
  await expect(page.getByText("Round 1", { exact: false }).first()).toBeVisible();
  // Auto-fit lands near the level-of-detail threshold here, so pin the view to
  // detail mode before anything asserts on node text.
  await ensureDetailZoom(page);
  await waitForCanvasIdle(page);
}

test.describe("debate tree", () => {
  test.beforeEach(async ({ page }) => {
    await openDebate(page);
  });

  test("draws one lane per model with display-name headers", async ({ page }) => {
    // Both the lane pill and each node badge carry title={model_id}; scope to
    // the <span> pills so this asserts the headers specifically.
    const pills = page.locator('span[title="gpt-5.4"], span[title="claude-sonnet-5"]');
    await expect(pills).toHaveCount(2);
    await expect(pills.filter({ hasText: "GPT-5.4" })).toHaveCount(1);
    await expect(pills.filter({ hasText: "Claude Sonnet 5" })).toHaveCount(1);
  });

  test("states the question once instead of once per lane", async ({ page }) => {
    // Regression: the prompt checkpoint used to render inside every lane, which
    // duplicated the question N times and doubled the round counter.
    const texts = (await nodeBoxes(page)).map((b) => b.text);
    const promptNodes = texts.filter((t) => t.includes("state your position"));
    expect(promptNodes.length).toBeLessThanOrEqual(1);
  });

  test("lays 2 models x 2 rounds into a grid, plus prompt and synthesis", async ({
    page,
  }) => {
    await expect(nodes(page)).toHaveCount(FIXTURE_NODE_COUNT);

    const boxes = await nodeBoxes(page);
    const columns = new Set(boxes.map((b) => Math.round(b.left / 20)));
    // Two lanes plus the centred prompt/synthesis column.
    expect(columns.size).toBeGreaterThanOrEqual(3);
  });

  test("labels each round and shows the recorded convergence score", async ({
    page,
  }) => {
    await expect(page.getByText("Round 1", { exact: false })).toBeVisible();
    await expect(page.getByText("Round 2", { exact: false })).toBeVisible();
    // seed_db.py records 0.91 for round index 1, which renders on Round 2.
    await expect(page.getByText("91% converged")).toBeVisible();
  });

  test("hangs synthesis below every lane", async ({ page }) => {
    const boxes = await nodeBoxes(page);
    const synthesis = boxes.find((b) => /synthesis/i.test(b.text));
    expect(synthesis, "synthesis node should render").toBeTruthy();

    const lowestLane = Math.max(
      ...boxes.filter((b) => b !== synthesis).map((b) => b.top),
    );
    expect(synthesis!.top).toBeGreaterThanOrEqual(lowestLane);
  });

  test("debate nodes are selectable and carry no delete affordance", async ({
    page,
  }) => {
    // Regression: onDeleteNode={() => {}} rendered a red trash button that did
    // nothing on hover.
    const node = nodes(page).nth(1);
    await node.hover();
    await expect(node.locator('button[title*="Delete"]')).toHaveCount(0);

    const before = (await node.boundingBox())!.height;
    await node.click();
    await expect
      .poll(async () => (await node.boundingBox())!.height)
      .toBeGreaterThan(before);
  });
});
