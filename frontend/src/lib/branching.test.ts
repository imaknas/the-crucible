import { branchPoint } from "./branching";
import type { TreeNode } from "./types";

const node = (id: string, role: string, label: string): TreeNode => ({
  id,
  data: { label },
  position: { x: 0, y: 0 },
  metadata: { role, preview: label },
});

const nodes = [
  node("1-root", "system", "Start"),
  node("2-q", "user", "What does branching buy me?"),
  node("3-a", "ai", "A long answer ".repeat(10)),
  node("4-q", "user", "Follow-up"),
];

describe("branchPoint", () => {
  it("names the node the next message branches from, clipped", () => {
    const bp = branchPoint(nodes, "3-a")!;
    expect(bp.preview.length).toBeLessThanOrEqual(60);
    expect(bp.preview.endsWith("…")).toBe(true);
    expect(bp.isLatest).toBe(false);
    expect(bp.latestId).toBe("4-q");
  });

  it("knows when you are already on the newest node", () => {
    expect(branchPoint(nodes, "4-q")!.isLatest).toBe(true);
  });

  it("has nothing to say for an empty tree or no selection", () => {
    expect(branchPoint([nodes[0]], "1-root")).toBeNull();
    expect(branchPoint(nodes, null)).toBeNull();
  });
});
