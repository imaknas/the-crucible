import { test, expect } from "@playwright/test";
import { addModel, newSession, openApp, send } from "./helpers";

// Blind comparison end to end: lettered cards while they stream, a vote
// that reveals who wrote which, and the win rates it adds to.
test("a blind turn is voted on, revealed and counted", async ({ page }) => {
  await openApp(page);
  await addModel(page, "Anthropic", "Claude Sonnet 5.5");
  await page.getByRole("switch", { name: "Blind comparison" }).click();
  await newSession(page);
  await page.getByRole("button", { name: "Arena", exact: true }).click();
  await send(page, "Which colour is warmer?");

  const cards = page.getByTestId("turn-cards").getByRole("article");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toHaveAttribute("aria-label", "Answer A's answer");
  await expect(cards.nth(1)).toHaveAttribute("aria-label", "Answer B's answer");
  await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
  // Nothing the UI puts on a card names a model, not even a tooltip. (The
  // fake model's own text says who wrote it: that is the fixture, not the UI.)
  await expect(page.getByTestId("turn-cards").locator("[title*='gpt' i], [title*='claude' i]")).toHaveCount(0);
  await expect(page.getByTestId("turn-cards").locator("[aria-label*='gpt' i], [aria-label*='claude' i]")).toHaveCount(0);

  const bar = page.getByTestId("vote-bar");
  await bar.getByRole("button", { name: "Answer A is best" }).click();
  await bar.getByLabel("Why (optional)").fill("warmer reasoning");
  await bar.getByRole("button", { name: "Vote and reveal" }).click();

  const summary = page.getByTestId("vote-summary");
  await expect(summary).toContainText(/You voted (GPT-6\.1 Sol|Claude Sonnet 5\.5) best \(it was Answer A\)/);
  // Revealed: the cards carry the models' names again.
  await expect(cards.filter({ has: page.locator("[aria-label]") }).first()).toBeVisible();
  await expect(page.getByRole("article", { name: "GPT-6.1 Sol's answer" })).toBeVisible();
  await expect(page.getByTestId("win-rates")).toContainText("100%");

  // The vote stays with the turn after a reload, and can be changed.
  await page.reload();
  await expect(page.getByTestId("vote-summary")).toBeVisible();
  await page.getByRole("button", { name: "Change vote" }).click();
  await page.getByTestId("vote-bar").getByRole("button", { name: "Tie" }).click();
  await page.getByTestId("vote-bar").getByRole("button", { name: "Vote", exact: true }).click();
  await expect(page.getByTestId("vote-summary")).toContainText("You voted a tie");

  // Leave blind comparison off for the specs after this one.
  await page.getByRole("switch", { name: "Blind comparison" }).click();
});
