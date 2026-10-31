import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import Sidebar from "./Sidebar";
import type { DebateSession } from "@/lib/types";

jest.mock("@/lib/api", () => ({
  searchHistory: jest.fn().mockResolvedValue({ results: [] }),
}));

describe("Sidebar", () => {
  const mockProps = () => ({
    threads: [{ id: "t1", title: "Thread 1" }],
    threadId: "t1",
    onStartNewExperiment: jest.fn(),
    onSwitchThread: jest.fn(),
    onDeleteThread: jest.fn(),
    onRenameThread: jest.fn().mockResolvedValue(true),
    onSwitchCheckpoint: jest.fn(),
  });

  it("renders threads list", () => {
    render(<Sidebar {...mockProps()} />);
    expect(screen.getByText("Thread 1")).toBeInTheDocument();
  });

  it("handles search input change", async () => {
    render(<Sidebar {...mockProps()} />);
    const searchInput = screen.getByLabelText(/Search this session/i);
    fireEvent.change(searchInput, { target: { value: "test" } });
    expect(searchInput).toHaveValue("test");
  });

  it("leaves edit mode once a rename is saved", async () => {
    const props = mockProps();
    render(<Sidebar {...props} />);
    fireEvent.click(screen.getByLabelText("Rename session"));
    const field = screen.getByLabelText("Session name");
    fireEvent.change(field, { target: { value: "Renamed" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(props.onRenameThread).toHaveBeenCalledWith("t1", "Renamed");
    await waitFor(() => expect(screen.queryByLabelText("Session name")).not.toBeInTheDocument());
  });

  it("stays in edit mode when the rename fails, keeping the draft", async () => {
    const props = { ...mockProps(), onRenameThread: jest.fn().mockResolvedValue(false) };
    render(<Sidebar {...props} />);
    fireEvent.click(screen.getByLabelText("Rename session"));
    const field = screen.getByLabelText("Session name");
    fireEvent.change(field, { target: { value: "Renamed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(props.onRenameThread).toHaveBeenCalled());
    expect(screen.getByLabelText("Session name")).toHaveValue("Renamed");
  });

  it("deletes a session by id", () => {
    const props = mockProps();
    render(<Sidebar {...props} />);
    fireEvent.click(screen.getByLabelText("Delete session"));
    expect(props.onDeleteThread).toHaveBeenCalledWith("t1");
  });
});

describe("Sidebar layout modes", () => {
  const props = () => ({
    threads: [
      { id: "t1", title: "Thread 1" },
      { id: "t2", title: "Thread 2" },
    ],
    threadId: "t1",
    onStartNewExperiment: jest.fn(),
    onSwitchThread: jest.fn(),
    onDeleteThread: jest.fn(),
    onRenameThread: jest.fn().mockResolvedValue(true),
    onSwitchCheckpoint: jest.fn(),
    debateSessions: [
      {
        session_id: "s1",
        parent_thread_id: "t1",
        participants: ["gpt-a", "claude-b"],
        thread_ids: {},
        current_round: 2,
        status: "completed",
        question: "Is it true?",
        created_at: new Date().toISOString(),
        termination_policy: { max_rounds: 3, convergence_threshold: null, llm_judge: null, mode: "any" },
        auto_synthesize: false,
        synthesizer_model: null,
      },
    ] satisfies DebateSession[],
    onSwitchDebateSession: jest.fn(),
    onClose: jest.fn(),
    onCollapsedChange: jest.fn(),
  });

  it("docked: the full list, collapsible, and picking never closes anything", () => {
    const p = props();
    render(<Sidebar {...p} mode="docked" />);
    expect(screen.getByRole("navigation", { name: "Sessions" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close sessions" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Thread 2" }));
    fireEvent.click(screen.getByRole("button", { name: "New Session" }));
    expect(p.onSwitchThread).toHaveBeenCalledWith("t2");
    expect(p.onStartNewExperiment).toHaveBeenCalled();
    expect(p.onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Collapse sessions" }));
    expect(p.onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it("docked and collapsed: a rail with expand and New Session only", () => {
    const p = props();
    render(<Sidebar {...p} mode="docked" collapsed />);
    expect(screen.queryByText("Thread 1")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Search this session/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "New Session" }));
    expect(p.onStartNewExperiment).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Expand sessions" }));
    expect(p.onCollapsedChange).toHaveBeenCalledWith(false);
  });

  it("overlay: a drawer that closes once something is picked", () => {
    const p = props();
    // A stored collapse belongs to the docked layout: the overlay never shows a rail.
    render(<Sidebar {...p} mode="overlay" open collapsed />);
    expect(screen.queryByRole("button", { name: "Expand sessions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Collapse sessions" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Thread 2" }));
    expect(p.onSwitchThread).toHaveBeenCalledWith("t2");
    expect(p.onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "New Session" }));
    expect(p.onStartNewExperiment).toHaveBeenCalled();
    expect(p.onClose).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Show 1 debate" }));
    fireEvent.click(screen.getByRole("button", { name: /Is it true\?/ }));
    expect(p.onSwitchDebateSession).toHaveBeenCalledWith("s1");
    expect(p.onClose).toHaveBeenCalledTimes(3);

    fireEvent.click(screen.getByRole("button", { name: "Close sessions" }));
    expect(p.onClose).toHaveBeenCalledTimes(4);
  });

  it("overlay: stays mounted but out of sight while closed", () => {
    render(<Sidebar {...props()} mode="overlay" open={false} />);
    expect(screen.getByText("Thread 1")).not.toBeVisible();
  });
});
