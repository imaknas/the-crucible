import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import ApiKeysSection from "./ApiKeysSection";
import * as api from "@/lib/api";
import { FAMILIES } from "@/test/families";

jest.mock("@/lib/api", () => ({
  fetchKeyStatus: jest.fn(),
  saveApiKeys: jest.fn(),
}));
jest.mock("lucide-react", () => {
  const Icon = () => <div />;
  return new Proxy({}, { get: (_, name) => (name === "__esModule" ? false : Icon) });
});

const mocked = api as jest.Mocked<typeof api>;

async function renderKeys(onSaved = jest.fn()) {
  render(<ApiKeysSection families={FAMILIES} isDark={false} onSaved={onSaved} />);
  await act(async () => {});
  return onSaved;
}

const field = (label: string) => screen.getByPlaceholderText(label) as HTMLInputElement;

beforeEach(() => {
  jest.clearAllMocks();
  mocked.fetchKeyStatus.mockResolvedValue({ OPENAI_API_KEY: { set: true, masked: "sk-…abcd" } } as never);
});

describe("ApiKeysSection", () => {
  it("opens the families without a key, and shows a set key only masked", async () => {
    await renderKeys();
    expect(screen.getByText("NOT SET")).toBeInTheDocument();
    expect(screen.getAllByText("SET")).toHaveLength(2);
    expect(field("Paste your Google API key")).toBeVisible();

    const [openai] = screen.getAllByPlaceholderText("Enter new key to replace") as HTMLInputElement[];
    expect(openai).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /^OpenAI/ }));
    expect(openai).toBeVisible();
    expect(screen.getByText("sk-…abcd")).toBeVisible();
    expect(openai.type).toBe("password");
  });

  it("shows a typed key on request", async () => {
    await renderKeys();
    const input = field("Paste your Google API key");
    fireEvent.click(screen.getByRole("button", { name: "Show Google key" }));
    expect(input.type).toBe("text");
    fireEvent.click(screen.getByRole("button", { name: "Hide Google key" }));
    expect(input.type).toBe("password");
  });

  it("saves only typed keys, by their environment name, then reports it", async () => {
    mocked.saveApiKeys.mockResolvedValue(undefined);
    const onSaved = await renderKeys();
    expect(screen.queryByRole("button", { name: "Save Keys" })).not.toBeInTheDocument();
    fireEvent.change(field("Paste your Google API key"), { target: { value: "   " } });
    expect(screen.queryByRole("button", { name: "Save Keys" })).not.toBeInTheDocument();

    fireEvent.change(field("Paste your Google API key"), { target: { value: "  g-key  " } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save Keys" }));
    });
    expect(mocked.saveApiKeys).toHaveBeenCalledWith({ GOOGLE_API_KEY: "g-key" });
    expect(onSaved).toHaveBeenCalled();
    // The typed value is gone and the status is read again.
    expect(field("Paste your Google API key").value).toBe("");
    expect(mocked.fetchKeyStatus).toHaveBeenCalledTimes(2);
  });

  it("shows the backend's reason when a save is refused", async () => {
    mocked.saveApiKeys.mockRejectedValue(new Error("Keys can only be set from this machine"));
    const onSaved = await renderKeys();
    fireEvent.change(field("Paste your Google API key"), { target: { value: "g-key" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save Keys" }));
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Keys can only be set from this machine");
    expect(onSaved).not.toHaveBeenCalled();
    expect(field("Paste your Google API key").value).toBe("g-key");
  });
});
