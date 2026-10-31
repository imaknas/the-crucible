import { act, renderHook } from "@testing-library/react";
import { useDocuments } from "./useDocuments";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/errors";

jest.mock("@/lib/api", () => ({ uploadDocument: jest.fn() }));

const file = (name: string) => new File(["x"], name, { type: "text/plain" });

describe("useDocuments", () => {
  beforeEach(() => jest.clearAllMocks());

  it("attaches an uploaded file by name, once per name", async () => {
    (api.uploadDocument as jest.Mock).mockResolvedValue({ filename: "notes.txt" });
    const onUploaded = jest.fn();
    const { result } = renderHook(() => useDocuments({ threadId: "t1", pushToast: jest.fn(), onUploaded }));
    await act(async () => {
      await result.current.attach(file("notes.txt"));
      await result.current.attach(file("notes.txt"));
    });
    expect(result.current.names).toEqual(["notes.txt"]);
    expect(onUploaded).toHaveBeenCalledWith("notes.txt");
    expect(result.current.uploading).toBeNull();
  });

  it("shows the file while it uploads", async () => {
    let finish: (v: unknown) => void = () => {};
    (api.uploadDocument as jest.Mock).mockReturnValue(new Promise((r) => (finish = r)));
    const { result } = renderHook(() => useDocuments({ threadId: "t1", pushToast: jest.fn() }));
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.attach(file("big.pdf"));
    });
    expect(result.current.uploading).toBe("big.pdf");
    await act(async () => {
      finish({ filename: "big.pdf" });
      await pending;
    });
    expect(result.current.uploading).toBeNull();
  });

  it("says why an upload failed", async () => {
    (api.uploadDocument as jest.Mock).mockRejectedValue(new ApiError("File too large (max 10 MB)", 413));
    const pushToast = jest.fn();
    const { result } = renderHook(() => useDocuments({ threadId: "t1", pushToast }));
    await act(async () => {
      await result.current.attach(file("big.pdf"));
    });
    expect(pushToast).toHaveBeenCalledWith("File too large (max 10 MB)", "error", "Upload failed");
    expect(result.current.names).toEqual([]);
  });

  it("drops the attachments when another thread opens", async () => {
    (api.uploadDocument as jest.Mock).mockResolvedValue({ filename: "a.txt" });
    const { result, rerender } = renderHook(({ threadId }) => useDocuments({ threadId, pushToast: jest.fn() }), {
      initialProps: { threadId: "t1" as string | null },
    });
    await act(async () => {
      await result.current.attach(file("a.txt"));
    });
    rerender({ threadId: "t2" });
    expect(result.current.names).toEqual([]);
  });
});
