import React from "react";
import { render, screen } from "@testing-library/react";
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
jest.mock("lucide-react", () => ({
  Send: () => <div />,
  FileText: () => <div />,
  Edit3: () => <div />,
  CheckCircle2: () => <div />,
  Sparkles: () => <div />,
  Network: () => <div />,
  Scale: () => <div />,
  X: () => <div />,
  StopCircle: () => <div />,
}));

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
    onSwitchCheckpoint: jest.fn(),
    onSynthesize: jest.fn(),
    onDeliberate: jest.fn(),
    setShowTree: jest.fn(),
    documents: {},
    setDocuments: jest.fn(),
    activeCheckpoint: "cp1",
    onDeleteNode: jest.fn(),
    onEditAndRebranch: jest.fn(),
    onFileUpload: jest.fn(),
    stopStreaming: jest.fn(),
    showEditButton: true,
    threadId: "t1",
    selectedModels: ["gpt-4o"],
    clearDocuments: jest.fn(),
    onHistoryRefreshNeeded: jest.fn(),
    setActiveCheckpoint: jest.fn(),
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
    render(<ChatView {...mockProps} threadId={null} />);
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
