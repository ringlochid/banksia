import { ApiResponseError, type WorkflowApi } from "../../../api/client";
import type { WorkflowGetResponse } from "../../../api/types";
import { AutosaveDeadline } from "./autosave-deadline";
import type {
    MemberEdit,
    StudioActions,
    StudioExclusiveOperation,
    StudioLifecycleActions,
    StudioRecovery,
    StudioSnapshot,
    StudioStructuralSelectionBasis,
    WorkflowEdit,
} from "./contracts";
import {
    addDraftChild,
    discardWorkflowDraft,
    openEditableDraft,
    removeDraftMember,
    undoDraftChange,
    validateAndPublishDraft,
} from "./draft-actions";
import { draftErrorMessage } from "./draft-failure";
import { WorkflowDraftRuntime } from "./draft-runtime";
import { buildUnsavedValues } from "./edit-operations";
import {
    INITIAL_STUDIO_SNAPSHOT,
    studioReducer,
    type StudioEvent,
} from "./reducer";
import { findMember } from "./tree";
import { validateLocalWorkflow } from "./validation";

type Listener = () => void;

export class WorkflowStudioController
    implements StudioActions, StudioLifecycleActions
{
    private snapshot: StudioSnapshot = INITIAL_STUDIO_SNAPSHOT;
    private readonly listeners = new Set<Listener>();
    private readonly autosave: AutosaveDeadline;
    private readonly draftRuntime: WorkflowDraftRuntime;
    private activationGeneration = 0;
    private isActive = false;
    private isDisposed = false;
    private loadAbortController: AbortController | null = null;
    private currentReadAbortController: AbortController | null = null;

    public constructor(
        private readonly workflowId: string,
        private readonly api: WorkflowApi,
    ) {
        this.draftRuntime = new WorkflowDraftRuntime(workflowId, api, {
            applyCatalog: (catalog, generation, selectedMemberId) =>
                this.applyCatalog(catalog, generation, selectedMemberId),
            beginExclusive: (operation) => this.beginExclusive(operation),
            clearAutosave: () => this.autosave.clear(),
            dispatch: (event, generation) => this.dispatch(event, generation),
            ensureActiveGeneration: () => this.ensureActiveGeneration(),
            finishExclusive: (operation, generation) =>
                this.finishExclusive(operation, generation),
            isCurrent: (generation) => this.isCurrent(generation),
            reloadCurrent: () => this.reloadCurrent(),
            snapshot: this.getSnapshot,
        });
        this.autosave = new AutosaveDeadline((claim) =>
            this.draftRuntime.deliverAutosave(claim),
        );
    }

    public getSnapshot = (): StudioSnapshot => this.snapshot;

    public subscribe = (listener: Listener): (() => void) => {
        this.listeners.add(listener);
        return () => {
            this.listeners.delete(listener);
        };
    };

    public activate(): () => void {
        if (this.isDisposed) {
            return () => undefined;
        }
        const generation = this.startActivation();
        void this.loadGeneration(generation);
        return () => {
            this.deactivate(generation);
        };
    }

    public async load(): Promise<void> {
        const generation = this.ensureActiveGeneration();
        if (generation !== null) {
            await this.loadGeneration(generation);
        }
    }

    public async beginEditing(): Promise<void> {
        await openEditableDraft(this.draftRuntime);
    }

    public selectMember(memberId: string): void {
        if (
            this.snapshot.workingWorkflow !== null &&
            findMember(this.snapshot.workingWorkflow.lead, memberId) !== null
        ) {
            this.dispatch({ type: "selected", memberId });
        }
    }

    public editWorkflow(patch: WorkflowEdit): void {
        if (!this.canAcceptLocalEdit()) {
            return;
        }
        this.dispatch({ type: "workflow_edited", patch });
        this.scheduleAutosave();
    }

    public editMember(memberId: string, patch: MemberEdit): void {
        if (!this.canAcceptLocalEdit()) {
            return;
        }
        this.dispatch({ type: "member_edited", memberId, patch });
        this.scheduleAutosave();
    }

    public async addChild(parentMemberId: string): Promise<void> {
        await addDraftChild(this.draftRuntime, parentMemberId);
    }

    public async removeMember(memberId: string): Promise<void> {
        await removeDraftMember(this.draftRuntime, memberId);
    }

    public async retrySave(): Promise<void> {
        await this.draftRuntime.retrySave();
    }

    public async undo(): Promise<void> {
        await undoDraftChange(this.draftRuntime);
    }

    public async validateAndPublish(): Promise<boolean> {
        return validateAndPublishDraft(this.draftRuntime);
    }

    public async discardDraft(): Promise<boolean> {
        return discardWorkflowDraft(this.draftRuntime);
    }

    public async reloadCurrent(): Promise<void> {
        const generation = this.ensureActiveGeneration();
        if (generation === null || this.currentReadAbortController !== null) {
            return;
        }
        this.autosave.clear();
        this.draftRuntime.resetUndo();
        const recovery = recoveryForCurrentRead(this.snapshot.recovery);
        const selectionBasis = selectionBasisForCurrentRead(
            this.snapshot,
            recovery,
        );
        const abortController = new AbortController();
        this.currentReadAbortController = abortController;
        this.dispatch(
            { type: "save_changed", save: { kind: "checking_current" } },
            generation,
        );
        try {
            const { body } = await this.api.getWorkflow(
                this.workflowId,
                abortController.signal,
            );
            if (this.isCurrent(generation)) {
                this.applyCatalog(body, generation, selectionBasis);
            }
        } catch (error) {
            if (
                !this.isCurrent(generation) ||
                isAbortError(error) ||
                abortController.signal.aborted
            ) {
                return;
            }
            if (isRemovedDraftOnlyWorkflow(error, recovery)) {
                this.dispatch(
                    {
                        type: "workflow_removed",
                        workflowId: this.workflowId,
                    },
                    generation,
                );
                return;
            }
            this.draftRuntime.fail(
                error,
                "Banksia could not check the latest Workflow.",
                recovery,
                generation,
            );
        } finally {
            if (this.currentReadAbortController === abortController) {
                this.currentReadAbortController = null;
            }
        }
    }

    public async copyUnsavedValues(): Promise<boolean> {
        const payload = buildUnsavedValues(this.snapshot);
        if (payload === null) {
            return false;
        }
        try {
            await navigator.clipboard.writeText(
                JSON.stringify(payload, null, 2),
            );
            return true;
        } catch {
            return false;
        }
    }

    public dispose(): void {
        if (this.isDisposed) {
            return;
        }
        this.isDisposed = true;
        this.isActive = false;
        this.activationGeneration += 1;
        this.loadAbortController?.abort();
        this.loadAbortController = null;
        this.currentReadAbortController?.abort();
        this.currentReadAbortController = null;
        this.autosave.clear();
        this.listeners.clear();
    }

    private startActivation(): number {
        this.activationGeneration += 1;
        this.isActive = true;
        return this.activationGeneration;
    }

    private ensureActiveGeneration(): number | null {
        if (this.isDisposed) {
            return null;
        }
        return this.isActive
            ? this.activationGeneration
            : this.startActivation();
    }

    private deactivate(generation: number): void {
        if (!this.isCurrent(generation)) {
            return;
        }
        this.isActive = false;
        this.loadAbortController?.abort();
        this.loadAbortController = null;
        this.currentReadAbortController?.abort();
        this.currentReadAbortController = null;
        this.autosave.clear();
    }

    private async loadGeneration(generation: number): Promise<void> {
        if (!this.isCurrent(generation)) {
            return;
        }
        this.loadAbortController?.abort();
        const abortController = new AbortController();
        this.loadAbortController = abortController;
        this.dispatch({ type: "loading" }, generation);
        try {
            const { body } = await this.api.getWorkflow(
                this.workflowId,
                abortController.signal,
            );
            if (this.isCurrent(generation)) {
                this.applyCatalog(body, generation);
            }
        } catch (error) {
            if (
                this.isCurrent(generation) &&
                !isAbortError(error) &&
                !abortController.signal.aborted
            ) {
                this.dispatch(
                    {
                        type: "load_failed",
                        message: draftErrorMessage(
                            error,
                            "This Workflow could not be opened.",
                        ),
                    },
                    generation,
                );
            }
        } finally {
            if (this.loadAbortController === abortController) {
                this.loadAbortController = null;
            }
        }
    }

    private beginExclusive(operation: StudioExclusiveOperation): number | null {
        const generation = this.ensureActiveGeneration();
        if (
            generation === null ||
            this.snapshot.exclusiveOperation !== null ||
            this.snapshot.conflict !== null ||
            this.snapshot.recovery !== null
        ) {
            return null;
        }
        this.dispatch({ type: "exclusive_changed", operation }, generation);
        return generation;
    }

    private finishExclusive(
        operation: StudioExclusiveOperation,
        generation: number,
    ): void {
        if (
            this.isCurrent(generation) &&
            this.snapshot.exclusiveOperation === operation
        ) {
            this.dispatch(
                { type: "exclusive_changed", operation: null },
                generation,
            );
        }
    }

    private canAcceptLocalEdit(): boolean {
        return (
            this.isActive &&
            this.snapshot.workingWorkflow !== null &&
            this.snapshot.exclusiveOperation === null &&
            this.snapshot.conflict === null &&
            (this.snapshot.recovery === null ||
                this.snapshot.recovery.kind === "retry_autosave")
        );
    }

    private scheduleAutosave(): void {
        const workflow = this.snapshot.workingWorkflow;
        if (workflow === null) {
            return;
        }
        const issues = validateLocalWorkflow(workflow);
        if (issues.length > 0) {
            this.autosave.clear();
            this.dispatch({
                type: "validation_changed",
                validation: { kind: "invalid", issues },
            });
            return;
        }
        this.autosave.recordEdit();
    }

    private applyCatalog(
        catalog: WorkflowGetResponse,
        generation: number,
        selectedMemberId?: string,
    ): void {
        this.draftRuntime.resetUndo();
        if (
            catalog.active_draft === null ||
            catalog.active_draft === undefined
        ) {
            this.dispatch({ type: "catalog_loaded", catalog }, generation);
            return;
        }
        this.dispatch(
            {
                type: "draft_loaded",
                catalog,
                draft: catalog.active_draft,
                ...(selectedMemberId !== undefined &&
                findMember(
                    catalog.active_draft.workflow.lead,
                    selectedMemberId,
                ) !== null
                    ? { selectedMemberId }
                    : {}),
            },
            generation,
        );
    }

    private isCurrent(generation: number): boolean {
        return (
            !this.isDisposed &&
            this.isActive &&
            this.activationGeneration === generation
        );
    }

    private dispatch(
        event: StudioEvent,
        generation = this.activationGeneration,
    ): void {
        if (!this.isCurrent(generation)) {
            return;
        }
        this.snapshot = studioReducer(this.snapshot, event);
        for (const listener of this.listeners) {
            listener();
        }
    }
}

function selectionBasisForCurrentRead(
    snapshot: StudioSnapshot,
    recovery: Exclude<StudioRecovery, null>,
): string | undefined {
    const structural =
        structuralSelectionBasis(recovery) ??
        snapshot.conflict?.selectionBasis ??
        null;
    return structural?.memberId ?? snapshot.selectedMemberId ?? undefined;
}

function structuralSelectionBasis(
    recovery: Exclude<StudioRecovery, null>,
): StudioStructuralSelectionBasis | null {
    return "selectionBasis" in recovery
        ? (recovery.selectionBasis ?? null)
        : null;
}

function isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError";
}

function recoveryForCurrentRead(
    recovery: StudioRecovery,
): Exclude<StudioRecovery, null> {
    return recovery?.kind === "check_current" ||
        recovery?.kind === "reload_current"
        ? recovery
        : { kind: "reload_current" };
}

function isRemovedDraftOnlyWorkflow(
    error: unknown,
    recovery: Exclude<StudioRecovery, null>,
): boolean {
    return (
        error instanceof ApiResponseError &&
        error.status === 404 &&
        recovery.kind === "check_current" &&
        recovery.operation === "discarding_draft" &&
        recovery.draftBasis.baseRevisionNo === null
    );
}
