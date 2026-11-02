import { test, expect, type Page } from "@playwright/test";
import {
  MAIN_THREAD_TITLE,
  SUMMARIZED_THREAD_TITLE,
  ensureDetailZoom,
  nodes,
  openApp,
  showTree,
  waitForCanvasIdle,
} from "./helpers";

async function openInTree(page: Page, title: string) {
  await openApp(page);
  const history = page.waitForResponse((r) => r.url().includes("/history/") && r.status() === 200);
  await page.getByRole("button", { name: title }).first().click();
  await history;
  await showTree(page);
  await expect(nodes(page).first()).toBeVisible();
  await waitForCanvasIdle(page);
  await ensureDetailZoom(page);
}

/** The node the arrow keys are on (its dashed focus ring). */
const focusedNode = (page: Page) => page.locator(".react-flow__node:has(> div[style*='dashed'])");

// The summarized fixture thread is one long line of turns: room to move,
// name, fold and compress without touching what other specs read.
test.describe("moving around a big tree", () => {
  test("arrow keys move a focus without choosing it; Enter chooses it", async ({ page }) => {
    await openInTree(page, SUMMARIZED_THREAD_TITLE);
    const canvas = page.getByTestId("tree-canvas");
    await canvas.focus();
    await page.keyboard.press("Home");
    await expect(focusedNode(page)).toContainText("Start");
    await page.keyboard.press("ArrowDown");
    await expect(focusedNode(page)).toContainText("Turn 1:");
    await page.keyboard.press("ArrowDown");
    await expect(focusedNode(page)).toContainText("Branching a conversation tree");
    // Moving the focus chose nothing: the next message still continues the latest turn.
    await expect(page.getByText("Latest turn")).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Latest turn")).toHaveCount(0);
  });

  test("a branch is named, bookmarked, compressed into a summary and opened again", async ({ page }) => {
    await openInTree(page, SUMMARIZED_THREAD_TITLE);
    await page.getByTestId("tree-canvas").focus();
    await page.keyboard.press("Home");
    await page.keyboard.press("ArrowDown");
    const node = focusedNode(page);
    await expect(node).toContainText("Turn 1:");
    const menu = async (item: RegExp | string) => {
      await node.getByRole("button", { name: "More actions" }).click();
      await page.getByRole("menuitem", { name: item }).click();
    };

    await menu(/Name this branch/);
    await page.getByLabel("Branch name").fill("Recall study");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(node).toContainText("Recall study");

    await menu("Bookmark");
    await expect(page.getByRole("navigation", { name: "Bookmarks" })).toContainText("Recall study");

    const before = await nodes(page).count();
    await menu(/Compress into a summary/);
    await expect(node.getByTestId("subtree-summary")).toBeVisible();
    const expand = node.getByRole("button", { name: /^Show \d+ hidden messages$/ });
    await expect(expand).toBeVisible();
    await expect.poll(() => nodes(page).count()).toBeLessThan(before);

    await expand.click();
    await expect(nodes(page)).toHaveCount(before);

    // Undone the same way, which leaves the fixture as it was for a rerun.
    // The node expanded is still the one in view.
    await expect(node.getByRole("button", { name: "More actions" })).toBeInViewport();
    await menu("Remove the summary");
    await expect(node.getByTestId("subtree-summary")).toHaveCount(0);
    await menu("Remove bookmark");
    await expect(page.getByRole("navigation", { name: "Bookmarks" })).toHaveCount(0);
    await menu(/Rename branch/);
    await page.getByLabel("Branch name").fill("");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(node).not.toContainText("Recall study");
  });

  test("a branch shown alone, and the way back to the whole tree", async ({ page }) => {
    await openInTree(page, SUMMARIZED_THREAD_TITLE);
    await page.getByTestId("tree-canvas").focus();
    for (const key of ["Home", "ArrowDown", "ArrowDown", "ArrowDown"]) await page.keyboard.press(key);
    await expect(focusedNode(page)).toContainText("Turn 2:");
    const before = await nodes(page).count();
    await focusedNode(page).getByRole("button", { name: "More actions" }).click();
    await page.getByRole("menuitem", { name: "Show only this branch" }).click();
    await expect(page.getByTestId("hoist-bar")).toBeVisible();
    await expect.poll(() => nodes(page).count()).toBeLessThan(before);
    await page.getByTestId("hoist-bar").getByText("Show whole tree").click();
    await expect(nodes(page)).toHaveCount(before);
  });
});

test("text selected in a reply branches from that reply, quoted in the composer", async ({ page }) => {
  await openApp(page);
  const history = page.waitForResponse((r) => r.url().includes("/history/") && r.status() === 200);
  await page.getByRole("button", { name: MAIN_THREAD_TITLE }).first().click();
  await history;
  const reply = page.locator("[data-message-id]").filter({ hasText: "compare model answers" }).first();
  await expect(reply).toBeVisible();
  await reply.evaluate((body) => {
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    let text = walker.nextNode();
    while (text && !text.textContent?.includes("compare model answers")) text = walker.nextNode();
    const start = text!.textContent!.indexOf("compare model answers");
    const range = document.createRange();
    range.setStart(text!, start);
    range.setEnd(text!, start + "compare model answers".length);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    body.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
  await page.getByTestId("branch-from-span").click();
  await expect(page.getByPlaceholder(/Ask the arena/i)).toHaveValue("> compare model answers\n\n");
  await expect(page.getByTestId("branch-chip")).toContainText("Branching from");
});
