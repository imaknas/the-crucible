import { initialStance, stanceProblem, toStance } from "./stances";

const P = ["gpt", "claude", "gemini"];

describe("debate stances", () => {
  it("starts open, with sides given in turn and the last participant as advocate", () => {
    const c = initialStance(P);
    expect(c.mode).toBe("open");
    expect(c.assignment).toEqual({ gpt: 0, claude: 1, gemini: 0 });
    expect(c.advocate).toBe("gemini");
    expect(toStance(c, P)).toBeNull();
  });

  it("builds assigned sides and says what's wrong with them", () => {
    const c = { ...initialStance(P), mode: "sides" as const, sides: ["Remote  work", "Office"] };
    expect(stanceProblem(c, P)).toBeNull();
    expect(toStance(c, P)).toEqual({
      mode: "sides",
      sides: { gpt: "Remote work", claude: "Office", gemini: "Remote work" },
    });
    expect(stanceProblem({ ...c, sides: ["", "Office"] }, P)).toBe("Every side needs a name.");
    expect(stanceProblem({ ...c, assignment: { gpt: 0, claude: 0, gemini: 0 } }, P)).toMatch(/two different sides/);
  });

  it("builds a devil's advocate from the participants only", () => {
    const c = { ...initialStance(P), mode: "advocate" as const, advocate: "claude" };
    expect(toStance(c, P)).toEqual({ mode: "advocate", advocate: "claude" });
    expect(stanceProblem({ ...c, advocate: "nobody" }, P)).toMatch(/devil's advocate/);
  });
});
