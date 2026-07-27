import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

class TestResizeObserver implements ResizeObserver {
    disconnect(): void {}

    observe(): void {}

    unobserve(): void {}
}

globalThis.ResizeObserver = TestResizeObserver;

if (HTMLElement.prototype.hasPointerCapture === undefined) {
    HTMLElement.prototype.hasPointerCapture = () => false;
}
if (HTMLElement.prototype.setPointerCapture === undefined) {
    HTMLElement.prototype.setPointerCapture = () => undefined;
}
if (HTMLElement.prototype.releasePointerCapture === undefined) {
    HTMLElement.prototype.releasePointerCapture = () => undefined;
}
if (HTMLElement.prototype.scrollIntoView === undefined) {
    HTMLElement.prototype.scrollIntoView = () => undefined;
}

afterEach(() => {
    // Unmount first so portalled Radix controls can release body pointer locks,
    // scroll locks, and focus guards before their DOM is removed.
    cleanup();
    vi.unstubAllGlobals();
});
