import type { WorkflowApi } from "../../../api/client";
import type {
    DraftOperation,
    WorkflowDraftReadback,
    WorkflowGetResponse,
} from "../../../api/types";
import type {
    StudioExclusiveOperation,
    StudioRecovery,
    StudioSnapshot,
} from "./contracts";
import {
    type BuiltDraftEdit,
    buildDraftEditBatch,
    buildNextDraftEdit,
    hasDirtyFields,
    retainNewerDirtyFields,
} from "./edit-operations";
import { mapDraftFailure } from "./draft-failure";
import { EMPTY_DIRTY, type StudioEvent } from "./reducer";
import { overlayDirtyValues } from "./tree";
import { validateLocalWorkflow } from "./validation";

export interface WorkflowDraftRuntimeHost {
    readonly applyCatalog: (
        catalog: WorkflowGetResponse,
        generation: number,
        selectedMemberId?: string,
    ) => void;
    readonly beginExclusive: (
        operation: StudioExclusiveOperation,
    ) => number | null;
    readonly clearAutosave: () => void;
    readonly dispatch: (event: StudioEvent, generation?: number) => void;
    readonly ensureActiveGeneration: () => number | null;
    readonly finishExclusive: (
        operation: StudioExclusiveOperation,
        generation: number,
    ) => void;
    readonly isCurrent: (generation: number) => boolean;
    readonly reloadCurrent: () => Promise<void>;
    readonly snapshot: () => StudioSnapshot;
}

export type AcceptedDraftOperation = {
    readonly draft: WorkflowDraftReadback;
    readonly undoReceipt: string;
};

export class WorkflowDraftRuntime {
    private mutationTail: Promise<void> = Promise.resolve();
    private undoReceipt: string | null = null;

    public constructor(
        public readonly workflowId: string,
        public readonly api: WorkflowApi,
        private readonly host: WorkflowDraftRuntimeHost,
    ) {}

    public snapshot(): StudioSnapshot {
        return this.host.snapshot();
    }

    public beginExclusive(operation: StudioExclusiveOperation): number | null {
        return this.host.beginExclusive(operation);
    }

    public finishExclusive(
        operation: StudioExclusiveOperation,
        generation: number,
    ): void {
        this.host.finishExclusive(operation, generation);
    }

    public dispatch(event: StudioEvent, generation?: number): void {
        this.host.dispatch(event, generation);
    }

    public isCurrent(generation: number): boolean {
        return this.host.isCurrent(generation);
    }

    public applyCatalog(
        catalog: WorkflowGetResponse,
        generation: number,
        selectedMemberId?: string,
    ): void {
        this.host.applyCatalog(catalog, generation, selectedMemberId);
    }

    public async reloadCurrent(): Promise<void> {
        await this.host.reloadCurrent();
    }

    public clearAutosave(): void {
        this.host.clearAutosave();
    }

    public resetUndo(): void {
        this.undoReceipt = null;
    }

    public undoBasis(): {
        readonly draft: WorkflowDraftReadback;
        readonly receipt: string;
    } | null {
        const draft = this.snapshot().acceptedDraft;
        return draft === null || this.undoReceipt === null
            ? null
            : { draft, receipt: this.undoReceipt };
    }

    public async retrySave(): Promise<void> {
        const recovery = this.snapshot().recovery;
        if (recovery === null || this.snapshot().save.kind === "conflict") {
            return;
        }
        if (
            recovery.kind === "check_current" ||
            recovery.kind === "reload_current"
        ) {
            await this.reloadCurrent();
            return;
        }
        const generation = this.host.ensureActiveGeneration();
        if (generation === null) {
            return;
        }
        this.dispatch({ type: "recovery_changed", recovery: null }, generation);
        await this.flushEdits(generation);
    }

    public async deliverAutosave(claim: () => boolean): Promise<void> {
        const generation = this.host.ensureActiveGeneration();
        if (generation === null) {
            return;
        }
        await this.enqueue(generation, async () => {
            if (!claim()) {
                return;
            }
            const edits = buildDraftEditBatch(this.snapshot());
            for (const edit of edits) {
                if (!(await this.performDraftEdit(edit, generation))) {
                    return;
                }
            }
        });
    }

    public async flushEdits(generation: number): Promise<boolean> {
        this.clearAutosave();
        while (
            this.isCurrent(generation) &&
            hasDirtyFields(this.snapshot().dirty)
        ) {
            const workflow = this.snapshot().workingWorkflow;
            if (workflow === null) {
                return false;
            }
            const issues = validateLocalWorkflow(workflow);
            if (issues.length > 0) {
                this.dispatch(
                    {
                        type: "validation_changed",
                        validation: { kind: "invalid", issues },
                    },
                    generation,
                );
                return false;
            }
            let accepted = false;
            await this.enqueue(generation, async () => {
                accepted = await this.performAutosave(generation);
            });
            if (!accepted) {
                return false;
            }
        }
        return this.isCurrent(generation);
    }

    public async enqueue(
        generation: number,
        operation: () => Promise<void>,
    ): Promise<void> {
        const guarded = async () => {
            if (this.isCurrent(generation)) {
                await operation();
            }
        };
        const run = this.mutationTail.then(guarded, guarded);
        this.mutationTail = run.catch(() => undefined);
        return run;
    }

    public async sendOperation(
        operation: DraftOperation,
        generation: number,
        recovery: Exclude<StudioRecovery, null>,
    ): Promise<AcceptedDraftOperation | null> {
        const draft = this.snapshot().acceptedDraft;
        if (draft === null || !this.isCurrent(generation)) {
            return null;
        }
        try {
            const response = await this.api.mutateDraft(
                draft.draft_id,
                draft.etag,
                operation,
            );
            return this.isCurrent(generation)
                ? {
                      draft: response.body.draft,
                      undoReceipt: response.body.undo_receipt,
                  }
                : null;
        } catch (error) {
            this.fail(
                error,
                "Your changes could not be saved.",
                recovery,
                generation,
                operation,
            );
            return null;
        }
    }

    public acceptMutation(
        accepted: AcceptedDraftOperation,
        generation: number,
        options: { readonly selectedMemberId?: string } = {},
    ): void {
        this.undoReceipt = accepted.undoReceipt;
        this.dispatch(
            {
                type: "accepted",
                draft: accepted.draft,
                working: structuredClone(accepted.draft.workflow),
                dirty: EMPTY_DIRTY,
                canUndo: true,
                save: { kind: "idle" },
                ...(options.selectedMemberId === undefined
                    ? {}
                    : { selectedMemberId: options.selectedMemberId }),
            },
            generation,
        );
    }

    public acceptValidationDraft(
        draft: WorkflowDraftReadback,
        generation: number,
    ): void {
        this.dispatch(
            {
                type: "accepted",
                draft,
                working: structuredClone(draft.workflow),
                dirty: EMPTY_DIRTY,
                canUndo: this.undoReceipt !== null,
                save: { kind: "idle" },
            },
            generation,
        );
    }

    public fail(
        error: unknown,
        fallback: string,
        requestedRecovery: Exclude<StudioRecovery, null>,
        generation: number,
        operation?: DraftOperation,
    ): void {
        if (!this.isCurrent(generation)) {
            return;
        }
        this.undoReceipt = null;
        const failure = mapDraftFailure(
            error,
            fallback,
            requestedRecovery,
            operation,
        );
        if (failure.kind === "conflict") {
            this.dispatch(
                {
                    type: "conflict",
                    conflict: {
                        message: failure.message,
                        current: failure.current,
                        selectionBasis: failure.selectionBasis,
                    },
                },
                generation,
            );
            return;
        }
        if (failure.fieldIssue !== null) {
            this.dispatch(
                {
                    type: "validation_changed",
                    validation: {
                        kind: "invalid",
                        issues: [failure.fieldIssue],
                    },
                },
                generation,
            );
        }
        this.dispatch(
            { type: "recovery_changed", recovery: failure.recovery },
            generation,
        );
        this.dispatch({ type: "save_changed", save: failure.save }, generation);
    }

    private async performAutosave(generation: number): Promise<boolean> {
        const edit = buildNextDraftEdit(this.snapshot());
        if (edit === null) {
            return true;
        }
        return this.performDraftEdit(edit, generation);
    }

    private async performDraftEdit(
        edit: BuiltDraftEdit,
        generation: number,
    ): Promise<boolean> {
        const draft = this.snapshot().acceptedDraft;
        if (draft === null || !this.isCurrent(generation)) {
            return true;
        }
        this.dispatch(
            { type: "save_changed", save: { kind: "saving" } },
            generation,
        );
        const accepted = await this.sendOperation(edit.operation, generation, {
            kind: "retry_autosave",
        });
        if (accepted === null || !this.isCurrent(generation)) {
            return false;
        }
        const current = this.snapshot();
        if (current.workingWorkflow === null) {
            return false;
        }
        const remainingDirty = retainNewerDirtyFields(current, edit.sent);
        const working = overlayDirtyValues(
            accepted.draft.workflow,
            current.workingWorkflow,
            remainingDirty,
        );
        this.undoReceipt = accepted.undoReceipt;
        this.dispatch(
            {
                type: "accepted",
                draft: accepted.draft,
                working,
                dirty: remainingDirty,
                canUndo: !hasDirtyFields(remainingDirty),
                save: hasDirtyFields(remainingDirty)
                    ? { kind: "settling" }
                    : { kind: "idle" },
            },
            generation,
        );
        return true;
    }
}
