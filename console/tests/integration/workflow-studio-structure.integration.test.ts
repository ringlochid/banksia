import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
    afterAll,
    afterEach,
    beforeAll,
    describe,
    expect,
    it,
    vi,
} from "vitest";

import type {
    DraftOperation,
    WorkflowDraftReadback,
} from "../../src/api/types";
import {
    catalogFixture,
    draftFixture,
    nestedDraftFixture,
    removeNestedMemberFixture,
} from "../fixtures/workflows";
import {
    applyWorkflowOperation,
    DRAFT_PATH,
    loadedController,
    mutationResponse,
    settleUntil,
    WORKFLOW_PATH,
    workflowRead,
} from "./workflow-studio-integration-support";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
    server.resetHandlers();
    vi.useRealTimers();
});
afterAll(() => server.close());

describe("Workflow Studio structural mutations", () => {
    it("waits for an in-flight prose save before adding with the latest ETag", async () => {
        vi.useFakeTimers();
        let releaseSave: (() => void) | undefined;
        const saveGate = new Promise<void>((resolve) => {
            releaseSave = resolve;
        });
        const calls: {
            readonly etag: string | null;
            readonly operation: DraftOperation;
        }[] = [];
        let current = draftFixture();
        server.use(
            workflowRead(() => catalogFixture({ draft: current })),
            http.patch(DRAFT_PATH, async ({ request }) => {
                const operation = (await request.json()) as DraftOperation;
                calls.push({
                    etag: request.headers.get("If-Match"),
                    operation,
                });
                if (calls.length === 1) {
                    await saveGate;
                    current = applyWorkflowOperation(
                        current,
                        operation,
                        '"wd-two"',
                    );
                } else {
                    current = addChildToDraft(current, '"wd-three"');
                }
                return mutationResponse(current, `receipt-${calls.length}`);
            }),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "Save before structure." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(() => calls.length === 1);
        const addingChild = controller.addChild("member-1", {
            title: "Release verifier",
        });
        await vi.advanceTimersByTimeAsync(0);
        expect(calls).toHaveLength(1);

        releaseSave?.();
        await addingChild;

        expect(calls.map((call) => call.etag)).toEqual([
            '"wd-one"',
            '"wd-two"',
        ]);
        expect(calls[1]?.operation).toEqual({
            kind: "add_member",
            parent_member_id: "member-1",
            member: { title: "Release verifier" },
        });
        expect(controller.getSnapshot().selectedMemberId).toBe("member-3");
        expect(controller.getSnapshot().pendingStructure).toBeNull();
        controller.dispose();
    });

    it("selects each accepted child while two additions append siblings", async () => {
        const operations: DraftOperation[] = [];
        let current = draftFixture();
        server.use(
            workflowRead(() => catalogFixture({ draft: current })),
            http.patch(DRAFT_PATH, async ({ request }) => {
                const operation = (await request.json()) as DraftOperation;
                operations.push(operation);
                current = addChildToDraft(
                    current,
                    `"wd-${operations.length + 1}"`,
                    `member-${operations.length + 2}`,
                );
                return mutationResponse(
                    current,
                    `receipt-${operations.length}`,
                );
            }),
        );
        const controller = await loadedController();

        await controller.addChild("member-1", { title: "First reviewer" });
        await controller.addChild("member-1", { title: "Second reviewer" });

        expect(operations).toEqual([
            {
                kind: "add_member",
                parent_member_id: "member-1",
                member: { title: "First reviewer" },
            },
            {
                kind: "add_member",
                parent_member_id: "member-1",
                member: { title: "Second reviewer" },
            },
        ]);
        expect(
            controller
                .getSnapshot()
                .workingWorkflow?.lead.children?.map((child) => child.id),
        ).toEqual(["member-2", "member-3", "member-4"]);
        expect(controller.getSnapshot().selectedMemberId).toBe("member-4");
        controller.dispose();
    });

    it.each([
        ["accepted", true],
        ["uncommitted", false],
    ] as const)(
        "reconciles a lost nested add response when the effect is %s without replay",
        async (_outcome, acceptedEffect) => {
            let current = nestedDraftFixture();
            let reads = 0;
            let attempts = 0;
            server.use(
                http.get(WORKFLOW_PATH, () => {
                    reads += 1;
                    return HttpResponse.json(
                        catalogFixture({ draft: current }),
                    );
                }),
                http.patch(DRAFT_PATH, async ({ request }) => {
                    const operation = (await request.json()) as DraftOperation;
                    attempts += 1;
                    if (acceptedEffect) {
                        current = addNestedChildToDraft(
                            current,
                            operation,
                            '"wd-lost-add"',
                        );
                    }
                    return HttpResponse.error();
                }),
            );
            const controller = await loadedController();

            await controller.addChild("member-2", {
                title: "Added specialist",
            });
            expect(controller.getSnapshot().recovery).toEqual({
                kind: "check_current",
                operation: "adding_child",
                selectionBasis: {
                    kind: "add_parent",
                    memberId: "member-2",
                },
            });
            await controller.retrySave();

            expect({ attempts, reads }).toEqual({ attempts: 1, reads: 2 });
            expect(controller.getSnapshot().selectedMemberId).toBe("member-2");
            expect(
                controller
                    .getSnapshot()
                    .workingWorkflow?.lead.children?.[0]?.children?.some(
                        (member) => member.id === "member-4",
                    ),
            ).toBe(acceptedEffect);
            controller.dispose();
        },
    );

    it.each([
        ["accepted", true],
        ["uncommitted", false],
    ] as const)(
        "reconciles a lost nested removal response when the effect is %s without replay",
        async (_outcome, acceptedEffect) => {
            let current = nestedDraftFixture();
            let reads = 0;
            let attempts = 0;
            server.use(
                http.get(WORKFLOW_PATH, () => {
                    reads += 1;
                    return HttpResponse.json(
                        catalogFixture({ draft: current }),
                    );
                }),
                http.patch(DRAFT_PATH, async ({ request }) => {
                    const operation = (await request.json()) as DraftOperation;
                    attempts += 1;
                    if (acceptedEffect && operation.kind === "remove_member") {
                        current = removeNestedMemberFixture(
                            current,
                            '"wd-lost-remove"',
                        );
                    }
                    return HttpResponse.error();
                }),
            );
            const controller = await loadedController();
            controller.selectMember("member-3");

            await controller.removeMember("member-3");
            expect(controller.getSnapshot().recovery).toEqual({
                kind: "check_current",
                operation: "removing_member",
                selectionBasis: {
                    kind: "remove_parent",
                    memberId: "member-2",
                },
            });
            await controller.retrySave();

            expect({ attempts, reads }).toEqual({ attempts: 1, reads: 2 });
            expect(controller.getSnapshot().selectedMemberId).toBe("member-2");
            expect(
                controller
                    .getSnapshot()
                    .workingWorkflow?.lead.children?.[0]?.children?.some(
                        (member) => member.id === "member-3",
                    ),
            ).toBe(!acceptedEffect);
            controller.dispose();
        },
    );
});

function addChildToDraft(
    draft: WorkflowDraftReadback,
    etag: string,
    memberId = "member-3",
): WorkflowDraftReadback {
    return {
        ...draft,
        etag,
        workflow: {
            ...draft.workflow,
            lead: {
                ...draft.workflow.lead,
                children: [
                    ...(draft.workflow.lead.children ?? []),
                    {
                        id: memberId,
                        title: "New teammate",
                    },
                ],
            },
        },
    };
}

function addNestedChildToDraft(
    draft: WorkflowDraftReadback,
    operation: DraftOperation,
    etag: string,
): WorkflowDraftReadback {
    if (
        operation.kind !== "add_member" ||
        operation.parent_member_id !== "member-2"
    ) {
        return draft;
    }
    const manager = draft.workflow.lead.children?.[0];
    if (manager === undefined) {
        throw new Error("Expected nested manager fixture");
    }
    return {
        ...draft,
        etag,
        workflow: {
            ...draft.workflow,
            lead: {
                ...draft.workflow.lead,
                children: [
                    {
                        ...manager,
                        children: [
                            ...(manager.children ?? []),
                            { id: "member-4", title: "Added specialist" },
                        ],
                    },
                ],
            },
        },
    };
}
