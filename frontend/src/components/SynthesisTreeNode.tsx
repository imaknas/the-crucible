"use client";

import React, { useState } from "react";
import { Handle, Position } from "reactflow";
import { GitBranch, Sparkles, Trash2 } from "lucide-react";
import { useTheme } from "@mui/material";

interface SynthesisNodeData {
  label: string;
  metadata?: { pending?: boolean; preview?: string; model_name?: string; active_peer?: string };
  /** Chat trees only: debate synthesis nodes are read-only. */
  onDelete?: (nodeId: string) => void;
  onBranch?: (nodeId: string) => void;
}

/**
 * A synthesis: one answer merged from several. Used for debate synthesis and
 * for chat replies the backend tagged as synthesis turns. 220px wide like the
 * other nodes, so it fits the 260px layout pitch next to its siblings.
 */
export default function SynthesisTreeNode({
  id,
  data,
  selected,
}: {
  id: string;
  data: SynthesisNodeData;
  selected?: boolean;
}) {
  const isDark = useTheme().palette.mode === "dark";
  const [hovered, setHovered] = useState(false);
  const isPending = data.metadata?.pending;
  const author = data.metadata?.model_name;

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ position: "relative" }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div
        style={{
          width: 220,
          padding: "14px 16px",
          borderRadius: 16,
          background: isDark
            ? "linear-gradient(135deg, rgba(109,40,217,0.25), rgba(37,99,235,0.2))"
            : "linear-gradient(135deg, rgba(109,40,217,0.08), rgba(37,99,235,0.06))",
          border: `1.5px solid ${selected ? "#8b5cf6" : isDark ? "rgba(139,92,246,0.35)" : "rgba(109,40,217,0.25)"}`,
          boxShadow: selected ? "0 0 20px rgba(139,92,246,0.35)" : "0 4px 20px -8px rgba(0,0,0,0.15)",
          opacity: isPending ? 0.6 : 1,
          animation: isPending ? "pulse 1.5s ease-in-out infinite" : undefined,
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <Sparkles width={18} height={18} color={isDark ? "#a78bfa" : "#7c3aed"} style={{ flexShrink: 0 }} />
        <div style={{ minWidth: 0 }}>
          <div
            title={data.metadata?.active_peer}
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: isDark ? "#a78bfa" : "#7c3aed",
              marginBottom: 3,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {author ? `Synthesis · ${author}` : "Synthesis"}
          </div>
          <div
            style={{
              fontSize: 12,
              color: isDark ? "#e2e8f0" : "#1e293b",
              lineHeight: 1.4,
              maxWidth: 170,
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "-webkit-box",
              WebkitLineClamp: selected ? 8 : 2,
              WebkitBoxOrient: "vertical",
              whiteSpace: selected ? "pre-wrap" : "normal",
            }}
          >
            {(selected && data.metadata?.preview) || data.label || (isPending ? "Pending…" : "Synthesis")}
          </div>
        </div>
      </div>
      {/* On hover and when selected, so keyboard and touch reach them too. */}
      {(hovered || selected) && (data.onDelete || data.onBranch) && (
        <div style={{ position: "absolute", top: -8, right: -8, display: "flex", gap: 4, zIndex: 200 }}>
            {data.onBranch && (
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  data.onBranch?.(id);
                }}
                title="Branch from here: write the next message from this point"
                aria-label="Branch from here"
                style={{
                  background: "#2563eb",
                  border: "none",
                  borderRadius: 12,
                  height: 24,
                  padding: "0 8px",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  color: "white",
                  fontSize: 11,
                  fontWeight: 700,
                  boxShadow: "0 2px 8px rgba(37, 99, 235, 0.4)",
                  whiteSpace: "nowrap",
                }}
              >
                <GitBranch size={12} />
                Branch
              </button>
            )}
        {data.onDelete && (
        <button
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            data.onDelete?.(id);
          }}
          title="Delete this synthesis and everything below it"
          aria-label="Delete message"
          style={{
            width: 24,
            height: 24,
            borderRadius: "50%",
            border: "none",
            background: "#ef4444",
            color: "white",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Trash2 size={12} />
        </button>
        )}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}
