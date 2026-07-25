import {
    BaseEdge,
    getSmoothStepPath,
    type Edge,
    type EdgeProps,
} from "@xyflow/react";

export type ResponsibilityEdgeModel = Edge<
    { readonly relationship: "ownership" | "add" },
    "responsibility"
>;

export function ResponsibilityEdge({
    id,
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
}: EdgeProps<ResponsibilityEdgeModel>) {
    const [path] = getSmoothStepPath({
        borderRadius: 10,
        offset: 24,
        sourcePosition,
        sourceX,
        sourceY,
        targetPosition,
        targetX,
        targetY,
    });
    return (
        <BaseEdge
            className="team-responsibility-edge"
            id={id}
            interactionWidth={0}
            path={path}
        />
    );
}
