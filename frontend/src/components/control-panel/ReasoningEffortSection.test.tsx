import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import ReasoningEffortSection from "./ReasoningEffortSection";
import type { ModelFamily } from "@/lib/api";

const families: ModelFamily[] = [
  {
    key: "anthropic", label: "Anthropic", color: "#000", available: true,
    models: [{ id: "claude-opus-5-5", name: "Claude Opus 5.5", desc: "", reasoning_efforts: ["low", "medium", "high", "max"] }],
  },
  {
    key: "openai", label: "OpenAI", color: "#000", available: true,
    models: [{ id: "gpt-6.2-astra", name: "GPT-6.2 Astra", desc: "", reasoning_efforts: null }],
  },
];
const choices = ["low", "medium", "high", "max"];

describe("ReasoningEffortSection", () => {
  it("offers each model's default and the backend's choices", () => {
    const onChange = jest.fn();
    render(<ReasoningEffortSection choice="" choices={choices} families={families} models={["claude-opus-5-5"]} onChange={onChange} />);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Reasoning effort" }));
    const list = within(screen.getByRole("listbox"));
    expect(list.getByText("Each model's default")).toBeInTheDocument();
    fireEvent.click(list.getByText(/Highest/));
    expect(onChange).toHaveBeenCalledWith("max");
  });

  it("says which answering models won't get it", () => {
    render(
      <ReasoningEffortSection
        choice="high"
        choices={choices}
        families={families}
        models={["claude-opus-5-5", "gpt-6.2-astra"]}
        onChange={jest.fn()}
      />,
    );
    expect(screen.getByTestId("effort-note")).toHaveTextContent(
      "GPT-6.2 Astra: levels not verified yet (catalog-sync --probe effort); they answer at their default",
    );
  });

  it("says so when every answering model takes it", () => {
    render(<ReasoningEffortSection choice="high" choices={choices} families={families} models={["claude-opus-5-5"]} onChange={jest.fn()} />);
    expect(screen.getByTestId("effort-note")).toHaveTextContent("Every model answering takes this level.");
  });
});
