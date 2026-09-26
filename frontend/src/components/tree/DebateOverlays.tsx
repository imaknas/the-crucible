import React from "react";
import { useTheme } from "@mui/material";
import type { DebateLane } from "@/lib/types";
import { LANE_WIDTH, ROUND_HEIGHT } from "@/hooks/useDebateTree";

/**
 * Overlays drawn above the React Flow canvas in debate mode, positioned from
 * the viewport transform so they track pan and zoom. Each needs an explicit
 * height: an absolutely positioned row otherwise collapses to zero and its
 * overflow clips every child away.
 */

// Matches the width CustomTreeNode actually renders at.
const NODE_RENDER_WIDTH = 220;

export function DebateLaneHeaders({
  lanes,
  transform,
}: {
  lanes: DebateLane[];
  transform: number[];
}) {
  const isDark = useTheme().palette.mode === "dark";
  const [panX, , zoom] = transform;
  return (
    <div
      style={{
        position: "absolute",
        top: 8,
        left: 0,
        width: "100%",
        // Every pill is absolutely positioned, so the row would collapse to
        // zero height and `overflow: hidden` would clip them all away.
        height: 24,
        pointerEvents: "none",
        zIndex: 10,
        overflowX: "hidden",
      }}
    >
      {lanes.map((lane) => {
        const centerX =
          lane.lane_index * LANE_WIDTH * zoom + panX + NODE_RENDER_WIDTH / 2 * zoom;
        return (
          <div
            key={lane.model_id}
            style={{
              position: "absolute",
              left: centerX,
              transform: "translateX(-50%)",
              padding: "3px 10px",
              borderRadius: 20,
              background: isDark ? "rgba(15,23,42,0.8)" : "rgba(255,255,255,0.85)",
              border: `1px solid ${lane.color}44`,
              backdropFilter: "blur(8px)",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: lane.color,
                flexShrink: 0,
              }}
            />
            <span
              title={lane.model_id}
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: lane.color,
                letterSpacing: "0.06em",
                whiteSpace: "nowrap",
              }}
            >
              {lane.label || lane.model_id}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Horizontal band per debate round, with its convergence score when one was
 * recorded. Without these the rounds are only distinguishable by y-position.
 *
 * Drawn in canvas space (it consumes the same transform React Flow applies to
 * the viewport) so the bands pan and zoom with the nodes they label.
 */
export function DebateRoundBands({
  maxRound,
  roundScores,
  transform,
  laneCount,
}: {
  maxRound: number;
  roundScores: Record<string, number>;
  transform: number[];
  laneCount: number;
}) {
  const isDark = useTheme().palette.mode === "dark";
  const [, panY, zoom] = transform;
  const rows = [];

  for (let r = 0; r <= maxRound; r++) {
    const y = r * ROUND_HEIGHT * zoom + panY;
    const score = roundScores[String(r)];
    rows.push(
      <div
        key={r}
        style={{
          position: "absolute",
          top: y - 14 * zoom,
          left: 0,
          right: 0,
          height: ROUND_HEIGHT * zoom,
          borderTop: `1px dashed ${
            isDark ? "rgba(148,163,184,0.16)" : "rgba(100,116,139,0.16)"
          }`,
          display: "flex",
          alignItems: "flex-start",
          paddingLeft: 10,
          paddingTop: 3,
          gap: 8,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: isDark ? "#64748b" : "#94a3b8",
            whiteSpace: "nowrap",
          }}
        >
          Round {r + 1}
        </span>
        {score != null && (
          <span
            title="Cosine similarity against the previous round"
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "1px 6px",
              borderRadius: 10,
              whiteSpace: "nowrap",
              color: score >= 0.9 ? "#10b981" : score >= 0.75 ? "#f59e0b" : "#64748b",
              background:
                score >= 0.9
                  ? "rgba(16,185,129,0.12)"
                  : score >= 0.75
                    ? "rgba(245,158,11,0.12)"
                    : isDark
                      ? "rgba(148,163,184,0.1)"
                      : "rgba(100,116,139,0.08)",
            }}
          >
            {(score * 100).toFixed(0)}% converged
          </span>
        )}
      </div>,
    );
  }

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        overflow: "hidden",
        zIndex: 1,
      }}
      aria-hidden
      data-lane-count={laneCount}
    >
      {rows}
    </div>
  );
}
