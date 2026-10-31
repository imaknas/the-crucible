import { renderHook, act } from "@testing-library/react";
import { useChatWebSocket } from "./useChatWebSocket";
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
    activeCheckpoint: "cp_1",
    selectedModels: ["gpt-4o"],
    toggles: {
      use_rag: true,
      use_web_search: false,
    },
    documents: {},
    clearDocuments: jest.fn(),
    onHistoryRefreshNeeded: jest.fn(),
    setActiveCheckpoint: jest.fn(),
    setErrorModals: jest.fn(),
    showConfirm: jest.fn().mockResolvedValue(true),
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
      await result.current.synthesizeBranches(["a1", "a2"], "cp_1");
    });

    expect(result.current.isLoading).toBe(true);
    expect(mockProps.clearDocuments).toHaveBeenCalled();
    const frame = JSON.parse(MockWebSocket.instances[0].send.mock.calls[0][0]);
    expect(frame).toMatchObject({
      type: "synthesis",
      model: "gpt-4o",
      parent_checkpoint_id: "cp_1",
      answer_checkpoint_ids: ["a1", "a2"],
    });
    expect(frame).not.toHaveProperty("message");
  });

  it("synthesizes with the chosen synthesizer, streaming as a synthesis", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.synthesizeBranches(["a1", "a2"], "cp_1", "claude-x");
    });
    const ws = MockWebSocket.instances[0];
    expect(JSON.parse(ws.send.mock.calls[0][0]).model).toBe("claude-x");

    act(() => ws.onmessage?.({ data: JSON.stringify({ type: "stream_start", model: "claude-x" }) }));
    expect(result.current.messages.at(-1)).toMatchObject({ type: "synthesis", model: "claude-x" });
  });

  it("does not synthesize fewer than two answers", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));
    await act(async () => {
      await result.current.synthesizeBranches(["a1"], "cp_1");
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
      await result.current.synthesizeBranches(["a1", "a2"], "cp_1");
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

  it("sends an ordinary turn from the active checkpoint", async () => {
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
    expect(mockProps.showConfirm).toHaveBeenCalled();
  });

  it("reconnects after an unexpected close", () => {
    renderHook(() => useChatWebSocket(mockProps));
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => {
      MockWebSocket.instances[0].onclose?.({ wasClean: false, code: 1006 });
      jest.advanceTimersByTime(2000);
    });

    expect(MockWebSocket.instances).toHaveLength(2);
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
});
