import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import ModelErrorBubble from "./ModelErrorBubble";
import type { ModelError } from "@/lib/types";

const RAW_ID = "claude-sonnet-5-20260901";
const LABEL = "Claude Sonnet 5";

const error: ModelError = {
  id: "err-1",
  model: RAW_ID,
  message: "429 Too Many Requests: rate limit reached",
  frame: { model: RAW_ID, parent_checkpoint_id: "cp-7" },
};

function renderBubble(retryDisabled?: boolean) {
  const onRetry = jest.fn();
  const onDismiss = jest.fn();
  const view = render(
    <ModelErrorBubble
      error={error}
      label={LABEL}
      onRetry={onRetry}
      onDismiss={onDismiss}
      retryDisabled={retryDisabled}
    />,
  );
  return { ...view, onRetry, onDismiss };
}

describe("ModelErrorBubble", () => {
  it("is an alert saying which model didn't answer and why", () => {
    renderBubble();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(`${LABEL} didn't answer`);
    expect(alert).toHaveTextContent(error.message);
  });

  it("names the model by its display name; the raw id is only a tooltip", () => {
    const { container } = renderBubble();
    expect(container.textContent).not.toContain(RAW_ID);
    expect(screen.getByText(`${LABEL} didn't answer`)).toHaveAttribute("title", RAW_ID);
  });

  it("Retry asks that model again, by the error's id", () => {
    const { onRetry, onDismiss } = renderBubble();
    fireEvent.click(screen.getByRole("button", { name: `Retry ${LABEL}` }));
    expect(onRetry).toHaveBeenCalledWith("err-1");
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("the icon-only dismiss button has a name and dismisses this error", () => {
    const { onRetry, onDismiss } = renderBubble();
    fireEvent.click(screen.getByRole("button", { name: `Dismiss ${LABEL} error` }));
    expect(onDismiss).toHaveBeenCalledWith("err-1");
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("disables Retry while a turn is running, but not Dismiss", () => {
    renderBubble(true);
    expect(screen.getByRole("button", { name: `Retry ${LABEL}` })).toBeDisabled();
    expect(screen.getByRole("button", { name: `Dismiss ${LABEL} error` })).toBeEnabled();
  });

  it("enables Retry otherwise", () => {
    renderBubble(false);
    expect(screen.getByRole("button", { name: `Retry ${LABEL}` })).toBeEnabled();
  });
});
