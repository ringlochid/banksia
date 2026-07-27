import type {
    MemberCapabilities,
    NewMember,
    NormalizedMember,
    NormalizedWorkflow,
    ProviderSelection,
    WorkflowAuthoringOptions,
    WorkflowDraftReadback,
    WorkflowGetResponse,
    WorkflowValidationIssue,
} from "../../../api/types";

export type WorkflowEditableField = "description" | "note";
export type MemberEditableField =
    "title" | "description" | "instruction" | "provider" | "capabilities";

export interface WorkflowEdit {
    readonly description?: string;
    readonly note?: string | null;
}

export interface MemberEdit {
    readonly title?: string | null;
    readonly description?: string | null;
    readonly instruction?: string | null;
    readonly provider?: ProviderSelection | null;
    readonly capabilities?: MemberCapabilities | null;
}

export interface StudioDirtyState {
    readonly workflow: readonly WorkflowEditableField[];
    readonly memberIds: readonly string[];
    readonly memberFields: Readonly<
        Record<string, readonly MemberEditableField[]>
    >;
}

export type StudioSaveState =
    | { readonly kind: "idle" }
    | { readonly kind: "settling" }
    | { readonly kind: "saving" }
    | { readonly kind: "checking_current" }
    | { readonly kind: "structural" }
    | { readonly kind: "offline"; readonly message: string }
    | { readonly kind: "failed"; readonly message: string }
    | { readonly kind: "conflict" };

export type StudioExclusiveOperation =
    | "opening_draft"
    | "validating_publish"
    | "undoing"
    | "adding_child"
    | "removing_member"
    | "discarding_draft";

export type StudioAmbiguousOperation = StudioExclusiveOperation;

export interface StudioDraftBasis {
    readonly draftId: string;
    readonly etag: string;
    readonly baseRevisionNo: number | null;
}

export type StudioStructuralSelectionBasis =
    | {
          readonly kind: "add_parent";
          readonly memberId: string;
      }
    | {
          readonly kind: "remove_parent";
          readonly memberId: string;
      };

export type StudioRecovery =
    | null
    | { readonly kind: "retry_autosave" }
    | {
          readonly kind: "check_current";
          readonly operation: Exclude<
              StudioAmbiguousOperation,
              "adding_child" | "removing_member" | "discarding_draft"
          >;
      }
    | {
          readonly kind: "check_current";
          readonly operation: "adding_child" | "removing_member";
          readonly selectionBasis: StudioStructuralSelectionBasis;
      }
    | {
          readonly kind: "check_current";
          readonly operation: "discarding_draft";
          readonly draftBasis: StudioDraftBasis;
      }
    | {
          readonly kind: "reload_current";
          readonly selectionBasis?: StudioStructuralSelectionBasis;
      };

export type StudioRecoveryOutcome = null | {
    readonly kind: "workflow_removed";
    readonly workflowId: string;
};

export type PendingStructure =
    | null
    | { readonly kind: "add_child"; readonly parentMemberId: string }
    | { readonly kind: "remove_member"; readonly memberId: string };

export type StudioValidationTarget =
    | {
          readonly kind: "workflow";
          readonly field: WorkflowEditableField;
      }
    | {
          readonly kind: "member";
          readonly memberId: string;
          readonly field: MemberEditableField | `provider.${string}`;
      };

export interface StudioValidationIssue extends WorkflowValidationIssue {
    readonly target?: StudioValidationTarget;
}

export type StudioValidationState =
    | { readonly kind: "unknown" }
    | { readonly kind: "checking" }
    | { readonly kind: "valid" }
    | {
          readonly kind: "invalid";
          readonly issues: readonly StudioValidationIssue[];
      }
    | { readonly kind: "failed"; readonly message: string };

export interface StudioConflict {
    readonly message: string;
    readonly current: WorkflowDraftReadback;
    readonly selectionBasis: StudioStructuralSelectionBasis | null;
}

export type StudioLoadState =
    | { readonly kind: "loading" }
    | { readonly kind: "ready" }
    | { readonly kind: "failed"; readonly message: string };

export interface StudioSnapshot {
    readonly load: StudioLoadState;
    readonly catalog: WorkflowGetResponse | null;
    readonly acceptedDraft: WorkflowDraftReadback | null;
    readonly workingWorkflow: NormalizedWorkflow | null;
    readonly selectedMemberId: string | null;
    readonly dirty: StudioDirtyState;
    readonly save: StudioSaveState;
    readonly exclusiveOperation: StudioExclusiveOperation | null;
    readonly recovery: StudioRecovery;
    readonly recoveryOutcome: StudioRecoveryOutcome;
    readonly pendingStructure: PendingStructure;
    readonly validation: StudioValidationState;
    readonly conflict: StudioConflict | null;
    readonly canUndo: boolean;
}

export interface StudioActions {
    selectMember(memberId: string): void;
    editWorkflow(patch: WorkflowEdit): void;
    editMember(memberId: string, patch: MemberEdit): void;
    addChild(parentMemberId: string, member: NewMember): Promise<string | null>;
    removeMember(memberId: string): Promise<void>;
    retrySave(): Promise<void>;
    undo(): Promise<void>;
    validateAndPublish(): Promise<boolean>;
    discardDraft(): Promise<boolean>;
    reloadCurrent(): Promise<void>;
    copyUnsavedValues(): Promise<boolean>;
}

export interface StudioLifecycleActions {
    activate(): () => void;
    beginEditing(): Promise<void>;
}

export interface StudioContextValue {
    readonly snapshot: StudioSnapshot;
    readonly actions: StudioActions & StudioLifecycleActions;
}

export interface MemberLookup {
    readonly member: NormalizedMember;
    readonly parentId: string | null;
}

export type WorkflowAuthoringOptionsState =
    | { readonly kind: "loading" }
    | {
          readonly kind: "ready";
          readonly options: WorkflowAuthoringOptions;
      }
    | { readonly kind: "error"; readonly message: string };
