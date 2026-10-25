import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import DebateConfigDialog from "./DebateConfigDialog";
import { DEFAULT_DEBATE_DEFAULTS, MAX_DEBATE_ROUNDS } from "@/hooks/useDebateDefaults";

function setup() {
  const onStart = jest.fn();
  render(
    <DebateConfigDialog
      open
      onClose={jest.fn()}
      onStart={onStart}
      defaults={DEFAULT_DEBATE_DEFAULTS}
      availableModels={["gpt-6.1-sol", "claude-sonnet-5-5"]}
      modelLabel={(id) => ({ "gpt-6.1-sol": "GPT-6.1 Sol", "claude-sonnet-5-5": "Claude Sonnet 5.5" })[id] ?? id}
      question="Is a hot dog a sandwich?"
      participants={["gpt-6.1-sol", "claude-sonnet-5-5"]}
    />,
  );
  return { onStart, rounds: screen.getByLabelText("Max rounds") as HTMLInputElement };
}

describe("DebateConfigDialog", () => {
  it("shows the question and the participants by name", () => {
    setup();
    expect(screen.getByText("Is a hot dog a sandwich?")).toBeInTheDocument();
    expect(screen.getByText("GPT-6.1 Sol")).toBeInTheDocument();
    expect(screen.getByText("Claude Sonnet 5.5")).toBeInTheDocument();
  });

  it("does not clamp the round count while typing", () => {
    const { rounds } = setup();
    fireEvent.change(rounds, { target: { value: "" } });
    expect(rounds.value).toBe("");
    fireEvent.change(rounds, { target: { value: "1" } });
    fireEvent.change(rounds, { target: { value: "10" } });
    expect(rounds.value).toBe("10");
  });

  it("clamps on blur and on start", () => {
    const { rounds, onStart } = setup();
    fireEvent.change(rounds, { target: { value: "99" } });
    fireEvent.blur(rounds);
    expect(rounds.value).toBe(String(MAX_DEBATE_ROUNDS));

    fireEvent.change(rounds, { target: { value: "-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Start Debate" }));
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ max_rounds: 1 }));
  });
});
