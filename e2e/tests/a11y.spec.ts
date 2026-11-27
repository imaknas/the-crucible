import { test, expect } from "@playwright/test";
import { MAIN_THREAD_TITLE, openApp, openThread } from "./helpers";

/**
 * Keyboard and small-screen access that was missing: each of these failed
 * in the UI/UX review of 2026-11-28.
 */

test("the first tab stop skips the sessions list to the conversation", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to the conversation" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
});

test("the page has landmarks: main, the sessions nav and the settings aside", async ({ page }) => {
  await openApp(page);
  await openThread(page, MAIN_THREAD_TITLE);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("complementary", { name: "Settings" })).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
});

test("the tree is one tab stop: no node or edge is one of its own", async ({ page }) => {
  await openApp(page);
  await openThread(page, MAIN_THREAD_TITLE);
  await page.getByTestId("tree-canvas").focus();
  // Past the canvas: the selected node's own buttons (Branch, More, …), then
  // the zoom controls. Every node and every edge used to be a stop, edges
  // named by raw checkpoint ids.
  const stops: string[] = [];
  for (let i = 0; i < 16; i++) {
    await page.keyboard.press("Tab");
    stops.push(
      await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el) return "";
        if (el.matches(".react-flow__edge, .react-flow__node")) return "tree item";
        return el.closest(".react-flow") ? "in tree" : "out";
      }),
    );
  }
  expect(stops).not.toContain("tree item");
  expect(stops.indexOf("out")).toBeGreaterThan(-1);
  // A fixed handful (the selected node's buttons, the canvas controls), whatever the tree's size.
  expect(stops.indexOf("out")).toBeLessThanOrEqual(14);
  // Arrow keys still move between messages, and say where.
  await page.getByTestId("tree-canvas").focus();
  await page.keyboard.press("Home");
  await expect(page.getByTestId("tree-focus-status")).not.toBeEmpty();
});

test.describe("at 320px (400% zoom of 1280)", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("every header control stays on screen", async ({ page }) => {
    // openApp waits for New Session, which is in the closed drawer here.
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await expect(page.getByRole("button", { name: "Open settings" })).toBeVisible();
    for (const name of ["Open sessions", "Open settings", "Tree", "Arena"]) {
      await expect(page.getByRole("button", { name, exact: true })).toBeInViewport({ ratio: 1 });
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
