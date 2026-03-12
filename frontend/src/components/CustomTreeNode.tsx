import React, { useState } from "react";
import { Handle, Position, NodeProps } from "reactflow";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { Trash2, Brain } from "lucide-react";
import { useTheme, Box, Typography } from "@mui/material";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  vscDarkPlus,
  vs,
} from "react-syntax-highlighter/dist/esm/styles/prism";

export type CustomNodeData = {
  label: string;
  onDelete?: (nodeId: string) => void;
  styling?: any;
  metadata?: {
    role?: string;
    active_peer?: string;
    thesis_preview?: string;
    has_thoughts?: boolean;
  };
};

const CustomTreeNode = React.memo(
  ({ id, data, selected }: NodeProps<CustomNodeData>) => {
    const isDark = useTheme().palette.mode === "dark";
    const [isHovered, setIsHovered] = useState(false);

    const hasThoughts = data.metadata?.has_thoughts;
    const modelName = data.metadata?.active_peer || "";
    const role = data.metadata?.role || "";

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
            }}
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

        {/* Simplified Content Rendering */}
        <Typography
          variant="body2"
          sx={{
            fontSize: "inherit",
            fontWeight: 500,
            lineHeight: "inherit",
            color: "inherit",
            opacity: 1,
            display: "-webkit-box",
            WebkitLineClamp: 3,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {data.label}
        </Typography>
      </div>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison to ensure we only re-render if the core content or selection state changes
    return (
      prevProps.id === nextProps.id &&
      prevProps.selected === nextProps.selected &&
      prevProps.data.label === nextProps.data.label &&
      prevProps.data.onDelete === nextProps.data.onDelete
    );
  },
);
CustomTreeNode.displayName = "CustomTreeNode";

export default CustomTreeNode;
