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

describe("Workflow Studio autosave", () => {
    it("drains rapid Workflow and Member edits in one settled batch", async () => {
        vi.useFakeTimers();
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
                current = applyWorkflowOperation(
                    current,
                    operation,
                    `"wd-${String(calls.length + 1)}"`,
                );
                return mutationResponse(current, `receipt-${calls.length}`);
            }),
        );
        const controller = await loadedController();

        controller.editMember("member-1", {
            title: "Accountable research lead",
        });
        controller.editWorkflow({
            description: "Investigate with an independent evidence review.",
        });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(
            () =>
                calls.length === 2 &&
                controller.getSnapshot().save.kind === "idle",
        );

        expect(calls.map((call) => call.etag)).toEqual(['"wd-one"', '"wd-2"']);
        expect(calls.map((call) => call.operation.kind)).toEqual([
            "update_workflow",
            "update_member",
        ]);
        expect(current.workflow.description).toBe(
            "Investigate with an independent evidence review.",
        );
        expect(current.workflow.lead.title).toBe("Accountable research lead");
        expect(controller.getSnapshot().dirty).toEqual({
            workflow: [],
            memberIds: [],
            memberFields: {},
        });
        controller.dispose();
    });

    it("waits 500 ms, serializes writes, and preserves newer typing", async () => {
        vi.useFakeTimers();
        let releaseFirst: (() => void) | undefined;
        const firstGate = new Promise<void>((resolve) => {
            releaseFirst = resolve;
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
                    await firstGate;
                }
                current = applyWorkflowOperation(
                    current,
                    operation,
                    `"wd-${String(calls.length + 1)}"`,
                );
                return mutationResponse(current, `receipt-${calls.length}`);
            }),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "First settled value." });
        await vi.advanceTimersByTimeAsync(499);
        expect(calls).toHaveLength(0);
        await vi.advanceTimersByTimeAsync(1);
        await settleUntil(() => calls.length === 1);
        controller.editWorkflow({ description: "Newer local value." });
        await vi.advanceTimersByTimeAsync(500);
        expect(calls).toHaveLength(1);

        releaseFirst?.();
        await settleUntil(
            () =>
                calls.length === 2 &&
                controller.getSnapshot().save.kind === "idle",
        );

        expect(calls.map((call) => call.etag)).toEqual(['"wd-one"', '"wd-2"']);
        expect(calls[1]?.operation).toEqual({
            kind: "update_workflow",
            patch: { description: "Newer local value." },
        });
        expect(controller.getSnapshot().workingWorkflow?.description).toBe(
            "Newer local value.",
        );
        expect(controller.getSnapshot().dirty.workflow).toEqual([]);
        expect(controller.getSnapshot().canUndo).toBe(true);
        controller.editWorkflow({ description: "Unsaved third value." });
        expect(controller.getSnapshot().canUndo).toBe(false);
        controller.dispose();
    });

    it("keeps the latest edit's original deadline after an earlier response", async () => {
        vi.useFakeTimers();
        let releaseFirst: (() => void) | undefined;
        const firstGate = new Promise<void>((resolve) => {
            releaseFirst = resolve;
        });
        const calls: DraftOperation[] = [];
        let current = draftFixture();
        server.use(
            workflowRead(() => catalogFixture({ draft: current })),
            http.patch(DRAFT_PATH, async ({ request }) => {
                const operation = (await request.json()) as DraftOperation;
                calls.push(operation);
                if (calls.length === 1) {
                    await firstGate;
                }
                current = applyWorkflowOperation(
                    current,
                    operation,
                    `"wd-${String(calls.length + 1)}"`,
                );
                return mutationResponse(current, `receipt-${calls.length}`);
            }),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "First value." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(() => calls.length === 1);
        await vi.advanceTimersByTimeAsync(100);
        controller.editWorkflow({ description: "Second value." });
        releaseFirst?.();
        await settleUntil(
            () => controller.getSnapshot().save.kind === "settling",
        );

        await vi.advanceTimersByTimeAsync(499);
        expect(calls).toHaveLength(1);
        await vi.advanceTimersByTimeAsync(1);
        await settleUntil(() => calls.length === 2);

        expect(calls[1]).toEqual({
            kind: "update_workflow",
            patch: { description: "Second value." },
        });
        controller.dispose();
    });

    it("freezes on conflict, keeps local values, and copies changed fields only", async () => {
        vi.useFakeTimers();
        const current = draftFixture('"wd-current"', "Controller value.");
        server.use(
            workflowRead(() => catalogFixture()),
            http.patch(DRAFT_PATH, () =>
                HttpResponse.json(
                    {
                        detail: {
                            code: "conflict",
                            message:
                                "The draft changed before this request was applied.",
                            current,
                        },
                    },
                    { status: 412 },
                ),
            ),
        );
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: { writeText },
        });
        const controller = await loadedController();

        controller.editWorkflow({ description: "My unsaved value." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(
            () => controller.getSnapshot().save.kind === "conflict",
        );

        expect(controller.getSnapshot().workingWorkflow?.description).toBe(
            "My unsaved value.",
        );
        expect(controller.getSnapshot().conflict?.current.etag).toBe(
            '"wd-current"',
        );
        expect(controller.getSnapshot().conflict?.selectionBasis).toBeNull();
        expect(await controller.copyUnsavedValues()).toBe(true);
        expect(JSON.parse(String(writeText.mock.calls[0]?.[0]))).toEqual({
            workflow_id: TEST_WORKFLOW_ID,
            workflow: { description: "My unsaved value." },
            members: [],
        });
        controller.dispose();
    });

    it("treats a missing current-version precondition as reloadable", async () => {
        vi.useFakeTimers();
        let reads = 0;
        let attempts = 0;
        server.use(
            workflowRead(() => {
                reads += 1;
                return catalogFixture();
            }),
            http.patch(DRAFT_PATH, () => {
                attempts += 1;
                return HttpResponse.json(
                    {
                        detail: {
                            code: "invalid_request",
                            message: "The current draft version is required.",
                        },
                    },
                    { status: 428 },
                );
            }),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "A valid local edit." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(
            () => controller.getSnapshot().save.kind === "failed",
        );
        expect(controller.getSnapshot().recovery).toEqual({
            kind: "reload_current",
        });

        await controller.retrySave();

        expect({ attempts, reads }).toEqual({ attempts: 1, reads: 2 });
        expect(controller.getSnapshot().recovery).toBeNull();
        controller.dispose();
    });

    it("preserves an offline edit and retries it once requested", async () => {
        vi.useFakeTimers();
        let attempts = 0;
        const accepted = draftFixture('"wd-two"', "Saved after reconnect.");
        server.use(
            workflowRead(() => catalogFixture()),
            http.patch(DRAFT_PATH, () => {
                attempts += 1;
                return attempts === 1
                    ? HttpResponse.error()
                    : mutationResponse(accepted, "receipt-retry");
            }),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "Saved after reconnect." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(
            () => controller.getSnapshot().save.kind === "offline",
        );
        expect(controller.getSnapshot().dirty.workflow).toEqual([
            "description",
        ]);

        await controller.retrySave();

        expect(attempts).toBe(2);
        expect(controller.getSnapshot().save.kind).toBe("idle");
        expect(controller.getSnapshot().dirty.workflow).toEqual([]);
        controller.dispose();
    });

    it("retries only remaining newer Member dirt from the accepted successor ETag", async () => {
        vi.useFakeTimers();
        let releaseMemberFailure: (() => void) | undefined;
        const memberFailureGate = new Promise<void>((resolve) => {
            releaseMemberFailure = resolve;
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
                if (calls.length === 2) {
                    await memberFailureGate;
                    return HttpResponse.error();
                }
                current = applyWorkflowOperation(
                    current,
                    operation,
                    calls.length === 1 ? '"wd-two"' : '"wd-three"',
                );
                return mutationResponse(current, `receipt-${calls.length}`);
            }),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "Accepted Workflow value." });
        controller.editMember("member-1", { title: "First Member value." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(() => calls.length === 2);
        controller.editMember("member-1", { title: "Newer Member value." });
        releaseMemberFailure?.();
        await settleUntil(
            () => controller.getSnapshot().save.kind === "offline",
        );

        expect(controller.getSnapshot().acceptedDraft?.etag).toBe('"wd-two"');
        expect(controller.getSnapshot().dirty).toEqual({
            workflow: [],
            memberIds: ["member-1"],
            memberFields: { "member-1": ["title"] },
        });

        await controller.retrySave();

        expect(calls.map((call) => call.etag)).toEqual([
            '"wd-one"',
            '"wd-two"',
            '"wd-two"',
        ]);
        expect(calls.map((call) => call.operation)).toEqual([
            {
                kind: "update_workflow",
                patch: { description: "Accepted Workflow value." },
            },
            {
                kind: "update_member",
                member_id: "member-1",
                patch: { title: "First Member value." },
            },
            {
                kind: "update_member",
                member_id: "member-1",
                patch: { title: "Newer Member value." },
            },
        ]);
        expect(controller.getSnapshot().workingWorkflow?.lead.title).toBe(
            "Newer Member value.",
        );
        expect(controller.getSnapshot().dirty.memberIds).toEqual([]);
        controller.dispose();
    });
});
