import { act, renderHook, waitFor } from "@testing-library/react";
import { useIssueChecks } from "./useIssueChecks";
import * as api from "@/lib/api";

jest.mock("@/lib/api");
const mocked = api as jest.Mocked<typeof api>;
const check = (id: string, problem = "p") => ({
  thread_id: "t", checkpoint_id: id, question: "", documents: [], source_truncated: false, checkers: [],
  issues: [{ number: 1, problem, raised_by: "", why: "", verdicts: [], disagree: false }], errors: {},
});

describe("useIssueChecks", () => {
  it("loads the thread's checks and replaces one it runs again", async () => {
    mocked.listIssueChecks.mockResolvedValue([check("list", "old")]);
    mocked.runIssueCheck.mockResolvedValue(check("list", "new"));
    const { result } = renderHook(() => useIssueChecks("t", jest.fn()));
    await waitFor(() => expect(result.current.checkFor("list")).not.toBeNull());
    await act(() => result.current.run("list"));
    expect(result.current.checkFor("list")?.issues[0].problem).toBe("new");
    expect(mocked.runIssueCheck).toHaveBeenCalledWith("t", "list");
    expect(result.current.busy).toBe(false);
  });

  it("tells the person when a check fails", async () => {
    mocked.listIssueChecks.mockResolvedValue([]);
    mocked.runIssueCheck.mockRejectedValue(new Error("boom"));
    const toast = jest.fn();
    const { result } = renderHook(() => useIssueChecks("t", toast));
    await act(() => result.current.run("list"));
    expect(toast).toHaveBeenCalledWith(expect.any(String), "error");
  });
});
