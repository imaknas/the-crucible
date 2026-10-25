import { test, expect } from "@playwright/test";
import { openApp } from "./helpers";

/**
 * Narrow screens: the sessions sidebar and the settings panel are overlay
 * drawers opened from the header. With both docked, the composer was 4px wide
 * at 820px and the app was unusable on a phone.
 */
for (const viewport of [
  { width: 390, height: 844 },
  { width: 820, height: 1180 },
]) {
  test.describe(`at ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test("creates a session and sends a message", async ({ page }) => {
      await page.goto("/");
      await page.evaluate(() => localStorage.clear());
      await page.reload();

      // Both panels start closed, leaving the main pane the full width.
      await page.getByRole("button", { name: "Open sessions" }).click();
      await page.getByRole("button", { name: "New Session" }).click();
      // Picking something closes the drawer.
      await expect(page.getByRole("button", { name: "Close sessions" })).toBeHidden();

      await page.getByRole("button", { name: "Arena", exact: true }).click();
      const composer = page.getByPlaceholder(/Ask the arena/i);
      const box = (await composer.boundingBox())!;
      expect(box.width).toBeGreaterThan(viewport.width * 0.5);

      await composer.fill("Hello from a small screen");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByText(/Scripted answer from gpt-6\.1-sol/).first()).toBeVisible();

      // The settings drawer opens from the header too.
      await page.getByRole("button", { name: "Open settings" }).click();
      await expect(page.getByText("Available models")).toBeVisible();
      await page.getByRole("button", { name: "Close settings" }).click();
      await expect(page.getByText("Available models")).toBeHidden();

      // Nothing scrolls sideways.
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  });
}

test("the docked sidebar collapses to a rail and remembers it", async ({ page }) => {
  await openApp(page);
  await page.getByRole("button", { name: "Collapse sessions" }).click();
  await expect(page.getByRole("button", { name: "Expand sessions" })).toBeVisible();
  // The rail keeps New Session one click away.
  await expect(page.getByRole("button", { name: "New Session" })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("button", { name: "Expand sessions" })).toBeVisible();
  await page.getByRole("button", { name: "Expand sessions" }).click();
  await expect(page.getByRole("button", { name: "Collapse sessions" })).toBeVisible();
});
