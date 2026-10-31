import { test, expect } from "@playwright/test";
import {
  BACKEND_URL,
  MAIN_THREAD_TITLE,
  addModel,
  currentThreadId,
  debateStatus,
  ensureDetailZoom,
  newSession,
  nodes,
  openApp,
  send,
  showTree,
  startDebate,
  waitForCanvasIdle,
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

  test("a multi-model turn streams into cards that stay put when it settles", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, "[[slow]] Compare slowly");

    const cards = page.getByRole("article");
    await expect(cards).toHaveCount(2);
    // Streaming: each card says so, and Continue waits for its reply.
    await expect(page.locator('article[aria-busy="true"]').first()).toBeVisible();
    await expect(
      page.locator('article[aria-busy="true"]').first().getByRole("button", { name: /^Continue with/ }),
    ).toBeDisabled();
    // Measured from the question above, so scrolling doesn't count as moving.
    const question = page.locator("section").getByText("[[slow]] Compare slowly", { exact: true });
    const offset = async () => (await cards.first().boundingBox())!.y - (await question.boundingBox())!.y;
    // The question's bubble animates in when sent; measure once it has landed.
    await page.waitForTimeout(800);
    const before = await offset();
    // Tag the streaming cards' DOM nodes: settling must keep them, not remount them.
    await cards.evaluateAll((els) => els.forEach((el) => el.setAttribute("data-e2e-mark", "streamed")));

    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0, { timeout: 30_000 });
    await expect(cards).toHaveCount(2);
    await expect(page.locator('article[aria-busy="true"]')).toHaveCount(0);
    // The settled turn is the same two cards in the same place, not bubbles that collapsed.
    await expect(page.locator('article[data-e2e-mark="streamed"]')).toHaveCount(2);
    await expect.poll(async () => Math.abs((await offset()) - before)).toBeLessThan(4);
    await expect(cards.getByText(answerFrom(GPT))).toBeVisible();
    await expect(cards.getByText(answerFrom(CLAUDE))).toBeVisible();
    await expect(cards.first().getByRole("button", { name: /^Continue with/ })).toBeEnabled();
  });

  test("Stop marks every card still streaming as cut off", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, "[[slow]] take your time");
    await expect(page.getByRole("article")).toHaveCount(2);
    await page.getByRole("button", { name: "Stop generating" }).click();
    await expect(page.locator('article[data-state="stopped"]')).toHaveCount(2);
    await expect(page.getByText("Stopped before it finished: this reply is incomplete.").first()).toBeVisible();
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

  test("sending again after a multi-model turn continues each model's own conversation", async ({ page, request }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    const idle = () => expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);

    await send(page, "Opening question");
    await idle();
    await expect(page.getByTestId("branch-chip")).toContainText("Continuing the latest turn");
    await send(page, "Follow-up for both");
    await idle();

    // Each second answer follows its own model's first answer, not one model's.
    const threadId = await currentThreadId(page);
    const tree = await (await request.get(`${BACKEND_URL}/history/${threadId}`)).json();
    for (const model of [GPT, CLAUDE]) {
      const answers = tree.nodes.filter((n: { metadata?: { active_peer?: string; role?: string } }) =>
        n.metadata?.role === "ai" && n.metadata?.active_peer === model,
      );
      expect(answers).toHaveLength(2);
      type PathMessage = { role: string; model?: string };
      const paths: PathMessage[][] = await Promise.all(
        answers.map(async (n: { id: string }) => {
          const res = await request.get(`${BACKEND_URL}/history/${threadId}?checkpoint_id=${encodeURIComponent(n.id)}`);
          return (await res.json()).messages as PathMessage[];
        }),
      );
      const longest = paths.sort((a, b) => b.length - a.length)[0];
      const repliers = longest.filter((m) => m.role === "assistant").map((m) => m.model);
      expect(repliers.every((m) => m?.startsWith(model))).toBe(true);
    }
  });

  test("continuing a clicked reply asks its model alone, and the selection stays as set", async ({ page }) => {
    const sent: { model?: string; message?: string }[] = [];
    page.on("websocket", (ws) => {
      if (!/\/ws\/thread/.test(ws.url())) return;
      ws.on("framesent", (f) => {
        try {
          sent.push(JSON.parse(String(f.payload)));
        } catch {}
      });
    });
    // The chat socket opened in beforeEach; a fresh session opens one we observe.
    await newSession(page);
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    const idle = () => expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
    const askedWith = (message: string) =>
      sent.filter((f) => f.message === message).map((f) => f.model).sort();

    await send(page, "First question");
    await expect(page.getByText(answerFrom(CLAUDE)).first()).toBeVisible();
    await idle();

    await showTree(page);
    await waitForCanvasIdle(page);
    await ensureDetailZoom(page);
    const reply = nodes(page).filter({ hasText: answerFrom(CLAUDE) }).first();
    await reply.hover();
    await reply.getByRole("button", { name: "Branch from here" }).click();

    const chip = page.getByTestId("branch-chip");
    const askAll = chip.getByRole("button", { name: "Ask all 2 selected models instead" });
    await expect(askAll).toHaveText(/Only Claude Sonnet 5\.5/);
    await send(page, "Go on");
    await expect.poll(() => askedWith("Go on")).toEqual([CLAUDE]);
    await idle();

    // Still continuing Claude's thread; now every selected model answers from it.
    await askAll.click();
    await expect(chip.getByRole("button", { name: "Ask only Claude Sonnet 5.5 instead" })).toHaveText("All 2 answer");
    await send(page, "Everyone, go on");
    await expect.poll(() => askedWith("Everyone, go on")).toEqual([CLAUDE, GPT].sort());
    await idle();

    // The click never touched the Control Panel's selection, which is what a reload keeps.
    expect(JSON.parse((await page.evaluate(() => localStorage.getItem("crucible_selected_models")))!)).toEqual([
      GPT,
      CLAUDE,
    ]);
    await page.reload();
    await expect(page.getByText("2 models", { exact: true })).toBeVisible();
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
    // The chat socket opened in beforeEach; a fresh session opens one we observe.
    await newSession(page);
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

  test("the Control Panel's system prompt goes out with each turn and is remembered", async ({ page }) => {
    const sent: { message?: string; system_prompt?: string; toggles?: object }[] = [];
    page.on("websocket", (ws) => {
      if (!ws.url().includes("/ws/")) return;
      ws.on("framesent", (f) => {
        try {
          sent.push(JSON.parse(String(f.payload)));
        } catch {}
      });
    });
    // The chat socket opened in beforeEach; a fresh session opens one we observe.
    await newSession(page);
    const field = page.getByLabel("System prompt");
    await expect(field).toHaveValue(""); // none by default
    await send(page, "Before any prompt");
    await expect.poll(() => sent.find((f) => f.message === "Before any prompt")).toBeTruthy();
    expect(sent.find((f) => f.message === "Before any prompt")).not.toHaveProperty("system_prompt");
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);

    await field.fill("Answer in one word.");
    await send(page, "With a prompt");
    await expect.poll(() => sent.find((f) => f.message === "With a prompt")?.system_prompt).toBe("Answer in one word.");
    expect(sent.find((f) => f.message === "With a prompt")?.toggles).not.toHaveProperty("system_prompt");
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);

    await page.reload();
    await expect(page.getByLabel("System prompt")).toHaveValue("Answer in one word.");
  });

  test("switching threads mid-stream does not leave the new thread loading", async ({ page }) => {
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, "[[slow]] take your time");
    await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible();

    // Leaving stops the models, so it asks first; declining stays put.
    await page.getByRole("button", { name: MAIN_THREAD_TITLE, exact: false }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("button", { name: "Stop generating" })).toBeVisible();

    await page.getByRole("button", { name: MAIN_THREAD_TITLE, exact: false }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Stop and leave" }).click();
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
    await page.getByPlaceholder(/Ask the arena/i).fill("ready?");
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeEnabled();
  });

  test("a debate pauses between rounds, resumes, and completes", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await startDebate(page, "Is a hot dog a sandwich?", 3);

    // The debated question heads the transcript.
    await expect(page.getByText("Is a hot dog a sandwich?").first()).toBeVisible();
    // Peers are anonymous to each other; the banner says who each label is.
    const legend = page.getByLabel("Who each participant is").first();
    await expect(legend).toContainText("GPT-6.1 Sol");
    await expect(legend).toContainText("Claude Sonnet 5.5");

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

  test("an interrupted debate resumes in this tab and finishes", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await startDebate(page, "Vim or Emacs?", 3);
    await expect(page.getByText("DEBATE · ROUND 2/3")).toBeVisible({ timeout: 20_000 });

    await page.reload();
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await expect(debateStatus(page)).toHaveText("interrupted");
    await expect(page.getByText(/Stopped when the tab running it closed/)).toBeVisible();
    // The restored transcript comes aligned by round from the server.
    await expect(page.getByText("Round 1 · independent answers")).toBeVisible();

    await page.getByRole("button", { name: "Resume the interrupted debate" }).click();
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 30_000 });
    await expect(page.getByText("Round 3", { exact: true })).toBeVisible();
  });

  test("closing a running debate asks first, and declining keeps it running", async ({ page }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await startDebate(page, "Slow one [[slow]]", 2);
    await expect(debateStatus(page)).toHaveText("running");

    await page.getByRole("button", { name: "Close debate" }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Leave the debate?");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(debateStatus(page)).toHaveText("running");

    await page.getByRole("button", { name: "Close debate" }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Stop and leave" }).click();
    await expect(page.getByText(/DEBATE · ROUND/)).toHaveCount(0);
  });

  test("a debate with named participants shows no participant key", async ({ page, request }) => {
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await startDebate(page, "Named or not?", 1, { named: true });
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 20_000 });
    // The models saw each other's names, so there are no labels to decode.
    await expect(page.getByLabel("Who each participant is")).toHaveCount(0);
    const sessions = await (await request.get(`${BACKEND_URL}/debate/sessions?parent_thread_id=${await currentThreadId(page)}`)).json();
    expect(JSON.stringify(sessions)).toContain('"peer_labels":"named"');
  });

  test("a message after a finished debate continues it and keeps its title", async ({ page, request }) => {
    const sent: { message?: string; debate_session_id?: string; parent_checkpoint_id?: string | null }[] = [];
    page.on("websocket", (ws) => {
      if (!/\/ws\/thread/.test(ws.url())) return;
      ws.on("framesent", (f) => {
        try {
          sent.push(JSON.parse(String(f.payload)));
        } catch {}
      });
    });
    // The chat socket opened in beforeEach; a fresh session opens one we observe.
    await newSession(page);
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await startDebate(page, "Cats or dogs?", 1);
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 20_000 });
    const sessionId = await page.evaluate(() => localStorage.getItem("crucible_active_debate"));

    await send(page, "Which argument was weakest?");
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0, { timeout: 20_000 });
    const frame = sent.find((f) => f.message === "Which argument was weakest?");
    expect(frame?.debate_session_id).toBe(sessionId);
    expect(frame?.parent_checkpoint_id).toBeNull();

    // The reply follows the debate on screen; the record the models read is
    // not shown again under the transcript, and the question appears once.
    await expect(page.getByText("Which argument was weakest?")).toHaveCount(1);
    await expect(page.getByText(/^A debate between/)).toHaveCount(0);
    await expect(page.getByText(answerFrom(GPT)).last()).toBeVisible();

    // The thread keeps the debate's title instead of being renamed by the turn.
    const threads = await (await request.get(`${BACKEND_URL}/threads`)).json();
    const id = await currentThreadId(page);
    const title = threads.threads.find((t: { id: string; title: string }) => t.id === id)?.title;
    expect(title).toMatch(/^Debate: Cats or dogs\?/);
  });

  test("a debate started mid-thread is still continued after a reload", async ({ page }) => {
    const sent: { message?: string; debate_session_id?: string }[] = [];
    page.on("websocket", (ws) => {
      if (!/\/ws\/thread/.test(ws.url())) return;
      ws.on("framesent", (f) => {
        try {
          sent.push(JSON.parse(String(f.payload)));
        } catch {}
      });
    });
    await newSession(page);
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await send(page, "Opening question");
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0, { timeout: 20_000 });
    await addModel(page, "Anthropic", "Claude Sonnet 5.5");
    await startDebate(page, "Mid-thread debate?", 1);
    await expect(debateStatus(page)).toHaveText("completed", { timeout: 20_000 });
    const sessionId = await page.evaluate(() => localStorage.getItem("crucible_active_debate"));

    // After a reload the thread opens on its chat; reopening the debate from
    // the sidebar puts it above the thread's own messages, and a turn sent
    // under it still continues the debate.
    await page.reload();
    // This thread is the most recently active, so it is listed first.
    await page.getByRole("button", { name: "Show 1 debate" }).first().click();
    await page.getByRole("button", { name: /GPT-6\.1 Sol vs Claude Sonnet 5\.5/ }).first().click();
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await expect(debateStatus(page)).toHaveText("completed");
    await send(page, "After the reload");
    await expect.poll(() => sent.find((f) => f.message === "After the reload")?.debate_session_id).toBe(sessionId);
  });

  test("a clean profile starts from the default arena, and the selection survives a reload", async ({ page }) => {
    await openApp(page, { freshProfile: true });
    await expect(page.getByText(/^3 models$/i).first()).toBeVisible();
    const stored = await page.evaluate(() => localStorage.getItem("crucible_selected_models"));
    expect(stored).toBeNull(); // nothing picked yet: the defaults are not written

    // Narrow it to one model and reload: the pick is kept. (A family button's
    // name ends with its selected count while it has one.)
    await page.getByRole("button", { name: /^Anthropic \d+ models( \d+)?$/ }).click();
    await page.getByRole("button", { name: "Claude Sonnet 5.5" }).first().click();
    await page.getByRole("button", { name: /^Google \d+ models( \d+)?$/ }).click();
    await page.getByRole("button", { name: "Gemini 3.1 Pro" }).first().click();
    await expect(page.getByText(/^[23] models$/i)).toHaveCount(0);
    await page.reload();
    await expect(page.getByText("GPT-6.1 Sol", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/^[23] models$/i)).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem("crucible_selected_models"))).toBe(
      JSON.stringify(["gpt-6.1-sol"]),
    );
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
    await page.getByRole("button", { name: "Delete", exact: true }).click();

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
    await expect(page.getByText("Sent with your next message only")).toBeVisible();
  });

  test("an attached document goes out by name and is gone after the turn", async ({ page }) => {
    const sent: { document_names?: string[]; documents?: unknown }[] = [];
    page.on("websocket", (ws) => {
      if (!/\/ws\/thread/.test(ws.url())) return;
      ws.on("framesent", (f) => {
        try {
          sent.push(JSON.parse(String(f.payload)));
        } catch {}
      });
    });
    await newSession(page);
    await page.getByRole("button", { name: "Arena", exact: true }).click();
    await page.locator('input[type="file"]').setInputFiles({
      name: "brief.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("The launch moved to Thursday."),
    });
    await expect(page.getByRole("button", { name: "brief.txt" })).toBeVisible();
    // Re-attaching the same file works (the input used to keep its value).
    await page.locator('input[type="file"]').setInputFiles({
      name: "brief.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("The launch moved to Friday."),
    });
    await send(page, "When is the launch?");
    await expect(page.getByRole("button", { name: "Stop generating" })).toHaveCount(0);
    expect(sent.at(-1)?.document_names).toEqual(["brief.txt"]);
    expect(sent.at(-1)).not.toHaveProperty("documents");
    await expect(page.getByRole("button", { name: "brief.txt" })).toHaveCount(0);
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
    await expect(page.getByText(/What does branching buy me/).first()).toBeVisible();
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
