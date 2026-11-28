import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { IssueCheckPanel, IssueCheckSection } from "./IssueCheckPanel";
import type { IssueCheck } from "@/lib/types";

const check: IssueCheck = {
  thread_id: "t",
  checkpoint_id: "list",
  question: "Review this plan.",
  documents: ["plan.md"],
  source_truncated: false,
  checkers: [
    { model: "gpt-6.1-sol", model_name: "GPT-6.1 Sol" },
    { model: "claude-sonnet-5-5", model_name: "Claude Sonnet 5.5" },
  ],
  issues: [
    {
      number: 1,
      problem: "There is no rollback.",
      raised_by: "GPT-6.1 Sol",
      why: "No backup step.",
      verdicts: [
        { checker: "gpt-6.1-sol", checker_name: "GPT-6.1 Sol", verdict: "holds", reason: "step 2", own: true },
        { checker: "claude-sonnet-5-5", checker_name: "Claude Sonnet 5.5", verdict: "does_not_hold", reason: "step 3", own: false },
      ],
      disagree: true,
    },
    { number: 2, problem: "Cost is low.", raised_by: "", why: "", verdicts: [], disagree: false },
  ],
  errors: { "gemini-3.1-pro-preview": "timed out" },
};
const names: Record<string, string> = { "gemini-3.1-pro-preview": "Gemini 3.1 Pro" };
const label = (id: string) => names[id] ?? id;

describe("IssueCheckPanel", () => {
  it("shows every checker's verdict side by side, never a tally", () => {
    render(<IssueCheckPanel check={check} modelLabel={label} />);
    const panel = screen.getByRole("region", { name: "Does each problem hold?" });
    expect(panel).toHaveTextContent("against the question and plan.md, without knowing who raised it");
    const [first, second] = within(panel).getAllByTestId("checked-issue");
    expect(first).toHaveTextContent("Checkers disagree");
    expect(first).toHaveTextContent("Holds · GPT-6.1 Sol (its own model raised it): step 2");
    expect(first).toHaveTextContent("Doesn't hold · Claude Sonnet 5.5: step 3");
    expect(second).toHaveTextContent("No verdicts");
    expect(second).not.toHaveTextContent("Checkers disagree");
    expect(panel).not.toHaveTextContent(/\d of \d|majority/i);
  });

  it("names a checker that failed by display name", () => {
    render(<IssueCheckPanel check={check} modelLabel={label} />);
    expect(screen.getByRole("note")).toHaveTextContent("Gemini 3.1 Pro couldn't check: timed out");
  });
});

describe("IssueCheckSection", () => {
  it("offers the check, then shows it and offers it again", () => {
    const onRun = jest.fn();
    const { rerender } = render(<IssueCheckSection check={null} running={false} busy={false} onRun={onRun} modelLabel={label} />);
    fireEvent.click(screen.getByRole("button", { name: "Check each problem" }));
    expect(onRun).toHaveBeenCalled();
    rerender(<IssueCheckSection check={check} running={false} busy={false} onRun={onRun} modelLabel={label} />);
    expect(screen.getByRole("button", { name: "Check each problem again" })).toBeEnabled();
    expect(screen.getByRole("region", { name: "Does each problem hold?" })).toBeInTheDocument();
    rerender(<IssueCheckSection check={check} running busy onRun={onRun} modelLabel={label} />);
    expect(screen.getByRole("button", { name: "Check each problem again" })).toBeDisabled();
  });
});
