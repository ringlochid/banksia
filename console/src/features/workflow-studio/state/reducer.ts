import type {
    MemberEdit,
    MemberEditableField,
    PendingStructure,
    StudioConflict,
    StudioDirtyState,
    StudioExclusiveOperation,
    StudioRecovery,
    StudioSaveState,
    StudioSnapshot,
    StudioValidationState,
    WorkflowEdit,
    WorkflowEditableField,
} from "./contracts";
import type {
    NormalizedWorkflow,
    WorkflowDraftReadback,
    WorkflowGetResponse,
} from "../../../api/types";
import { updateWorkflowMember } from "./tree";

export const EMPTY_DIRTY: StudioDirtyState = {
    workflow: [],
    memberIds: [],
    memberFields: {},
};

export const INITIAL_STUDIO_SNAPSHOT: StudioSnapshot = {
    load: { kind: "loading" },
    catalog: null,
    acceptedDraft: null,
    workingWorkflow: null,
    selectedMemberId: null,
    dirty: EMPTY_DIRTY,
    save: { kind: "idle" },
    exclusiveOperation: null,
    recovery: null,
    recoveryOutcome: null,
    pendingStructure: null,
    validation: { kind: "unknown" },
    conflict: null,
    canUndo: false,
};

export type StudioEvent =
    | { readonly type: "loading" }
    | { readonly type: "load_failed"; readonly message: string }
    | { readonly type: "catalog_loaded"; readonly catalog: WorkflowGetResponse }
    | {
          readonly type: "draft_loaded";
          readonly catalog: WorkflowGetResponse;
          readonly draft: WorkflowDraftReadback;
          readonly selectedMemberId?: string;
      }
    | { readonly type: "workflow_edited"; readonly patch: WorkflowEdit }
    | {
          readonly type: "member_edited";
          readonly memberId: string;
          readonly patch: MemberEdit;
      }
    | { readonly type: "selected"; readonly memberId: string }
    | { readonly type: "save_changed"; readonly save: StudioSaveState }
    | {
          readonly type: "exclusive_changed";
          readonly operation: StudioExclusiveOperation | null;
      }
    | { readonly type: "recovery_changed"; readonly recovery: StudioRecovery }
    | { readonly type: "workflow_removed"; readonly workflowId: string }
    | {
          readonly type: "accepted";
          readonly draft: WorkflowDraftReadback;
          readonly working: NormalizedWorkflow;
          readonly dirty: StudioDirtyState;
          readonly canUndo: boolean;
          readonly save: StudioSaveState;
          readonly selectedMemberId?: string;
      }
    | {
          readonly type: "structure_changed";
          readonly pending: PendingStructure;
      }
    | {
          readonly type: "validation_changed";
          readonly validation: StudioValidationState;
      }
    | { readonly type: "conflict"; readonly conflict: StudioConflict }
    | { readonly type: "undo_invalidated" };

export function studioReducer(
    state: StudioSnapshot,
    event: StudioEvent,
): StudioSnapshot {
    switch (event.type) {
        case "loading":
            return { ...state, load: { kind: "loading" } };
        case "load_failed":
            return {
                ...state,
                load: { kind: "failed", message: event.message },
            };
        case "catalog_loaded":
            return catalogState(event.catalog);
        case "draft_loaded":
            return draftState(
                event.catalog,
                event.draft,
                event.selectedMemberId,
            );
        case "workflow_edited":
            return editWorkflowState(state, event.patch);
        case "member_edited":
            return editMemberState(state, event.memberId, event.patch);
        case "selected":
            return { ...state, selectedMemberId: event.memberId };
        case "save_changed":
            return {
                ...state,
                save: event.save,
                canUndo: event.save.kind === "idle" ? state.canUndo : false,
            };
        case "exclusive_changed":
            return {
                ...state,
                exclusiveOperation: event.operation,
                canUndo: event.operation === null ? state.canUndo : false,
            };
        case "recovery_changed":
            return { ...state, recovery: event.recovery };
        case "workflow_removed":
            return {
                ...INITIAL_STUDIO_SNAPSHOT,
                load: { kind: "ready" },
                recoveryOutcome: {
                    kind: "workflow_removed",
                    workflowId: event.workflowId,
                },
            };
        case "structure_changed":
            return {
                ...state,
                pendingStructure: event.pending,
                canUndo: event.pending === null ? state.canUndo : false,
            };
        case "validation_changed":
            return {
                ...state,
                validation: event.validation,
                canUndo:
                    event.validation.kind === "checking"
                        ? false
                        : state.canUndo,
            };
        case "conflict":
            return {
                ...state,
                save: { kind: "conflict" },
                conflict: event.conflict,
                canUndo: false,
            };
        case "undo_invalidated":
            return { ...state, canUndo: false };
        case "accepted":
            return {
                ...state,
                acceptedDraft: event.draft,
                workingWorkflow: event.working,
                dirty: event.dirty,
                save: event.save,
                recovery: null,
                recoveryOutcome: null,
                conflict: null,
                canUndo: event.canUndo,
                selectedMemberId:
                    event.selectedMemberId ?? state.selectedMemberId,
                validation: { kind: "unknown" },
            };
    }
}

function catalogState(catalog: WorkflowGetResponse): StudioSnapshot {
    return {
        ...INITIAL_STUDIO_SNAPSHOT,
        load: { kind: "ready" },
        catalog,
    };
}

function draftState(
    catalog: WorkflowGetResponse,
    draft: WorkflowDraftReadback,
    selectedMemberId?: string,
): StudioSnapshot {
    return {
        ...INITIAL_STUDIO_SNAPSHOT,
        load: { kind: "ready" },
        catalog,
        acceptedDraft: draft,
        workingWorkflow: structuredClone(draft.workflow),
        selectedMemberId: selectedMemberId ?? draft.workflow.lead.id,
    };
}

function editWorkflowState(
    state: StudioSnapshot,
    patch: WorkflowEdit,
): StudioSnapshot {
    if (state.workingWorkflow === null) {
        return state;
    }
    const fields = Object.keys(patch) as WorkflowEditableField[];
    return {
        ...state,
        workingWorkflow: { ...state.workingWorkflow, ...patch },
        dirty: {
            ...state.dirty,
            workflow: union(state.dirty.workflow, fields),
        },
        save: { kind: "settling" },
        recovery: null,
        validation: { kind: "unknown" },
        canUndo: false,
    };
}

function editMemberState(
    state: StudioSnapshot,
    memberId: string,
    patch: MemberEdit,
): StudioSnapshot {
    if (state.workingWorkflow === null) {
        return state;
    }
    const fields = Object.keys(patch) as MemberEditableField[];
    return {
        ...state,
        workingWorkflow: updateWorkflowMember(
            state.workingWorkflow,
            memberId,
            patch,
        ),
        dirty: {
            ...state.dirty,
            memberIds: union(state.dirty.memberIds, [memberId]),
            memberFields: {
                ...state.dirty.memberFields,
                [memberId]: union(
                    state.dirty.memberFields[memberId] ?? [],
                    fields,
                ),
            },
        },
        save: { kind: "settling" },
        recovery: null,
        validation: { kind: "unknown" },
        canUndo: false,
    };
}

function union<T>(
    current: readonly T[],
    additions: readonly T[],
): readonly T[] {
    return [...new Set([...current, ...additions])];
}
