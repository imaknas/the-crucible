import { test, expect, type Page } from "@playwright/test";
import { MAIN_THREAD_TITLE, openApp, textContrast } from "./helpers";

/**
 * Colours as the browser paints them. Each of these was wrong once: the
 * workspace drawn in the text colour, the "You" bubble a white box with a
 * near-black border (palette shades the theme never defined), and blue text
 * and buttons under 4.5:1 in both themes.
 */

const AA = 4.5;

async function openArena(page: Page, scheme: "light" | "dark") {
  await page.emulateMedia({ colorScheme: scheme });
  await openApp(page);
  await page.getByRole("button", { name: MAIN_THREAD_TITLE }).first().click();
  const arena = page.getByRole("button", { name: "Arena", exact: true });
  if ((await arena.getAttribute("aria-pressed")) !== "true") await arena.click();
  await expect(page.getByText("You", { exact: true }).first()).toBeVisible();
  // The theme follows the system's scheme until the person picks one.
  const body = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(body).toBe(scheme === "dark" ? "rgb(10, 15, 30)" : "rgb(248, 250, 252)");
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.beforeEach(async ({ page }) => openArena(page, scheme));

    test("primary text and filled buttons reach AA", async ({ page }) => {
      const checks = {
        "New Session": page.getByRole("button", { name: "New Session" }).first(),
        "the open session's title": page.locator('nav[aria-label="Sessions"] [aria-current="page"]').first(),
        "the You label": page.getByText("You", { exact: true }).first(),
        "the Sessions title": page.getByRole("heading", { name: "Sessions" }),
      };
      for (const [what, locator] of Object.entries(checks)) {
        expect(await textContrast(locator), what).toBeGreaterThanOrEqual(AA);
      }
      await page.getByPlaceholder(/Ask the arena/i).fill("Something to send");
      const send = page.getByTestId("composer-toolbar").getByRole("button", { name: "Send" });
      expect(await textContrast(send), "Send").toBeGreaterThanOrEqual(AA);
    });
  });
}

test("the workspace is outlined in the divider colour, not the text colour", async ({ page }) => {
  await openArena(page, "light");
  const main = page.locator("main");
  const [border, text] = await main.evaluate((el) => [
    getComputedStyle(el).borderTopColor,
    getComputedStyle(document.body).color,
  ]);
  expect(border).toBe("rgb(226, 232, 240)"); // slate-200, the theme's divider
  expect(border).not.toBe(text);
});

test("the person's message is a tinted bubble, not a white box with a dark border", async ({ page }) => {
  await openArena(page, "light");
  const bubble = page.getByText("You", { exact: true }).first().locator("xpath=ancestor::*[contains(@class,'MuiPaper-root')][1]");
  const style = await bubble.evaluate((el) => ({
    bg: getComputedStyle(el).backgroundColor,
    border: getComputedStyle(el).borderTopColor,
  }));
  expect(style.bg).not.toBe("rgb(255, 255, 255)");
  expect(style.bg).not.toBe("rgba(0, 0, 0, 0)");
  expect(style.border).not.toBe("rgb(15, 23, 42)");
});
