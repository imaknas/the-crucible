import { useCallback, useMemo, useState } from "react";
import type { TreeNode } from "@/lib/types";
import { canAskAll, replyModelOf, respondingModels } from "@/lib/replyTarget";

interface ReplyState {
  threadId: string | null;
  /** The clicked reply's model; null after clicking any other node. */
  model: string | null;
  /** Every selected model answers from the reply, not only its author. */
  askAll: boolean;
}

/**
 * Who answers the next message: the model of a reply you clicked, or the
 * Control Panel's selection. Not persisted, and forgotten on another thread;
 * the selection itself is never changed here (lib/replyTarget).
 *
 * The clicked model holds while the branch point is that model's reply —
 * a click, then each reply it writes. Once the branch point moves to another
 * model's reply ("Latest", or the newest reply after every selected model
 * answered), the selection answers again; otherwise the chip would offer
 * "only Claude" while replying to GPT.
 */
export function useReplyTarget(
  threadId: string | null,
  selectedModels: string[],
  branchNode: TreeNode | undefined,
) {
  const [reply, setReply] = useState<ReplyState | null>(null);
  const branchAuthor = replyModelOf(branchNode);
  const current =
    reply && reply.threadId === threadId && reply.model === branchAuthor
      ? reply
      : null;
  const replyModel = current?.model ?? null;
  const askAll = current?.askAll ?? false;

  /** A node was clicked: continue a model's reply with that model. */
  const continueFrom = useCallback(
    (node: TreeNode | undefined) =>
      setReply({ threadId, model: replyModelOf(node), askAll: false }),
    [threadId],
  );

  /** Back to the selection, e.g. once a debate is on screen. */
  const reset = useCallback(() => setReply(null), []);

  const setAskAll = useCallback(
    (all: boolean) =>
      setReply((prev) => (prev ? { ...prev, askAll: all } : prev)),
    [],
  );

  const responders = useMemo(
    () => respondingModels(selectedModels, replyModel, askAll),
    [selectedModels, replyModel, askAll],
  );

  return {
    replyModel,
    askAll,
    setAskAll,
    continueFrom,
    reset,
    responders,
    /** Whether the branch chip offers switching between the two. */
    canAskAll: canAskAll(selectedModels, replyModel),
  };
}
