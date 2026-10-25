/**
 * Which composer actions are available, and why not when they aren't.
 *
 * Disabled buttons used to explain nothing (or, for Deliberate with an empty
 * box, looked enabled and did nothing). Every disabled action now carries the
 * reason its tooltip shows.
 */
export interface ComposerState {
  isLoading: boolean;
  modelCount: number;
  /** Whether the conversation has anything to review yet. */
  hasHistory: boolean;
  hasText: boolean;
}

export interface ComposerAction {
  enabled: boolean;
  /** Tooltip: what the action does, or why it is unavailable. */
  hint: string;
}

const BUSY = "Wait for the current replies to finish";

export function deliberateAction({ isLoading, modelCount, hasHistory }: ComposerState): ComposerAction {
  if (isLoading) return { enabled: false, hint: BUSY };
  if (modelCount === 0) return { enabled: false, hint: "Select one model to deliberate" };
  if (modelCount > 1)
    return {
      enabled: false,
      hint: `Deliberation needs exactly 1 model selected (${modelCount} are selected)`,
    };
  if (!hasHistory)
    return { enabled: false, hint: "Deliberation reviews the conversation so far; send a message first" };
  return {
    enabled: true,
    hint: "Ask the selected model to critique the conversation so far. Anything you typed is added as instructions.",
  };
}

export function debateAction({ isLoading, modelCount, hasText }: ComposerState): ComposerAction {
  if (isLoading) return { enabled: false, hint: BUSY };
  if (modelCount < 2) return { enabled: false, hint: "Select 2 or more models to start a debate" };
  if (!hasText) return { enabled: false, hint: "Type the question the models should debate" };
  return { enabled: true, hint: "Start a multi-round debate between the selected models" };
}

export function sendAction({ isLoading, modelCount, hasText }: ComposerState): ComposerAction {
  if (isLoading) return { enabled: false, hint: BUSY };
  if (modelCount === 0) return { enabled: false, hint: "Select a model first" };
  if (!hasText) return { enabled: false, hint: "Type a message" };
  return {
    enabled: true,
    hint: modelCount > 1 ? `Send to all ${modelCount} selected models` : "Send",
  };
}
