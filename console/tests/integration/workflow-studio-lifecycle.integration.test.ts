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

import type { DraftOperation } from "../../src/api/types";
import {
    catalogFixture,
    draftFixture,
    nestedDraftFixture,
    removeNestedMemberFixture,
    TEST_WORKFLOW_ID,
} from "../fixtures/workflows";
import {
    applyWorkflowOperation,
    DRAFT_PATH,
    loadedController,
    mutationResponse,
    settleUntil,
    workflowRead,
} from "./workflow-studio-integration-support";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
    server.resetHandlers();
    vi.useRealTimers();
});
afterAll(() => server.close());

describe("Workflow Studio accepted lifecycle operations", () => {
    it("invalidates a rejected Undo receipt and refetches current truth", async () => {
        vi.useFakeTimers();
        let reads = 0;
        const saved = draftFixture('"wd-two"', "Saved value.");
        server.use(
            workflowRead(() => {
                reads += 1;
                return catalogFixture({
                    draft: reads === 1 ? draftFixture() : saved,
                });
            }),
            http.patch(DRAFT_PATH, () =>
                mutationResponse(saved, "receipt-one"),
            ),
            http.post(`${DRAFT_PATH}/undo`, () =>
                HttpResponse.json(
                    {
                        ok: false,
                        code: "conflict",
                        summary: "The Undo action is no longer available.",
                        retryable: false,
                    },
                    { status: 409 },
                ),
            ),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "Saved value." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(() => controller.getSnapshot().canUndo);
        await controller.undo();

        expect(reads).toBe(2);
        expect(controller.getSnapshot().canUndo).toBe(false);
        expect(controller.getSnapshot().workingWorkflow?.description).toBe(
            "Saved value.",
        );
        controller.dispose();
    });

    it("applies a successful Undo using the saved receipt", async () => {
        vi.useFakeTimers();
        const original = draftFixture();
        const saved = draftFixture('"wd-two"', "Saved value.");
        server.use(
            workflowRead(() => catalogFixture({ draft: original })),
            http.patch(DRAFT_PATH, () =>
                mutationResponse(saved, "receipt-one"),
            ),
            http.post(`${DRAFT_PATH}/undo`, async ({ request }) => {
                expect(request.headers.get("If-Match")).toBe('"wd-two"');
                expect(await request.json()).toEqual({
                    receipt_id: "receipt-one",
                });
                return HttpResponse.json(original);
            }),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "Saved value." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(() => controller.getSnapshot().canUndo);
        await controller.undo();

        expect(controller.getSnapshot().workingWorkflow?.description).toBe(
            original.workflow.description,
        );
        expect(controller.getSnapshot().canUndo).toBe(false);
        controller.dispose();
    });

    it("selects the surviving direct parent after accepted subtree removal", async () => {
        const original = nestedDraftFixture();
        const accepted = removeNestedMemberFixture(original, '"wd-two"');
        server.use(
            workflowRead(() => catalogFixture({ draft: original })),
            http.patch(DRAFT_PATH, async ({ request }) => {
                expect(await request.json()).toEqual({
                    kind: "remove_member",
                    member_id: "member-3",
                });
                return mutationResponse(accepted, "receipt-remove");
            }),
        );
        const controller = await loadedController();
        controller.selectMember("member-3");

        await controller.removeMember("member-3");

        expect(
            controller.getSnapshot().workingWorkflow?.lead.children?.[0]
                ?.children,
        ).toEqual([]);
        expect(controller.getSnapshot().selectedMemberId).toBe("member-2");
        expect(controller.getSnapshot().canUndo).toBe(true);
        controller.dispose();
    });

    it("flushes, validates, and publishes with validation's ETag", async () => {
        const order: string[] = [];
        let current = draftFixture();
        let published = false;
        server.use(
            workflowRead(() =>
                published
                    ? catalogFixture({ draft: null, published: true })
                    : catalogFixture({ draft: current }),
            ),
            http.patch(DRAFT_PATH, async ({ request }) => {
                order.push("save");
                current = applyWorkflowOperation(
                    current,
                    (await request.json()) as DraftOperation,
                    '"wd-two"',
                );
                return mutationResponse(current, "receipt-publish");
            }),
            http.post(`${DRAFT_PATH}/validate`, () => {
                order.push("validate");
                current = { ...current, etag: '"wd-validated"' };
                return HttpResponse.json({
                    is_valid: true,
                    issues: [],
                    draft: current,
                });
            }),
            http.post(`${DRAFT_PATH}/publish`, ({ request }) => {
                order.push(`publish:${request.headers.get("If-Match")}`);
                published = true;
                return HttpResponse.json({
                    workflow_id: TEST_WORKFLOW_ID,
                    revision_no: 2,
                    workflow: current.workflow,
                });
            }),
        );
        const controller = await loadedController();
        controller.editWorkflow({ description: "Publish this value." });

        expect(await controller.validateAndPublish()).toBe(true);

        expect(order).toEqual(["save", "validate", 'publish:"wd-validated"']);
        expect(controller.getSnapshot().workingWorkflow).toBeNull();
        expect(controller.getSnapshot().catalog?.state).toBe("published");
        controller.dispose();
    });

    it("discards only the draft and returns to published truth", async () => {
        let discarded = false;
        server.use(
            workflowRead(() =>
                discarded
                    ? catalogFixture({ draft: null, published: true })
                    : catalogFixture(),
            ),
            http.delete(DRAFT_PATH, ({ request }) => {
                expect(request.headers.get("If-Match")).toBe('"wd-one"');
                discarded = true;
                return HttpResponse.json({
                    is_discarded: true,
                    draft_id: "workflow-draft.test",
                });
            }),
        );
        const controller = await loadedController();

        expect(await controller.discardDraft()).toBe(true);

        expect(controller.getSnapshot().workingWorkflow).toBeNull();
        expect(controller.getSnapshot().catalog?.state).toBe("published");
        controller.dispose();
    });
});
