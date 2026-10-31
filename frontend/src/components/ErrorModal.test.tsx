import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import ErrorModal from "./ErrorModal";

const TITLE = "Connection lost";
const DETAILS = "WebSocket closed with code 1006";

let writeText: jest.Mock;
const savedClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");

beforeEach(() => {
  // jsdom has no clipboard.
  writeText = jest.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});

afterEach(() => {
  if (savedClipboard) Object.defineProperty(navigator, "clipboard", savedClipboard);
  else delete (navigator as { clipboard?: unknown }).clipboard;
});

function renderModal(props: Partial<React.ComponentProps<typeof ErrorModal>> = {}) {
  const onDismiss = jest.fn();
  render(<ErrorModal title={TITLE} details={DETAILS} onDismiss={onDismiss} {...props} />);
  return { onDismiss, dialog: screen.getByRole("dialog") };
}

describe("ErrorModal", () => {
  it("opens as a dialog named by its title, showing the details", () => {
    const { dialog } = renderModal();
    expect(screen.getByRole("dialog", { name: TITLE })).toBe(dialog);
    expect(within(dialog).getByText(DETAILS)).toBeInTheDocument();
  });

  it("shows the recovery suggestion only when there is one", () => {
    const { dialog } = renderModal({ suggestion: "Check that the backend is running." });
    expect(within(dialog).getByText("Recovery Info:")).toBeInTheDocument();
    expect(within(dialog).getByText(/Check that the backend is running\./)).toBeInTheDocument();
  });

  it("leaves the recovery box out without a suggestion", () => {
    const { dialog } = renderModal();
    expect(within(dialog).queryByText("Recovery Info:")).not.toBeInTheDocument();
  });

  it("Dismiss closes it", () => {
    const { dialog, onDismiss } = renderModal();
    fireEvent.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("Escape closes it too", () => {
    const { dialog, onDismiss } = renderModal();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("Copy Log copies the title and details without closing", () => {
    const { dialog, onDismiss } = renderModal();
    fireEvent.click(within(dialog).getByRole("button", { name: "Copy Log" }));
    expect(writeText).toHaveBeenCalledWith(`${TITLE}: ${DETAILS}`);
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
