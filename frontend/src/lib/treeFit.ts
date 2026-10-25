/**
 * Where auto-fit points the canvas.
 *
 * Fitting only the active node (the newest reply, usually at the bottom) at a
 * readable zoom pushed the top of the tree off the canvas, behind the header,
 * where nothing could be clicked. The whole tree is fitted whenever it fits
 * at a zoom where nodes still show their text; only trees too big for that
 * fall back to centring the active node.
 */
export interface Size {
  width: number;
  height: number;
}

/** The zoom React Flow's fitView would pick for `bounds` (same formula). */
export function fitZoom(bounds: Size, viewport: Size, padding: number): number {
  if (bounds.width <= 0 || bounds.height <= 0) return Infinity;
  return Math.min(
    viewport.width / (bounds.width * (1 + padding)),
    viewport.height / (bounds.height * (1 + padding)),
  );
}

export function shouldFitWholeTree(
  bounds: Size,
  viewport: Size,
  padding: number,
  readableZoom: number,
): boolean {
  return fitZoom(bounds, viewport, padding) >= readableZoom;
}
