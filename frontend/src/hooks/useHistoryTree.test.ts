import { renderHook, act } from "@testing-library/react";
import { useHistoryTree } from "./useHistoryTree";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/errors";

jest.mock("@/lib/api", () => ({
  fetchHistory: jest.fn(),
}));

const response = (current: string | null, ids: string[] = ["n1"]) => ({
  nodes: ids.map((id) => ({ id })),
  edges: [],
  messages: [{ role: "user", content: "m" }],
  current_checkpoint: current,
});

describe("useHistoryTree", () => {
  const onLoaded = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
  });

  it("starts empty, with nothing chosen and the transcript view", () => {
    const { result } = renderHook(() => useHistoryTree(onLoaded));
    expect(result.current.nodes).toEqual([]);
    expect(result.current.chosen).toBeNull();
    expect(result.current.showTree).toBe(false);
  });

  it("a fetch without a checkpoint sets the head and what is shown, never the choice", async () => {
    (api.fetchHistory as jest.Mock).mockResolvedValue(response("head_1"));
    const { result } = renderHook(() => useHistoryTree(onLoaded));
    await act(async () => {
      await result.current.fetchHistory("thread_1");
    });
    expect(result.current.head).toBe("head_1");
    expect(result.current.shown).toBe("head_1");
    expect(result.current.chosen).toBeNull();
    expect(onLoaded).toHaveBeenCalledWith([{ role: "user", content: "m" }]);
  });

  it("a fetch at a checkpoint moves what is shown, not the head", async () => {
    (api.fetchHistory as jest.Mock).mockResolvedValueOnce(response("head_1")).mockResolvedValueOnce(response("cp_x"));
    const { result } = renderHook(() => useHistoryTree(onLoaded));
    await act(async () => {
      await result.current.fetchHistory("thread_1");
      await result.current.fetchHistory("thread_1", "cp_x");
    });
    expect(result.current.head).toBe("head_1");
    expect(result.current.shown).toBe("cp_x");
  });

  it("honours a null head: an empty thread has nothing to continue", async () => {
    (api.fetchHistory as jest.Mock).mockResolvedValueOnce(response("head_1")).mockResolvedValueOnce(response(null, []));
    const { result } = renderHook(() => useHistoryTree(onLoaded));
    await act(async () => {
      await result.current.fetchHistory("thread_1");
      await result.current.fetchHistory("thread_2");
    });
    expect(result.current.head).toBeNull();
    expect(result.current.nodes).toEqual([]);
  });

  it("forgets the chosen checkpoint when another thread opens", async () => {
    (api.fetchHistory as jest.Mock).mockResolvedValue(response("h"));
    const { result } = renderHook(() => useHistoryTree(onLoaded));
    await act(async () => {
      await result.current.fetchHistory("thread_1");
    });
    act(() => result.current.setChosen("old_cp"));
    await act(async () => {
      await result.current.fetchHistory("thread_2");
    });
    expect(result.current.chosen).toBeNull();
  });

  it("keeps the tree on screen while the same thread reloads", async () => {
    let resolve: (v: unknown) => void = () => {};
    (api.fetchHistory as jest.Mock)
      .mockResolvedValueOnce(response("h", ["n1", "n2"]))
      .mockReturnValueOnce(new Promise((r) => (resolve = r)));
    const { result } = renderHook(() => useHistoryTree(onLoaded));
    await act(async () => {
      await result.current.fetchHistory("thread_1");
    });
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.fetchHistory("thread_1");
    });
    expect(result.current.nodes).toHaveLength(2);
    await act(async () => {
      resolve(response("h", ["n1", "n2", "n3"]));
      await pending;
    });
    expect(result.current.nodes).toHaveLength(3);
  });

  it("drops a response that arrives after a newer request", async () => {
    let slow: (v: unknown) => void = () => {};
    (api.fetchHistory as jest.Mock)
      .mockReturnValueOnce(new Promise((r) => (slow = r)))
      .mockResolvedValueOnce(response("new_head", ["fresh"]));
    const { result } = renderHook(() => useHistoryTree(onLoaded));
    let first: Promise<void> = Promise.resolve();
    act(() => {
      first = result.current.fetchHistory("thread_1");
    });
    await act(async () => {
      await result.current.fetchHistory("thread_2");
    });
    await act(async () => {
      slow(response("stale_head", ["stale"]));
      await first;
    });
    expect(result.current.head).toBe("new_head");
    expect(result.current.nodes).toEqual([{ id: "fresh" }]);
    expect(onLoaded).toHaveBeenCalledTimes(1);
  });

  it("reports a failed load", async () => {
    (api.fetchHistory as jest.Mock).mockRejectedValue(new ApiError("Thread not found", 404));
    const pushToast = jest.fn();
    const { result } = renderHook(() => useHistoryTree(onLoaded, pushToast));
    await act(async () => {
      await result.current.fetchHistory("thread_1");
    });
    expect(pushToast).toHaveBeenCalledWith("Thread not found", "error");
    expect(result.current.isHistoryLoading).toBe(false);
  });

  it("remembers the view as the person left it", () => {
    const { result, rerender } = renderHook(() => useHistoryTree(onLoaded));
    act(() => result.current.setShowTree(true));
    rerender();
    expect(result.current.showTree).toBe(true);
    expect(localStorage.getItem("crucible_view")).toBe("tree");
  });

  it("clears everything", () => {
    const { result } = renderHook(() => useHistoryTree(onLoaded));
    act(() => {
      result.current.setNodes([{ id: "n1", data: { label: "" }, position: { x: 0, y: 0 } }]);
      result.current.setChosen("cp_x");
    });
    act(() => result.current.clearTree());
    expect(result.current.nodes).toEqual([]);
    expect(result.current.chosen).toBeNull();
  });
});
