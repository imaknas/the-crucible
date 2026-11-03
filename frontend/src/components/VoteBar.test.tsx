import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import VoteBar from "./VoteBar";
import type { TurnCard } from "@/lib/turns";
import type { AnswerVote } from "@/lib/types";

const card = (model: string, label: string): TurnCard => ({
  key: model,
  model,
  id: `n-${model}`,
  label,
  color: null,
  text: "x",
  full: true,
  streaming: false,
  stopped: false,
  error: null,
  shown: false,
  metrics: null,
});
const cards = [card("claude", "Answer A"), card("gpt", "Answer B")];

describe("VoteBar", () => {
  it("votes for a lettered answer with the task and reason, blind", async () => {
    const onVote = jest.fn().mockResolvedValue(true);
    render(<VoteBar cards={cards} blind vote={null} lastTask="coding" onVote={onVote} />);
    const send = screen.getByRole("button", { name: "Vote and reveal" });
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Answer B is best" }));
    fireEvent.change(screen.getByLabelText("Why (optional)"), { target: { value: "  clearer " } });
    fireEvent.click(send);
    await waitFor(() =>
      expect(onVote).toHaveBeenCalledWith({
        outcome: "best",
        best: "n-gpt",
        reason: "clearer",
        taskType: "coding",
        blind: true,
      }),
    );
  });

  it("says what was voted, revealing the models, and the vote can be changed", () => {
    const vote: AnswerVote = {
      thread_id: "t",
      turn_id: "turn",
      outcome: "best",
      winner_checkpoint_id: "n-gpt",
      answers: [
        { checkpoint_id: "n-claude", model: "claude", model_name: "Claude", letter: "A" },
        { checkpoint_id: "n-gpt", model: "gpt", model_name: "GPT", letter: "B" },
      ],
      reason: "clearer",
      task_type: "coding",
      blind: true,
      created_at: "now",
    };
    render(<VoteBar cards={cards} blind={false} vote={vote} lastTask="general" onVote={jest.fn()} />);
    expect(screen.getByTestId("vote-summary")).toHaveTextContent(
      "You voted GPT best (it was Answer B) · coding · “clearer”",
    );
    fireEvent.click(screen.getByRole("button", { name: "Change vote" }));
    expect(screen.getByRole("button", { name: "Tie" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Vote" })).toBeInTheDocument();
  });
});
