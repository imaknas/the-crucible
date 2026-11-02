import { synthesisFrameFields, synthesisLabel } from "./synthesis";

describe("synthesis modes", () => {
  it("sends only what each mode needs", () => {
    expect(synthesisFrameFields()).toEqual({ synthesis_mode: "merge" });
    expect(synthesisFrameFields({ mode: "compare" })).toEqual({ synthesis_mode: "compare" });
    expect(synthesisFrameFields({ mode: "checklist", keep: ["a"] })).toEqual({ synthesis_mode: "checklist", keep_components: ["a"] });
    expect(synthesisFrameFields({ mode: "ask", question: "Why?" })).toEqual({ synthesis_mode: "ask", synthesis_question: "Why?" });
  });

  it("names each kind of reply; replies from before modes are syntheses", () => {
    expect(synthesisLabel("compare")).toBe("Comparison");
    expect(synthesisLabel("checklist")).toBe("Synthesis of kept parts");
    expect(synthesisLabel("ask")).toBe("Answer about the selection");
    expect(synthesisLabel(undefined)).toBe("Synthesis");
  });
});
