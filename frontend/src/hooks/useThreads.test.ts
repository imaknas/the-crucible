import { renderHook, act } from "@testing-library/react";
import { useThreads } from "./useThreads";
import * as api from "@/lib/api";

// Mock the API library
jest.mock("@/lib/api", () => ({
  listThreads: jest.fn(),
  deleteThread: jest.fn(),
  renameThread: jest.fn(),
}));

describe("useThreads", () => {
  const mockOnThreadClear = jest.fn();
  const mockOnThreadSwitch = jest.fn();
  const mockShowConfirm = jest.fn().mockResolvedValue(true);

  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    (api.listThreads as jest.Mock).mockResolvedValue({
      threads: [{ id: "thread_1", title: "Test Thread" }],
    });
  });

  it("fetches threads on mount and sets threadId to null to show landing page", async () => {
    const { result } = renderHook(() =>
      useThreads(mockOnThreadClear, mockOnThreadSwitch, mockShowConfirm),
    );

    expect(result.current.threadId).toBeNull();

    // Wait for the async fetch to settle
    await act(async () => {
      await Promise.resolve();
    });

    expect(api.listThreads).toHaveBeenCalledTimes(1);
    expect(result.current.threads).toEqual([
      { id: "thread_1", title: "Test Thread" },
    ]);
  });

  it("starts a new experiment and clears thread state", async () => {
    const { result } = renderHook(() =>
      useThreads(mockOnThreadClear, mockOnThreadSwitch, mockShowConfirm),
    );

    await act(async () => {
      result.current.startNewExperiment();
    });

    expect(result.current.threadId).toMatch(/^thread_/);
    expect(localStorage.getItem("crucible_thread_id")).toBe(
      result.current.threadId,
    );
    expect(mockOnThreadClear).toHaveBeenCalled();
    expect(api.listThreads).toHaveBeenCalled(); // Should refetch
  });

  it("switches thread and calls onThreadSwitch callback", () => {
    const { result } = renderHook(() =>
      useThreads(mockOnThreadClear, mockOnThreadSwitch, mockShowConfirm),
    );

    act(() => {
      result.current.switchThread("thread_2");
    });

    expect(result.current.threadId).toBe("thread_2");
    expect(localStorage.getItem("crucible_thread_id")).toBe("thread_2");
    expect(mockOnThreadSwitch).toHaveBeenCalledWith("thread_2");
  });

  it("deletes a thread successfully after confirmation", async () => {
    const { result } = renderHook(() =>
      useThreads(mockOnThreadClear, mockOnThreadSwitch, mockShowConfirm),
    );

    // Fake event
    const mockEvent = {
      stopPropagation: jest.fn(),
    } as unknown as React.MouseEvent;

    await act(async () => {
      await result.current.deleteThread(mockEvent, "thread_1");
    });

    expect(mockEvent.stopPropagation).toHaveBeenCalled();
    expect(mockShowConfirm).toHaveBeenCalled();
    expect(api.deleteThread).toHaveBeenCalledWith("thread_1");
    expect(api.listThreads).toHaveBeenCalled();
  });
});
