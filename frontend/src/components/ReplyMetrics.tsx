import React from "react";
import { Box, Tooltip, Typography } from "@mui/material";
import { Gauge } from "lucide-react";
import {
  formatMetrics,
  formatTurnTotal,
  formatUsage,
  metricsBreakdown,
  usageBreakdown,
  type ReplyMetrics,
  type TurnMetrics,
  type UsageSummary,
} from "@/lib/metrics";
import { effortLabel } from "@/lib/effort";
import type { ReplyEffort } from "@/lib/types";

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
  effort = null,
}: {
  metrics: ReplyMetrics | null | undefined;
  /** The reasoning effort it answered at; null at the model's default. */
  effort?: ReplyEffort | null;
}) {
  const text = formatMetrics(metrics);
  const effortText = effortLabel(effort);
  if (!(metrics && text) && !effortText) return null;
  const shown = [effortText, metrics && text ? text : null].filter(Boolean).join(" · ");
  return (
    <MetricsLine
      text={shown}
      lines={[...(effort ? [`Reasoning effort: ${effort.choice} (sent as ${effort.level})`] : []), ...(metrics ? metricsBreakdown(metrics) : [])]}
      testId="reply-metrics"
    />
  );
}

/** The turn's answers together: summed tokens and cost, the slowest time. */
export function TurnMetricsLine({
  total,
  answered = null,
  asked = 0,
  align = "center",
  testId = "turn-metrics",
}: {
  total: TurnMetrics | null;
  /** How many of the `asked` models answered: a total over fewer says so. */
  answered?: number | null;
  asked?: number;
  align?: "left" | "center";
  testId?: string;
}) {
  const text = formatTurnTotal(total);
  if (!total || text === "Total") return null;
  const partial = answered !== null && answered < asked ? `${answered} of ${asked} answered · ` : "";
  return (
    <MetricsLine
      text={partial + text}
      lines={metricsBreakdown(total)}
      testId={testId}
      align={align}
    />
  );
}

/** What an operation's own calls took (peer review, a check, a branch summary). */
export function UsageLine({ usage }: { usage: UsageSummary | null | undefined }) {
  const text = formatUsage(usage);
  if (!usage || !text) return null;
  return <MetricsLine text={text} lines={usageBreakdown(usage)} testId="usage-metrics" />;
}
