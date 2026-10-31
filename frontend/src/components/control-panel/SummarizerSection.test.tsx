import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import SummarizerSection from "./SummarizerSection";
import { FAMILIES } from "@/test/families";

type Props = React.ComponentProps<typeof SummarizerSection>;

function renderSection(overrides: Partial<Props> = {}) {
  const p: Props = {
    families: FAMILIES,
    choice: "",
    summarizer: null,
    defaultSummarizer: "claude-b",
    onChange: jest.fn(),
    ...overrides,
  };
  render(<SummarizerSection {...p} />);
  return p;
}

describe("SummarizerSection", () => {
  it("names the automatic choice and offers only current models with a key", () => {
    const p = renderSection();
    const select = screen.getByRole("combobox", { name: "Summarizer model" });
    expect(select).toHaveTextContent("Automatic (Claude B)");
    fireEvent.mouseDown(select);
    const options = within(screen.getByRole("listbox")).getAllByRole("option");
    expect(options.map((o) => o.getAttribute("aria-label") ?? o.textContent)).toEqual([
      "Automatic (Claude B)",
      "GPT A, OpenAI",
      "Claude B, Anthropic",
    ]);
    fireEvent.click(screen.getByRole("option", { name: "GPT A, OpenAI" }));
    expect(p.onChange).toHaveBeenCalledWith("gpt-a");
  });

  it("says when the picked model lost its key and the automatic choice is used", () => {
    renderSection({ choice: "gemini-c", summarizer: null });
    expect(screen.getByText(/no longer has an API key/)).toBeInTheDocument();
  });
});
