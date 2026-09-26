import { renderHook, act } from "@testing-library/react";
import { useConfirm } from "./useConfirm";

describe("useConfirm", () => {
  it("resolves with the user's answer and clears the request", async () => {
    const { result } = renderHook(() => useConfirm());
    let answer: Promise<boolean> = Promise.resolve(false);
    act(() => {
      answer = result.current.confirm("Delete", "Sure?");
    });
    expect(result.current.request).toMatchObject({ title: "Delete", message: "Sure?" });

    act(() => result.current.answer(true));
    await expect(answer).resolves.toBe(true);
    expect(result.current.request).toBeNull();
  });
});
