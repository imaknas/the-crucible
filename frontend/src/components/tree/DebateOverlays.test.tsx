import React from "react";
import { render, screen } from "@testing-library/react";
import { DebateLaneHeaders, DebateRoundBands } from "./DebateOverlays";
import { LANE_WIDTH, ROUND_HEIGHT } from "@/hooks/useDebateTree";
import type { DebateLane } from "@/lib/types";

/** The width a tree node renders at; lane headers centre over it. */
const NODE_WIDTH = 220;

const lanes: DebateLane[] = [
  { model_id: "gpt-5.4-2026-03-17", label: "GPT-5.4", peer_label: "Participant B", lane_index: 0, color: "#10b981" },
  { model_id: "claude-sonnet-5", label: "Claude Sonnet 5", peer_label: "Participant A", lane_index: 1, color: "#d97706" },
];

it("mirrors the backend's lane layout (services/tree.py)", () => {
  expect([LANE_WIDTH, ROUND_HEIGHT]).toEqual([300, 160]);
});

describe("DebateLaneHeaders", () => {
  const pill = (text: string) => screen.getByText(text).parentElement as HTMLElement;

  it("is an absolutely positioned row with an explicit height, so it never collapses", () => {
    const { container } = render(<DebateLaneHeaders lanes={lanes} transform={[0, 0, 1]} />);
    const row = container.firstElementChild as HTMLElement;
    expect(row.style.position).toBe("absolute");
    expect(row.style.height).toBe("24px");
  });

  it("names each lane by display name; the raw id is only a tooltip", () => {
    const { container } = render(<DebateLaneHeaders lanes={lanes} transform={[0, 0, 1]} />);
    expect(screen.getByText("GPT-5.4")).toHaveAttribute("title", "gpt-5.4-2026-03-17");
    expect(screen.getByText("Claude Sonnet 5")).toHaveAttribute("title", "claude-sonnet-5");
    expect(container.textContent).not.toContain("gpt-5.4-2026-03-17");
  });

  it("falls back to the model id for lanes without a label (older payloads)", () => {
    render(<DebateLaneHeaders lanes={[{ model_id: "gpt-4o", lane_index: 0, color: "#000" }]} transform={[0, 0, 1]} />);
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
  });

  it("shows the peer label the other models saw, so replies naming it can be decoded", () => {
    render(<DebateLaneHeaders lanes={lanes} transform={[0, 0, 1]} />);
    expect(screen.getByText("Participant B")).toHaveAttribute(
      "title",
      "The other models saw GPT-5.4 as Participant B",
    );
    expect(pill("GPT-5.4")).toHaveTextContent("GPT-5.4Participant B");
    expect(pill("Claude Sonnet 5")).toHaveTextContent("Claude Sonnet 5Participant A");
  });

  it("has no peer label when the models saw each other's names", () => {
    const named = lanes.map((lane) => ({ ...lane, peer_label: null }));
    render(<DebateLaneHeaders lanes={named} transform={[0, 0, 1]} />);
    expect(screen.queryByText(/Participant/)).not.toBeInTheDocument();
  });

  it.each([
    [0, 0, 1],
    [-40, 25, 0.5],
    [120, -60, 1.5],
  ])("centres each header over its lane (pan x %d, pan y %d, zoom %d)", (panX, panY, zoom) => {
    render(<DebateLaneHeaders lanes={lanes} transform={[panX, panY, zoom]} />);
    for (const lane of lanes) {
      const left = lane.lane_index * LANE_WIDTH * zoom + panX + (NODE_WIDTH / 2) * zoom;
      expect(pill(lane.label as string).style.left).toBe(`${left}px`);
    }
  });
});

describe("DebateRoundBands", () => {
  const band = (label: string) => screen.getByText(label).parentElement as HTMLElement;

  it("is hidden from assistive technology: it only labels the canvas", () => {
    const { container } = render(
      <DebateRoundBands maxRound={1} roundScores={{}} transform={[0, 0, 1]} laneCount={2} />,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveAttribute("aria-hidden");
    expect(root).toHaveAttribute("data-lane-count", "2");
  });

  it("labels one band per round, numbered from 1, the first as independent answers", () => {
    render(<DebateRoundBands maxRound={2} roundScores={{}} transform={[0, 0, 1]} laneCount={2} />);
    expect(screen.getByText("Round 1 · independent")).toBeInTheDocument();
    expect(screen.getByText("Round 2")).toBeInTheDocument();
    expect(screen.getByText("Round 3")).toBeInTheDocument();
    expect(screen.queryByText("Round 4")).not.toBeInTheDocument();
  });

  it.each([
    [0, 0, 1],
    [10, 50, 0.5],
  ])("places each band on its round with an explicit height (pan x %d, pan y %d, zoom %d)", (panX, panY, zoom) => {
    render(<DebateRoundBands maxRound={1} roundScores={{}} transform={[panX, panY, zoom]} laneCount={2} />);
    for (const [r, label] of [[0, "Round 1 · independent"], [1, "Round 2"]] as const) {
      const row = band(label);
      expect(row.style.position).toBe("absolute");
      expect(row.style.height).toBe(`${ROUND_HEIGHT * zoom}px`);
      expect(row.style.top).toBe(`${r * ROUND_HEIGHT * zoom + panY - 14 * zoom}px`);
    }
  });

  it("shows a stability score only for rounds that recorded one, and calls it stability", () => {
    render(
      <DebateRoundBands maxRound={2} roundScores={{ "1": 0.934, "2": 0 }} transform={[0, 0, 1]} laneCount={2} />,
    );
    expect(band("Round 1 · independent")).not.toHaveTextContent(/stable/);
    const score = screen.getByText("93% stable");
    expect(band("Round 2")).toContainElement(score);
    expect(score.getAttribute("title")).toMatch(/^Stability: .*Not agreement between models\.$/);
    // A score of zero is still a score.
    expect(band("Round 3")).toHaveTextContent("0% stable");
  });

  it("colours the score by how stable the round was", () => {
    render(
      <DebateRoundBands
        maxRound={3}
        roundScores={{ "1": 0.95, "2": 0.8, "3": 0.5 }}
        transform={[0, 0, 1]}
        laneCount={2}
      />,
    );
    expect(screen.getByText("95% stable").style.color).toBe("rgb(16, 185, 129)");
    expect(screen.getByText("80% stable").style.color).toBe("rgb(245, 158, 11)");
    expect(screen.getByText("50% stable").style.color).toBe("rgb(100, 116, 139)");
  });
});
