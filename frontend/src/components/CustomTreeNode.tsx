import React, { useState } from "react";
import { Handle, Position, NodeProps } from "reactflow";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { Trash2 } from "lucide-react";
import { useTheme } from "@mui/material/styles";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  vscDarkPlus,
  vs,
} from "react-syntax-highlighter/dist/esm/styles/prism";

export type CustomNodeData = {
  label: string;
  onDelete?: (nodeId: string) => void;
  styling?: any;
};

const CustomTreeNode = React.memo(
  ({ id, data, selected }: NodeProps<CustomNodeData>) => {
    const isDark = useTheme().palette.mode === "dark";
    const [isHovered, setIsHovered] = useState(false);

    // Preprocess LaTeX delimiters that models often use but standard remark-math might miss
    const processedLabel = (data.label || "")
      .replace(/\\\[/g, "$$")
      .replace(/\\\]/g, "$$")
      .replace(/\\\(/g, "$")
      .replace(/\\\)/g, "$");

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
          borderRadius: data.styling?.borderRadius || "14px",
          padding: data.styling?.padding || "14px",
          fontSize: data.styling?.fontSize || "14px",
          fontFamily: "var(--font-geist-sans), sans-serif",
          lineHeight: data.styling?.lineHeight || "1.4",
          width: data.styling?.width || 250,
          boxShadow:
            data.styling?.boxShadow || "0 4px 20px -8px rgba(0, 0, 0, 0.15)",
          wordWrap: "break-word",
          overflow: "hidden",
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

        {/* Delete Button Container */}
        {isHovered && data.onDelete && (
          <div
            style={{
              position: "absolute",
              top: "6px",
              right: "6px",
              zIndex: 200, // Higher than handles and content
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
                background: "rgba(239, 68, 68, 0.2)",
                border: "none",
                borderRadius: "6px",
                padding: "6px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#ef4444",
                transition: "all 0.2s",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "rgba(239, 68, 68, 0.3)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "rgba(239, 68, 68, 0.2)")
              }
              title="Delete Node and its Children"
            >
              <Trash2 size={16} />
            </button>
          </div>
        )}

        {/* Markdown Content */}
        <div
          style={{
            fontSize: "inherit",
            pointerEvents: "none",
          }}
          className="prose dark:prose-invert prose-sm max-w-none"
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex]}
            components={{
              p: ({ node, ...props }) => (
                <p style={{ margin: "0.25em 0" }} {...props} />
              ),
              pre: ({ children }) => (
                <div
                  style={{
                    margin: "0.5em 0",
                    borderRadius: "8px",
                    overflow: "hidden",
                  }}
                >
                  {children}
                </div>
              ),
              code: ({ node, inline, className, children, ...props }: any) => {
                const match = /language-(\w+)/.exec(className || "");
                return !inline && match ? (
                  <SyntaxHighlighter
                    style={isDark ? vscDarkPlus : vs}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{
                      margin: 0,
                      padding: "12px",
                      fontSize: "0.85em",
                      background: isDark
                        ? "rgba(0,0,0,0.3)"
                        : "rgba(0,0,0,0.03)",
                    }}
                    {...props}
                  >
                    {String(children).replace(/\n$/, "")}
                  </SyntaxHighlighter>
                ) : (
                  <code
                    style={{
                      background: "rgba(127,127,127,0.2)",
                      padding: "2px 4px",
                      borderRadius: "4px",
                      fontSize: "0.9em",
                    }}
                    className={className}
                    {...props}
                  >
                    {children}
                  </code>
                );
              },
            }}
          >
            {processedLabel}
          </ReactMarkdown>
        </div>
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

export default CustomTreeNode;
