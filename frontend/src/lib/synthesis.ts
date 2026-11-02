/**
 * Ways to ask for a synthesis (the backend's synthesis.SYNTHESIS_MODES) and
 * what each reply is called. merge: one answer from many; compare: a table of
 * where they differ; checklist: one answer from the components the person
 * kept; ask: the person's own question about the answers.
 */
export type SynthesisMode = "merge" | "compare" | "checklist" | "ask";

export interface SynthesisRequest {
  mode: SynthesisMode;
  /** checklist: the component texts kept (from POST /synthesis/components). */
  keep?: string[];
  /** ask: the person's question about the answers. */
  question?: string;
}

export const SYNTHESIS_MODES: { mode: SynthesisMode; action: string; description: string }[] = [
  { mode: "merge", action: "Merge into one answer", description: "One answer that keeps the strongest points and flags contradictions." },
  { mode: "compare", action: "Compare in a table", description: "Where the answers differ, what they agree on, what only one covers. No winner." },
  { mode: "checklist", action: "Pick the parts to keep…", description: "Split the answers into parts, tick the ones you want, then merge just those." },
  { mode: "ask", action: "Ask about them…", description: "Your own question, answered from these answers." },
];

/** The chat frame's synthesis fields (api/chat.py), only what the mode needs. */
export function synthesisFrameFields(request: SynthesisRequest = { mode: "merge" }): Record<string, unknown> {
  return {
    synthesis_mode: request.mode,
    ...(request.mode === "checklist" ? { keep_components: request.keep ?? [] } : {}),
    ...(request.mode === "ask" ? { synthesis_question: request.question ?? "" } : {}),
  };
}

/** What a synthesis reply is, in its bubble and tree node (replies before modes are merges). */
export function synthesisLabel(mode?: string | null): string {
  switch (mode) {
    case "compare":
      return "Comparison";
    case "checklist":
      return "Synthesis of kept parts";
    case "ask":
      return "Answer about the selection";
    default:
      return "Synthesis";
  }
}
