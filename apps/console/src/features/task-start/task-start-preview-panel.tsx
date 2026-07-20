import type { ReactNode } from "react";

import { Button, IdRefText, StatePanel, StatusChip } from "../../components/ui";
import type { TaskStartController } from "./task-start-controller";
import { isAuthError } from "./task-start-data";
import { TaskStartDialog } from "./task-start-dialog";
import type {
    TaskStartPreview,
    TaskStartPreviewIssue,
    TaskStartPreviewNode,
} from "./task-start-model";

export function PreviewPanel({ controller }: { readonly controller: TaskStartController }) {
    const { previewState } = controller;
    const preview = previewState.preview;
    const canStart = preview?.status === "ready" && !controller.submitState.isSubmitting;

    return (
        <TaskStartDialog
            footer={
                <>
                    <Button
                        data-dialog-initial-focus
                        onClick={() => {
                            controller.setPreviewOpen(false);
                        }}
                    >
                        Back to edit
                    </Button>
                    {previewState.error === null ? null : (
                        <Button onClick={controller.showPreview}>Retry preview</Button>
                    )}
                    <Button
                        className="disabled:border-outline disabled:bg-outline disabled:text-white disabled:opacity-100"
                        disabled={!canStart}
                        onClick={controller.start}
                        variant="primary"
                    >
                        {controller.submitState.isSubmitting ? "Starting" : "Start Task"}
                    </Button>
                </>
            }
            label="Preview"
            onClose={() => {
                controller.setPreviewOpen(false);
            }}
            title="Preview"
        >
            <PreviewContent controller={controller} />
        </TaskStartDialog>
    );
}

function PreviewContent({ controller }: { readonly controller: TaskStartController }) {
    const { previewState } = controller;
    if (previewState.isLoading) {
        return (
            <StatePanel
                summary="The controller is resolving current registry, provider, path, and capability truth."
                title="Resolving preview"
                tone="loading"
            />
        );
    }

    if (previewState.error !== null) {
        return (
            <StatePanel
                summary={previewState.error.summary}
                title={
                    isAuthError(previewState.error)
                        ? "Access to preview failed"
                        : "Preview could not be resolved"
                }
                tone={isAuthError(previewState.error) ? "auth" : "error"}
            />
        );
    }

    if (previewState.preview === null) {
        return <StatePanel title="No preview response" tone="empty" />;
    }

    return <ResolvedPreview preview={previewState.preview} />;
}

function ResolvedPreview({ preview }: { readonly preview: TaskStartPreview }) {
    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-display text-compact font-semibold text-foreground">
                    Current controller resolution
                </p>
                <StatusChip tone={preview.status === "ready" ? "success" : "danger"}>
                    {preview.status}
                </StatusChip>
            </div>
            <p className="rounded-card border border-outline-soft bg-surface-low px-4 py-3 text-compact text-muted">
                Preview validates and resolves current controller truth. It does not reserve task or
                dispatch IDs, create a compiled plan, mutate provider defaults, contact a live
                provider, or guarantee that a later start will succeed. Start rereads and
                revalidates current truth independently.
            </p>
            <dl className="overflow-hidden rounded-card border border-outline-soft bg-surface-low">
                <PreviewReadbackRow label="Workflow">
                    <p className="break-all font-mono text-compact font-semibold text-foreground">
                        {preview.workflowKey}
                    </p>
                    <p className="mt-1 break-words text-compact text-muted">
                        {preview.workflowDescription}
                    </p>
                </PreviewReadbackRow>
                <PreviewReadbackRow label="Task">
                    <p className="break-words font-display text-compact font-semibold text-foreground">
                        {preview.title}
                    </p>
                    <IdRefText className="mt-1 break-all" value={preview.taskKey} />
                </PreviewReadbackRow>
                <PreviewReadbackRow label="Summary">{preview.summary}</PreviewReadbackRow>
                <PreviewReadbackRow label="Instruction">
                    {preview.instructionSummary}
                </PreviewReadbackRow>
                <PreviewReadbackRow label="Workspace">
                    <p className="font-display text-compact font-semibold text-foreground">
                        {preview.workspaceModeLabel}
                    </p>
                    <p className="mt-1 text-compact text-muted">{preview.workspaceSummary}</p>
                    {preview.workspaceHostPath === null ? null : (
                        <IdRefText className="mt-1 break-all" value={preview.workspaceHostPath} />
                    )}
                </PreviewReadbackRow>
            </dl>
            <PreviewIssues label="Errors" issues={preview.errors} />
            <PreviewIssues label="Warnings" issues={preview.warnings} />
            <PreviewNodes nodes={preview.nodes} />
            <p className="text-compact text-muted">
                Provider setup, checks, and default changes remain CLI-only. This page only reads
                the resolution returned by the controller.
            </p>
        </div>
    );
}

function PreviewNodes({ nodes }: { readonly nodes: readonly TaskStartPreviewNode[] }) {
    if (nodes.length === 0) {
        return (
            <StatePanel
                summary="Resolve the reported errors before relying on provider or capability readback."
                title="No ready workflow nodes"
                tone="empty"
            />
        );
    }

    return (
        <div className="space-y-3">
            <h3 className="font-display text-compact font-semibold text-foreground">
                Node resolution
            </h3>
            <ol aria-label="Task compose node preview" className="space-y-3">
                {nodes.map((node) => (
                    <li
                        className="rounded-card border border-outline-soft bg-surface-low p-4"
                        key={node.nodeKey}
                    >
                        <div className="flex flex-wrap items-center gap-2">
                            <IdRefText value={node.nodeKey} />
                            <StatusChip>{formatProvider(node.resolvedProvider)}</StatusChip>
                            <StatusChip>{formatSelectionBasis(node.selectionBasis)}</StatusChip>
                            {node.isExperimentalProvider ? (
                                <StatusChip tone="warning">experimental</StatusChip>
                            ) : null}
                        </div>
                        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                            <CapabilityReadback
                                effective={node.providerNativeAccess.effective}
                                label="Provider-native access"
                                source={node.providerNativeAccess.source}
                            />
                            <CapabilityReadback
                                effective={node.networkAccess.effective}
                                label="Network access"
                                source={node.networkAccess.source}
                            />
                        </dl>
                        <p className="mt-3 text-utility text-muted">
                            Requested {formatProvider(node.requestedProvider)}; resolved{" "}
                            {formatProvider(node.resolvedProvider)}. Target routing has no fallback.
                        </p>
                    </li>
                ))}
            </ol>
        </div>
    );
}

function CapabilityReadback({
    effective,
    label,
    source,
}: {
    readonly effective: string;
    readonly label: string;
    readonly source: string;
}) {
    return (
        <div className="rounded-control border border-outline-soft bg-surface px-3 py-3">
            <dt className="font-mono text-label font-medium uppercase text-muted">{label}</dt>
            <dd className="mt-1 text-compact text-foreground">
                <span className="font-semibold">{formatEnum(effective)}</span>
                <span className="text-muted"> from {formatEnum(source)}</span>
            </dd>
        </div>
    );
}

function PreviewIssues({
    issues,
    label,
}: {
    readonly issues: readonly TaskStartPreviewIssue[];
    readonly label: string;
}) {
    if (issues.length === 0) {
        return null;
    }

    return (
        <section aria-label={`Preview ${label.toLowerCase()}`} className="space-y-2">
            <h3 className="font-display text-compact font-semibold text-foreground">{label}</h3>
            <ul className="space-y-2">
                {issues.map((issue, index) => (
                    <li
                        className="rounded-control border border-outline-soft bg-surface-low px-3 py-3 text-compact text-foreground"
                        key={`${issue.code}:${issue.path ?? "root"}:${String(index)}`}
                    >
                        <span className="font-semibold">{issue.message}</span>
                        <span className="mt-1 block font-mono text-utility text-muted">
                            {issue.kind} · {issue.code}
                            {issue.path === null ? "" : ` · ${issue.path}`}
                        </span>
                    </li>
                ))}
            </ul>
        </section>
    );
}

function PreviewReadbackRow({
    children,
    label,
}: {
    readonly children: ReactNode;
    readonly label: string;
}) {
    return (
        <div className="grid gap-3 border-b border-outline-soft px-4 py-3 last:border-b-0 sm:grid-cols-[8.5rem_minmax(0,1fr)]">
            <dt className="font-mono text-label font-medium uppercase text-muted">{label}</dt>
            <dd className="min-w-0 text-compact text-foreground">{children}</dd>
        </div>
    );
}

function formatProvider(provider: string): string {
    return provider === "openclaw" ? "OpenClaw" : provider === "codex" ? "Codex" : "Claude";
}

function formatSelectionBasis(basis: string): string {
    return basis === "explicit" ? "Explicit selection" : "Machine default";
}

function formatEnum(value: string): string {
    return value.replace(/_/g, " ");
}
