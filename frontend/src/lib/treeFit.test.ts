import { fitZoom, shouldFitWholeTree } from "./treeFit";

describe("tree auto-fit", () => {
  const viewport = { width: 800, height: 700 };

  it("computes fitView's zoom: the tighter axis wins", () => {
    expect(fitZoom({ width: 400, height: 700 }, viewport, 0)).toBeCloseTo(1);
    expect(fitZoom({ width: 400, height: 350 }, viewport, 1)).toBeCloseTo(1);
  });

  it("fits a small tree whole, so its top stays on the canvas", () => {
    expect(shouldFitWholeTree({ width: 480, height: 570 }, viewport, 0.15, 0.6)).toBe(true);
  });

  it("falls back to the active node when the whole tree would be unreadable", () => {
    expect(shouldFitWholeTree({ width: 4000, height: 3000 }, viewport, 0.15, 0.6)).toBe(false);
  });
});
