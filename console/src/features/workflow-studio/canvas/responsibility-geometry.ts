import { getBezierPath, type Position } from "@xyflow/react";

export interface ResponsibilityGeometry {
    readonly sourceX: number;
    readonly sourceY: number;
    readonly sourcePosition: Position;
    readonly targetX: number;
    readonly targetY: number;
    readonly targetPosition: Position;
}

export function responsibilitySegments(
    geometry: ResponsibilityGeometry,
): readonly string[] {
    const [path] = getBezierPath(geometry);
    return [path];
}
