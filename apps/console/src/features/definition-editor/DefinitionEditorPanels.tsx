import type { ReactNode } from "react";

import { CheckCircle2, RefreshCw, Rocket, RotateCcw, Save, Trash2 } from "lucide-react";

import { Button, StatePanel, StatusChip } from "../../components/ui";
import { classNames } from "../../lib/classNames";
import { isAuthError, type DraftIdentity } from "./definition-editor-data";
import {
    draftIdentityEquals,
    draftIdentityFromSummary,
    kindLabel,
    modeLabel,
    statusLabel,
    statusTone,
} from "./definition-editor-model";
import type { DefinitionEditorController } from "./use-definition-editor-controller";

export function DefinitionEditorPanels({
    controller,
}: {
    readonly controller: DefinitionEditorController;
}) {
    return (
        <div className="grid min-w-0 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
            <DraftListPanel controller={controller} />
            <DraftEditorPanel controller={controller} />
        </div>
    );
}

function DraftListPanel({ controller }: { readonly controller: DefinitionEditorController }) {
    const { listState } = controller;
    return (
        <aside className="flex min-h-[640px] min-w-0 flex-col overflow-hidden rounded-card border border-outline-soft bg-surface-low">
            <header className="flex shrink-0 items-center justify-between gap-3 border-b border-outline-soft p-4">
                <div className="min-w-0">
                    <p className="font-mono text-label font-medium uppercase text-muted">Drafts</p>
                    <h2 className="mt-1 font-display text-[18px] font-semibold leading-6 text-foreground">
                        Saved drafts
                    </h2>
                </div>
            </header>
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
                {listState.error === null ? null : (
                    <StatePanel
                        action={<Button onClick={controller.refreshList}>Retry</Button>}
                        summary={listState.error.summary}
                        title={
                            isAuthError(listState.error)
                                ? "Access to drafts failed"
                                : "Drafts could not load"
                        }
                        tone={isAuthError(listState.error) ? "auth" : "error"}
                    />
                )}
                {listState.isLoading && listState.rows.length === 0 ? (
                    <StatePanel title="Loading drafts" tone="loading" />
                ) : null}
                {!listState.isLoading && listState.rows.length === 0 && listState.error === null ? (
                    <StatePanel
                        summary="Use New draft above to start one."
                        title="No saved drafts"
                    />
                ) : null}
                {listState.rows.length === 0 ? null : (
                    <ol aria-label="Saved definition drafts" className="flex flex-col gap-2">
                        {listState.rows.map((row) => {
                            const identity = draftIdentityFromSummary(row);
                            const isSelected = draftIdentityEquals(identity, controller.selection);
                            return (
                                <li key={`${identity.kind}:${identity.key}`}>
                                    <DraftRowButton
                                        identity={identity}
                                        isBusy={controller.isBusy}
                                        isSelected={isSelected}
                                        onSelect={controller.selectDraft}
                                        row={row}
                                    />
                                </li>
                            );
                        })}
                    </ol>
                )}
                {listState.nextCursor === null ? null : (
                    <Button disabled={listState.isLoading} onClick={controller.loadMoreDrafts}>
                        Load more
                    </Button>
                )}
            </div>
        </aside>
    );
}

function DraftRowButton({
    identity,
    isBusy,
    isSelected,
    onSelect,
    row,
}: {
    readonly identity: DraftIdentity;
    readonly isBusy: boolean;
    readonly isSelected: boolean;
    readonly onSelect: (identity: DraftIdentity | null) => void;
    readonly row: DefinitionEditorController["listState"]["rows"][number];
}) {
    return (
        <button
            aria-pressed={isSelected}
            className={classNames(
                "block w-full min-w-0 rounded-card border p-3 text-left transition-colors",
                isSelected
                    ? "border-primary/45 bg-active text-active-foreground"
                    : "border-outline-soft bg-surface hover:border-primary/35",
            )}
            disabled={isBusy}
            onClick={() => {
                onSelect(identity);
            }}
            type="button"
        >
            <div className="flex min-w-0 items-center gap-2">
                <StatusChip tone="neutral">{kindLabel(row.kind)}</StatusChip>
                <StatusChip tone={statusTone(row.status)}>{statusLabel(row.status)}</StatusChip>
            </div>
            <p className="mt-3 truncate font-display text-compact font-semibold text-foreground">
                {row.key}
            </p>
            <p className="mt-1 font-mono text-label text-muted">{modeLabel(row.mode)}</p>
        </button>
    );
}

function DraftEditorPanel({ controller }: { readonly controller: DefinitionEditorController }) {
    const { currentDraft, detailState } = controller;
    if (detailState.isLoading) {
        return (
            <DraftEditorEmptySurface>
                <StatePanel title="Loading draft" tone="loading" />
            </DraftEditorEmptySurface>
        );
    }
    if (detailState.error !== null) {
        return (
            <DraftEditorEmptySurface>
                <StatePanel
                    action={<Button onClick={controller.refreshSelected}>Retry</Button>}
                    summary={detailState.error.summary}
                    title={
                        isAuthError(detailState.error)
                            ? "Access to draft failed"
                            : "Selected draft could not load"
                    }
                    tone={isAuthError(detailState.error) ? "auth" : "error"}
                />
            </DraftEditorEmptySurface>
        );
    }
    if (currentDraft === null) {
        return (
            <DraftEditorEmptySurface>
                {controller.listState.rows.length === 0 ? (
                    <StatePanel summary="Create a draft to start editing." title="No drafts yet" />
                ) : (
                    <StatePanel title="Select a draft" />
                )}
            </DraftEditorEmptySurface>
        );
    }

    const canSave = !controller.isBusy && (!currentDraft.is_saved || controller.isDirty);
    const canDiscard = !controller.isBusy && currentDraft.is_saved;
    const canReset = canDiscard && currentDraft.baseline_body !== null;
    const canReplaceWithCurrent = canDiscard && currentDraft.mode === "update";

    return (
        <section className="flex min-h-[640px] min-w-0 flex-col rounded-card border border-outline-soft bg-surface-low">
            <header className="flex flex-col gap-4 border-b border-outline-soft p-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0">
                    <p className="font-mono text-label font-medium uppercase text-muted">Draft</p>
                    <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2">
                        <h2 className="min-w-0 break-words font-display text-[20px] font-semibold leading-6 text-foreground">
                            {currentDraft.key}
                        </h2>
                        <StatusChip tone="neutral">{kindLabel(currentDraft.kind)}</StatusChip>
                        <StatusChip tone="neutral">{modeLabel(currentDraft.mode)}</StatusChip>
                        <StatusChip tone={statusTone(currentDraft.status)}>
                            {statusLabel(currentDraft.status)}
                        </StatusChip>
                        {controller.isDirty ? (
                            <StatusChip tone="warning">local edits</StatusChip>
                        ) : null}
                    </div>
                </div>
                <div className="flex flex-wrap gap-2">
                    <Button
                        disabled={!canSave}
                        icon={<Save className="size-4" />}
                        onClick={controller.saveDraft}
                        variant="secondary"
                    >
                        {controller.operation === "saving" ? "Saving" : "Save draft"}
                    </Button>
                    <Button
                        disabled={controller.isBusy}
                        icon={<CheckCircle2 className="size-4" />}
                        onClick={controller.validateDraft}
                        variant="secondary"
                    >
                        {controller.operation === "validating" ? "Validating" : "Validate"}
                    </Button>
                    <Button
                        disabled={controller.isBusy}
                        icon={<Rocket className="size-4" />}
                        onClick={controller.publishDraft}
                        variant="primary"
                    >
                        {controller.operation === "publishing" ? "Publishing" : "Publish"}
                    </Button>
                </div>
            </header>
            <div className="grid min-w-0 gap-4 p-4">
                {controller.operationError === null ? null : (
                    <StatePanel
                        summary={controller.operationError.summary}
                        title={controller.operationError.title}
                        tone="error"
                    />
                )}
                <label className="grid gap-2" htmlFor="definition-draft-body">
                    <span className="font-mono text-label font-medium uppercase text-muted">
                        Draft body
                    </span>
                    <textarea
                        className="definition-editor-body min-h-[520px] w-full min-w-0 rounded-card border border-outline bg-surface p-4 text-[14px] text-foreground shadow-hairline focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
                        disabled={controller.isBusy}
                        id="definition-draft-body"
                        onChange={(event) => {
                            controller.setEditorBody(event.target.value);
                        }}
                        onKeyDown={controller.handleDraftBodyKeyDown}
                        spellCheck={false}
                        value={controller.editorBody}
                    />
                </label>
                <DraftSecondaryActions
                    canDiscard={canDiscard}
                    canReplaceWithCurrent={canReplaceWithCurrent}
                    canReset={canReset}
                    controller={controller}
                />
            </div>
        </section>
    );
}

function DraftSecondaryActions({
    canDiscard,
    canReplaceWithCurrent,
    canReset,
    controller,
}: {
    readonly canDiscard: boolean;
    readonly canReplaceWithCurrent: boolean;
    readonly canReset: boolean;
    readonly controller: DefinitionEditorController;
}) {
    return (
        <div className="flex flex-wrap justify-end gap-2 border-t border-outline-soft pt-4">
            <Button
                disabled={!canReset}
                icon={<RotateCcw className="size-4" />}
                onClick={() => {
                    controller.openDraftConfirmation("reset");
                }}
                variant="secondary"
            >
                {controller.operation === "resetting" ? "Resetting" : "Reset draft"}
            </Button>
            <Button
                disabled={!canReplaceWithCurrent}
                icon={<RefreshCw className="size-4" />}
                onClick={() => {
                    controller.openDraftConfirmation("replace");
                }}
                variant="secondary"
            >
                {controller.operation === "replacing"
                    ? "Replacing"
                    : "Replace with current stored revision"}
            </Button>
            <Button
                disabled={!canDiscard}
                icon={<Trash2 className="size-4" />}
                onClick={() => {
                    controller.openDraftConfirmation("discard");
                }}
                variant="danger"
            >
                {controller.operation === "discarding" ? "Discarding" : "Discard saved draft"}
            </Button>
        </div>
    );
}

function DraftEditorEmptySurface({ children }: { readonly children: ReactNode }) {
    return (
        <section className="flex min-h-[640px] min-w-0 items-start rounded-card border border-outline-soft bg-surface-low p-4">
            <div className="w-full">{children}</div>
        </section>
    );
}
