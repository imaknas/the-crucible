import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import Sidebar from "./Sidebar";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  searchHistory: jest.fn().mockResolvedValue({ results: [] }),
}));

describe("Sidebar", () => {
  const mockProps = {
    threads: [
      { id: "t1", title: "Thread 1", updated_at: "2024-01-01T00:00:00" },
    ],
    threadId: "t1",
    activeThreadId: "t1",
    editingThreadId: null,
    editingTitle: "",
    onSelectThread: jest.fn(),
    onDeleteThread: jest.fn(),
    onRenameThread: jest.fn(),
    onJumpToNode: jest.fn(),
    onStartNewExperiment: jest.fn(),
    onSetEditing: jest.fn(),
    onUpdateTitle: jest.fn(),
    onSaveTitle: jest.fn(),
    onCancelEdit: jest.fn(),
  };

  it("renders threads list", () => {
    render(<Sidebar {...mockProps} />);
    expect(screen.getByText("Thread 1")).toBeInTheDocument();
  });

  it("handles search input change", async () => {
    render(<Sidebar {...mockProps} />);
    const searchInput = screen.getByPlaceholderText(/Search/i);
    fireEvent.change(searchInput, { target: { value: "test" } });
    expect(searchInput).toHaveValue("test");
  });
});
