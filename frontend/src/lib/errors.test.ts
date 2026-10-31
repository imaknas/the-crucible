import { ApiError, ensureOk, errorMessage } from "./errors";

const response = (status: number, body: unknown) =>
  ({ ok: status < 400, status, json: async () => body }) as unknown as Response;

describe("ensureOk", () => {
  it("passes a successful response", async () => {
    await expect(ensureOk(response(200, {}), "x")).resolves.toBeUndefined();
  });

  it("throws the backend's detail", async () => {
    await expect(ensureOk(response(404, { detail: "No such thread" }), "Failed")).rejects.toEqual(
      new ApiError("No such thread", 404),
    );
  });

  it("falls back to the caller's message and the status", async () => {
    const res = { ok: false, status: 500, json: async () => Promise.reject(new Error("not json")) } as unknown as Response;
    await expect(ensureOk(res, "Failed to rename")).rejects.toThrow("Failed to rename (HTTP 500)");
  });
});

describe("errorMessage", () => {
  it("prefers an ApiError's explanation", () => {
    expect(errorMessage(new ApiError("Too big", 413), "Upload failed")).toBe("Too big");
  });
  it("names an unreachable backend", () => {
    expect(errorMessage(new TypeError("Failed to fetch"), "Upload failed")).toBe("Upload failed: the backend is unreachable.");
  });
  it("otherwise uses the fallback", () => {
    expect(errorMessage(new Error("x"), "Upload failed")).toBe("Upload failed");
  });
});
