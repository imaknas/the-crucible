import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import SavedCasesDialog from "./SavedCasesDialog";
import type { CaseReplay, CaseSummary, SavedCase } from "@/lib/cases";
import { FAMILIES } from "@/test/families";

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
  const Icon = () => <svg />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

const label = (id: string) => ({ "gpt-a": "GPT A", "claude-b": "Claude B" })[id] ?? id;
const metrics = {
  ttft_ms: 900,
  total_ms: 3000,
  input_tokens: 100,
  output_tokens: 50,
  reasoning_tokens: null,
  cached_input_tokens: null,
  cost_usd: 0.0021,
};

const summary: CaseSummary = {
  case_id: "case-1",
  title: "Which database?",
  question: "Which database?",
  created_at: "2026-11-03 10:00:00",
  source_thread_id: "t1",
  models: ["gpt-a", "claude-b"],
  model_names: ["GPT A", "Claude B"],
  voted: true,
  replay_count: 1,
  last_replayed_at: "2026-11-03 11:00:00",
};

const replay: CaseReplay = {
  replay_id: "r1",
  case_id: "case-1",
  thread_id: "replay-1",
  created_at: "2026-11-03 11:00:00",
  models: ["gpt-a"],
  total: { ...metrics, answers: 1, unpriced: 0 },
  results: [
    {
      model: "gpt-a",
      model_name: "GPT A",
      content: "Use SQLite. It is small.",
      checkpoint_id: "n1",
      error: null,
      metrics,
      baseline: { model: "claude-b", model_name: "Claude B", reason: "voted_best" },
      diff: { summary_text: "1 sentence changed", identical: false },
    },
  ],
};

const savedCase: SavedCase = {
  case_id: "case-1",
  title: "Which database?",
  question: "Which database?",
  created_at: "2026-11-03 10:00:00",
  source_thread_id: "t1",
  source_turn_id: "T",
  history: [
    { role: "user", kind: null, content: "Hi", model: null, model_name: null },
    { role: "assistant", kind: null, content: "Hello", model: "gpt-a", model_name: "GPT A" },
  ],
  history_from: "gpt-a",
  summarized: false,
  documents: [{ name: "brief.md", characters: 20 }],
  searched_documents: [],
  settings: { use_web_search: true, use_rag: false, system_prompt: null, summarizer: null, is_deliberation: false },
  answers: [
    { model: "gpt-a", model_name: "GPT A", content: "Use Postgres.", metrics, checkpoint_id: "a1" },
    {
      model: "claude-b",
      model_name: "Claude B",
      content: "Use Postgres. It is reliable.",
      metrics,
      checkpoint_id: "b1",
    },
  ],
  total: { ...metrics, answers: 2, unpriced: 0 },
  vote: { outcome: "best", winner_checkpoint_id: "b1", reason: "clearer", task_type: "general", blind: false },
  best_model: "claude-b",
  replays: [replay],
};

const handlers = () => ({
  onClose: jest.fn(),
  onBack: jest.fn(),
  onOpenCase: jest.fn(),
  onDelete: jest.fn(),
  onReplay: jest.fn(),
});

function renderDialog(over: Partial<React.ComponentProps<typeof SavedCasesDialog>> = {}) {
  const h = handlers();
  render(
    <SavedCasesDialog
      open
      list={[summary]}
      loading={false}
      current={null}
      replaying={false}
      families={FAMILIES}
      modelLabel={label}
      {...h}
      {...over}
    />,
  );
  return h;
}

describe("SavedCasesDialog: the list", () => {
  it("lists cases by display name and opens or deletes one", () => {
    const h = renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Saved cases" });
    const open = within(dialog).getByRole("button", { name: /^Which database\?/ });
    expect(open).toHaveTextContent("GPT A, Claude B · voted · 1 replay");
    fireEvent.click(open);
    expect(h.onOpenCase).toHaveBeenCalledWith("case-1");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete case Which database?" }));
    expect(h.onDelete).toHaveBeenCalledWith("case-1", "Which database?");
  });

  it("says how to make one when there are none", () => {
    renderDialog({ list: [] });
    expect(screen.getByText(/Save as a case/)).toBeInTheDocument();
  });
});

describe("SavedCasesDialog: a case", () => {
  it("shows the question, context, vote and answers, and never a raw model id", () => {
    renderDialog({ current: savedCase });
    const dialog = screen.getByRole("dialog", { name: "Which database?" });
    expect(within(dialog).getByText(/2 earlier messages · documents: brief.md · web search/)).toBeInTheDocument();
    expect(within(dialog).getByText("Your vote: Claude B was best: clearer")).toBeInTheDocument();
    const answers = within(dialog).getByRole("region", { name: "The case's answers" });
    expect(within(answers).getByRole("article", { name: "Claude B's answer" })).toHaveTextContent(
      "You voted this best.",
    );
    expect(within(answers).getAllByTestId("reply-metrics")).toHaveLength(2);
    // Ids only in tooltips.
    expect(dialog.textContent).not.toMatch(/gpt-a|claude-b/);
  });

  it("replays on the case's own models by default, and on the ones picked", () => {
    const h = renderDialog({ current: savedCase });
    const picker = screen.getByRole("group", { name: "Models to replay on" });
    // Only families with a key; the legacy model isn't the case's, so it isn't offered.
    expect(
      within(picker)
        .getAllByRole("checkbox")
        .map((c) => c.closest("label")?.textContent),
    ).toEqual(["GPT A", "Claude B"]);
    fireEvent.click(screen.getByRole("button", { name: "Replay on 2 models" }));
    expect(h.onReplay).toHaveBeenLastCalledWith(["gpt-a", "claude-b"]);
    fireEvent.click(within(picker).getByRole("checkbox", { name: "GPT A" }));
    fireEvent.click(screen.getByRole("button", { name: "Replay on 1 model" }));
    expect(h.onReplay).toHaveBeenLastCalledWith(["claude-b"]);
  });

  it("holds Replay while one runs", () => {
    renderDialog({ current: savedCase, replaying: true });
    expect(screen.getByRole("button", { name: "Replaying…" })).toBeDisabled();
  });

  it("shows each replay old against new, with its metrics and the diff on request", () => {
    renderDialog({ current: savedCase });
    const section = screen.getByRole("region", { name: "Replay · 2026-11-03 11:00" });
    const card = within(section).getByRole("article", { name: "GPT A's answer" });
    expect(card).toHaveTextContent("Against Claude B's answer, which you voted best: 1 sentence changed");
    expect(within(card).getByTestId("reply-metrics")).toBeInTheDocument();
    expect(within(section).getByTestId("turn-metrics")).toBeInTheDocument();
    expect(screen.queryByTestId("diff-summary")).not.toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Show changes" }));
    expect(within(section).getByTestId("diff-summary")).toBeInTheDocument();
    expect(within(section).getByText(/Claude B \(case\)/)).toBeInTheDocument();
    expect(within(section).getByText(/GPT A \(replay\)/)).toBeInTheDocument();
  });

  it("goes back to the list", () => {
    const h = renderDialog({ current: savedCase });
    fireEvent.click(screen.getByRole("button", { name: "Back to saved cases" }));
    expect(h.onBack).toHaveBeenCalled();
  });
});
