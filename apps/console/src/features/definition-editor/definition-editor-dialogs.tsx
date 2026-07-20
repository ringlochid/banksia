import { FilePenLine } from "lucide-react";

import { Button, StatePanel } from "../../components/ui";
import type { ConsoleErrorView } from "../../api/client";
import { DefinitionEditorDialog } from "./DefinitionEditorDialog";
import type {
    DefinitionDraftKind,
    DefinitionDraftMode,
    DraftDetail,
    DraftPublishResponse,
    DraftValidationResponse,
} from "./definition-editor-data";

export interface NewDraftFormState {
    readonly description: string;
    readonly error: ConsoleErrorView | null;
    readonly isCreating: boolean;
    readonly isOpen: boolean;
    readonly key: string;
    readonly kind: DefinitionDraftKind;
    readonly mode: DefinitionDraftMode;
}

export type DraftOperation =
    "discarding" | "publishing" | "replacing" | "resetting" | "saving" | "validating" | null;

export type DraftConfirmation = "discard" | "replace" | "reset";

export type DraftActionDialog =
    | {
          readonly kind: "publish";
          readonly result: DraftPublishResponse;
      }
    | {
          readonly kind: "validation";
          readonly validation: DraftValidationResponse;
      }
    | null;

const DRAFT_KIND_OPTIONS: readonly DefinitionDraftKind[] = ["role", "policy", "workflow"];

export function UnsavedDraftChangesDialog({
    onDiscard,
    onKeepEditing,
}: {
    readonly onDiscard: () => void;
    readonly onKeepEditing: () => void;
}) {
    return (
        <DefinitionEditorDialog
            closeLabel="Close unsaved changes"
            eyebrow="Unsaved changes"
            footer={
                <>
                    <Button data-dialog-initial-focus onClick={onKeepEditing}>
                        Keep editing
                    </Button>
                    <Button onClick={onDiscard} variant="danger">
                        Discard local edits
                    </Button>
                </>
            }
            onClose={onKeepEditing}
            title="Discard local draft edits?"
        >
            <p className="text-compact text-muted">
                These textarea edits exist only in this browser tab. Discard them before leaving
                this draft, or keep editing and save first.
            </p>
        </DefinitionEditorDialog>
    );
}

export function DraftOperationNavigationDialog({ onStay }: { readonly onStay: () => void }) {
    return (
        <DefinitionEditorDialog
            eyebrow="Draft operation"
            footer={
                <Button data-dialog-initial-focus onClick={onStay}>
                    Stay on this draft
                </Button>
            }
            onClose={onStay}
            title="Draft operation still in progress"
        >
            <p className="text-compact text-muted">
                Wait for the current save, validation, publish, or draft action to finish before
                leaving. Its response belongs to this exact draft and will not be applied elsewhere.
            </p>
        </DefinitionEditorDialog>
    );
}

export function DraftActionConfirmDialog({
    action,
    draft,
    isBusy,
    onCancel,
    onConfirm,
    operation,
    operationError,
}: {
    readonly action: DraftConfirmation;
    readonly draft: DraftDetail;
    readonly isBusy: boolean;
    readonly onCancel: () => void;
    readonly onConfirm: () => void;
    readonly operation: DraftOperation;
    readonly operationError: ConsoleErrorView | null;
}) {
    const copy = draftConfirmationCopy(action);
    const isActionBusy = operation === draftConfirmationOperation(action);

    return (
        <DefinitionEditorDialog
            canClose={!isBusy}
            closeLabel="Close draft action"
            eyebrow="Draft action"
            footer={
                <>
                    <Button
                        data-dialog-initial-focus
                        disabled={isBusy}
                        onClick={onCancel}
                        variant="secondary"
                    >
                        Cancel
                    </Button>
                    <Button disabled={isBusy} onClick={onConfirm} variant="danger">
                        {isActionBusy ? copy.busyLabel : copy.confirmLabel}
                    </Button>
                </>
            }
            onClose={onCancel}
            title={copy.title}
        >
            <p className="text-compact leading-6 text-muted">{copy.description}</p>
            <div className="rounded-card border border-outline-soft bg-surface-low px-4 py-3">
                <dl className="grid gap-3 sm:grid-cols-2">
                    <div className="min-w-0">
                        <dt className="font-mono text-label font-medium uppercase text-muted">
                            Selected draft
                        </dt>
                        <dd className="mt-1 break-words font-mono text-utility text-foreground">
                            {draft.kind}/{draft.key}
                        </dd>
                    </div>
                    <div className="min-w-0">
                        <dt className="font-mono text-label font-medium uppercase text-muted">
                            Baseline
                        </dt>
                        <dd className="mt-1 font-mono text-utility text-foreground">
                            {draftBaselineLabel(draft)}
                        </dd>
                    </div>
                </dl>
            </div>
            {operationError === null ? null : (
                <StatePanel
                    summary={operationError.summary}
                    title={operationError.title}
                    tone="error"
                />
            )}
        </DefinitionEditorDialog>
    );
}

export function DraftActionResultDialog({
    dialog,
    onClose,
}: {
    readonly dialog: Exclude<DraftActionDialog, null>;
    readonly onClose: () => void;
}) {
    const title =
        dialog.kind === "validation"
            ? `Validation ${statusLabel(dialog.validation.status)}`
            : `Publish ${statusLabel(dialog.result.status)}`;
    const kind = dialog.kind === "validation" ? dialog.validation.kind : dialog.result.kind;
    const key = dialog.kind === "validation" ? dialog.validation.key : dialog.result.key;
    const outcome = dialog.kind === "validation" ? dialog.validation.status : dialog.result.status;

    return (
        <DefinitionEditorDialog
            closeLabel="Close draft action"
            eyebrow="Draft action"
            footer={
                <Button data-dialog-initial-focus onClick={onClose}>
                    Close
                </Button>
            }
            onClose={onClose}
            title={title}
        >
            <div className="rounded-card border border-outline-soft bg-surface-low px-4 py-3">
                <dl className="grid gap-3 sm:grid-cols-2">
                    <div className="min-w-0">
                        <dt className="font-mono text-label font-medium uppercase text-muted">
                            Selected draft
                        </dt>
                        <dd className="mt-1 break-words font-mono text-utility text-foreground">
                            {kind}:{key}
                        </dd>
                    </div>
                    <div className="min-w-0">
                        <dt className="font-mono text-label font-medium uppercase text-muted">
                            Outcome
                        </dt>
                        <dd className="mt-1 font-mono text-utility text-foreground">
                            {statusLabel(outcome)}
                        </dd>
                    </div>
                </dl>
            </div>
            {dialog.kind === "validation" ? (
                <ValidationPanel validation={dialog.validation} />
            ) : (
                <PublishPanel result={dialog.result} />
            )}
        </DefinitionEditorDialog>
    );
}

export function NewDraftDialog({
    form,
    onCancel,
    onChange,
    onCreate,
}: {
    readonly form: NewDraftFormState;
    readonly onCancel: () => void;
    readonly onChange: (form: NewDraftFormState) => void;
    readonly onCreate: () => void;
}) {
    return (
        <DefinitionEditorDialog
            canClose={!form.isCreating}
            closeLabel="Close new draft"
            eyebrow="Draft"
            footer={
                <>
                    <Button disabled={form.isCreating} onClick={onCancel} variant="secondary">
                        Cancel
                    </Button>
                    <Button
                        disabled={form.isCreating}
                        icon={<FilePenLine className="size-4" />}
                        type="submit"
                        variant="primary"
                    >
                        {form.isCreating ? "Creating" : "Create draft"}
                    </Button>
                </>
            }
            onClose={onCancel}
            onSubmit={(event) => {
                event.preventDefault();
                onCreate();
            }}
            title="New draft"
        >
            {form.error === null ? null : (
                <StatePanel summary={form.error.summary} title={form.error.title} tone="error" />
            )}
            <label className="grid gap-2" htmlFor="new-draft-kind">
                <span className="font-mono text-label font-medium uppercase text-muted">Kind</span>
                <select
                    className={controlClassName()}
                    disabled={form.isCreating}
                    id="new-draft-kind"
                    onChange={(event) => {
                        onChange({ ...form, kind: event.target.value as DefinitionDraftKind });
                    }}
                    value={form.kind}
                >
                    {DRAFT_KIND_OPTIONS.map((kind) => (
                        <option key={kind} value={kind}>
                            {kindLabel(kind)}
                        </option>
                    ))}
                </select>
            </label>
            <label className="grid gap-2" htmlFor="new-draft-mode">
                <span className="font-mono text-label font-medium uppercase text-muted">Mode</span>
                <select
                    className={controlClassName()}
                    disabled={form.isCreating}
                    id="new-draft-mode"
                    onChange={(event) => {
                        onChange({ ...form, mode: event.target.value as DefinitionDraftMode });
                    }}
                    value={form.mode}
                >
                    <option value="create">Create new</option>
                    <option value="update">Edit existing</option>
                </select>
            </label>
            <label className="grid gap-2" htmlFor="new-draft-key">
                <span className="font-mono text-label font-medium uppercase text-muted">Key</span>
                <input
                    className={controlClassName()}
                    data-dialog-initial-focus
                    disabled={form.isCreating}
                    id="new-draft-key"
                    onChange={(event) => {
                        onChange({ ...form, key: event.target.value, error: null });
                    }}
                    value={form.key}
                />
            </label>
            {form.mode === "create" ? (
                <label className="grid gap-2" htmlFor="new-draft-description">
                    <span className="font-mono text-label font-medium uppercase text-muted">
                        Description
                    </span>
                    <input
                        className={controlClassName()}
                        disabled={form.isCreating}
                        id="new-draft-description"
                        onChange={(event) => {
                            onChange({ ...form, description: event.target.value });
                        }}
                        value={form.description}
                    />
                </label>
            ) : null}
        </DefinitionEditorDialog>
    );
}

function ValidationPanel({ validation }: { readonly validation: DraftValidationResponse }) {
    const tone =
        validation.status === "valid"
            ? "success"
            : validation.status === "stale"
              ? "stale"
              : "error";
    return (
        <StatePanel
            summary={
                <IssueList
                    emptyText="No validation issues returned."
                    items={[...validation.errors, ...validation.warnings]}
                />
            }
            title={`Validation ${statusLabel(validation.status)}`}
            tone={tone}
        />
    );
}

function PublishPanel({ result }: { readonly result: DraftPublishResponse }) {
    const tone =
        result.status === "published" ? "success" : result.status === "stale" ? "stale" : "error";
    return (
        <StatePanel
            summary={
                result.published_revision === null ? (
                    <IssueList
                        emptyText="No revision was published."
                        items={[...result.validation.errors, ...result.validation.warnings]}
                    />
                ) : (
                    <div className="space-y-2">
                        <p>
                            {kindLabel(result.published_revision.kind)}{" "}
                            {result.published_revision.key} revision{" "}
                            {result.published_revision.revision_no}
                        </p>
                        <p className="text-muted">
                            This is the publish response. Reread the published registry to confirm
                            its current pointer; the editor's refreshed draft baseline is separate.
                        </p>
                    </div>
                )
            }
            title={`Publish ${statusLabel(result.status)}`}
            tone={tone}
        />
    );
}

function IssueList({
    emptyText,
    items,
}: {
    readonly emptyText: string;
    readonly items: readonly {
        readonly code: string;
        readonly message: string;
        readonly path?: string | null;
    }[];
}) {
    if (items.length === 0) {
        return <p>{emptyText}</p>;
    }

    return (
        <ul className="grid gap-2">
            {items.map((item) => (
                <li className="min-w-0" key={`${item.code}:${item.path ?? item.message}`}>
                    <p className="font-semibold text-foreground">{item.message}</p>
                    <p className="break-words font-mono text-label text-muted">
                        {item.code}
                        {item.path === null || item.path === undefined ? "" : ` · ${item.path}`}
                    </p>
                </li>
            ))}
        </ul>
    );
}

function draftConfirmationCopy(action: DraftConfirmation): {
    readonly busyLabel: string;
    readonly confirmLabel: string;
    readonly description: string;
    readonly title: string;
} {
    switch (action) {
        case "discard":
            return {
                busyLabel: "Discarding",
                confirmLabel: "Discard saved draft",
                description:
                    "This permanently removes the saved draft file. It does not change current stored registry truth or publish changes.",
                title: "Discard saved draft",
            };
        case "replace":
            return {
                busyLabel: "Replacing",
                confirmLabel: "Replace draft",
                description:
                    "This discards draft edits, reads the current stored registry revision, and updates the draft baseline. It does not apply or launch anything.",
                title: "Replace with current stored revision",
            };
        case "reset":
            return {
                busyLabel: "Resetting",
                confirmLabel: "Reset draft",
                description:
                    "This discards draft edits and restores the selected file to its captured draft baseline. It does not read current stored truth or publish changes.",
                title: "Reset draft",
            };
    }
}

function draftConfirmationOperation(action: DraftConfirmation): Exclude<DraftOperation, null> {
    switch (action) {
        case "discard":
            return "discarding";
        case "replace":
            return "replacing";
        case "reset":
            return "resetting";
    }
}

function draftBaselineLabel(draft: DraftDetail): string {
    const revisionNo = draft.based_on.revision_no;
    if (revisionNo !== null && revisionNo !== undefined) {
        return `rev ${String(revisionNo)}`;
    }
    return draft.mode === "create" ? "template" : "current";
}

function kindLabel(kind: DefinitionDraftKind): string {
    switch (kind) {
        case "policy":
            return "Policy";
        case "role":
            return "Role";
        case "workflow":
            return "Workflow";
    }
}

function statusLabel(status: string): string {
    return status.replace(/_/g, " ");
}

function controlClassName(): string {
    return "h-control w-full min-w-0 rounded-control border border-outline bg-surface-low px-3 text-compact text-foreground shadow-hairline focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15";
}
