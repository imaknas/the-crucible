import { act, renderHook, waitFor } from "@testing-library/react";
import { sameAnswers, useAnswerReviews } from "./useAnswerReviews";
import * as api from "@/lib/api";

jest.mock("@/lib/api");
const mocked = api as jest.Mocked<typeof api>;
const review = (ids: string[]) => ({ review_key: ids.join(), thread_id: "t", checkpoint_ids: ids, question: "", answers: [], errors: {} });

describe("useAnswerReviews", () => {
  it("matches a review to its answers in any order", () => {
    expect(sameAnswers(["a", "b"], ["b", "a"])).toBe(true);
    expect(sameAnswers(["a", "b"], ["a", "c"])).toBe(false);
  });

  it("loads the thread's reviews and adds one it runs", async () => {
    mocked.listAnswerReviews.mockResolvedValue([review(["x", "y"])]);
    mocked.runAnswerReview.mockResolvedValue(review(["a", "b"]));
    const { result } = renderHook(() => useAnswerReviews("t", jest.fn()));
    await waitFor(() => expect(result.current.reviewFor(["y", "x"])).not.toBeNull());
    await act(() => result.current.run(["b", "a"]));
    expect(result.current.reviewFor(["a", "b"])?.review_key).toBe("a,b");
    expect(mocked.runAnswerReview).toHaveBeenCalledWith("t", ["b", "a"]);
  });

  it("tells the person when a review fails", async () => {
    mocked.listAnswerReviews.mockResolvedValue([]);
    mocked.runAnswerReview.mockRejectedValue(new Error("boom"));
    const toast = jest.fn();
    const { result } = renderHook(() => useAnswerReviews("t", toast));
    await act(() => result.current.run(["a", "b"]));
    expect(toast).toHaveBeenCalledWith(expect.any(String), "error");
  });
});
