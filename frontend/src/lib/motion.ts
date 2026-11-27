/**
 * Whether the person asked their system for less motion. Read when an
 * animation starts, so a change applies to the next one without a reload.
 */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** An animation's duration, or 0 when the system asks for reduced motion. */
export function motionMs(ms: number): number {
  return prefersReducedMotion() ? 0 : ms;
}
