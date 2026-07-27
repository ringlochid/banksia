import "@xyflow/react/dist/style.css";
import "./team-canvas.css";

import {
    applyNodeChanges,
    Background,
    BackgroundVariant,
    Panel,
    Position,
    ReactFlow,
    type EdgeTypes,
    type NodeChange,
    type NodeTypes,
    type ReactFlowInstance,
} from "@xyflow/react";
import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
    type RefObject,
} from "react";

import type { NormalizedMember } from "../../../api/types";
import type {
    PendingStructure,
    StudioValidationIssue,
} from "../state/contracts";
import { findMember, memberIds } from "../state/tree";
import { AddChildControl, type AddChildNode } from "./AddChildControl";
import { MemberCard, type MemberCardNode } from "./MemberCard";
import {
    ResponsibilityEdge,
    type ResponsibilityEdgeModel,
} from "./ResponsibilityEdge";
import { TeamCanvasControls } from "./TeamCanvasControls";
import { TeamOutline } from "./TeamOutline";
import { memberTitle } from "./member-presentation";
import {
    addNodeId,
    layoutTeam,
    type TeamDimensionsById,
    type TeamNodeDimensions,
} from "./team-layout";
import { TeamViewportCoordinator } from "./use-team-viewport";
import type { TeamStructureEntry } from "./use-team-viewport";

export type TeamFlowNode = MemberCardNode | AddChildNode;

const nodeTypes = {
    "add-child": AddChildControl,
    member: MemberCard,
} satisfies NodeTypes;

const edgeTypes = {
    responsibility: ResponsibilityEdge,
} satisfies EdgeTypes;

export interface TeamCanvasProps {
    readonly collapsedMemberIds: ReadonlySet<string>;
    readonly detailsOpen: boolean;
    readonly disabled: boolean;
    readonly focusRequest: TeamMemberFocusRequest | null;
    readonly issues: readonly StudioValidationIssue[];
    readonly lead: NormalizedMember;
    readonly localAddOpen: boolean;
    readonly onAddChild: (parentMemberId: string) => void;
    readonly onEdit: (memberId: string) => void;
    readonly onOutlineOpenChange: (open: boolean) => void;
    readonly onRemove: (memberId: string) => void;
    readonly onSelect: (memberId: string, openDetails: boolean) => void;
    readonly onToggleCollapse: (memberId: string) => void;
    readonly outlineOpen: boolean;
    readonly pendingStructure: PendingStructure;
    readonly selectedMemberId: string;
}

export interface TeamMemberFocusRequest {
    readonly memberId: string;
    readonly revision: number;
    readonly surface: "canvas" | "outline";
}

export function TeamCanvas({
    collapsedMemberIds,
    detailsOpen,
    disabled,
    focusRequest,
    issues,
    lead,
    localAddOpen,
    onAddChild,
    onEdit,
    onOutlineOpenChange,
    onRemove,
    onSelect,
    onToggleCollapse,
    outlineOpen,
    pendingStructure,
    selectedMemberId,
}: TeamCanvasProps) {
    const canvasRef = useRef<HTMLElement>(null);
    const [dimensionsById, setDimensionsById] = useState<TeamDimensionsById>(
        {},
    );
    const [layoutRevision, setLayoutRevision] = useState(0);
    /**
     * Cards the user has dragged. Presentation state only — it is never sent
     * to the controller and never becomes part of the Workflow. `Tidy team`
     * clears it, which is what puts the hierarchy back in order.
     */
    const [positionOverrides, setPositionOverrides] = useState<
        ReadonlyMap<string, { readonly x: number; readonly y: number }>
    >(() => new Map());

    const tidyTeam = useCallback(() => {
        setPositionOverrides(new Map());
        setLayoutRevision((revision) => revision + 1);
    }, []);
    const flowRef = useRef<ReactFlowInstance<
        TeamFlowNode,
        ResponsibilityEdgeModel
    > | null>(null);
    const activeDragId = useRef<string | null>(null);
    const measurementFrame = useRef<number | null>(null);
    const pendingMeasurements = useRef(new Map<string, TeamNodeDimensions>());
    const visibleMemberIds = useMemo(() => new Set(memberIds(lead)), [lead]);
    const structure = useMemo(() => teamStructure(lead), [lead]);

    useEffect(
        () => () => {
            if (measurementFrame.current !== null) {
                cancelAnimationFrame(measurementFrame.current);
            }
        },
        [],
    );

    const visibleDimensionsById = useMemo(
        () =>
            Object.fromEntries(
                Object.entries(dimensionsById).filter(([memberId]) =>
                    visibleMemberIds.has(memberId),
                ),
            ),
        [dimensionsById, visibleMemberIds],
    );

    const layout = useMemo(() => {
        const layoutInput = {
            collapsedMemberIds,
            dimensionsById: visibleDimensionsById,
            layoutRevision,
            lead,
            selectedMemberId,
        };
        return layoutTeam(layoutInput);
    }, [
        collapsedMemberIds,
        layoutRevision,
        lead,
        selectedMemberId,
        visibleDimensionsById,
    ]);

    const authoredNodes = useMemo<readonly TeamFlowNode[]>(
        () =>
            layout.nodes.map((node): TeamFlowNode => {
                if (node.kind === "add") {
                    const position = addControlPosition(
                        node,
                        layout.nodes,
                        positionOverrides,
                    );
                    return {
                        data: {
                            disabled: disabled || localAddOpen,
                            onAdd: onAddChild,
                            parentMemberId: node.parentId,
                            parentName: memberTitle(
                                findMember(lead, node.parentId)?.member ?? lead,
                            ),
                            pending:
                                pendingStructure?.kind === "add_child" &&
                                pendingStructure.parentMemberId ===
                                    node.parentId,
                        },
                        // The add control follows its parent rather than being
                        // placed by hand.
                        draggable: false,
                        focusable: false,
                        id: addNodeId(node.parentId),
                        position,
                        selectable: false,
                        sourcePosition: Position.Right,
                        style: {
                            height: node.height,
                            width: node.width,
                        },
                        targetPosition: Position.Left,
                        type: "add-child",
                    };
                }
                return {
                    data: {
                        collapsed: collapsedMemberIds.has(node.member.id),
                        issueCount: issueCount(issues, node.member.id),
                        member: node.member,
                        onSelect: (memberId: string) =>
                            onSelect(memberId, true),
                        onToggleCollapse,
                        pending: isMemberPending(
                            pendingStructure,
                            node.member.id,
                        ),
                        selected: selectedMemberId === node.member.id,
                    },
                    draggable: !disabled,
                    focusable: false,
                    id: node.member.id,
                    // A dragged card keeps the position the user gave it until
                    // Tidy team recomputes the layout. Position is presentation
                    // state only; it never reaches the Workflow.
                    position: positionOverrides.get(node.member.id) ?? {
                        x: node.x,
                        y: node.y,
                    },
                    selectable: false,
                    sourcePosition: Position.Right,
                    style: { width: node.width },
                    targetPosition: Position.Left,
                    type: "member",
                };
            }),
        [
            collapsedMemberIds,
            disabled,
            issues,
            layout.nodes,
            lead,
            localAddOpen,
            onAddChild,
            onSelect,
            onToggleCollapse,
            pendingStructure,
            positionOverrides,
            selectedMemberId,
        ],
    );
    const [flowNodes, setFlowNodes] = useState<TeamFlowNode[]>(() => [
        ...authoredNodes,
    ]);

    useEffect(() => {
        if (activeDragId.current !== null) {
            return;
        }
        setFlowNodes((current) =>
            reconcileAuthoredNodes(current, authoredNodes),
        );
    }, [authoredNodes]);

    const edges = useMemo<ResponsibilityEdgeModel[]>(
        () =>
            layout.edges.map((edge) => ({
                data: { relationship: edge.kind },
                deletable: false,
                focusable: false,
                id: edge.id,
                reconnectable: false,
                selectable: false,
                source: edge.source,
                target: edge.target,
                type: "responsibility",
            })),
        [layout.edges],
    );

    const onNodesChange = useCallback(
        (changes: NodeChange<TeamFlowNode>[]) => {
            /*
             * Let XYFlow own transient drag geometry. Rebuilding every authored
             * node from React state on every pointer event repaints the whole
             * canvas and caused the black flash visible in the drag recording.
             * Only the changed node and its attached add control move here;
             * the presentation override is committed on drag stop.
             */
            setFlowNodes((current) =>
                applyTransientNodeChanges(current, changes),
            );

            const measured = changes.filter(
                (change) =>
                    change.type === "dimensions" &&
                    change.dimensions !== undefined &&
                    visibleMemberIds.has(change.id),
            );
            if (measured.length === 0) {
                return;
            }
            for (const change of measured) {
                if (
                    change.type === "dimensions" &&
                    change.dimensions !== undefined
                ) {
                    pendingMeasurements.current.set(
                        change.id,
                        change.dimensions,
                    );
                }
            }
            if (measurementFrame.current === null) {
                measurementFrame.current = requestAnimationFrame(() => {
                    const pending = new Map(pendingMeasurements.current);
                    pendingMeasurements.current.clear();
                    measurementFrame.current = null;
                    setDimensionsById((current) =>
                        mergeMeasuredDimensions(current, pending),
                    );
                });
            }
        },
        [visibleMemberIds],
    );

    const fitTeam = (): void => {
        void flowRef.current?.fitView({
            duration: 220,
            maxZoom: 1,
            padding: 0.18,
        });
    };

    return (
        <section
            aria-label="Team hierarchy canvas"
            className="team-canvas"
            data-team-canvas
            ref={canvasRef}
        >
            <ReactFlow<TeamFlowNode, ResponsibilityEdgeModel>
                deleteKeyCode={null}
                edges={edges}
                edgesFocusable={false}
                edgesReconnectable={false}
                edgeTypes={edgeTypes}
                elementsSelectable={false}
                fitView
                fitViewOptions={{ maxZoom: 1, padding: 0.18 }}
                maxZoom={1.5}
                minZoom={0.25}
                nodeTypes={nodeTypes}
                nodes={flowNodes}
                nodesConnectable={false}
                nodesDraggable={!disabled}
                nodesFocusable={false}
                autoPanOnNodeDrag={false}
                onInit={(instance) => {
                    flowRef.current = instance;
                }}
                onNodeDragStart={(_, node) => {
                    activeDragId.current = node.id;
                }}
                onNodeDragStop={(_, node) => {
                    activeDragId.current = null;
                    if (!visibleMemberIds.has(node.id)) {
                        return;
                    }
                    const position = node.position;
                    setPositionOverrides((current) => {
                        const previous = current.get(node.id);
                        if (
                            previous?.x === position.x &&
                            previous.y === position.y
                        ) {
                            return current;
                        }
                        const next = new Map(current);
                        next.set(node.id, position);
                        return next;
                    });
                }}
                onNodeClick={() => undefined}
                onNodesChange={onNodesChange}
                nodeDragThreshold={4}
                panOnDrag
                proOptions={{ hideAttribution: true }}
                selectionOnDrag={false}
                zoomOnDoubleClick={false}
            >
                <Background
                    color="var(--canvas--dot--color)"
                    gap={16}
                    size={1}
                    variant={BackgroundVariant.Dots}
                />
                <Panel className="team-canvas__controls" position="bottom-left">
                    <TeamCanvasControls onFit={fitTeam} onTidy={tidyTeam} />
                </Panel>
                <TeamViewportCoordinator
                    canvasRef={canvasRef}
                    detailsOpen={detailsOpen}
                    outlineOpen={outlineOpen}
                    selectedMemberId={selectedMemberId}
                    structure={structure}
                />
                <TeamCanvasFocusCoordinator
                    canvasRef={canvasRef}
                    focusRequest={focusRequest}
                />
            </ReactFlow>
            <details
                className="team-canvas__outline"
                data-team-outline
                onToggle={(event) => {
                    if (event.currentTarget.open !== outlineOpen) {
                        onOutlineOpenChange(event.currentTarget.open);
                    }
                }}
                open={outlineOpen}
            >
                <summary>Team outline</summary>
                <TeamOutline
                    collapsedMemberIds={collapsedMemberIds}
                    disabled={disabled}
                    lead={lead}
                    onAddChild={onAddChild}
                    onEdit={onEdit}
                    onRemove={onRemove}
                    onSelect={(memberId) => onSelect(memberId, false)}
                    onToggleCollapse={onToggleCollapse}
                    requestedFocus={
                        focusRequest?.surface === "outline"
                            ? focusRequest
                            : null
                    }
                    selectedMemberId={selectedMemberId}
                />
            </details>
        </section>
    );
}

function TeamCanvasFocusCoordinator({
    canvasRef,
    focusRequest,
}: {
    readonly canvasRef: RefObject<HTMLElement | null>;
    readonly focusRequest: TeamMemberFocusRequest | null;
}) {
    const settledRevision = useRef<number | null>(null);

    useEffect(() => {
        if (
            focusRequest?.surface !== "canvas" ||
            settledRevision.current === focusRequest.revision
        ) {
            return;
        }
        let cancelled = false;
        let frame: number | null = null;
        const findTarget = (): HTMLElement | null =>
            canvasRef.current?.querySelector<HTMLElement>(
                `[data-focus-surface="canvas"][data-member-focus="${CSS.escape(
                    focusRequest.memberId,
                )}"]`,
            ) ?? null;
        const focusAndVerify = (attemptsRemaining: number): void => {
            const target = findTarget();
            target?.focus();
            frame = requestAnimationFrame(() => {
                if (cancelled) {
                    return;
                }
                const currentTarget = findTarget();
                if (
                    target !== null &&
                    currentTarget === target &&
                    document.activeElement === target
                ) {
                    settledRevision.current = focusRequest.revision;
                    return;
                }
                if (attemptsRemaining > 1) {
                    focusAndVerify(attemptsRemaining - 1);
                }
            });
        };
        frame = requestAnimationFrame(() => {
            if (!cancelled) {
                focusAndVerify(2);
            }
        });
        return () => {
            cancelled = true;
            if (frame !== null) {
                cancelAnimationFrame(frame);
            }
        };
    }, [canvasRef, focusRequest]);

    return null;
}

function issueCount(
    issues: readonly StudioValidationIssue[],
    memberId: string,
): number {
    return issues.filter(
        (issue) =>
            issue.target?.kind === "member" &&
            issue.target.memberId === memberId,
    ).length;
}

function isMemberPending(pending: PendingStructure, memberId: string): boolean {
    return (
        (pending?.kind === "add_child" &&
            pending.parentMemberId === memberId) ||
        (pending?.kind === "remove_member" && pending.memberId === memberId)
    );
}

function teamStructure(lead: NormalizedMember): readonly TeamStructureEntry[] {
    const entries: TeamStructureEntry[] = [];
    function visit(member: NormalizedMember, parentId: string | null): void {
        entries.push({ id: member.id, parentId });
        for (const child of member.children ?? []) {
            visit(child, member.id);
        }
    }
    visit(lead, null);
    return entries;
}

function mergeMeasuredDimensions(
    current: TeamDimensionsById,
    measured: ReadonlyMap<string, TeamNodeDimensions>,
): TeamDimensionsById {
    let changed = false;
    const next = { ...current };
    for (const [memberId, dimensions] of measured) {
        const previous = next[memberId];
        if (
            previous === undefined ||
            Math.abs(previous.height - dimensions.height) > 0.5 ||
            Math.abs(previous.width - dimensions.width) > 0.5
        ) {
            next[memberId] = dimensions;
            changed = true;
        }
    }
    return changed ? next : current;
}

function addControlPosition(
    addNode: Extract<
        ReturnType<typeof layoutTeam>["nodes"][number],
        { readonly kind: "add" }
    >,
    nodes: ReturnType<typeof layoutTeam>["nodes"],
    positionOverrides: ReadonlyMap<
        string,
        { readonly x: number; readonly y: number }
    >,
): { readonly x: number; readonly y: number } {
    const parent = nodes.find(
        (node) => node.kind === "member" && node.member.id === addNode.parentId,
    );
    const parentOverride = positionOverrides.get(addNode.parentId);
    if (parent === undefined || parentOverride === undefined) {
        return { x: addNode.x, y: addNode.y };
    }
    return {
        x: addNode.x + parentOverride.x - parent.x,
        y: addNode.y + parentOverride.y - parent.y,
    };
}

function applyTransientNodeChanges(
    current: TeamFlowNode[],
    changes: NodeChange<TeamFlowNode>[],
): TeamFlowNode[] {
    const next = applyNodeChanges(changes, current);
    for (const change of changes) {
        if (change.type !== "position" || change.position === undefined) {
            continue;
        }
        const previousParent = current.find((node) => node.id === change.id);
        const nextParent = next.find((node) => node.id === change.id);
        const addIndex = next.findIndex(
            (node) => node.id === addNodeId(change.id),
        );
        const addNode = next[addIndex];
        if (
            previousParent === undefined ||
            nextParent === undefined ||
            addNode === undefined
        ) {
            continue;
        }
        next[addIndex] = {
            ...addNode,
            position: {
                x:
                    addNode.position.x +
                    nextParent.position.x -
                    previousParent.position.x,
                y:
                    addNode.position.y +
                    nextParent.position.y -
                    previousParent.position.y,
            },
        };
    }
    return next;
}

function reconcileAuthoredNodes(
    current: readonly TeamFlowNode[],
    authored: readonly TeamFlowNode[],
): TeamFlowNode[] {
    const currentById = new Map(current.map((node) => [node.id, node]));
    return authored.map((node) => {
        const previous = currentById.get(node.id);
        return previous === undefined ? node : { ...previous, ...node };
    });
}
