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
    // yanked the user out of the tree. The assertion is about the view, not
    // the (scripted) reply. A throwaway session, so this test never mutates
    // the reference thread.
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

  test("the landing page says what the app does, with its call to action above the fold", async ({
    page,
  }) => {
    await expect(page.getByText(/compare their answers side by side/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Debate" })).toBeVisible();
    await expect(page.getByText(/unbreakable academic/)).toHaveCount(0);
    await expect(page.getByText("Initialize New Experiment")).toHaveCount(0);
    // At the suite's 1280x720 viewport the button must be reachable without scrolling.
    await expect(page.getByRole("button", { name: "Start a session" })).toBeInViewport();

    // Feature tiles are real 40px squares, not stretched to the card width.
    const tile = page.getByRole("heading", { name: "Debate" }).locator("xpath=preceding-sibling::div[1]");
    const box = (await tile.boundingBox())!;
    expect(Math.round(box.width)).toBe(40);
    expect(Math.round(box.height)).toBe(40);

    await page.getByRole("button", { name: "Start a session" }).click();
    await expect(page.getByPlaceholder(/Ask the arena/i)).toBeVisible();
  });

  test("keyboard focus is visible on every tab stop", async ({ page }) => {
    await openThread(page, MAIN_THREAD_TITLE);
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    const unmarked: string[] = [];
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press("Tab");
      // Some controls transition "all" properties, the outline included.
      await page.waitForTimeout(300);
      const info = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const s = getComputedStyle(el);
        const ring = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2;
        // Text fields mark focus with their own border instead.
        const field = el.tagName === "INPUT" || el.tagName === "TEXTAREA";
        return ring || field ? null : `${el.tagName} ${el.getAttribute("aria-label") ?? el.innerText.slice(0, 30)}`;
      });
      if (info) unmarked.push(info);
    }
    expect(unmarked).toEqual([]);
  });

  test("controls are named and real buttons; labels are at least 11px", async ({ page }) => {
    await openThread(page, MAIN_THREAD_TITLE);
    // Sidebar rows are <button>s, not focusable divs.
    const row = page.getByRole("button", { name: MAIN_THREAD_TITLE }).first();
    expect(await row.evaluate((el) => el.tagName)).toBe("BUTTON");

    const report = await page.evaluate(() => {
      const visible = (el: Element) => {
        const r = (el as HTMLElement).getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
      };
      const unnamed = [...document.querySelectorAll("button, [role=button]")]
        .filter(visible)
        .filter((el) => !el.closest(".react-flow__minimap"))
        .filter(
          (el) =>
            !(el.getAttribute("aria-label") || el.getAttribute("title") || (el as HTMLElement).innerText.trim()),
        )
        .map((el) => el.outerHTML.slice(0, 80));
      // Text outside the zoomable canvas, whose size scales with the zoom.
      const tiny: string[] = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const parent = walker.currentNode.parentElement;
        if (!parent || !walker.currentNode.textContent?.trim() || !visible(parent)) continue;
        if (parent.closest(".react-flow__viewport, .react-flow__minimap, .react-flow__attribution")) continue;
        const size = parseFloat(getComputedStyle(parent).fontSize);
        if (size < 11) tiny.push(`${size}px "${walker.currentNode.textContent.trim().slice(0, 30)}"`);
      }
      return { unnamed, tiny };
    });
    expect(report.unnamed).toEqual([]);
    expect(report.tiny).toEqual([]);
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
    for (const name of ["Claude Opus 5.5", "Claude Opus 5", "Claude Sonnet 5"]) {
      await expect(page.getByText(name, { exact: true })).toBeVisible();
    }

    const body = await page.locator("body").innerText();
    expect(body).not.toContain("gpt-5.4-pro");
    expect(body).not.toContain("gemini-3-flash-lite-preview");
  });
});
