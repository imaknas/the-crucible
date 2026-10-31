import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import ModelPickerSection from "./ModelPickerSection";
import { FAMILIES } from "@/test/families";

jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

type Props = React.ComponentProps<typeof ModelPickerSection>;

function renderPicker(overrides: Partial<Props> = {}) {
  const p: Props = {
    isDark: false,
    families: FAMILIES,
    status: "ready",
    onRetry: jest.fn(),
    selectedModels: ["gpt-a"],
    setSelectedModels: jest.fn(),
    ...overrides,
  };
  render(<ModelPickerSection {...p} />);
  return p;
}

const family = (label: RegExp) => screen.getByRole("button", { name: label });
const model = (name: RegExp) => screen.getByRole("button", { name });

describe("ModelPickerSection", () => {
  it("lists families collapsed, with their counts and a missing key", () => {
    renderPicker();
    expect(family(/^OpenAI/)).toHaveAttribute("aria-expanded", "false");
    expect(family(/^Google/)).toHaveTextContent("1 models · No API key");
    fireEvent.click(family(/^OpenAI/));
    expect(family(/^OpenAI/)).toHaveAttribute("aria-expanded", "true");
  });

  it("adds and removes models from the selection", () => {
    const p = renderPicker({ selectedModels: ["gpt-a", "claude-b"] });
    fireEvent.click(family(/^OpenAI/));
    expect(model(/^GPT A/)).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(model(/^GPT A/));
    expect(p.setSelectedModels).toHaveBeenLastCalledWith(["claude-b"]);
    fireEvent.click(model(/^GPT Old/));
    expect(p.setSelectedModels).toHaveBeenLastCalledWith(["gpt-a", "claude-b", "gpt-old"]);
  });

  it("keeps the last selected model", () => {
    const p = renderPicker({ selectedModels: ["gpt-a"] });
    fireEvent.click(family(/^OpenAI/));
    fireEvent.click(model(/^GPT A/));
    expect(p.setSelectedModels).not.toHaveBeenCalled();
  });

  it("disables a family's models until it has a key, and says why", () => {
    const p = renderPicker();
    fireEvent.click(family(/^Google/));
    const gemini = model(/^Gemini C/);
    expect(gemini).toBeDisabled();
    expect(gemini).toHaveAttribute("title", "Add a Google API key to use this model");
    fireEvent.click(gemini);
    expect(p.setSelectedModels).not.toHaveBeenCalled();
  });

  it("says when the catalogue is loading or failed, and retries", () => {
    const { rerender } = render(
      <ModelPickerSection isDark={false} families={[]} status="loading" onRetry={jest.fn()} selectedModels={[]} setSelectedModels={jest.fn()} />,
    );
    expect(screen.getByText("Loading models…")).toBeInTheDocument();
    const onRetry = jest.fn();
    rerender(
      <ModelPickerSection isDark={false} families={[]} status="error" onRetry={onRetry} selectedModels={[]} setSelectedModels={jest.fn()} />,
    );
    expect(screen.getByText("Failed to load models.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalled();
  });
});
