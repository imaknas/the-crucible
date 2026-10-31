import { act, renderHook } from "@testing-library/react";
import { useReplyTarget } from "./useReplyTarget";
import type { TreeNode } from "@/lib/types";

const selected = ["gpt-x", "claude-x", "gemini-x"];
const replyBy = (model: string, id = `a-${model}`): TreeNode => ({
  id,
  data: { label: "answer" },
  position: { x: 0, y: 0 },
  metadata: { role: "ai", active_peer: model },
});
const claudeReply = replyBy("claude-x");
const question: TreeNode = {
  ...claudeReply,
  id: "u1",
  metadata: { role: "user" },
};

/** The hook with the branch point following the last node clicked, as the page wires it. */
function setup(thread = "t1") {
  return renderHook(
    ({ thread, branch }: { thread: string; branch: TreeNode | undefined }) =>
      useReplyTarget(thread, selected, branch),
    { initialProps: { thread, branch: undefined as TreeNode | undefined } },
  );
}

describe("useReplyTarget", () => {
  it("continues a clicked reply with its model and leaves the selection alone", () => {
    const { result, rerender } = setup();
    expect(result.current.responders).toEqual(selected);

    act(() => result.current.continueFrom(claudeReply));
    rerender({ thread: "t1", branch: claudeReply });
    expect(result.current.responders).toEqual(["claude-x"]);
    expect(result.current.canAskAll).toBe(true);
    expect(selected).toEqual(["gpt-x", "claude-x", "gemini-x"]);
  });

  it("keeps the model on each reply it writes from there", () => {
    const { result, rerender } = setup();
    act(() => result.current.continueFrom(claudeReply));
    rerender({ thread: "t1", branch: replyBy("claude-x", "a-next") });
    expect(result.current.responders).toEqual(["claude-x"]);
  });

  it("asks every selected model from the reply when switched, and only its model again", () => {
    const { result, rerender } = setup();
    act(() => result.current.continueFrom(claudeReply));
    rerender({ thread: "t1", branch: claudeReply });
    act(() => result.current.setAskAll(true));
    expect(result.current.responders).toEqual(selected);
    act(() => result.current.setAskAll(false));
    expect(result.current.responders).toEqual(["claude-x"]);
  });

  it("lets the selection answer once the branch point is another model's reply", () => {
    const { result, rerender } = setup();
    act(() => result.current.continueFrom(claudeReply));
    rerender({ thread: "t1", branch: claudeReply });
    // e.g. every selected model answered and the newest reply is GPT's.
    rerender({ thread: "t1", branch: replyBy("gpt-x") });
    expect(result.current.responders).toEqual(selected);
    expect(result.current.canAskAll).toBe(false);
  });

  it("goes back to the selection on the person's message, a reset or another thread", () => {
    const { result, rerender } = setup();
    act(() => result.current.continueFrom(claudeReply));
    act(() => result.current.continueFrom(question));
    rerender({ thread: "t1", branch: question });
    expect(result.current.responders).toEqual(selected);

    act(() => result.current.continueFrom(claudeReply));
    rerender({ thread: "t1", branch: claudeReply });
    act(() => result.current.reset());
    expect(result.current.responders).toEqual(selected);

    act(() => result.current.continueFrom(claudeReply));
    rerender({ thread: "t2", branch: claudeReply });
    expect(result.current.responders).toEqual(selected);
  });

  it("a clicked reply starts out answered by its model alone", () => {
    const { result, rerender } = setup();
    act(() => result.current.continueFrom(claudeReply));
    rerender({ thread: "t1", branch: claudeReply });
    act(() => result.current.setAskAll(true));
    act(() => result.current.continueFrom(claudeReply));
    expect(result.current.askAll).toBe(false);
  });
});
