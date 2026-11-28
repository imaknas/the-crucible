import { effortGaps, effortLabel } from "./effort";
import { contextFields } from "./runContext";

describe("reasoning effort", () => {
  it("labels a reply by what was asked, and the level sent for the highest", () => {
    expect(effortLabel({ choice: "high", level: "high" })).toBe("high effort");
    expect(effortLabel({ choice: "max", level: "xhigh" })).toBe("highest effort (xhigh)");
    expect(effortLabel(null)).toBeNull();
  });

  it("travels as a top-level frame field only when chosen", () => {
    expect(contextFields({ reasoningEffort: "max" })).toEqual({ reasoning_effort: "max" });
    expect(contextFields({ reasoningEffort: null })).toEqual({});
  });

  it("names the models that won't get the choice, and why", () => {
    const models = [
      { id: "a", name: "A", reasoning_efforts: ["low", "high", "max"] },
      { id: "b", name: "B", reasoning_efforts: [] },
      { id: "c", name: "C", reasoning_efforts: null },
    ];
    expect(effortGaps("high", models)).toEqual({ unverified: ["C"], lacking: ["B"] });
    expect(effortGaps("medium", models)).toEqual({ unverified: ["C"], lacking: ["A", "B"] });
    expect(effortGaps("", models)).toEqual({ unverified: [], lacking: [] });
  });
});
