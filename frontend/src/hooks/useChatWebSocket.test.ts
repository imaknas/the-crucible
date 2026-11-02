import { renderHook, act } from "@testing-library/react";
import { useChatWebSocket } from "./useChatWebSocket";
import { reconnectDelay } from "@/lib/transport";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  createWebSocketUrl: jest
    .fn()
    .mockImplementation((tid) => `ws://localhost/test-ws/${tid}`),
  fetchHistory: jest.fn(),
}));

class MockWebSocket {
  static OPEN = 1;
  static instances: MockWebSocket[] = [];
  url: string;
  readyState: number = 1; // OPEN
  onmessage: ((event: any) => void) | null = null;
  onclose: ((event: any) => void) | null = null;
  onopen: (() => void) | null = null;
  send = jest.fn();
  close = jest.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

describe("useChatWebSocket", () => {
  const mockProps = {
    threadId: "thread_1",
    parentCheckpoint: "cp_1" as string | null,
    selectedModels: ["gpt-4o"],
    toggles: {
      use_rag: true,
      use_web_search: false,
    },
    documentNames: [] as string[],
    clearDocuments: jest.fn(),
    onTurnSettled: jest.fn(),
    setErrorModals: jest.fn(),
    pushToast: jest.fn(),
  };

  let globalWs: any;

  beforeAll(() => {
    globalWs = global.WebSocket;
    (global as any).WebSocket = MockWebSocket;
    jest.useFakeTimers();
  });

  afterAll(() => {
    (global as any).WebSocket = globalWs;
    jest.useRealTimers();
  });

  beforeEach(() => {
    jest.clearAllMocks();
    MockWebSocket.instances = [];
  });

  it("creates a websocket connection on mount if threadId exists", () => {
    renderHook(() => useChatWebSocket(mockProps));
    expect(api.createWebSocketUrl).toHaveBeenCalledWith("thread_1");
  });

  it("sends interactive message correctly", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));

    await act(async () => {
      await result.current.sendInteractiveMessage("Hello Crucible");
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.messages).toEqual([
      expect.objectContaining({
        role: "user",
        content: "Hello Crucible",
        type: "human",
      }),
    ]);
    expect(mockProps.clearDocuments).toHaveBeenCalled();
  });

  it("synthesizes by naming the answers; the backend writes the prompt", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));

    await act(async () => {
      await result.current.synthesizeBranches(["a1", "a2"]);
    });

    expect(result.current.isLoading).toBe(true);
    expect(mockProps.clearDocuments).toHaveBeenCalled();
    const frame = JSON.parse(MockWebSocket.instances[0].send.mock.calls[0][0]);
    expect(frame).toMatchObject({
      type: "synthesis",
      model: "gpt-4o",
      // The answers may sit on different branches: the backend hangs the
      // synthesis from the question they answered.
      parent_checkpoint_id: null,
      answer_checkpoint_ids: ["a1", "a2"],
    });
    expect(frame).not.toHaveProperty("message");
  });

  it("synthesizes with the chosen synthesizer, streaming as a synthesis", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.synthesizeBranches(["a1", "a2"], "claude-x");
    });
    const ws = MockWebSocket.instances[0];
    expect(JSON.parse(ws.send.mock.calls[0][0]).model).toBe("claude-x");

    act(() => ws.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "claude-x" }) }));
    expect(result.current.messages.at(-1)).toMatchObject({ type: "synthesis", model: "claude-x" });
  });

  it("does not synthesize fewer than two answers", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.synthesizeBranches(["a1"]);
    });
    expect(MockWebSocket.instances[0].send).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });

  it("clears loading when the thread changes mid-stream", async () => {
    const { result, rerender } = renderHook((props) => useChatWebSocket(props), {
      initialProps: mockProps,
    });
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    expect(result.current.isLoading).toBe(true);

    rerender({ ...mockProps, threadId: "thread_2" });
    expect(result.current.isLoading).toBe(false);
  });

  it.each([
    ["claude-haiku-4-5-20251001", "claude-haiku-4-5-20251001"],
    [null, undefined],
  ])("sends the chosen summarizer (%s) with the model's frame", async (summarizer, sent) => {
    const { result } = renderHook(() => useChatWebSocket({ ...mockProps, summarizer }));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const frame = JSON.parse(MockWebSocket.instances[0].send.mock.calls[0][0]);
    expect(frame.summarizer).toBe(sent); // automatic: omitted, the backend decides
  });

  it.each([
    ["Answer in French.", "Answer in French."],
    [null, undefined],
    ["   ", undefined],
  ])("sends the system prompt (%p) as a top-level field only when set", async (systemPrompt, sent) => {
    const { result } = renderHook(() => useChatWebSocket({ ...mockProps, systemPrompt }));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const frame = JSON.parse(MockWebSocket.instances[0].send.mock.calls[0][0]);
    expect(frame.system_prompt).toBe(sent);
    expect("system_prompt" in frame).toBe(sent !== undefined);
    expect(frame.toggles).not.toHaveProperty("system_prompt");
  });

  it("sends the system prompt with a synthesis turn", async () => {
    const { result } = renderHook(() => useChatWebSocket({ ...mockProps, systemPrompt: "Be terse." }));
    await act(async () => {
      await result.current.synthesizeBranches(["a1", "a2"]);
    });
    const frame = JSON.parse(MockWebSocket.instances[0].send.mock.calls[0][0]);
    expect(frame).toMatchObject({ type: "synthesis", system_prompt: "Be terse." });
  });

  it("continues a finished debate from the debate, not from the active checkpoint", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.sendInteractiveMessage("Which argument was weakest?", false, "debate-1");
    });
    const frame = JSON.parse(MockWebSocket.instances[0].send.mock.calls[0][0]);
    expect(frame).toMatchObject({ debate_session_id: "debate-1", parent_checkpoint_id: null });
  });

  it("names the attached documents instead of sending their text", async () => {
    const { result } = renderHook(() => useChatWebSocket({ ...mockProps, documentNames: ["notes.pdf"] }));
    await act(async () => {
      await result.current.sendInteractiveMessage("Summarize it");
    });
    const frame = JSON.parse(MockWebSocket.instances[0].send.mock.calls[0][0]);
    expect(frame.document_names).toEqual(["notes.pdf"]);
    expect(frame).not.toHaveProperty("documents");
    expect(mockProps.clearDocuments).toHaveBeenCalled();
  });

  it("sends no parent for the latest turn, so every model continues its own reply", async () => {
    const { result } = renderHook(() =>
      useChatWebSocket({ ...mockProps, parentCheckpoint: null, selectedModels: ["gpt-4o", "claude-x"] }),
    );
    await act(async () => {
      await result.current.sendInteractiveMessage("And then?");
    });
    const frames = MockWebSocket.instances[0].send.mock.calls.map((c) => JSON.parse(c[0]));
    expect(frames.map((f) => f.model)).toEqual(["gpt-4o", "claude-x"]);
    expect(frames.every((f) => f.parent_checkpoint_id === null)).toBe(true);
  });

  it("settles a turn without pinning the next one to its first reply", async () => {
    const onTurnSettled = jest.fn();
    const { result } = renderHook(() =>
      useChatWebSocket({ ...mockProps, onTurnSettled, selectedModels: ["gpt-4o", "claude-x"] }),
    );
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    const frame = (data: object) => ws.onmessage?.({ data: JSON.stringify(data) });
    act(() => {
      frame({ type: "stream_start", model: "gpt-4o", turn_id: "t1" });
      frame({ type: "stream_token", model: "gpt-4o", token: "Hi there" });
      frame({ type: "stream_end", model: "gpt-4o", checkpoint_id: "n_a", turn_id: "t1" });
    });
    expect(onTurnSettled).not.toHaveBeenCalled();
    act(() => {
      frame({ type: "stream_start", model: "claude-x", turn_id: "t1" });
      frame({ type: "stream_end", model: "claude-x", checkpoint_id: "n_b", turn_id: "t1" });
    });
    expect(onTurnSettled).toHaveBeenCalledWith("thread_1");
    expect(result.current.replyTexts).toEqual({ n_a: "Hi there" });
    // Several models: their replies streamed into the turn's cards, not bubbles.
    expect(result.current.messages.filter((m) => m.role === "assistant")).toEqual([]);
    expect(result.current.liveTurn).toMatchObject({
      turnId: "t1",
      replies: [
        { model: "gpt-4o", content: "Hi there", streaming: false, checkpoint_id: "n_a" },
        { model: "claude-x", streaming: false, checkpoint_id: "n_b" },
      ],
    });
    expect(result.current.isLoading).toBe(false);
  });

  it("streams a single-model turn as a bubble, with no cards", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "gpt-4o" }) });
      ws.onmessage?.({ data: JSON.stringify({ type: "stream_end", model: "gpt-4o", checkpoint_id: "n_a" }) });
    });
    expect(result.current.liveTurn).toBeNull();
    expect(result.current.messages.at(-1)).toMatchObject({ role: "assistant", id: "n_a" });
  });

  it("keeps each reply's metrics from stream_end, for the cards and the bubble", async () => {
    const metrics = { ttft_ms: 900, total_ms: 3000, input_tokens: 10, output_tokens: 20, reasoning_tokens: 5, cached_input_tokens: 0, cost_usd: 0.001 };
    const multi = renderHook(() => useChatWebSocket({ ...mockProps, selectedModels: ["gpt-4o", "claude-x"] }));
    await act(async () => {
      await multi.result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances.at(-1)!;
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "gpt-4o", turn_id: "t1" }) });
      ws.onmessage?.({ data: JSON.stringify({ type: "stream_end", model: "gpt-4o", checkpoint_id: "n_a", turn_id: "t1", metrics }) });
    });
    expect(multi.result.current.liveTurn?.replies[0].metrics).toEqual(metrics);
    multi.unmount();

    const single = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await single.result.current.sendInteractiveMessage("Hello");
    });
    const ws2 = MockWebSocket.instances.at(-1)!;
    act(() => {
      ws2.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "gpt-4o" }) });
      ws2.onmessage?.({ data: JSON.stringify({ type: "stream_end", model: "gpt-4o", checkpoint_id: "n_b", metrics }) });
    });
    expect(single.result.current.messages.at(-1)).toMatchObject({ id: "n_b", metrics });
  });

  it("cards a model that fails, streams its retry back into the same card, and stops cards on Stop", async () => {
    const { result } = renderHook(() => useChatWebSocket({ ...mockProps, selectedModels: ["gpt-4o", "claude-x"] }));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    const frame = (data: object) => ws.onmessage?.({ data: JSON.stringify(data) });
    act(() => {
      frame({ type: "stream_start", model: "gpt-4o" });
      frame({ type: "stream_end", model: "gpt-4o", checkpoint_id: "n_a" });
      frame({ type: "error", model: "claude-x", message: "boom" });
    });
    expect(result.current.liveTurn?.replies[1]).toMatchObject({ model: "claude-x", error: "boom", streaming: false });

    act(() => result.current.retryModel(result.current.modelErrors[0].id));
    expect(result.current.liveTurn?.replies[1]).toMatchObject({ streaming: true, error: null });
    act(() => frame({ type: "stream_start", model: "claude-x" }));
    act(() => result.current.stopStreaming());
    expect(result.current.liveTurn?.replies[1]).toMatchObject({ streaming: false, stopped: true });
    expect(result.current.messages.filter((m) => m.role === "assistant")).toEqual([]);
  });

  it("marks a reply cut off by Stop as incomplete", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "gpt-4o" }) }));
    act(() => result.current.stopStreaming());
    expect(JSON.parse(ws.send.mock.calls.at(-1)[0])).toEqual({ type: "stop" });
    expect(result.current.messages.at(-1)).toMatchObject({ streaming: false, stopped: true });
    expect(result.current.isLoading).toBe(false);
  });

  it("keeps a reply streaming through a dropped connection and catches up when the socket returns", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "gpt-4o", turn_id: "t1" }) });
      ws.onmessage?.({ data: JSON.stringify({ type: "stream_token", model: "gpt-4o", token: "Hel" }) });
    });
    // The run goes on without the socket: nothing is marked stopped.
    act(() => ws.onclose?.({ wasClean: false, code: 1006 }));
    expect(result.current.messages.at(-1)).toMatchObject({ streaming: true });
    expect(result.current.messages.at(-1)?.stopped).toBeFalsy();
    expect(result.current.isLoading).toBe(true);

    act(() => jest.advanceTimersByTime(600));
    const again = MockWebSocket.instances[1];
    act(() => {
      again.onmessage?.({
        data: JSON.stringify({ type: "stream_resume", model: "gpt-4o", turn_id: "t1", content_so_far: "Hello the", message: "Hello", turn_models: ["gpt-4o"] }),
      });
      again.onmessage?.({ data: JSON.stringify({ type: "attached", runs: [{ model: "gpt-4o", turn_id: "t1" }] }) });
      again.onmessage?.({ data: JSON.stringify({ type: "stream_token", model: "gpt-4o", token: "re" }) });
      jest.advanceTimersByTime(50);
    });
    // One bubble, its text what the backend has (tokens sent while away included).
    expect(result.current.messages.filter((m) => m.role === "assistant")).toHaveLength(1);
    expect(result.current.messages.at(-1)).toMatchObject({ content: "Hello there", streaming: true });

    act(() => again.onmessage?.({ data: JSON.stringify({ type: "stream_end", model: "gpt-4o", checkpoint_id: "n1", turn_id: "t1" }) }));
    expect(result.current.isLoading).toBe(false);
    expect(mockProps.onTurnSettled).toHaveBeenCalledWith("thread_1");
  });

  it("marks a reply stopped when the socket returns and its run is gone, and reloads the thread", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "gpt-4o", turn_id: "t1" }) }));
    act(() => {
      ws.onclose?.({ wasClean: false, code: 1006 });
      jest.advanceTimersByTime(600);
    });
    // The backend restarted (or the reply finished meanwhile): no live run.
    act(() => MockWebSocket.instances[1].onmessage?.({ data: JSON.stringify({ type: "attached", runs: [] }) }));
    expect(result.current.messages.at(-1)).toMatchObject({ streaming: false, stopped: true });
    expect(result.current.isLoading).toBe(false);
    expect(mockProps.onTurnSettled).toHaveBeenCalledWith("thread_1");
  });

  it("shows a turn it didn't send (a reload, another tab) as it stands, then streams it to the end", () => {
    const onThreadsChanged = jest.fn();
    const { result } = renderHook(() =>
      useChatWebSocket({ ...mockProps, selectedModels: ["gpt-4o"], onThreadsChanged }),
    );
    const ws = MockWebSocket.instances[0];
    const frame = (data: object) => ws.onmessage?.({ data: JSON.stringify(data) });
    act(() => {
      for (const [model, text] of [["claude-x", "Partial B"], ["gpt-4o", "Partial A"]]) {
        frame({
          type: "stream_resume", model, turn_id: "t9", parent_checkpoint_id: "p", content_so_far: text,
          message: "Compare", kind: null, turn_models: ["gpt-4o", "claude-x"], model_color: "#111",
        });
      }
      frame({ type: "attached", runs: [{ model: "claude-x", turn_id: "t9" }, { model: "gpt-4o", turn_id: "t9" }] });
    });
    expect(result.current.isLoading).toBe(true);
    // The question the turn answers, then its cards, with the text so far.
    expect(result.current.messages).toEqual([expect.objectContaining({ role: "user", content: "Compare", turn_id: "t9" })]);
    expect(result.current.liveTurn).toMatchObject({ key: "live-t9", turnId: "t9" });
    expect(result.current.liveTurn?.replies.map((r) => [r.model, r.content, r.streaming])).toEqual([
      ["claude-x", "Partial B", true],
      ["gpt-4o", "Partial A", true],
    ]);

    act(() => {
      frame({ type: "stream_token", model: "gpt-4o", token: " more" });
      jest.advanceTimersByTime(50);
    });
    expect(result.current.liveTurn?.replies[1].content).toBe("Partial A more");
    act(() => {
      frame({ type: "stream_end", model: "gpt-4o", checkpoint_id: "na", turn_id: "t9" });
      frame({ type: "stream_end", model: "claude-x", checkpoint_id: "nb", turn_id: "t9" });
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.replyTexts).toEqual({ na: "Partial A more", nb: "Partial B" });
    expect(mockProps.onTurnSettled).toHaveBeenCalledWith("thread_1");
  });

  it("resumes a one-model turn as a bubble after its question", () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    const ws = MockWebSocket.instances[0];
    act(() =>
      ws.onmessage?.({
        data: JSON.stringify({ type: "stream_resume", model: "gpt-4o", turn_id: "t2", content_so_far: "So far", message: "Q", turn_models: ["gpt-4o"] }),
      }),
    );
    expect(result.current.liveTurn).toBeNull();
    expect(result.current.messages).toEqual([
      expect.objectContaining({ role: "user", content: "Q" }),
      expect.objectContaining({ role: "assistant", content: "So far", streaming: true, model: "gpt-4o" }),
    ]);
  });

  it("marks a reply stopped when another tab stops the turn", async () => {
    const { result } = renderHook(() => useChatWebSocket({ ...mockProps, selectedModels: ["gpt-4o", "claude-x"] }));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    const frame = (data: object) => ws.onmessage?.({ data: JSON.stringify(data) });
    act(() => {
      frame({ type: "stream_start", model: "gpt-4o", turn_id: "t1" });
      frame({ type: "stream_start", model: "claude-x", turn_id: "t1" });
      frame({ type: "stream_stopped", model: "gpt-4o", turn_id: "t1" });
      frame({ type: "stream_stopped", model: "claude-x", turn_id: "t1" });
    });
    expect(result.current.liveTurn?.replies.map((r) => r.stopped)).toEqual([true, true]);
    expect(result.current.isLoading).toBe(false);
  });

  it("sends a Stop pressed while disconnected once the socket is back", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "gpt-4o" }) }));
    act(() => {
      ws.readyState = 3;
      ws.onclose?.({ wasClean: false, code: 1006 });
    });
    act(() => result.current.stopStreaming());
    expect(result.current.messages.at(-1)).toMatchObject({ stopped: true });
    act(() => jest.advanceTimersByTime(600));
    const again = MockWebSocket.instances[1];
    act(() => again.onopen?.());
    expect(again.send.mock.calls.map((c) => JSON.parse(c[0]))).toEqual([{ type: "stop" }]);
  });

  it("sends an ordinary turn from the chosen checkpoint", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const frame = JSON.parse(MockWebSocket.instances[0].send.mock.calls[0][0]);
    expect(frame.parent_checkpoint_id).toBe("cp_1");
    expect(frame).not.toHaveProperty("debate_session_id");
  });

  it("does not echo a message it could not send", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    MockWebSocket.instances[0].readyState = 3; // CLOSED

    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });

    expect(result.current.messages).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(mockProps.pushToast).toHaveBeenCalledWith(expect.any(String), "error", "Not sent");
  });

  it("waits for a socket that is still connecting instead of refusing the message", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    const ws = MockWebSocket.instances[0];
    ws.readyState = 0; // CONNECTING: the thread was opened a moment ago

    let sent: Promise<boolean> = Promise.resolve(false);
    act(() => {
      sent = result.current.sendInteractiveMessage("Hello");
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(200);
    });
    expect(ws.send).not.toHaveBeenCalled();

    ws.readyState = 1;
    await act(async () => {
      await jest.advanceTimersByTimeAsync(100);
      expect(await sent).toBe(true);
    });
    expect(ws.send).toHaveBeenCalledTimes(1);
    expect(mockProps.pushToast).not.toHaveBeenCalled();
  });

  it("reconnects after an unexpected close, backing off while it keeps failing", () => {
    renderHook(() => useChatWebSocket(mockProps));
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => {
      MockWebSocket.instances[0].onclose?.({ wasClean: false, code: 1006 });
      jest.advanceTimersByTime(500);
    });
    expect(MockWebSocket.instances).toHaveLength(2);
    act(() => {
      MockWebSocket.instances[1].onclose?.({ wasClean: false, code: 1006 });
      jest.advanceTimersByTime(500);
    });
    // The second try waits twice as long.
    expect(MockWebSocket.instances).toHaveLength(2);
    act(() => jest.advanceTimersByTime(500));
    expect(MockWebSocket.instances).toHaveLength(3);
    expect([0, 1, 2, 10].map(reconnectDelay)).toEqual([500, 1000, 2000, 10_000]);
  });

  it("does not reconnect a socket it closed itself on a thread switch", () => {
    const { rerender } = renderHook((props) => useChatWebSocket(props), { initialProps: mockProps });
    rerender({ ...mockProps, threadId: "thread_2" });
    act(() => {
      MockWebSocket.instances[0].onclose?.({ wasClean: true, code: 1000 });
      jest.advanceTimersByTime(20_000);
    });
    expect(MockWebSocket.instances.map((w) => w.url)).toEqual(["ws://localhost/test-ws/thread_1", "ws://localhost/test-ws/thread_2"]);
  });

  it("refreshes the thread list when a turn finishes and when the thread is titled", async () => {
    const onThreadsChanged = jest.fn();
    const { result } = renderHook(() => useChatWebSocket({ ...mockProps, onThreadsChanged }));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    const frame = (data: object) => ws.onmessage?.({ data: JSON.stringify(data) });

    act(() => {
      frame({ type: "stream_start", model: "gpt-4o" });
      frame({ type: "stream_end", model: "gpt-4o", checkpoint_id: "cp_2" });
    });
    expect(onThreadsChanged).toHaveBeenCalledTimes(1);

    act(() => frame({ type: "title_update", thread_id: "thread_1", title: "Hello" }));
    expect(onThreadsChanged).toHaveBeenCalledTimes(2);
  });

  it("shows a failed model inline and retries it from the parent it forked from", async () => {
    const { result } = renderHook(() => useChatWebSocket({ ...mockProps, selectedModels: ["gpt-4o", "claude-x"] }));
    await act(async () => {
      await result.current.sendInteractiveMessage("Hello");
    });
    const ws = MockWebSocket.instances[0];
    const frame = (data: object) => ws.onmessage?.({ data: JSON.stringify(data) });
    act(() => {
      frame({ type: "stream_start", model: "gpt-4o", parent_checkpoint_id: "cp_root" });
      frame({ type: "stream_end", model: "gpt-4o", checkpoint_id: "cp_a" });
      frame({ type: "error", model: "claude-x", message: "boom", parent_checkpoint_id: "cp_root" });
    });

    // No modal for one model: the sibling's reply stays visible.
    expect(mockProps.setErrorModals).not.toHaveBeenCalled();
    expect(result.current.modelErrors).toEqual([
      expect.objectContaining({ model: "claude-x", message: "boom" }),
    ]);

    ws.send.mockClear();
    act(() => result.current.retryModel(result.current.modelErrors[0].id));
    const retried = JSON.parse(ws.send.mock.calls[0][0]);
    expect(retried).toMatchObject({ model: "claude-x", message: "Hello", parent_checkpoint_id: "cp_root" });
    expect(result.current.modelErrors).toEqual([]);
    expect(result.current.isLoading).toBe(true);
  });

  it("keeps a modal for an error that belongs to no model", async () => {
    renderHook(() => useChatWebSocket(mockProps));
    const ws = MockWebSocket.instances[0];
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: "error", message: "bad key" }) }));
    expect(mockProps.setErrorModals).toHaveBeenCalled();
  });

  describe("adding a model to a finished turn", () => {
    it("sends one frame naming the turn by its reply, with no message, and streams into that turn's grid", () => {
      const onTurnJoined = jest.fn();
      const { result } = renderHook(() =>
        useChatWebSocket({ ...mockProps, selectedModels: ["gpt-4o", "claude-x"], onTurnJoined }),
      );
      const ws = MockWebSocket.instances[0];
      const frame = (data: object) => ws.onmessage?.({ data: JSON.stringify(data) });

      act(() => {
        expect(result.current.addModelToTurn("reply_a", "t1", "gemini-y")).toBe(true);
      });
      expect(ws.send).toHaveBeenCalledTimes(1);
      const sent = JSON.parse(ws.send.mock.calls[0][0]);
      expect(sent).toMatchObject({ model: "gemini-y", join_turn: "reply_a", toggles: mockProps.toggles });
      expect(sent).not.toHaveProperty("message");
      expect(sent).not.toHaveProperty("parent_checkpoint_id");
      expect(result.current.liveTurn).toMatchObject({ key: "turn-t1", turnId: "t1", joins: true });
      expect(result.current.isLoading).toBe(true);

      act(() => {
        frame({ type: "stream_start", model: "gemini-y", turn_id: "t1", joins_turn: true, message: null });
        frame({ type: "stream_token", model: "gemini-y", token: "Hi" });
        jest.advanceTimersByTime(50);
      });
      // No question bubble: the question is already on the thread.
      expect(result.current.messages).toEqual([]);
      expect(result.current.liveTurn?.replies).toEqual([expect.objectContaining({ model: "gemini-y", content: "Hi" })]);

      act(() => frame({ type: "stream_end", model: "gemini-y", checkpoint_id: "ng", turn_id: "t1", joins_turn: true }));
      expect(result.current.isLoading).toBe(false);
      expect(result.current.liveTurn?.replies[0]).toMatchObject({ checkpoint_id: "ng", streaming: false });
      // The branch point stays: the join reloads, it doesn't settle a turn.
      expect(onTurnJoined).toHaveBeenCalledWith("thread_1");
      expect(mockProps.onTurnSettled).not.toHaveBeenCalled();
    });

    it("waits for a running turn before adding a model", async () => {
      const { result } = renderHook(() => useChatWebSocket(mockProps));
      await act(async () => {
        await result.current.sendInteractiveMessage("Hello");
      });
      const ws = MockWebSocket.instances[0];
      ws.send.mockClear();
      act(() => {
        expect(result.current.addModelToTurn("reply_a", "t1", "gemini-y")).toBe(false);
      });
      expect(ws.send).not.toHaveBeenCalled();
    });

    it("resumes another tab's join as a card of its turn, without repeating the question", () => {
      const onTurnJoined = jest.fn();
      const { result } = renderHook(() => useChatWebSocket({ ...mockProps, onTurnJoined }));
      const ws = MockWebSocket.instances[0];
      act(() =>
        ws.onmessage?.({
          data: JSON.stringify({
            type: "stream_resume", model: "gemini-y", turn_id: "t1", joins_turn: true, content_so_far: "So far",
            message: null, kind: null, turn_models: ["gpt-4o", "gemini-y"],
          }),
        }),
      );
      expect(result.current.messages).toEqual([]);
      expect(result.current.liveTurn).toMatchObject({ key: "turn-t1", turnId: "t1", joins: true });
      act(() => ws.onmessage?.({ data: JSON.stringify({ type: "stream_end", model: "gemini-y", checkpoint_id: "ng", turn_id: "t1" }) }));
      expect(onTurnJoined).toHaveBeenCalledWith("thread_1");
      expect(mockProps.onTurnSettled).not.toHaveBeenCalled();
    });

    it("retries a refused join with the same frame", () => {
      const { result } = renderHook(() => useChatWebSocket(mockProps));
      const ws = MockWebSocket.instances[0];
      act(() => {
        result.current.addModelToTurn("reply_a", "t1", "gemini-y");
      });
      act(() =>
        ws.onmessage?.({ data: JSON.stringify({ type: "error", model: "gemini-y", message: "busy", joins_turn: true }) }),
      );
      expect(result.current.liveTurn?.replies[0]).toMatchObject({ error: "busy", streaming: false });
      ws.send.mockClear();
      act(() => result.current.retryModel(result.current.modelErrors[0].id));
      expect(JSON.parse(ws.send.mock.calls[0][0])).toMatchObject({ model: "gemini-y", join_turn: "reply_a" });
    });
  });
});
