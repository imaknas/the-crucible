import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import BlindVotesSection from "./BlindVotesSection";

jest.mock("lucide-react", () => {
  const Icon = () => <svg />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

describe("BlindVotesSection", () => {
  it("switches blind comparison and lists the win rates by display name", () => {
    const onBlindChange = jest.fn();
    render(
      <BlindVotesSection
        isDark={false}
        blind={false}
        onBlindChange={onBlindChange}
        taskType=""
        onTaskTypeChange={jest.fn()}
        stats={{
          task_type: null,
          task_types: { coding: 2 },
          votes: 2,
          models: [
            {
              model: "gpt-5.4",
              model_name: "GPT-5.4",
              wins: 2,
              losses: 0,
              ties: 1,
              all_bad: 0,
              votes: 2,
              win_rate: 0.833,
            },
            { model: "x", model_name: "X", wins: 0, losses: 0, ties: 0, all_bad: 1, votes: 1, win_rate: null },
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByRole("switch", { name: "Blind comparison" }));
    expect(onBlindChange).toHaveBeenCalledWith(true);
    const table = screen.getByTestId("win-rates");
    expect(table).toHaveTextContent("GPT-5.483%2–0–10");
    expect(table).toHaveTextContent("X—0–0–01");
  });
});
