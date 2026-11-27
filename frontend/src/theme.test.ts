import fs from "fs";
import path from "path";
import { getContrastRatio } from "@mui/material/styles";
import { darkTheme, lightTheme } from "./theme";
import { MIN_TEXT_CONTRAST, SURFACE } from "./lib/colors";

/** Every .tsx under src, tests excluded. */
function sources(dir = __dirname): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return sources(p);
    return /\.tsx?$/.test(e.name) && !/\.test\./.test(e.name) ? [p] : [];
  });
}

describe("theme colours", () => {
  it.each([
    ["light", lightTheme, SURFACE.light],
    ["dark", darkTheme, SURFACE.dark],
  ])("%s: primary reads as text and carries its button text at AA", (_name, theme, surface) => {
    const { primary } = theme.palette;
    expect(getContrastRatio(primary.main, surface)).toBeGreaterThanOrEqual(MIN_TEXT_CONTRAST);
    expect(getContrastRatio(primary.contrastText, primary.main)).toBeGreaterThanOrEqual(MIN_TEXT_CONTRAST);
  });

  it("light: secondary text stays at AA on the tinted surfaces it labels", () => {
    // slate-100 and slate-200: the cards and chips the panel draws.
    for (const tint of [SURFACE.light, "#f1f5f9", "#e2e8f0"]) {
      expect(getContrastRatio(lightTheme.palette.text.secondary, tint)).toBeGreaterThanOrEqual(MIN_TEXT_CONTRAST);
    }
  });

  it("names no palette shade the theme doesn't define", () => {
    // `primary.50` and the like resolve to nothing: the light "You" bubble
    // fell back to a white fill and a near-black border.
    const offenders = sources().flatMap((file) =>
      [...fs.readFileSync(file, "utf8").matchAll(/["'`](primary|secondary|error|warning|info|success)\.\d{2,3}["'`]/g)].map(
        (m) => `${path.relative(__dirname, file)}: ${m[0]}`,
      ),
    );
    expect(offenders).toEqual([]);
  });
});
