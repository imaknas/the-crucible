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
    mocked.summarizeSubtree.mockResolvedValue({
      calls: 1, kinds: ["branch summary"], input_tokens: 1200, output_tokens: 80,
      reasoning_tokens: 0, cached_input_tokens: 0, cost_usd: 0.0004, unpriced: 0,
    });
    const { result, collapse, refresh, pushToast } = setup();
    await act(() => result.current.summarize("n1"));
    expect(mocked.summarizeSubtree).toHaveBeenCalledWith("t1", "n1", "luna");
    expect(collapse).toHaveBeenCalledWith("n1", true);
    expect(refresh).toHaveBeenCalled();
    expect(result.current.summarizing).toEqual([]);
    // The call isn't on the tree, so its cost is said once.
    expect(pushToast).toHaveBeenCalledWith("Branch summarized · 1 call · 1,200 in / 80 out · $0.0004", "success");
  });

  it("says why a summary failed and folds nothing", async () => {
    mocked.summarizeSubtree.mockRejectedValue(new Error("no key"));
    const { result, collapse, pushToast } = setup();
    await act(() => result.current.summarize("n1"));
    expect(collapse).not.toHaveBeenCalled();
    expect(pushToast).toHaveBeenCalledWith(expect.any(String), "error");
  });
});
