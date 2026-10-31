import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import SynthesisTreeNode from "./SynthesisTreeNode";

jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

// Handles need a node id from a rendered React Flow node; they aren't under test.
jest.mock("reactflow", () => ({ ...jest.requireActual("reactflow"), Handle: () => null }));

type Data = React.ComponentProps<typeof SynthesisTreeNode>["data"];

const RAW_ID = "gemini-3.5-pro-preview-09-2026";
const DISPLAY_NAME = "Gemini 3.5 Pro";

function synthesis(overrides: Partial<Data> = {}): Data {
  return {
    label: "Both answers agree on the date",
    metadata: {
      model_name: DISPLAY_NAME,
      active_peer: RAW_ID,
      preview: "A longer excerpt of the merged answer, shown when selected",
    },
    ...overrides,
  };
}

function renderNode(data: Data, selected = false) {
  const view = render(<SynthesisTreeNode id="s1" data={data} selected={selected} />);
  const root = view.container.firstElementChild as HTMLElement;
  // The 220px card is the element that carries the pending style.
  const card = root.querySelector<HTMLElement>('div[style*="width: 220px"]') as HTMLElement;
  return { ...view, root, card };
}

const ACTIONS = ["Read in full", "Branch from here", "Delete message"];

function visibleActions() {
  return ACTIONS.filter((name) => screen.queryByRole("button", { name }));
}

describe("SynthesisTreeNode heading", () => {
  it("names its author by display name; the raw id is only a tooltip", () => {
    const { container } = renderNode(synthesis());
    expect(screen.getByText(`Synthesis · ${DISPLAY_NAME}`)).toHaveAttribute("title", RAW_ID);
    expect(container.textContent).not.toContain(RAW_ID);
  });

  it("says only 'Synthesis' when the author is unknown", () => {
    renderNode(synthesis({ metadata: {} }));
    expect(screen.getByText("Synthesis")).toBeInTheDocument();
    expect(screen.queryByText(/Synthesis ·/)).not.toBeInTheDocument();
  });
});

describe("SynthesisTreeNode text", () => {
  it("shows the label when not selected", () => {
    renderNode(synthesis());
    expect(screen.getByText("Both answers agree on the date")).toBeInTheDocument();
    expect(screen.queryByText(/A longer excerpt/)).not.toBeInTheDocument();
  });

  it("expands into the longer excerpt when selected", () => {
    renderNode(synthesis(), true);
    expect(screen.getByText(/A longer excerpt/)).toBeInTheDocument();
    expect(screen.queryByText("Both answers agree on the date")).not.toBeInTheDocument();
  });

  it("keeps the label when selected without an excerpt", () => {
    renderNode(synthesis({ metadata: { model_name: DISPLAY_NAME } }), true);
    expect(screen.getByText("Both answers agree on the date")).toBeInTheDocument();
  });
});

describe("SynthesisTreeNode pending vs settled", () => {
  it("a pending placeholder is faded, pulses and says Pending…", () => {
    const { card } = renderNode({ label: "", metadata: { pending: true } });
    expect(screen.getByText("Pending…")).toBeInTheDocument();
    expect(card.style.opacity).toBe("0.6");
    expect(card.style.animation).toContain("pulse");
  });

  it("a settled node is opaque and still", () => {
    const { card } = renderNode(synthesis());
    expect(screen.queryByText("Pending…")).not.toBeInTheDocument();
    expect(card.style.opacity).toBe("1");
    expect(card.style.animation).toBe("");
  });
});

describe("SynthesisTreeNode actions", () => {
  it("a debate synthesis offers only Read in full, on hover, for this node", () => {
    const onRead = jest.fn();
    const { root } = renderNode(synthesis({ onRead }));
    expect(visibleActions()).toEqual([]);
    fireEvent.mouseEnter(root);
    expect(visibleActions()).toEqual(["Read in full"]);
    fireEvent.click(screen.getByRole("button", { name: "Read in full" }));
    expect(onRead).toHaveBeenCalledWith("s1");
    fireEvent.mouseLeave(root);
    expect(visibleActions()).toEqual([]);
  });

  it("a chat synthesis offers Branch from here and delete, acting on this node", () => {
    const onBranch = jest.fn();
    const onDelete = jest.fn();
    const { root } = renderNode(synthesis({ onBranch, onDelete }));
    fireEvent.mouseEnter(root);
    expect(visibleActions()).toEqual(["Branch from here", "Delete message"]);
    fireEvent.click(screen.getByRole("button", { name: "Branch from here" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete message" }));
    expect(onBranch).toHaveBeenCalledWith("s1");
    expect(onDelete).toHaveBeenCalledWith("s1");
  });

  it("shows the actions on the selected node without hovering, for keyboard and touch", () => {
    renderNode(synthesis({ onBranch: jest.fn(), onDelete: jest.fn() }), true);
    expect(visibleActions()).toEqual(["Branch from here", "Delete message"]);
  });

  it("has no actions without callbacks, even hovered and selected", () => {
    const { root } = renderNode(synthesis(), true);
    fireEvent.mouseEnter(root);
    expect(screen.queryAllByRole("button")).toEqual([]);
  });

  it("an action's click doesn't also select the node", () => {
    const onClick = jest.fn();
    const onRead = jest.fn();
    render(
      <div onClick={onClick}>
        <SynthesisTreeNode id="s1" data={synthesis({ onRead })} selected />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Read in full" }));
    expect(onRead).toHaveBeenCalledWith("s1");
    expect(onClick).not.toHaveBeenCalled();
  });
});
