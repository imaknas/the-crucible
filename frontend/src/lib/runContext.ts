/**
 * The per-run choices the person makes in the Control Panel, as they travel
 * on a request: top-level frame fields (never inside `toggles`), which the
 * backend reads with `ContextSettings.from_frame`. A field is omitted when
 * unset so the backend's default applies.
 */
export interface RunContext {
  /** Model that summarizes long history; null = the backend's default. */
  summarizer?: string | null;
  /** Sent to every model before the conversation; null = no system prompt. */
  systemPrompt?: string | null;
  /** How hard the answering models reason (lib/effort); null = each model's default. */
  reasoningEffort?: string | null;
}

export function contextFields({ summarizer, systemPrompt, reasoningEffort }: RunContext): {
  summarizer?: string;
  system_prompt?: string;
  reasoning_effort?: string;
} {
  const fields: { summarizer?: string; system_prompt?: string; reasoning_effort?: string } = {};
  if (summarizer) fields.summarizer = summarizer;
  if (systemPrompt && systemPrompt.trim()) fields.system_prompt = systemPrompt;
  if (reasoningEffort) fields.reasoning_effort = reasoningEffort;
  return fields;
}
