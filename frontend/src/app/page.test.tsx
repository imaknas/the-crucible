import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import Home from "./page";
import * as api from "@/lib/api";
import { TransportProvider } from "@/lib/transport";
import { installReactFlowDom, measureNodes } from "@/test/reactFlowDom";
import { FAMILIES } from "@/test/families";

/**
 * The page's composition: what it wires between hooks that each hook's own
 * tests can't see. The network is mocked at lib/api, sockets through the
 * TransportProvider; everything between them is the real app.
 */

installReactFlowDom();

const MODELS = ["gpt-a", "claude-b"];

const EMPTY_HISTORY = { nodes: [], edges: [], messages: [], current_checkpoint: null };

jest.mock("@/lib/api", () => ({
  API_BASE: "http://test",
  CLIENT_HEADERS: {},
  listThreads: jest.fn(),
  listAnswerReviews: jest.fn(),
  runAnswerReview: jest.fn(),
  listAnswerComponents: jest.fn(),
  fetchHistory: jest.fn(),
  fetchNextTurnContext: jest.fn(),
  listVotes: jest.fn(),
  voteTurn: jest.fn(),
  fetchVoteStats: jest.fn(),
  fetchKeyStatus: jest.fn(),
  fetchModels: jest.fn(),
  listDebateSessions: jest.fn(),
  createDebateSession: jest.fn(),
  fetchDebateSession: jest.fn(),
  fetchDebateTree: jest.fn(),
  fetchDebateTranscript: jest.fn(),
  uploadDocument: jest.fn(),
  searchHistory: jest.fn(),
  saveNodePositions: jest.fn(),
  createWebSocketUrl: (id: string) => `ws://test/ws/${id}`,
  createDebateWebSocketUrl: (id: string) => `ws://test/debate/${id}`,
}));

// ESM-only renderers Jest can't load, as in ChatView.test.
jest.mock("react-markdown", () => {
  const MockMarkdown = ({ children }: { children: React.ReactNode }) => <div>{children}</div>;
  MockMarkdown.displayName = "MockMarkdown";
  return MockMarkdown;
});
jest.mock("remark-gfm", () => ({}));
jest.mock("remark-math", () => ({}));
jest.mock("rehype-katex", () => ({}));
jest.mock("react-syntax-highlighter", () => ({
  Prism: ({ children }: { children: React.ReactNode }) => <pre>{children}</pre>,
}));
jest.mock("react-syntax-highlighter/dist/esm/styles/prism", () => ({ vscDarkPlus: {}, vs: {} }));
jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});
// Animations aren't under test, and AnimatePresence's exit animation would
// hold the old view on screen for a while after every switch.
jest.mock("framer-motion", () => {
  const React = jest.requireActual("react");
  const MOTION_PROPS = ["initial", "animate", "exit", "transition", "layout", "layoutId", "whileHover", "whileTap", "variants"];
  const cache = new Map<string, unknown>();
  const motion = new Proxy(
    {},
    {
      get: (_, tag: string) => {
        if (!cache.has(tag)) {
          const Component = React.forwardRef((props: Record<string, unknown>, ref: unknown) => {
            const rest = { ...props };
            for (const p of MOTION_PROPS) delete rest[p];
            return React.createElement(tag, { ...rest, ref });
          });
          Component.displayName = `motion.${tag}`;
          cache.set(tag, Component);
        }
        return cache.get(tag);
      },
    },
  );
  const AnimatePresence = ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children);
  return { __esModule: true, motion, AnimatePresence };
});

/** A socket the test drives: `emit` plays a server frame, `sent` records client frames. */
class FakeSocket {
  readyState = 1;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev?: unknown) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {}
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
  }
  emit(frame: object) {
    act(() => this.onmessage?.({ data: JSON.stringify(frame) }));
  }
}

let sockets: FakeSocket[] = [];
const chatSocket = (thread = "t1") => {
  const found = sockets.filter((s) => s.url === `ws://test/ws/${thread}`).at(-1);
  if (!found) throw new Error(`no socket for ${thread}`);
  return found;
};

const mocked = api as jest.Mocked<typeof api>;

function renderPage({ view, thread = "t1" }: { view?: "tree" | "arena"; thread?: string | null } = {}) {
  if (view) localStorage.setItem("crucible_view", view);
  if (thread) localStorage.setItem("crucible_thread_id", thread);
  localStorage.setItem("crucible_selected_models", JSON.stringify(MODELS));
  const factory = (url: string) => {
    const s = new FakeSocket(url);
    sockets.push(s);
    return s as unknown as WebSocket;
  };
  return render(
    <TransportProvider value={factory}>
      <Home />
    </TransportProvider>,
  );
}

const composer = () => screen.findByPlaceholderText(/Ask the arena/i);
const storedView = () => localStorage.getItem("crucible_view");
const emptyTreeHint = /Switch to Arena \(top right\)/;

async function send(text: string) {
  fireEvent.change(await composer(), { target: { value: text } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toHaveAttribute("aria-disabled", "false"));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
  });
  await waitFor(() => expect(chatSocket().sent.length).toBe(MODELS.length));
  return chatSocket().sent;
}

function settleTurn() {
  const ws = chatSocket();
  MODELS.forEach((model, i) => {
    ws.emit({ type: "stream_start", model });
    ws.emit({ type: "stream_token", model, token: `Answer ${i}` });
    ws.emit({ type: "stream_end", model, checkpoint_id: `a${i}`, turn_id: "turn1" });
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  sockets = [];
  mocked.listThreads.mockResolvedValue({
    threads: [
      { id: "t1", title: "Thread one" },
      { id: "t2", title: "Thread two" },
    ],
  });
  mocked.fetchHistory.mockResolvedValue(EMPTY_HISTORY);
  mocked.fetchKeyStatus.mockResolvedValue({ OPENAI_API_KEY: { set: true }, ANTHROPIC_API_KEY: { set: true } } as never);
  mocked.fetchModels.mockResolvedValue({ families: FAMILIES, default_model: "gpt-a", default_arena_models: MODELS });
  mocked.listDebateSessions.mockResolvedValue([]);
  mocked.fetchDebateTree.mockResolvedValue({ nodes: [], edges: [], lanes: [], session_metadata: null } as never);
  mocked.fetchDebateTranscript.mockResolvedValue({ question: "", rounds: [], synthesis: null } as never);
  mocked.searchHistory.mockResolvedValue({ results: [] });
  mocked.listAnswerReviews.mockResolvedValue([]);
  mocked.listVotes.mockResolvedValue([]);
  mocked.fetchVoteStats.mockResolvedValue({ task_type: null, task_types: {}, votes: 0, models: [] });
  mocked.fetchNextTurnContext.mockImplementation(async (_t, _c, models) => ({
    checkpoint_id: null,
    models: models.map((model) => ({
      model,
      tokens: 40,
      history_tokens: 40,
      messages: 2,
      summarized: false,
      from_summary: false,
      summarizes_next: false,
      soft_limit: 1000,
      context_window: 2000,
    })),
  }));
});

describe("Home: the view never switches itself", () => {
  it("stays in Arena through a whole turn, then continues the latest turn", async () => {
    renderPage({ view: "arena" });
    const frames = await send("Hello");
    // Nothing was chosen: every model continues its own reply in the latest turn.
    expect(frames.map((f) => f.parent_checkpoint_id)).toEqual([null, null]);

    mocked.fetchHistory.mockClear();
    settleTurn();
    // The settled turn reloads the thread at its head, not at one model's reply.
    await waitFor(() => expect(mocked.fetchHistory).toHaveBeenCalledWith("t1", undefined));
    expect(storedView()).toBe("arena");
    expect(await composer()).toBeInTheDocument();
    expect(screen.queryByText(emptyTreeHint)).not.toBeInTheDocument();
  });

  it("New Session keeps the tree view", async () => {
    renderPage({ view: "tree" });
    expect(await screen.findByText(emptyTreeHint)).toBeInTheDocument();
    await waitFor(() => expect(mocked.fetchHistory).toHaveBeenCalledWith("t1", undefined));

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "New Session" }));
    });
    await waitFor(() => expect(localStorage.getItem("crucible_thread_id")).not.toBe("t1"));
    expect(storedView()).toBe("tree");
    expect(screen.getByText(emptyTreeHint)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Ask the arena/i)).not.toBeInTheDocument();
  });

  it("New Session keeps the Arena view", async () => {
    renderPage({ view: "arena" });
    await composer();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "New Session" }));
    });
    await waitFor(() => expect(localStorage.getItem("crucible_thread_id")).not.toBe("t1"));
    expect(storedView()).toBe("arena");
    expect(await composer()).toBeInTheDocument();
  });

  it("Branch from here leaves the tree for the composer, branching from that reply", async () => {
    mocked.fetchHistory.mockResolvedValue({
      nodes: [
        { id: "u1", position: { x: 0, y: 0 }, data: { label: "The question" }, metadata: { role: "user" } },
        {
          id: "a1",
          position: { x: 0, y: 160 },
          data: { label: "The answer" },
          metadata: { role: "ai", active_peer: "gpt-a", model_name: "GPT A" },
        },
      ],
      edges: [{ id: "e1", source: "u1", target: "a1" }],
      messages: [
        { role: "user", content: "The question", type: "human", checkpoint_id: "u1" },
        { role: "assistant", content: "The answer", type: "ai", model: "gpt-a", checkpoint_id: "a1" },
      ],
      current_checkpoint: "a1",
    } as never);
    renderPage({ view: "tree" });
    await screen.findByText("The answer");
    // React Flow shows nodes once it has measured them.
    act(() => measureNodes());
    // The head is the selected node, so its actions show without hovering.
    const branch = await screen.findByRole("button", { name: "Branch from here" });
    await act(async () => {
      fireEvent.click(branch);
    });
    expect(storedView()).toBe("arena");
    expect(await composer()).toBeInTheDocument();
    expect(screen.getByText(/Branching from/)).toBeInTheDocument();
  });

  it("opening a debate shows its tree", async () => {
    mocked.createDebateSession.mockResolvedValue({ session_id: "s1", participants: MODELS } as never);
    renderPage({ view: "arena" });
    fireEvent.change(await composer(), { target: { value: "Is it true?" } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start debate" })).toHaveAttribute("aria-disabled", "false"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Start debate" }));
    const dialog = await screen.findByRole("dialog");
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Start Debate" }));
    });
    await waitFor(() => expect(mocked.createDebateSession).toHaveBeenCalled());
    expect(mocked.createDebateSession.mock.calls[0][0]).toMatchObject({ parent_thread_id: "t1", participants: MODELS });
    await waitFor(() => expect(storedView()).toBe("tree"));
    expect(screen.queryByPlaceholderText(/Ask the arena/i)).not.toBeInTheDocument();
  });
});

describe("Home: what the next turn inherits", () => {
  const history = {
    nodes: [
      { id: "root", position: { x: 0, y: 0 }, data: { label: "Start" }, metadata: { role: "system" } },
      { id: "u1", position: { x: 0, y: 150 }, data: { label: "The question" }, metadata: { role: "user" } },
      {
        id: "a1",
        position: { x: 0, y: 300 },
        data: { label: "The answer" },
        metadata: { role: "ai", active_peer: "gpt-a", model_name: "GPT A" },
      },
    ],
    edges: [
      { id: "e0", source: "root", target: "u1" },
      { id: "e1", source: "u1", target: "a1" },
    ],
    messages: [
      { role: "user", content: "The question", type: "human", checkpoint_id: "u1" },
      { role: "assistant", content: "The answer", type: "ai", model: "gpt-a", checkpoint_id: "a1" },
    ],
    current_checkpoint: "a1",
  };

  it("measures the next turn for whoever answers, and Start fresh branches from the start", async () => {
    mocked.fetchHistory.mockResolvedValue(history as never);
    renderPage({ view: "arena" });
    expect(await screen.findByTestId("branch-inherits")).toHaveTextContent("Sends 2 messages · ~40 tokens");
    expect(mocked.fetchNextTurnContext).toHaveBeenCalledWith("t1", null, MODELS);

    mocked.fetchHistory.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Start fresh/ }));
    });
    expect(mocked.fetchHistory).toHaveBeenCalledWith("t1", "root");
    expect(await screen.findByText(/Starting fresh/)).toBeInTheDocument();
    await waitFor(() => expect(mocked.fetchNextTurnContext).toHaveBeenLastCalledWith("t1", "root", MODELS));
  });
});

describe("Home: attachments", () => {
  it("an upload goes with the next message and leaves document search off", async () => {
    mocked.uploadDocument.mockResolvedValue({ filename: "notes.txt" });
    const { container } = renderPage({ view: "arena" });
    await composer();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });
    });

    expect(await screen.findByText(/notes\.txt goes with your next message/)).toBeInTheDocument();
    const search = screen.getByLabelText("Search my documents") as HTMLInputElement;
    expect(search.checked).toBe(false);

    const frames = await send("Summarise it");
    for (const frame of frames) {
      expect(frame.toggles).toEqual({ use_rag: false, use_web_search: false });
      expect(frame.document_names).toEqual(["notes.txt"]);
    }
  });

  it("says nothing about document search when it is already on", async () => {
    localStorage.setItem("crucible_toggles", JSON.stringify({ use_rag: true, use_web_search: false }));
    mocked.uploadDocument.mockResolvedValue({ filename: "notes.txt" });
    const { container } = renderPage({ view: "arena" });
    await composer();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });
    });
    await waitFor(() => expect(mocked.uploadDocument).toHaveBeenCalled());
    expect(screen.queryByText(/goes with your next message/)).not.toBeInTheDocument();
  });
});

describe("Home: leaving a thread while models answer", () => {
  it("leaves without asking: the turn runs on on the backend, and coming back reattaches to it", async () => {
    renderPage({ view: "arena" });
    await send("Hello");
    const other = await screen.findByRole("button", { name: "Thread two" });
    await act(async () => {
      fireEvent.click(other);
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(mocked.fetchHistory).toHaveBeenCalledWith("t2", undefined));
    expect(localStorage.getItem("crucible_thread_id")).toBe("t2");
  });

  it("leaves without asking once the turn has settled", async () => {
    renderPage({ view: "arena" });
    await send("Hello");
    settleTurn();
    const other = await screen.findByRole("button", { name: "Thread two" });
    await act(async () => {
      fireEvent.click(other);
    });
    await waitFor(() => expect(mocked.fetchHistory).toHaveBeenCalledWith("t2", undefined));
    expect(screen.queryByText("Leave while models answer?")).not.toBeInTheDocument();
  });
});

describe("Home: adding a model to a turn, and the reply the next message continues", () => {
  const question = { id: "u1", position: { x: 0, y: 0 }, data: { label: "The question" }, metadata: { role: "user" } };
  const answer = (id: string, model: string, name: string) => ({
    id,
    position: { x: 0, y: 160 },
    data: { label: `${name} says` },
    metadata: { role: "ai", active_peer: model, model_name: name, turn_id: "T", preview: `${name} says` },
  });
  const history = (replies: ReturnType<typeof answer>[]) => ({
    nodes: [question, ...replies],
    edges: replies.map((r) => ({ id: `e-${r.id}`, source: "u1", target: r.id })),
    messages: [
      { role: "user", content: "The question", type: "human", checkpoint_id: "u1" },
      { role: "assistant", content: "GPT A says", type: "ai", model: "gpt-a", checkpoint_id: "a1", turn_id: "T" },
    ],
    current_checkpoint: "a1",
  });

  it("asks one more model the turn's question and leaves the branch point where it was", async () => {
    mocked.fetchHistory.mockResolvedValue(history([answer("a1", "gpt-a", "GPT A")]) as never);
    renderPage({ view: "arena" });
    await screen.findByText("GPT A says");
    fireEvent.click(await screen.findByRole("button", { name: "Add a model" }));
    // Only models with a key that aren't in the turn yet.
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Claude B"]);
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Claude B" }));
    });
    const ws = chatSocket();
    expect(ws.sent).toEqual([expect.objectContaining({ model: "claude-b", join_turn: "a1" })]);
    expect(ws.sent[0]).not.toHaveProperty("message");

    mocked.fetchHistory.mockClear();
    ws.emit({ type: "stream_start", model: "claude-b", turn_id: "T", joins_turn: true, message: null });
    expect(await screen.findByRole("article", { name: "Claude B's answer" })).toBeInTheDocument();
    ws.emit({ type: "stream_end", model: "claude-b", checkpoint_id: "b1", turn_id: "T", joins_turn: true });
    // The path on screen reloads; nothing was chosen, so the next message still continues the latest turn.
    await waitFor(() => expect(mocked.fetchHistory).toHaveBeenCalledWith("t1", "a1"));
    expect(screen.queryByTestId("next-here")).not.toBeInTheDocument();
    ws.sent = [];
    const frames = await send("Next");
    expect(frames.map((f) => f.parent_checkpoint_id)).toEqual([null, null]);
  });

  it("Everyone continues from here makes that reply the branch point for every selected model", async () => {
    mocked.fetchHistory.mockResolvedValue(
      history([answer("a1", "gpt-a", "GPT A"), answer("b1", "claude-b", "Claude B")]) as never,
    );
    renderPage({ view: "arena" });
    const claude = await screen.findByRole("article", { name: "Claude B's answer" });
    mocked.fetchHistory.mockClear();
    await act(async () => {
      fireEvent.click(within(claude).getByRole("button", { name: "Everyone continues from here" }));
    });
    expect(mocked.fetchHistory).toHaveBeenCalledWith("t1", "b1");
    expect(await within(screen.getByRole("article", { name: "Claude B's answer" })).findByTestId("next-here")).toBeInTheDocument();
    const frames = await send("Go on");
    expect(frames.map((f) => [f.model, f.parent_checkpoint_id])).toEqual([
      ["gpt-a", "b1"],
      ["claude-b", "b1"],
    ]);
  });
});
