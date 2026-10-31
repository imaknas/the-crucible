import type { DebateTranscript } from "./types";
import {
  EMPTY_TRANSCRIPT,
  afterDebateRecord,
  debateControls,
  questionMessage,
  sessionRowStatus,
  earlyStopStatus,
  restoredDebateStatus,
  peerLegend,
  roundLabel,
  transcriptReducer,
  type Transcript,
  type TranscriptAction, debateCallEstimate, debateReplyFor, debateReplyTitle, transcriptIncomplete, leaveWarning, sessionAge, transcriptMessages } from "./debateTranscript";

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
      continue: false, inject: true, redirect: true, pause: true, resume: false, synthesize: false, stopOnClose: true,
    });
    expect(debateControls("pausing", true)).toMatchObject({ inject: true, pause: false, resume: false, synthesize: false, stopOnClose: true });
    // A paused debate still takes injected messages; they join the next round.
    expect(debateControls("paused", true)).toMatchObject({ inject: true, resume: true, synthesize: true, stopOnClose: true });
    expect(debateControls("interrupted", true)).toMatchObject({ continue: true, inject: false, synthesize: true, stopOnClose: false });
    expect(debateControls("completed", true).continue).toBe(true);
    expect(debateControls("paused", true).continue).toBe(false);
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

describe("peerLegend", () => {
  it("maps each participant label to its model, in label order", () => {
    const lanes = [
      { model_id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5", peer_label: "Participant B", lane_index: 0, color: "#f59e0b" },
      { model_id: "gpt-6.1-sol", label: "GPT-6.1 Sol", peer_label: "Participant A", lane_index: 1, color: "#10b981" },
    ];
    expect(peerLegend(lanes).map((e) => `${e.label}=${e.name}`)).toEqual([
      "Participant A=GPT-6.1 Sol",
      "Participant B=Claude Sonnet 5.5",
    ]);
  });

  it("is empty when the models saw each other's names", () => {
    expect(peerLegend([{ model_id: "gpt-6.1-sol", peer_label: null, lane_index: 0, color: "#000" }])).toEqual([]);
    expect(peerLegend(undefined)).toEqual([]);
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

describe("afterDebateRecord", () => {
  const msg = (id: string, role: "user" | "assistant", kind?: string) =>
    ({ id, role, content: id, type: role === "user" ? "human" : "ai", kind }) as any;

  it("drops the debate's question and record, which the transcript already shows", () => {
    const thread = [msg("q", "user"), msg("record", "assistant", "debate"), msg("ask", "user"), msg("reply", "assistant")];
    expect(afterDebateRecord(thread).map((m) => m.id)).toEqual(["ask", "reply"]);
  });

  it("keeps everything when the thread holds no record", () => {
    const thread = [msg("ask", "user"), msg("reply", "assistant")];
    expect(afterDebateRecord(thread)).toEqual(thread);
  });
});

describe("transcriptMessages", () => {
  const transcript: DebateTranscript = {
    question: "Is a hot dog a sandwich?",
    rounds: [
      { round: 0, question: "Is a hot dog a sandwich?", responses: { a: "Yes", b: "No" } },
      // b failed round 1: its slot says why; its round-2 answer stays in round 2.
      { round: 1, question: "Is a hot dog a sandwich?", responses: { a: "Still yes" }, errors: { b: "timed out" } },
      { round: 2, question: "Is a taco a sandwich?", responses: { b: "No", a: "Maybe" } },
    ],
    synthesis: { model: "a", content: "The map" },
    injected: [{ round: 1, message: "Consider bread" }],
  };

  it("lays the stored debate out round by round, aligned", () => {
    const out = transcriptMessages(transcript, ["a", "b"]);
    expect(out.map((m) => [m.type, m.model ?? null, m.content])).toEqual([
      ["human", null, "Is a hot dog a sandwich?"],
      ["round_header", null, "Round 1 · independent answers"],
      ["ai", "a", "Yes"],
      ["ai", "b", "No"],
      ["inject", null, "Consider bread"],
      ["round_header", null, "Round 2"],
      ["ai", "a", "Still yes"],
      ["ai", "b", "_(no response: timed out)_"],
      ["redirect", null, "Is a taco a sandwich?"],
      ["round_header", null, "Round 3"],
      ["ai", "a", "Maybe"],
      ["ai", "b", "No"],
      ["synthesis", "a", "The map"],
    ]);
  });

  it("keeps ids unique", () => {
    const ids = transcriptMessages(transcript, ["a", "b"]).map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("sessionAge", () => {
  const now = Date.parse("2026-10-31T12:00:00Z");
  it("reads SQLite's zone-less UTC timestamps", () => {
    expect(sessionAge("2026-10-31 11:55:00", now)).toBe("5 min ago");
    expect(sessionAge("2026-10-31 09:00:00", now)).toBe("3 h ago");
    expect(sessionAge("2026-10-31 11:59:50", now)).toBe("just now");
  });
  it("says nothing for a missing or unreadable time", () => {
    expect(sessionAge(null, now)).toBeNull();
    expect(sessionAge("yesterday", now)).toBeNull();
  });
});

describe("leaveWarning", () => {
  it("warns only when leaving would stop a debate this tab is driving", () => {
    expect(leaveWarning("running", true)).toMatch(/stops it/);
    expect(leaveWarning("paused", true)).toMatch(/holds only while this tab/);
    expect(leaveWarning("running", false)).toBeNull();
    expect(leaveWarning("completed", true)).toBeNull();
  });
});

describe("debateCallEstimate", () => {
  it("counts every answer, judge call and the synthesis", () => {
    expect(debateCallEstimate({ rounds: 3, participants: 2, judge: false, synthesize: false })).toEqual({
      calls: 6,
      breakdown: "3 rounds × 2 models",
    });
    expect(debateCallEstimate({ rounds: 2, participants: 3, judge: true, synthesize: true })).toEqual({
      calls: 9,
      breakdown: "2 rounds × 3 models + 2 judge calls + 1 synthesis",
    });
  });
});

describe("transcriptIncomplete", () => {
  const t = (n: number) => ({ question: "Q", rounds: Array.from({ length: n }, (_, round) => ({ round, question: "Q", responses: {} })), synthesis: null });
  it("flags a transcript missing rounds the session finished", () => {
    expect(transcriptIncomplete(t(0), { current_round: 1 })).toBe(true);
    expect(transcriptIncomplete(t(1), { current_round: 1 })).toBe(false);
    expect(transcriptIncomplete(t(2), { current_round: 1 })).toBe(false);
    expect(transcriptIncomplete(t(0), { current_round: 0 })).toBe(false);
  });
});

describe("reading a debate node in full", () => {
  const node = (id: string, metadata: object, type?: string) =>
    ({ id, data: { label: id }, position: { x: 0, y: 0 }, metadata, ...(type ? { type } : {}) }) as any;

  it("live replies carry their round and, once ended, their node's checkpoint", () => {
    const t = run([
      ev({ type: "stream_start", model: "a", round: 2 }),
      ev({ type: "stream_end", model: "a", content: "full text", checkpoint_id: "cp9" }),
    ]);
    expect(t.messages[0]).toMatchObject({ round: 2, checkpoint_id: "cp9", content: "full text" });
  });

  it("finds a reply by the node's checkpoint, else by model and round", () => {
    const live = run([
      ev({ type: "stream_start", model: "a", round: 0 }),
      ev({ type: "stream_end", model: "a", content: "live", checkpoint_id: "cp1" }),
    ]).messages;
    expect(debateReplyFor(node("a::cp1", { active_peer: "a", round_num: 0 }), live)?.content).toBe("live");

    const restored = transcriptMessages(
      {
        question: "Q",
        rounds: [
          { round: 0, question: "Q", responses: { a: "zero" }, errors: {} },
          { round: 2, question: "Q", responses: { a: "two" }, errors: {} },
        ],
        synthesis: { model: "b", content: "map" },
      } as unknown as DebateTranscript,
      ["a"],
    );
    expect(debateReplyFor(node("a::cpX", { active_peer: "a", round_num: 2 }), restored)?.content).toBe("two");
    expect(debateReplyFor(node("synthesis::cp", { role: "synthesis" }, "synthesis"), restored)?.content).toBe("map");
    expect(debateReplyFor(node("a::pending-r3", { active_peer: "a", round_num: 3, pending: true }), restored)).toBeNull();
    expect(debateReplyFor(node("a::cpY", { active_peer: "a", round_num: 1 }), restored)).toBeNull();
  });

  it("titles the reply with its model, participant label and round", () => {
    const lanes = [{ model_id: "a", label: "Model A", peer_label: "Participant B", lane_index: 0, color: "#000" }];
    expect(debateReplyTitle(node("a::cp", { active_peer: "a", model_name: "Model A", round_num: 0 }), lanes)).toBe(
      "Model A (Participant B) · Round 1 · independent answers",
    );
    expect(debateReplyTitle(node("s", { role: "synthesis", model_name: "Model C" }, "synthesis"), lanes)).toBe(
      "Argument map · Model C",
    );
  });
});
