import { BaseEdge, type Edge, type EdgeProps } from "@xyflow/react";

import { responsibilitySegments } from "./responsibility-geometry";

export type ResponsibilityEdgeModel = Edge<
    { readonly relationship: "ownership" | "add" },
    "responsibility"
>;

/**
 * Ownership connector.
 *
 * Translated from n8n's `getEdgeRenderData.ts` and `CanvasEdge.vue` at pinned
 * commit 43c6f329fb1fb528259a78f80b163e4ed1405c02: one neutral bezier between
 * visible endpoint ports. Copyright (c) n8n GmbH and contributors. Sustainable
 * Use License; see console/LICENSE and console/NOTICE.
 *
 * A connector means one Member owns another's work. It carries no execution
 * order, so there is no flow animation and no dot travelling along it.
 */

export function ResponsibilityEdge({
    id,
    sourcePosition,
    sourceX,
    sourceY,
    targetPosition,
    targetX,
    targetY,
}: EdgeProps<ResponsibilityEdgeModel>) {
    const segments = responsibilitySegments({
        sourcePosition,
        sourceX,
        sourceY,
        targetPosition,
        targetX,
        targetY,
    });
    return (
        <>
            {segments.map((path, index) => (
                <BaseEdge
                    className="team-responsibility-edge"
                    id={`${id}-${String(index)}`}
                    interactionWidth={0}
                    key={path}
                    path={path}
                />
            ))}
        </>
    );
}
