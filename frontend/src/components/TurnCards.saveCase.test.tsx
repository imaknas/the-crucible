import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import TurnCards from "./TurnCards";
import type { TurnCard } from "@/lib/turns";

jest.mock("react-markdown", () => {
  const MockMarkdown = ({ children }: { children: React.ReactNode }) => <div>{children}</div>;
  MockMarkdown.displayName = "MockMarkdown";
  return MockMarkdown;
});
jest.mock("remark-gfm", () => ({}));
jest.mock("remark-math", () => ({}));
jest.mock("rehype-katex", () => ({}));
jest.mock("react-syntax-highlighter", () => ({
  Prism: ({ children }: { children: React.ReactNode }) => <pre>{children}</pre>,
}));
jest.mock("react-syntax-highlighter/dist/esm/styles/prism", () => ({ vscDarkPlus: {}, vs: {} }));
jest.mock("lucide-react", () => {
  const Icon = () => <svg />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

const card = (model: string, over: Partial<TurnCard> = {}): TurnCard => ({
  key: model,
  model,
  id: `n_${model}`,
  label: model.toUpperCase(),
  color: null,
  text: `${model} says`,
  full: true,
  streaming: false,
  stopped: false,
  error: null,
  shown: false,
  metrics: null,
  ...over,
});

const props = {
  isDark: false,
  modelLabel: (id: string) => id.toUpperCase(),
  onViewReply: jest.fn(),
  onContinueReply: jest.fn(),
};

describe("TurnCards: Save as a case", () => {
  it("is offered once every answer is in", () => {
    const onSave = jest.fn();
    const { rerender } = render(
      <TurnCards
        {...props}
        cards={[card("a", { streaming: true }), card("b")]}
        saveCase={{ disabled: false, saving: false, onSave }}
      />,
    );
    expect(screen.queryByRole("button", { name: "Save as a case" })).not.toBeInTheDocument();
    rerender(
      <TurnCards {...props} cards={[card("a"), card("b")]} saveCase={{ disabled: false, saving: false, onSave }} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save as a case" }));
    expect(onSave).toHaveBeenCalled();
  });

  it("is held while it saves, and absent without the prop", () => {
    const { rerender } = render(
      <TurnCards
        {...props}
        cards={[card("a"), card("b")]}
        saveCase={{ disabled: false, saving: true, onSave: jest.fn() }}
      />,
    );
    expect(screen.getByRole("button", { name: "Save as a case" })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Save as a case" })).toBeDisabled();
    rerender(<TurnCards {...props} cards={[card("a"), card("b")]} />);
    expect(screen.queryByRole("button", { name: "Save as a case" })).not.toBeInTheDocument();
  });
});
