import { FALLBACK_LIMITS, catalogColor, familyEnvKey, resolveLimits } from "./catalog";
import type { ModelFamily } from "./api";

const families: ModelFamily[] = [
  { key: "anthropic", label: "Anthropic", color: "#d97706", env_key: "ANTHROPIC_API_KEY", available: true, models: [{ id: "claude-x", name: "Claude X", desc: "" }] },
];

describe("resolveLimits", () => {
  it("takes the backend's limits and keeps fallbacks for the rest", () => {
    expect(resolveLimits({ max_debate_rounds: 6 })).toEqual({ ...FALLBACK_LIMITS, max_debate_rounds: 6 });
    expect(resolveLimits(null)).toEqual(FALLBACK_LIMITS);
    expect(resolveLimits({ max_prompt_chars: -1 })).toEqual(FALLBACK_LIMITS);
  });
});

describe("catalogColor", () => {
  it("prefers the catalogue's family colour", () => {
    expect(catalogColor("claude-x", families)).toBe("#d97706");
  });
  it("guesses before the catalogue knows the model", () => {
    expect(catalogColor("gpt-7", [])).toBe("#10b981");
  });
});

describe("familyEnvKey", () => {
  it("uses the backend's env_key", () => {
    expect(familyEnvKey({ key: "google", env_key: "GEMINI_KEY" })).toBe("GEMINI_KEY");
    expect(familyEnvKey({ key: "openai" })).toBe("OPENAI_API_KEY");
  });
});
