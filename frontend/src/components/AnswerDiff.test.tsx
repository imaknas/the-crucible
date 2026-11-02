import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import AnswerDiffDialog, { DiffView } from "./AnswerDiff";
import TurnCards from "./TurnCards";
import { useAnswerDiff } from "@/hooks/useAnswerDiff";
import type { TurnCard } from "@/lib/turns";
import { fetchHistory } from "@/lib/api";

jest.mock("react-markdown", () => {
  const MockMarkdown = ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  );
  MockMarkdown.displayName = "MockMarkdown";
  return MockMarkdown;
});
jest.mock("remark-gfm", () => ({}));
jest.mock("remark-math", () => ({}));
jest.mock("rehype-katex", () => ({}));
jest.mock("react-syntax-highlighter", () => ({
  Prism: ({ children }: { children: React.ReactNode }) => <pre>{children}</pre>,
}));
jest.mock("react-syntax-highlighter/dist/esm/styles/prism", () => ({
  vscDarkPlus: {},
  vs: {},
}));
jest.mock("@/lib/api", () => ({ fetchHistory: jest.fn() }));

const A_TEXT =
  "Paris is the capital of France. It sits on the Seine. Its museums are famous.";
const B_TEXT =
  "Paris is the capital of France. It sits on the river Seine. Lyon is the second city.";

describe("DiffView", () => {
  const view = () =>
    render(
      <DiffView
        a={{ label: "GPT-6.1 Sol", model: "gpt-6.1-sol", text: A_TEXT }}
        b={{
          label: "Claude Sonnet 5.5",
          model: "claude-sonnet-5-5",
          text: B_TEXT,
        }}
      />,
    );

  it("says in one line what differs", () => {
    view();
    expect(screen.getByTestId("diff-summary")).toHaveTextContent(
      "1 sentence the same, 1 changed, 1 only in A, 1 only in B",
    );
  });

  it("marks removed and added words with more than colour", () => {
    const { container } = view();
    const removed = container.querySelector("del");
    const added = container.querySelector("ins");
    expect(removed).toBeNull(); // nothing was removed from the changed sentence…
    expect(added).toHaveTextContent("river");
    expect(added).toHaveStyle({ textDecorationLine: "underline" });
    // …and lines only one answer has carry a −/+ gutter and say so to screen readers.
    const onlyA = container.querySelector('[data-op="only_a"][data-side="a"]')!;
    expect(onlyA).toHaveTextContent("−Only in A: Its museums are famous.");
    const onlyB = container.querySelector('[data-op="only_b"][data-side="b"]')!;
    expect(onlyB).toHaveTextContent("+Only in B: Lyon is the second city.");
  });

  it("strikes through what A says that B doesn't", () => {
    const { container } = render(
      <DiffView
        a={{ label: "A model", text: "The sky is blue." }}
        b={{ label: "B model", text: "The sky is green." }}
      />,
    );
    const removed = container.querySelector("del")!;
    expect(removed).toHaveTextContent("blue");
    expect(removed).toHaveStyle({ textDecorationLine: "line-through" });
    expect(container.querySelector("ins")).toHaveTextContent("green");
  });

  it("names both answers by display name, ids only in a tooltip", () => {
    view();
    expect(screen.getByText("A · GPT-6.1 Sol")).toHaveAttribute(
      "title",
      "gpt-6.1-sol",
    );
    expect(screen.getByText("B · Claude Sonnet 5.5")).toHaveAttribute(
      "title",
      "claude-sonnet-5-5",
    );
  });

  it("can hide what both answers share", () => {
    view();
    const toggle = screen.getByRole("button", { name: "Hide unchanged" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByText("Paris is the capital of France."),
    ).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Paris is the capital of France.")).toBeNull();
    expect(screen.getByText("… 1 the same")).toBeInTheDocument();
  });
});

describe("AnswerDiffDialog", () => {
  it("names the two answers while they load", () => {
    render(
      <AnswerDiffDialog
        open
        a={null}
        b={null}
        labels={{ a: "One", b: "Two" }}
        onClose={() => {}}
      />,
    );
    expect(
      screen.getByRole("dialog", { name: "Compare answers: One and Two" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading both answers…",
    );
  });

  it("says why it couldn't load them", () => {
    render(
      <AnswerDiffDialog
        open
        a={null}
        b={null}
        labels={{ a: "One", b: "Two" }}
        error="Thread gone"
        onClose={() => {}}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Thread gone");
  });
});

const card = (
  model: string,
  label: string,
  over: Partial<TurnCard> = {},
): TurnCard => ({
  key: model,
  model,
  id: `n_${model}`,
  label,
  color: null,
  text: model === "gpt-6.1-sol" ? A_TEXT : B_TEXT,
  full: true,
  streaming: false,
  stopped: false,
  error: null,
  shown: false,
  metrics: null,
  ...over,
});

/** The page's wiring: cards → useAnswerDiff → the dialog. */
function Harness({ cards }: { cards: TurnCard[] }) {
  const diff = useAnswerDiff({
    threadId: "t1",
    replyTexts: {},
    modelLabel: (id) => id,
  });
  return (
    <>
      <TurnCards
        cards={cards}
        isDark={false}
        modelLabel={(id) => id}
        onViewReply={() => {}}
        onContinueReply={() => {}}
        onCompare={diff.compare}
      />
      <AnswerDiffDialog
        open={diff.open}
        a={diff.a}
        b={diff.b}
        labels={diff.labels}
        error={diff.error}
        onClose={diff.close}
      />
    </>
  );
}

describe("Compare with… on a compare card", () => {
  beforeEach(() => (fetchHistory as jest.Mock).mockReset());

  it("offers the turn's other answers by name and opens their diff", async () => {
    render(
      <Harness
        cards={[
          card("gpt-6.1-sol", "GPT-6.1 Sol"),
          card("claude-sonnet-5-5", "Claude Sonnet 5.5"),
        ]}
      />,
    );
    const gpt = screen.getByRole("article", { name: "GPT-6.1 Sol's answer" });
    const button = within(gpt).getByRole("button", { name: "Compare with…" });
    expect(button).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(button);

    const menu = screen.getByRole("menu", {
      name: "Compare GPT-6.1 Sol's answer with",
    });
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Claude Sonnet 5.5"]);
    fireEvent.click(items[0]);

    const dialog = await screen.findByRole("dialog", {
      name: "Compare answers: GPT-6.1 Sol and Claude Sonnet 5.5",
    });
    expect(within(dialog).getByTestId("diff-summary")).toHaveTextContent(
      "1 sentence the same, 1 changed, 1 only in A, 1 only in B",
    );
    expect(dialog).not.toHaveTextContent("claude-sonnet-5-5");
    // Full texts were on the cards: nothing was fetched.
    expect(fetchHistory).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("reads an answer shown as an excerpt from its node, without moving the path", async () => {
    (fetchHistory as jest.Mock).mockResolvedValue({
      nodes: [],
      edges: [],
      messages: [
        { id: "q", role: "user", content: "Where is Paris?" },
        { id: "r", role: "assistant", content: B_TEXT },
      ],
    });
    render(
      <Harness
        cards={[
          card("gpt-6.1-sol", "GPT-6.1 Sol"),
          card("claude-sonnet-5-5", "Claude Sonnet 5.5", {
            full: false,
            text: "Paris is the capital…",
          }),
        ]}
      />,
    );
    fireEvent.click(
      within(
        screen.getByRole("article", { name: "GPT-6.1 Sol's answer" }),
      ).getByRole("button", { name: "Compare with…" }),
    );
    await act(async () => {
      fireEvent.click(
        screen.getByRole("menuitem", { name: "Claude Sonnet 5.5" }),
      );
    });
    expect(fetchHistory).toHaveBeenCalledWith("t1", "n_claude-sonnet-5-5");
    expect(await screen.findByTestId("diff-summary")).toHaveTextContent(
      "1 changed",
    );
  });

  it("is not offered on an answer still streaming, a failed one, or with nothing to compare", () => {
    render(
      <Harness
        cards={[
          card("gpt-6.1-sol", "GPT-6.1 Sol"),
          card("claude-sonnet-5-5", "Claude Sonnet 5.5", { streaming: true }),
          card("gemini-3", "Gemini 3", { error: "Rate limited", text: "" }),
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: "Compare with…" })).toBeNull();
  });
});
