import React, { useLayoutEffect } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider, useStoreApi, type NodeProps } from "reactflow";
import CustomTreeNode, {
  chipScale,
  LOD_CHIP_WIDTH,
  LOD_MAX_BOOST,
  LOD_THRESHOLD,
  type CustomNodeData,
} from "./CustomTreeNode";

jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

// Handles need a node id from a rendered React Flow node; they aren't under
// test. useStore is the real hook, wrapped so a test can count how often the
// node rendered (it reads the zoom once per render).
jest.mock("reactflow", () => {
  const actual = jest.requireActual("reactflow");
  return { ...actual, Handle: () => null, useStore: jest.fn(actual.useStore) };
});
const { useStore: useStoreSpy } = jest.requireMock("reactflow") as { useStore: jest.Mock };

/** The history tree's column pitch (`NODE_SPACING_X` in backend/app/services/tree.py). */
const NODE_SPACING_X = 260;

const RAW_ID = "gpt-5.4-2026-03-17";
const DISPLAY_NAME = "GPT-5.4";

/** Puts the canvas at `zoom` through React Flow's own store. */
function AtZoom({ zoom, children }: { zoom: number; children: React.ReactNode }) {
  const store = useStoreApi();
  useLayoutEffect(() => {
    store.setState({ transform: [0, 0, zoom] });
  }, [store, zoom]);
  return <>{children}</>;
}

function nodeProps(data: CustomNodeData, selected = false): NodeProps<CustomNodeData> {
  return {
    id: "n1",
    data,
    selected,
    type: "custom",
    zIndex: 0,
    isConnectable: false,
    xPos: 0,
    yPos: 0,
    dragging: false,
  };
}

function reply(overrides: Partial<CustomNodeData> = {}): CustomNodeData {
  return {
    label: "The short label",
    metadata: {
      role: "ai",
      active_peer: RAW_ID,
      model_name: DISPLAY_NAME,
      model_color: "#10b981",
      preview: "A much longer excerpt of the reply, nine words",
    },
    styling: { background: "rgb(1, 2, 3)", color: "rgb(4, 5, 6)" },
    ...overrides,
  };
}

function renderNode(zoom: number, props: NodeProps<CustomNodeData>) {
  const view = render(
    <ReactFlowProvider>
      <AtZoom zoom={zoom}>
        <CustomTreeNode {...props} />
      </AtZoom>
    </ReactFlowProvider>,
  );
  return {
    ...view,
    rerenderNode: (next: NodeProps<CustomNodeData>) =>
      view.rerender(
        <ReactFlowProvider>
          <AtZoom zoom={zoom}>
            <CustomTreeNode {...next} />
          </AtZoom>
        </ReactFlowProvider>,
      ),
  };
}

const FAR = 0.5;
const VERY_FAR = 0.3;
const NEAR = 1;

describe("CustomTreeNode level of detail", () => {
  it("renders a chip below the threshold: colour bar, display name, word count", () => {
    const { container } = renderNode(FAR, nodeProps(reply()));
    expect(screen.getByText(DISPLAY_NAME)).toBeInTheDocument();
    expect(screen.getByText("9 words")).toBeInTheDocument();
    // The preview text is not drawn at this distance.
    expect(screen.queryByText("The short label")).not.toBeInTheDocument();
    const chip = container.firstElementChild as HTMLElement;
    expect(chip.style.width).toBe(`${LOD_CHIP_WIDTH}px`);
    // The colour bar carries the model's colour.
    const bar = [...chip.querySelectorAll<HTMLElement>("div")].find((d) => d.style.width === "4px");
    expect(bar?.style.background).toBe("rgb(16, 185, 129)");
  });

  it("keeps only the name when the canvas is very far out", () => {
    renderNode(VERY_FAR, nodeProps(reply()));
    expect(screen.getByText(DISPLAY_NAME)).toBeInTheDocument();
    expect(screen.queryByText(/words/)).not.toBeInTheDocument();
  });

  it("counts CJK characters as words", () => {
    renderNode(FAR, nodeProps(reply({ metadata: { ...reply().metadata, preview: "你好世界 and more" } })));
    expect(screen.getByText("6 words")).toBeInTheDocument();
  });

  it("calls a user message 'You' in the chip", () => {
    renderNode(FAR, nodeProps({ label: "hello there", metadata: { role: "user", preview: "hello there" } }));
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("2 words")).toBeInTheDocument();
  });

  it("renders the preview and the model badge at or above the threshold", () => {
    renderNode(LOD_THRESHOLD, nodeProps(reply()));
    expect(screen.getByText("The short label")).toBeInTheDocument();
    expect(screen.getByText(DISPLAY_NAME)).toBeInTheDocument();
    expect(screen.queryByText(/words/)).not.toBeInTheDocument();
  });

  it("caps the chip's counter-scale so it never reaches the next column", () => {
    const { container } = renderNode(0.1, nodeProps(reply()));
    const chip = container.firstElementChild as HTMLElement;
    expect(chip.style.transform).toBe(`scale(${LOD_MAX_BOOST})`);

    for (const zoom of [0.01, 0.08, 0.2, 0.42, 0.59, LOD_THRESHOLD, 0.8, 1, 2]) {
      expect(chipScale(zoom)).toBeLessThanOrEqual(LOD_MAX_BOOST);
    }
    // Close in, the boost is just the inverse zoom.
    expect(chipScale(1)).toBe(1);
    expect(LOD_CHIP_WIDTH * LOD_MAX_BOOST).toBeLessThan(NODE_SPACING_X);
  });

  it("applies the same rule to the selected node", () => {
    renderNode(FAR, nodeProps(reply({ onDelete: jest.fn(), onBranch: jest.fn() }), true));
    expect(screen.getByText("9 words")).toBeInTheDocument();
    expect(screen.queryByText("The short label")).not.toBeInTheDocument();
    expect(screen.queryByText(/A much longer excerpt/)).not.toBeInTheDocument();
  });
});

describe("CustomTreeNode model name", () => {
  it.each([
    ["chip", FAR],
    ["full node", NEAR],
  ])("shows the display name, never the raw id (%s)", (_, zoom) => {
    const { container } = renderNode(zoom, nodeProps(reply()));
    expect(screen.getByText(DISPLAY_NAME)).toBeInTheDocument();
    expect(container.textContent).not.toContain(RAW_ID);
    // The exact id is still there for anyone who hovers.
    expect(container.querySelector(`[title="${RAW_ID}"]`)).not.toBeNull();
  });
});

describe("CustomTreeNode actions", () => {
  const withActions = () => reply({ onDelete: jest.fn(), onBranch: jest.fn() });

  it("shows Branch and Delete on the selected node without hovering", () => {
    renderNode(NEAR, nodeProps(withActions(), true));
    expect(screen.getByRole("button", { name: "Branch from here" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete message" })).toBeInTheDocument();
  });

  it("shows them on hover for other nodes, and they act on this node", () => {
    const data = withActions();
    const { container } = renderNode(NEAR, nodeProps(data));
    expect(screen.queryByRole("button", { name: "Branch from here" })).not.toBeInTheDocument();
    fireEvent.mouseEnter(container.firstElementChild as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "Branch from here" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete message" }));
    expect(data.onBranch).toHaveBeenCalledWith("n1");
    expect(data.onDelete).toHaveBeenCalledWith("n1");
  });

  it("expands the selected node into the longer excerpt", () => {
    renderNode(NEAR, nodeProps(reply(), true));
    expect(screen.getByText(/A much longer excerpt/)).toBeInTheDocument();
  });
});

describe("CustomTreeNode memo", () => {
  it("repaints when only the styling changes (a theme swap)", () => {
    const data = reply();
    const { container, rerenderNode } = renderNode(NEAR, nodeProps(data));
    const body = () => container.firstElementChild as HTMLElement;
    expect(body().style.background).toBe("rgb(1, 2, 3)");
    rerenderNode(nodeProps({ ...data, styling: { ...data.styling, background: "rgb(9, 9, 9)" } }));
    expect(body().style.background).toBe("rgb(9, 9, 9)");
  });

  it("repaints when only the metadata changes (the model badge)", () => {
    const data = reply();
    const { rerenderNode } = renderNode(NEAR, nodeProps(data));
    rerenderNode(nodeProps({ ...data, metadata: { ...data.metadata, model_name: "GPT-5.4 Mini" } }));
    expect(screen.getByText("GPT-5.4 Mini")).toBeInTheDocument();
  });

  it("skips the render when nothing it draws changed", () => {
    const data = reply();
    const { rerenderNode } = renderNode(NEAR, nodeProps(data));
    useStoreSpy.mockClear();
    rerenderNode(nodeProps({ ...data }));
    expect(useStoreSpy).not.toHaveBeenCalled();
    rerenderNode(nodeProps({ ...data }, true));
    expect(useStoreSpy).toHaveBeenCalled();
  });
});
