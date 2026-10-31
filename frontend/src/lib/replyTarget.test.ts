import { canAskAll, replyModelOf, respondingModels } from "./replyTarget";
import type { TreeNode } from "./types";

const node = (metadata: TreeNode["metadata"]): TreeNode => ({
  id: "n",
  data: { label: "x" },
  position: { x: 0, y: 0 },
  metadata,
});

describe("replyModelOf", () => {
  it("is the author of a model's reply", () => {
    expect(replyModelOf(node({ role: "ai", active_peer: "claude-x" }))).toBe(
      "claude-x",
    );
  });

  it("is nobody for the person's message, the debate record or no node", () => {
    expect(
      replyModelOf(node({ role: "user", active_peer: "claude-x" })),
    ).toBeNull();
    expect(
      replyModelOf(
        node({ role: "ai", kind: "debate", active_peer: "claude-x" }),
      ),
    ).toBeNull();
    expect(replyModelOf(undefined)).toBeNull();
  });
});

describe("respondingModels", () => {
  const selected = ["gpt-x", "claude-x", "gemini-x"];

  it("is the selection when no reply was clicked", () => {
    expect(respondingModels(selected, null, false)).toEqual(selected);
  });

  it("is the clicked reply's model, whatever is selected", () => {
    expect(respondingModels(selected, "claude-x", false)).toEqual(["claude-x"]);
    expect(respondingModels(["gpt-x"], "claude-x", false)).toEqual([
      "claude-x",
    ]);
  });

  it("is the selection again when every selected model is asked", () => {
    expect(respondingModels(selected, "claude-x", true)).toEqual(selected);
  });
});

describe("canAskAll", () => {
  it("only when the selection holds a model besides the reply's", () => {
    expect(canAskAll(["gpt-x", "claude-x"], "claude-x")).toBe(true);
    expect(canAskAll(["claude-x"], "claude-x")).toBe(false);
    expect(canAskAll(["gpt-x"], null)).toBe(false);
  });
});
