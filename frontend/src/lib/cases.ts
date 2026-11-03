import type { ModelFamily } from "@/lib/api";
import type { ReplyMetrics, TurnMetrics } from "@/lib/metrics";
import type { DiffSide } from "@/lib/diff";

/**
 * Saved cases (backend services/cases.py): one turn copied whole, replayed on
 * other models and compared old against new. The shapes GET /cases and
 * GET /cases/{id} return, and the pure helpers the Saved cases dialog uses.
 */

export interface CaseSummary {
  case_id: string;
  title: string;
  question: string;
  created_at: string;
  source_thread_id: string | null;
  models: string[];
  model_names: string[];
  voted: boolean;
  replay_count: number;
  last_replayed_at: string | null;
}

export interface CaseAnswer {
  model: string;
  model_name: string;
  content: string;
  metrics: ReplyMetrics | null;
  checkpoint_id: string;
}

export interface CaseSettings {
  use_web_search: boolean;
  use_rag: boolean;
  system_prompt: string | null;
  summarizer: string | null;
  is_deliberation: boolean;
}

export interface CaseVote {
  outcome: "best" | "tie" | "all_bad";
  winner_checkpoint_id: string | null;
  reason: string | null;
  task_type: string;
  blind: boolean;
}

export interface ReplayResult {
  model: string;
  model_name: string;
  content: string | null;
  checkpoint_id: string | null;
  error: string | null;
  metrics: ReplyMetrics | null;
  /** The case's answer this one is compared with; null when there is none. */
  baseline: { model: string; model_name: string; reason: "same_model" | "voted_best" } | null;
  diff: { summary_text: string; identical: boolean } | null;
}

export interface CaseReplay {
  replay_id: string;
  case_id: string;
  thread_id: string;
  created_at: string;
  models: string[];
  total: TurnMetrics | null;
  results: ReplayResult[];
}

export interface SavedCase {
  case_id: string;
  title: string;
  question: string;
  created_at: string;
  source_thread_id: string | null;
  source_turn_id: string | null;
  history: {
    role: "user" | "assistant" | "system";
    kind: "summary" | null;
    content: string;
    model: string | null;
    model_name: string | null;
  }[];
  history_from: string | null;
  summarized: boolean;
  documents: { name: string; characters: number }[];
  searched_documents: { name: string; characters: number }[];
  settings: CaseSettings;
  answers: CaseAnswer[];
  total: TurnMetrics | null;
  vote: CaseVote | null;
  best_model: string | null;
  replays: CaseReplay[];
}

/** A stored time (ISO, with its zone) in the reader's own time: "Nov 3, 2026, 14:05". */
export function caseTime(iso: string | null | undefined): string {
  if (!iso) return "";
  // A time without a zone is SQLite's CURRENT_TIMESTAMP: UTC.
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso.replace(" ", "T")}Z`);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * The models a case can be replayed on: every model whose family has a key,
 * legacy ones only if the case itself has their answer (they are kept for old
 * threads, not offered for new runs).
 */
export function replayChoices(families: ModelFamily[], caseModels: string[]): string[] {
  return families
    .filter((f) => f.available)
    .flatMap((f) => f.models)
    .filter((m) => m.desc !== "Legacy" || caseModels.includes(m.id))
    .map((m) => m.id);
}

/** What a replay starts with: the case's own models that can still run. */
export function defaultReplayModels(caseModels: string[], choices: string[]): string[] {
  return caseModels.filter((m) => choices.includes(m));
}

/** The settings that shaped the case's answers, in words. */
export function settingsSummary(settings: CaseSettings, modelLabel: (id: string) => string): string[] {
  const out: string[] = [];
  if (settings.use_web_search) out.push("web search");
  if (settings.use_rag) out.push("document search");
  if (settings.is_deliberation) out.push("Deliberation");
  if (settings.system_prompt) out.push("a system prompt");
  if (settings.summarizer) out.push(`summarized by ${modelLabel(settings.summarizer)}`);
  return out;
}

/** The person's vote, in words; null when they didn't vote. */
export function voteSummary(
  c: Pick<SavedCase, "vote" | "best_model">,
  modelLabel: (id: string) => string,
): string | null {
  if (!c.vote) return null;
  const said =
    c.vote.outcome === "best"
      ? `${c.best_model ? modelLabel(c.best_model) : "One answer"} was best`
      : c.vote.outcome === "tie"
        ? "A tie"
        : "All bad";
  return c.vote.reason ? `${said}: ${c.vote.reason}` : said;
}

/** What a new answer is compared with, in words. */
export function baselineNote(result: ReplayResult): string {
  if (result.error) return `Failed: ${result.error}`;
  if (!result.baseline)
    return "Nothing to compare with: the case has no answer from this model and none was voted best.";
  const against =
    result.baseline.reason === "same_model"
      ? "its own answer in the case"
      : `${result.baseline.model_name}'s answer, which you voted best`;
  return `Against ${against}: ${result.diff?.summary_text ?? ""}`.trim();
}

/** The two sides of a replayed answer's diff (case answer, new answer); null without a baseline. */
export function replayDiffSides(
  c: Pick<SavedCase, "answers">,
  result: ReplayResult,
): { a: DiffSide; b: DiffSide } | null {
  if (!result.baseline || result.error) return null;
  const old = c.answers.find((a) => a.model === result.baseline!.model);
  if (!old) return null;
  return {
    a: { label: `${result.baseline.model_name} (case)`, model: old.model, text: old.content },
    b: { label: `${result.model_name} (replay)`, model: result.model, text: result.content ?? "" },
  };
}
