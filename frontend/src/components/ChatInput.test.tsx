import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ChatInput } from "./ChatInput";

const baseProps = {
  isLoading: false,
  onSendMessage: jest.fn(),
  onDeliberate: jest.fn(),
  stopStreaming: jest.fn(),
  onFileUpload: jest.fn(),
  documents: {},
  setDocuments: jest.fn(),
  selectedModels: ["gpt-6.1-sol", "claude-sonnet-5-5"],
  messages: [],
  onEditAndRebranch: jest.fn(),
  showEditButton: false,
  isDark: true,
};

function composer() {
  return screen.getByPlaceholderText(/Ask the arena/i) as HTMLTextAreaElement;
}

describe("ChatInput", () => {
  it("keeps the typed prompt when the debate dialog opens, and clears it once the debate starts", () => {
    const onDebateOpen = jest.fn();
    const { rerender } = render(<ChatInput {...baseProps} onDebateOpen={onDebateOpen} clearSignal={0} />);
    fireEvent.change(composer(), { target: { value: "Tabs or spaces?" } });
    fireEvent.click(screen.getByRole("button", { name: /Start debate/i }));

    expect(onDebateOpen).toHaveBeenCalledWith("Tabs or spaces?");
    expect(composer().value).toBe("Tabs or spaces?"); // a cancelled dialog loses nothing

    rerender(<ChatInput {...baseProps} onDebateOpen={onDebateOpen} clearSignal={1} />);
    expect(composer().value).toBe("");
  });
});
