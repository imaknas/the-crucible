import { act, renderHook, waitFor } from "@testing-library/react";
import * as api from "@/lib/api";
import { useVotes } from "./useVotes";

jest.mock("@/lib/api", () => ({ listVotes: jest.fn(), voteTurn: jest.fn() }));
const mocked = api as jest.Mocked<typeof api>;

beforeEach(() => {
  jest.resetAllMocks();
  localStorage.clear();
});

describe("useVotes", () => {
  it("loads a thread's votes by turn, records a new one and remembers the task type", async () => {
    mocked.listVotes.mockResolvedValue([]);
    const stored = { turn_id: "turn-1", outcome: "tie" } as never;
    mocked.voteTurn.mockResolvedValue(stored);
    const pushToast = jest.fn(); // stable, as the page's is
    const { result } = renderHook(() => useVotes("t1", pushToast));
    await waitFor(() => expect(mocked.listVotes).toHaveBeenCalledWith("t1"));
    expect(result.current.blind).toBe(false);
    let ok = false;
    await act(async () => {
      ok = await result.current.vote("turn-1", { outcome: "tie", taskType: "writing", blind: false });
    });
    expect(ok).toBe(true);
    expect(result.current.byTurn["turn-1"]).toBe(stored);
    expect(result.current.lastTask).toBe("writing");
    expect(result.current.version).toBe(1);
    act(() => result.current.setBlind(true));
    expect(result.current.blind).toBe(true);
  });

  it("says why a vote failed", async () => {
    mocked.listVotes.mockResolvedValue([]);
    mocked.voteTurn.mockRejectedValue(new Error("nope"));
    const pushToast = jest.fn();
    const { result } = renderHook(() => useVotes("t1", pushToast));
    let ok = true;
    await act(async () => {
      ok = await result.current.vote("turn-1", { outcome: "tie", taskType: "general", blind: false });
    });
    expect(ok).toBe(false);
    expect(pushToast).toHaveBeenCalledWith(expect.any(String), "error");
  });
});
