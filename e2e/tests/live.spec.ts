import { test, expect } from "@playwright/test";
import {
  BACKEND_URL,
  MAIN_THREAD_TITLE,
  addModel,
  currentThreadId,
  debateStatus,
  newSession,
  nodes,
  openApp,
  send,
  showTree,
  startDebate,
} from "./helpers";

/**
 * Flows that stream from a model. The backend runs with CRUCIBLE_FAKE_LLM, so
 * every model is a scripted fake: replies read "Scripted answer from <id>",
 * "[[slow]]" in a prompt holds the stream open, and "[[fail:<id>]]" makes that
 * model raise. Each test works in a fresh session.
 */

const GPT = "gpt-5.4";
const CLAUDE = "claude-sonnet-5";
const answerFrom = (id: string) => new RegExp(`Scripted answer from ${id.replace(".", "\\.")}`);

test.describe("live flows (scripted models)", () => {
  test.beforeEach(async ({ page }) => {
    await openApp(page);
    await newSession(page);
  });

  test("two models answer in parallel, each on its own branch", async ({ page, request }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, "Compare the two approaches");

    await expect(page.getByText(answerFrom(GPT))).toBeVisible();
    await expect(page.getByText(answerFrom(CLAUDE))).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);

    // Regression guard for parallel-run isolation: each model's branch holds
    // exactly one prompt and its own reply, never the other model's turn.
    const threadId = await currentThreadId(page);
    const tree = await (await request.get(`${BACKEND_URL}/history/${threadId}`)).json();
    const answerIds: string[] = tree.nodes
      .filter((n: { data?: { label?: string } }) => /Scripted answer/.test(n.data?.label ?? ""))
      .map((n: { id: string }) => n.id);
    expect(answerIds).toHaveLength(2);
    for (const id of answerIds) {
      const res = await request.get(
        `${BACKEND_URL}/history/${threadId}?checkpoint_id=${encodeURIComponent(id)}`,
      );
      const { messages } = await res.json();
      const users = messages.filter((m: { role: string }) => m.role === "user");
      const replies = messages.filter((m: { role: string }) => m.role === "assistant");
      expect(users.map((m: { content: string }) => m.content)).toEqual(["Compare the two approaches"]);
      expect(replies).toHaveLength(1);
    }
  });

  test("switching threads mid-stream does not leave the new thread loading", async ({ page }) => {
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, "[[slow]] take your time");
    await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible();

    await page.getByRole("button", { name: MAIN_THREAD_TITLE, exact: false }).first().click();
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
    await page.getByPlaceholder(/Ask the arena/i).fill("ready?");
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeEnabled();
  });

  test("a debate pauses between rounds, resumes, and completes", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5");
    await startDebate(page, "Is a hot dog a sandwich?", 3);

    await page.getByRole("button", { name: "Pause debate" }).click();
    await expect(debateStatus(page)).toHaveText("pausing after this round");
    await expect(debateStatus(page)).toHaveText("paused");
    // Held: the next round does not start while paused.
    await page.waitForTimeout(1500);
    await expect(page.getByText("DEBATE · ROUND 1/3")).toBeVisible();

    await page.getByRole("button", { name: "Resume debate" }).click();
    await expect(page.getByText("DEBATE · ROUND 2/3")).toBeVisible();
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 30_000 });
    await expect(page.getByText(answerFrom(CLAUDE)).first()).toBeVisible();
  });

  test("a model that fails mid-debate is closed out, not left spinning", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5");
    await startDebate(page, `Settle it [[fail:${CLAUDE}]]`, 1);

    await expect(page.getByText(/failed \(scripted/).first()).toBeVisible();
    await expect(page.getByText(/no response:/)).toBeVisible();
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 20_000 });

    await showTree(page);
    await expect(nodes(page).filter({ hasText: "Thinking…" })).toHaveCount(0);
    await expect(nodes(page).filter({ hasText: /Scripted answer/ })).toHaveCount(1);
  });

  test("a debate cut off by a reload is restored as interrupted and can be synthesized", async ({
    page,
    request,
  }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5");
    await startDebate(page, "Tabs or spaces?", 3);
    await expect(page.getByText("DEBATE · ROUND 2/3")).toBeVisible({ timeout: 20_000 });
    const sessionId = await page.evaluate(() => localStorage.getItem("crucible_active_debate"));

    await page.reload();
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await expect(debateStatus(page)).toHaveText("interrupted");
    // Nothing is running, so the composer must not offer to inject.
    await expect(page.getByRole("button", { name: "Inject into debate" })).toHaveCount(0);
    const before = await (await request.get(`${BACKEND_URL}/debate/sessions/${sessionId}`)).json();
    expect(before.status).toBe("interrupted");

    await page.getByRole("button", { name: "Synthesize" }).click();
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 20_000 });
    const after = await (await request.get(`${BACKEND_URL}/debate/sessions/${sessionId}/tree`)).json();
    expect(after.nodes.some((n: { id: string }) => /synthesis/i.test(n.id))).toBe(true);
  });

  test("a debate can be deleted from the sidebar", async ({ page, request }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5");
    await startDebate(page, "Delete me afterwards", 1);
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 20_000 });
    const sessionId = await page.evaluate(() => localStorage.getItem("crucible_active_debate"));

    const activeRow = page.locator('[aria-current="true"]').filter({
      has: page.getByRole("button", { name: "Delete debate" }),
    });
    await activeRow.getByRole("button", { name: "Delete debate" }).click();
    await page.getByRole("button", { name: "Confirm" }).click();

    await expect(activeRow).toHaveCount(0);
    await expect(page.getByText(/DEBATE · ROUND/)).toHaveCount(0);
    const res = await request.get(`${BACKEND_URL}/debate/sessions/${sessionId}`);
    expect(res.status()).toBe(404);
  });
});

test.describe("entry points", () => {
  test("?thread= opens that thread and is dropped from the URL", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    const res = await page.request.get(`${BACKEND_URL}/threads`);
    const main = (await res.json()).threads.find(
      (t: { title: string }) => t.title === MAIN_THREAD_TITLE,
    );

    await page.goto(`/?thread=${main.id}`);
    await expect(nodes(page).filter({ hasText: /What does branching buy me/ }).first()).toBeVisible();
    expect(new URL(page.url()).search).toBe("");
  });

  test("a rejected API key save explains why", async ({ page }) => {
    await openApp(page);
    await page.route("**/config/keys", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({
            status: 403,
            contentType: "application/json",
            body: JSON.stringify({ detail: "API key configuration is only available from localhost" }),
          })
        : route.continue(),
    );
    await page.getByRole("button", { name: /^OpenAI (SET|NOT SET)$/i }).click();
    await page
      .getByPlaceholder(/Enter new key to replace|Paste your OpenAI API key/)
      .filter({ visible: true })
      .fill("sk-test-value");
    await page.getByRole("button", { name: "Save Keys" }).click();
    // Next.js renders its own (empty) route announcer with role=alert.
    await expect(
      page.getByRole("alert").filter({ hasText: /only available from localhost/ }),
    ).toBeVisible();
  });
});
