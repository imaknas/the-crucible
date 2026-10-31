import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import ChatView from "./ChatView";
import { replyAuthor } from "./MessageBubble";

// Mock high-level hooks and dependencies
jest.mock("@/hooks/useChatWebSocket", () => ({
  useChatWebSocket: () => ({
    messages: [
      { role: "user", content: "Hello", type: "human" },
      { role: "assistant", content: "World", type: "ai" },
    ],
    isLoading: false,
    sendInteractiveMessage: jest.fn(),
    stopStreaming: jest.fn(),
  }),
}));

jest.mock("@/hooks/useHistoryTree", () => ({
  useHistoryTree: () => ({
    history: { nodes: [], edges: [] },
    activeNodeId: "root",
    setActiveNodeId: jest.fn(),
  }),
}));

// Mock ESM libraries that cause Jest issues
jest.mock("react-markdown", () => {
  const MockMarkdown = ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  );
  MockMarkdown.displayName = "MockMarkdown";
  return MockMarkdown;
});
jest.mock("remark-gfm", () => ({}));
jest.mock("remark-math", () => ({}));
jest.mock("rehype-katex", () => ({}));
jest.mock("react-syntax-highlighter", () => ({
  Prism: ({ children }: { children: React.ReactNode }) => <pre>{children}</pre>,
}));
jest.mock("react-syntax-highlighter/dist/esm/styles/prism", () => ({
  vscDarkPlus: {},
  vs: {},
}));
// Every icon renders as an empty element, whichever ones a component uses.
jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

// Mock ResizeObserver for JSDOM
global.ResizeObserver = jest.fn().mockImplementation(() => ({
  observe: jest.fn(),
  unobserve: jest.fn(),
  disconnect: jest.fn(),
}));

describe("ChatView", () => {
  const mockProps = {
    messages: [],
    nodes: [],
    edges: [],
    isLoading: false,
    input: "",
    setInput: jest.fn(),
    onSendMessage: jest.fn(),
    onViewReply: jest.fn(),
    onContinueReply: jest.fn(),
    onSynthesize: jest.fn(),
    onDeliberate: jest.fn(),
    setShowTree: jest.fn(),
    documents: [] as string[],
    onRemoveDocument: jest.fn(),
    onEditAndRebranch: jest.fn(),
    onAttach: jest.fn(),
    stopStreaming: jest.fn(),
    showEditButton: true,
    selectedModels: ["gpt-4o"],
    clearDocuments: jest.fn(),
    setErrorModals: jest.fn(),
    modelLabel: (id: string) => (id === "claude-sonnet-5-5" ? "Claude Sonnet 5.5" : id),
  };

  it("renders messages correctly", () => {
    // In actual use, messages come from useChatWebSocket, but ChatView also takes them as props.
    // Let's ensure the component renders the messages passed to it.
    render(
      <ChatView
        {...mockProps}
        messages={[
          { id: "msg-1", role: "user", content: "Hello", type: "human" },
          { id: "msg-2", role: "assistant", content: "World", type: "ai" },
        ]}
      />,
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("World")).toBeInTheDocument();
  });

  it("shows welcome screen when no threadId exists", () => {
    render(<ChatView {...mockProps} />);
    expect(screen.getByText(/Ask the arena anything/i)).toBeInTheDocument();
  });

  it("labels a reply with the model's display name, raw ID only in the tooltip", () => {
    render(
      <ChatView
        {...mockProps}
        messages={[
          { id: "u", role: "user", content: "Hi", type: "human" },
          { id: "a", role: "assistant", content: "Hello", type: "ai", model: "claude-sonnet-5-5" },
        ]}
      />,
    );
    const label = screen.getByText("Claude Sonnet 5.5");
    expect(label).toHaveAttribute("title", "claude-sonnet-5-5");
    expect(screen.queryByText(/CLAUDE SONNET 5 5/i)).not.toBeInTheDocument();
  });
});

describe("ChatView synthesis", () => {
  const base = {
    nodes: [],
    edges: [],
    isLoading: false,
    input: "",
    setInput: jest.fn(),
    onSendMessage: jest.fn(),
    onViewReply: jest.fn(),
    onContinueReply: jest.fn(),
    onSynthesize: jest.fn(),
    onDeliberate: jest.fn(),
    setShowTree: jest.fn(),
    documents: [] as string[],
    onRemoveDocument: jest.fn(),
    onEditAndRebranch: jest.fn(),
    onAttach: jest.fn(),
    stopStreaming: jest.fn(),
    showEditButton: false,
    selectedModels: ["gpt-6.1-sol"],
    modelLabel: (id: string) => id,
  };

  it("shows a tagged synthesis reply as a synthesis, not as another answer", () => {
    render(
      <ChatView
        {...base}
        messages={[
          { id: "u", role: "user", content: "Q", type: "human" },
          { id: "s", role: "assistant", content: "Merged answer", model: "m", model_name: "Claude", kind: "synthesis" },
        ]}
      />,
    );
    expect(screen.getByText("Synthesis · Claude")).toBeInTheDocument();
  });

  const node = (id: string, model: string, turn: string, extra: object = {}) => ({
    id,
    data: { label: id },
    position: { x: 0, y: 0 },
    metadata: { role: "ai", active_peer: model, model_name: model.toUpperCase(), turn_id: turn, preview: `${id} excerpt` },
    ...extra,
  });
  const question = { id: "u", role: "user", content: "Q", type: "human" };
  // The path on screen: the question and GPT's reply in turn t1.
  const gptReply = { id: "a1", role: "assistant", content: "GPT's whole reply", model: "gpt", checkpoint_id: "a1", turn_id: "t1" };

  it("shows a multi-model turn as cards in place of the reply, and synthesizes the real answers", () => {
    const onSynthesize = jest.fn();
    render(
      <ChatView
        {...base}
        onSynthesize={onSynthesize}
        messages={[question, gptReply]}
        nodes={[node("a1", "gpt", "t1"), node("b1", "claude", "t1"), node("syn", "gpt", "t1", { type: "synthesis" }), node("old", "gpt", "t0")]}
        // Each model continued its own branch: the answers share a turn, not a parent.
        edges={[
          { id: "e1", source: "pa", target: "a1" },
          { id: "e2", source: "pb", target: "b1" },
        ]}
      />,
    );
    expect(screen.getAllByRole("article")).toHaveLength(2);
    // The path's own reply is its card, whole, not also a bubble above.
    expect(screen.getAllByText("GPT's whole reply")).toHaveLength(1);
    fireEvent.click(screen.getByText("Synthesize answers"));
    expect(onSynthesize).toHaveBeenCalledWith(["a1", "b1"], null);
  });

  it("reads another answer without changing who answers next, and continues it only on request", () => {
    const onViewReply = jest.fn();
    const onContinueReply = jest.fn();
    render(
      <ChatView
        {...base}
        onViewReply={onViewReply}
        onContinueReply={onContinueReply}
        messages={[question, gptReply]}
        nodes={[node("a1", "gpt", "t1"), node("b1", "claude", "t1")]}
        edges={[]}
      />,
    );
    const claude = screen.getByRole("article", { name: "CLAUDE's answer" });
    fireEvent.click(within(claude).getByRole("button", { name: "Read in full" }));
    expect(onViewReply).toHaveBeenCalledWith("b1");
    expect(onContinueReply).not.toHaveBeenCalled();
    fireEvent.click(within(claude).getByRole("button", { name: "Continue with CLAUDE" }));
    expect(onContinueReply).toHaveBeenCalledWith("b1");
  });

  it("streams a multi-model turn into cards, Continue waiting for each reply's node", () => {
    const live = {
      key: "live-1",
      turnId: "t1",
      replies: [
        { model: "gpt", content: "Partial GPT", streaming: true },
        { model: "claude", content: "Claude done", streaming: false, checkpoint_id: "b1" },
      ],
    };
    render(<ChatView {...base} isLoading messages={[question]} liveTurn={live} />);
    const gpt = screen.getByRole("article", { name: "gpt's answer" });
    expect(gpt).toHaveAttribute("aria-busy", "true");
    expect(within(gpt).getByText("Partial GPT")).toBeInTheDocument();
    expect(within(gpt).getByRole("button", { name: "Continue with gpt" })).toBeDisabled();
    const claude = screen.getByRole("article", { name: "claude's answer" });
    expect(within(claude).getByRole("button", { name: "Continue with claude" })).toBeEnabled();
  });

  it("keeps the same cards when the turn settles: only their content and ids fill in", () => {
    const live = {
      key: "live-1",
      turnId: "t1",
      replies: [
        { model: "gpt", content: "GPT's whole reply", streaming: false, checkpoint_id: "a1", turn_id: "t1" },
        { model: "claude", content: "Claude's whole reply", streaming: false, checkpoint_id: "b1", turn_id: "t1" },
      ],
    };
    const { rerender } = render(<ChatView {...base} messages={[question]} liveTurn={live} />);
    const before = screen.getAllByRole("article");
    rerender(
      <ChatView
        {...base}
        messages={[question, gptReply]}
        nodes={[node("a1", "gpt", "t1"), node("b1", "claude", "t1")]}
        edges={[]}
        liveTurn={live}
        replyTexts={{ a1: "GPT's whole reply", b1: "Claude's whole reply" }}
      />,
    );
    const after = screen.getAllByRole("article");
    // Same DOM nodes: nothing remounted, so nothing jumps.
    expect(after).toHaveLength(2);
    expect(after[0]).toBe(before[0]);
    expect(after[1]).toBe(before[1]);
    expect(within(after[1]).getByText("Claude's whole reply")).toBeInTheDocument();
  });

  it("shows a model that failed in the turn on its card, with Retry", () => {
    const onRetryModel = jest.fn();
    const live = {
      key: "live-1",
      turnId: "t1",
      replies: [
        { model: "gpt", content: "Fine", streaming: false, checkpoint_id: "a1" },
        { model: "claude", content: "", streaming: false, error: "rate limited" },
      ],
    };
    render(
      <ChatView
        {...base}
        messages={[question]}
        liveTurn={live}
        modelErrors={[{ id: "err-1", model: "claude", message: "rate limited", frame: {} }]}
        onRetryModel={onRetryModel}
      />,
    );
    const claude = screen.getByRole("article", { name: "claude's answer" });
    expect(within(claude).getByRole("alert")).toHaveTextContent("rate limited");
    fireEvent.click(within(claude).getByRole("button", { name: "Retry" }));
    expect(onRetryModel).toHaveBeenCalledWith("err-1");
  });
});

describe("replyAuthor", () => {
  const label = (id: string) => (id === "gpt-6.1-sol" ? "GPT-6.1 Sol" : id);
  it("prefers the backend's display name", () => {
    expect(replyAuthor({ model: "gpt-6.1-sol", model_name: "Backend Name" }, label)).toBe("Backend Name");
  });
  it("falls back to the catalogue", () => {
    expect(replyAuthor({ model: "gpt-6.1-sol" }, label)).toBe("GPT-6.1 Sol");
  });
  it("never invents a name from an unknown author", () => {
    expect(replyAuthor({ model: "assistant" }, label)).toBe("Assistant");
    expect(replyAuthor({}, label)).toBe("Assistant");
  });
});
