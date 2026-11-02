import React from "react";
import { render, screen, within } from "@testing-library/react";
import PeerReviewPanel from "./PeerReviewPanel";
import type { AnswerReview } from "@/lib/types";

const review: AnswerReview = {
  review_key: "k",
  thread_id: "t",
  checkpoint_ids: ["a", "b"],
  question: "Which?",
  answers: [
    { label: "A", checkpoint_id: "a", model: "gpt-6.1-sol", model_name: "GPT-6.1 Sol", average: 4, scores: [
      { reviewer: "claude-sonnet-5-5", reviewer_name: "Claude Sonnet 5.5", score: 4, reason: "thin" },
    ] },
    { label: "B", checkpoint_id: "b", model: "claude-sonnet-5-5", model_name: "Claude Sonnet 5.5", average: 8, scores: [
      { reviewer: "gpt-6.1-sol", reviewer_name: "GPT-6.1 Sol", score: 8, reason: "precise" },
    ] },
  ],
  errors: { "gemini-3.1-pro-preview": "timed out" },
};
const names: Record<string, string> = { "gemini-3.1-pro-preview": "Gemini 3.1 Pro" };

describe("PeerReviewPanel", () => {
  it("lists each answer's average with every reviewer's reason, as evidence", () => {
    render(<PeerReviewPanel review={review} modelLabel={(id) => names[id] ?? id} />);
    const panel = screen.getByRole("region", { name: "How the models scored each other's answers" });
    expect(panel).toHaveTextContent("Evidence to weigh, not a verdict");
    expect(panel).not.toHaveTextContent(/best answer|winner/i);
    expect(within(panel).getByText("8.0 / 10")).toBeInTheDocument();
    expect(within(panel).getByText("GPT-6.1 Sol: 8 — precise")).toBeInTheDocument();
    // Highest first.
    expect(panel.textContent!.indexOf("8.0 / 10")).toBeLessThan(panel.textContent!.indexOf("4.0 / 10"));
  });

  it("names a reviewer that failed by display name", () => {
    render(<PeerReviewPanel review={review} modelLabel={(id) => names[id] ?? id} />);
    expect(screen.getByRole("note")).toHaveTextContent("Gemini 3.1 Pro couldn't review: timed out");
    expect(screen.getByRole("note")).not.toHaveTextContent("gemini-3.1-pro-preview");
  });
});
