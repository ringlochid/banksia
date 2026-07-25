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

import {
    catalogFixture,
    draftFixture,
    TEST_WORKFLOW_ID,
} from "../fixtures/workflows";
import {
    DRAFT_PATH,
    loadedController,
    mutationResponse,
    settleUntil,
    WORKFLOW_PATH,
} from "./workflow-studio-integration-support";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
    server.resetHandlers();
    vi.useRealTimers();
});
afterAll(() => server.close());

describe("Workflow Studio current-truth recovery", () => {
    it("reconciles an uncommitted draft-only discard with one DELETE and one GET", async () => {
        const draftOnly = { ...draftFixture(), base_revision_no: null };
        let reads = 0;
        let deletes = 0;
        server.use(
            http.get(WORKFLOW_PATH, () => {
                reads += 1;
                return HttpResponse.json(
                    catalogFixture({ draft: draftOnly, published: false }),
                );
            }),
            http.delete(DRAFT_PATH, () => {
                deletes += 1;
                return HttpResponse.error();
            }),
        );
        const controller = await loadedController();

        expect(await controller.discardDraft()).toBe(false);
        expect(controller.getSnapshot().recovery).toEqual({
            kind: "check_current",
            operation: "discarding_draft",
            draftBasis: {
                draftId: draftOnly.draft_id,
                etag: draftOnly.etag,
                baseRevisionNo: null,
            },
        });
        await controller.retrySave();

        expect({ deletes, reads }).toEqual({ deletes: 1, reads: 2 });
        expect(controller.getSnapshot().load.kind).toBe("ready");
        expect(controller.getSnapshot().workingWorkflow?.id).toBe(
            TEST_WORKFLOW_ID,
        );
        expect(controller.getSnapshot().recovery).toBeNull();
        expect(controller.getSnapshot().recoveryOutcome).toBeNull();
        controller.dispose();
    });

    it("resolves a lost draft-only discard response from an exact 404 without replay", async () => {
        const draftOnly = { ...draftFixture(), base_revision_no: null };
        let isRemoved = false;
        let reads = 0;
        let deletes = 0;
        server.use(
            http.get(WORKFLOW_PATH, () => {
                reads += 1;
                return isRemoved
                    ? HttpResponse.json(
                          { detail: "Workflow not found." },
                          { status: 404 },
                      )
                    : HttpResponse.json(
                          catalogFixture({
                              draft: draftOnly,
                              published: false,
                          }),
                      );
            }),
            http.delete(DRAFT_PATH, () => {
                deletes += 1;
                isRemoved = true;
                return HttpResponse.error();
            }),
        );
        const controller = await loadedController();

        expect(await controller.discardDraft()).toBe(false);
        await controller.retrySave();

        expect({ deletes, reads }).toEqual({ deletes: 1, reads: 2 });
        expect(controller.getSnapshot().recoveryOutcome).toEqual({
            kind: "workflow_removed",
            workflowId: TEST_WORKFLOW_ID,
        });
        expect(controller.getSnapshot().workingWorkflow).toBeNull();
        controller.dispose();
    });

    it("keeps a published Workflow's discard 404 in normal recovery", async () => {
        let reads = 0;
        let deletes = 0;
        server.use(
            http.get(WORKFLOW_PATH, () => {
                reads += 1;
                return reads === 1
                    ? HttpResponse.json(catalogFixture())
                    : HttpResponse.json(
                          { detail: "Workflow not found." },
                          { status: 404 },
                      );
            }),
            http.delete(DRAFT_PATH, () => {
                deletes += 1;
                return HttpResponse.error();
            }),
        );
        const controller = await loadedController();

        await controller.discardDraft();
        await controller.retrySave();

        expect({ deletes, reads }).toEqual({ deletes: 1, reads: 2 });
        expect(controller.getSnapshot().load.kind).toBe("ready");
        expect(controller.getSnapshot().workingWorkflow).not.toBeNull();
        expect(controller.getSnapshot().recoveryOutcome).toBeNull();
        expect(controller.getSnapshot().recovery).toMatchObject({
            kind: "check_current",
            operation: "discarding_draft",
            draftBasis: { baseRevisionNo: 1 },
        });
        controller.dispose();
    });

    it("keeps Check current actionable when its first truth read fails", async () => {
        const draftOnly = { ...draftFixture(), base_revision_no: null };
        let reads = 0;
        let deletes = 0;
        server.use(
            http.get(WORKFLOW_PATH, () => {
                reads += 1;
                return reads === 2
                    ? HttpResponse.error()
                    : HttpResponse.json(
                          catalogFixture({
                              draft: draftOnly,
                              published: false,
                          }),
                      );
            }),
            http.delete(DRAFT_PATH, () => {
                deletes += 1;
                return HttpResponse.error();
            }),
        );
        const controller = await loadedController();
        const localDescription =
            controller.getSnapshot().workingWorkflow?.description;

        await controller.discardDraft();
        await controller.retrySave();

        expect(controller.getSnapshot().load.kind).toBe("ready");
        expect(controller.getSnapshot().workingWorkflow?.description).toBe(
            localDescription,
        );
        expect(controller.getSnapshot().save.kind).toBe("offline");
        expect(controller.getSnapshot().recovery).toMatchObject({
            kind: "check_current",
            operation: "discarding_draft",
        });

        await controller.retrySave();

        expect({ deletes, reads }).toEqual({ deletes: 1, reads: 3 });
        expect(controller.getSnapshot().recovery).toBeNull();
        controller.dispose();
    });

    it("keeps Reload current actionable when its first truth read fails", async () => {
        vi.useFakeTimers();
        let reads = 0;
        server.use(
            http.get(WORKFLOW_PATH, () => {
                reads += 1;
                return reads === 2
                    ? HttpResponse.error()
                    : HttpResponse.json(catalogFixture());
            }),
            http.patch(DRAFT_PATH, () =>
                HttpResponse.json(
                    {
                        detail: {
                            code: "invalid_request",
                            message: "The current draft version is required.",
                        },
                    },
                    { status: 428 },
                ),
            ),
        );
        const controller = await loadedController();

        controller.editWorkflow({ description: "Keep this local value." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(
            () => controller.getSnapshot().recovery?.kind === "reload_current",
        );
        await controller.retrySave();

        expect(controller.getSnapshot().load.kind).toBe("ready");
        expect(controller.getSnapshot().workingWorkflow?.description).toBe(
            "Keep this local value.",
        );
        expect(controller.getSnapshot().recovery).toEqual({
            kind: "reload_current",
        });

        await controller.retrySave();

        expect(reads).toBe(3);
        expect(controller.getSnapshot().recovery).toBeNull();
        controller.dispose();
    });

    it("preserves the Studio when an Undo conflict truth read fails", async () => {
        vi.useFakeTimers();
        const saved = draftFixture('"wd-two"', "Saved value.");
        let reads = 0;
        server.use(
            http.get(WORKFLOW_PATH, () => {
                reads += 1;
                return reads === 2
                    ? HttpResponse.error()
                    : HttpResponse.json(
                          catalogFixture({
                              draft: reads === 1 ? draftFixture() : saved,
                          }),
                      );
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

        expect(controller.getSnapshot().load.kind).toBe("ready");
        expect(controller.getSnapshot().workingWorkflow?.description).toBe(
            "Saved value.",
        );
        expect(controller.getSnapshot().canUndo).toBe(false);
        expect(controller.getSnapshot().recovery).toEqual({
            kind: "reload_current",
        });

        await controller.retrySave();

        expect(reads).toBe(3);
        expect(controller.getSnapshot().recovery).toBeNull();
        controller.dispose();
    });
});
