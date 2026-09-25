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

  it("resolving round N keeps the model's round N+1 placeholder", async () => {
    let release: (v: unknown) => void = () => {};
    fetchMock.mockImplementation(() => new Promise((r) => { release = r; }));
    const { result } = renderHook(() => useDebateTree());

    act(() => result.current.addPendingNode("gpt-5.4", 0, 0, "#000"));
    let resolving: Promise<void> = Promise.resolve();
    act(() => {
      resolving = result.current.resolvePendingNode("gpt-5.4", "s1", 0);
    });
    // The next round starts while round 0's refetch is still in flight.
    act(() => result.current.addPendingNode("gpt-5.4", 1, 0, "#000"));
    await act(async () => {
      release(tree("s1"));
      await resolving;
    });

    expect(result.current.nodes.map((n) => n.id)).toEqual(["gpt-5.4::pending-r1"]);
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
