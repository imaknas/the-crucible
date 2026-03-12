import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import Sidebar from "./Sidebar";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  searchHistory: jest.fn().mockResolvedValue({ results: [] }),
}));

describe("Sidebar", () => {
  const mockProps = {
    threads: [{ id: "t1", title: "Thread 1" }],
    threadId: "t1",
    editingThreadId: null,
    editingTitle: "",
    onStartNewExperiment: jest.fn(),
    onSwitchThread: jest.fn(),
    onDeleteThread: jest.fn(),
    onRenameThread: jest.fn(),
    setEditingThreadId: jest.fn(),
    setEditingTitle: jest.fn(),
    onSwitchCheckpoint: jest.fn(),
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
