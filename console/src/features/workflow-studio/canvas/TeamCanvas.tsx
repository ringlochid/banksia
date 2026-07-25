import "@xyflow/react/dist/style.css";
import "./team-canvas.css";

import {
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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
    const flowRef = useRef<ReactFlowInstance<
        TeamFlowNode,
        ResponsibilityEdgeModel
    > | null>(null);
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

    const nodes = useMemo<readonly TeamFlowNode[]>(
        () =>
            layout.nodes.map((node): TeamFlowNode => {
                if (node.kind === "add") {
                    return {
                        data: {
                            disabled,
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
                        draggable: false,
                        focusable: false,
                        id: addNodeId(node.parentId),
                        position: { x: node.x, y: node.y },
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
                    draggable: false,
                    focusable: false,
                    id: node.member.id,
                    position: { x: node.x, y: node.y },
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
            onAddChild,
            onSelect,
            onToggleCollapse,
            pendingStructure,
            selectedMemberId,
        ],
    );

    const edges = useMemo<readonly ResponsibilityEdgeModel[]>(
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

    useEffect(() => {
        if (focusRequest?.surface !== "canvas") {
            return;
        }
        let frame: number | null = null;
        let attemptsRemaining = 12;
        const focusWhenVisible = (): void => {
            const target = canvasRef.current?.querySelector<HTMLElement>(
                `[data-focus-surface="canvas"][data-member-focus="${CSS.escape(
                    focusRequest.memberId,
                )}"]`,
            );
            if (
                target !== undefined &&
                target !== null &&
                getComputedStyle(target).visibility !== "hidden"
            ) {
                target.focus();
                return;
            }
            attemptsRemaining -= 1;
            if (attemptsRemaining > 0) {
                frame = requestAnimationFrame(focusWhenVisible);
            }
        };
        frame = requestAnimationFrame(focusWhenVisible);
        return () => {
            if (frame !== null) {
                cancelAnimationFrame(frame);
            }
        };
    }, [focusRequest]);

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
                edges={[...edges]}
                edgesFocusable={false}
                edgesReconnectable={false}
                edgeTypes={edgeTypes}
                elementsSelectable={false}
                fitView
                fitViewOptions={{ maxZoom: 1, padding: 0.18 }}
                maxZoom={1.5}
                minZoom={0.25}
                nodeTypes={nodeTypes}
                nodes={[...nodes]}
                nodesConnectable={false}
                nodesDraggable={false}
                nodesFocusable={false}
                onInit={(instance) => {
                    flowRef.current = instance;
                }}
                onNodeClick={() => undefined}
                onNodesChange={onNodesChange}
                panOnDrag
                proOptions={{ hideAttribution: true }}
                selectionOnDrag={false}
                zoomOnDoubleClick={false}
            >
                <Background
                    color="#d7d4c9"
                    gap={24}
                    size={1}
                    variant={BackgroundVariant.Dots}
                />
                <Panel className="team-canvas__legend" position="top-right">
                    Lines show responsibility, not task order.
                </Panel>
                <Panel className="team-canvas__controls" position="bottom-left">
                    <TeamCanvasControls
                        onFit={fitTeam}
                        onTidy={() =>
                            setLayoutRevision((revision) => revision + 1)
                        }
                    />
                </Panel>
                <TeamViewportCoordinator
                    canvasRef={canvasRef}
                    detailsOpen={detailsOpen}
                    outlineOpen={outlineOpen}
                    selectedMemberId={selectedMemberId}
                    structure={structure}
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
