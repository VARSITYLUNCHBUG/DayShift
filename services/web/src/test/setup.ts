import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// jsdom has no matchMedia; HeroUI and React Aria ask it about motion and colour scheme.
if (typeof (window as Partial<Window>).matchMedia !== "function") {
  Object.assign(window, {
    matchMedia: (query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  });
}

// Nor ResizeObserver, which HeroUI's toasts measure themselves with.
if (!("ResizeObserver" in window)) {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  Object.assign(window, { ResizeObserver: ResizeObserverStub });
}

// Nor the Web Animations API, which the tabs' moving indicator waits on.
if (!("getAnimations" in Element.prototype)) {
  Object.assign(Element.prototype, { getAnimations: () => [] });
}
