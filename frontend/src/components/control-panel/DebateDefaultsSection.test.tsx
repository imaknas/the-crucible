import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import DebateDefaultsSection from "./DebateDefaultsSection";
import { DEFAULT_DEBATE_DEFAULTS } from "@/hooks/useDebateDefaults";
import type { DebateDefaults } from "@/lib/types";

function Harness({ maxRounds = 10 }: { maxRounds?: number }) {
  const [value, setValue] = React.useState<DebateDefaults>(DEFAULT_DEBATE_DEFAULTS);
  return (
    <>
      <DebateDefaultsSection isDark={false} debateDefaults={value} setDebateDefaults={setValue} maxRounds={maxRounds} />
      <output data-testid="saved">{value.max_rounds}</output>
    </>
  );
}

describe("DebateDefaultsSection max rounds", () => {
  it("lets a cleared field be retyped, committing on blur", () => {
    render(<Harness />);
    const field = screen.getByLabelText("Max rounds") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "" } });
    expect(field.value).toBe("");
    fireEvent.change(field, { target: { value: "8" } });
    expect(screen.getByTestId("saved")).toHaveTextContent("3");
    fireEvent.blur(field);
    expect(screen.getByTestId("saved")).toHaveTextContent("8");
  });

  it("clamps to the backend's limit on commit", () => {
    render(<Harness maxRounds={5} />);
    const field = screen.getByLabelText("Max rounds") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "12" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.getByTestId("saved")).toHaveTextContent("5");
    expect(field.value).toBe("5");
  });
});
