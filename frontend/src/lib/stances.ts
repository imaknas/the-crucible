/**
 * The debate dialog's stance choice, as the backend takes it
 * (services/stances.py): pure, so the rules are tested apart from the form.
 */
import type { DebateStance, StanceMode } from "@/lib/types";

export const SIDE_MAX_CHARS = 200;
export const DEFAULT_SIDES = ["For", "Against"];

export interface StanceChoice {
  mode: StanceMode;
  /** The sides' names, in the order the form lists them. */
  sides: string[];
  /** Participant → index into `sides`. */
  assignment: Record<string, number>;
  advocate: string | null;
}

/** The form's starting point for these participants: sides given in turn, the last participant as advocate. */
export function initialStance(participants: string[]): StanceChoice {
  return {
    mode: "open",
    sides: [...DEFAULT_SIDES],
    assignment: Object.fromEntries(participants.map((m, i) => [m, i % DEFAULT_SIDES.length])),
    advocate: participants[participants.length - 1] ?? null,
  };
}

/** Why the choice can't start a debate, in words, or null. */
export function stanceProblem(choice: StanceChoice, participants: string[]): string | null {
  if (choice.mode === "sides") {
    const names = participants.map((m) => (choice.sides[choice.assignment[m] ?? 0] ?? "").trim());
    if (names.some((n) => !n)) return "Every side needs a name.";
    if (names.some((n) => n.length > SIDE_MAX_CHARS)) return `A side is at most ${SIDE_MAX_CHARS} characters.`;
    if (new Set(names.map((n) => n.toLowerCase().replace(/\s+/g, " "))).size < 2)
      return "Give the participants at least two different sides.";
  }
  if (choice.mode === "advocate" && (!choice.advocate || !participants.includes(choice.advocate)))
    return "Choose which participant plays devil's advocate.";
  return null;
}

/** What the backend stores, or null for an open debate. */
export function toStance(choice: StanceChoice, participants: string[]): DebateStance | null {
  if (choice.mode === "sides") {
    return {
      mode: "sides",
      sides: Object.fromEntries(
        participants.map((m) => [m, choice.sides[choice.assignment[m] ?? 0].trim().replace(/\s+/g, " ")]),
      ),
    };
  }
  if (choice.mode === "advocate") return { mode: "advocate", advocate: choice.advocate };
  return null;
}
