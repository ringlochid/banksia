import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
    type PointerEvent,
    type RefObject,
} from "react";

import { ExternalLink } from "lucide-react";

import { classNames } from "../../lib/classNames";
import type { TaskGraphEdge, TaskGraphNode } from "./task-detail-model";

interface GraphLayout {
    readonly activeLineage: ReadonlySet<string>;
    readonly height: number;
    readonly nodes: readonly GraphLayoutNode[];
    readonly parentByNodeKey: ReadonlyMap<string, string>;
    readonly positionByNodeKey: ReadonlyMap<string, GraphNodePosition>;
    readonly width: number;
}

interface GraphLayoutNode extends TaskGraphNode {
    readonly height: number;
    readonly width: number;
    readonly x: number;
    readonly y: number;
}

interface GraphNodePosition {
    readonly height: number;
    readonly width: number;
    readonly x: number;
    readonly y: number;
}

interface CameraTransform {
    readonly scale: number;
    readonly tx: number;
    readonly ty: number;
}

interface DragOrigin {
    readonly clientX: number;
    readonly clientY: number;
    readonly camera: CameraTransform;
}

interface EdgeGeometry {
    readonly arrow: string;
    readonly d: string;
}

interface GraphViewport {
    readonly height: number;
    readonly width: number;
}

interface GraphBounds {
    readonly maxX: number;
    readonly maxY: number;
    readonly minX: number;
    readonly minY: number;
}

type GraphTone = "active" | "amber" | "gray" | "green" | "root";

const GRAPH_LABEL_FONT_SIZE = 13;
const GRAPH_NODE_HEIGHT = 56;
const GRAPH_LEVEL_GAP = 156;
const GRAPH_LEFT_PAD = 72;
const GRAPH_BOTTOM_PAD = 92;
const GRAPH_MIN_HEIGHT = 580;
const GRAPH_MIN_WIDTH = 1180;
const GRAPH_TOP_PAD = 84;
const GRAPH_MANUAL_ZOOM_STEP = 1.1;
const GRAPH_MAX_AUTO_SCALE = 5;
const GRAPH_MAX_VISUAL_SCALE = 5;
const GRAPH_MIN_VISUAL_SCALE = 0.7;
const GRAPH_AUTO_FALLBACK_SCALE = 1.85;
const GRAPH_AUTO_FIT_X_PAD = 104;
const GRAPH_AUTO_FIT_Y_PAD = 32;
const GRAPH_AUTO_VERTICAL_FILL = 0.88;
const GRAPH_READABLE_LABEL_PX = 12.5;
const GRAPH_READABLE_LABEL_PX_MAX = 15.2;

const edgePriority: Record<TaskGraphEdge["kind"], number> = {
    structural: 2,
    staged: 3,
};

export function TaskGraph({
    edges,
    nodes,
    onOpenDetail,
    onSelectNode,
    selectedNodeKey,
}: {
    readonly edges: readonly TaskGraphEdge[];
    readonly nodes: readonly TaskGraphNode[];
    readonly onOpenDetail: () => void;
    readonly onSelectNode: (nodeKey: string) => void;
    readonly selectedNodeKey: string | null;
}) {
    const selectedGraphNodeKey = resolveSelectedNodeKey(nodes, selectedNodeKey);
    const layout = useMemo(
        () => buildGraphLayout({ edges, nodes, selectedNodeKey: selectedGraphNodeKey }),
        [edges, nodes, selectedGraphNodeKey],
    );
    const svgRef = useRef<SVGSVGElement>(null);
    const viewport = useSvgViewport(svgRef);
    const graphCamera = useGraphCamera({
        layout,
        selectedNodeKey: selectedGraphNodeKey,
        svgRef,
        viewport,
    });
    const visibleZoomPercent = Math.round(graphCamera.camera.scale * 100);

    return (
        <section className="min-w-0 overflow-hidden rounded-[22px] border border-outline-soft bg-surface-low shadow-panel">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-outline-soft px-4 py-3 sm:px-5">
                <p className="font-mono text-label font-medium text-muted">Execution graph</p>
                <button
                    className="inline-flex h-control items-center justify-center gap-2 rounded-control border border-primary bg-primary px-4 text-utility font-semibold text-white shadow-sm transition-colors hover:bg-[#1d4ed8]"
                    onClick={onOpenDetail}
                    type="button"
                >
                    <span className="min-w-0 truncate">Open detail</span>
                    <ExternalLink aria-hidden="true" className="size-4 shrink-0" />
                </button>
            </header>

            <div className="relative p-4 sm:p-5">
                <div className="overflow-hidden rounded-[20px] border border-outline-soft bg-surface-low shadow-hairline">
                    <GraphCanvas
                        camera={graphCamera.camera}
                        edges={edges}
                        isDragging={graphCamera.isDragging}
                        layout={layout}
                        onOpenDetail={onOpenDetail}
                        onPointerDown={graphCamera.handlePointerDown}
                        onPointerLeave={graphCamera.handlePointerLeave}
                        onPointerMove={graphCamera.handlePointerMove}
                        onPointerUp={graphCamera.handlePointerUp}
                        onSelectNode={onSelectNode}
                        selectedNodeKey={selectedGraphNodeKey}
                        svgRef={svgRef}
                    />
                </div>

                <div className="absolute bottom-8 right-8 flex items-center gap-2 rounded-full border border-outline-soft bg-surface px-2 py-2 shadow-hairline">
                    <GraphZoomButton label="Zoom out graph" onClick={graphCamera.zoomOut}>
                        −
                    </GraphZoomButton>
                    <span className="min-w-14 text-center font-mono text-utility text-muted">
                        {visibleZoomPercent}%
                    </span>
                    <GraphZoomButton label="Zoom in graph" onClick={graphCamera.zoomIn}>
                        +
                    </GraphZoomButton>
                    <GraphZoomButton label="Reset graph zoom" onClick={graphCamera.reset}>
                        ↺
                    </GraphZoomButton>
                </div>
            </div>
        </section>
    );
}

function GraphCanvas({
    camera,
    edges,
    isDragging,
    layout,
    onOpenDetail,
    onPointerDown,
    onPointerLeave,
    onPointerMove,
    onPointerUp,
    onSelectNode,
    selectedNodeKey,
    svgRef,
}: {
    readonly camera: CameraTransform;
    readonly edges: readonly TaskGraphEdge[];
    readonly isDragging: boolean;
    readonly layout: GraphLayout;
    readonly onOpenDetail: () => void;
    readonly onPointerDown: (event: PointerEvent<SVGSVGElement>) => void;
    readonly onPointerLeave: () => void;
    readonly onPointerMove: (event: PointerEvent<SVGSVGElement>) => void;
    readonly onPointerUp: (event: PointerEvent<SVGSVGElement>) => void;
    readonly onSelectNode: (nodeKey: string) => void;
    readonly selectedNodeKey: string;
    readonly svgRef: RefObject<SVGSVGElement | null>;
}) {
    return (
        <svg
            aria-label="Execution graph"
            className={classNames(
                "block h-[500px] w-full touch-none select-none bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.96),transparent_24%),radial-gradient(circle_at_top_right,rgba(99,102,241,0.12),transparent_22%),radial-gradient(circle_at_bottom_left,rgba(52,211,153,0.07),transparent_18%),linear-gradient(180deg,#fff,#f7f4ef)] sm:h-[560px] xl:h-[620px]",
                isDragging ? "cursor-grabbing" : "cursor-grab",
            )}
            onPointerDown={onPointerDown}
            onPointerLeave={onPointerLeave}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            ref={svgRef}
            role="group"
            viewBox={`0 0 ${String(layout.width)} ${String(layout.height)}`}
        >
            <GraphDefinitions />
            <rect fill="url(#task-detail-grid-dots)" height={layout.height} width={layout.width} />
            <g
                transform={`translate(${String(camera.tx)} ${String(camera.ty)}) scale(${String(camera.scale)})`}
            >
                <GraphEdges edges={edges} layout={layout} selectedNodeKey={selectedNodeKey} />
                <GraphNodes
                    layout={layout}
                    onOpenDetail={onOpenDetail}
                    onSelectNode={onSelectNode}
                    selectedNodeKey={selectedNodeKey}
                />
            </g>
        </svg>
    );
}

function GraphDefinitions() {
    return (
        <defs>
            <linearGradient id="task-detail-node-root" x1="0%" x2="100%" y1="0%" y2="100%">
                <stop offset="0%" stopColor="#fcf8ff" />
                <stop offset="100%" stopColor="#f2e8ff" />
            </linearGradient>
            <linearGradient id="task-detail-node-blue" x1="0%" x2="100%" y1="0%" y2="100%">
                <stop offset="0%" stopColor="#f7f9ff" />
                <stop offset="100%" stopColor="#eef2ff" />
            </linearGradient>
            <linearGradient id="task-detail-node-green" x1="0%" x2="100%" y1="0%" y2="100%">
                <stop offset="0%" stopColor="#fbfffd" />
                <stop offset="100%" stopColor="#eefdf5" />
            </linearGradient>
            <linearGradient id="task-detail-node-amber" x1="0%" x2="100%" y1="0%" y2="100%">
                <stop offset="0%" stopColor="#fffdfa" />
                <stop offset="100%" stopColor="#fff5e6" />
            </linearGradient>
            <linearGradient id="task-detail-node-gray" x1="0%" x2="100%" y1="0%" y2="100%">
                <stop offset="0%" stopColor="#ffffff" />
                <stop offset="100%" stopColor="#f6f8fb" />
            </linearGradient>
            <pattern
                height="34"
                id="task-detail-grid-dots"
                patternUnits="userSpaceOnUse"
                width="34"
                x="0"
                y="0"
            >
                <circle cx="2" cy="2" fill="rgba(150,160,174,0.18)" r="1.1" />
            </pattern>
        </defs>
    );
}

function GraphEdges({
    edges,
    layout,
    selectedNodeKey,
}: {
    readonly edges: readonly TaskGraphEdge[];
    readonly layout: GraphLayout;
    readonly selectedNodeKey: string;
}) {
    const edgeKeys = new Set<string>();

    return (
        <>
            {edges.map((edge) => {
                const from = layout.positionByNodeKey.get(edge.fromNodeKey);
                const to = layout.positionByNodeKey.get(edge.toNodeKey);
                if (from === undefined || to === undefined) {
                    return null;
                }

                const edgeKey = `${edge.fromNodeKey}\u0000${edge.toNodeKey}\u0000${edge.kind}`;
                if (edgeKeys.has(edgeKey)) {
                    return null;
                }
                edgeKeys.add(edgeKey);

                const isLinked =
                    edge.fromNodeKey === selectedNodeKey || edge.toNodeKey === selectedNodeKey;
                const isActiveLineage =
                    layout.activeLineage.has(edge.fromNodeKey) &&
                    layout.activeLineage.has(edge.toNodeKey);
                const isEmphasized = isLinked || isActiveLineage;
                const geometry = buildEdgeGeometry(from, to);
                const color = edgeColor(edge.kind, isActiveLineage);
                const opacity = isLinked ? 1 : isEmphasized ? 0.7 : 0.56;

                return (
                    <g key={`${edge.fromNodeKey}-${edge.toNodeKey}-${edge.kind}`}>
                        <path
                            className={classNames(
                                "fill-none transition-opacity",
                                edge.kind === "staged" && "[stroke-dasharray:7_9]",
                            )}
                            d={geometry.d}
                            opacity={opacity}
                            stroke={color}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={isActiveLineage ? 3.8 : edge.kind === "staged" ? 3.4 : 2.6}
                        />
                        <polygon fill={color} opacity={opacity} points={geometry.arrow} />
                    </g>
                );
            })}
        </>
    );
}

function GraphNodes({
    layout,
    onOpenDetail,
    onSelectNode,
    selectedNodeKey,
}: {
    readonly layout: GraphLayout;
    readonly onOpenDetail: () => void;
    readonly onSelectNode: (nodeKey: string) => void;
    readonly selectedNodeKey: string;
}) {
    return (
        <>
            {layout.nodes.map((node) => {
                const tone = nodeTone(node);
                const colors = toneColors(tone);
                const isSelected = node.nodeKey === selectedNodeKey;
                const isEmphasized = isSelected || layout.activeLineage.has(node.nodeKey);

                return (
                    <g
                        aria-label={`${graphLabel(node)} ${node.status} ${node.summary}`}
                        className={classNames(
                            "cursor-pointer outline-none transition-opacity",
                            !isEmphasized && "opacity-45",
                        )}
                        data-graph-node="true"
                        key={node.nodeKey}
                        onClick={() => {
                            onSelectNode(node.nodeKey);
                        }}
                        onDoubleClick={() => {
                            onSelectNode(node.nodeKey);
                            onOpenDetail();
                        }}
                        onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                onSelectNode(node.nodeKey);
                            }
                        }}
                        role="button"
                        tabIndex={0}
                        transform={`translate(${String(node.x)}, ${String(node.y)})`}
                    >
                        <rect
                            fill={colors.fill}
                            filter={
                                isSelected
                                    ? "drop-shadow(0 18px 28px rgba(99, 102, 241, 0.22))"
                                    : "drop-shadow(0 14px 24px rgba(148, 163, 184, 0.16))"
                            }
                            height={node.height}
                            rx="18"
                            stroke={colors.stroke}
                            strokeWidth={
                                isSelected ? 3.4 : layout.activeLineage.has(node.nodeKey) ? 2.5 : 2
                            }
                            width={node.width}
                            x={-node.width / 2}
                            y={-node.height / 2}
                        />
                        <text
                            dominantBaseline="middle"
                            fill={colors.title}
                            fontFamily="JetBrains Mono, monospace"
                            fontSize="13"
                            fontWeight="500"
                            pointerEvents="none"
                            textAnchor="middle"
                            x="0"
                            y="2"
                        >
                            {graphLabel(node)}
                        </text>
                    </g>
                );
            })}
        </>
    );
}

function GraphZoomButton({
    children,
    label,
    onClick,
}: {
    readonly children: string;
    readonly label: string;
    readonly onClick: () => void;
}) {
    return (
        <button
            aria-label={label}
            className="flex size-9 items-center justify-center rounded-full bg-surface-muted text-lg text-foreground transition-colors hover:bg-surface-high"
            onClick={onClick}
            title={label}
            type="button"
        >
            {children}
        </button>
    );
}

function buildGraphLayout({
    edges,
    nodes,
    selectedNodeKey,
}: {
    readonly edges: readonly TaskGraphEdge[];
    readonly nodes: readonly TaskGraphNode[];
    readonly selectedNodeKey: string;
}): GraphLayout {
    const orderedNodes = [...nodes].sort((left, right) => left.order - right.order);
    const nodeByKey = new Map(orderedNodes.map((node) => [node.nodeKey, node]));
    const parentByNodeKey = buildParentMap(edges, orderedNodes);
    const childrenByNodeKey = buildChildrenMap(orderedNodes, parentByNodeKey);
    const rootNodeKey = resolveRootNodeKey(orderedNodes, parentByNodeKey);
    const subtreeWidthMemo = new Map<string, number>();
    const positionByNodeKey = new Map<string, GraphNodePosition>();
    const visited = new Set<string>();

    const rootWidth = computeSubtreeWidth({
        childrenByNodeKey,
        memo: subtreeWidthMemo,
        nodeByKey,
        nodeKey: rootNodeKey,
    });

    placeNode({
        childrenByNodeKey,
        left: GRAPH_LEFT_PAD,
        memo: subtreeWidthMemo,
        nodeByKey,
        nodeKey: rootNodeKey,
        positions: positionByNodeKey,
        depth: 0,
        visited,
    });

    let detachedCursor = GRAPH_LEFT_PAD;
    for (const node of orderedNodes) {
        if (visited.has(node.nodeKey)) {
            continue;
        }
        const nodeWidth = measureNodeWidth(node);
        positionByNodeKey.set(node.nodeKey, {
            height: GRAPH_NODE_HEIGHT,
            width: nodeWidth,
            x: detachedCursor + nodeWidth / 2,
            y: GRAPH_TOP_PAD + GRAPH_LEVEL_GAP * 3,
        });
        detachedCursor += nodeWidth + 56;
    }

    const activeLineage = buildActiveLineage(selectedNodeKey, parentByNodeKey);
    const layoutNodes = orderedNodes.map((node): GraphLayoutNode => {
        const position = positionByNodeKey.get(node.nodeKey) ?? {
            height: GRAPH_NODE_HEIGHT,
            width: measureNodeWidth(node),
            x: GRAPH_LEFT_PAD,
            y: GRAPH_TOP_PAD,
        };
        return { ...node, ...position };
    });
    const height = Math.max(
        GRAPH_MIN_HEIGHT,
        ...layoutNodes.map((node) => node.y + node.height / 2 + GRAPH_BOTTOM_PAD),
    );
    const width = Math.max(GRAPH_MIN_WIDTH, rootWidth + GRAPH_LEFT_PAD * 2, detachedCursor);

    return {
        activeLineage,
        height,
        nodes: layoutNodes,
        parentByNodeKey,
        positionByNodeKey,
        width,
    };
}

function buildParentMap(
    edges: readonly TaskGraphEdge[],
    orderedNodes: readonly TaskGraphNode[],
): ReadonlyMap<string, string> {
    const nodeKeys = new Set(orderedNodes.map((node) => node.nodeKey));
    const hasRootNode = nodeKeys.has("root");
    const parentByNodeKey = new Map<string, string>();
    const priorityByNodeKey = new Map<string, number>();

    for (const edge of edges) {
        if (!nodeKeys.has(edge.fromNodeKey) || !nodeKeys.has(edge.toNodeKey)) {
            continue;
        }
        if (hasRootNode && edge.toNodeKey === "root") {
            continue;
        }
        if (wouldCreateParentCycle(parentByNodeKey, edge.fromNodeKey, edge.toNodeKey)) {
            continue;
        }
        const currentPriority = priorityByNodeKey.get(edge.toNodeKey) ?? -1;
        const nextPriority = edgePriority[edge.kind];
        if (nextPriority < currentPriority) {
            continue;
        }
        parentByNodeKey.set(edge.toNodeKey, edge.fromNodeKey);
        priorityByNodeKey.set(edge.toNodeKey, nextPriority);
    }

    return parentByNodeKey;
}

function wouldCreateParentCycle(
    parentByNodeKey: ReadonlyMap<string, string>,
    parentNodeKey: string,
    childNodeKey: string,
): boolean {
    let cursor: string | undefined = parentNodeKey;
    const seen = new Set<string>();
    while (cursor !== undefined) {
        if (cursor === childNodeKey) {
            return true;
        }
        if (seen.has(cursor)) {
            return true;
        }
        seen.add(cursor);
        cursor = parentByNodeKey.get(cursor);
    }
    return false;
}

function buildChildrenMap(
    orderedNodes: readonly TaskGraphNode[],
    parentByNodeKey: ReadonlyMap<string, string>,
): ReadonlyMap<string, readonly string[]> {
    const childrenByNodeKey = new Map<string, string[]>(
        orderedNodes.map((node) => [node.nodeKey, []]),
    );

    for (const node of orderedNodes) {
        const parentNodeKey = parentByNodeKey.get(node.nodeKey);
        if (parentNodeKey === undefined) {
            continue;
        }
        childrenByNodeKey.get(parentNodeKey)?.push(node.nodeKey);
    }

    return childrenByNodeKey;
}

function resolveRootNodeKey(
    orderedNodes: readonly TaskGraphNode[],
    parentByNodeKey: ReadonlyMap<string, string>,
): string {
    const rootNode = orderedNodes.find((node) => node.nodeKey === "root");
    if (rootNode !== undefined) {
        return rootNode.nodeKey;
    }

    const rootlessNode = orderedNodes.find((node) => !parentByNodeKey.has(node.nodeKey));
    if (rootlessNode !== undefined) {
        return rootlessNode.nodeKey;
    }

    return orderedNodes[0]?.nodeKey ?? "root";
}

function computeSubtreeWidth({
    childrenByNodeKey,
    memo,
    nodeByKey,
    nodeKey,
    visiting = new Set<string>(),
}: {
    readonly childrenByNodeKey: ReadonlyMap<string, readonly string[]>;
    readonly memo: Map<string, number>;
    readonly nodeByKey: ReadonlyMap<string, TaskGraphNode>;
    readonly nodeKey: string;
    readonly visiting?: Set<string>;
}): number {
    const existingWidth = memo.get(nodeKey);
    if (existingWidth !== undefined) {
        return existingWidth;
    }
    if (visiting.has(nodeKey)) {
        return 0;
    }

    visiting.add(nodeKey);
    const node = nodeByKey.get(nodeKey);
    const ownWidth = measureNodeWidth(node) + 56;
    const childNodeKeys = childrenByNodeKey.get(nodeKey) ?? [];
    if (childNodeKeys.length === 0) {
        memo.set(nodeKey, ownWidth);
        visiting.delete(nodeKey);
        return ownWidth;
    }

    const childWidth = childNodeKeys.reduce(
        (width, childNodeKey) =>
            width +
            computeSubtreeWidth({
                childrenByNodeKey,
                memo,
                nodeByKey,
                nodeKey: childNodeKey,
                visiting,
            }),
        0,
    );
    const width = Math.max(ownWidth, childWidth);
    memo.set(nodeKey, width);
    visiting.delete(nodeKey);
    return width;
}

function placeNode({
    childrenByNodeKey,
    depth,
    left,
    memo,
    nodeByKey,
    nodeKey,
    positions,
    visited,
}: {
    readonly childrenByNodeKey: ReadonlyMap<string, readonly string[]>;
    readonly depth: number;
    readonly left: number;
    readonly memo: ReadonlyMap<string, number>;
    readonly nodeByKey: ReadonlyMap<string, TaskGraphNode>;
    readonly nodeKey: string;
    readonly positions: Map<string, GraphNodePosition>;
    readonly visited: Set<string>;
}) {
    if (visited.has(nodeKey)) {
        return;
    }

    const totalWidth = memo.get(nodeKey) ?? measureNodeWidth(nodeByKey.get(nodeKey)) + 56;
    const nodeWidth = measureNodeWidth(nodeByKey.get(nodeKey));
    positions.set(nodeKey, {
        height: GRAPH_NODE_HEIGHT,
        width: nodeWidth,
        x: left + totalWidth / 2,
        y: GRAPH_TOP_PAD + depth * GRAPH_LEVEL_GAP,
    });
    visited.add(nodeKey);

    let cursor = left;
    for (const childNodeKey of childrenByNodeKey.get(nodeKey) ?? []) {
        const childWidth = memo.get(childNodeKey) ?? 0;
        placeNode({
            childrenByNodeKey,
            depth: depth + 1,
            left: cursor,
            memo,
            nodeByKey,
            nodeKey: childNodeKey,
            positions,
            visited,
        });
        cursor += childWidth;
    }
}

function buildActiveLineage(
    selectedNodeKey: string,
    parentByNodeKey: ReadonlyMap<string, string>,
): ReadonlySet<string> {
    const lineage = new Set<string>([selectedNodeKey]);
    let cursor = selectedNodeKey;
    for (;;) {
        const parent = parentByNodeKey.get(cursor);
        if (parent === undefined || lineage.has(parent)) {
            break;
        }
        lineage.add(parent);
        cursor = parent;
    }
    return lineage;
}

function buildCameraTransform(
    layout: GraphLayout,
    selectedNodeKey: string,
    viewport: GraphViewport | null,
): CameraTransform {
    const bounds = graphAutoFitBounds(layout, selectedNodeKey);
    const centerX = (bounds.maxX + bounds.minX) / 2;
    const centerY = (bounds.maxY + bounds.minY) / 2;
    const scale = autoFitGraphScale(layout, viewport, bounds);

    return {
        scale,
        tx: layout.width * 0.5 - centerX * scale,
        ty: layout.height * 0.5 - centerY * scale,
    };
}

function centerCameraOnFocus(
    layout: GraphLayout,
    selectedNodeKey: string,
    scale: number,
): CameraTransform {
    const bounds = graphFocusBounds(layout, selectedNodeKey);
    const centerX = (bounds.maxX + bounds.minX) / 2;
    const centerY = (bounds.maxY + bounds.minY) / 2;

    return {
        scale,
        tx: layout.width * 0.5 - centerX * scale,
        ty: layout.height * 0.5 - centerY * scale,
    };
}

function zoomCameraAroundPoint({
    clientX,
    clientY,
    current,
    layout,
    nextScale,
    svgElement,
}: {
    readonly clientX: number;
    readonly clientY: number;
    readonly current: CameraTransform;
    readonly layout: GraphLayout;
    readonly nextScale: number;
    readonly svgElement: SVGSVGElement;
}): CameraTransform {
    const rect = svgElement.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
        return current;
    }

    const svgX = ((clientX - rect.left) / rect.width) * layout.width;
    const svgY = ((clientY - rect.top) / rect.height) * layout.height;
    const worldX = (svgX - current.tx) / current.scale;
    const worldY = (svgY - current.ty) / current.scale;
    const scale = clamp(nextScale, GRAPH_MIN_VISUAL_SCALE, GRAPH_MAX_VISUAL_SCALE);

    return {
        scale,
        tx: svgX - worldX * scale,
        ty: svgY - worldY * scale,
    };
}

function readableGraphScale(layout: GraphLayout, viewport: GraphViewport | null): number {
    if (viewport === null) {
        return GRAPH_AUTO_FALLBACK_SCALE;
    }
    const baseScale = graphViewportBaseScale(layout, viewport);
    if (!Number.isFinite(baseScale) || baseScale <= 0) {
        return GRAPH_AUTO_FALLBACK_SCALE;
    }
    const widthPressure = layout.width / Math.max(viewport.width, 1);
    const heightPressure = layout.height / Math.max(viewport.height, 1);
    const pressure = Math.max(widthPressure, heightPressure);
    const readableLabelPx = clamp(
        GRAPH_READABLE_LABEL_PX + Math.max(0, pressure - 1.25) * 2.8,
        GRAPH_READABLE_LABEL_PX,
        GRAPH_READABLE_LABEL_PX_MAX,
    );

    return clamp(
        readableLabelPx / (GRAPH_LABEL_FONT_SIZE * baseScale),
        GRAPH_MIN_VISUAL_SCALE,
        readableGraphScaleLimit(layout),
    );
}

function autoFitGraphScale(
    layout: GraphLayout,
    viewport: GraphViewport | null,
    bounds: GraphBounds,
): number {
    if (viewport === null) {
        return readableGraphScale(layout, viewport);
    }

    const baseScale = graphViewportBaseScale(layout, viewport);
    const focusHeight = Math.max(bounds.maxY - bounds.minY, GRAPH_NODE_HEIGHT);
    const verticalFitScale =
        (viewport.height * GRAPH_AUTO_VERTICAL_FILL) / (focusHeight * baseScale);
    const readableScale = readableGraphScale(layout, viewport);

    if (!Number.isFinite(verticalFitScale) || verticalFitScale <= 0) {
        return readableScale;
    }

    return clamp(
        Math.max(verticalFitScale, readableScale),
        GRAPH_MIN_VISUAL_SCALE,
        GRAPH_MAX_AUTO_SCALE,
    );
}

function graphViewportBaseScale(layout: GraphLayout, viewport: GraphViewport): number {
    return Math.min(viewport.width / layout.width, viewport.height / layout.height);
}

function readableGraphScaleLimit(layout: GraphLayout): number {
    const levelCounts = new Map<number, number>();
    for (const node of layout.nodes) {
        const level = Math.max(0, Math.round((node.y - GRAPH_TOP_PAD) / GRAPH_LEVEL_GAP));
        levelCounts.set(level, (levelCounts.get(level) ?? 0) + 1);
    }

    const depth = Math.max(...levelCounts.keys(), 0) + 1;
    const breadth = Math.max(...levelCounts.values(), 1);
    const breadthBonus = clamp((breadth - 3) * 0.03, 0, 0.18);

    return clamp(1.48 + depth * 0.16 + breadthBonus, 1.7, GRAPH_MAX_AUTO_SCALE);
}

function useSvgViewport(ref: RefObject<SVGSVGElement | null>): GraphViewport | null {
    const [viewport, setViewport] = useState<GraphViewport | null>(null);

    useLayoutEffect(() => {
        const element = ref.current;
        if (element === null) {
            return;
        }

        const updateViewport = () => {
            const rect = element.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) {
                return;
            }
            setViewport((current) =>
                current !== null &&
                Math.abs(current.width - rect.width) < 0.5 &&
                Math.abs(current.height - rect.height) < 0.5
                    ? current
                    : { height: rect.height, width: rect.width },
            );
        };

        updateViewport();
        const observer =
            typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateViewport);
        observer?.observe(element);
        window.addEventListener("resize", updateViewport);
        return () => {
            observer?.disconnect();
            window.removeEventListener("resize", updateViewport);
        };
    }, [ref]);

    return viewport;
}

function useGraphCamera({
    layout,
    selectedNodeKey,
    svgRef,
    viewport,
}: {
    readonly layout: GraphLayout;
    readonly selectedNodeKey: string;
    readonly svgRef: RefObject<SVGSVGElement | null>;
    readonly viewport: GraphViewport | null;
}) {
    const [camera, setCamera] = useState<CameraTransform>(() =>
        buildCameraTransform(layout, selectedNodeKey, viewport),
    );
    const cameraRef = useRef(camera);
    const [isDragging, setIsDragging] = useState(false);
    const dragOriginRef = useRef<DragOrigin | null>(null);
    const lastFitKeyRef = useRef<string | null>(null);
    const lastSelectedNodeKeyRef = useRef<string | null>(null);
    const layoutKey = buildLayoutKey(layout);
    const viewportKey =
        viewport === null
            ? "viewport-pending"
            : `${String(Math.round(viewport.width))}x${String(Math.round(viewport.height))}`;

    useEffect(() => {
        cameraRef.current = camera;
    }, [camera]);

    useLayoutEffect(() => {
        const fitKey = `${layoutKey}:${viewportKey}`;
        const shouldFit = lastFitKeyRef.current !== fitKey;
        const shouldCenterSelection =
            !shouldFit && lastSelectedNodeKeyRef.current !== selectedNodeKey;

        setCamera((current) => {
            if (shouldFit) {
                return buildCameraTransform(layout, selectedNodeKey, viewport);
            }
            if (shouldCenterSelection) {
                return centerCameraOnFocus(layout, selectedNodeKey, current.scale);
            }
            return current;
        });

        lastFitKeyRef.current = fitKey;
        lastSelectedNodeKeyRef.current = selectedNodeKey;
    }, [layout, layoutKey, selectedNodeKey, viewport, viewportKey]);

    const reset = useCallback(() => {
        setCamera(buildCameraTransform(layout, selectedNodeKey, viewport));
    }, [layout, selectedNodeKey, viewport]);

    const zoomAround = useCallback(
        (clientX: number, clientY: number, nextScale: number) => {
            const svgElement = svgRef.current;
            if (svgElement === null) {
                return;
            }

            setCamera((current) =>
                zoomCameraAroundPoint({
                    clientX,
                    clientY,
                    current,
                    layout,
                    nextScale,
                    svgElement,
                }),
            );
        },
        [layout, svgRef],
    );

    const zoomFromCenter = useCallback(
        (factor: number) => {
            const svgElement = svgRef.current;
            if (svgElement === null) {
                return;
            }

            const rect = svgElement.getBoundingClientRect();
            zoomAround(
                rect.left + rect.width / 2,
                rect.top + rect.height / 2,
                camera.scale * factor,
            );
        },
        [camera.scale, svgRef, zoomAround],
    );

    useEffect(() => {
        const svgElement = svgRef.current;
        if (svgElement === null) {
            return undefined;
        }

        const handleWheel = (event: globalThis.WheelEvent) => {
            event.preventDefault();
            zoomAround(
                event.clientX,
                event.clientY,
                cameraRef.current.scale * (event.deltaY < 0 ? 1.08 : 0.92),
            );
        };

        svgElement.addEventListener("wheel", handleWheel, { passive: false });
        return () => {
            svgElement.removeEventListener("wheel", handleWheel);
        };
    }, [svgRef, zoomAround]);

    const handlePointerDown = useCallback(
        (event: PointerEvent<SVGSVGElement>) => {
            if (isGraphNodeTarget(event.target)) {
                return;
            }

            dragOriginRef.current = {
                camera,
                clientX: event.clientX,
                clientY: event.clientY,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
            setIsDragging(true);
        },
        [camera],
    );

    const handlePointerMove = useCallback(
        (event: PointerEvent<SVGSVGElement>) => {
            const dragOrigin = dragOriginRef.current;
            if (dragOrigin === null) {
                return;
            }

            const rect = event.currentTarget.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) {
                return;
            }

            const dx = ((event.clientX - dragOrigin.clientX) / rect.width) * layout.width;
            const dy = ((event.clientY - dragOrigin.clientY) / rect.height) * layout.height;
            setCamera({
                ...dragOrigin.camera,
                tx: dragOrigin.camera.tx + dx,
                ty: dragOrigin.camera.ty + dy,
            });
        },
        [layout.height, layout.width],
    );

    const endDrag = useCallback((event?: PointerEvent<SVGSVGElement>) => {
        if (event?.currentTarget.hasPointerCapture(event.pointerId) === true) {
            event.currentTarget.releasePointerCapture(event.pointerId);
        }
        dragOriginRef.current = null;
        setIsDragging(false);
    }, []);

    return {
        camera,
        handlePointerDown,
        handlePointerLeave: endDrag,
        handlePointerMove,
        handlePointerUp: endDrag,
        isDragging,
        reset,
        zoomIn: () => {
            zoomFromCenter(GRAPH_MANUAL_ZOOM_STEP);
        },
        zoomOut: () => {
            zoomFromCenter(1 / GRAPH_MANUAL_ZOOM_STEP);
        },
    };
}

function buildLayoutKey(layout: GraphLayout): string {
    return `${String(layout.width)}:${String(layout.height)}:${layout.nodes
        .map(
            (node) => `${node.nodeKey}@${String(Math.round(node.x))},${String(Math.round(node.y))}`,
        )
        .join("|")}`;
}

function isGraphNodeTarget(target: EventTarget): boolean {
    return target instanceof Element && target.closest('[data-graph-node="true"]') !== null;
}

function graphFocusBounds(layout: GraphLayout, selectedNodeKey: string): GraphBounds {
    const selectedPosition = layout.positionByNodeKey.get(selectedNodeKey);
    if (selectedPosition === undefined) {
        return fullGraphBounds(layout);
    }

    return {
        maxX: selectedPosition.x + selectedPosition.width / 2 + 104,
        maxY: selectedPosition.y + selectedPosition.height / 2 + 88,
        minX: selectedPosition.x - selectedPosition.width / 2 - 104,
        minY: selectedPosition.y - selectedPosition.height / 2 - 88,
    };
}

function graphAutoFitBounds(layout: GraphLayout, selectedNodeKey: string): GraphBounds {
    const nodeKeys = new Set<string>();
    let cursor: string | undefined = selectedNodeKey;

    while (cursor !== undefined && !nodeKeys.has(cursor)) {
        nodeKeys.add(cursor);
        cursor = layout.parentByNodeKey.get(cursor);
    }

    for (const node of layout.nodes) {
        if (layout.parentByNodeKey.get(node.nodeKey) === selectedNodeKey) {
            nodeKeys.add(node.nodeKey);
        }
    }

    return graphBoundsForNodeKeys(layout, nodeKeys, {
        x: GRAPH_AUTO_FIT_X_PAD,
        y: GRAPH_AUTO_FIT_Y_PAD,
    });
}

function graphBoundsForNodeKeys(
    layout: GraphLayout,
    nodeKeys: ReadonlySet<string>,
    padding: {
        readonly x: number;
        readonly y: number;
    },
): GraphBounds {
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;

    for (const nodeKey of nodeKeys) {
        const position = layout.positionByNodeKey.get(nodeKey);
        if (position === undefined) {
            continue;
        }
        maxX = Math.max(maxX, position.x + position.width / 2 + padding.x);
        maxY = Math.max(maxY, position.y + position.height / 2 + padding.y);
        minX = Math.min(minX, position.x - position.width / 2 - padding.x);
        minY = Math.min(minY, position.y - position.height / 2 - padding.y);
    }

    if (
        !Number.isFinite(maxX) ||
        !Number.isFinite(maxY) ||
        !Number.isFinite(minX) ||
        !Number.isFinite(minY)
    ) {
        return fullGraphBounds(layout);
    }

    return { maxX, maxY, minX, minY };
}

function fullGraphBounds(layout: GraphLayout): GraphBounds {
    return {
        maxX: layout.width,
        maxY: layout.height,
        minX: 0,
        minY: 0,
    };
}

function buildEdgeGeometry(from: GraphNodePosition, to: GraphNodePosition): EdgeGeometry {
    const startX = from.x;
    const startY = from.y + from.height / 2;
    const tipX = to.x;
    const tipY = to.y - to.height / 2 + 2;
    const endY = tipY - 16;
    const bend = Math.max(72, (endY - startY) * 0.48);

    return {
        arrow: buildArrowPolygon(tipX, tipY, tipX, endY - 2),
        d: `M ${String(startX)} ${String(startY)} C ${String(startX)} ${String(startY + bend)}, ${String(tipX)} ${String(endY - bend)}, ${String(tipX)} ${String(endY)}`,
    };
}

function buildArrowPolygon(tipX: number, tipY: number, tailX: number, tailY: number): string {
    const dx = tipX - tailX;
    const dy = tipY - tailY;
    const length = Math.hypot(dx, dy) || 1;
    const ux = dx / length;
    const uy = dy / length;
    const px = -uy;
    const py = ux;
    const size = 10;
    const wing = size * 0.62;
    const baseX = tipX - ux * size;
    const baseY = tipY - uy * size;
    return [
        [tipX, tipY],
        [baseX + px * wing, baseY + py * wing],
        [baseX - px * wing, baseY - py * wing],
    ]
        .map((pair) => pair.join(","))
        .join(" ");
}

function edgeColor(kind: TaskGraphEdge["kind"], isActiveLineage: boolean): string {
    if (isActiveLineage) {
        return "#7b8cff";
    }
    if (kind === "staged") {
        return "#b28af7";
    }
    return "#d7dde7";
}

function nodeTone(node: TaskGraphNode): GraphTone {
    if (node.nodeKey === "root") {
        return "root";
    }
    if (node.status === "done") {
        return "green";
    }
    if (node.nodeKey.includes("human_request")) {
        return "amber";
    }
    if (node.status === "quiet" || node.status === "staged") {
        return "gray";
    }
    return "active";
}

function toneColors(tone: GraphTone): {
    readonly fill: string;
    readonly stroke: string;
    readonly title: string;
} {
    switch (tone) {
        case "root":
            return {
                fill: "url(#task-detail-node-root)",
                stroke: "#b28af7",
                title: "#8b5cf6",
            };
        case "green":
            return {
                fill: "url(#task-detail-node-green)",
                stroke: "#56c98a",
                title: "#2da06a",
            };
        case "amber":
            return {
                fill: "url(#task-detail-node-amber)",
                stroke: "#d8a553",
                title: "#b77916",
            };
        case "gray":
            return {
                fill: "url(#task-detail-node-gray)",
                stroke: "#d7dde7",
                title: "#6b7280",
            };
        case "active":
            return {
                fill: "url(#task-detail-node-blue)",
                stroke: "#7b8cff",
                title: "#5669ea",
            };
    }
}

function resolveSelectedNodeKey(
    nodes: readonly TaskGraphNode[],
    selectedNodeKey: string | null,
): string {
    if (selectedNodeKey !== null) {
        const selectedNode = nodes.find((node) => node.nodeKey === selectedNodeKey);
        if (selectedNode !== undefined) {
            return selectedNode.nodeKey;
        }
    }

    const currentNode = nodes.find((node) => node.isCurrent);
    if (currentNode !== undefined) {
        return currentNode.nodeKey;
    }

    return nodes[0]?.nodeKey ?? "root";
}

function measureNodeWidth(node: TaskGraphNode | undefined): number {
    const label = node === undefined ? "root" : graphLabel(node);
    return Math.max(158, Math.min(260, label.length * 8.4 + 40));
}

function graphLabel(node: TaskGraphNode): string {
    return node.nodeKey;
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}
