import { answeringModels, defaultSynthesizer } from "./referee";
import type { TreeNode } from "./types";

const GPT = "gpt-6.2-sol";
const CLAUDE = "claude-sonnet-5-5";
const GEMINI = "gemini-4-neon";
const GROK = "grok-4.7";
const REFEREES = [GPT, CLAUDE, GEMINI, GROK];

const families = (withoutKey: string[] = []) =>
  [
    ["openai", GPT],
    ["anthropic", CLAUDE],
    ["google", GEMINI],
    ["xai", GROK],
  ].map(([key, id]) => ({ key, available: !withoutKey.includes(key), models: [{ id, name: id }] }));

describe("the default synthesizer", () => {
  // The same cases are in backend/tests/test_referee.py.
  it("comes from a provider that wrote none of the answers", () => {
    expect(defaultSynthesizer([GPT, CLAUDE], families(), REFEREES)).toBe(GEMINI);
    expect(defaultSynthesizer([GPT, CLAUDE, GEMINI], families(), REFEREES)).toBe(GROK);
  });

  it("needs that provider's key", () => {
    expect(defaultSynthesizer([GPT, CLAUDE], families(["google"]), REFEREES)).toBe(GROK);
  });

  it("is the first answering model when there is no outsider", () => {
    expect(defaultSynthesizer([GPT, CLAUDE, GEMINI], families(["xai"]), REFEREES)).toBe(GPT);
    expect(defaultSynthesizer([], families(), [])).toBeNull();
  });
});

it("reads who wrote each answer from the tree", () => {
  const nodes = [
    { id: "a", metadata: { active_peer: GPT } },
    { id: "b", metadata: { active_peer: CLAUDE } },
  ] as unknown as TreeNode[];
  expect(answeringModels(["b", "a", "missing"], nodes)).toEqual([CLAUDE, GPT]);
});
