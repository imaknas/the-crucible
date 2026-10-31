import { mayLeaveThread } from "./leaveGuard";

describe("mayLeaveThread", () => {
  it("asks nothing of its own when no chat turn is answering; the debate decides", async () => {
    const confirm = jest.fn();
    const confirmLeaveDebate = jest.fn().mockResolvedValue(true);
    await expect(mayLeaveThread({ answering: false, confirm, confirmLeaveDebate })).resolves.toBe(true);
    expect(confirm).not.toHaveBeenCalled();
    expect(confirmLeaveDebate).toHaveBeenCalledTimes(1);

    confirmLeaveDebate.mockResolvedValueOnce(false);
    await expect(mayLeaveThread({ answering: false, confirm, confirmLeaveDebate })).resolves.toBe(false);
  });

  it("asks about the answering models first, with the action's verb", async () => {
    const confirm = jest.fn().mockResolvedValue(true);
    const confirmLeaveDebate = jest.fn().mockResolvedValue(true);
    await expect(mayLeaveThread({ answering: true, confirm, confirmLeaveDebate })).resolves.toBe(true);
    expect(confirm).toHaveBeenCalledWith("Leave while models answer?", expect.stringContaining("still answering"), {
      confirmLabel: "Stop and leave",
    });
    expect(confirm.mock.invocationCallOrder[0]).toBeLessThan(confirmLeaveDebate.mock.invocationCallOrder[0]);
  });

  it("stays when the chat question is declined, without asking about the debate", async () => {
    const confirm = jest.fn().mockResolvedValue(false);
    const confirmLeaveDebate = jest.fn().mockResolvedValue(true);
    await expect(mayLeaveThread({ answering: true, confirm, confirmLeaveDebate })).resolves.toBe(false);
    expect(confirmLeaveDebate).not.toHaveBeenCalled();
  });

  it("stays when the chat question is accepted but the debate one is declined", async () => {
    const confirm = jest.fn().mockResolvedValue(true);
    const confirmLeaveDebate = jest.fn().mockResolvedValue(false);
    await expect(mayLeaveThread({ answering: true, confirm, confirmLeaveDebate })).resolves.toBe(false);
  });
});
