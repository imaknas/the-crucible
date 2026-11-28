import React from "react";
import { render, screen } from "@testing-library/react";
import DebateBanner from "./DebateBanner";

jest.mock("lucide-react", () => new Proxy({}, { get: () => () => null }));

describe("DebateBanner", () => {
  it("shows the session's warnings, also when a debate is reopened", () => {
    render(
      <DebateBanner
        state={{
          round: 1,
          maxRounds: 2,
          status: "completed",
          warnings: ["GPT-6.1 Sol writes the argument map and is also debating."],
        }}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent("writes the argument map and is also debating");
  });

  it("offers the argument map as the next step, and as a redo once it is written", () => {
    const state = { round: 1, maxRounds: 2, status: "completed" as const };
    const { rerender } = render(<DebateBanner state={state} onSynthesize={() => {}} />);
    expect(screen.getByRole("button", { name: "Write the argument map" })).toBeInTheDocument();
    rerender(<DebateBanner state={{ ...state, mapWritten: true }} onSynthesize={() => {}} />);
    expect(screen.getByRole("button", { name: "Rewrite the argument map" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Write the argument map" })).not.toBeInTheDocument();
  });

  it("has no note without warnings", () => {
    render(<DebateBanner state={{ round: 0, maxRounds: 2, status: "running" }} />);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
