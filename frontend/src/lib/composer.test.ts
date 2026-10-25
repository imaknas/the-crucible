import { debateAction, deliberateAction, sendAction, type ComposerState } from "./composer";

const base: ComposerState = { isLoading: false, modelCount: 1, hasHistory: true, hasText: false };

describe("deliberateAction", () => {
  it("works with an empty box: the typed text is optional", () => {
    expect(deliberateAction(base).enabled).toBe(true);
  });
  it("explains why it is unavailable", () => {
    expect(deliberateAction({ ...base, modelCount: 2 }).hint).toMatch(/exactly 1 model/);
    expect(deliberateAction({ ...base, hasHistory: false }).hint).toMatch(/send a message first/);
    expect(deliberateAction({ ...base, isLoading: true }).enabled).toBe(false);
  });
});

describe("debateAction", () => {
  it("needs two models and a question", () => {
    expect(debateAction({ ...base, hasText: true }).hint).toMatch(/2 or more models/);
    expect(debateAction({ ...base, modelCount: 2 }).hint).toMatch(/Type the question/);
    expect(debateAction({ ...base, modelCount: 2, hasText: true }).enabled).toBe(true);
  });
});

describe("sendAction", () => {
  it("needs text and a model", () => {
    expect(sendAction(base).enabled).toBe(false);
    expect(sendAction({ ...base, modelCount: 0, hasText: true }).hint).toMatch(/Select a model/);
    expect(sendAction({ ...base, modelCount: 3, hasText: true })).toEqual({
      enabled: true,
      hint: "Send to all 3 selected models",
    });
  });
});
