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
    setSelectedModels: jest.fn(),
  };
  const { result } = renderHook(() => useTreeActions(props));
  return { props, result };
}

describe("useTreeActions.selectCheckpoint", () => {
  it("selects the model that wrote a clicked reply", () => {
    const { props, result } = setup();
    act(() => result.current.selectCheckpoint("a1"));
    expect(props.setActiveCheckpoint).toHaveBeenCalledWith("a1");
    expect(props.setSelectedModels).toHaveBeenCalledWith(["claude-sonnet-5-5"]);
    expect(props.fetchHistory).toHaveBeenCalledWith("thread_1", "a1");
  });

  it("leaves the selection alone for a user message", () => {
    const { props, result } = setup();
    act(() => result.current.selectCheckpoint("u1"));
    expect(props.setActiveCheckpoint).toHaveBeenCalledWith("u1");
    expect(props.setSelectedModels).not.toHaveBeenCalled();
  });
});
