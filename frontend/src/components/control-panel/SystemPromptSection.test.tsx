import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import SystemPromptSection from "./SystemPromptSection";

describe("SystemPromptSection", () => {
  it("holds the backend's limit and counts only near it", () => {
    const onChange = jest.fn();
    const { rerender } = render(<SystemPromptSection value="short" onChange={onChange} maxChars={100} />);
    const field = screen.getByLabelText("System prompt");
    expect(field).toHaveAttribute("maxLength", "100");
    expect(screen.queryByText(/characters\./)).not.toBeInTheDocument();
    fireEvent.change(field, { target: { value: "Be terse." } });
    expect(onChange).toHaveBeenCalledWith("Be terse.");

    rerender(<SystemPromptSection value={"x".repeat(95)} onChange={onChange} maxChars={100} />);
    expect(screen.getByText(/95 \/ 100 characters\./)).toBeInTheDocument();
  });
});
