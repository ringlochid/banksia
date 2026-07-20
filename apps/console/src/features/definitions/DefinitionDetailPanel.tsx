import { useEffect, useId, useRef, useState, type RefObject } from "react";

import { ExternalLink, X } from "lucide-react";
import { Link } from "react-router-dom";

import { Button, PropertyGrid, StatePanel, StatusChip, TimestampText } from "../../components/ui";
import { isAuthError, type DefinitionsController } from "./definition-controller";
import {
    formatBudgetSpec,
    formatNodeKind,
    formatOptionalInstruction,
    type DefinitionDetailView,
    type DefinitionVersionRow,
    type WorkflowNodeSummary,
} from "./definition-model";

export function DefinitionDetailPanel({
    controller,
}: {
    readonly controller: DefinitionsController;
}) {
    const [isVersionsOpen, setIsVersionsOpen] = useState(false);
    const versionsButtonRef = useRef<HTMLButtonElement | null>(null);
    const handleCloseVersions = () => {
        setIsVersionsOpen(false);
        window.setTimeout(() => {
            versionsButtonRef.current?.focus();
        }, 0);
    };

    if (controller.selectedKey === null) {
        return (
            <StatePanel
                className="m-4"
                summary="Choose a stored role, policy, or workflow to read current detail."
                title="Select a definition"
                tone="empty"
            />
        );
    }

    if (!controller.isSelectedKeyInRows && !controller.listState.isLoading) {
        return (
            <StatePanel
                className="m-4"
                action={<Button onClick={controller.clearFilters}>Clear filters</Button>}
                summary="The selected key is no longer present in the current kind, query, or filter result. Reread or clear filters before trusting current detail."
                title="Selected definition is stale"
                tone="stale"
            />
        );
    }

    if (controller.detailState.isLoading) {
        return (
            <StatePanel
                className="m-4"
                summary="Reading the selected current stored definition revision."
                title="Loading definition detail"
                tone="loading"
            />
        );
    }

    if (controller.detailState.error !== null) {
        return (
            <StatePanel
                className="m-4"
                action={<Button onClick={controller.refresh}>Retry</Button>}
                summary={controller.detailState.error.summary}
                title={
                    isAuthError(controller.detailState.error)
                        ? "Access to definition detail failed"
                        : "Definition detail could not load"
                }
                tone={isAuthError(controller.detailState.error) ? "auth" : "error"}
            />
        );
    }

    if (controller.detailState.detail === null) {
        return (
            <StatePanel
                className="m-4"
                summary="The current selected definition has no detail payload yet."
                title="No detail selected"
                tone="empty"
            />
        );
    }

    return (
        <div className="space-y-4 p-4">
            <DefinitionDetailHeader
                detail={controller.detailState.detail}
                onOpenVersions={() => {
                    setIsVersionsOpen(true);
                }}
                versionsButtonRef={versionsButtonRef}
            />
            <DefinitionDetailSummary detail={controller.detailState.detail} />
            <DefinitionKindDetail detail={controller.detailState.detail} />
            <DefinitionVersionsModal
                controller={controller}
                detail={controller.detailState.detail}
                isOpen={isVersionsOpen}
                onClose={handleCloseVersions}
            />
        </div>
    );
}

function DefinitionDetailHeader({
    detail,
    onOpenVersions,
    versionsButtonRef,
}: {
    readonly detail: DefinitionDetailView;
    readonly onOpenVersions: () => void;
    readonly versionsButtonRef: RefObject<HTMLButtonElement | null>;
}) {
    return (
        <div className="flex min-h-control flex-wrap items-center justify-end gap-2">
            <Link
                className="inline-flex h-8 items-center justify-center gap-2 rounded-control border border-outline bg-surface px-3 font-body text-compact font-semibold text-foreground transition-colors hover:border-primary/45 hover:text-primary-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                to={definitionEditorRoute(detail.kind, detail.key)}
            >
                <span>Edit in draft</span>
                <ExternalLink aria-hidden="true" className="size-3.5 shrink-0" />
            </Link>
            <StatusChip>{detail.kind}</StatusChip>
            <button
                className="inline-flex h-8 items-center justify-center rounded-control border border-outline bg-surface px-3 font-mono text-label font-medium text-foreground transition-colors hover:border-primary/45 hover:text-primary-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                onClick={onOpenVersions}
                ref={versionsButtonRef}
                type="button"
            >
                Revision {detail.revisionNo}
            </button>
        </div>
    );
}

function DefinitionDetailSummary({ detail }: { readonly detail: DefinitionDetailView }) {
    return (
        <div className="rounded-card border border-outline-soft bg-surface-low p-4 shadow-hairline">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <h2
                    className="min-w-0 break-words font-display text-compact font-semibold text-foreground"
                    id="definitions-detail-heading"
                >
                    {detail.key}
                </h2>
                <StatusChip>
                    <span>Updated</span>
                    <TimestampText value={detail.updatedAt} />
                </StatusChip>
            </div>
            <p className="mt-2 break-words text-compact text-muted">{detail.description}</p>
        </div>
    );
}

function DefinitionKindDetail({ detail }: { readonly detail: DefinitionDetailView }) {
    if (detail.kind === "workflow") {
        return <WorkflowDetail detail={detail} />;
    }
    if (detail.kind === "policy") {
        return (
            <div className="space-y-4">
                <ChipSection
                    emptyLabel="No applies-to values reported."
                    label="Applies to"
                    values={detail.appliesTo.map(formatNodeKind)}
                />
                <PropertyGrid
                    items={[{ label: "Budget", value: formatBudgetSpec(detail.budgetSpec) }]}
                />
                <PolicyCapabilities detail={detail} />
                <InstructionSection instruction={detail.instruction} />
            </div>
        );
    }
    return (
        <div className="space-y-4">
            <ChipSection
                emptyLabel="No allowed node kinds reported."
                label="Allowed node kinds"
                values={detail.allowedNodeKinds.map(formatNodeKind)}
            />
            <InstructionSection instruction={detail.instruction} />
        </div>
    );
}

function WorkflowDetail({
    detail,
}: {
    readonly detail: Extract<DefinitionDetailView, { kind: "workflow" }>;
}) {
    return (
        <div className="space-y-4">
            <div className="rounded-card border border-outline-soft bg-surface-low p-4">
                <p className="font-mono text-label font-medium uppercase text-muted">Structure</p>
                <div className="mt-3 rounded-card border border-outline-soft bg-surface px-4 py-3">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <StatusChip>root</StatusChip>
                        <span className="break-words font-display text-compact font-semibold text-foreground">
                            {detail.root.roleId}
                        </span>
                        <StatusChip>{detail.root.policyId}</StatusChip>
                        <WorkflowProviderChips node={detail.root} />
                    </div>
                    <p className="mt-3 max-w-3xl break-words text-compact text-muted">
                        {detail.root.description}
                    </p>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                    <WorkflowMetric label="Children" value={detail.workflowStats.childCount} />
                    <WorkflowMetric label="Leaf roles" value={detail.workflowStats.leafRoleCount} />
                    <WorkflowMetric
                        label="Produced slots"
                        value={detail.workflowStats.producedArtifactCount}
                    />
                </div>
            </div>
            <div className="rounded-card border border-outline-soft bg-surface-low p-4">
                <p className="font-mono text-label font-medium uppercase text-muted">
                    First-level nodes
                </p>
                <ol className="mt-3 space-y-3" aria-label="Workflow first-level nodes">
                    {detail.firstLevelNodes.map((node) => (
                        <WorkflowNodeRow key={node.nodeKey} node={node} />
                    ))}
                </ol>
            </div>
        </div>
    );
}

function WorkflowMetric({ label, value }: { readonly label: string; readonly value: number }) {
    return (
        <div className="rounded-control border border-outline-soft bg-surface px-3 py-3">
            <p className="font-mono text-label font-medium uppercase text-muted">{label}</p>
            <p className="mt-1 font-mono text-utility text-foreground">{value}</p>
        </div>
    );
}

function WorkflowNodeRow({ node }: { readonly node: WorkflowNodeSummary }) {
    return (
        <li className="rounded-card border border-outline-soft bg-surface px-3 py-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <StatusChip>{node.nodeKey}</StatusChip>
                <span className="break-words font-display text-compact font-semibold text-foreground">
                    {node.roleId}
                </span>
                <StatusChip>{node.policyId}</StatusChip>
                <WorkflowProviderChips node={node} />
            </div>
            <p className="mt-2 break-words text-compact text-muted">{node.description}</p>
            {node.childCount === 0 ? null : (
                <p className="mt-2 text-compact text-muted">
                    {node.childCount === 1
                        ? "1 nested node inside this branch."
                        : `${String(node.childCount)} nested nodes inside this branch.`}
                </p>
            )}
            {node.producedSlots.length === 0 ? null : (
                <div className="mt-2 flex min-w-0 flex-wrap gap-2">
                    {node.producedSlots.map((slot) => (
                        <StatusChip key={slot}>{slot}</StatusChip>
                    ))}
                </div>
            )}
        </li>
    );
}

function WorkflowProviderChips({ node }: { readonly node: WorkflowNodeSummary }) {
    return (
        <>
            <StatusChip>
                {node.providerKind === null
                    ? "Provider: machine default"
                    : `Provider: ${formatProviderKind(node.providerKind)} (explicit)`}
            </StatusChip>
            {node.providerKind === "openclaw" ? (
                <StatusChip tone="warning">experimental</StatusChip>
            ) : null}
        </>
    );
}

function PolicyCapabilities({
    detail,
}: {
    readonly detail: Extract<DefinitionDetailView, { kind: "policy" }>;
}) {
    const { capabilities } = detail;
    return (
        <div className="rounded-card border border-outline-soft bg-surface-low p-4">
            <p className="font-mono text-label font-medium uppercase text-muted">
                Policy capability values
            </p>
            <p className="mt-2 text-compact text-muted">
                These are normalized portable policy values, not effective runtime capability
                readback for a dispatch. Explicit-versus-omitted provenance appears only when the
                registry contract preserves it.
            </p>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                <AuthoredCapability
                    basis={capabilities.providerNativeAccess.basis}
                    label="Provider-native access"
                    value={capabilities.providerNativeAccess.value}
                />
                <AuthoredCapability
                    basis={capabilities.networkAccess.basis}
                    label="Network access"
                    value={capabilities.networkAccess.value}
                />
                <AuthoredCapability
                    basis={capabilities.commandRun.basis}
                    label="Command run"
                    value={capabilities.commandRun.value}
                />
                <AuthoredCapability
                    basis={capabilities.humanRequest.basis}
                    label="Human request"
                    value={capabilities.humanRequest.mode}
                />
            </dl>
            {capabilities.humanRequest.allowedKinds.length === 0 ? null : (
                <div className="mt-3 flex flex-wrap gap-2" aria-label="Allowed human request kinds">
                    {capabilities.humanRequest.allowedKinds.map((kind) => (
                        <StatusChip key={kind}>{kind}</StatusChip>
                    ))}
                </div>
            )}
        </div>
    );
}

function AuthoredCapability({
    basis,
    label,
    value,
}: {
    readonly basis: "authored" | "omitted_default" | null;
    readonly label: string;
    readonly value: string;
}) {
    return (
        <div className="rounded-control border border-outline-soft bg-surface px-3 py-3">
            <dt className="font-mono text-label font-medium uppercase text-muted">{label}</dt>
            <dd className="mt-1 text-compact text-foreground">
                <span className="font-semibold">{formatEnum(value)}</span>
                {basis === null ? null : (
                    <span className="text-muted">
                        {basis === "authored" ? " · authored" : " · omitted default"}
                    </span>
                )}
            </dd>
        </div>
    );
}

function ChipSection({
    emptyLabel,
    label,
    values,
}: {
    readonly emptyLabel: string;
    readonly label: string;
    readonly values: readonly string[];
}) {
    return (
        <div className="rounded-card border border-outline-soft bg-surface-low p-4">
            <p className="font-mono text-label font-medium uppercase text-muted">{label}</p>
            {values.length === 0 ? (
                <p className="mt-2 text-compact text-muted">{emptyLabel}</p>
            ) : (
                <div className="mt-3 flex flex-wrap gap-2">
                    {values.map((value) => (
                        <StatusChip key={value}>{value}</StatusChip>
                    ))}
                </div>
            )}
        </div>
    );
}

function InstructionSection({ instruction }: { readonly instruction: string | null }) {
    return (
        <div className="rounded-card border border-outline-soft bg-surface-low p-4">
            <p className="font-mono text-label font-medium uppercase text-muted">Instruction</p>
            <p className="mt-3 whitespace-pre-wrap break-words text-compact text-foreground">
                {formatOptionalInstruction(instruction)}
            </p>
        </div>
    );
}

function DefinitionVersionsModal({
    controller,
    detail,
    isOpen,
    onClose,
}: {
    readonly controller: DefinitionsController;
    readonly detail: DefinitionDetailView;
    readonly isOpen: boolean;
    readonly onClose: () => void;
}) {
    const dialogRef = useRef<HTMLDialogElement | null>(null);
    const titleId = useId();

    useEffect(() => {
        const dialog = dialogRef.current;
        if (dialog === null) return;
        if (isOpen) {
            if (!dialog.open) {
                if (typeof dialog.showModal === "function") {
                    dialog.showModal();
                } else {
                    dialog.setAttribute("open", "");
                }
            }
            return;
        }
        if (dialog.open) {
            if (typeof dialog.close === "function") {
                dialog.close();
            } else {
                dialog.removeAttribute("open");
            }
        }
    }, [isOpen]);

    return (
        <dialog
            aria-labelledby={titleId}
            className="m-auto max-h-[86vh] w-[calc(100%-2rem)] max-w-2xl overflow-hidden rounded-shell border border-outline-soft bg-surface p-0 text-foreground shadow-popover backdrop:bg-black/35"
            onCancel={(event) => {
                event.preventDefault();
                onClose();
            }}
            onClose={onClose}
            ref={dialogRef}
        >
            <header className="flex items-start justify-between gap-4 border-b border-outline-soft bg-surface-muted px-5 py-4">
                <div className="min-w-0">
                    <p className="font-mono text-label font-medium uppercase text-muted">
                        Revisions
                    </p>
                    <h2 className="mt-1 font-display text-compact font-semibold" id={titleId}>
                        Versions
                    </h2>
                    <p className="mt-1 truncate font-mono text-label text-muted">
                        {detail.kind}:{detail.key}
                    </p>
                </div>
                <button
                    aria-label="Close versions"
                    className="inline-flex size-control shrink-0 items-center justify-center rounded-control border border-outline bg-surface-low text-muted transition-colors hover:border-primary/45 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                    onClick={onClose}
                    type="button"
                >
                    <X aria-hidden="true" className="size-4" />
                </button>
            </header>
            <div className="max-h-[calc(86vh-8rem)] overflow-y-auto px-5 py-4">
                <DefinitionVersionsContent controller={controller} />
            </div>
        </dialog>
    );
}

function DefinitionVersionsContent({ controller }: { readonly controller: DefinitionsController }) {
    const { versionsState } = controller;
    if (versionsState.isLoading) {
        return (
            <StatePanel
                summary="Reading stored revision history for this definition."
                title="Loading versions"
                tone="loading"
            />
        );
    }
    if (versionsState.error !== null) {
        return (
            <StatePanel
                action={<Button onClick={controller.refresh}>Retry</Button>}
                summary={versionsState.error.summary}
                title={
                    isAuthError(versionsState.error)
                        ? "Access to version history failed"
                        : "Version history could not load"
                }
                tone={isAuthError(versionsState.error) ? "auth" : "error"}
            />
        );
    }
    if (versionsState.rows.length === 0) {
        return (
            <StatePanel
                summary="The controller returned no revision history entries for this definition."
                title="No versions"
                tone="empty"
            />
        );
    }
    return (
        <div className="space-y-3">
            {versionsState.currentRevisionNo === null ? null : (
                <p className="text-compact text-muted">
                    Current registry pointer: revision {versionsState.currentRevisionNo}.
                </p>
            )}
            {versionsState.rows.length === 1 ? (
                <p className="text-compact text-muted">Single current revision recorded.</p>
            ) : null}
            <ol aria-label="Definition versions" className="space-y-2">
                {versionsState.rows.map((row) => (
                    <DefinitionVersionItem
                        isCurrent={row.revisionNo === versionsState.currentRevisionNo}
                        key={row.revisionNo}
                        row={row}
                    />
                ))}
            </ol>
            <div className="flex flex-col gap-3 border-t border-outline-soft pt-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-compact text-muted">
                    {versionsState.nextCursor === null
                        ? "End of current revision history."
                        : "More revisions are available."}
                </p>
                <Button
                    disabled={versionsState.nextCursor === null || versionsState.isLoadingMore}
                    onClick={controller.loadMoreVersions}
                >
                    {versionsState.isLoadingMore ? "Loading" : "Load more versions"}
                </Button>
            </div>
        </div>
    );
}

function DefinitionVersionItem({
    isCurrent,
    row,
}: {
    readonly isCurrent: boolean;
    readonly row: DefinitionVersionRow;
}) {
    return (
        <li className="rounded-card border border-outline-soft bg-surface px-3 py-3">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <StatusChip>Revision {row.revisionNo}</StatusChip>
                    {isCurrent ? <StatusChip tone="success">Current</StatusChip> : null}
                </div>
                <TimestampText value={row.updatedAt} />
            </div>
            {row.recordedBy === null ? null : (
                <p className="mt-2 text-compact text-muted">Recorded by: {row.recordedBy}</p>
            )}
        </li>
    );
}

function definitionEditorRoute(kind: string, key: string): string {
    const query = new URLSearchParams({ key, kind });
    return `/definitions/editor?${query.toString()}`;
}

function formatProviderKind(kind: WorkflowNodeSummary["providerKind"]): string {
    switch (kind) {
        case "claude":
            return "Claude";
        case "codex":
            return "Codex";
        case "openclaw":
            return "OpenClaw";
        case null:
            return "Machine default";
    }
}

function formatEnum(value: string): string {
    return value.replace(/_/g, " ");
}
