import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import ChecklistDialog from "./ChecklistDialog";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/errors";

jest.mock("@/lib/api");

describe("ChecklistDialog", () => {
  it("lists the parts, all kept, and merges the ones still ticked", async () => {
    (api.listAnswerComponents as jest.Mock).mockResolvedValue([
      { text: "Start with a monolith.", sources: ["GPT-5.4"] },
      { text: "Split out billing first.", sources: ["Claude Sonnet 5"] },
    ]);
    const onMerge = jest.fn();
    render(<ChecklistDialog open threadId="t" ids={["a", "b"]} model={null} onClose={jest.fn()} onMerge={onMerge} />);
    expect(screen.getByRole("status")).toHaveTextContent("Splitting the answers into parts");
    fireEvent.click(await screen.findByRole("checkbox", { name: /Split out billing first/ }));
    fireEvent.click(screen.getByRole("button", { name: "Merge 1 part" }));
    expect(onMerge).toHaveBeenCalledWith(["Start with a monolith."]);
    expect(api.listAnswerComponents).toHaveBeenCalledWith("t", ["a", "b"], null);
  });

  it("shows why it couldn't split the answers", async () => {
    (api.listAnswerComponents as jest.Mock).mockRejectedValue(new ApiError("The model's reply listed no components", 400));
    render(<ChecklistDialog open threadId="t" ids={["a", "b"]} model={null} onClose={jest.fn()} onMerge={jest.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("listed no components");
    expect(screen.getByRole("button", { name: /Merge/ })).toBeDisabled();
  });
});
