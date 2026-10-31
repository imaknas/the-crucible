import { act, renderHook } from "@testing-library/react";
import { useLayoutPanels } from "./useLayoutPanels";

/** A viewport below the md breakpoint, or not: every max-width query matches when narrow. */
function setViewport(narrow: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: narrow && query.includes("max-width"),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

const original = window.matchMedia;

beforeEach(() => {
  localStorage.clear();
});

afterAll(() => {
  window.matchMedia = original;
});

describe("useLayoutPanels", () => {
  it("docks both panels on a wide screen, each collapsing to a rail it remembers", () => {
    setViewport(false);
    const { result } = renderHook(() => useLayoutPanels());
    expect(result.current.compact).toBe(false);
    expect(result.current.sidebar).toMatchObject({ mode: "docked", collapsed: false, open: false });
    expect(result.current.panel).toMatchObject({ mode: "docked", collapsed: false, open: false });

    act(() => result.current.sidebar.setCollapsed(true));
    expect(result.current.sidebar.collapsed).toBe(true);
    expect(result.current.panel.collapsed).toBe(false);
    expect(localStorage.getItem("crucible_sidebar_collapsed")).toBe("1");

    act(() => result.current.panel.setCollapsed(true));
    act(() => result.current.sidebar.setCollapsed(false));
    expect(result.current.sidebar.collapsed).toBe(false);
    expect(result.current.panel.collapsed).toBe(true);
  });

  it("restores a collapse from an earlier visit", () => {
    setViewport(false);
    localStorage.setItem("crucible_panel_collapsed", "1");
    const { result } = renderHook(() => useLayoutPanels());
    expect(result.current.panel.collapsed).toBe(true);
    expect(result.current.sidebar.collapsed).toBe(false);
  });

  it("makes both panels closed overlay drawers on a narrow screen, never rails", () => {
    setViewport(true);
    localStorage.setItem("crucible_sidebar_collapsed", "1");
    localStorage.setItem("crucible_panel_collapsed", "1");
    const { result } = renderHook(() => useLayoutPanels());
    expect(result.current.compact).toBe(true);
    expect(result.current.sidebar).toMatchObject({ mode: "overlay", collapsed: false, open: false });
    expect(result.current.panel).toMatchObject({ mode: "overlay", collapsed: false, open: false });

    act(() => result.current.sidebar.setOpen(true));
    expect(result.current.sidebar.open).toBe(true);
    expect(result.current.panel.open).toBe(false);
  });
});
