import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import AppHeader from "./AppHeader";

jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

const connection = { tone: "ok" as const, label: "2 keys · connected" };

describe("AppHeader", () => {
  const props = () => ({
    connection,
    selectedModels: ["gpt-6.1-sol", "claude-sonnet-5-5"],
    showTree: false,
    onShowTreeChange: jest.fn(),
    onHome: jest.fn(),
    modelLabel: jest.fn((id: string) => id.toUpperCase()),
    modelColor: jest.fn(() => "#10b981"),
  });

  it("doesn't redraw when the page re-renders with the same props", () => {
    const p = props();
    const { rerender } = render(<AppHeader {...p} />);
    const colorCalls = p.modelColor.mock.calls.length;
    expect(colorCalls).toBeGreaterThan(0);
    rerender(<AppHeader {...p} />);
    expect(p.modelColor.mock.calls.length).toBe(colorCalls);
    rerender(<AppHeader {...p} showTree />);
    expect(p.modelColor.mock.calls.length).toBeGreaterThan(colorCalls);
  });

  it("says who answers and switches the view", () => {
    const p = props();
    render(<AppHeader {...p} />);
    expect(screen.getByText("2 models")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Tree/ }));
    expect(p.onShowTreeChange).toHaveBeenCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "The Crucible: home" }));
    expect(p.onHome).toHaveBeenCalled();
  });
});
