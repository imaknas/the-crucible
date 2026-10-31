import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import BranchChip from "./BranchChip";
import type { BranchPoint } from "@/lib/branching";

const point: BranchPoint = {
  node: {
    id: "a1",
    data: { label: "answer" },
    position: { x: 0, y: 0 },
    metadata: { role: "ai", active_peer: "claude-x", model_name: "Claude X" },
  },
  preview: "answer",
  isLatest: false,
};
const label = (id: string) => (id === "claude-x" ? "Claude X" : id);

describe("BranchChip", () => {
  it("says only the reply's model answers, and switches to every selected model", () => {
    const onChange = jest.fn();
    render(
      <BranchChip
        point={point}
        onReset={jest.fn()}
        modelLabel={label}
        answer={{
          replyModel: "claude-x",
          askAll: false,
          selected: ["gpt-x", "claude-x", "gemini-x"],
          onChange,
        }}
      />,
    );
    const toggle = screen.getByRole("button", {
      name: "Ask all 3 selected models instead",
    });
    expect(toggle).toHaveTextContent("Only Claude X");
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("says every selected model answers, and switches back", () => {
    const onChange = jest.fn();
    render(
      <BranchChip
        point={point}
        onReset={jest.fn()}
        modelLabel={label}
        answer={{
          replyModel: "claude-x",
          askAll: true,
          selected: ["gpt-x", "claude-x", "gemini-x"],
          onChange,
        }}
      />,
    );
    const toggle = screen.getByRole("button", {
      name: "Ask only Claude X instead",
    });
    expect(toggle).toHaveTextContent("All 3 answer");
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("names the one selected model instead of counting it", () => {
    render(
      <BranchChip
        point={point}
        onReset={jest.fn()}
        modelLabel={label}
        answer={{
          replyModel: "claude-x",
          askAll: true,
          selected: ["gpt-x"],
          onChange: jest.fn(),
        }}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Ask only Claude X instead" }),
    ).toHaveTextContent("gpt-x answers");
  });

  it("offers no switch when there is no choice", () => {
    render(<BranchChip point={point} onReset={jest.fn()} modelLabel={label} />);
    expect(screen.queryByRole("button", { name: /^Ask/ })).toBeNull();
  });
});

describe("BranchChip, latest turn", () => {
  it("says the latest turn is continued and offers no way back to it", () => {
    render(<BranchChip point={{ ...point, isLatest: true }} onReset={jest.fn()} modelLabel={label} />);
    expect(screen.getByTestId("branch-chip")).toHaveTextContent("Continuing the latest turn");
    expect(screen.queryByRole("button", { name: /latest turn instead/ })).toBeNull();
  });

  it("offers the latest turn when branching from a chosen node", () => {
    const onReset = jest.fn();
    render(<BranchChip point={point} onReset={onReset} modelLabel={label} />);
    expect(screen.getByTestId("branch-chip")).toHaveTextContent("Branching from Claude X");
    fireEvent.click(screen.getByRole("button", { name: "Continue the latest turn instead" }));
    expect(onReset).toHaveBeenCalled();
  });
});
