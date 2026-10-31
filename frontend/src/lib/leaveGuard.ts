import type { Confirm } from "@/hooks/useConfirm";

/**
 * Whether the open thread may be left (another thread, New Session, home).
 *
 * Leaving closes the thread's sockets, which stops models still answering
 * and a live debate. Each asks first: the chat, then the debate (its own
 * `confirmLeave`, which asks only while the debate would be lost). Declining
 * either keeps the person where they are, and a declined chat question never
 * goes on to ask about the debate.
 */
export async function mayLeaveThread({
  answering,
  confirm,
  confirmLeaveDebate,
}: {
  /** Models are still answering a chat turn on this thread. */
  answering: boolean;
  confirm: Confirm;
  confirmLeaveDebate: () => Promise<boolean>;
}): Promise<boolean> {
  if (
    answering &&
    !(await confirm(
      "Leave while models answer?",
      "The models are still answering in this session. Leaving stops them where they are.",
      { confirmLabel: "Stop and leave" },
    ))
  )
    return false;
  return confirmLeaveDebate();
}
