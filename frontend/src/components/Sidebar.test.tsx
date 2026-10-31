import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import Sidebar from "./Sidebar";

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
