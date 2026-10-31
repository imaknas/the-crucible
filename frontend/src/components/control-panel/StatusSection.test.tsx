import React from "react";
import { render, screen } from "@testing-library/react";
import StatusSection from "./StatusSection";
import { FAMILIES } from "@/test/families";

const base = {
  isDark: false,
  families: FAMILIES,
  selectedModels: ["gpt-a", "claude-b"],
  activeCheckpointLabel: "Latest turn",
  messagesCount: 7,
};

describe("StatusSection", () => {
  it("shows the selection by name, the branch point and the tree size", () => {
    render(<StatusSection {...base} />);
    expect(screen.getByText("GPT A")).toBeInTheDocument();
    expect(screen.getByText("Claude B")).toBeInTheDocument();
    expect(screen.getByText("Latest turn")).toBeInTheDocument();
    expect(screen.getByText("7 nodes")).toBeInTheDocument();
  });

  it("says who answers next only when it isn't the selection", () => {
    const { rerender } = render(<StatusSection {...base} respondingModels={["gpt-a", "claude-b"]} />);
    expect(screen.queryByText("Answers next")).not.toBeInTheDocument();

    rerender(<StatusSection {...base} respondingModels={["claude-b"]} />);
    expect(screen.getByText("Answers next")).toBeInTheDocument();
    expect(screen.getByText(/You are continuing a reply/)).toBeInTheDocument();
  });
});
