import { CLIENT_HEADERS, uploadDocument } from "./api";

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
