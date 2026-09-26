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
  loadDebateMessages: jest.fn().mockResolvedValue([]),
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
    threads: [],
    fetchThreads: jest.fn(),
    historyNodeCount: 0,
    isHistoryLoading: false,
    setShowTree: jest.fn(),
    clearChatMessages: jest.fn(),
    pushToast: jest.fn(),
    confirm: jest.fn().mockResolvedValue(true),
    modelLabel: (id: string) => id.toUpperCase(),
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
      documents: {},
      parentCheckpointId: null,
    });
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  jest.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    cb(0);
    return 1;
  });
});

describe("useDebateSession", () => {
  it("starts a debate over the injected socket and streams the transcript", async () => {
    const { result, sockets } = setup();
    await startDebate(result);

    const ws = sockets[0];
    expect(ws.url).toBe("ws://test/debate/s1");
    act(() => ws.open());
    expect(ws.sent[0]).toMatchObject({ type: "debate_start", prompt: "Question?" });

    act(() => {
      ws.emit({ type: "debate_session_created", participants: ["a", "b"] });
      ws.emit({ type: "debate_round_start", round: 0 });
      ws.emit({ type: "stream_start", model: "a", round: 0 });
      ws.emit({ type: "stream_token", model: "a", token: "Hi " });
      ws.emit({ type: "stream_end", model: "a", round: 0, content: "Hi there" });
    });

    expect(result.current.messages.map((m) => m.content)).toEqual(["Round 1", "Hi there"]);
    expect(result.current.status).toBe("running");
    expect(result.current.controls.pause).toBe(true);
  });

  it("a failed model closes its bubble and notifies with its label", async () => {
    const { result, sockets, opts } = setup();
    await startDebate(result);
    act(() => {
      sockets[0].open();
      sockets[0].emit({ type: "stream_start", model: "b", round: 0 });
      sockets[0].emit({ type: "error", model: "b", round: 0, message: "timed out" });
    });
    expect(result.current.messages[0]).toMatchObject({ streaming: false, content: "_(no response: timed out)_" });
    expect(opts.pushToast).toHaveBeenCalledWith("timed out", "B");
  });

  it("a dropped socket marks the debate interrupted", async () => {
    const { result, sockets } = setup();
    await startDebate(result);
    act(() => {
      sockets[0].open();
      sockets[0].emit({ type: "debate_round_start", round: 0 });
      sockets[0].drop();
    });
    expect(result.current.status).toBe("interrupted");
    expect(result.current.controls.synthesize).toBe(true);
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

    act(() => result.current.close());
    expect(sockets[0].sent.at(-1)).toEqual({ type: "debate_control", action: "stop" });
    expect(result.current.activeSessionId).toBeNull();
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
});
