import {
    getViewportForBounds,
    useReactFlow,
    type Edge,
    type Node,
    type ReactFlowInstance,
} from "@xyflow/react";
import { useEffect, useRef, type RefObject } from "react";

export interface TeamViewportProps {
    readonly canvasRef: RefObject<HTMLElement | null>;
    readonly detailsOpen: boolean;
    readonly outlineOpen: boolean;
    readonly selectedMemberId: string;
    readonly structure: readonly TeamStructureEntry[];
}

export interface TeamStructureEntry {
    readonly id: string;
    readonly parentId: string | null;
}

export function TeamViewportCoordinator({
    canvasRef,
    detailsOpen,
    outlineOpen,
    selectedMemberId,
    structure,
}: TeamViewportProps) {
    const flow = useReactFlow<Node, Edge>();
    const previousStructure = useRef<readonly TeamStructureEntry[] | null>(
        null,
    );

    useEffect(() => {
        if (!detailsOpen) {
            return;
        }
        const frame = requestAnimationFrame(() => {
            centerSelectedMember(flow, canvasRef, selectedMemberId);
        });
        return () => cancelAnimationFrame(frame);
    }, [canvasRef, detailsOpen, flow, selectedMemberId]);

    useEffect(() => {
        const previous = previousStructure.current;
        previousStructure.current = structure;
        if (
            previous === null ||
            sameStructure(previous, structure) ||
            structure.length === 0
        ) {
            return;
        }
        let cancelled = false;
        const frame = requestAnimationFrame(() => {
            if (!cancelled) {
                void revealChangedBranch(
                    flow,
                    canvasRef,
                    previous,
                    structure,
                    selectedMemberId,
                );
            }
        });
        return () => {
            cancelled = true;
            cancelAnimationFrame(frame);
        };
    }, [canvasRef, flow, outlineOpen, selectedMemberId, structure]);

    return null;
}

function centerSelectedMember(
    flow: ReactFlowInstance<Node, Edge>,
    canvasRef: RefObject<HTMLElement | null>,
    selectedMemberId: string,
): void {
    const node = flow.getNode(selectedMemberId);
    if (node === undefined) {
        return;
    }
    const measuredWidth = node.measured?.width ?? node.width ?? 17.5 * 16;
    const measuredHeight = node.measured?.height ?? node.height ?? 10.75 * 16;
    const zoom = Math.min(flow.getZoom(), 1);
    const frame = availableCanvasFrame(canvasRef.current);
    const horizontalBias =
        (frame.rightInset - frame.leftInset) / (2 * Math.max(zoom, 0.2));
    void flow.setCenter(
        node.position.x + measuredWidth / 2 + horizontalBias,
        node.position.y + measuredHeight / 2,
        { duration: 220, zoom },
    );
}

async function revealChangedBranch(
    flow: ReactFlowInstance<Node, Edge>,
    canvasRef: RefObject<HTMLElement | null>,
    previous: readonly TeamStructureEntry[],
    current: readonly TeamStructureEntry[],
    selectedMemberId: string,
): Promise<void> {
    const previousIds = new Set(previous.map((entry) => entry.id));
    const addedIds = current
        .filter((entry) => !previousIds.has(entry.id))
        .map((entry) => entry.id);
    const targetIds =
        addedIds.length > 0
            ? [selectedMemberId, ...addedIds]
            : [
                  selectedMemberId,
                  ...current
                      .filter((entry) => entry.parentId === selectedMemberId)
                      .map((entry) => entry.id),
              ];
    const targetNodes = [...new Set(targetIds)]
        .map((memberId) => flow.getNode(memberId))
        .filter((node): node is Node => node !== undefined);
    const canvas = canvasRef.current;
    if (targetNodes.length === 0 || canvas === null) {
        return;
    }
    const bounds = flow.getNodesBounds(targetNodes);
    const frame = availableCanvasFrame(canvas);
    const viewport = getViewportForBounds(
        bounds,
        frame.width,
        frame.height,
        0.68,
        1,
        0.18,
    );
    await flow.setViewport(
        { ...viewport, x: viewport.x + frame.leftInset },
        { duration: 220 },
    );
}

function sameStructure(
    left: readonly TeamStructureEntry[],
    right: readonly TeamStructureEntry[],
): boolean {
    return (
        left.length === right.length &&
        left.every(
            (entry, index) =>
                entry.id === right[index]?.id &&
                entry.parentId === right[index]?.parentId,
        )
    );
}

function availableCanvasFrame(canvas: HTMLElement | null): {
    readonly height: number;
    readonly leftInset: number;
    readonly rightInset: number;
    readonly width: number;
} {
    if (canvas === null) {
        return { height: 1, leftInset: 0, rightInset: 0, width: 1 };
    }
    const canvasBounds = canvas.getBoundingClientRect();
    const workspace = canvas.closest(".studio__workspace");
    const outline = canvas.querySelector<HTMLElement>(
        "[data-team-outline][open]",
    );
    const details = workspace?.querySelector<HTMLElement>(
        "[data-details-surface]",
    );
    const leftInset = overlayInset(canvasBounds, outline, "left");
    const rightInset = overlayInset(canvasBounds, details ?? null, "right");
    return {
        height: Math.max(canvasBounds.height, 1),
        leftInset,
        rightInset,
        width: Math.max(canvasBounds.width - leftInset - rightInset, 1),
    };
}

function overlayInset(
    canvas: DOMRect,
    overlay: HTMLElement | null,
    side: "left" | "right",
): number {
    if (overlay === null) {
        return 0;
    }
    const bounds = overlay.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) {
        return 0;
    }
    const gap = 16;
    return side === "left"
        ? Math.max(0, bounds.right - canvas.left + gap)
        : Math.max(0, canvas.right - bounds.left + gap);
}
