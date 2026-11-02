import { test, expect } from "@playwright/test";
import { SUMMARIZED_THREAD_TITLE, openApp } from "./helpers";

// What a turn was written from: the fixture's summarized thread has two
// summaries, and its later replies were written from them with excerpts
// recall brought back (e2e/seed_db.py).
test.describe("visible context", () => {
  test.beforeEach(async ({ page }) => {
    await openApp(page);
    const history = page.waitForResponse((r) => r.url().includes("/history/") && r.status() === 200);
    await page.getByRole("button", { name: SUMMARIZED_THREAD_TITLE }).first().click();
    await history;
  });

  test("a summary is a marker that opens the summary", async ({ page }) => {
    const markers = page.getByTestId("summary-marker");
    await expect(markers).toHaveCount(2);
    const toggle = markers.first().getByRole("button", { name: /Earlier messages summarized/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(markers.first().getByText(/written from this summary/)).toBeVisible();
  });

  test("a reply says it was written from the summary and lists what recall brought back", async ({ page }) => {
    const note = page.getByTestId("reply-context").last();
    const toggle = note.getByRole("button", { name: /Written from the summary.*recall brought back 4 earlier messages/ });
    await toggle.scrollIntoViewIfNeeded();
    await toggle.click();
    await expect(note.locator("li")).toHaveCount(4);
  });

  test("the branch chip says what the next turn sends", async ({ page }) => {
    await expect(page.getByTestId("branch-inherits")).toHaveText(/Sends 16 messages · ~\d+ tokens/);
  });
});
