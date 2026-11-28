/**
 * Per-model angles: in one turn each model can answer the same message from
 * its own angle, e.g. to review a plan from several sides (one its security,
 * another its cost, a third the case against it). The message stays the same
 * for every model; the backend sends each angle with that model's system
 * prompt and keeps it on the reply (graph.ANGLE_CONFIG_KEY). Angles go with
 * one message, like attachments.
 */

/** Angles people reach for when reviewing a plan or an idea; any text works. */
export const ANGLE_SUGGESTIONS = [
  "Security and privacy",
  "Cost and effort",
  "What could stop it from working",
  "The case against it",
  "What is missing",
];

/** The frame field for one model's angle; nothing when it has none. */
export function angleField(angles: Record<string, string>, model: string): { angle?: string } {
  const angle = angles[model]?.trim();
  return angle ? { angle } : {};
}

/** The angles that go with the next message: set, and for a model that answers it. */
export function anglesFor(angles: Record<string, string>, responders: string[]): Record<string, string> {
  return Object.fromEntries(
    responders.flatMap((m) => {
      const angle = angles[m]?.trim();
      return angle ? [[m, angle]] : [];
    }),
  );
}

/**
 * Whether a turn's answers were asked from different angles (an angle and
 * none count as different): they answered different asks, so the backend
 * refuses a vote on them (votes.angles_differ).
 */
export function anglesDiffer(cards: { angle?: string | null }[]): boolean {
  return new Set(cards.map((c) => c.angle || null)).size > 1;
}
