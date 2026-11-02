import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import PositionShiftPanel from "./PositionShiftPanel";
import type { Message } from "@/lib/types";

// The shared message renderer pulls in ESM-only markdown packages.
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

const answer = (model: string, round: number, content: string): Message => ({
  id: `${model}-${round}`,
  role: "assistant",
  type: "ai",
  model,
  round,
  content,
});

const shift = {
  startRound: 0,
  endRound: 1,
  rows: [
    { model: "gpt-6.1-sol", first: answer("gpt-6.1-sol", 0, "Yes, at first."), last: answer("gpt-6.1-sol", 1, "No, after all.") },
    { model: "claude-sonnet-5-5", first: answer("claude-sonnet-5-5", 0, "No."), last: null },
  ],
};
const names: Record<string, string> = { "gpt-6.1-sol": "GPT-6.1 Sol", "claude-sonnet-5-5": "Claude Sonnet 5.5" };

function setup() {
  render(
    <PositionShiftPanel
      shift={shift}
      legend={[{ label: "Participant A", name: "GPT-6.1 Sol", modelId: "gpt-6.1-sol", color: "#10b981" }]}
      modelLabel={(id) => names[id] ?? id}
      isDark={false}
    />,
  );
  return screen.getByRole("region", { name: "Where each participant started and ended" });
}

describe("PositionShiftPanel", () => {
  it("puts each participant's Round 1 answer next to its latest", () => {
    const panel = setup();
    expect(within(panel).getByText("Yes, at first.")).toBeInTheDocument();
    expect(within(panel).getByText("No, after all.")).toBeInTheDocument();
    expect(within(panel).getAllByText("Round 1 · independent")).toHaveLength(2);
    expect(within(panel).getByText("Round 2")).toBeInTheDocument();
  });

  it("names participants by display name and peer label, the id only in a tooltip", () => {
    const panel = setup();
    expect(within(panel).getByText("GPT-6.1 Sol")).toHaveAttribute("title", "gpt-6.1-sol");
    expect(within(panel).getByText("Participant A")).toBeInTheDocument();
    expect(panel).not.toHaveTextContent("claude-sonnet-5-5");
  });

  it("says when a participant has no later answer", () => {
    expect(setup()).toHaveTextContent("No later answer");
  });

  it("shows what changed between a participant's first and last answer", () => {
    const panel = setup();
    const toggle = within(panel).getByRole("button", { name: "Show changes in GPT-6.1 Sol's answer" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    // A participant with no later answer has nothing to compare.
    expect(within(panel).queryByRole("button", { name: "Show changes in Claude Sonnet 5.5's answer" })).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(within(panel).getByTestId("diff-summary")).toHaveTextContent("0 sentences the same, 1 only in A, 1 only in B");
    expect(within(panel).getByText("A · Round 1 · independent")).toBeInTheDocument();
    expect(within(panel).getByText("B · Round 2")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(within(panel).queryByTestId("diff-summary")).toBeNull();
    expect(within(panel).getByText("No, after all.")).toBeInTheDocument();
  });

  it("expands to the full answers and back", () => {
    setup();
    const toggle = screen.getByRole("button", { name: "Show both in full" });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Show excerpts" })).toHaveAttribute("aria-expanded", "true");
  });
});
