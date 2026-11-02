import { lastUserText, markStopped, reconcileMessages, withResumedQuestion } from "./messages";
import type { Message } from "./types";

describe("reconcileMessages", () => {
  it("keys each message by its tree node id, so a streamed reply keeps its key", () => {
    const prev: Message[] = [{ id: "n2", role: "assistant", content: "partial", model: "m" }];
    const next: Message[] = [
      { id: "", role: "user", content: "Q", checkpoint_id: "n1" },
      { id: "", role: "assistant", content: "full", model: "m", checkpoint_id: "n2" },
    ];
    expect(reconcileMessages(prev, next).map((m) => m.id)).toEqual(["n1", "n2"]);
  });

  it("falls back to the position for payloads without ids, when the author matches", () => {
    const prev: Message[] = [
      { id: "user-1", role: "user", content: "Q" },
      { id: "streaming-a", role: "assistant", content: "A", model: "a" },
    ];
    const next = [
      { role: "user", content: "Q" },
      { role: "assistant", content: "B", model: "b" },
    ] as Message[];
    expect(reconcileMessages(prev, next).map((m) => m.id)).toEqual(["user-1", "stable-1"]);
  });
});

describe("reconcileMessages, the echoed question", () => {
  it("keeps the client id of the question echoed on send, so its bubble isn't remounted", () => {
    const prev: Message[] = [{ id: "user-123", role: "user", content: "Q" }];
    const next: Message[] = [
      { id: "", role: "user", content: "Q", checkpoint_id: "n1" },
      { id: "", role: "assistant", content: "A", checkpoint_id: "n2" },
    ];
    expect(reconcileMessages(prev, next).map((m) => m.id)).toEqual(["user-123", "n2"]);
  });
});

describe("lastUserText", () => {
  it("returns the full text of the person's last message", () => {
    const long = "A question that is much longer than the forty characters a tree label keeps, with **markdown**.";
    expect(lastUserText([{ role: "user", content: "first" }, { role: "assistant", content: "x" }, { role: "user", content: long }])).toBe(long);
    expect(lastUserText([{ role: "assistant", content: "x" }])).toBeNull();
  });
});

describe("markStopped", () => {
  it("marks streaming replies as stopped and leaves finished ones alone", () => {
    const out = markStopped([
      { id: "a", role: "assistant", content: "done" },
      { id: "b", role: "assistant", content: "half", streaming: true },
    ]);
    expect(out[0]).toEqual({ id: "a", role: "assistant", content: "done" });
    expect(out[1]).toMatchObject({ streaming: false, stopped: true, content: "half" });
  });

  it("marks only one model's reply when named", () => {
    const out = markStopped([
      { id: "a", role: "assistant", content: "x", model: "a", streaming: true },
      { id: "b", role: "assistant", content: "y", model: "b", streaming: true },
    ], "b");
    expect(out.map((m) => !!m.stopped)).toEqual([false, true]);
  });
});

describe("a turn attached to after a reload", () => {
  const path: Message[] = [
    { id: "", role: "user", content: "Q1", checkpoint_id: "n1", turn_id: "t1" },
    { id: "", role: "assistant", content: "A1", checkpoint_id: "n2", turn_id: "t1" },
  ];

  it("puts the question after the messages, once", () => {
    const once = withResumedQuestion([], "t2", "Q2");
    expect(once).toEqual([{ id: "resumed-q-t2", role: "user", content: "Q2", type: "human", turn_id: "t2" }]);
    expect(withResumedQuestion(once, "t2", "Q2")).toBe(once);
    // Not when this tab sent it, or the path already holds the turn.
    const sent: Message[] = [{ id: "user-1", role: "user", content: "Q2" }];
    expect(withResumedQuestion(sent, "t2", "Q2")).toBe(sent);
    expect(withResumedQuestion(path, "t1", "Q1")).toBe(path);
  });

  it("keeps its question and bubble through a history load that doesn't hold the turn yet", () => {
    const onScreen = [
      ...withResumedQuestion([], "t2", "Q2"),
      { id: "resumed-gpt-t2", role: "assistant", content: "so far", streaming: true, turn_id: "t2" } as Message,
    ];
    const loaded = reconcileMessages(onScreen, path);
    expect(loaded.map((m) => m.content)).toEqual(["Q1", "A1", "Q2", "so far"]);
    // Once the path holds the turn, the load's copy replaces them.
    const settled: Message[] = [...path, { id: "", role: "user", content: "Q2", checkpoint_id: "n3", turn_id: "t2" }];
    expect(reconcileMessages(loaded, settled).map((m) => m.content)).toEqual(["Q1", "A1", "Q2"]);
  });

  it("leaves ordinary loads alone", () => {
    const onScreen: Message[] = [
      { id: "user-5", role: "user", content: "Q" },
      { id: "streaming-a", role: "assistant", content: "x", streaming: true },
    ];
    expect(reconcileMessages(onScreen, path)).toHaveLength(2);
  });
});
