import React from "react";
import { Box, Tooltip, Typography } from "@mui/material";
import { Gauge } from "lucide-react";
import {
  formatMetrics,
  formatTurnTotal,
  metricsBreakdown,
  type ReplyMetrics,
  type TurnMetrics,
} from "@/lib/metrics";

function Breakdown({ lines }: { lines: string[] }) {
  return (
    <Box
      component="span"
      sx={{ display: "block", fontVariantNumeric: "tabular-nums" }}
    >
      {lines.map((line) => (
        <Box component="span" key={line} sx={{ display: "block" }}>
          {line}
        </Box>
      ))}
    </Box>
  );
}

interface LineProps {
  text: string;
  lines: string[];
  testId: string;
  align?: "left" | "center";
}

/**
 * The numbers on one visible line; every number, exact, in a tooltip that
 * keyboard focus opens too. The line itself carries the information, the
 * tooltip only adds precision.
 */
function MetricsLine({ text, lines, testId, align = "left" }: LineProps) {
  return (
    <Tooltip
      title={<Breakdown lines={lines} />}
      describeChild
      placement="top"
      enterDelay={300}
    >
      <Typography
        component="p"
        tabIndex={0}
        data-testid={testId}
        sx={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: align === "center" ? "center" : "flex-start",
          gap: 0.5,
          m: 0,
          fontSize: "0.6875rem",
          lineHeight: 1.5,
          fontWeight: 500,
          color: "text.secondary",
          fontVariantNumeric: "tabular-nums",
          textAlign: align,
          cursor: "help",
          width: "fit-content",
          maxWidth: "100%",
          ...(align === "center" ? { mx: "auto" } : {}),
        }}
      >
        <Gauge width={11} height={11} aria-hidden style={{ flexShrink: 0, marginTop: 3 }} />
        <Box component="span" sx={{ minWidth: 0 }}>
          {text}
        </Box>
      </Typography>
    </Tooltip>
  );
}

/** What one answer took: nothing for a reply that recorded none. */
export function ReplyMetricsLine({
  metrics,
}: {
  metrics: ReplyMetrics | null | undefined;
}) {
  const text = formatMetrics(metrics);
  if (!metrics || !text) return null;
  return (
    <MetricsLine
      text={text}
      lines={metricsBreakdown(metrics)}
      testId="reply-metrics"
    />
  );
}

/** The turn's answers together: summed tokens and cost, the slowest time. */
export function TurnMetricsLine({ total }: { total: TurnMetrics | null }) {
  const text = formatTurnTotal(total);
  if (!total || text === "Total") return null;
  return (
    <MetricsLine
      text={text}
      lines={metricsBreakdown(total)}
      testId="turn-metrics"
      align="center"
    />
  );
}
