import {
  EMPTY_TRANSCRIPT,
  debateControls,
  questionMessage,
  sessionRowStatus,
  earlyStopStatus,
  restoredDebateStatus,
  roundLabel,
  transcriptReducer,
  type Transcript,
  type TranscriptAction,
} from "./debateTranscript";

const run = (actions: TranscriptAction[], start: Transcript = EMPTY_TRANSCRIPT) =>
  actions.reduce(transcriptReducer, start);

let clock = 0;
const ev = (event: object): TranscriptAction =>
  ({ kind: "event", event, now: ++clock }) as TranscriptAction;
const tokens = (chunks: Record<string, string>): TranscriptAction => ({ kind: "tokens", chunks });

describe("transcriptReducer", () => {
  it("streams interleaved models into their own bubbles", () => {
    const t = run([
      ev({ type: "debate_round_start", round: 0 }),
      ev({ type: "stream_start", model: "a", round: 0 }),
      ev({ type: "stream_start", model: "b", round: 0 }),
      tokens({ a: "Hel", b: "Wor" }),
      tokens({ a: "lo", b: "ld" }),
    ]);
    expect(t.messages.map((m) => m.content)).toEqual(["Round 1 · independent answers", "Hello", "World"]);
    expect(t.messages.filter((m) => m.streaming)).toHaveLength(2);
  });

  it("marks round 1 as the independent answers and numbers later rounds plainly", () => {
    const t = run([
      ev({ type: "debate_round_start", round: 0 }),
      ev({ type: "debate_round_start", round: 1 }),
      ev({ type: "debate_round_start", round: 2 }),
    ]);
    expect(t.messages.map((m) => [m.type, m.content])).toEqual([
      ["round_header", "Round 1 · independent answers"],
      ["round_header", "Round 2"],
      ["round_header", "Round 3"],
    ]);
  });

  it("stream_end sets the final content and stops streaming", () => {
    const t = run([
      ev({ type: "stream_start", model: "a" }),
      tokens({ a: "partial" }),
      ev({ type: "stream_end", model: "a", content: "full answer" }),
    ]);
    expect(t.messages[0]).toMatchObject({ content: "full answer", streaming: false });
    expect(t.streaming).toEqual({});
  });

  it("drops tokens that arrive after their stream closed", () => {
    const t = run([
      ev({ type: "stream_start", model: "a" }),
      ev({ type: "stream_end", model: "a", content: "done" }),
      tokens({ a: " late" }),
    ]);
    expect(t.messages[0].content).toBe("done");
  });

  it("an error closes the failing model's bubble, keeping partial text", () => {
    const t = run([
      ev({ type: "stream_start", model: "a" }),
      ev({ type: "stream_start", model: "b" }),
      tokens({ a: "half" }),
      ev({ type: "error", model: "a", message: "timed out" }),
      ev({ type: "error", model: "b", message: "rate limited" }),
    ]);
    expect(t.messages[0]).toMatchObject({ streaming: false, content: "half\n\n_(stopped: timed out)_" });
    expect(t.messages[1]).toMatchObject({ streaming: false, content: "_(no response: rate limited)_" });
  });

  it("an error without a model leaves the transcript alone", () => {
    const start = run([ev({ type: "stream_start", model: "a" })]);
    expect(transcriptReducer(start, ev({ type: "error", message: "x" }))).toBe(start);
  });

  it("synthesis streams under the synthesizer's id and closes on synthesis_end", () => {
    const t = run([
      ev({ type: "stream_start", model: "a" }),
      ev({ type: "stream_end", model: "a", content: "answer" }),
      ev({ type: "debate_synthesis_start", model: "a" }),
      tokens({ a: "synth" }),
      ev({ type: "debate_synthesis_end", model: "a", content: "final synthesis" }),
    ]);
    expect(t.messages[1]).toMatchObject({ type: "synthesis", content: "final synthesis", streaming: false });
    expect(t.messages[0].content).toBe("answer");
    expect(t.streaming).toEqual({});
  });

  it("records inject and redirect entries and resets", () => {
    const t = run([
      { kind: "user", entry: "inject", content: "consider cost", now: 1 },
      { kind: "user", entry: "redirect", content: "new topic", now: 2 },
    ]);
    expect(t.messages.map((m) => [m.type, m.role, m.content])).toEqual([
      ["inject", "user", "consider cost"],
      ["redirect", "user", "new topic"],
    ]);
    expect(transcriptReducer(t, { kind: "reset" })).toEqual(EMPTY_TRANSCRIPT);
  });
});

describe("debate status helpers", () => {
  it("a session loaded from the server is never running here", () => {
    expect(restoredDebateStatus("running")).toBe("interrupted");
    expect(restoredDebateStatus("paused")).toBe("interrupted");
    expect(restoredDebateStatus("completed")).toBe("completed");
  });

  it("calls an early stop agreement only when a judge decided it", () => {
    expect(earlyStopStatus("judge")).toBe("converged");
    expect(earlyStopStatus("stability")).toBe("stable");
    expect(earlyStopStatus(undefined)).toBe("stable");
  });

  it("offers controls that match the status", () => {
    expect(debateControls("running", true)).toEqual({
      inject: true, redirect: true, pause: true, resume: false, synthesize: false, stopOnClose: true,
    });
    expect(debateControls("pausing", true)).toMatchObject({ inject: true, pause: false, resume: false, synthesize: false, stopOnClose: true });
    // A paused debate still takes injected messages; they join the next round.
    expect(debateControls("paused", true)).toMatchObject({ inject: true, resume: true, synthesize: true, stopOnClose: true });
    expect(debateControls("interrupted", true)).toMatchObject({ inject: false, synthesize: true, stopOnClose: false });
    expect(debateControls("completed", false).synthesize).toBe(false);
  });
});

describe("sessionRowStatus", () => {
  it("shows the live status of the debate this tab is driving", () => {
    expect(sessionRowStatus("running", "paused")).toBe("paused");
    expect(sessionRowStatus("running", "pausing")).toBe("pausing");
    expect(sessionRowStatus("running", "stable")).toBe("completed");
  });
  it("falls back to the server's record for other sessions", () => {
    expect(sessionRowStatus("interrupted", null)).toBe("interrupted");
  });
});

describe("questionMessage", () => {
  it("is a user bubble with the question", () => {
    expect(questionMessage("Tabs or spaces?")).toMatchObject({ role: "user", content: "Tabs or spaces?" });
  });
});

describe("roundLabel", () => {
  it("names round 1 as the independent answers, in full and in the tree's short form", () => {
    expect(roundLabel(0)).toBe("Round 1 · independent answers");
    expect(roundLabel(0, "short")).toBe("Round 1 · independent");
    expect(roundLabel(3)).toBe("Round 4");
    expect(roundLabel(3, "short")).toBe("Round 4");
  });
});
