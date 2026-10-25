/**
 * The chat "Synthesize" request: merge sibling answers to one prompt.
 *
 * The backend recognises (and hides) the prompt by SYNTHESIS_MARKER, as it
 * did before synthesis turns were tagged, so keep that sentence intact.
 */
export const SYNTHESIS_MARKER = "Please act as the Crucible Lead. Synthesize these viewpoints";

export interface SynthesisAnswer {
  /** Display name of the model that wrote it. */
  author: string;
  content: string;
}

export function buildSynthesisPrompt(answers: SynthesisAnswer[]): string {
  const body = answers.map((a) => `[${a.author}]:\n${a.content}`).join("\n\n");
  return (
    `I have received perspectives from multiple models:\n${body}\n\n` +
    `${SYNTHESIS_MARKER} into a single, cohesive answer: state where they agree, ` +
    "resolve or flag where they contradict each other, and keep the strongest supported points."
  );
}

/** The reply a branch ends in: the last assistant message on its path. */
export function lastReply(
  messages: { role: string; content: string; model?: string; model_name?: string | null }[],
  modelLabel: (id: string) => string,
): SynthesisAnswer | null {
  const reply = [...messages].reverse().find((m) => m.role === "assistant");
  if (!reply) return null;
  return { author: reply.model_name || (reply.model ? modelLabel(reply.model) : "Assistant"), content: reply.content };
}
