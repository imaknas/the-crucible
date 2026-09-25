import { renderHook, act } from "@testing-library/react";
import { useChatWebSocket } from "./useChatWebSocket";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  createWebSocketUrl: jest
    .fn()
    .mockImplementation((tid) => `ws://localhost/test-ws/${tid}`),
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

  it("synthesizes consensus correctly", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));

    await act(async () => {
      await result.current.synthesizeConsensus(["View 1", "View 2"], "cp_1");
    });

    expect(result.current.isLoading).toBe(true);
    expect(mockProps.clearDocuments).toHaveBeenCalled();
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
});
