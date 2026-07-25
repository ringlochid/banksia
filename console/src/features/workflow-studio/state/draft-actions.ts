import { ApiResponseError } from "../../../api/client";
import type {
    DraftOperation,
    WorkflowDraftReadback,
    WorkflowGetResponse,
} from "../../../api/types";
import type {
    StudioAmbiguousOperation,
    StudioRecovery,
    StudioStructuralSelectionBasis,
} from "./contracts";
import { draftErrorMessage } from "./draft-failure";
import type { WorkflowDraftRuntime } from "./draft-runtime";
import { EMPTY_DIRTY } from "./reducer";
import { findMember } from "./tree";

export async function openEditableDraft(
    runtime: WorkflowDraftRuntime,
): Promise<void> {
    const catalog = runtime.snapshot().catalog;
    if (catalog === null || !catalog.available_actions.includes("edit")) {
        return;
    }
    const generation = runtime.beginExclusive("opening_draft");
    if (generation === null) {
        return;
    }
    runtime.dispatch(
        { type: "save_changed", save: { kind: "saving" } },
        generation,
    );
    try {
        const { body } = await runtime.api.openWorkflow(runtime.workflowId);
        if (!runtime.isCurrent(generation)) {
            return;
        }
        runtime.resetUndo();
        runtime.dispatch(
            {
                type: "draft_loaded",
                catalog: catalogWithDraft(catalog, body.draft),
                draft: body.draft,
            },
            generation,
        );
    } catch (error) {
        runtime.fail(
            error,
            "The editable draft could not be opened.",
            ambiguousRecovery("opening_draft"),
            generation,
        );
    } finally {
        runtime.finishExclusive("opening_draft", generation);
    }
}

export async function addDraftChild(
    runtime: WorkflowDraftRuntime,
    parentMemberId: string,
): Promise<void> {
    const generation = runtime.beginExclusive("adding_child");
    if (generation === null) {
        return;
    }
    try {
        if (!(await runtime.flushEdits(generation))) {
            return;
        }
        await runtime.enqueue(generation, async () => {
            if (runtime.snapshot().workingWorkflow === null) {
                return;
            }
            runtime.dispatch(
                {
                    type: "structure_changed",
                    pending: { kind: "add_child", parentMemberId },
                },
                generation,
            );
            runtime.dispatch(
                { type: "save_changed", save: { kind: "structural" } },
                generation,
            );
            const operation: DraftOperation = {
                kind: "add_member",
                parent_member_id: parentMemberId,
                member: {},
            };
            const accepted = await runtime.sendOperation(
                operation,
                generation,
                structuralRecovery("adding_child", {
                    kind: "add_parent",
                    memberId: parentMemberId,
                }),
            );
            if (accepted === null) {
                return;
            }
            runtime.acceptMutation(accepted, generation, {
                selectedMemberId: parentMemberId,
            });
        });
    } finally {
        runtime.dispatch(
            { type: "structure_changed", pending: null },
            generation,
        );
        runtime.finishExclusive("adding_child", generation);
    }
}

export async function removeDraftMember(
    runtime: WorkflowDraftRuntime,
    memberId: string,
): Promise<void> {
    const generation = runtime.beginExclusive("removing_member");
    if (generation === null) {
        return;
    }
    try {
        if (!(await runtime.flushEdits(generation))) {
            return;
        }
        await runtime.enqueue(generation, async () => {
            const acceptedBeforeRemoval = runtime.snapshot().acceptedDraft;
            const directParentId =
                acceptedBeforeRemoval === null
                    ? null
                    : (findMember(acceptedBeforeRemoval.workflow.lead, memberId)
                          ?.parentId ?? null);
            const removalParentId =
                directParentId ??
                acceptedBeforeRemoval?.workflow.lead.id ??
                runtime.snapshot().workingWorkflow?.lead.id;
            if (removalParentId === undefined) {
                return;
            }
            runtime.dispatch(
                {
                    type: "structure_changed",
                    pending: { kind: "remove_member", memberId },
                },
                generation,
            );
            runtime.dispatch(
                { type: "save_changed", save: { kind: "structural" } },
                generation,
            );
            const operation: DraftOperation = {
                kind: "remove_member",
                member_id: memberId,
            };
            const accepted = await runtime.sendOperation(
                operation,
                generation,
                structuralRecovery("removing_member", {
                    kind: "remove_parent",
                    memberId: removalParentId,
                }),
            );
            if (accepted !== null) {
                const selectedMemberId =
                    directParentId !== null &&
                    findMember(accepted.draft.workflow.lead, directParentId) !==
                        null
                        ? directParentId
                        : accepted.draft.workflow.lead.id;
                runtime.acceptMutation(accepted, generation, {
                    selectedMemberId,
                });
            }
        });
    } finally {
        runtime.dispatch(
            { type: "structure_changed", pending: null },
            generation,
        );
        runtime.finishExclusive("removing_member", generation);
    }
}

export async function undoDraftChange(
    runtime: WorkflowDraftRuntime,
): Promise<void> {
    const basis = runtime.undoBasis();
    if (!runtime.snapshot().canUndo || basis === null) {
        return;
    }
    const generation = runtime.beginExclusive("undoing");
    if (generation === null) {
        return;
    }
    try {
        await runtime.enqueue(generation, async () => {
            runtime.dispatch(
                { type: "save_changed", save: { kind: "saving" } },
                generation,
            );
            try {
                const response = await runtime.api.undoDraft(
                    basis.draft.draft_id,
                    basis.draft.etag,
                    basis.receipt,
                );
                if (!runtime.isCurrent(generation)) {
                    return;
                }
                runtime.resetUndo();
                runtime.dispatch(
                    {
                        type: "accepted",
                        draft: response.body,
                        working: structuredClone(response.body.workflow),
                        dirty: EMPTY_DIRTY,
                        canUndo: false,
                        save: { kind: "idle" },
                    },
                    generation,
                );
            } catch (error) {
                runtime.resetUndo();
                runtime.dispatch({ type: "undo_invalidated" }, generation);
                if (error instanceof ApiResponseError && error.status === 409) {
                    await runtime.reloadCurrent();
                    return;
                }
                runtime.fail(
                    error,
                    "Undo could not be applied.",
                    ambiguousRecovery("undoing"),
                    generation,
                );
            }
        });
    } finally {
        runtime.finishExclusive("undoing", generation);
    }
}

export async function validateAndPublishDraft(
    runtime: WorkflowDraftRuntime,
): Promise<boolean> {
    const generation = runtime.beginExclusive("validating_publish");
    if (generation === null) {
        return false;
    }
    let published = false;
    try {
        if (!(await runtime.flushEdits(generation))) {
            return false;
        }
        await runtime.enqueue(generation, async () => {
            published = await publishAcceptedDraft(runtime, generation);
        });
    } finally {
        runtime.finishExclusive("validating_publish", generation);
    }
    return published;
}

export async function discardWorkflowDraft(
    runtime: WorkflowDraftRuntime,
): Promise<boolean> {
    if (runtime.snapshot().acceptedDraft === null) {
        return false;
    }
    const generation = runtime.beginExclusive("discarding_draft");
    if (generation === null) {
        return false;
    }
    runtime.clearAutosave();
    let discarded = false;
    try {
        await runtime.enqueue(generation, async () => {
            const draft = runtime.snapshot().acceptedDraft;
            if (draft === null) {
                return;
            }
            runtime.dispatch(
                { type: "save_changed", save: { kind: "saving" } },
                generation,
            );
            try {
                await runtime.api.discardDraft(draft.draft_id, draft.etag);
                if (!runtime.isCurrent(generation)) {
                    return;
                }
                runtime.resetUndo();
                discarded = true;
                if (
                    draft.base_revision_no === null ||
                    draft.base_revision_no === undefined
                ) {
                    return;
                }
                const current = await runtime.api.getWorkflow(
                    runtime.workflowId,
                );
                if (runtime.isCurrent(generation)) {
                    runtime.applyCatalog(current.body, generation);
                }
            } catch (error) {
                runtime.fail(
                    error,
                    "The draft could not be discarded.",
                    discardRecovery(draft),
                    generation,
                );
            }
        });
    } finally {
        runtime.finishExclusive("discarding_draft", generation);
    }
    return discarded;
}

async function publishAcceptedDraft(
    runtime: WorkflowDraftRuntime,
    generation: number,
): Promise<boolean> {
    const draft = runtime.snapshot().acceptedDraft;
    if (draft === null) {
        return false;
    }
    runtime.dispatch(
        {
            type: "validation_changed",
            validation: { kind: "checking" },
        },
        generation,
    );
    try {
        const validation = await runtime.api.validateDraft(draft.draft_id);
        if (!runtime.isCurrent(generation)) {
            return false;
        }
        runtime.acceptValidationDraft(validation.body.draft, generation);
        if (!validation.body.is_valid) {
            runtime.dispatch(
                {
                    type: "validation_changed",
                    validation: {
                        kind: "invalid",
                        issues: validation.body.issues,
                    },
                },
                generation,
            );
            return false;
        }
        await runtime.api.publishDraft(
            validation.body.draft.draft_id,
            validation.body.draft.etag,
        );
        if (!runtime.isCurrent(generation)) {
            return false;
        }
        runtime.resetUndo();
        const current = await runtime.api.getWorkflow(runtime.workflowId);
        if (!runtime.isCurrent(generation)) {
            return false;
        }
        runtime.applyCatalog(current.body, generation);
        return true;
    } catch (error) {
        runtime.dispatch(
            {
                type: "validation_changed",
                validation: {
                    kind: "failed",
                    message: draftErrorMessage(
                        error,
                        "This Workflow could not be published.",
                    ),
                },
            },
            generation,
        );
        runtime.fail(
            error,
            "This Workflow could not be published.",
            ambiguousRecovery("validating_publish"),
            generation,
        );
        return false;
    }
}

function ambiguousRecovery(
    operation: Exclude<
        StudioAmbiguousOperation,
        "adding_child" | "removing_member" | "discarding_draft"
    >,
): Exclude<StudioRecovery, null> {
    return { kind: "check_current", operation };
}

function structuralRecovery(
    operation: "adding_child" | "removing_member",
    selectionBasis: StudioStructuralSelectionBasis,
): Exclude<StudioRecovery, null> {
    return { kind: "check_current", operation, selectionBasis };
}

function discardRecovery(
    draft: WorkflowDraftReadback,
): Exclude<StudioRecovery, null> {
    return {
        kind: "check_current",
        operation: "discarding_draft",
        draftBasis: {
            draftId: draft.draft_id,
            etag: draft.etag,
            baseRevisionNo: draft.base_revision_no ?? null,
        },
    };
}

function catalogWithDraft(
    catalog: WorkflowGetResponse,
    draft: WorkflowDraftReadback,
): WorkflowGetResponse {
    return {
        ...catalog,
        active_draft: draft,
        description: draft.workflow.description,
        state:
            catalog.published_revision_no === null ||
            catalog.published_revision_no === undefined
                ? "draft"
                : "published_with_draft",
    };
}
