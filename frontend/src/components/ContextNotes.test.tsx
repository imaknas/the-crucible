import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReplyContextNote } from "./ContextNotes";
import SummaryMarker from "./SummaryMarker";
import BranchChip from "./BranchChip";
import type { BranchPoint } from "@/lib/branching";

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
jest.mock("react-syntax-highlighter/dist/esm/styles/prism", () => ({
  oneDark: {},
  oneLight: {},
}));

const label = (id: string) => (id === "gpt-a" ? "GPT A" : id);

describe("ReplyContextNote", () => {
  it("says what a reply was written from and lists what recall brought back, by display name", () => {
    render(
      <ReplyContextNote
        modelLabel={label}
        context={{
          tokens: 900,
          soft_limit: 1000,
          context_window: null,
          pruned: true,
          kept_verbatim: 5,
          recalled: [
            { role: "user", excerpt: "the vendor budget is 40k" },
            { role: "assistant", author: "gpt-a", excerpt: "agreed on 40k" },
          ],
        }}
      />,
    );
    const toggle = screen.getByRole("button", {
      name: /Written from the summary and 5 recent messages; recall brought back 2/,
    });
    expect(screen.queryByText(/vendor budget/)).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByText(/the vendor budget is 40k/)).toBeInTheDocument();
    expect(screen.getByText("GPT A:")).toBeInTheDocument();
  });

  it("is absent for a reply that saw the whole history", () => {
    const { container } = render(
      <ReplyContextNote
        modelLabel={label}
        context={{
          tokens: 9,
          soft_limit: 1000,
          context_window: null,
          pruned: false,
          recalled: [],
        }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("SummaryMarker", () => {
  it("marks where history was summarized and opens the summary", () => {
    render(
      <SummaryMarker
        isDark={false}
        msg={{
          id: "summary-c1",
          role: "system",
          kind: "summary",
          content: "We chose Postgres.",
        }}
      />,
    );
    const toggle = screen.getByRole("button", {
      name: /Earlier messages summarized/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByText("We chose Postgres.")).toBeInTheDocument();
  });
});

describe("BranchChip: what the next turn inherits", () => {
  const point: BranchPoint = {
    node: {
      id: "a1",
      data: { label: "answer" },
      position: { x: 0, y: 0 },
      metadata: { role: "ai", active_peer: "gpt-a" },
    },
    preview: "answer",
    isLatest: true,
  };
  const row = {
    model: "gpt-a",
    tokens: 900,
    history_tokens: 5000,
    messages: 30,
    summarized: true,
    from_summary: true,
    summarizes_next: false,
    soft_limit: 1000,
    context_window: 4000,
  };

  it("shows the messages and tokens sent, and offers Start fresh", () => {
    const onStartFresh = jest.fn();
    render(
      <BranchChip point={point} onReset={jest.fn()} modelLabel={label} context={[row]} onStartFresh={onStartFresh} />,
    );
    expect(screen.getByTestId("branch-inherits")).toHaveTextContent("Sends 30 messages · ~900 tokens · from a summary");
    fireEvent.click(screen.getByRole("button", { name: /Start fresh/ }));
    expect(onStartFresh).toHaveBeenCalled();
  });

  it("says a fresh start sends nothing earlier, and doesn't offer it again", () => {
    render(
      <BranchChip
        point={{ ...point, isLatest: false, fresh: true, preview: "" }}
        onReset={jest.fn()}
        modelLabel={label}
        onStartFresh={jest.fn()}
      />,
    );
    expect(screen.getByText(/Starting fresh/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start fresh/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue the latest turn instead" })).toBeInTheDocument();
  });
});
