import type { ModelFamily } from "@/lib/api";

/**
 * A small model catalogue for component tests, shaped like GET /models
 * `families`: two families with a key, one model each, and a family without
 * a key.
 */
export const OPENAI: ModelFamily = {
  key: "openai",
  label: "OpenAI",
  color: "#10b981",
  env_key: "OPENAI_API_KEY",
  available: true,
  models: [
    { id: "gpt-a", name: "GPT A", desc: "Fast" },
    { id: "gpt-old", name: "GPT Old", desc: "Legacy" },
  ],
};

export const ANTHROPIC: ModelFamily = {
  key: "anthropic",
  label: "Anthropic",
  color: "#d97706",
  env_key: "ANTHROPIC_API_KEY",
  available: true,
  models: [{ id: "claude-b", name: "Claude B", desc: "Careful" }],
};

export const GOOGLE_NO_KEY: ModelFamily = {
  key: "google",
  label: "Google",
  color: "#3b82f6",
  env_key: "GOOGLE_API_KEY",
  available: false,
  models: [{ id: "gemini-c", name: "Gemini C", desc: "Wide" }],
};

export const FAMILIES: ModelFamily[] = [OPENAI, ANTHROPIC, GOOGLE_NO_KEY];
