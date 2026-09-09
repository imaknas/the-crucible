import React, { useState } from "react";
import { Handle, Position, NodeProps, useStore } from "reactflow";
import { Trash2, Brain } from "lucide-react";
import { useTheme, Box, Typography } from "@mui/material";

export type CustomNodeData = {
  label: string;
  onDelete?: (nodeId: string) => void;
  styling?: any;
  metadata?: {
    role?: string;
    active_peer?: string;
    model_name?: string;
    model_color?: string;
    thesis_preview?: string;
    has_thoughts?: boolean;
    preview?: string;
    round_num?: number;
  };
};

/**
 * Below this zoom the 12px clamped preview is unreadable, so the node swaps to
 * a chip carrying only what survives at distance: who spoke, and roughly how
 * much. Without it, a fit-all view of a large thread is just coloured boxes.
 */
const LOD_THRESHOLD = 0.6;
/**
 * The chip is counter-scaled to stay legible as the canvas shrinks, but it
 * still occupies canvas space: the tightest layout pitch is 260px (history
 * tree; debate lanes are 300px), so a 190px chip can grow by at most ~1.36x
 * before neighbouring columns collide.
 */
const LOD_CHIP_WIDTH = 190;
const LOD_MAX_BOOST = 1.35;
const zoomSelector = (s: { transform: number[] }) => s.transform[2];

/** Rough size signal for the far-zoom chip; the label is a clipped preview. */
function wordCount(text: string) {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  // CJK has no spaces, so fall back to character count for those runs.
  const cjk = (trimmed.match(/[\u3400-\u9fff\u3040-\u30ff]/g) || []).length;
  const latin = trimmed
    .replace(/[\u3400-\u9fff\u3040-\u30ff]/g, " ")
    .split(/\s+/)
    .filter(Boolean).length;
  return cjk + latin;
}

const CustomTreeNode = React.memo(
  ({ id, data, selected }: NodeProps<CustomNodeData>) => {
    const isDark = useTheme().palette.mode === "dark";
    const [isHovered, setIsHovered] = useState(false);
    const zoom = useStore(zoomSelector);

    const hasThoughts = data.metadata?.has_thoughts;
    const modelId = data.metadata?.active_peer || "";
    const modelName = data.metadata?.model_name || modelId;
    const role = data.metadata?.role || "";
    const accent = data.metadata?.model_color || data.styling?.color;

    // Far zoom: legibility over detail, for the selected node too. Exempting
    // it was backwards — at this scale its 12px preview renders smaller than
    // the chip's label, so the exemption made the one node you care about the
    // hardest to read while breaking the overview's consistency. Selection
    // still reads: the chip inherits the active background and glow.
    if (zoom < LOD_THRESHOLD && (modelName || role === "user")) {
      const label = role === "user" ? "You" : modelName;
      const words = wordCount(data.metadata?.preview || data.label || "");
      // Counter-scale so the chip holds a readable size as the canvas shrinks,
      // capped so it can never overlap the next column.
      const boost = Math.min(1 / Math.max(zoom, 0.08), LOD_MAX_BOOST);
      // Far out there is no room for both lines; the name is what matters.
      const showMeta = zoom >= 0.42;

      return (
        <div
          style={{
            width: LOD_CHIP_WIDTH,
            transform: `scale(${boost})`,
            transformOrigin: "center",
          }}
          title={role === "user" ? "User message" : modelId}
        >
          <Handle
            type="target"
            position={Position.Top}
            style={{ visibility: "hidden" }}
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 11,
              padding: "13px 14px",
              borderRadius: 14,
              background: data.styling?.background,
              boxShadow: data.styling?.boxShadow,
              outline: `1px solid ${accent || (isDark ? "rgba(255,255,255,0.14)" : "rgba(0,0,0,0.12)")}`,
              outlineOffset: -1,
            }}
          >
            <div
              style={{
                width: 4,
                height: showMeta ? 30 : 22,
                borderRadius: 3,
                flexShrink: 0,
                background: accent || (isDark ? "#60a5fa" : "#2563eb"),
              }}
            />
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontFamily: "Inter, var(--font-geist-sans), sans-serif",
                  fontWeight: 700,
                  // Sized so the longest registered name ("Claude Sonnet 4.6")
                  // fits the chip without clipping.
                  fontSize: 17,
                  letterSpacing: "-0.01em",
                  lineHeight: 1.15,
                  color: accent || data.styling?.color,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {label}
              </div>
              {showMeta && words > 0 && (
                <div
                  style={{
                    fontSize: 12,
                    lineHeight: 1.3,
                    opacity: 0.65,
                    color: data.styling?.color,
                    whiteSpace: "nowrap",
                  }}
                >
                  {words} words
                </div>
              )}
            </div>
          </div>
          <Handle
            type="source"
            position={Position.Bottom}
            style={{ visibility: "hidden" }}
          />
        </div>
      );
    }

    return (
      <div
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        style={{
          position: "relative",
          background:
            data.styling?.background ||
            (isDark ? "rgba(30, 41, 59, 1)" : "rgba(255, 255, 255, 1)"),
          border:
            data.styling?.border ||
            `1px solid ${isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"}`,
          color: data.styling?.color || (isDark ? "#fff" : "#000"),
          borderRadius: data.styling?.borderRadius || "16px",
          padding: data.styling?.padding || "12px 14px",
          fontSize: data.styling?.fontSize || "13px",
          fontFamily: "Inter, var(--font-geist-sans), sans-serif",
          lineHeight: data.styling?.lineHeight || "1.5",
          width: data.styling?.width || 240,
          boxShadow:
            data.styling?.boxShadow || "0 10px 30px -10px rgba(0, 0, 0, 0.2)",
          wordWrap: "break-word",
          overflow: "visible",
          transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
          transform: isHovered ? "translateY(-2px)" : "none",
        }}
      >
        <Handle
          type="target"
          position={Position.Top}
          style={{ visibility: "hidden" }}
        />
        <Handle
          type="source"
          position={Position.Bottom}
          style={{ visibility: "hidden" }}
        />

        {/* Model/Role Badge */}
        {(modelName || role === "user") && (
          <Box
            sx={{
              position: "absolute",
              top: -10,
              left: 12,
              px: 1,
              py: 0.25,
              borderRadius: "4px",
              bgcolor:
                role === "user"
                  ? isDark
                    ? "#1e3a8a"
                    : "#dbeafe"
                  : isDark
                    ? "#1e293b"
                    : "#f8fafc",
              border: "1px solid",
              borderColor:
                role === "user" ? (isDark ? "#3b82f6" : "#bfdbfe") : "divider",
              fontSize: "0.6rem",
              fontWeight: 700,
              color:
                role === "user"
                  ? isDark
                    ? "#93c5fd"
                    : "#1e40af"
                  : "text.secondary",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              zIndex: 10,
              boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
              maxWidth: 190,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={role === "user" ? "User message" : modelId}
          >
            {role === "user" ? "User" : modelName}
          </Box>
        )}

        {/* Reasoning Indicator */}
        {hasThoughts && (
          <Box
            sx={{
              position: "absolute",
              bottom: -10,
              right: 12,
              width: 20,
              height: 20,
              borderRadius: "50%",
              bgcolor: "#a78bfa",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "white",
              boxShadow: "0 2px 8px rgba(139, 92, 246, 0.4)",
              zIndex: 10,
            }}
            title="Reasoning available"
          >
            <Brain size={12} />
          </Box>
        )}

        {/* Delete Button Container */}
        {isHovered && data.onDelete && (
          <div
            style={{
              position: "absolute",
              top: "-8px",
              right: "-8px",
              zIndex: 200,
            }}
          >
            <button
              onMouseDown={(e) => {
                e.stopPropagation();
              }}
              onClick={(e) => {
                e.stopPropagation();
                if (data.onDelete) data.onDelete(id);
              }}
              style={{
                background: "#ef4444",
                border: "none",
                borderRadius: "50%",
                width: "24px",
                height: "24px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "white",
                boxShadow: "0 2px 8px rgba(239, 68, 68, 0.4)",
                transition: "all 0.2s",
              }}
              title="Delete Node and its Children"
            >
              <Trash2 size={12} />
            </button>
          </div>
        )}

        {/* Selecting a node expands it into a longer excerpt — the 40-char
            label alone made the debate tree unreadable. */}
        <Typography
          variant="body2"
          sx={{
            fontSize: "inherit",
            fontWeight: 500,
            lineHeight: "inherit",
            color: "inherit",
            opacity: 1,
            display: "-webkit-box",
            WebkitLineClamp: selected ? 10 : 3,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "pre-wrap",
          }}
        >
          {selected && data.metadata?.preview
            ? data.metadata.preview
            : data.label}
        </Typography>
      </div>
    );
  },
  (prevProps, nextProps) => {
    // Styling and metadata must take part in the comparison: they carry the
    // theme colours and the model badge. Leaving them out meant a theme swap
    // repainted the canvas chrome but not the nodes.
    const a = prevProps.data;
    const b = nextProps.data;
    return (
      prevProps.id === nextProps.id &&
      prevProps.selected === nextProps.selected &&
      a.label === b.label &&
      a.onDelete === b.onDelete &&
      a.styling === b.styling &&
      a.metadata === b.metadata
    );
  },
);
CustomTreeNode.displayName = "CustomTreeNode";

export default CustomTreeNode;
