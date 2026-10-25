import { act, renderHook } from "@testing-library/react";
import { useSystemPrompt } from "./useSystemPrompt";

describe("useSystemPrompt", () => {
  beforeEach(() => localStorage.clear());

  it("is empty by default, so requests carry none", () => {
    const { result } = renderHook(() => useSystemPrompt());
    expect(result.current.text).toBe("");
    expect(result.current.systemPrompt).toBeNull();
  });

  it("persists what is typed and treats blank text as none", () => {
    const { result } = renderHook(() => useSystemPrompt());
    act(() => result.current.setText("Answer in French."));
    expect(result.current.systemPrompt).toBe("Answer in French.");
    expect(renderHook(() => useSystemPrompt()).result.current.text).toBe("Answer in French.");

    act(() => result.current.setText("  "));
    expect(result.current.text).toBe("  ");
    expect(result.current.systemPrompt).toBeNull();

    act(() => result.current.setText(""));
    expect(localStorage.getItem("crucible_system_prompt")).toBeNull();
  });
});
