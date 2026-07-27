import { describe, expect, it } from "vitest";

import type { NormalizedMember } from "../../src/api/types";
import {
    addNodeId,
    layoutTeam,
} from "../../src/features/workflow-studio/canvas/team-layout";

describe("team layout", () => {
    it("places one trailing add control to the right of a lead-only team", () => {
        const lead = member("lead", "Lead");

        const result = layoutTeam({
            collapsedMemberIds: new Set(),
            lead,
            selectedMemberId: lead.id,
        });

        const leadNode = memberNode(result, "lead");
        const addNode = result.nodes.find((node) => node.kind === "add");
        expect(result.nodes).toHaveLength(2);
        expect(addNode?.x).toBeGreaterThan(leadNode.x + leadNode.width);
        expect(addNodeCenter(addNode)).toBeCloseTo(
            leadNode.y + leadNode.height / 2,
        );
        expect(result.edges).toContainEqual(
            expect.objectContaining({
                id: "add:lead",
                kind: "add",
                source: "lead",
                target: addNodeId("lead"),
            }),
        );
    });

    it("keeps broad authored siblings in stable top-to-bottom order", () => {
        const lead = member("lead", "Lead", [
            member("first", "First"),
            member("second", "Second"),
            member("third", "Third"),
            member("fourth", "Fourth"),
        ]);
        const input = {
            collapsedMemberIds: new Set<string>(),
            lead,
            selectedMemberId: "second",
        };

        const first = layoutTeam(input);
        const repeated = layoutTeam(input);
        const siblingNodes = ["first", "second", "third", "fourth"].map((id) =>
            memberNode(first, id),
        );

        expect(
            siblingNodes.every((node) => node.x > memberNode(first, "lead").x),
        ).toBe(true);
        expect(siblingNodes.map((node) => node.y)).toEqual(
            [...siblingNodes.map((node) => node.y)].sort(
                (left, right) => left - right,
            ),
        );
        expect(repeated).toEqual(first);
        expect(first.nodes.filter((node) => node.kind === "add")).toHaveLength(
            1,
        );
    });

    it("lays out a deep team left-to-right and appends after the selected subtree", () => {
        const lead = member("lead", "Lead", [
            member("manager", "Manager", [
                member("reviewer", "Reviewer", [
                    member("specialist", "Specialist"),
                ]),
                member("writer", "Writer"),
            ]),
        ]);

        const result = layoutTeam({
            collapsedMemberIds: new Set(),
            lead,
            selectedMemberId: "manager",
        });
        const leadNode = memberNode(result, "lead");
        const manager = memberNode(result, "manager");
        const reviewer = memberNode(result, "reviewer");
        const specialist = memberNode(result, "specialist");
        const writer = memberNode(result, "writer");
        const add = result.nodes.find((node) => node.kind === "add");

        expect(manager.x).toBeGreaterThan(leadNode.x);
        expect(reviewer.x).toBeGreaterThan(manager.x);
        expect(specialist.x).toBeGreaterThan(reviewer.x);
        expect(add?.x).toBeCloseTo(reviewer.x);
        expect(add?.y).toBeGreaterThan(
            Math.max(
                specialist.y + specialist.height,
                writer.y + writer.height,
            ),
        );
    });

    it("moves the add control past occupied regions in a mixed deep-peer tree", () => {
        const lead = member("lead", "Lead", [
            member("manager-a", "Manager A", [
                member("specialist-a", "Specialist A"),
            ]),
            member("manager-b", "Manager B", [
                member("specialist-b", "Specialist B"),
            ]),
        ]);
        const input = {
            collapsedMemberIds: new Set<string>(),
            dimensionsById: {
                "specialist-a": { width: 280, height: 240 },
                "specialist-b": { width: 280, height: 320 },
            },
            lead,
            selectedMemberId: "manager-a",
        };

        const result = layoutTeam(input);
        const repeated = layoutTeam(input);
        const add = addNode(result);
        const visibleCards = result.nodes.filter(
            (node) => node.kind === "member",
        );

        expect(result.nodes.filter((node) => node.kind === "add")).toHaveLength(
            1,
        );
        expect(
            visibleCards.every((card) => !rectanglesOverlap(add, card)),
        ).toBe(true);
        expect(repeated).toEqual(result);
    });

    it("hides collapsed descendants and respects measured localized card height", () => {
        const lead = member("lead", "Lead", [
            member("manager", "A manager with a long localized title", [
                member("hidden", "Hidden teammate"),
            ]),
            member("peer", "Peer"),
        ]);
        const expanded = layoutTeam({
            collapsedMemberIds: new Set(),
            dimensionsById: {
                manager: { width: 280, height: 360 },
            },
            lead,
            selectedMemberId: "peer",
        });
        const manager = memberNode(expanded, "manager");
        const peer = memberNode(expanded, "peer");
        expect(peer.y).toBeGreaterThan(manager.y);
        expect(peer.y).toBeGreaterThanOrEqual(manager.y + manager.height);

        const collapsed = layoutTeam({
            collapsedMemberIds: new Set(["manager"]),
            dimensionsById: {
                manager: { width: 280, height: 360 },
            },
            lead,
            selectedMemberId: "manager",
        });
        expect(
            collapsed.nodes.some(
                (node) => node.kind === "member" && node.member.id === "hidden",
            ),
        ).toBe(false);
        expect(
            collapsed.visibleMembers.map((entry) => entry.member.id),
        ).toEqual(["lead", "manager", "peer"]);
        // A collapsed Member hides the slot a new child would occupy, so no
        // add control is offered until it is expanded.
        expect(
            collapsed.nodes.filter((node) => node.kind === "add"),
        ).toHaveLength(0);
    });
});

function member(
    id: string,
    title: string,
    children: NormalizedMember[] = [],
): NormalizedMember {
    return {
        children,
        id,
        title,
    };
}

function memberNode(result: ReturnType<typeof layoutTeam>, memberId: string) {
    const node = result.nodes.find(
        (candidate) =>
            candidate.kind === "member" && candidate.member.id === memberId,
    );
    if (node === undefined || node.kind !== "member") {
        throw new Error(`Missing layout node ${memberId}`);
    }
    return node;
}

function addNodeCenter(
    node:
        | Extract<
              ReturnType<typeof layoutTeam>["nodes"][number],
              { kind: "add" }
          >
        | undefined,
): number {
    if (node === undefined) {
        throw new Error("Missing add node");
    }
    return node.y + node.height / 2;
}

function addNode(result: ReturnType<typeof layoutTeam>) {
    const node = result.nodes.find((candidate) => candidate.kind === "add");
    if (node === undefined || node.kind !== "add") {
        throw new Error("Missing add node");
    }
    return node;
}

function rectanglesOverlap(
    left: ReturnType<typeof addNode>,
    right: ReturnType<typeof memberNode>,
): boolean {
    return (
        left.x < right.x + right.width &&
        left.x + left.width > right.x &&
        left.y < right.y + right.height &&
        left.y + left.height > right.y
    );
}
