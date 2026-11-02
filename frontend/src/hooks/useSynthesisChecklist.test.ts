import { act, renderHook } from "@testing-library/react";
import { useSynthesisChecklist } from "./useSynthesisChecklist";

describe("useSynthesisChecklist", () => {
  it("runs every mode but checklist straight away", () => {
    const synthesize = jest.fn();
    const { result } = renderHook(() => useSynthesisChecklist(synthesize));
    act(() => result.current.request(["a", "b"], "m", { mode: "compare" }));
    expect(synthesize).toHaveBeenCalledWith(["a", "b"], "m", { mode: "compare" });
    expect(result.current.checklist).toBeNull();
  });

  it("asks which parts to keep first, then merges just those", () => {
    const synthesize = jest.fn();
    const { result } = renderHook(() => useSynthesisChecklist(synthesize));
    act(() => result.current.request(["a", "b"], null, { mode: "checklist" }));
    expect(synthesize).not.toHaveBeenCalled();
    expect(result.current.checklist).toEqual({ ids: ["a", "b"], model: null });
    act(() => result.current.merge(["Keep me"]));
    expect(synthesize).toHaveBeenCalledWith(["a", "b"], null, { mode: "checklist", keep: ["Keep me"] });
    expect(result.current.checklist).toBeNull();
  });
});
