import React from "react";
import { render, screen } from "@testing-library/react";
import ChatView from "./ChatView";

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
  };

  it("renders messages correctly", () => {
    // In actual use, messages come from useChatWebSocket, but ChatView also takes them as props.
    // Let's ensure the component renders the messages passed to it.
    render(
      <ChatView
        {...mockProps}
        messages={[
          { role: "user", content: "Hello", type: "human" },
          { role: "assistant", content: "World", type: "ai" },
        ]}
      />,
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("World")).toBeInTheDocument();
  });

  it("shows welcome screen when no threadId exists", () => {
    render(<ChatView {...mockProps} threadId={null} />);
    expect(screen.getByText(/The Council awaits/i)).toBeInTheDocument();
  });
});
