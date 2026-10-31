import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material";
import dagre from "dagre";
import type { Edge } from "reactflow";
import TreeCanvas, { type CustomNode } from "./TreeCanvas";
import { installReactFlowDom, measureNodes } from "@/test/reactFlowDom";

jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

// The real useReactFlow, with fitView observed: each call is recorded and then
// handed to React Flow's own fitView, which moves the viewport as usual.
const mockFitView = jest.fn();
jest.mock("reactflow", () => {
  const actual = jest.requireActual("reactflow");
  const { useMemo } = jest.requireActual("react");
  return {
    __esModule: true,
    ...actual,
    useReactFlow: () => {
      const instance = actual.useReactFlow();
      return useMemo(
        () => ({
          ...instance,
          fitView: (options: unknown) => {
            mockFitView(options);
            return instance.fitView(options);
          },
        }),
        [instance],
      );
    },
  };
});

installReactFlowDom();

const light = createTheme({ palette: { mode: "light" } });
const dark = createTheme({ palette: { mode: "dark" } });

function node(id: string, x: number, y: number, label = `Reply ${id}`): CustomNode {
  return {
    id,
    position: { x, y },
    data: { label },
    metadata: { role: "ai", active_peer: "gpt-5.4", model_name: "GPT-5.4", model_color: "#10b981" },
  };
}

const twoNodes = () => [node("a", 0, 0), node("b", 0, 160)];
const edgesFor = (nodes: CustomNode[]): Edge[] =>
  nodes.slice(1).map((n, i) => ({ id: `e${i}`, source: nodes[i].id, target: n.id }));

type Props = React.ComponentProps<typeof TreeCanvas>;

function renderCanvas(props: Props, theme = light) {
  const view = render(
    <ThemeProvider theme={theme}>
      <TreeCanvas {...props} />
    </ThemeProvider>,
  );
  return {
    ...view,
    rerenderCanvas: (next: Props, nextTheme = theme) =>
      view.rerender(
        <ThemeProvider theme={nextTheme}>
          <TreeCanvas {...next} />
        </ThemeProvider>,
      ),
  };
}

/** The node body CustomTreeNode draws, inside React Flow's wrapper. */
function body(container: HTMLElement, id: string) {
  const wrapper = container.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`);
  return wrapper?.firstElementChild as HTMLElement;
}
function wrapperTransform(container: HTMLElement, id: string) {
  return container.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`)?.style.transform;
}
function viewportTransform(container: HTMLElement) {
  return container.querySelector<HTMLElement>(".react-flow__viewport")?.style.transform;
}

const ACTIVE_LIGHT = "rgb(59, 130, 246)"; // #3b82f6
const ACTIVE_DARK = "rgb(37, 99, 235)"; // #2563eb

beforeEach(() => {
  mockFitView.mockClear();
});

describe("TreeCanvas node sync", () => {
  it("applies a label change when the set of node ids is unchanged", () => {
    const nodes = twoNodes();
    const { rerenderCanvas } = renderCanvas({ nodes, edges: edgesFor(nodes) });
    expect(screen.getByText("Reply b")).toBeInTheDocument();
    const relabelled = [nodes[0], node("b", 0, 160, "Reply b, edited")];
    rerenderCanvas({ nodes: relabelled, edges: edgesFor(relabelled) });
    expect(screen.getByText("Reply b, edited")).toBeInTheDocument();
  });

  it("restyles the active node when the selection moves", () => {
    const nodes = twoNodes();
    const edges = edgesFor(nodes);
    const { container, rerenderCanvas } = renderCanvas({ nodes, edges, activeNodeId: "a" });
    expect(body(container, "a").style.background).toBe(ACTIVE_LIGHT);
    rerenderCanvas({ nodes, edges, activeNodeId: "b" });
    expect(body(container, "a").style.background).not.toBe(ACTIVE_LIGHT);
    expect(body(container, "b").style.background).toBe(ACTIVE_LIGHT);
  });

  it("repaints the nodes on a theme swap", () => {
    const nodes = twoNodes();
    const edges = edgesFor(nodes);
    const props = { nodes, edges, activeNodeId: "a" };
    const { container, rerenderCanvas } = renderCanvas(props, light);
    const replyColour = body(container, "b").style.background;
    rerenderCanvas(props, dark);
    expect(body(container, "a").style.background).toBe(ACTIVE_DARK);
    expect(body(container, "b").style.background).not.toBe(replyColour);
  });

  it("keeps the positions on screen through a restyle", () => {
    // Side by side, so the tidy layout (one above the other) moves them.
    const nodes = [node("a", 0, 0), node("b", 600, 0)];
    const edges = edgesFor(nodes);
    const props = { nodes, edges };
    const { container, rerenderCanvas } = renderCanvas(props, light);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Tidy layout" }));
    });
    const tidied = wrapperTransform(container, "b");
    expect(tidied).not.toBe("translate(600px,0px)");
    rerenderCanvas(props, dark);
    expect(wrapperTransform(container, "b")).toBe(tidied);
  });
});

describe("TreeCanvas layout", () => {
  let layoutSpy: jest.SpyInstance;
  beforeEach(() => {
    layoutSpy = jest.spyOn(dagre, "layout");
  });
  afterEach(() => {
    layoutSpy.mockRestore();
  });

  it("offers Tidy layout in a chat tree, which lays out with dagre and saves every position", () => {
    const nodes = twoNodes();
    const onLayoutPositions = jest.fn();
    renderCanvas({ nodes, edges: edgesFor(nodes), onLayoutPositions });
    expect(layoutSpy).not.toHaveBeenCalled();
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Tidy layout" }));
    });
    expect(layoutSpy).toHaveBeenCalledTimes(1);
    expect(onLayoutPositions).toHaveBeenCalledTimes(1);
    expect(onLayoutPositions.mock.calls[0][0].map((u: { node_id: string }) => u.node_id)).toEqual(["a", "b"]);
  });

  it("never runs dagre in debate mode: the lanes keep their positions", () => {
    // Lane layout from the backend: x = lane × 300, y = round × 160.
    const nodes = [node("m1-r0", 0, 0), node("m2-r0", 300, 0), node("m1-r1", 0, 160)];
    const { container } = renderCanvas({ nodes, edges: [], debateMode: true });
    act(() => measureNodes());
    expect(screen.queryByRole("button", { name: "Tidy layout" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recenter on the active node" })).toBeInTheDocument();
    expect(layoutSpy).not.toHaveBeenCalled();
    expect(wrapperTransform(container, "m2-r0")).toBe("translate(300px,0px)");
    expect(wrapperTransform(container, "m1-r1")).toBe("translate(0px,160px)");
  });

  it("lays out each thread on its own, whatever was laid out before", () => {
    const threadA = [node("a1", 0, 0), node("a2", 0, 0), node("a3", 0, 0)];
    const threadB = [node("b1", 0, 0), node("b2", 0, 0)];
    const onLayoutPositions = jest.fn();
    const tidy = () =>
      act(() => {
        fireEvent.click(screen.getByRole("button", { name: "Tidy layout" }));
      });

    const { rerenderCanvas } = renderCanvas({ nodes: threadA, edges: edgesFor(threadA), onLayoutPositions });
    tidy();
    rerenderCanvas({ nodes: threadB, edges: edgesFor(threadB), onLayoutPositions });
    tidy();
    // A lone chain is one column at the layout's left edge. A dagre graph that
    // kept the earlier thread's nodes placed this one beside them instead.
    const laidOutB = onLayoutPositions.mock.calls[1][0] as { node_id: string; x: number }[];
    expect(laidOutB.map((u) => u.node_id)).toEqual(["b1", "b2"]);
    expect(laidOutB.map((u) => u.x)).toEqual([0, 0]);
  });
});

describe("TreeCanvas auto-fit", () => {
  it("waits until React Flow has measured the nodes, then fits the whole tree once", async () => {
    const nodes = twoNodes();
    const { container } = renderCanvas({ nodes, edges: edgesFor(nodes) });
    // Fitting now would be a silent no-op: the store has no node sizes yet.
    expect(mockFitView).not.toHaveBeenCalled();
    const before = viewportTransform(container);

    act(() => measureNodes());
    expect(mockFitView).toHaveBeenCalledTimes(1);
    expect(mockFitView.mock.calls[0][0]).not.toHaveProperty("nodes");
    // React Flow's own fitView ran and moved the viewport.
    await waitFor(() => expect(viewportTransform(container)).not.toBe(before));
  });

  it("fits once per structural change, not on a restyle", () => {
    const nodes = twoNodes();
    const { rerenderCanvas } = renderCanvas({ nodes, edges: edgesFor(nodes) }, light);
    act(() => measureNodes());
    expect(mockFitView).toHaveBeenCalledTimes(1);

    // Same ids: a theme swap and a relabel leave the viewport to the person.
    rerenderCanvas({ nodes, edges: edgesFor(nodes) }, dark);
    const relabelled = [nodes[0], node("b", 0, 160, "Reply b, edited")];
    rerenderCanvas({ nodes: relabelled, edges: edgesFor(relabelled) }, dark);
    act(() => measureNodes());
    expect(mockFitView).toHaveBeenCalledTimes(1);

    // A new node is structural, and is fitted once it has been measured.
    const grown = [...relabelled, node("c", 0, 320)];
    rerenderCanvas({ nodes: grown, edges: edgesFor(grown) }, dark);
    expect(mockFitView).toHaveBeenCalledTimes(1);
    act(() => measureNodes());
    expect(mockFitView).toHaveBeenCalledTimes(2);
  });

  it("fits the active node when the whole tree would be unreadably small", () => {
    // Too wide for a 560px pane at a zoom where nodes still show their text.
    const nodes = [node("a", 0, 0), node("b", 1200, 0)];
    renderCanvas({ nodes, edges: edgesFor(nodes), activeNodeId: "b" });
    act(() => measureNodes());
    expect(mockFitView).toHaveBeenCalledTimes(1);
    expect(mockFitView.mock.calls[0][0]).toMatchObject({ nodes: [{ id: "b" }] });
  });

  it("fits the whole tree when it is readable, even with an active node", () => {
    const nodes = twoNodes();
    renderCanvas({ nodes, edges: edgesFor(nodes), activeNodeId: "b" });
    act(() => measureNodes());
    expect(mockFitView).toHaveBeenCalledTimes(1);
    expect(mockFitView.mock.calls[0][0]).not.toHaveProperty("nodes");
  });
});
