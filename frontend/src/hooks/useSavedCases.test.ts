import { act, renderHook, waitFor } from "@testing-library/react";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { useSavedCases } from "./useSavedCases";

jest.mock("@/lib/api", () => ({
  saveCase: jest.fn(),
  listCases: jest.fn(),
  fetchCase: jest.fn(),
  deleteCase: jest.fn(),
  replayCase: jest.fn(),
}));
const mocked = api as jest.Mocked<typeof api>;

const saved = {
  case_id: "case-1",
  title: "Which database?",
  question: "Which database?",
  created_at: "2026-11-03 10:00:00",
  source_thread_id: "t1",
  answers: [{ model: "gpt-a", model_name: "GPT A", content: "x", metrics: null, checkpoint_id: "a1" }],
  vote: null,
  replays: [],
};

function setup(confirmAnswer = true) {
  const pushToast = jest.fn();
  const confirm = jest.fn().mockResolvedValue(confirmAnswer);
  const hook = renderHook(() => useSavedCases(pushToast, confirm));
  return { pushToast, confirm, hook };
}

beforeEach(() => {
  jest.clearAllMocks();
  mocked.listCases.mockResolvedValue([]);
  mocked.fetchCase.mockResolvedValue(saved as never);
});

it("returns the same object until something it holds changes", () => {
  const { hook } = setup();
  const first = hook.result.current;
  hook.rerender();
  expect(hook.result.current).toBe(first);
});

it("saves a turn, says so, and lists it without a refetch", async () => {
  mocked.saveCase.mockResolvedValue(saved as never);
  const { hook, pushToast } = setup();
  await act(() => hook.result.current.save("t1", "a1"));
  expect(mocked.saveCase).toHaveBeenCalledWith("t1", "a1");
  expect(pushToast).toHaveBeenCalledWith(expect.stringContaining("Which database?"), "success", "Case saved");
  expect(hook.result.current.list.map((c) => c.case_id)).toEqual(["case-1"]);
  expect(hook.result.current.saving).toBeNull();
});

it("a failed save is an error toast with the backend's reason", async () => {
  mocked.saveCase.mockRejectedValue(new ApiError("Turn x not found on thread t1.", 404));
  const { hook, pushToast } = setup();
  await act(() => hook.result.current.save("t1", "x"));
  expect(pushToast).toHaveBeenCalledWith("Turn x not found on thread t1.", "error");
});

it("opens the dialog on the list, opens a case, replays it and shows the replay with its cost", async () => {
  mocked.replayCase.mockResolvedValue({
    results: [{ error: null }, { error: "down" }],
    total: { cost_usd: 0.0123 },
  } as never);
  const { hook, pushToast } = setup();
  act(() => hook.result.current.show());
  await waitFor(() => expect(mocked.listCases).toHaveBeenCalled());
  expect(hook.result.current.open).toBe(true);
  await act(() => hook.result.current.openCase("case-1"));
  expect(hook.result.current.current?.case_id).toBe("case-1");

  await act(() => hook.result.current.replay(["gpt-a", "claude-b"]));
  expect(mocked.replayCase).toHaveBeenCalledWith("case-1", ["gpt-a", "claude-b"]);
  expect(pushToast).toHaveBeenCalledWith("1 of 2 answered · $0.0123", "error", "Replay finished");
  // The case is read again, so its replays include this one.
  expect(mocked.fetchCase).toHaveBeenCalledTimes(2);
  expect(hook.result.current.replaying).toBe(false);
});

it("deletes a case only once the person confirms", async () => {
  mocked.listCases.mockResolvedValue([{ case_id: "case-1" }] as never);
  const declined = setup(false);
  await act(() => declined.hook.result.current.remove("case-1", "Which database?"));
  expect(mocked.deleteCase).not.toHaveBeenCalled();

  const accepted = setup(true);
  act(() => accepted.hook.result.current.show());
  await waitFor(() => expect(accepted.hook.result.current.list).toHaveLength(1));
  await act(() => accepted.hook.result.current.remove("case-1", "Which database?"));
  expect(accepted.confirm).toHaveBeenCalledWith("Delete this case?", expect.any(String), { confirmLabel: "Delete" });
  expect(mocked.deleteCase).toHaveBeenCalledWith("case-1");
  expect(accepted.hook.result.current.list).toEqual([]);
});
