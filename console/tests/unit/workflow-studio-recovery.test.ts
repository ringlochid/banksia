import { afterEach, describe, expect, it, vi } from "vitest";

import {
    ApiNetworkError,
    ApiResponseError,
    type ControllerResponse,
    type WorkflowApi,
} from "../../src/api/client";
import type { WorkflowDraftReadback } from "../../src/api/types";
import { WorkflowStudioController } from "../../src/features/workflow-studio/state/controller";
import {
    catalogFixture,
    draftFixture,
    response,
    TEST_WORKFLOW_ID,
    workflowApiStub,
} from "../fixtures/workflows";

afterEach(() => {
    vi.useRealTimers();
});

describe("Workflow Studio exclusive operations", () => {
    it.each([
        ["validating_publish", "publish"],
        ["adding_child", "add"],
        ["removing_member", "remove"],
        ["undoing", "undo"],
        ["discarding_draft", "discard"],
    ] as const)(
        "rejects local edits while %s owns the draft boundary",
        async (expectedOperation, action) => {
            vi.useFakeTimers();
            const gate = deferred<void>();
            const initial = draftFixture();
            const added = addChild(initial, '"wd-added"');
            const removed = removeChild(initial, '"wd-removed"');
            const api = workflowApiStub({
                getWorkflow: () => Promise.resolve(response(catalogFixture())),
                mutateDraft: (_draftId, _etag, operation) => {
                    if (operation.kind === "add_member") {
                        return action === "add"
                            ? gate.promise.then(() =>
                                  mutationResponse(added, "receipt-add"),
                              )
                            : Promise.resolve(
                                  mutationResponse(added, "receipt-add"),
                              );
                    }
                    if (operation.kind === "remove_member") {
                        return gate.promise.then(() =>
                            mutationResponse(removed, "receipt-remove"),
                        );
                    }
                    return Promise.resolve(
                        mutationResponse(initial, "receipt-edit"),
                    );
                },
                validateDraft: () =>
                    gate.promise.then(() =>
                        response({
                            is_valid: false,
                            issues: [],
                            draft: initial,
                        }),
                    ),
                publishDraft: unexpected,
                discardDraft: () =>
                    gate.promise.then(() =>
                        response({
                            is_discarded: true,
                            draft_id: initial.draft_id,
                        }),
                    ),
                undoDraft: () => gate.promise.then(() => response(initial)),
            });
            const controller = await loadedController(api);
            if (action === "undo") {
                await controller.addChild("member-1");
                expect(controller.getSnapshot().canUndo).toBe(true);
            }

            const operation =
                action === "publish"
                    ? controller.validateAndPublish()
                    : action === "add"
                      ? controller.addChild("member-1")
                      : action === "remove"
                        ? controller.removeMember("member-2")
                        : action === "undo"
                          ? controller.undo()
                          : controller.discardDraft();
            await settleUntil(
                () =>
                    controller.getSnapshot().exclusiveOperation ===
                    expectedOperation,
            );
            const description =
                controller.getSnapshot().workingWorkflow?.description;

            controller.editWorkflow({
                description: "This edit must be rejected.",
            });

            expect(controller.getSnapshot().workingWorkflow?.description).toBe(
                description,
            );
            gate.resolve();
            await operation;
            controller.dispose();
        },
    );
});

describe("Workflow Studio typed recovery state", () => {
    it.each([
        ["validation", "validating_publish"],
        ["publish", "validating_publish"],
        ["add", "adding_child"],
        ["remove", "removing_member"],
        ["undo", "undoing"],
        ["discard", "discarding_draft"],
    ] as const)(
        "checks current truth instead of blindly repeating an ambiguous %s failure",
        async (failurePoint, expectedOperation) => {
            const calls = {
                add: 0,
                discard: 0,
                publish: 0,
                remove: 0,
                undo: 0,
                validation: 0,
            };
            let reads = 0;
            const initial = draftFixture();
            const added = addChild(initial, '"wd-added"');
            const api = workflowApiStub({
                getWorkflow: () => {
                    reads += 1;
                    return Promise.resolve(
                        response(
                            catalogFixture({
                                draft:
                                    failurePoint === "undo" && reads > 1
                                        ? added
                                        : initial,
                            }),
                        ),
                    );
                },
                mutateDraft: (_draftId, _etag, operation) => {
                    if (operation.kind === "add_member") {
                        calls.add += 1;
                        return failurePoint === "add"
                            ? Promise.reject(networkFailure())
                            : Promise.resolve(
                                  mutationResponse(added, "receipt-add"),
                              );
                    }
                    if (operation.kind === "remove_member") {
                        calls.remove += 1;
                        return failurePoint === "remove"
                            ? Promise.reject(networkFailure())
                            : Promise.resolve(
                                  mutationResponse(
                                      removeChild(initial, '"wd-removed"'),
                                      "receipt-remove",
                                  ),
                              );
                    }
                    return Promise.resolve(
                        mutationResponse(initial, "receipt-edit"),
                    );
                },
                validateDraft: () => {
                    calls.validation += 1;
                    return failurePoint === "validation"
                        ? Promise.reject(networkFailure())
                        : Promise.resolve(
                              response({
                                  is_valid: true,
                                  issues: [],
                                  draft: initial,
                              }),
                          );
                },
                publishDraft: () => {
                    calls.publish += 1;
                    return failurePoint === "publish"
                        ? Promise.reject(networkFailure())
                        : Promise.resolve(
                              response({
                                  workflow_id: TEST_WORKFLOW_ID,
                                  revision_no: 2,
                                  workflow: initial.workflow,
                              }),
                          );
                },
                discardDraft: () => {
                    calls.discard += 1;
                    return failurePoint === "discard"
                        ? Promise.reject(networkFailure())
                        : Promise.resolve(
                              response({
                                  is_discarded: true,
                                  draft_id: initial.draft_id,
                              }),
                          );
                },
                undoDraft: () => {
                    calls.undo += 1;
                    return failurePoint === "undo"
                        ? Promise.reject(networkFailure())
                        : Promise.resolve(response(initial));
                },
            });
            const controller = await loadedController(api);
            if (failurePoint === "undo") {
                await controller.addChild("member-1");
            }

            if (failurePoint === "validation" || failurePoint === "publish") {
                await controller.validateAndPublish();
            } else if (failurePoint === "add") {
                await controller.addChild("member-1");
            } else if (failurePoint === "remove") {
                await controller.removeMember("member-2");
            } else if (failurePoint === "undo") {
                await controller.undo();
            } else {
                await controller.discardDraft();
            }

            expect(controller.getSnapshot().recovery).toEqual(
                failurePoint === "discard"
                    ? {
                          kind: "check_current",
                          operation: "discarding_draft",
                          draftBasis: {
                              draftId: initial.draft_id,
                              etag: initial.etag,
                              baseRevisionNo: initial.base_revision_no,
                          },
                      }
                    : failurePoint === "add"
                      ? {
                            kind: "check_current",
                            operation: "adding_child",
                            selectionBasis: {
                                kind: "add_parent",
                                memberId: "member-1",
                            },
                        }
                      : failurePoint === "remove"
                        ? {
                              kind: "check_current",
                              operation: "removing_member",
                              selectionBasis: {
                                  kind: "remove_parent",
                                  memberId: "member-1",
                              },
                          }
                        : {
                              kind: "check_current",
                              operation: expectedOperation,
                          },
            );
            expect(controller.getSnapshot().save.kind).toBe("offline");
            const description =
                controller.getSnapshot().workingWorkflow?.description;
            controller.editWorkflow({ description: "Do not accept this." });
            expect(controller.getSnapshot().workingWorkflow?.description).toBe(
                description,
            );

            await controller.retrySave();

            expect(reads).toBe(2);
            expect(calls[failurePoint]).toBe(1);
            expect(controller.getSnapshot().recovery).toBeNull();
            controller.dispose();
        },
    );

    it("keeps a rejected provider field_path exact and retryable", async () => {
        vi.useFakeTimers();
        const draft = {
            ...draftFixture(),
            workflow: {
                ...draftFixture().workflow,
                lead: {
                    ...draftFixture().workflow.lead,
                    provider: { kind: "codex" as const },
                },
            },
        };
        const api = workflowApiStub({
            getWorkflow: () =>
                Promise.resolve(response(catalogFixture({ draft }))),
            mutateDraft: () =>
                Promise.reject(
                    new ApiResponseError(422, {
                        ok: false,
                        code: "invalid_request",
                        summary: "That model is unavailable.",
                        retryable: false,
                        field_path: "patch.provider.model",
                    }),
                ),
        });
        const controller = await loadedController(api);

        controller.editMember("member-1", {
            provider: { kind: "codex", model: "missing-model" },
        });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(
            () => controller.getSnapshot().save.kind === "failed",
        );

        expect(controller.getSnapshot().validation).toEqual({
            kind: "invalid",
            issues: [
                {
                    source: "controller",
                    path: "patch.provider.model",
                    message: "That model is unavailable.",
                    target: {
                        kind: "member",
                        memberId: "member-1",
                        field: "provider.model",
                    },
                },
            ],
        });
        expect(controller.getSnapshot().recovery).toEqual({
            kind: "retry_autosave",
        });
        controller.dispose();
    });
});

describe("Workflow Studio activation generations", () => {
    it("ignores a stale mutation completion after deactivation and reloads normally", async () => {
        vi.useFakeTimers();
        const mutationGate = deferred<
            ControllerResponse<{
                draft: WorkflowDraftReadback;
                undo_receipt: string;
            }>
        >();
        let reads = 0;
        let mutations = 0;
        const reloaded = draftFixture(
            '"wd-current"',
            "Current controller truth.",
        );
        const api = workflowApiStub({
            getWorkflow: () => {
                reads += 1;
                return Promise.resolve(
                    response(
                        catalogFixture({
                            draft: reads === 1 ? draftFixture() : reloaded,
                        }),
                    ),
                );
            },
            mutateDraft: () => {
                mutations += 1;
                return mutationGate.promise;
            },
        });
        const controller = new WorkflowStudioController(TEST_WORKFLOW_ID, api);
        const deactivateFirst = controller.activate();
        await settleUntil(() => controller.getSnapshot().load.kind === "ready");
        controller.editWorkflow({ description: "Stale local value." });
        await vi.advanceTimersByTimeAsync(500);
        await settleUntil(() => mutations === 1);

        deactivateFirst();
        const deactivateSecond = controller.activate();
        await settleUntil(
            () =>
                reads === 2 &&
                controller.getSnapshot().workingWorkflow?.description ===
                    "Current controller truth.",
        );
        mutationGate.resolve(
            mutationResponse(
                draftFixture('"wd-stale"', "Stale local value."),
                "receipt-stale",
            ),
        );
        await vi.advanceTimersByTimeAsync(0);

        expect(controller.getSnapshot().workingWorkflow?.description).toBe(
            "Current controller truth.",
        );
        deactivateSecond();
        controller.dispose();
    });
});

async function loadedController(
    api: WorkflowApi,
): Promise<WorkflowStudioController> {
    const controller = new WorkflowStudioController(TEST_WORKFLOW_ID, api);
    await controller.load();
    expect(controller.getSnapshot().load.kind).toBe("ready");
    return controller;
}

function mutationResponse(
    draft: WorkflowDraftReadback,
    receipt: string,
): ControllerResponse<{
    draft: WorkflowDraftReadback;
    undo_receipt: string;
}> {
    return response({ draft, undo_receipt: receipt });
}

function addChild(
    draft: WorkflowDraftReadback,
    etag: string,
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
                    { id: "member-3", title: "New teammate" },
                ],
            },
        },
    };
}

function removeChild(
    draft: WorkflowDraftReadback,
    etag: string,
): WorkflowDraftReadback {
    return {
        ...draft,
        etag,
        workflow: {
            ...draft.workflow,
            lead: { ...draft.workflow.lead, children: [] },
        },
    };
}

function networkFailure(): ApiNetworkError {
    return new ApiNetworkError(new Error("Connection lost."));
}

function unexpected<T>(): Promise<T> {
    return Promise.reject(new Error("Unexpected API call."));
}

function deferred<T>(): {
    readonly promise: Promise<T>;
    readonly resolve: (value?: T) => void;
} {
    let resolvePromise: ((value: T) => void) | undefined;
    const promise = new Promise<T>((resolve) => {
        resolvePromise = resolve;
    });
    return {
        promise,
        resolve: (value) => resolvePromise?.(value as T),
    };
}

async function settleUntil(condition: () => boolean): Promise<void> {
    for (let attempt = 0; attempt < 100; attempt += 1) {
        if (condition()) {
            return;
        }
        await vi.advanceTimersByTimeAsync(0);
    }
    throw new Error("Controller did not settle within the bounded test loop");
}
