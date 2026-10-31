import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ChatInput } from "./ChatInput";

type Props = React.ComponentProps<typeof ChatInput>;

/** The composer as the page uses it: controlled, the text owned outside. */
function Controlled(props: Omit<Props, "value" | "onChange"> & { initial?: string }) {
  const [value, setValue] = React.useState(props.initial ?? "");
  return <ChatInput {...props} value={value} onChange={setValue} />;
}

const baseProps = {
  isLoading: false,
  onSendMessage: jest.fn(),
  onDeliberate: jest.fn(),
  stopStreaming: jest.fn(),
  onAttach: jest.fn(),
  documents: [] as string[],
  onRemoveDocument: jest.fn(),
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
  it("keeps the typed prompt when the debate dialog opens", () => {
    const onDebateOpen = jest.fn();
    render(<Controlled {...baseProps} onDebateOpen={onDebateOpen} />);
    fireEvent.change(composer(), { target: { value: "Tabs or spaces?" } });
    fireEvent.click(screen.getByRole("button", { name: /Start debate/i }));

    expect(onDebateOpen).toHaveBeenCalledWith("Tabs or spaces?");
    expect(composer().value).toBe("Tabs or spaces?"); // a cancelled dialog loses nothing
  });

  it("shows whatever its owner puts in it, the same text twice included", () => {
    const { rerender } = render(<ChatInput {...baseProps} value="Edited question" onChange={jest.fn()} />);
    expect(composer().value).toBe("Edited question");
    rerender(<ChatInput {...baseProps} value="" onChange={jest.fn()} />);
    expect(composer().value).toBe("");
    rerender(<ChatInput {...baseProps} value="Edited question" onChange={jest.fn()} />);
    expect(composer().value).toBe("Edited question");
  });

  it("sends the typed text and leaves clearing to its owner", () => {
    const onSendMessage = jest.fn();
    render(<Controlled {...baseProps} onSendMessage={onSendMessage} />);
    fireEvent.change(composer(), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSendMessage).toHaveBeenCalledWith("Hello");
  });

  it("deliberates with an empty box instead of silently doing nothing", () => {
    const onDeliberate = jest.fn();
    render(
      <Controlled
        {...baseProps}
        selectedModels={["gpt-6.1-sol"]}
        messages={[{ id: "m", role: "user", content: "Hi" }]}
        onDeliberate={onDeliberate}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Deliberate" }));
    expect(onDeliberate).toHaveBeenCalledWith("");
  });

  it("disables Deliberate with more than one model selected", () => {
    render(<Controlled {...baseProps} messages={[{ id: "m", role: "user", content: "Hi" }]} />);
    expect(screen.getByRole("button", { name: "Deliberate" })).toHaveAttribute("aria-disabled", "true");
  });

  it("deliberates with a clicked reply's model while the debate keeps the selection", () => {
    render(
      <Controlled
        {...baseProps}
        respondingModels={["claude-sonnet-5-5"]}
        messages={[{ id: "m", role: "user", content: "Hi" }]}
        onDebateOpen={jest.fn()}
      />,
    );
    fireEvent.change(composer(), { target: { value: "Go on" } });
    expect(screen.getByRole("button", { name: "Deliberate" })).toHaveAttribute("aria-disabled", "false");
    expect(screen.getByRole("button", { name: /Start debate/i })).toHaveAttribute("aria-disabled", "false");
  });

  it("says attachments go with one message, shows an upload in progress, and takes the same file twice", () => {
    const onAttach = jest.fn();
    const { container, rerender } = render(
      <Controlled {...baseProps} onAttach={onAttach} documents={["notes.txt"]} uploading="big.pdf" />,
    );
    expect(screen.getByText("Sent with your next message only")).toBeInTheDocument();
    expect(screen.getByText("Uploading big.pdf…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Attach a document" })).toBeDisabled();

    rerender(<Controlled {...baseProps} onAttach={onAttach} documents={[]} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["x"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onAttach).toHaveBeenCalledWith(file);
    expect(input.value).toBe("");
  });

  it("counts down near the backend's limit and refuses to send over it", () => {
    render(<Controlled {...baseProps} maxChars={20} />);
    fireEvent.change(composer(), { target: { value: "x".repeat(19) } });
    expect(screen.getByTestId("chars-left")).toHaveTextContent("1 characters left");
    expect(screen.getByRole("button", { name: "Send" })).toHaveAttribute("aria-disabled", "false");
    fireEvent.change(composer(), { target: { value: "x".repeat(25) } });
    expect(screen.getByTestId("chars-left")).toHaveTextContent("5 over the limit");
    expect(screen.getByRole("button", { name: "Send" })).toHaveAttribute("aria-disabled", "true");
  });
});
