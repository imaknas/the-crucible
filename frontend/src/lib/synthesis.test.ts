import { SYNTHESIS_MARKER, buildSynthesisPrompt, lastReply } from "./synthesis";

describe("chat synthesis", () => {
  it("attributes each answer and keeps the marker the backend recognises", () => {
    const prompt = buildSynthesisPrompt([
      { author: "GPT-6.1 Sol", content: "Use Rust." },
      { author: "Claude Sonnet 5.5", content: "Use Go." },
    ]);
    expect(prompt).toContain("[GPT-6.1 Sol]:\nUse Rust.");
    expect(prompt).toContain("[Claude Sonnet 5.5]:\nUse Go.");
    expect(prompt).toContain(SYNTHESIS_MARKER);
    expect(prompt.startsWith("I have received perspectives from multiple models:")).toBe(true);
  });

  it("takes a branch's last reply with its author's display name", () => {
    const label = (id: string) => (id === "gpt-6.1-sol" ? "GPT-6.1 Sol" : id);
    expect(
      lastReply(
        [
          { role: "user", content: "Q" },
          { role: "assistant", content: "first", model: "gpt-6.1-sol" },
          { role: "user", content: "Q2" },
          { role: "assistant", content: "second", model: "gpt-6.1-sol" },
        ],
        label,
      ),
    ).toEqual({ author: "GPT-6.1 Sol", content: "second" });
    expect(lastReply([{ role: "user", content: "Q" }], label)).toBeNull();
  });
});
