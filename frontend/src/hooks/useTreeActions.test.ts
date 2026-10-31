import { renderHook, act } from "@testing-library/react";
import { useTreeActions } from "./useTreeActions";
import type { TreeEdge, TreeNode } from "@/lib/types";

jest.mock("@/lib/api", () => ({
  deleteCheckpoint: jest.fn(),
  saveNodePositions: jest.fn(),
}));

const nodes: TreeNode[] = [
  { id: "u1", data: { label: "question" }, position: { x: 0, y: 0 }, metadata: { role: "user" } },
  {
    id: "a1",
    data: { label: "answer" },
    position: { x: 0, y: 150 },
    metadata: { role: "ai", active_peer: "claude-sonnet-5-5" },
  },
];
const edges: TreeEdge[] = [{ id: "e-u1-a1", source: "u1", target: "a1" }];

function setup() {
  const props = {
    threadId: "thread_1",
    nodes,
    edges,
    setNodes: jest.fn(),
    activeCheckpoint: null,
    setActiveCheckpoint: jest.fn(),
    fetchHistory: jest.fn(),
    fetchThreads: jest.fn(),
    clearChatMessages: jest.fn(),
    setInput: jest.fn(),
    setShowTree: jest.fn(),
    confirm: jest.fn().mockResolvedValue(true),
    pushToast: jest.fn(),
    continueFrom: jest.fn(),
  };
  const { result } = renderHook(() => useTreeActions(props));
  return { props, result };
}

describe("useTreeActions.selectCheckpoint", () => {
  it("opens a clicked reply and continues from it", () => {
    const { props, result } = setup();
    act(() => result.current.selectCheckpoint("a1"));
    expect(props.setActiveCheckpoint).toHaveBeenCalledWith("a1");
    expect(props.continueFrom).toHaveBeenCalledWith(nodes[1]);
    expect(props.fetchHistory).toHaveBeenCalledWith("thread_1", "a1");
  });

  it("continues from a clicked user message too", () => {
    const { props, result } = setup();
    act(() => result.current.selectCheckpoint("u1"));
    expect(props.setActiveCheckpoint).toHaveBeenCalledWith("u1");
    expect(props.continueFrom).toHaveBeenCalledWith(nodes[0]);
  });
});

describe("useTreeActions branching", () => {
  it("branches from a node: selects it and brings up the composer", () => {
    const { props, result } = setup();
    act(() => result.current.branchFrom("u1"));
    expect(props.setActiveCheckpoint).toHaveBeenCalledWith("u1");
    expect(props.setShowTree).toHaveBeenCalledWith(false);
  });

  it("reports the branch point for the composer chip", () => {
    const { result } = setup();
    // No active checkpoint in this setup.
    expect(result.current.branch).toBeNull();
  });
});

describe("useTreeActions.resetToLatest", () => {
  it("returns to the newest message without changing who answers", () => {
    // Checkpoint ids are time-ordered: "2-a" is newer than "1-u".
    const ordered = [
      { ...nodes[0], id: "1-u" },
      { ...nodes[1], id: "2-a" },
    ];
    const props = {
      threadId: "thread_1",
      nodes: ordered,
      edges: [{ id: "e", source: "1-u", target: "2-a" }],
      setNodes: jest.fn(),
      activeCheckpoint: "1-u",
      setActiveCheckpoint: jest.fn(),
      fetchHistory: jest.fn(),
      fetchThreads: jest.fn(),
      clearChatMessages: jest.fn(),
      setInput: jest.fn(),
      setShowTree: jest.fn(),
      confirm: jest.fn().mockResolvedValue(true),
      pushToast: jest.fn(),
      continueFrom: jest.fn(),
    };
    const { result } = renderHook(() => useTreeActions(props));
    expect(result.current.branch?.isLatest).toBe(false);
    act(() => result.current.resetToLatest());
    expect(props.setActiveCheckpoint).toHaveBeenCalledWith("2-a");
    expect(props.continueFrom).not.toHaveBeenCalled();
  });
});

