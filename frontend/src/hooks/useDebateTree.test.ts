import { renderHook, act } from "@testing-library/react";
import { useDebateTree } from "./useDebateTree";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({ fetchDebateTree: jest.fn() }));

const fetchMock = api.fetchDebateTree as jest.Mock;

const tree = (sessionId: string, nodeIds: string[] = []) => ({
  nodes: nodeIds.map((id) => ({ id, data: { label: id }, position: { x: 0, y: 0 }, metadata: {} })),
  edges: [],
  lanes: [],
  session_metadata: { session_id: sessionId, status: "running" },
});

describe("useDebateTree", () => {
  beforeEach(() => fetchMock.mockReset());

  afterEach(() => jest.useRealTimers());

  it("resolving round N keeps the model's round N+1 placeholder", async () => {
    jest.useFakeTimers();
    let release: (v: unknown) => void = () => {};
    fetchMock.mockImplementation(() => new Promise((r) => { release = r; }));
    const { result } = renderHook(() => useDebateTree());

    act(() => {
      void result.current.fetchTree("s1");
    });
    release(tree("s1"));
    act(() => result.current.addPendingNode("gpt-5.4", 0, 0, "#000"));
    let resolving: Promise<void> = Promise.resolve();
    act(() => {
      resolving = result.current.resolvePendingNode("gpt-5.4", "s1", 0);
    });
    act(() => jest.advanceTimersByTime(500));
    // The next round starts while round 0's refetch is still in flight.
    act(() => result.current.addPendingNode("gpt-5.4", 1, 0, "#000"));
    await act(async () => {
      release(tree("s1"));
      await resolving;
    });

    expect(result.current.nodes.map((n) => n.id)).toEqual(["gpt-5.4::pending-r1"]);
  });

  it("refetches once for replies that finish together", async () => {
    jest.useFakeTimers();
    fetchMock.mockResolvedValue(tree("s1"));
    const { result } = renderHook(() => useDebateTree());
    await act(async () => {
      await result.current.fetchTree("s1");
    });
    fetchMock.mockClear();
    act(() => {
      void result.current.refreshSoon("s1");
      void result.current.refreshSoon("s1");
      void result.current.refreshSoon("s1");
    });
    await act(async () => {
      jest.advanceTimersByTime(500);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("drops a late response for a session it has moved away from", async () => {
    const resolvers: Record<string, (v: unknown) => void> = {};
    fetchMock.mockImplementation((id: string) => new Promise((r) => { resolvers[id] = r; }));
    const { result } = renderHook(() => useDebateTree());

    let first: Promise<void> = Promise.resolve();
    act(() => { first = result.current.fetchTree("old"); });
    let second: Promise<void> = Promise.resolve();
    act(() => { second = result.current.fetchTree("new"); });

    await act(async () => {
      resolvers["new"](tree("new", ["new-node"]));
      await second;
      resolvers["old"](tree("old", ["old-node"]));
      await first;
    });

    expect(result.current.nodes.map((n) => n.id)).toEqual(["new-node"]);
  });
});

describe("useDebateTree settling", () => {
  beforeEach(() => fetchMock.mockReset());

  it("turns a finished reply's placeholder into the server's node at once", async () => {
    fetchMock.mockResolvedValue(tree("s1"));
    const { result } = renderHook(() => useDebateTree());
    await act(async () => {
      await result.current.fetchTree("s1");
    });
    act(() => result.current.addPendingNode("gpt-5.4", 0, 0, "#000", "GPT-5.4"));
    act(() => result.current.settlePendingNode("gpt-5.4", 0, "cp-1", "**Yes.** A hot dog is a sandwich because " + "x ".repeat(300)));

    const node = result.current.nodes.find((n) => n.id === "gpt-5.4::cp-1");
    expect(node?.metadata?.pending).toBe(false);
    expect(node?.data.label.startsWith("Yes. A hot dog")).toBe(true);
    expect((node?.metadata?.preview as string).length).toBeLessThanOrEqual(403);
    expect(result.current.pendingModels.size).toBe(0);

    // The next round's placeholder doesn't drop it before the server has it.
    act(() => result.current.addPendingNode("gpt-5.4", 1, 0, "#000"));
    expect(result.current.nodes.map((n) => n.id)).toEqual(["gpt-5.4::cp-1", "gpt-5.4::pending-r1"]);
  });

  it("hangs a placeholder after a failed round off the lane's latest earlier node", async () => {
    fetchMock.mockResolvedValue({
      ...tree("s1"),
      nodes: [{ id: "m::cp0", data: { label: "r0" }, position: { x: 0, y: 0 }, metadata: { active_peer: "m", round_num: 0 } }],
    });
    const { result } = renderHook(() => useDebateTree());
    await act(async () => {
      await result.current.fetchTree("s1");
    });
    act(() => result.current.addPendingNode("m", 2, 0, "#000"));
    expect(result.current.edges).toEqual([{ id: "e-m::cp0-m::pending-r2", source: "m::cp0", target: "m::pending-r2" }]);
  });
});
