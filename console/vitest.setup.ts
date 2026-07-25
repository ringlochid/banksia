import "@testing-library/jest-dom/vitest";

import { afterEach } from "vitest";

class TestResizeObserver implements ResizeObserver {
    disconnect(): void {}

    observe(): void {}

    unobserve(): void {}
}

globalThis.ResizeObserver = TestResizeObserver;

afterEach(() => {
    document.body.innerHTML = "";
});
