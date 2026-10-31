import { lastUserText, markStopped, reconcileMessages } from "./messages";
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
});
