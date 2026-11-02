import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useDebateSession } from "./useDebateSession";
import { TransportProvider } from "@/lib/transport";
import * as api from "@/lib/api";
import { DEFAULT_DEBATE_DEFAULTS } from "@/hooks/useDebateDefaults";

jest.mock("@/lib/api", () => ({
  listDebateSessions: jest.fn().mockResolvedValue([]),
  createDebateSession: jest.fn(),
  fetchDebateSession: jest.fn(),
  fetchDebateTranscript: jest.fn().mockResolvedValue({ question: "", rounds: [], synthesis: null }),
  deleteDebateSession: jest.fn(),
  fetchDebateTree: jest.fn().mockResolvedValue({ nodes: [], edges: [], lanes: [], session_metadata: null }),
  createDebateWebSocketUrl: (id: string) => `ws://test/debate/${id}`,
}));

/** A socket the test drives: `emit` plays a server frame, `sent` records client frames. */
class FakeSocket {
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {}
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closed = true;
    this.readyState = 3;
  }
  emit(frame: object) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
}

function setup() {
  const sockets: FakeSocket[] = [];
  const factory = (url: string) => {
    const s = new FakeSocket(url);
    sockets.push(s);
    return s as unknown as WebSocket;
  };
  const opts = {
    threadId: "t1",
    fetchThreads: jest.fn(),
    historyNodeCount: 0,
    isHistoryLoading: false,
    setShowTree: jest.fn(),
    clearChatMessages: jest.fn(),
    pushToast: jest.fn(),
    confirm: jest.fn().mockResolvedValue(true),
    modelLabel: (id: string) => id.toUpperCase(),
    modelColor: () => "#123456",
  };
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <TransportProvider value={factory}>{children}</TransportProvider>
  );
  const hook = renderHook(() => useDebateSession(opts), { wrapper });
  return { ...hook, sockets, opts };
}

async function startDebate(result: ReturnType<typeof setup>["result"], sessionId = "s1") {
  (api.createDebateSession as jest.Mock).mockResolvedValueOnce({
    session_id: sessionId,
    participants: ["a", "b"],
  });
  await act(async () => {
    result.current.openDialog("Question?");
    await result.current.start(DEFAULT_DEBATE_DEFAULTS, {
      participants: ["a", "b"],
      toggles: { use_rag: false, use_web_search: false },
      documentNames: [],
      parentCheckpointId: null,
    });
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  // Tests that set their own answers must not leak them into the next one.
  (api.listDebateSessions as jest.Mock).mockReset().mockResolvedValue([]);
  (api.fetchDebateSession as jest.Mock).mockReset();
  (api.fetchDebateTranscript as jest.Mock).mockReset().mockResolvedValue({ question: "", rounds: [], synthesis: null });
  localStorage.clear();
  jest.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    cb(0);
    return 1;
  });
});

describe("useDebateSession", () => {
  it("carries the chosen summarizer and system prompt into the debate's start and synthesis frames", async () => {
    const { result, sockets } = setup();
    (api.createDebateSession as jest.Mock).mockResolvedValueOnce({ session_id: "s1", participants: ["a", "b"] });
    await act(async () => {
      result.current.openDialog("Question?");
      await result.current.start(DEFAULT_DEBATE_DEFAULTS, {
        participants: ["a", "b"],
        toggles: { use_rag: false, use_web_search: false },
        documentNames: [],
        parentCheckpointId: null,
        summarizer: "gpt-6-luna",
        systemPrompt: "Be terse.",
      });
    });
    // The participants' view of each other goes with the session.
    expect(api.createDebateSession).toHaveBeenCalledWith(expect.objectContaining({ peer_labels: "anonymous" }));
    const ws = sockets[0];
    act(() => ws.open());
    expect(ws.sent[0]).toMatchObject({ type: "debate_start", summarizer: "gpt-6-luna", system_prompt: "Be terse." });
    expect(ws.sent[0].toggles).not.toHaveProperty("system_prompt");
    act(() =>
      result.current.synthesize(null, { use_rag: false, use_web_search: false }, {
        summarizer: "gpt-6-luna",
        systemPrompt: "Be terse.",
      }),
    );
    expect(ws.sent.at(-1)).toMatchObject({
      type: "debate_synthesize",
      summarizer: "gpt-6-luna",
      system_prompt: "Be terse.",
    });
  });

  it("starts a debate over the injected socket and streams the transcript", async () => {
    const { result, sockets } = setup();
    await startDebate(result);

    const ws = sockets[0];
    expect(ws.url).toBe("ws://test/debate/s1");
    act(() => ws.open());
    expect(ws.sent[0]).toMatchObject({ type: "debate_start", prompt: "Question?" });
    expect(ws.sent[0]).not.toHaveProperty("summarizer"); // automatic unless chosen
    expect(ws.sent[0]).not.toHaveProperty("system_prompt"); // none unless set

    act(() => {
      ws.emit({ type: "debate_session_created", participants: ["a", "b"] });
      ws.emit({ type: "debate_round_start", round: 0 });
      ws.emit({ type: "stream_start", model: "a", round: 0 });
      ws.emit({ type: "stream_token", model: "a", token: "Hi " });
      ws.emit({ type: "stream_end", model: "a", round: 0, content: "Hi there" });
    });

    expect(result.current.messages.map((m) => m.content)).toEqual(["Question?", "Round 1 · independent answers", "Hi there"]);
    expect(result.current.status).toBe("running");
    expect(result.current.controls.pause).toBe(true);
  });

  it("takes injected messages while paused instead of letting the composer chat", async () => {
    const { result, sockets } = setup();
    await startDebate(result);
    const ws = sockets[0];
    act(() => ws.open());
    act(() => ws.emit({ type: "debate_session_status", status: "paused" }));

    expect(result.current.status).toBe("paused");
    expect(result.current.controls.inject).toBe(true);
    act(() => result.current.inject("consider cost"));
    expect(ws.sent.at(-1)).toEqual({ type: "debate_inject", message: "consider cost" });
  });

  it("a failed model closes its bubble and notifies with its label", async () => {
    const { result, sockets, opts } = setup();
    await startDebate(result);
    act(() => {
      sockets[0].open();
      sockets[0].emit({ type: "stream_start", model: "b", round: 0 });
      sockets[0].emit({ type: "error", model: "b", round: 0, message: "timed out" });
    });
    expect(result.current.messages.at(-1)).toMatchObject({ streaming: false, content: "_(no response: timed out)_" });
    expect(opts.pushToast).toHaveBeenCalledWith("timed out", "error", "B failed");
  });

  it("a dropped socket attaches to the debate again instead of calling it interrupted", async () => {
    const { result, sockets } = setup();
    await startDebate(result);
    act(() => {
      sockets[0].open();
      sockets[0].emit({ type: "debate_round_start", round: 0 });
      sockets[0].emit({ type: "stream_start", model: "a", round: 0 });
      sockets[0].emit({ type: "stream_token", model: "a", token: "Tab" });
      sockets[0].drop();
    });
    // The run goes on on the backend.
    expect(result.current.status).toBe("running");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 600));
    });
    const again = sockets[1];
    expect(again.url).toBe("ws://test/debate/s1");
    (api.fetchDebateTranscript as jest.Mock).mockResolvedValueOnce({ question: "Question?", rounds: [], synthesis: null });
    await act(async () => {
      again.open();
      // Attaching sends nothing: no start, no continue.
      expect(again.sent).toEqual([]);
      again.emit({
        type: "debate_resume", session_id: "s1", status: "running", round: 0, question: "Question?",
        answers: [{ model: "a", content: "Tabs so far", done: false }], synthesis: null, convergence_score: null,
      });
      again.emit({ type: "attached", session_id: "s1", live: true });
    });
    await waitFor(() => expect(result.current.messages.at(-1)).toMatchObject({ content: "Tabs so far", streaming: true }));
    // One bubble for a's answer, caught up on what streamed while away.
    expect(result.current.messages.filter((m) => m.model === "a")).toHaveLength(1);
    act(() => again.emit({ type: "stream_end", model: "a", round: 0, content: "Tabs win", checkpoint_id: "c1" }));
    expect(result.current.messages.at(-1)).toMatchObject({ content: "Tabs win", streaming: false });
    expect(result.current.connected).toBe(true);
  });

  it("starting another debate closes the old socket and ignores its frames", async () => {
    const { result, sockets } = setup();
    await startDebate(result, "s1");
    act(() => sockets[0].open());
    const old = sockets[0];
    const oldOnMessage = old.onmessage;

    await startDebate(result, "s2");
    expect(old.closed).toBe(true);
    expect(old.onmessage).toBeNull();
    // Even a frame the old socket had already queued can't reach the new debate.
    act(() => oldOnMessage?.({ data: JSON.stringify({ type: "debate_round_start", round: 5 }) }));
    expect(result.current.activeSessionId).toBe("s2");
    expect(result.current.round).toBe(0);
  });

  it("pause and resume send control frames; closing a running debate stops it", async () => {
    const { result, sockets } = setup();
    await startDebate(result);
    act(() => sockets[0].open());

    act(() => result.current.pause());
    act(() => sockets[0].emit({ type: "debate_session_status", status: "paused" }));
    act(() => result.current.resume());
    expect(sockets[0].sent.slice(1)).toEqual([
      { type: "debate_control", action: "pause" },
      { type: "debate_control", action: "resume" },
    ]);

    await act(async () => {
      await result.current.close();
    });
    expect(sockets[0].sent.at(-1)).toEqual({ type: "debate_control", action: "stop" });
    expect(result.current.activeSessionId).toBeNull();
  });

  it("names the debate on screen for a chat turn to continue, until one has", async () => {
    const { result } = setup();
    expect(result.current.continuesDebate).toBeNull();
    await startDebate(result, "s1");
    expect(result.current.continuesDebate).toBe("s1");

    act(() => result.current.markFollowedUp());
    expect(result.current.continuesDebate).toBeNull();

    // Another debate on screen is continued afresh.
    await startDebate(result, "s2");
    expect(result.current.continuesDebate).toBe("s2");
  });

  it("persists the active session and completes on the server's word", async () => {
    const { result, sockets, opts } = setup();
    await startDebate(result);
    await waitFor(() => expect(localStorage.getItem("crucible_active_debate")).toBe("s1"));
    act(() => {
      sockets[0].open();
      sockets[0].emit({ type: "debate_session_status", status: "completed" });
    });
    expect(result.current.status).toBe("completed");
    expect(opts.clearChatMessages).toHaveBeenCalled();
  });

  it("asks before closing a running debate, and keeps it when the person declines", async () => {
    const { result, sockets, opts } = setup();
    await startDebate(result);
    act(() => sockets[0].open());
    opts.confirm.mockResolvedValueOnce(false);
    await act(async () => {
      await result.current.close();
    });
    expect(opts.confirm).toHaveBeenCalledWith("Stop the debate?", expect.stringMatching(/stops the debate/), {
      confirmLabel: "Stop and close",
    });
    expect(result.current.activeSessionId).toBe("s1");
    expect(sockets[0].closed).toBe(false);
  });

  it("closing a running debate while its socket reattaches still stops it", async () => {
    const { result, sockets } = setup();
    await startDebate(result);
    act(() => {
      sockets[0].open();
      sockets[0].emit({ type: "debate_round_start", round: 0 });
      sockets[0].drop();
    });
    await act(async () => {
      await result.current.close();
    });
    const stopper = sockets[1];
    act(() => stopper.open());
    expect(stopper.sent).toEqual([{ type: "debate_control", action: "stop" }]);
    expect(stopper.closed).toBe(true);
    expect(result.current.activeSessionId).toBeNull();
    // The reattach that was pending is cancelled with the debate.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 600));
    });
    expect(sockets).toHaveLength(2);
  });

  it("leaves a running debate for another without asking and without stopping it", async () => {
    const { result, sockets, opts } = setup();
    await startDebate(result);
    act(() => {
      sockets[0].open();
      sockets[0].emit({ type: "debate_round_start", round: 0 });
    });
    (api.fetchDebateSession as jest.Mock).mockResolvedValue({
      session_id: "s2", parent_thread_id: "t1", participants: ["a", "b"], current_round: 1, status: "completed",
      termination_policy: { max_rounds: 2 },
    });
    await act(async () => {
      await result.current.switchTo("s2");
    });
    expect(opts.confirm).not.toHaveBeenCalled();
    expect(sockets[0].sent.some((f) => f.type === "debate_control")).toBe(false);
    expect(sockets[0].closed).toBe(true);
    expect(result.current.activeSessionId).toBe("s2");
  });

  it("reopening a running debate attaches to it, holding live frames until its stored rounds are read", async () => {
    localStorage.setItem("crucible_active_debate", "s4");
    (api.fetchDebateSession as jest.Mock).mockResolvedValue({
      session_id: "s4", parent_thread_id: "t1", participants: ["a", "b"], current_round: 1, status: "running",
      question: "Tabs?", termination_policy: { max_rounds: 3 },
    });
    let release: (t: unknown) => void = () => {};
    (api.fetchDebateTranscript as jest.Mock).mockReturnValueOnce(new Promise((r) => (release = r)));
    const { result, sockets } = setup();
    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(result.current.status).toBe("running");
    act(() => {
      sockets[0].open();
      sockets[0].emit({
        type: "debate_resume", session_id: "s4", status: "pausing", round: 1, question: "Tabs?",
        answers: [{ model: "a", content: "A1", done: false }, { model: "b", content: "B1", done: true }],
        synthesis: null, convergence_score: 0.4,
      });
      // Arrives while the stored rounds load: applied after them, not lost.
      sockets[0].emit({ type: "stream_token", model: "a", token: " more" });
    });
    expect(sockets[0].sent).toEqual([]);
    await act(async () => {
      release({ question: "Tabs?", rounds: [{ round: 0, question: "Tabs?", responses: { a: "A0", b: "B0" } }], synthesis: null });
    });
    expect(result.current.status).toBe("pausing");
    expect(result.current.round).toBe(1);
    expect(result.current.convergenceScore).toBe(0.4);
    expect(result.current.messages.map((m) => m.content)).toEqual([
      "Tabs?", "Round 1 · independent answers", "A0", "B0", "Round 2", "A1 more", "B1",
    ]);
    // Still running on the backend: Resume isn't offered, the live controls are.
    expect(result.current.controls.continue).toBe(false);
    expect(result.current.controls.inject).toBe(true);
  });

  it("shows a debate as stored when the attach finds nothing running it", async () => {
    localStorage.setItem("crucible_active_debate", "s6");
    (api.fetchDebateSession as jest.Mock)
      .mockResolvedValueOnce({
        session_id: "s6", parent_thread_id: "t1", participants: ["a", "b"], current_round: 1, status: "running",
        question: "Q", termination_policy: { max_rounds: 3 },
      })
      // The server restarted meanwhile.
      .mockResolvedValueOnce({
        session_id: "s6", parent_thread_id: "t1", participants: ["a", "b"], current_round: 1, status: "interrupted",
        question: "Q", termination_policy: { max_rounds: 3 },
      });
    (api.fetchDebateTranscript as jest.Mock).mockResolvedValue({
      question: "Q", rounds: [{ round: 0, question: "Q", responses: { a: "A", b: "B" } }], synthesis: null,
    });
    const { result, sockets } = setup();
    await waitFor(() => expect(sockets).toHaveLength(1));
    await act(async () => {
      sockets[0].open();
      sockets[0].emit({ type: "attached", session_id: "s6", live: false });
    });
    await waitFor(() => expect(result.current.messages.map((m) => m.content)).toContain("B"));
    expect(result.current.status).toBe("interrupted");
    expect(sockets[0].closed).toBe(true);
    expect(result.current.connected).toBe(false);
    expect(result.current.controls.continue).toBe(true);
  });

  it("resumes an interrupted debate with the rounds it has left", async () => {
    localStorage.setItem("crucible_active_debate", "s3");
    (api.fetchDebateSession as jest.Mock).mockResolvedValue({
      session_id: "s3", parent_thread_id: "t1", participants: ["a", "b"], current_round: 0, status: "interrupted",
      question: "Q", termination_policy: { max_rounds: 2 },
    });
    (api.fetchDebateTranscript as jest.Mock).mockResolvedValue({
      question: "Q", rounds: [{ round: 0, question: "Q", responses: { a: "A", b: "B" } }], synthesis: null,
    });
    const { result, sockets } = setup();
    await waitFor(() => expect(result.current.controls.continue).toBe(true));
    // A stored session that isn't running opens no socket.
    expect(sockets).toHaveLength(0);
    expect(result.current.status).toBe("interrupted");

    act(() => result.current.continueDebate());
    const ws = sockets[0];
    act(() => ws.open());
    // The 2 rounds, round 1 of them done.
    expect(ws.sent[0]).toEqual({ type: "debate_continue", rounds: 1 });
    expect(result.current.status).toBe("running");

    // The backend refuses (another client runs it): back to interrupted.
    act(() => ws.emit({ type: "error", message: "Another tab is running this debate." }));
    expect(result.current.status).toBe("interrupted");
  });

  it("restores a debate from its transcript and synthesizes it with its question", async () => {
    localStorage.setItem("crucible_active_debate", "s9");
    (api.fetchDebateSession as jest.Mock).mockResolvedValue({
      session_id: "s9",
      parent_thread_id: "t1",
      participants: ["a", "b"],
      current_round: 1,
      status: "interrupted",
      question: "Tabs or spaces?",
      termination_policy: { max_rounds: 3 },
    });
    (api.fetchDebateTranscript as jest.Mock).mockResolvedValueOnce({
      question: "Tabs or spaces?",
      rounds: [{ round: 0, question: "Tabs or spaces?", responses: { a: "Tabs", b: "Spaces" } }],
      synthesis: null,
    });
    const { result, sockets } = setup();
    await waitFor(() => expect(result.current.messages.length).toBeGreaterThan(0));
    expect(result.current.status).toBe("interrupted");
    expect(result.current.messages.map((m) => m.content)).toEqual([
      "Tabs or spaces?",
      "Round 1 · independent answers",
      "Tabs",
      "Spaces",
    ]);

    act(() => result.current.synthesize(null, { use_rag: false, use_web_search: false }));
    act(() => sockets[0].open());
    expect(sockets[0].sent[0]).toMatchObject({ type: "debate_synthesize", prompt: "Tabs or spaces?" });
  });

  it("does not reopen a debate-only thread's debate after it was closed", async () => {
    (api.listDebateSessions as jest.Mock).mockResolvedValue([
      { session_id: "s5", parent_thread_id: "t1", current_round: 2, status: "completed" },
    ]);
    (api.fetchDebateSession as jest.Mock).mockResolvedValue({
      session_id: "s5",
      parent_thread_id: "t1",
      participants: ["a", "b"],
      current_round: 2,
      status: "completed",
      termination_policy: { max_rounds: 2 },
    });
    const { result } = setup();
    await waitFor(() => expect(result.current.activeSessionId).toBe("s5"));
    await act(async () => {
      await result.current.close();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.activeSessionId).toBeNull();
    expect(api.fetchDebateSession).toHaveBeenCalledTimes(1);
  });

  it("starting a debate is reported when the backend refuses it", async () => {
    const { result, opts } = setup();
    (api.createDebateSession as jest.Mock).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    let started = true;
    await act(async () => {
      result.current.openDialog("Q");
      started = await result.current.start(DEFAULT_DEBATE_DEFAULTS, {
        participants: ["a", "b"],
        toggles: { use_rag: false, use_web_search: false },
        documentNames: [],
        parentCheckpointId: null,
      });
    });
    expect(started).toBe(false);
    expect(opts.pushToast).toHaveBeenCalledWith(expect.stringMatching(/unreachable/), "error");
  });

  it("asks before a redirect restarts the round, and sends nothing when declined", async () => {
    const { result, sockets, opts } = setup();
    await startDebate(result);
    act(() => sockets[0].open());

    opts.confirm.mockResolvedValueOnce(false);
    let redirected = true;
    await act(async () => {
      redirected = await result.current.redirect("Is a taco a sandwich?");
    });
    expect(redirected).toBe(false);
    expect(sockets[0].sent.some((f) => f.type === "debate_redirect")).toBe(false);

    await act(async () => {
      redirected = await result.current.redirect("Is a taco a sandwich?");
    });
    expect(redirected).toBe(true);
    expect(opts.confirm).toHaveBeenLastCalledWith("Redirect the debate?", expect.any(String), {
      confirmLabel: "Redirect",
      destructive: false,
    });
    expect(sockets[0].sent.at(-1)).toEqual({ type: "debate_redirect", message: "Is a taco a sandwich?" });
    expect(result.current.messages.at(-1)).toMatchObject({ type: "redirect", content: "Is a taco a sandwich?" });
  });

  it("injects into the next round", async () => {
    const { result, sockets } = setup();
    await startDebate(result);
    act(() => sockets[0].open());
    act(() => result.current.inject("Consider cost"));
    expect(sockets[0].sent.at(-1)).toEqual({ type: "debate_inject", message: "Consider cost" });
    expect(result.current.messages.at(-1)).toMatchObject({ type: "inject", content: "Consider cost" });
  });

  it("asks for the transcript again when it comes back without rounds the session finished", async () => {
    localStorage.setItem("crucible_active_debate", "s7");
    (api.fetchDebateSession as jest.Mock).mockResolvedValue({
      session_id: "s7",
      parent_thread_id: "t1",
      participants: ["a", "b"],
      current_round: 1,
      status: "interrupted",
      question: "Vim or Emacs?",
      termination_policy: { max_rounds: 3 },
    });
    (api.fetchDebateTranscript as jest.Mock)
      // Read while the round's checkpoints were still being written: no rounds yet.
      .mockResolvedValueOnce({ question: "Vim or Emacs?", rounds: [], synthesis: null })
      .mockResolvedValueOnce({
        question: "Vim or Emacs?",
        rounds: [{ round: 0, question: "Vim or Emacs?", responses: { a: "Vim", b: "Emacs" } }],
        synthesis: null,
      });
    const { result } = setup();
    await waitFor(() => expect(result.current.messages.map((m) => m.content)).toContain("Emacs"), { timeout: 3000 });
    expect(result.current.messages.map((m) => m.content)).toContain("Round 1 · independent answers");
  });
});
