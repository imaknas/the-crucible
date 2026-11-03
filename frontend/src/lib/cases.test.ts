import {
  baselineNote,
  defaultReplayModels,
  replayChoices,
  replayDiffSides,
  settingsSummary,
  voteSummary,
  type ReplayResult,
} from "./cases";
import { FAMILIES } from "@/test/families";

const label = (id: string) => ({ "gpt-a": "GPT A", "claude-b": "Claude B" })[id] ?? id;

const result = (over: Partial<ReplayResult> = {}): ReplayResult => ({
  model: "claude-b",
  model_name: "Claude B",
  content: "New answer.",
  checkpoint_id: "n1",
  error: null,
  metrics: null,
  baseline: { model: "claude-b", model_name: "Claude B", reason: "same_model" },
  diff: { summary_text: "1 sentence changed", identical: false },
  ...over,
});

describe("replayChoices", () => {
  it("offers models whose family has a key, legacy ones only when the case has them", () => {
    expect(replayChoices(FAMILIES, [])).toEqual(["gpt-a", "claude-b"]);
    expect(replayChoices(FAMILIES, ["gpt-old"])).toEqual(["gpt-a", "gpt-old", "claude-b"]);
    // No key: never offered, even if the case has it.
    expect(replayChoices(FAMILIES, ["gemini-c"])).not.toContain("gemini-c");
  });

  it("starts from the case's own models that can still run", () => {
    expect(defaultReplayModels(["gemini-c", "claude-b"], ["gpt-a", "claude-b"])).toEqual(["claude-b"]);
  });
});

describe("what a case says", () => {
  it("names its settings and the summarizer by display name", () => {
    expect(
      settingsSummary(
        { use_web_search: true, use_rag: true, system_prompt: "Be brief", summarizer: "gpt-a", is_deliberation: true },
        label,
      ),
    ).toEqual(["web search", "document search", "Deliberation", "a system prompt", "summarized by GPT A"]);
    expect(
      settingsSummary(
        { use_web_search: false, use_rag: false, system_prompt: null, summarizer: null, is_deliberation: false },
        label,
      ),
    ).toEqual([]);
  });

  it("says the vote in words", () => {
    const vote = { winner_checkpoint_id: "x", reason: null, task_type: "general", blind: false };
    expect(voteSummary({ vote: null, best_model: null }, label)).toBeNull();
    expect(voteSummary({ vote: { ...vote, outcome: "best" }, best_model: "claude-b" }, label)).toBe(
      "Claude B was best",
    );
    expect(voteSummary({ vote: { ...vote, outcome: "tie", reason: "both fine" }, best_model: null }, label)).toBe(
      "A tie: both fine",
    );
    expect(voteSummary({ vote: { ...vote, outcome: "all_bad" }, best_model: null }, label)).toBe("All bad");
  });

  it("says what a new answer is compared with", () => {
    expect(baselineNote(result())).toBe("Against its own answer in the case: 1 sentence changed");
    expect(
      baselineNote(
        result({ model: "gemini-c", baseline: { model: "claude-b", model_name: "Claude B", reason: "voted_best" } }),
      ),
    ).toBe("Against Claude B's answer, which you voted best: 1 sentence changed");
    expect(baselineNote(result({ baseline: null, diff: null }))).toMatch(/^Nothing to compare with/);
    expect(baselineNote(result({ error: "rate limited", diff: null }))).toBe("Failed: rate limited");
  });
});

describe("replayDiffSides", () => {
  const c = {
    answers: [
      { model: "claude-b", model_name: "Claude B", content: "Old answer.", metrics: null, checkpoint_id: "o1" },
    ],
  };

  it("puts the case's answer on A and the new one on B, by display name", () => {
    expect(replayDiffSides(c, result())).toEqual({
      a: { label: "Claude B (case)", model: "claude-b", text: "Old answer." },
      b: { label: "Claude B (replay)", model: "claude-b", text: "New answer." },
    });
  });

  it("has nothing to show without a baseline or after a failure", () => {
    expect(replayDiffSides(c, result({ baseline: null }))).toBeNull();
    expect(replayDiffSides(c, result({ error: "down" }))).toBeNull();
  });
});
