import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskGraph } from "../../src/features/task-detail/task-detail-graph";
import type {
    TaskGraphEdge,
    TaskGraphNode,
} from "../../src/features/task-detail/task-detail-model";

const cyclicNodes: readonly TaskGraphNode[] = [
    {
        attemptId: "attempt.root.01",
        checkpointSummary: null,
        eventCount: 2,
        isActive: false,
        isCurrent: true,
        nodeKey: "root",
        order: 0,
        status: "active",
        summary: "Root task.",
    },
    {
        attemptId: "attempt.implementation.01",
        checkpointSummary: null,
        eventCount: 2,
        isActive: false,
        isCurrent: false,
        nodeKey: "implementation_delivery",
        order: 1,
        status: "quiet",
        summary: "Implementation delivery.",
    },
];

const cyclicEdges: readonly TaskGraphEdge[] = [
    {
        fromNodeKey: "root",
        kind: "structural",
        toNodeKey: "implementation_delivery",
    },
    {
        fromNodeKey: "implementation_delivery",
        kind: "staged",
        toNodeKey: "root",
    },
];

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

describe("task detail graph", () => {
    it("renders cyclic non-tree edges without overflowing the layout walk", () => {
        render(
            <TaskGraph
                edges={cyclicEdges}
                nodes={cyclicNodes}
                onOpenDetail={vi.fn()}
                onSelectNode={vi.fn()}
                selectedNodeKey="root"
            />,
        );

        expect(screen.getByLabelText("Execution graph")).toBeVisible();
        expect(screen.getByRole("button", { name: /root active/i })).toBeVisible();
        expect(
            screen.getByRole("button", { name: /implementation_delivery quiet/i }),
        ).toBeVisible();
    });

    it("fits the full graph on the initial camera", () => {
        render(
            <TaskGraph
                edges={[
                    { fromNodeKey: "root", kind: "structural", toNodeKey: "left_worker" },
                    { fromNodeKey: "root", kind: "structural", toNodeKey: "right_worker" },
                ]}
                nodes={[
                    {
                        attemptId: "attempt.root.01",
                        checkpointSummary: null,
                        eventCount: 1,
                        isActive: false,
                        isCurrent: false,
                        nodeKey: "root",
                        order: 0,
                        status: "quiet",
                        summary: "Root task.",
                    },
                    {
                        attemptId: "attempt.left.01",
                        checkpointSummary: null,
                        eventCount: 1,
                        isActive: true,
                        isCurrent: true,
                        nodeKey: "left_worker",
                        order: 1,
                        status: "active",
                        summary: "Left worker.",
                    },
                    {
                        attemptId: "attempt.right.01",
                        checkpointSummary: null,
                        eventCount: 1,
                        isActive: false,
                        isCurrent: false,
                        nodeKey: "right_worker",
                        order: 2,
                        status: "quiet",
                        summary: "Right worker.",
                    },
                ]}
                onOpenDetail={vi.fn()}
                onSelectNode={vi.fn()}
                selectedNodeKey="left_worker"
            />,
        );

        const cameraGroup = screen
            .getByLabelText("Execution graph")
            .querySelector('g[transform^="translate"]');

        const transform = cameraGroup?.getAttribute("transform") ?? "";
        const translateX = Number(
            /^translate\((?<translateX>-?\d+(?:\.\d+)?) /.exec(transform)?.groups?.translateX,
        );
        const scale = Number(/scale\((?<scale>-?\d+(?:\.\d+)?)\)/.exec(transform)?.groups?.scale);

        expect(Number.isFinite(translateX)).toBe(true);
        expect(scale).toBeGreaterThan(0.7);
        expect(scale).toBeLessThanOrEqual(1.85);
    });

    it("opens at a readable fit and keeps manual zoom capped at 500 percent", async () => {
        mockGraphViewport({ height: 620, width: 320 });

        render(
            <TaskGraph
                edges={[{ fromNodeKey: "root", kind: "structural", toNodeKey: "charter_phase" }]}
                nodes={[
                    {
                        attemptId: "attempt.root.01",
                        checkpointSummary: null,
                        eventCount: 1,
                        isActive: true,
                        isCurrent: true,
                        nodeKey: "root",
                        order: 0,
                        status: "active",
                        summary: "Root task.",
                    },
                    {
                        attemptId: "attempt.charter.01",
                        checkpointSummary: null,
                        eventCount: 1,
                        isActive: false,
                        isCurrent: false,
                        nodeKey: "charter_phase",
                        order: 1,
                        status: "quiet",
                        summary: "Charter phase.",
                    },
                ]}
                onOpenDetail={vi.fn()}
                onSelectNode={vi.fn()}
                selectedNodeKey="root"
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("185%")).toBeVisible();
        });

        for (let index = 0; index < 12; index += 1) {
            fireEvent.click(screen.getByRole("button", { name: "Zoom in graph" }));
        }

        expect(screen.getByText("500%")).toBeVisible();
    });
});

function mockGraphViewport({ height, width }: { readonly height: number; readonly width: number }) {
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (
        this: Element,
    ) {
        if (
            this instanceof SVGSVGElement &&
            this.getAttribute("aria-label") === "Execution graph"
        ) {
            return {
                bottom: height,
                height,
                left: 0,
                right: width,
                top: 0,
                width,
                x: 0,
                y: 0,
                toJSON: () => ({}),
            };
        }

        return {
            bottom: 0,
            height: 0,
            left: 0,
            right: 0,
            top: 0,
            width: 0,
            x: 0,
            y: 0,
            toJSON: () => ({}),
        };
    });
}
