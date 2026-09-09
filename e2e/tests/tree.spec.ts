import { test, expect } from "@playwright/test";
import {
  MAIN_THREAD_TITLE,
  LOD_THRESHOLD,
  NODE_SPACING_X,
  openApp,
  openThread,
  nodes,
  getZoom,
  zoomOutTo,
  nodeBoxes,
  nodeColors,
  clickableNode,
} from "./helpers";

test.beforeEach(async ({ page }) => {
  await openApp(page);
  await openThread(page, MAIN_THREAD_TITLE);
});

test.describe("conversation tree", () => {
  test("renders the seeded thread with its branch", async ({ page }) => {
    // Fixture: root → prompt → reply, then a fork into two prompt/reply pairs.
    await expect(nodes(page)).toHaveCount(7);
    await expect(page.locator(".react-flow__edge")).toHaveCount(6);
  });

  test("auto-fits so the tree is on screen without touching the controls", async ({
    page,
  }) => {
    // Regression: fitView used to race React Flow's store and silently no-op,
    // leaving every node parked off-canvas until the user hit Recenter.
    const pane = await page.locator(".react-flow__pane").boundingBox();
    expect(pane).not.toBeNull();

    const boxes = await nodeBoxes(page);
    const onScreen = boxes.filter(
      (b) =>
        b.right > pane!.x &&
        b.left < pane!.x + pane!.width &&
        b.bottom > pane!.y &&
        b.top < pane!.y + pane!.height,
    );
    expect(onScreen.length).toBeGreaterThan(0);
  });

  test("parents sit centred over their children", async ({ page }) => {
    // The tidy-tree invariant, observed through the DOM rather than the layout
    // function: the fork's parent must be midway between its two subtrees.
    const boxes = await nodeBoxes(page);
    const rows = new Map<number, typeof boxes>();
    for (const b of boxes) {
      const key = Math.round(b.top / 10) * 10;
      rows.set(key, [...(rows.get(key) ?? []), b]);
    }
    const forkRow = [...rows.values()].find((r) => r.length === 2);
    expect(forkRow, "fixture should contain one row with two siblings").toBeTruthy();

    const centre = (b: { left: number; right: number }) => (b.left + b.right) / 2;
    const siblingMidpoint =
      (centre(forkRow![0]) + centre(forkRow![1])) / 2;

    const above = boxes
      .filter((b) => b.bottom <= forkRow![0].top)
      .sort((a, b) => b.top - a.top)[0];
    expect(Math.abs(centre(above) - siblingMidpoint)).toBeLessThan(8);
  });

  test("no two nodes overlap at any zoom level", async ({ page }) => {
    // Guards the level-of-detail counter-scale: the chip is enlarged as the
    // canvas shrinks, and an uncapped boost made neighbouring columns collide.
    for (const target of [1.0, 0.55, 0.35]) {
      if (target < (await getZoom(page))) await zoomOutTo(page, target);

      const boxes = await nodeBoxes(page);
      const rows = new Map<number, typeof boxes>();
      for (const b of boxes) {
        const key = Math.round(b.top / 12) * 12;
        rows.set(key, [...(rows.get(key) ?? []), b]);
      }

      for (const row of rows.values()) {
        const sorted = [...row].sort((a, b) => a.left - b.left);
        for (let i = 1; i < sorted.length; i++) {
          expect(
            sorted[i].left,
            `overlap at zoom ${await getZoom(page)}: "${sorted[i - 1].text}" / "${sorted[i].text}"`,
          ).toBeGreaterThanOrEqual(sorted[i - 1].right - 1);
        }
      }
    }
  });

  test("swaps to a legible chip below the level-of-detail threshold", async ({
    page,
  }) => {
    // Close in, nodes carry a clamped preview of the message.
    expect(await getZoom(page)).toBeGreaterThan(LOD_THRESHOLD);
    const detailed = (await nodeBoxes(page)).map((b) => b.text).join(" ");
    expect(detailed).toContain("Branching a conversation tree");

    await zoomOutTo(page, LOD_THRESHOLD - 0.05);

    // Far out, the preview is gone and identity survives instead.
    const chips = (await nodeBoxes(page)).map((b) => b.text);
    expect(chips.join(" ")).not.toContain("Branching a conversation tree");
    expect(chips.some((t) => /GPT-5\.4/.test(t))).toBe(true);
    expect(chips.some((t) => /words/.test(t))).toBe(true);
  });

  test("chips stay within their column budget when scaled up", async ({ page }) => {
    await zoomOutTo(page, 0.4);
    const zoom = await getZoom(page);
    const boxes = await nodeBoxes(page);
    const widest = Math.max(...boxes.map((b) => b.right - b.left));

    // A chip may never occupy more canvas than the layout pitch it sits in.
    expect(widest).toBeLessThanOrEqual(NODE_SPACING_X * zoom + 1);
  });

  test("shows model display names, never raw API identifiers", async ({ page }) => {
    const text = (await nodeBoxes(page)).map((b) => b.text).join(" ");
    // Badges are uppercased in CSS, and innerText reports the rendered form.
    expect(text).toMatch(/GPT-5\.4/i);
    expect(text).toMatch(/Claude Sonnet 5/i);
    // The registry id for this model carries a date suffix; a badge showing one
    // means the display-name lookup was bypassed somewhere.
    expect(text).not.toMatch(/claude-[a-z]+-\d/);
  });

  test("selecting a node expands it in place", async ({ page }) => {
    const target = await clickableNode(page);
    const before = (await target.boundingBox())!.height;
    await target.click();
    await expect
      .poll(async () => (await target.boundingBox())!.height)
      .toBeGreaterThan(before);
  });

  test("repaints node colours when the theme is toggled", async ({ page }) => {
    // Regression: the sync effect only ran on structural changes, so a theme
    // swap repainted the canvas chrome but left the nodes in the old palette.
    const before = await nodeColors(page);
    await page.getByRole("button", { name: /Switch to (light|dark) theme/ }).click();
    await expect
      .poll(async () => (await nodeColors(page)).join())
      .not.toBe(before.join());
  });
});
