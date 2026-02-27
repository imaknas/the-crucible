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
  url: string;
  readyState: number = 1; // OPEN
  onmessage: ((event: any) => void) | null = null;
  onclose: (() => void) | null = null;
  send = jest.fn();
  close = jest.fn();

  constructor(url: string) {
    this.url = url;
  }
}

describe("useChatWebSocket", () => {
  const mockProps = {
    threadId: "thread_1",
    activeCheckpoint: "cp_1",
    selectedModels: ["gpt-4o"],
    toggles: { strict_logic: true },
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
      { role: "user", content: "Hello Crucible", type: "human" },
    ]);
    expect(mockProps.clearDocuments).toHaveBeenCalled();
  });

  it("synthesizes consensus correctly", async () => {
    const { result } = renderHook(() => useChatWebSocket(mockProps));

    await act(async () => {
      await result.current.synthesizeConsensus(["View 1", "View 2"]);
    });

    expect(result.current.isLoading).toBe(true);
    expect(mockProps.clearDocuments).toHaveBeenCalled();
  });
});
