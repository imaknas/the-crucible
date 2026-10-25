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

const GPT = "gpt-6.1-sol";
const CLAUDE = "claude-sonnet-5-5";
const answerFrom = (id: string) => new RegExp(`Scripted answer from ${id.replace(".", "\\.")}`);

test.describe("live flows (scripted models)", () => {
  test.beforeEach(async ({ page }) => {
    await openApp(page);
    await newSession(page);
  });

  test("two models answer in parallel, each on its own branch", async ({ page, request }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, "Compare the two approaches");

    await expect(page.getByText(answerFrom(GPT))).toBeVisible();
    await expect(page.getByText(answerFrom(CLAUDE))).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
    // Replies are labelled with display names, never a reshuffled raw ID.
    await expect(page.getByText(/^Claude Sonnet 5\.5$/i).first()).toBeVisible();
    await expect(page.getByText(/claude sonnet 5 5/i)).toHaveCount(0);

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

  test("a multi-model selection survives the refresh after each turn", async ({ page, request }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    const idle = () => expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);

    await send(page, "First question");
    await expect(page.getByText(answerFrom(CLAUDE)).first()).toBeVisible();
    await idle();
    // The post-stream history refresh used to reset the selection to one model.
    await expect(page.getByText("2 models", { exact: true })).toBeVisible();

    await send(page, "Second question");
    await idle();
    await expect(page.getByText("2 models", { exact: true })).toBeVisible();

    const threadId = await currentThreadId(page);
    await expect
      .poll(async () => {
        const tree = await (await request.get(`${BACKEND_URL}/history/${threadId}`)).json();
        const labels: string[] = tree.nodes.map((n: { data?: { label?: string } }) => n.data?.label ?? "");
        return [GPT, CLAUDE].map((id) => labels.filter((l) => answerFrom(id).test(l)).length);
      })
      .toEqual([2, 2]);
  });

  test("a new session appears in the sidebar under its title without a reload", async ({ page }) => {
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    const title = `Sidebar title check ${Date.now() % 100000}`;
    await send(page, title);
    await expect(page.getByRole("button", { name: title, exact: false }).first()).toBeVisible();
  });

  test("a debate started from a new session is listed under a readable title", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    const prompt = `Listed debate ${Date.now() % 100000}`;
    await startDebate(page, prompt, 1);
    await expect(
      page.getByRole("button", { name: `Debate: ${prompt}`, exact: false }).first(),
    ).toBeVisible();
  });

  test("the debate dialog shows what it will start, and cancelling keeps the prompt", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    const composer = page.getByPlaceholder(/Ask the arena/i);
    await composer.fill("Should we rewrite it in Rust?");
    await page.getByRole("button", { name: "Start debate" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Should we rewrite it in Rust?")).toBeVisible();
    await expect(dialog.getByText("Claude Sonnet 5.5")).toBeVisible();
    // Typing a two-digit count over the default must not be clamped mid-way.
    const rounds = dialog.getByLabel("Max rounds");
    await rounds.fill("");
    await rounds.pressSequentially("10");
    await expect(rounds).toHaveValue("10");

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(composer).toHaveValue("Should we rewrite it in Rust?");
  });

  test("composer actions say why they are disabled, and Deliberate works with an empty box", async ({
    page,
    request,
  }) => {
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    const deliberate = page.getByRole("button", { name: "Deliberate" });
    await expect(deliberate).toBeDisabled();
    await deliberate.locator("..").hover();
    await expect(page.getByRole("tooltip")).toContainText("send a message first");

    await send(page, "Explain monads briefly");
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
    await expect(page.getByText(answerFrom(GPT)).first()).toBeVisible();

    // An empty box asks for a plain review instead of doing nothing.
    await expect(deliberate).toBeEnabled();
    await deliberate.click();
    const threadId = await currentThreadId(page);
    await expect
      .poll(async () => {
        const tree = await (await request.get(`${BACKEND_URL}/history/${threadId}`)).json();
        return tree.nodes.filter((n: { data?: { label?: string } }) => answerFrom(GPT).test(n.data?.label ?? "")).length;
      })
      .toBe(2);
  });

  test("a chat synthesis is written by the chosen model and shown as a synthesis", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, "Rust or Go for a CLI?");
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);

    await expect(page.getByText("Synthesize answers")).toBeVisible();
    await page.getByLabel("Synthesis written by").click();
    await page.getByRole("option", { name: "Claude Sonnet 5.5" }).click();
    await page.getByText("Synthesize answers").click();

    await expect(page.getByText(/^Synthesis · Claude Sonnet 5\.5$/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
    await showTree(page);
    await expect(page.locator(".react-flow__node-synthesis")).toHaveCount(1);
    await expect(page.locator(".react-flow__node-synthesis")).toContainText(/Synthesis · Claude Sonnet 5\.5/i);
  });

  test("a model that fails is shown inline with a Retry, not a modal over the other replies", async ({ page }) => {
    const sent: { model?: string; parent_checkpoint_id?: string | null }[] = [];
    page.on("websocket", (ws) => {
      if (!ws.url().includes("/ws/")) return;
      ws.on("framesent", (f) => {
        try {
          sent.push(JSON.parse(String(f.payload)));
        } catch {}
      });
    });
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, `Which is faster? [[fail:${CLAUDE}]]`);

    const error = page.getByTestId("model-error");
    await expect(error).toContainText(/Claude Sonnet 5\.5 didn.t answer/i);
    await expect(page.getByText(answerFrom(GPT)).first()).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    const before = sent.filter((f) => f.model === CLAUDE).length;
    await error.getByRole("button", { name: /Retry/ }).click();
    await expect.poll(() => sent.filter((f) => f.model === CLAUDE).length).toBe(before + 1);
    // The retry is pinned to the parent the first attempt forked from.
    const retry = sent.filter((f) => f.model === CLAUDE).at(-1)!;
    expect(retry.parent_checkpoint_id).toBeTruthy();
    // The scripted failure repeats, so the inline error comes back.
    await expect(page.getByTestId("model-error")).toBeVisible();
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
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await startDebate(page, "Is a hot dog a sandwich?", 3);

    // The debated question heads the transcript.
    await expect(page.getByText("Is a hot dog a sandwich?").first()).toBeVisible();

    await page.getByRole("button", { name: "Pause debate" }).click();
    await expect(debateStatus(page)).toHaveText("pausing after this round");
    await expect(debateStatus(page)).toHaveText("paused");
    // Held: the next round does not start while paused.
    await page.waitForTimeout(1500);
    await expect(page.getByText("DEBATE · ROUND 1/3")).toBeVisible();
    // The sidebar row reports the live status, not the server's "running".
    await expect(
      page.locator('[aria-current="true"]').getByText("paused", { exact: true }),
    ).toBeVisible();

    // While paused, Send injects into the next round rather than chatting.
    await page.getByPlaceholder(/Ask the arena/i).fill("Consider street food law");
    await page.getByRole("button", { name: "Inject into debate" }).click();
    await expect(page.getByText(/Inject:/)).toBeVisible();

    // The controls are reachable from the tree view too.
    await showTree(page);
    await expect(page.getByRole("button", { name: "Resume debate" })).toBeVisible();
    await page.getByRole("button", { name: "Arena", exact: true }).click();

    await page.getByRole("button", { name: "Resume debate" }).click();
    await expect(page.getByText("DEBATE · ROUND 2/3")).toBeVisible();
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 30_000 });
    await expect(page.getByText(answerFrom(CLAUDE)).first()).toBeVisible();
  });

  test("a model that fails mid-debate is closed out, not left spinning", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
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
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
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
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
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

  test("a document upload passes the backend's preflight guard", async ({ page }) => {
    // The upload is a multipart POST, which the backend refuses without the
    // client header; sending that header makes the browser preflight it.
    const upload = page.waitForResponse(
      (res) => res.url().endsWith("/upload") && res.request().method() === "POST",
    );
    await page.locator('input[type="file"]').setInputFiles({
      name: "e2e-notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Notes for the arena."),
    });
    expect((await upload).status()).toBe(200);
    await expect(page.getByRole("button", { name: "e2e-notes.txt" })).toBeVisible();
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
