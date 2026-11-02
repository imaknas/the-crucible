import { act, renderHook } from "@testing-library/react";
import { useTreeView } from "./useTreeView";

const edges = [
  { id: "e1", source: "q", target: "a" },
  { id: "e2", source: "a", target: "q2" },
];

beforeEach(() => localStorage.clear());

describe("useTreeView", () => {
  it("keeps collapsed nodes per thread, across remounts", () => {
    const { result, rerender, unmount } = renderHook(({ t }) => useTreeView(t), { initialProps: { t: "t1" } });
    act(() => result.current.toggleCollapse("a"));
    expect([...result.current.collapsed]).toEqual(["a"]);
    rerender({ t: "t2" });
    expect(result.current.collapsed.size).toBe(0);
    unmount();
    const again = renderHook(() => useTreeView("t1"));
    expect([...again.result.current.collapsed]).toEqual(["a"]);
  });

  it("forgets the hoisted branch on another thread, and a revealed node opens what hides it", () => {
    const { result, rerender } = renderHook(({ t }) => useTreeView(t), { initialProps: { t: "t1" } });
    act(() => {
      result.current.setCollapsed("a", true);
      result.current.hoistNode("q2");
    });
    expect(result.current.hoisted).toBe("q2");
    act(() => result.current.revealNode(edges, "q2"));
    expect(result.current.collapsed.has("a")).toBe(false);
    expect(result.current.hoisted).toBe("q2");
    act(() => result.current.revealNode(edges, "a"));
    expect(result.current.hoisted).toBeNull();
    act(() => result.current.hoistNode("a"));
    rerender({ t: "t2" });
    expect(result.current.hoisted).toBeNull();
  });
});
