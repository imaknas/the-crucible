import { CLIENT_HEADERS, loadDebateMessages, uploadDocument } from "./api";

describe("uploadDocument", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("sends the client header, so the browser preflights the form POST", async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ filename: "notes.txt", full_content: "hi" }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    await uploadDocument(new File(["hi"], "notes.txt", { type: "text/plain" }), "thread_1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/upload$/);
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual(CLIENT_HEADERS);
    expect(init.headers["X-Crucible-Client"]).toBe("1");
    expect(init.body).toBeInstanceOf(FormData);
  });
});

describe("loadDebateMessages", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  const session = (synthesizer_model: string | null) =>
    ({
      session_id: "debate-1",
      parent_thread_id: "t",
      participants: ["gpt-a", "claude-b"],
      thread_ids: { "gpt-a": "t::d::gpt-a", "claude-b": "t::d::claude-b", synthesis: "t::d::synthesis" },
      synthesizer_model,
    }) as any;

  function serveHistories(byThread: Record<string, any[]>) {
    global.fetch = jest.fn(async (url: string) => {
      const thread = decodeURIComponent(String(url).split("/history/")[1]);
      return { ok: true, json: async () => ({ messages: byThread[thread] ?? [] }) };
    }) as unknown as typeof fetch;
  }

  const histories = {
    "t::d::gpt-a": [
      { role: "user", content: "Q?" },
      { role: "assistant", content: "a0" },
    ],
    "t::d::claude-b": [
      { role: "user", content: "Q?" },
      { role: "assistant", content: "b0" },
    ],
    "t::d::synthesis": [
      { role: "user", content: "map it" },
      { role: "assistant", content: "the map", model: "gpt-a-2026-01-01", model_name: "GPT A" },
    ],
  };

  it("labels the restored synthesis with the session's synthesizer", async () => {
    serveHistories(histories);
    const messages = await loadDebateMessages(session("claude-b"));
    const synthesis = messages.find((m) => m.type === "synthesis")!;
    expect(synthesis.model).toBe("claude-b");
    expect(synthesis.content).toBe("the map");
  });

  it("never labels it with the thread key when the session names no synthesizer", async () => {
    serveHistories(histories);
    const synthesis = (await loadDebateMessages(session(null))).find((m) => m.type === "synthesis")!;
    expect(synthesis.model).not.toBe("synthesis");
    expect((synthesis as any).model_name).toBe("GPT A");
  });
});
