import { renderHook, act } from "@testing-library/react";
import { useHistoryTree } from "./useHistoryTree";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  fetchHistory: jest.fn(),
}));

describe("useHistoryTree", () => {
  const mockOnMessagesLoaded = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("initializes with empty tree and active showing state", () => {
    const { result } = renderHook(() => useHistoryTree(mockOnMessagesLoaded));
    expect(result.current.nodes).toEqual([]);
    expect(result.current.edges).toEqual([]);
    expect(result.current.activeCheckpoint).toBeNull();
    expect(result.current.showTree).toBe(true);
  });

  it("fetches history and updates state properly", async () => {
    (api.fetchHistory as jest.Mock).mockResolvedValue({
      nodes: [{ id: "n1" }],
      edges: [{ id: "e1" }],
      messages: [{ id: "m1" }],
      current_checkpoint: "cp_123",
    });

    const { result } = renderHook(() => useHistoryTree(mockOnMessagesLoaded));

    await act(async () => {
      await result.current.fetchHistory("thread_1", "cp_x");
    });

    expect(api.fetchHistory).toHaveBeenCalledWith("thread_1", "cp_x");
    expect(result.current.nodes).toEqual([{ id: "n1" }]);
    expect(result.current.edges).toEqual([{ id: "e1" }]);
    expect(mockOnMessagesLoaded).toHaveBeenCalledWith([{ id: "m1" }]);
    expect(result.current.activeCheckpoint).toBe("cp_123");
  });

  it("clears the tree properly", () => {
    const { result } = renderHook(() => useHistoryTree(mockOnMessagesLoaded));

    // Manually set some state
    act(() => {
      result.current.setNodes([{ id: "n1" }]);
      result.current.setEdges([{ id: "e1" }]);
      result.current.setActiveCheckpoint("cp_x");
    });

    // Clear the tree
    act(() => {
      result.current.clearTree();
    });

    expect(result.current.nodes).toEqual([]);
    expect(result.current.edges).toEqual([]);
    expect(result.current.activeCheckpoint).toBeNull();
    expect(result.current.showTree).toBe(false);
  });
});
