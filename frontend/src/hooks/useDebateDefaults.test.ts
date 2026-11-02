import { renderHook, act } from "@testing-library/react";
import { useDebateDefaults } from "./useDebateDefaults";

beforeEach(() => localStorage.clear());

describe("useDebateDefaults", () => {
  it("starts from the backend's recommended round count", () => {
    const { result } = renderHook(() => useDebateDefaults(10, 2));
    expect(result.current.debateDefaults.max_rounds).toBe(2);
  });

  it("keeps the person's saved count over the recommendation", () => {
    const { result, rerender } = renderHook(({ rec }) => useDebateDefaults(10, rec), { initialProps: { rec: 2 } });
    act(() => result.current.setDebateDefaults((prev) => ({ ...prev, max_rounds: 5 })));
    rerender({ rec: 1 });
    expect(result.current.debateDefaults.max_rounds).toBe(5);
  });

  it("never seeds above the limit", () => {
    const { result } = renderHook(() => useDebateDefaults(1, 2));
    expect(result.current.debateDefaults.max_rounds).toBe(1);
  });
});
