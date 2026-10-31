import { renderHook, act } from "@testing-library/react";
import { useTreeActions } from "./useTreeActions";
import * as api from "@/lib/api";
import type { TreeEdge, TreeNode } from "@/lib/types";

jest.mock("@/lib/api", () => ({
  deleteCheckpoint: jest.fn(),
  saveNodePositions: jest.fn(),
  fetchHistory: jest.fn(),
}));

const nodes: TreeNode[] = [
  { id: "root", data: { label: "" }, position: { x: 0, y: 0 }, metadata: { role: "system" } },
  { id: "u1", data: { label: "A question whose label is clipped..." }, position: { x: 0, y: 0 }, metadata: { role: "user" } },
  {
    id: "a1",
    data: { label: "answer" },
    position: { x: 0, y: 150 },
    metadata: { role: "ai", active_peer: "claude-sonnet-5-5" },
  },
];
const edges: TreeEdge[] = [
  { id: "e-root-u1", source: "root", target: "u1" },
  { id: "e-u1-a1", source: "u1", target: "a1" },
];

function setup(overrides: Record<string, unknown> = {}) {
  const props = {
    threadId: "thread_1",
    nodes,
    edges,
    setNodes: jest.fn(),
    chosen: null as string | null,
    setChosen: jest.fn(),
    head: "a1" as string | null,
    shown: "a1" as string | null,
    fetchHistory: jest.fn(),
    fetchThreads: jest.fn(),
    clearChatMessages: jest.fn(),
    setInput: jest.fn(),
    setShowTree: jest.fn(),
    confirm: jest.fn().mockResolvedValue(true),
    pushToast: jest.fn(),
    continueFrom: jest.fn(),
    ...overrides,
  };
  const { result } = renderHook(() => useTreeActions(props));
  return { props, result };
}

beforeEach(() => jest.clearAllMocks());

describe("useTreeActions.selectCheckpoint", () => {
  it("chooses a clicked reply and continues from it", () => {
    const { props, result } = setup();
    act(() => result.current.selectCheckpoint("a1"));
    expect(props.setChosen).toHaveBeenCalledWith("a1");
    expect(props.continueFrom).toHaveBeenCalledWith(nodes[2]);
    expect(props.fetchHistory).toHaveBeenCalledWith("thread_1", "a1");
  });

  it("shows a reply read-only: no choice, no change of who answers", () => {
    const { props, result } = setup();
    act(() => result.current.viewCheckpoint("a1"));
    expect(props.fetchHistory).toHaveBeenCalledWith("thread_1", "a1");
    expect(props.setChosen).not.toHaveBeenCalled();
    expect(props.continueFrom).not.toHaveBeenCalled();
  });
});

describe("useTreeActions branching", () => {
  it("branches from a node: chooses it and brings up the composer", () => {
    const { props, result } = setup();
    act(() => result.current.branchFrom("u1"));
    expect(props.setChosen).toHaveBeenCalledWith("u1");
    expect(props.setShowTree).toHaveBeenCalledWith(false);
  });

  it("continues the latest turn when nothing is chosen", () => {
    const { result } = setup();
    expect(result.current.branch).toMatchObject({ isLatest: true });
    expect(result.current.branch?.node.id).toBe("a1");
  });

  it("goes back to the latest turn without changing who answers", () => {
    const { props, result } = setup({ chosen: "u1" });
    expect(result.current.branch?.isLatest).toBe(false);
    act(() => result.current.resetToLatest());
    expect(props.setChosen).toHaveBeenCalledWith(null);
    expect(props.fetchHistory).toHaveBeenCalledWith("thread_1");
    expect(props.continueFrom).not.toHaveBeenCalled();
  });
});

describe("useTreeActions.editAndRebranch", () => {
  it("puts the message's full text in the composer, not its clipped label, and branches from its parent", async () => {
    const full = "A question whose label is clipped, with **markdown** and a long tail of words.";
    (api.fetchHistory as jest.Mock).mockResolvedValue({ messages: [{ role: "user", content: full }] });
    const { props, result } = setup({ shown: "u1", chosen: "u1" });
    await act(async () => {
      await result.current.editAndRebranch();
    });
    expect(api.fetchHistory).toHaveBeenCalledWith("thread_1", "u1");
    expect(props.setInput).toHaveBeenCalledWith(full);
    expect(props.setChosen).toHaveBeenCalledWith("root");
    expect(props.setShowTree).toHaveBeenCalledWith(false);
  });

  it("reports a failed load and changes nothing", async () => {
    (api.fetchHistory as jest.Mock).mockRejectedValue(new TypeError("Failed to fetch"));
    const { props, result } = setup({ shown: "u1" });
    await act(async () => {
      await result.current.editAndRebranch();
    });
    expect(props.pushToast).toHaveBeenCalledWith(expect.stringMatching(/unreachable/), "error");
    expect(props.setInput).not.toHaveBeenCalled();
    expect(props.setChosen).not.toHaveBeenCalled();
  });
});

describe("useTreeActions.deleteNode", () => {
  it("asks with a Delete button, then continues from the deleted node's parent", async () => {
    const { props, result } = setup({ chosen: "a1" });
    await act(async () => {
      await result.current.deleteNode("a1");
    });
    expect(props.confirm).toHaveBeenCalledWith(expect.any(String), expect.any(String), { confirmLabel: "Delete" });
    expect(api.deleteCheckpoint).toHaveBeenCalledWith("thread_1", "a1");
    expect(props.setChosen).toHaveBeenCalledWith("u1");
    expect(props.fetchThreads).toHaveBeenCalled();
  });

  it("reports a failed delete", async () => {
    (api.deleteCheckpoint as jest.Mock).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { props, result } = setup();
    await act(async () => {
      await result.current.deleteNode("a1");
    });
    expect(props.pushToast).toHaveBeenCalledWith(expect.stringMatching(/Couldn't delete/), "error");
  });
});
