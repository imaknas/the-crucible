import { parseStoredSelection, resolveSelection } from "./modelSelection";
import { parseToggles, DEFAULT_TOGGLES } from "@/hooks/useToggles";

const family = (key: string, available: boolean, ids: string[]) =>
  ({ key, label: key, color: "#000", available, models: ids.map((id) => ({ id, name: id, desc: "" })) }) as any;

const families = [family("openai", true, ["gpt-a", "gpt-b"]), family("anthropic", true, ["claude-a"]), family("google", false, ["gem-a"])];
const defaults = { default_model: "gpt-a", default_arena_models: ["gpt-a", "claude-a", "gem-a"] };

describe("resolveSelection", () => {
  it("starts from the default arena, keeping models whose family has a key", () => {
    expect(resolveSelection([], families, defaults)).toEqual(["gpt-a", "claude-a"]);
  });

  it("keeps what was picked last", () => {
    expect(resolveSelection(["claude-a", "gpt-b"], families, defaults)).toEqual(["claude-a", "gpt-b"]);
  });

  it("drops picked models that are gone or have no key, and falls back when none is left", () => {
    expect(resolveSelection(["gem-a", "retired", "gpt-b"], families, defaults)).toEqual(["gpt-b"]);
    expect(resolveSelection(["gem-a"], families, defaults)).toEqual(["gpt-a", "claude-a"]);
  });

  it("falls back to the default model when no default arena model is usable", () => {
    expect(resolveSelection([], families, { default_model: "gpt-a", default_arena_models: ["gem-a"] })).toEqual(["gpt-a"]);
  });

  it("selects nothing before the catalogue has loaded", () => {
    expect(resolveSelection(["gpt-a"], [], {})).toEqual([]);
  });
});

describe("stored values", () => {
  it("reads a malformed selection as none", () => {
    expect(parseStoredSelection("not json")).toEqual([]);
    expect(parseStoredSelection('{"a":1}')).toEqual([]);
    expect(parseStoredSelection('["gpt-a", 3]')).toEqual(["gpt-a"]);
  });

  it("reads toggles over the defaults", () => {
    expect(parseToggles(null)).toEqual(DEFAULT_TOGGLES);
    expect(parseToggles('{"use_web_search": true}')).toEqual({ ...DEFAULT_TOGGLES, use_web_search: true });
    expect(parseToggles("garbage")).toEqual(DEFAULT_TOGGLES);
  });
});
