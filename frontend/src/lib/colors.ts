import { alpha, darken, getContrastRatio, lighten } from "@mui/material/styles";

/**
 * Model colours: one family colour per model, from the backend.
 *
 * GET /models ships each family's colour and the backend puts the resolved
 * colour on every node and message (`model_color`). `FAMILY_COLORS` and
 * `modelFamilyColor` are only the fallback for the moment before the
 * catalogue has loaded; `modelPalette` derives everything drawn from a
 * colour, in either theme, so there is one palette instead of four.
 */
export const FAMILY_COLORS = {
  openai: "#10b981",
  anthropic: "#f59e0b",
  google: "#8b5cf6",
  synthesis: "#8b5cf6",
  unknown: "#6366f1",
} as const;

/** Pre-fetch fallback: a family colour guessed from the id. Prefer the catalogue's. */
export function modelFamilyColor(modelId: string | undefined | null): string {
  const m = (modelId || "").toLowerCase();
  if (m.includes("gpt") || m.includes("o1") || m.includes("o3")) return FAMILY_COLORS.openai;
  if (m.includes("claude")) return FAMILY_COLORS.anthropic;
  if (m.includes("gemini")) return FAMILY_COLORS.google;
  return FAMILY_COLORS.unknown;
}

/** The surfaces text is read on: the light theme's paper and the dark theme's. */
export const SURFACE = { light: "#ffffff", dark: "#0f172a" } as const;

/** WCAG AA for normal text. */
export const MIN_TEXT_CONTRAST = 4.5;

/**
 * `color`, darkened (on a light surface) or lightened (on a dark one) until
 * text in it reaches AA contrast. Amber, emerald and violet labels used to
 * sit at 1.7–2.7:1 on white.
 */
export function readableOn(color: string, surface: string): string {
  const towardsDark = getContrastRatio(surface, "#000") > getContrastRatio(surface, "#fff");
  let c = color;
  for (let i = 0; i < 12 && getContrastRatio(c, surface) < MIN_TEXT_CONTRAST; i++) {
    c = towardsDark ? darken(c, 0.12) : lighten(c, 0.12);
  }
  return c;
}

export interface ModelPalette {
  /** The family colour itself: borders and marks. */
  main: string;
  /** Text in the family colour, readable on the theme's surface. */
  text: string;
  /** Dot or bar beside a name. */
  dot: string;
  /** Tinted background and border. */
  bg: string;
  border: string;
}

export function modelPalette(color: string, isDark: boolean): ModelPalette {
  return {
    main: color,
    text: readableOn(color, isDark ? SURFACE.dark : SURFACE.light),
    dot: color,
    bg: alpha(color, isDark ? 0.1 : 0.08),
    border: alpha(color, isDark ? 0.3 : 0.35),
  };
}

/** No model (or an unknown author): neutral grey. */
export const NEUTRAL_COLOR = "#94a3b8";
