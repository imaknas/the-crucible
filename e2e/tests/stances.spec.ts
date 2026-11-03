import { test, expect } from "@playwright/test";
import { addModel, debateStatus, newSession, openApp, showTree } from "./helpers";

// A debate with assigned sides, end to end: chosen in the dialog, argued
// round by round, and labelled as assigned wherever the person reads it.
test("a debate with assigned sides says who argued what, and that round 1 is opening cases", async ({ page }) => {
  await openApp(page);
  await addModel(page, "Anthropic", "Claude Sonnet 5.5");
  await newSession(page);
  await page.getByRole("button", { name: "Arena", exact: true }).click();
  await page.getByPlaceholder(/Ask the arena/i).fill("Should the office have a four-day week?");
  await page.getByRole("button", { name: "Start debate" }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Max rounds").fill("2");
  await dialog.getByRole("combobox", { name: "How they argue" }).click();
  await page.getByRole("option", { name: "Assigned sides" }).click();
  await expect(dialog.getByRole("combobox", { name: "Agreement judge" })).toHaveCount(0);
  await dialog.getByLabel("Side 1").fill("Yes, four days");
  await dialog.getByLabel("Side 2").fill("No, keep five");
  await dialog.getByRole("button", { name: "Start Debate" }).click();

  await page.getByRole("button", { name: "Arena", exact: true }).click();
  await expect(debateStatus(page)).toHaveText("completed", { timeout: 40_000 });
  await expect(page.getByText("Round 1 · opening cases")).toBeVisible();
  const legend = page.getByLabel("Who each participant is");
  await expect(legend).toContainText("assigned to argue: Yes, four days");
  await expect(legend).toContainText("assigned to argue: No, keep five");

  // The tree's lanes say it too, and round 1's band.
  await showTree(page);
  await expect(page.getByTestId("lane-stance")).toHaveCount(2);
  await expect(page.getByTestId("lane-stance").first()).toContainText("assigned to argue");
  await expect(page.getByText("Round 1 · opening", { exact: true })).toBeVisible();
});
