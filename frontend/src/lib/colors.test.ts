import { getContrastRatio } from "@mui/material/styles";
import { FAMILY_COLORS, MIN_TEXT_CONTRAST, SURFACE, modelFamilyColor, modelPalette, readableOn } from "./colors";

describe("modelPalette", () => {
  const families = Object.values(FAMILY_COLORS);

  it.each(families)("%s text is readable on white", (color) => {
    expect(getContrastRatio(modelPalette(color, false).text, SURFACE.light)).toBeGreaterThanOrEqual(MIN_TEXT_CONTRAST);
  });

  it.each(families)("%s text is readable on the dark surface", (color) => {
    expect(getContrastRatio(modelPalette(color, true).text, SURFACE.dark)).toBeGreaterThanOrEqual(MIN_TEXT_CONTRAST);
  });

  it("keeps the family colour itself for marks", () => {
    expect(modelPalette("#f59e0b", false).main).toBe("#f59e0b");
  });
});

describe("readableOn", () => {
  it("leaves a colour that is already readable alone", () => {
    expect(readableOn("#1e40af", SURFACE.light)).toBe("#1e40af");
  });
});

describe("modelFamilyColor", () => {
  it("guesses a family before the catalogue loads", () => {
    expect(modelFamilyColor("claude-sonnet-5-5")).toBe(FAMILY_COLORS.anthropic);
    expect(modelFamilyColor("mystery")).toBe(FAMILY_COLORS.unknown);
  });
});
