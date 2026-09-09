"use client";

import React from "react";
import { Handle, Position } from "reactflow";
import { Sparkles } from "lucide-react";
import { useTheme } from "@mui/material";

interface SynthesisNodeData {
  label: string;
  metadata?: { pending?: boolean; preview?: string };
}

export default function SynthesisTreeNode({
  data,
  selected,
}: {
  data: SynthesisNodeData;
  selected?: boolean;
}) {
  const isDark = useTheme().palette.mode === "dark";
  const isPending = data.metadata?.pending;

  return (
    <>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div
        style={{
          width: 260,
          padding: "14px 18px",
          borderRadius: 16,
          background: isDark
            ? "linear-gradient(135deg, rgba(109,40,217,0.25), rgba(37,99,235,0.2))"
            : "linear-gradient(135deg, rgba(109,40,217,0.08), rgba(37,99,235,0.06))",
          border: `1.5px solid ${selected ? "#8b5cf6" : isDark ? "rgba(139,92,246,0.35)" : "rgba(109,40,217,0.25)"}`,
          boxShadow: selected
            ? "0 0 20px rgba(139,92,246,0.35)"
            : "0 4px 20px -8px rgba(0,0,0,0.15)",
          opacity: isPending ? 0.6 : 1,
          animation: isPending ? "pulse 1.5s ease-in-out infinite" : undefined,
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <Sparkles
          width={18}
          height={18}
          color={isDark ? "#a78bfa" : "#7c3aed"}
          style={{ flexShrink: 0 }}
        />
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: isDark ? "#a78bfa" : "#7c3aed",
              marginBottom: 3,
            }}
          >
            Synthesis
          </div>
          <div
            style={{
              fontSize: 12,
              color: isDark ? "#e2e8f0" : "#1e293b",
              lineHeight: 1.4,
              maxWidth: 200,
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "-webkit-box",
              WebkitLineClamp: selected ? 8 : 1,
              WebkitBoxOrient: "vertical",
              whiteSpace: selected ? "pre-wrap" : "nowrap",
            }}
          >
            {(selected && data.metadata?.preview) ||
              data.label ||
              (isPending ? "Pending…" : "Consensus")}
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </>
  );
}
