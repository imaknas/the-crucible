/**
 * What React Flow needs from the DOM that jsdom doesn't provide.
 *
 * jsdom has no layout: every offsetWidth is 0 and there is no ResizeObserver,
 * so React Flow would never measure its pane or its nodes. Measuring is what
 * fills `width` / `height` on the store's nodes, which auto-fit waits for, so
 * the observer here does not fire by itself: a test calls `measureNodes()` at
 * the moment it wants React Flow to see the measurements.
 *
 * Call `installReactFlowDom()` at the top of a test file; it registers its own
 * setup and teardown hooks.
 */

/** Pane size reported for the canvas. Under 600px wide, so no minimap. */
export const PANE = { width: 560, height: 420 };
/** Size every node reports once measured. */
export const NODE = { width: 220, height: 100 };

type Observer = { callback: ResizeObserverCallback; targets: Set<Element> };
let observers: Observer[] = [];

class StubResizeObserver {
  private readonly entry: Observer;
  constructor(callback: ResizeObserverCallback) {
    this.entry = { callback, targets: new Set() };
    observers.push(this.entry);
  }
  observe(target: Element) {
    this.entry.targets.add(target);
  }
  unobserve(target: Element) {
    this.entry.targets.delete(target);
  }
  disconnect() {
    this.entry.targets.clear();
  }
}

/** React Flow reads only the zoom (m22) from the viewport's transform. */
class StubDOMMatrixReadOnly {
  m22 = 1;
}

/**
 * Report a resize for everything observed: React Flow measures each node
 * (`offsetWidth` / `offsetHeight`) and stores its size. Wrap in `act`.
 */
export function measureNodes() {
  for (const { callback, targets } of observers) {
    if (targets.size === 0) continue;
    const entries = [...targets].map((target) => ({ target }) as ResizeObserverEntry);
    callback(entries, {} as ResizeObserver);
  }
}

function sizeOf(el: HTMLElement) {
  return el.classList.contains("react-flow__node") ? NODE : PANE;
}

export function installReactFlowDom() {
  const saved = {
    ResizeObserver: window.ResizeObserver,
    DOMMatrixReadOnly: window.DOMMatrixReadOnly,
    offsetWidth: Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth"),
    offsetHeight: Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight"),
  };

  beforeAll(() => {
    window.ResizeObserver = StubResizeObserver as unknown as typeof ResizeObserver;
    window.DOMMatrixReadOnly = StubDOMMatrixReadOnly as unknown as typeof DOMMatrixReadOnly;
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return sizeOf(this).width;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get(this: HTMLElement) {
        return sizeOf(this).height;
      },
    });
  });

  afterEach(() => {
    observers = [];
  });

  afterAll(() => {
    window.ResizeObserver = saved.ResizeObserver;
    window.DOMMatrixReadOnly = saved.DOMMatrixReadOnly;
    if (saved.offsetWidth) Object.defineProperty(HTMLElement.prototype, "offsetWidth", saved.offsetWidth);
    if (saved.offsetHeight) Object.defineProperty(HTMLElement.prototype, "offsetHeight", saved.offsetHeight);
  });
}
