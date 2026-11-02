import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import TurnCards from "./TurnCards";
import { ReplyTurnActions, answererNames } from "./TurnActions";
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

const LABELS: Record<string, string> = { a: "Model A", b: "Model B", c: "Model C", d: "Model D" };
const modelLabel = (id: string) => LABELS[id] ?? id;

const card = (model: string, over: Partial<TurnCard> = {}): TurnCard => ({
  key: model,
  model,
  id: `n_${model}`,
  label: LABELS[model],
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

const base = {
  isDark: false,
  modelLabel,
  onViewReply: jest.fn(),
  onContinueReply: jest.fn(),
};

const cardOf = (label: string) => screen.getByRole("article", { name: `${label}'s answer` });

describe("adding a model to a turn", () => {
  it("lists the models not in the turn by display name, and adds the one picked", () => {
    const onAdd = jest.fn();
    render(
      <TurnCards {...base} cards={[card("a"), card("b")]} addModel={{ options: ["c", "d"], disabled: false, onAdd }} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add a model" }));
    const menu = screen.getByRole("menu", { name: "Model to add to this turn" });
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((i) => i.textContent),
    ).toEqual(["Model C", "Model D"]);
    expect(within(menu).getByRole("menuitem", { name: "Model C" })).toHaveAttribute("title", "c");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Model D" }));
    expect(onAdd).toHaveBeenCalledWith("d");
  });

  it("says why it can't while a turn runs, and opens nothing", () => {
    render(
      <TurnCards
        {...base}
        cards={[card("a"), card("b", { streaming: true, id: null })]}
        addModel={{ options: ["c"], disabled: false, onAdd: jest.fn() }}
      />,
    );
    const add = screen.getByRole("button", { name: "Add a model" });
    expect(add).toHaveAttribute("aria-disabled", "true");
    expect(add).toHaveAttribute("title", expect.stringMatching(/once the models have finished/));
    fireEvent.click(add);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("is not offered when every model with a key already answered", () => {
    render(
      <TurnCards
        {...base}
        cards={[card("a"), card("b")]}
        addModel={{ options: [], disabled: false, onAdd: jest.fn() }}
      />,
    );
    expect(screen.queryByRole("button", { name: "Add a model" })).toBeNull();
  });
});

describe("the reply the next message continues", () => {
  it("marks the branch point's card, and says who will answer", () => {
    render(
      <TurnCards
        {...base}
        cards={[card("a", { shown: true }), card("b")]}
        primaryId="n_b"
        answerers="Model A and Model B"
      />,
    );
    const mark = within(cardOf("Model B")).getByTestId("next-here");
    expect(mark).toHaveTextContent("Next message continues here");
    expect(mark).toHaveAttribute("title", expect.stringContaining("Model A and Model B will answer it"));
    // The card on screen says only that.
    expect(within(cardOf("Model A")).queryByTestId("next-here")).toBeNull();
    expect(within(cardOf("Model A")).getByText("On screen")).toHaveAttribute(
      "title",
      "This answer's conversation is the one on screen",
    );
  });

  it("marks nothing while the next message continues the latest turn", () => {
    render(<TurnCards {...base} cards={[card("a", { shown: true }), card("b")]} primaryId={null} />);
    expect(screen.queryByTestId("next-here")).toBeNull();
  });

  it("offers Everyone continues from here when it adds models, beside Continue from this", () => {
    const onContinueAll = jest.fn();
    const onContinueReply = jest.fn();
    render(
      <TurnCards
        {...base}
        onContinueReply={onContinueReply}
        cards={[card("a"), card("b")]}
        onContinueAll={onContinueAll}
        selectedModels={["a"]}
      />,
    );
    // Only "a" is selected: on a's card everyone is a alone, so it isn't offered.
    expect(within(cardOf("Model A")).queryByRole("button", { name: "Everyone continues from here" })).toBeNull();
    fireEvent.click(within(cardOf("Model B")).getByRole("button", { name: "Everyone continues from here" }));
    expect(onContinueAll).toHaveBeenCalledWith("n_b");
    fireEvent.click(within(cardOf("Model B")).getByRole("button", { name: "Continue with Model B" }));
    expect(onContinueReply).toHaveBeenCalledWith("n_b");
  });
});

describe("under a single-model reply", () => {
  it("shows the mark, Everyone continues from here and Add a model", () => {
    const onContinueAll = jest.fn();
    const onAdd = jest.fn();
    render(
      <ReplyTurnActions
        id="n_a"
        label="Model A"
        primary
        answerers="Model A"
        addModel={{ options: ["b"], disabled: false, onAdd }}
        onContinueAll={onContinueAll}
        modelLabel={modelLabel}
      />,
    );
    expect(screen.getByTestId("next-here")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Everyone continues from here" }));
    expect(onContinueAll).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Add a model" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Model B" }));
    expect(onAdd).toHaveBeenCalledWith("b");
  });

  it("renders nothing when it has nothing to offer", () => {
    const { container } = render(
      <ReplyTurnActions
        id="n_a"
        label="Model A"
        primary={false}
        answerers=""
        addModel={null}
        modelLabel={modelLabel}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

it("names who answers in words", () => {
  expect(answererNames(["a"], modelLabel)).toBe("Model A");
  expect(answererNames(["a", "b", "c"], modelLabel)).toBe("Model A, Model B and Model C");
  expect(answererNames([], modelLabel)).toBe("");
});
