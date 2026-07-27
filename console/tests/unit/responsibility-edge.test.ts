import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { responsibilitySegments } from "../../src/features/workflow-studio/canvas/responsibility-geometry";

describe("responsibility edge", () => {
    it("draws one curve when the child sits to the right", () => {
        const segments = responsibilitySegments({
            sourcePosition: Position.Right,
            sourceX: 100,
            sourceY: 200,
            targetPosition: Position.Left,
            targetX: 400,
            targetY: 260,
        });

        expect(segments).toHaveLength(1);
        // A bezier, not an orthogonal run.
        expect(segments[0]).toContain("C");
    });

    it("still draws one curve when parent and child share a row", () => {
        const segments = responsibilitySegments({
            sourcePosition: Position.Right,
            sourceX: 100,
            sourceY: 200,
            targetPosition: Position.Left,
            targetX: 400,
            targetY: 200,
        });

        expect(segments).toHaveLength(1);
    });

    it("keeps one continuous curve if positions briefly cross", () => {
        const segments = responsibilitySegments({
            sourcePosition: Position.Right,
            sourceX: 600,
            sourceY: 200,
            targetPosition: Position.Left,
            targetX: 100,
            targetY: 260,
        });

        expect(segments).toHaveLength(1);
        expect(segments[0]?.startsWith("M")).toBe(true);
    });

    it("treats a child within the handle's own width as forward", () => {
        const segments = responsibilitySegments({
            sourcePosition: Position.Right,
            sourceX: 100,
            sourceY: 200,
            targetPosition: Position.Left,
            targetX: 90,
            targetY: 200,
        });

        expect(segments).toHaveLength(1);
    });

    it("emits paths that begin with a move command", () => {
        const segments = responsibilitySegments({
            sourcePosition: Position.Right,
            sourceX: 0,
            sourceY: 0,
            targetPosition: Position.Left,
            targetX: 200,
            targetY: 120,
        });

        expect(segments[0]?.startsWith("M")).toBe(true);
    });
});
