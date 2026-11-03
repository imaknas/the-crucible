import { test, expect } from "@playwright/test";
import { BACKEND_URL, addModel, currentThreadId, newSession, openApp, send } from "./helpers";

/**
 * Saved cases with scripted models (CRUCIBLE_FAKE_LLM): replies read
 * "Scripted answer from <id>". A turn is saved as a case, opened from the
 * sidebar and replayed on its own model and a new one, old against new.
 */

const GPT = "gpt-6.1-sol";
const answerFrom = (id: string) => new RegExp(`Scripted answer from ${id.replace(/\./g, "\\.")}`);

test("a turn saved as a case replays on another model, old against new, and its thread is untouched", async ({
  page,
  request,
}) => {
  await openApp(page);
  await newSession(page);
  await addModel(page, "Anthropic", "Claude Sonnet 5.5");
  await page.getByRole("button", { name: "Arena", exact: true }).click();
  await send(page, "Name a colour for the case");
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0, { timeout: 30_000 });
  const source = await currentThreadId(page);
  const before = (await (await request.get(`${BACKEND_URL}/history/${source}`)).json()).nodes.length;

  await page.getByRole("button", { name: "Save as a case" }).click();
  await expect(page.getByText("Case saved")).toBeVisible();

  await page.getByRole("button", { name: "Saved cases" }).first().click();
  const list = page.getByRole("dialog", { name: "Saved cases" });
  await list.getByRole("button", { name: /^Name a colour for the case/ }).first().click();
  const dialog = page.getByRole("dialog", { name: "Name a colour for the case" });
  await expect(dialog.getByRole("region", { name: "The case's answers" }).getByRole("article")).toHaveCount(2);

  // Keep GPT (compared with its own answer), drop Claude, add a Gemini model.
  const picker = dialog.getByRole("group", { name: "Models to replay on" });
  await expect(picker.getByRole("checkbox", { name: "GPT-6.1 Sol" })).toBeChecked();
  await picker.getByRole("checkbox", { name: "Claude Sonnet 5.5" }).uncheck();
  const gemini = picker.locator('label[title^="gemini"]').first();
  const geminiId = (await gemini.getAttribute("title"))!;
  await gemini.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Replay on 2 models" }).click();

  const replay = dialog.getByRole("region", { name: /^Replay · / });
  await expect(replay).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Replay finished")).toBeVisible();
  const gptCard = replay.getByRole("article").filter({ hasText: answerFrom(GPT) });
  await expect(gptCard).toContainText("Against its own answer in the case");
  await expect(gptCard.getByTestId("reply-metrics")).toBeVisible();
  const geminiCard = replay.getByRole("article").filter({ hasText: answerFrom(geminiId) });
  // Nobody voted, so a model new to the case has nothing to be compared with.
  await expect(geminiCard).toContainText("Nothing to compare with");
  await expect(replay.getByTestId("turn-metrics")).toBeVisible();
  // Answers are named by display name; the raw ids stay in tooltips (the scripted text itself quotes them).
  const names = await replay.getByRole("article").evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")));
  expect(names).toContain("GPT-6.1 Sol's answer");
  expect(names.join(" ")).not.toContain(geminiId);

  await gptCard.getByRole("button", { name: "Show changes" }).click();
  await expect(replay.getByTestId("diff-summary")).toBeVisible();
  await expect(replay.getByText(/GPT-6\.1 Sol \(case\)/)).toBeVisible();

  // The source thread is as it was; the replay ran in its own thread.
  const after = (await (await request.get(`${BACKEND_URL}/history/${source}`)).json()).nodes.length;
  expect(after).toBe(before);
  const cases = (await (await request.get(`${BACKEND_URL}/cases`)).json()).cases;
  const saved = cases.find((c: { title: string }) => c.title === "Name a colour for the case");
  const full = await (await request.get(`${BACKEND_URL}/cases/${saved.case_id}`)).json();
  expect(full.replays[0].thread_id).not.toBe(source);
});
