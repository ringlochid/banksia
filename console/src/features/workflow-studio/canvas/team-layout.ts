import dagre, {
    type EdgeLabel,
    type GraphLabel,
    type NodeLabel,
    type OrderConstraint,
} from "@dagrejs/dagre";

import type { NormalizedMember } from "../../../api/types";

// One row per card: icon, name, optional warning. Matches `--member--height`.
export const MEMBER_CARD_WIDTH = 12 * 16;
export const MEMBER_CARD_HEIGHT = 2.25 * 16;
export const ADD_CONTROL_SIZE = 1.5 * 16;
/** Gap between a childless Member and its trailing add control. */
const ADD_CONTROL_STEM = 2.5 * 16;

const RANK_SPACING = 5 * 16;
const SIBLING_SPACING = 1.25 * 16;
const CANVAS_MARGIN = 2 * 16;

export interface TeamNodeDimensions {
    readonly height: number;
    readonly width: number;
}

export type TeamDimensionsById = Readonly<
    Record<string, TeamNodeDimensions | undefined>
>;

export interface VisibleTeamMember {
    readonly depth: number;
    readonly member: NormalizedMember;
    readonly parentId: string | null;
}

export interface TeamMemberLayoutNode extends VisibleTeamMember {
    readonly height: number;
    readonly kind: "member";
    readonly width: number;
    readonly x: number;
    readonly y: number;
}

export interface TeamAddLayoutNode {
    readonly height: number;
    readonly kind: "add";
    readonly parentId: string;
    readonly width: number;
    readonly x: number;
    readonly y: number;
}

export type TeamLayoutNode = TeamMemberLayoutNode | TeamAddLayoutNode;

export interface TeamLayoutEdge {
    readonly id: string;
    readonly kind: "ownership" | "add";
    readonly source: string;
    readonly target: string;
}

export interface TeamLayoutResult {
    readonly edges: readonly TeamLayoutEdge[];
    readonly height: number;
    readonly nodes: readonly TeamLayoutNode[];
    readonly visibleMembers: readonly VisibleTeamMember[];
    readonly width: number;
}

export interface TeamLayoutInput {
    readonly collapsedMemberIds: ReadonlySet<string>;
    readonly dimensionsById?: TeamDimensionsById;
    readonly lead: NormalizedMember;
    readonly selectedMemberId: string;
}

export function layoutTeam({
    collapsedMemberIds,
    dimensionsById = {},
    lead,
    selectedMemberId,
}: TeamLayoutInput): TeamLayoutResult {
    const visibleMembers = flattenVisibleTeam(lead, collapsedMemberIds);
    const graph = new dagre.graphlib.Graph<GraphLabel, NodeLabel, EdgeLabel>();
    graph.setGraph({
        edgesep: SIBLING_SPACING,
        marginx: CANVAS_MARGIN,
        marginy: CANVAS_MARGIN,
        nodesep: SIBLING_SPACING,
        rankdir: "LR",
        ranksep: RANK_SPACING,
    });
    graph.setDefaultEdgeLabel(() => ({}));

    for (const entry of visibleMembers) {
        const dimensions = dimensionsFor(entry.member, dimensionsById);
        graph.setNode(entry.member.id, {
            height: dimensions.height,
            width: dimensions.width,
        });
        if (entry.parentId !== null) {
            graph.setEdge(entry.parentId, entry.member.id, {
                minlen: 1,
                weight: 3,
            });
        }
    }

    dagre.layout(graph, {
        constraints: authoredOrderConstraints(visibleMembers),
    });

    const memberNodes = visibleMembers.map<TeamMemberLayoutNode>((entry) => {
        const node = graph.node(entry.member.id);
        const dimensions = dimensionsFor(entry.member, dimensionsById);
        if (node.x === undefined || node.y === undefined) {
            throw new Error(`Dagre did not position Member ${entry.member.id}`);
        }
        return {
            ...entry,
            height: dimensions.height,
            kind: "member",
            width: dimensions.width,
            x: node.x - dimensions.width / 2,
            y: node.y - dimensions.height / 2,
        };
    });
    const addNode = positionAddControl(
        memberNodes,
        selectedMemberId,
        collapsedMemberIds,
    );
    const nodes: readonly TeamLayoutNode[] =
        addNode === null ? memberNodes : [...memberNodes, addNode];
    const bounds = layoutBounds(nodes);

    return {
        edges: buildEdges(memberNodes, addNode),
        height: bounds.height,
        nodes,
        visibleMembers,
        width: bounds.width,
    };
}

/**
 * One edge per ownership link, plus one to the trailing add control. The path
 * itself is computed by the edge component from the handle positions React
 * Flow supplies, exactly as n8n's canvas does.
 */
function buildEdges(
    memberNodes: readonly TeamMemberLayoutNode[],
    addNode: TeamAddLayoutNode | null,
): readonly TeamLayoutEdge[] {
    const edges: TeamLayoutEdge[] = memberNodes.flatMap((node) =>
        node.parentId === null
            ? []
            : [
                  {
                      id: `owns:${node.parentId}:${node.member.id}`,
                      kind: "ownership" as const,
                      source: node.parentId,
                      target: node.member.id,
                  },
              ],
    );
    if (addNode !== null) {
        edges.push({
            id: `add:${addNode.parentId}`,
            kind: "add",
            source: addNode.parentId,
            target: addNodeId(addNode.parentId),
        });
    }
    return edges;
}

export function flattenVisibleTeam(
    lead: NormalizedMember,
    collapsedMemberIds: ReadonlySet<string>,
): readonly VisibleTeamMember[] {
    const entries: VisibleTeamMember[] = [];

    function visit(
        member: NormalizedMember,
        parentId: string | null,
        depth: number,
    ): void {
        entries.push({ depth, member, parentId });
        if (collapsedMemberIds.has(member.id)) {
            return;
        }
        for (const child of member.children ?? []) {
            visit(child, member.id, depth + 1);
        }
    }

    visit(lead, null, 0);
    return entries;
}

export function addNodeId(parentMemberId: string): string {
    return `add-child:${parentMemberId}`;
}

function authoredOrderConstraints(
    entries: readonly VisibleTeamMember[],
): OrderConstraint[] {
    const byDepth = new Map<number, string[]>();
    for (const entry of entries) {
        const depth = byDepth.get(entry.depth) ?? [];
        depth.push(entry.member.id);
        byDepth.set(entry.depth, depth);
    }
    return [...byDepth.values()].flatMap((memberIds) =>
        memberIds.slice(1).map((memberId, index) => ({
            left: memberIds[index] as string,
            right: memberId,
        })),
    );
}

/**
 * Every card is one fixed-height row, so there is nothing to estimate from the
 * Member's content. Measured heights still win in case the browser rounds
 * differently.
 */
function dimensionsFor(
    member: NormalizedMember,
    dimensionsById: TeamDimensionsById,
): TeamNodeDimensions {
    const measured = dimensionsById[member.id];
    return {
        height:
            measured === undefined || measured.height <= 0
                ? MEMBER_CARD_HEIGHT
                : measured.height,
        width: MEMBER_CARD_WIDTH,
    };
}

function positionAddControl(
    nodes: readonly TeamMemberLayoutNode[],
    selectedMemberId: string,
    collapsedMemberIds: ReadonlySet<string>,
): TeamAddLayoutNode | null {
    const selected = nodes.find((node) => node.member.id === selectedMemberId);
    if (selected === undefined) {
        return null;
    }
    const acceptedChildren = selected.member.children ?? [];

    // A collapsed Member hides the very slot a new child would land in, so
    // offering the control there points at nothing. Expand first.
    if (
        collapsedMemberIds.has(selected.member.id) &&
        acceptedChildren.length > 0
    ) {
        return null;
    }

    // With no children yet, the control sits on a short stem beside the card
    // rather than a full column away, so it reads as belonging to it.
    if (acceptedChildren.length === 0) {
        return {
            height: ADD_CONTROL_SIZE,
            kind: "add",
            parentId: selected.member.id,
            width: ADD_CONTROL_SIZE,
            x: selected.x + selected.width + ADD_CONTROL_STEM,
            y: selected.y + (selected.height - ADD_CONTROL_SIZE) / 2,
        };
    }

    // Otherwise it takes the next direct-child slot, below this Member's own
    // last descendant. Siblings share a column, so the slot is then pushed
    // clear of anything already occupying it — the connector keeps it legible
    // even when that lands some way down.
    const subtree = nodes.filter(
        (node) =>
            node.depth > selected.depth &&
            isDescendantOf(node, selected.member.id, nodes),
    );
    const directChild = subtree.find(
        (node) => node.parentId === selected.member.id,
    );
    const lastSubtreeBottom = Math.max(
        ...subtree.map((node) => node.y + node.height),
    );
    return resolveAddCollision(
        {
            height: ADD_CONTROL_SIZE,
            kind: "add",
            parentId: selected.member.id,
            width: ADD_CONTROL_SIZE,
            x: directChild?.x ?? selected.x + selected.width + RANK_SPACING,
            y: lastSubtreeBottom + SIBLING_SPACING,
        },
        nodes,
    );
}

function resolveAddCollision(
    candidate: TeamAddLayoutNode,
    nodes: readonly TeamMemberLayoutNode[],
): TeamAddLayoutNode {
    const occupied = nodes
        .filter((node) => horizontalRangesOverlap(candidate, node))
        .sort(
            (left, right) =>
                left.y - right.y ||
                left.x - right.x ||
                left.member.id.localeCompare(right.member.id),
        );
    let y = candidate.y;
    for (;;) {
        const collision = occupied.find((node) =>
            verticalRangesConflict(y, candidate.height, node),
        );
        if (collision === undefined) {
            return { ...candidate, y };
        }
        y = collision.y + collision.height + SIBLING_SPACING;
    }
}

function horizontalRangesOverlap(
    left: Pick<TeamLayoutNode, "width" | "x">,
    right: Pick<TeamLayoutNode, "width" | "x">,
): boolean {
    return left.x < right.x + right.width && left.x + left.width > right.x;
}

function verticalRangesConflict(
    candidateY: number,
    candidateHeight: number,
    occupied: Pick<TeamLayoutNode, "height" | "y">,
): boolean {
    return (
        candidateY < occupied.y + occupied.height + SIBLING_SPACING &&
        candidateY + candidateHeight + SIBLING_SPACING > occupied.y
    );
}

function isDescendantOf(
    candidate: TeamMemberLayoutNode,
    ancestorId: string,
    nodes: readonly TeamMemberLayoutNode[],
): boolean {
    let parentId = candidate.parentId;
    while (parentId !== null) {
        if (parentId === ancestorId) {
            return true;
        }
        parentId =
            nodes.find((node) => node.member.id === parentId)?.parentId ?? null;
    }
    return false;
}

function layoutBounds(nodes: readonly TeamLayoutNode[]): {
    readonly height: number;
    readonly width: number;
} {
    if (nodes.length === 0) {
        return { height: 0, width: 0 };
    }
    const width =
        Math.max(...nodes.map((node) => node.x + node.width)) + CANVAS_MARGIN;
    const height =
        Math.max(...nodes.map((node) => node.y + node.height)) + CANVAS_MARGIN;
    return { height, width };
}
