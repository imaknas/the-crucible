import { charsLeft, debateAction, deliberateAction, sendAction, type ComposerState } from "./composer";

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

describe("the prompt limit", () => {
  const full = { isLoading: false, modelCount: 2, hasHistory: true, hasText: true };
  it("disables sending and debating a message over the limit, saying why", () => {
    expect(sendAction({ ...full, overLimit: 1000 })).toEqual({
      enabled: false,
      hint: "Your message is over the 1,000-character limit; shorten it first",
    });
    expect(debateAction({ ...full, overLimit: 1000 }).enabled).toBe(false);
  });
  it("counts down only near the limit", () => {
    expect(charsLeft(100, 1000)).toBeNull();
    expect(charsLeft(950, 1000)).toBe(50);
    expect(charsLeft(1010, 1000)).toBe(-10);
  });
});
