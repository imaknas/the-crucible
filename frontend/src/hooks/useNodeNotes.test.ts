import { act, renderHook } from "@testing-library/react";
import * as api from "@/lib/api";
import { useNodeNotes } from "./useNodeNotes";

jest.mock("@/lib/api", () => ({
  labelNode: jest.fn(),
  summarizeSubtree: jest.fn(),
  clearSubtreeSummary: jest.fn(),
}));
const mocked = api as jest.Mocked<typeof api>;

function setup() {
  const refresh = jest.fn();
  const pushToast = jest.fn();
  const collapse = jest.fn();
  const hook = renderHook(() => useNodeNotes({ threadId: "t1", refresh, pushToast, summarizer: "luna", collapse }));
  return { ...hook, refresh, pushToast, collapse };
}

beforeEach(() => jest.resetAllMocks());

describe("useNodeNotes", () => {
  it("names and bookmarks a node, then reloads the tree", async () => {
    mocked.labelNode.mockResolvedValue({ name: "x", bookmarked: true });
    const { result, refresh } = setup();
    await act(() => result.current.rename("n1", "Plan A"));
    await act(() => result.current.setBookmark("n1", true));
    expect(mocked.labelNode).toHaveBeenNthCalledWith(1, "t1", "n1", { name: "Plan A" });
    expect(mocked.labelNode).toHaveBeenNthCalledWith(2, "t1", "n1", { bookmarked: true });
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("summarizes with the chosen summarizer and folds the branch under its summary", async () => {
    mocked.summarizeSubtree.mockResolvedValue();
    const { result, collapse, refresh } = setup();
    await act(() => result.current.summarize("n1"));
    expect(mocked.summarizeSubtree).toHaveBeenCalledWith("t1", "n1", "luna");
    expect(collapse).toHaveBeenCalledWith("n1", true);
    expect(refresh).toHaveBeenCalled();
    expect(result.current.summarizing).toEqual([]);
  });

  it("says why a summary failed and folds nothing", async () => {
    mocked.summarizeSubtree.mockRejectedValue(new Error("no key"));
    const { result, collapse, pushToast } = setup();
    await act(() => result.current.summarize("n1"));
    expect(collapse).not.toHaveBeenCalled();
    expect(pushToast).toHaveBeenCalledWith(expect.any(String), "error");
  });
});
