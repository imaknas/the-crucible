import { renderHook, act } from "@testing-library/react";
import { useThreads } from "./useThreads";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/errors";

jest.mock("@/lib/api", () => ({
  listThreads: jest.fn(),
  deleteThread: jest.fn(),
  renameThread: jest.fn(),
}));

describe("useThreads", () => {
  const options = () => ({
    onThreadClear: jest.fn(),
    onThreadSwitch: jest.fn(),
    confirm: jest.fn().mockResolvedValue(true),
    pushToast: jest.fn(),
  });

  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    (api.listThreads as jest.Mock).mockResolvedValue({
      threads: [{ id: "thread_1", title: "Test Thread" }],
    });
  });

  it("fetches threads on mount and sets threadId to null to show landing page", async () => {
    const { result } = renderHook(() => useThreads(options()));
    expect(result.current.threadId).toBeNull();
    await act(async () => {
      await Promise.resolve();
    });
    expect(api.listThreads).toHaveBeenCalledTimes(1);
    expect(result.current.threads).toEqual([{ id: "thread_1", title: "Test Thread" }]);
  });

  it("starts a new experiment and clears thread state", async () => {
    const opts = options();
    const { result } = renderHook(() => useThreads(opts));
    await act(async () => {
      await result.current.startNewExperiment();
    });
    expect(result.current.threadId).toMatch(/^thread_/);
    expect(localStorage.getItem("crucible_thread_id")).toBe(result.current.threadId);
    expect(opts.onThreadClear).toHaveBeenCalled();
    expect(api.listThreads).toHaveBeenCalled();
  });

  it("switches thread and calls onThreadSwitch callback", async () => {
    const opts = options();
    const { result } = renderHook(() => useThreads(opts));
    await act(async () => {
      await result.current.switchThread("thread_2");
    });
    expect(result.current.threadId).toBe("thread_2");
    expect(localStorage.getItem("crucible_thread_id")).toBe("thread_2");
    expect(opts.onThreadSwitch).toHaveBeenCalledWith("thread_2");
  });

  it("stays on the thread when leaving is declined", async () => {
    const opts = { ...options(), beforeLeave: jest.fn().mockResolvedValue(false) };
    const { result } = renderHook(() => useThreads(opts));
    await act(async () => {
      await result.current.switchThread("thread_2");
      await result.current.startNewExperiment();
    });
    expect(result.current.threadId).toBeNull();
    expect(opts.onThreadSwitch).not.toHaveBeenCalled();
    expect(opts.onThreadClear).not.toHaveBeenCalled();
  });

  it("deletes a thread after confirmation and says so", async () => {
    const opts = options();
    const { result } = renderHook(() => useThreads(opts));
    await act(async () => {
      await result.current.deleteThread("thread_1");
    });
    expect(opts.confirm).toHaveBeenCalledWith(expect.any(String), expect.any(String), { confirmLabel: "Delete" });
    expect(api.deleteThread).toHaveBeenCalledWith("thread_1");
    expect(opts.pushToast).toHaveBeenCalledWith("Session deleted.", "success");
    expect(api.listThreads).toHaveBeenCalled();
  });

  it("reports a failed delete with the backend's reason", async () => {
    (api.deleteThread as jest.Mock).mockRejectedValue(new ApiError("Thread is busy", 409));
    const opts = options();
    const { result } = renderHook(() => useThreads(opts));
    await act(async () => {
      await result.current.deleteThread("thread_1");
    });
    expect(opts.pushToast).toHaveBeenCalledWith("Thread is busy", "error");
  });

  it("resolves a rename true on success and false (with a notice) on failure", async () => {
    const opts = options();
    const { result } = renderHook(() => useThreads(opts));
    let ok = false;
    await act(async () => {
      ok = await result.current.renameThread("thread_1", "  New  ");
    });
    expect(ok).toBe(true);
    expect(api.renameThread).toHaveBeenCalledWith("thread_1", "New");

    (api.renameThread as jest.Mock).mockRejectedValue(new ApiError("Title too long", 422));
    await act(async () => {
      ok = await result.current.renameThread("thread_1", "x");
    });
    expect(ok).toBe(false);
    expect(opts.pushToast).toHaveBeenCalledWith("Title too long", "error");
  });

  it("reopens the stored thread without waiting for the thread list", async () => {
    localStorage.setItem("crucible_thread_id", "thread_saved");
    // The list never answers: the history request must not depend on it.
    (api.listThreads as jest.Mock).mockReturnValue(new Promise(() => {}));
    const opts = options();
    const { result } = renderHook(() => useThreads(opts));
    expect(opts.onThreadSwitch).toHaveBeenCalledWith("thread_saved");
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.threadId).toBe("thread_saved");
    expect(result.current.resolved).toBe(true);
  });

  it("is unresolved until it knows whether a thread is reopened", async () => {
    const { result } = renderHook(() => useThreads(options()));
    // threadId null here means "not known yet": the page shows no landing view.
    expect(result.current.resolved).toBe(false);
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.resolved).toBe(true);
    expect(result.current.threadId).toBeNull();
  });

  it("opens the thread named in ?thread= and clears it from the URL", async () => {
    localStorage.setItem("crucible_thread_id", "thread_old");
    window.history.replaceState(null, "", "/?thread=cli-abc123");
    const opts = options();
    const { result } = renderHook(() => useThreads(opts));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.threadId).toBe("cli-abc123");
    expect(opts.onThreadSwitch).toHaveBeenCalledWith("cli-abc123");
    expect(window.location.search).toBe("");
    expect(localStorage.getItem("crucible_thread_id")).toBe("cli-abc123");
  });
});
