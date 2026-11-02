import React from "react";
import { render, screen, within } from "@testing-library/react";
import TurnCards from "./TurnCards";
import { MessageBubble } from "./MessageBubble";
import type { TurnCard } from "@/lib/turns";
import type { ReplyMetrics } from "@/lib/metrics";

jest.mock("react-markdown", () => {
  const MockMarkdown = ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  );
  MockMarkdown.displayName = "MockMarkdown";
  return MockMarkdown;
});
jest.mock("remark-gfm", () => ({}));
jest.mock("remark-math", () => ({}));
jest.mock("rehype-katex", () => ({}));
jest.mock("react-syntax-highlighter", () => ({
  Prism: ({ children }: { children: React.ReactNode }) => <pre>{children}</pre>,
}));
jest.mock("react-syntax-highlighter/dist/esm/styles/prism", () => ({
  vscDarkPlus: {},
  vs: {},
}));
jest.mock("lucide-react", () => {
  const Icon = () => <svg />;
  return new Proxy(
    {},
    { get: (_, name) => (name === "__esModule" ? false : Icon) },
  );
});

const metrics = (over: Partial<ReplyMetrics> = {}): ReplyMetrics => ({
  ttft_ms: 1200,
  total_ms: 8400,
  input_tokens: 1234,
  output_tokens: 567,
  reasoning_tokens: 120,
  cached_input_tokens: 0,
  cost_usd: 0.0123,
  ...over,
});

const card = (model: string, over: Partial<TurnCard> = {}): TurnCard => ({
  key: model,
  model,
  id: `n_${model}`,
  label: `Model ${model.toUpperCase()}`,
  color: null,
  text: `${model} says`,
  full: true,
  streaming: false,
  stopped: false,
  error: null,
  shown: false,
  metrics: metrics(),
  ...over,
});

const props = {
  isDark: false,
  modelLabel: (id: string) => id,
  onViewReply: jest.fn(),
  onContinueReply: jest.fn(),
};

describe("compare card metrics", () => {
  it("shows what each answer took and the turn's total", () => {
    render(
      <TurnCards
        {...props}
        cards={[
          card("a"),
          card("b", {
            metrics: metrics({
              total_ms: 9100,
              cost_usd: 0.02,
              reasoning_tokens: null,
            }),
          }),
        ]}
      />,
    );
    const a = screen.getByRole("article", { name: "Model A's answer" });
    expect(within(a).getByTestId("reply-metrics")).toHaveTextContent(
      "1.2 s to first token · 8.4 s · 1,234 in / 567 out (120 reasoning) · $0.0123",
    );
    const b = screen.getByRole("article", { name: "Model B's answer" });
    expect(within(b).getByTestId("reply-metrics")).toHaveTextContent(
      "9.1 s · 1,234 in / 567 out · $0.0200",
    );
    expect(screen.getByTestId("turn-metrics")).toHaveTextContent(
      "Total · slowest 9.1 s · 2,468 in / 1,134 out (120 reasoning) · $0.0323",
    );
  });

  it("says a price is unknown, on the card and in the total", () => {
    render(
      <TurnCards
        {...props}
        cards={[card("a"), card("b", { metrics: metrics({ cost_usd: null }) })]}
      />,
    );
    const b = screen.getByRole("article", { name: "Model B's answer" });
    expect(within(b).getByTestId("reply-metrics")).toHaveTextContent(
      /price unknown$/,
    );
    expect(screen.getByTestId("turn-metrics")).toHaveTextContent(
      /\$0\.0123 \+ 1 price unknown$/,
    );
  });

  it("shows nothing for older answers that recorded no metrics", () => {
    render(
      <TurnCards
        {...props}
        cards={[card("a", { metrics: null }), card("b", { metrics: null })]}
      />,
    );
    expect(screen.queryByTestId("reply-metrics")).toBeNull();
    expect(screen.queryByTestId("turn-metrics")).toBeNull();
  });

  it("waits for every answer before showing a total, and for a reply to finish before its own", () => {
    render(
      <TurnCards
        {...props}
        cards={[
          card("a"),
          card("b", { streaming: true, metrics: null, text: "partial" }),
        ]}
      />,
    );
    expect(screen.getAllByTestId("reply-metrics")).toHaveLength(1);
    expect(screen.queryByTestId("turn-metrics")).toBeNull();
  });

  it("is reachable from the keyboard and readable at the 11px floor", () => {
    render(<TurnCards {...props} cards={[card("a"), card("b")]} />);
    const line = screen.getAllByTestId("reply-metrics")[0];
    expect(line).toHaveAttribute("tabindex", "0");
    expect(line).toHaveStyle({
      fontSize: "0.6875rem",
      fontVariantNumeric: "tabular-nums",
    });
  });
});

describe("reply bubble metrics", () => {
  const bubble = (over: object = {}) =>
    render(
      <MessageBubble
        msg={{
          id: "r",
          role: "assistant",
          content: "Hi",
          model: "gpt-x",
          model_name: "GPT X",
          metrics: metrics(),
          ...over,
        }}
        isUser={false}
        isDark={false}
        onMount={() => {}}
        index={0}
      />,
    );

  it("shows a reply's metrics under it", () => {
    bubble();
    expect(screen.getByTestId("reply-metrics")).toHaveTextContent(
      "8.4 s · 1,234 in / 567 out",
    );
  });

  it("shows none while streaming or for a reply without them", () => {
    bubble({ streaming: true });
    expect(screen.queryByTestId("reply-metrics")).toBeNull();
  });

  it("shows none for an older reply", () => {
    bubble({ metrics: undefined });
    expect(screen.queryByTestId("reply-metrics")).toBeNull();
  });
});
