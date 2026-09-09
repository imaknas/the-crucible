import { test, expect } from "@playwright/test";
import { MAIN_THREAD_TITLE, openApp, openThread, nodes, showTree } from "./helpers";

test.describe("application shell", () => {
  test.beforeEach(async ({ page }) => {
    await openApp(page);
  });

  test("reports real connection and key status in the header", async ({ page }) => {
    // Regression: this slot used to read "Quantum Nexus Online", which said
    // nothing about whether the app could actually run.
    await expect(page.getByText(/keys? · connected/i)).toBeVisible();
    await expect(page.getByText("Quantum Nexus Online")).toHaveCount(0);
  });

  test("uses plain labels rather than themed vocabulary", async ({ page }) => {
    await openThread(page, MAIN_THREAD_TITLE);
    await expect(page.getByText("Models in this arena")).toBeVisible();
    await expect(page.getByText("Available models")).toBeVisible();
    await expect(page.getByText("Search my documents")).toBeVisible();
    for (const gone of ["Active Council", "Council Members", "Deep Knowledge Search"]) {
      await expect(page.getByText(gone, { exact: true })).toHaveCount(0);
    }
  });

  test("the view control states the current view and both halves work", async ({
    page,
  }) => {
    await openThread(page, MAIN_THREAD_TITLE);
    const tree = page.getByRole("button", { name: "Tree", exact: true });
    const arena = page.getByRole("button", { name: "Arena", exact: true });

    await expect(tree).toHaveAttribute("aria-pressed", "true");
    await expect(arena).toHaveAttribute("aria-pressed", "false");

    await arena.click();
    await expect(arena).toHaveAttribute("aria-pressed", "true");
    await expect(nodes(page)).toHaveCount(0);

    await tree.click();
    await expect(tree).toHaveAttribute("aria-pressed", "true");
    await expect(nodes(page).first()).toBeVisible();
  });

  test("stays in the tree when a message is sent", async ({ page }) => {
    // Regression: handleSendMessage used to call setShowTree(false), so sending
    // yanked the user out of the tree. The models are stubbed in this fixture,
    // so the request fails — the assertion is about the view, not the reply.
    // A throwaway session, so this test never mutates the reference thread.
    await page.getByRole("button", { name: "New Session" }).click();
    await showTree(page);
    const tree = page.getByRole("button", { name: "Tree", exact: true });
    await expect(tree).toHaveAttribute("aria-pressed", "true");

    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await page.getByPlaceholder(/Ask the arena/i).fill("does the view move?");
    await page.keyboard.press("Enter");

    // Still in Arena — sending must not change the view in either direction.
    await expect(
      page.getByRole("button", { name: "Arena", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  test("collapses the control panel and remembers the choice", async ({ page }) => {
    const widthOf = () =>
      page.evaluate(() => {
        const panes = [...document.querySelectorAll(".MuiDrawer-paper")];
        return Math.round(panes[panes.length - 1].getBoundingClientRect().width);
      });

    expect(await widthOf()).toBe(280);

    await page.getByRole("button", { name: "Hide settings panel" }).click();
    await expect.poll(widthOf).toBe(44);

    // Survives a reload, so the preference is persisted rather than in state.
    await page.reload();
    await expect(
      page.getByRole("button", { name: "Show settings panel" }),
    ).toBeVisible();
    expect(await widthOf()).toBe(44);

    await page.getByRole("button", { name: "Show settings panel" }).click();
    await expect.poll(widthOf).toBe(280);
  });

  test("explains an empty canvas instead of rendering a void", async ({ page }) => {
    await page.getByRole("button", { name: "New Session" }).click();
    await showTree(page);
    await expect(page.getByText("No checkpoints yet")).toBeVisible();
  });

  test("lists the verified model catalogue", async ({ page }) => {
    // Guards the registry refresh: names come from MODEL_REGISTRY, and the two
    // IDs that 404 on the providers must not reappear.
    await page.getByRole("button", { name: /^Anthropic \d+ models$/ }).click();
    await expect(page.getByText("Claude Opus 5")).toBeVisible();
    await expect(page.getByText("Claude Sonnet 5")).toBeVisible();

    const body = await page.locator("body").innerText();
    expect(body).not.toContain("gpt-5.4-pro");
    expect(body).not.toContain("gemini-3-flash-lite-preview");
  });
});
