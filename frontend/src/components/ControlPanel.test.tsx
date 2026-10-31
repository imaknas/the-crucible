import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ControlPanel from "./ControlPanel";
import { DEFAULT_DEBATE_DEFAULTS } from "@/hooks/useDebateDefaults";
import { FALLBACK_LIMITS } from "@/lib/catalog";
import type { Toggles } from "@/lib/types";
import { FAMILIES } from "@/test/families";

jest.mock("@/lib/api", () => ({
  fetchKeyStatus: jest.fn().mockResolvedValue({}),
  saveApiKeys: jest.fn(),
}));
jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

type Props = React.ComponentProps<typeof ControlPanel>;

function props(overrides: Partial<Props> = {}): Props {
  return {
    toggles: { use_rag: false, use_web_search: false },
    setToggles: jest.fn(),
    families: FAMILIES,
    modelsStatus: "ready",
    onReloadModels: jest.fn(),
    onKeysSaved: jest.fn(),
    selectedModels: ["gpt-a", "claude-b"],
    setSelectedModels: jest.fn(),
    messagesCount: 4,
    activeCheckpointLabel: "Latest turn",
    debateDefaults: DEFAULT_DEBATE_DEFAULTS,
    setDebateDefaults: jest.fn(),
    collapsed: false,
    onCollapsedChange: jest.fn(),
    summarizerChoice: "",
    summarizer: null,
    defaultSummarizer: null,
    onSummarizerChange: jest.fn(),
    systemPrompt: "",
    onSystemPromptChange: jest.fn(),
    limits: FALLBACK_LIMITS,
    ...overrides,
  };
}

// ApiKeysSection reads the key status on mount; let it land inside act.
async function renderPanel(p: Props) {
  const view = render(<ControlPanel {...p} />);
  await act(async () => {});
  return view;
}

describe("ControlPanel docked", () => {
  it("shows every section and collapses to the rail", async () => {
    const p = props();
    await renderPanel(p);
    for (const section of ["Status", "Available models", "Parameters", "System prompt", "Summarizer", "Debate", "API Keys"]) {
      expect(screen.getByText(section)).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Close settings" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide settings panel" }));
    expect(p.onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it("as a rail, keeps the selected models legible by name and expands again", async () => {
    const p = props({ collapsed: true });
    await renderPanel(p);
    expect(screen.queryByText("Control Panel")).not.toBeInTheDocument();
    expect(screen.queryByText("Parameters")).not.toBeInTheDocument();
    // One dot per selected model, named by display name, never the raw id.
    expect(screen.getByLabelText("GPT A")).toBeInTheDocument();
    expect(screen.getByLabelText("Claude B")).toBeInTheDocument();
    expect(screen.queryByLabelText("gpt-a")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show settings panel" }));
    expect(p.onCollapsedChange).toHaveBeenCalledWith(false);
  });
});

describe("ControlPanel overlay", () => {
  it("is a closable drawer, never a rail", async () => {
    // A stored collapse belongs to the docked layout: the overlay ignores it.
    const p = props({ mode: "overlay", open: true, collapsed: true, onClose: jest.fn() });
    await renderPanel(p);
    expect(screen.getByLabelText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Parameters")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Hide settings panel" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show settings panel" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    expect(p.onClose).toHaveBeenCalled();
  });

  it("stays mounted but out of sight while closed", async () => {
    await renderPanel(props({ mode: "overlay", open: false, onClose: jest.fn() }));
    expect(screen.getByText("Control Panel")).toBeInTheDocument();
    expect(screen.getByText("Control Panel")).not.toBeVisible();
  });
});

describe("ControlPanel wiring", () => {
  function Harness() {
    const [toggles, setToggles] = React.useState<Toggles>({ use_rag: false, use_web_search: false });
    return (
      <>
        <ControlPanel {...props({ toggles, setToggles })} />
        <output data-testid="toggles">{JSON.stringify(toggles)}</output>
      </>
    );
  }

  it("flips one parameter at a time", async () => {
    render(<Harness />);
    await act(async () => {});
    fireEvent.click(screen.getByLabelText("Web Search Grounding"));
    expect(screen.getByTestId("toggles")).toHaveTextContent('{"use_rag":false,"use_web_search":true}');
    fireEvent.click(screen.getByLabelText("Search my documents"));
    expect(screen.getByTestId("toggles")).toHaveTextContent('{"use_rag":true,"use_web_search":true}');
  });

  it("passes the system prompt through, with the backend's limit", async () => {
    const p = props({ limits: { ...FALLBACK_LIMITS, max_system_prompt_chars: 50 } });
    await renderPanel(p);
    const field = screen.getByLabelText("System prompt");
    expect(field).toHaveAttribute("maxLength", "50");
    fireEvent.change(field, { target: { value: "Be terse." } });
    expect(p.onSystemPromptChange).toHaveBeenCalledWith("Be terse.");
  });

  it("reports a saved key so the catalogue and header reload", async () => {
    const { saveApiKeys } = jest.requireMock("@/lib/api");
    saveApiKeys.mockResolvedValue(undefined);
    const p = props();
    await renderPanel(p);
    // Google has no key, so its entry starts open.
    fireEvent.change(screen.getByPlaceholderText("Paste your Google API key"), { target: { value: "g-key" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save Keys" }));
    });
    await waitFor(() => expect(p.onKeysSaved).toHaveBeenCalled());
  });
});
