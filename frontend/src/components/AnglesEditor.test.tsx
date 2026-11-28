import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { AngleChips, AnglesButton } from "./AnglesEditor";

const label = (id: string) => ({ a: "Model A", b: "Model B" })[id] ?? id;

function Harness({ initial = {} }: { initial?: Record<string, string> }) {
  const [angles, setAngles] = React.useState<Record<string, string>>(initial);
  return (
    <>
      <AnglesButton models={["a", "b"]} angles={angles} onChange={setAngles} modelLabel={label} maxChars={500} />
      <AngleChips angles={angles} onChange={setAngles} modelLabel={label} />
    </>
  );
}

describe("AnglesEditor", () => {
  it("gives each answering model a field, and a suggestion fills the first empty one", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Angles" }));
    const dialog = screen.getByRole("dialog", { name: "Angles for the next message" });
    fireEvent.change(screen.getByLabelText("Model A"), { target: { value: "its security" } });
    fireEvent.click(screen.getByText("The case against it"));
    expect(screen.getByLabelText("Model B")).toHaveValue("The case against it");
    expect(dialog).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByRole("button", { name: "Angles (2)" })).toBeInTheDocument();
    expect(screen.getByText("Model A: its security")).toBeInTheDocument();
  });

  it("removes one angle from its chip, and Clear all removes them all", () => {
    render(<Harness initial={{ a: "cost", b: "risk" }} />);
    fireEvent.click(screen.getByLabelText("Remove Model A's angle"));
    expect(screen.queryByText("Model A: cost")).not.toBeInTheDocument();
    expect(screen.getByText("Model B: risk")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Angles (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(screen.queryByText("Model B: risk")).not.toBeInTheDocument();
  });
});
