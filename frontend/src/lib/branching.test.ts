import { branchPoint } from "./branching";
import type { TreeNode } from "./types";

const node = (id: string, role: string, label: string): TreeNode => ({
  id,
  data: { label },
  position: { x: 0, y: 0 },
  metadata: { role, preview: label },
});

const nodes = [
  node("root", "system", "Start"),
  node("q", "user", "What does branching buy me?"),
  node("a", "ai", "A long answer ".repeat(10)),
  node("q2", "user", "Follow-up"),
];

describe("branchPoint", () => {
  it("names the chosen node, clipped, and says it is not the latest turn", () => {
    const bp = branchPoint(nodes, "a", "q2")!;
    expect(bp.node.id).toBe("a");
    expect(bp.preview.length).toBeLessThanOrEqual(60);
    expect(bp.preview.endsWith("…")).toBe(true);
    expect(bp.isLatest).toBe(false);
  });

  it("is the latest turn when nothing was chosen, shown at the thread's head", () => {
    const bp = branchPoint(nodes, null, "q2")!;
    expect(bp.isLatest).toBe(true);
    expect(bp.node.id).toBe("q2");
  });

  it("a chosen node is never 'latest', even when it is the head", () => {
    // Choosing the head pins the next message to it alone; Latest continues every model.
    expect(branchPoint(nodes, "q2", "q2")!.isLatest).toBe(false);
  });

  it("has nothing to say for an empty tree, the root, or no head", () => {
    expect(branchPoint([nodes[0]], null, "root")).toBeNull();
    expect(branchPoint(nodes, null, null)).toBeNull();
  });
});
