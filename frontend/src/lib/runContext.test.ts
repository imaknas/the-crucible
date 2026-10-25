import { contextFields } from "./runContext";

describe("contextFields", () => {
  it("names only the choices that were made", () => {
    expect(contextFields({})).toEqual({});
    expect(contextFields({ summarizer: null, systemPrompt: null })).toEqual({});
    expect(contextFields({ systemPrompt: "   \n" })).toEqual({});
  });

  it("puts each choice in its top-level frame field", () => {
    expect(contextFields({ summarizer: "gpt-6-luna", systemPrompt: "Be terse." })).toEqual({
      summarizer: "gpt-6-luna",
      system_prompt: "Be terse.",
    });
  });
});
