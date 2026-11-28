import { angleField, anglesDiffer, anglesFor } from "./angles";

describe("angles", () => {
  it("sends a model its angle only when it has one", () => {
    expect(angleField({ a: " security " }, "a")).toEqual({ angle: "security" });
    expect(angleField({ a: "   " }, "a")).toEqual({});
    expect(angleField({}, "b")).toEqual({});
  });

  it("keeps only the angles of models that answer, and drops blank ones", () => {
    expect(anglesFor({ a: "cost", b: " ", c: "risk" }, ["a", "b"])).toEqual({ a: "cost" });
  });

  it("tells answers asked from different angles apart from a like-for-like turn", () => {
    expect(anglesDiffer([{ angle: "cost" }, { angle: null }])).toBe(true);
    expect(anglesDiffer([{ angle: "cost" }, { angle: "risk" }])).toBe(true);
    expect(anglesDiffer([{ angle: "cost" }, { angle: "cost" }])).toBe(false);
    expect(anglesDiffer([{}, { angle: null }])).toBe(false);
  });
});
