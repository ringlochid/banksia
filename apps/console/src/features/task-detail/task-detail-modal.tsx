import { type KeyboardEvent, type ReactNode, useEffect, useRef } from "react";

import { X } from "lucide-react";
import { Link } from "react-router-dom";

import { CodeBlock, StatePanel, StatusChip, Tabs } from "../../components/ui";
import type { TaskDetailController } from "./task-detail-controller";
import { titleCaseNodeLabel } from "./task-detail-format";
import {
    TASK_DETAIL_TABS,
    commandRunTone,
    humanRequestTone,
    type DetailRow,
    type TaskDetailRef,
    type TaskDetailTab,
    type TaskDetailView,
    type TaskGraphNode,
} from "./task-detail-model";
import { TaskDetailTimestamp } from "./task-detail-summary";

export function TaskDetailModal({
    context,
    onClose,
    onTabChange,
    tab,
    taskId,
    view,
}: {
    readonly context: NonNullable<TaskDetailController["selectedContext"]>;
    readonly onClose: () => void;
    readonly onTabChange: (tab: TaskDetailTab) => void;
    readonly tab: TaskDetailTab;
    readonly taskId: string;
    readonly view: TaskDetailView;
}) {
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const dialogRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        closeButtonRef.current?.focus({ preventScroll: true });
    }, []);

    const handleDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (event.key !== "Tab") {
            return;
        }

        const dialogElement = dialogRef.current;
        if (dialogElement === null) {
            return;
        }

        const focusableElements = getFocusableElements(dialogElement);
        if (focusableElements.length === 0) {
            event.preventDefault();
            return;
        }
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (event.shiftKey && document.activeElement === firstElement) {
            event.preventDefault();
            lastElement.focus();
            return;
        }

        if (!event.shiftKey && document.activeElement === lastElement) {
            event.preventDefault();
            firstElement.focus();
        }
    };

    return (
        <div
            aria-labelledby="task-detail-modal-title"
            aria-modal="true"
            className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/30 px-4 py-6 backdrop-blur-[2px]"
            onKeyDown={handleDialogKeyDown}
            ref={dialogRef}
            role="dialog"
        >
            <section className="relative max-h-[calc(100vh-3rem)] w-full max-w-[55rem] overflow-hidden rounded-shell border border-outline-soft bg-surface shadow-shell">
                <button
                    aria-label="Close node detail"
                    className="absolute right-4 top-4 z-10 inline-flex size-10 items-center justify-center rounded-control bg-surface-high text-foreground transition-colors hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                    onClick={onClose}
                    ref={closeButtonRef}
                    title="Close node detail"
                    type="button"
                >
                    <X aria-hidden="true" className="size-5" />
                </button>

                <div className="max-h-[calc(100vh-3rem)] min-w-0 overflow-y-auto">
                    <header className="border-b border-outline-soft px-5 py-4 pr-16">
                        <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                                <p className="font-mono text-label font-medium text-muted">
                                    Node detail
                                </p>
                                <h2
                                    className="mt-2 truncate font-display text-compact font-semibold text-foreground"
                                    id="task-detail-modal-title"
                                >
                                    {context.node === null
                                        ? view.task.title
                                        : titleCaseNodeLabel(context.node.nodeKey)}
                                </h2>
                            </div>
                            <NodeStatusChip context={context} view={view} />
                        </div>
                        <div className="mt-3">
                            <Tabs
                                label="Selected detail views"
                                onChange={onTabChange}
                                tabs={TASK_DETAIL_TABS.map((tabOption) => ({
                                    label: tabOption.label,
                                    panelId: `task-detail-${tabOption.value}`,
                                    value: tabOption.value,
                                }))}
                                value={tab}
                            />
                        </div>
                    </header>
                    <div
                        aria-labelledby={`task-detail-${tab}-tab`}
                        className="px-5 py-4"
                        id={`task-detail-${tab}`}
                        role="tabpanel"
                    >
                        <TaskDetailTabPanel
                            context={context}
                            tab={tab}
                            taskId={taskId}
                            view={view}
                        />
                    </div>
                </div>
            </section>
        </div>
    );
}

function getFocusableElements(root: HTMLElement): readonly HTMLElement[] {
    return Array.from(
        root.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
    ).filter(
        (element) =>
            element.tabIndex >= 0 &&
            !element.hasAttribute("hidden") &&
            element.getAttribute("aria-hidden") !== "true",
    );
}

function TaskDetailTabPanel({
    context,
    tab,
    taskId,
    view,
}: {
    readonly context: NonNullable<TaskDetailController["selectedContext"]>;
    readonly tab: TaskDetailTab;
    readonly taskId: string;
    readonly view: TaskDetailView;
}) {
    switch (tab) {
        case "overview":
            return <OverviewTab context={context} taskId={taskId} view={view} />;
        case "checkpoint":
            return (
                <DetailTab
                    label="Checkpoint"
                    rows={preferRows(context.checkpointRows, [
                        "Kind",
                        "Outcome",
                        "Summary",
                        "Next step",
                    ])}
                />
            );
        case "assignment":
            return (
                <DetailTab
                    label="Assignment"
                    rows={preferRows(context.assignmentRows, [
                        "Assignment key",
                        "Node",
                        "Assignment summary",
                    ])}
                />
            );
        case "boundary":
            return (
                <DetailTab
                    emptyTitle="No accepted boundary"
                    label="Boundary"
                    rows={context.boundaryRows}
                />
            );
        case "artifacts":
            return <ArtifactRefs refs={context.artifactRefs} />;
        case "trace":
            return (
                <CodeBlock title="Trace">
                    {context.traceJson === "{}"
                        ? `No selected task event for ${taskId}.`
                        : context.traceJson}
                </CodeBlock>
            );
    }
}

function OverviewTab({
    context,
    taskId,
    view,
}: {
    readonly context: NonNullable<TaskDetailController["selectedContext"]>;
    readonly taskId: string;
    readonly view: TaskDetailView;
}) {
    const selectedNodeTitle =
        context.node === null ? view.task.title : titleCaseNodeLabel(context.node.nodeKey);

    return (
        <div className="min-w-0 space-y-3">
            <section className="min-w-0 rounded-[16px] border border-outline-soft bg-surface-muted p-4">
                <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                        <p className="font-mono text-label font-medium text-muted">
                            Selected context
                        </p>
                        <h3 className="mt-2 font-display text-lg font-semibold text-foreground">
                            {selectedNodeTitle}
                        </h3>
                    </div>
                    <NodeStatusChip context={context} view={view} />
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                    <DetailProperty label="Task">{view.task.title}</DetailProperty>
                    <DetailProperty label="Selected event">
                        {context.event === null
                            ? "No event selected yet"
                            : displayEventLabel(context.event.eventType)}
                    </DetailProperty>
                    <DetailProperty label="Updated" mono>
                        <TaskDetailTimestamp value={view.task.updatedAt} />
                    </DetailProperty>
                </div>
            </section>

            <div className="grid min-w-0 gap-3">
                <HumanRequestHandoff taskId={taskId} view={view} />
                <CommandRunHandoff taskId={taskId} view={view} />
            </div>
        </div>
    );
}

function DetailTab({
    emptyTitle = "No selected detail",
    label,
    rows,
}: {
    readonly emptyTitle?: string;
    readonly label: string;
    readonly rows: readonly DetailRow[];
}) {
    if (rows.length === 0) {
        return (
            <StatePanel
                summary="No controller-backed details are available."
                title={emptyTitle}
                tone="empty"
            />
        );
    }

    return (
        <section className="rounded-[16px] border border-outline-soft bg-surface-muted p-4">
            <p className="font-mono text-label font-medium text-muted">{label}</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {rows.map((row) => (
                    <DetailProperty key={row.label} label={row.label} mono={shouldUseMono(row)}>
                        {row.value}
                    </DetailProperty>
                ))}
            </div>
        </section>
    );
}

function HumanRequestHandoff({
    taskId,
    view,
}: {
    readonly taskId: string;
    readonly view: TaskDetailView;
}) {
    const request = view.humanRequests.at(0) ?? null;
    if (request === null) {
        return null;
    }

    return (
        <DetailHandoff
            actionLabel="Open Human Requests"
            status={
                <StatusChip
                    className="rounded-full"
                    tone={humanRequestTone(request.status)}
                    withDot
                >
                    {request.status}
                </StatusChip>
            }
            title={request.title}
            to={`/tasks/${encodeURIComponent(taskId)}/human-requests`}
            eyebrow="Human Requests"
        />
    );
}

function CommandRunHandoff({
    taskId,
    view,
}: {
    readonly taskId: string;
    readonly view: TaskDetailView;
}) {
    const run = view.commandRuns.at(0) ?? null;
    if (run === null) {
        return null;
    }

    return (
        <DetailHandoff
            actionLabel="Open Command Runs"
            status={
                <StatusChip className="rounded-full" tone={commandRunTone(run.state)} withDot>
                    {run.state}
                </StatusChip>
            }
            title={run.description ?? run.runId}
            to={`/tasks/${encodeURIComponent(taskId)}/command-runs`}
            eyebrow="Command Runs"
        />
    );
}

function DetailHandoff({
    actionLabel,
    eyebrow,
    status,
    title,
    to,
}: {
    readonly actionLabel: string;
    readonly eyebrow: string;
    readonly status: ReactNode;
    readonly title: string;
    readonly to: string;
}) {
    return (
        <section className="min-w-0 rounded-[16px] border border-outline-soft bg-surface p-4">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="font-mono text-label font-medium text-muted">{eyebrow}</p>
                    <h3 className="mt-2 font-display text-compact font-semibold text-foreground">
                        {title}
                    </h3>
                </div>
                {status}
            </div>
            <div className="mt-3 flex min-w-0 flex-wrap items-center justify-end gap-3">
                <Link
                    className="ml-auto inline-flex h-control shrink-0 items-center justify-center rounded-control border border-outline bg-surface-low px-4 text-utility font-semibold text-foreground transition-colors hover:border-primary/45 hover:text-primary-foreground"
                    to={to}
                >
                    {actionLabel}
                </Link>
            </div>
        </section>
    );
}

function DetailProperty({
    children,
    label,
    mono = false,
}: {
    readonly children: ReactNode;
    readonly label: string;
    readonly mono?: boolean;
}) {
    return (
        <div className="min-w-0">
            <p className="font-mono text-label font-medium text-muted">{label}</p>
            <p
                className={
                    mono
                        ? "mt-1 break-words font-mono text-utility text-foreground"
                        : "mt-1 break-words text-utility text-foreground"
                }
            >
                {children}
            </p>
        </div>
    );
}

function ArtifactRefs({ refs }: { readonly refs: readonly TaskDetailRef[] }) {
    if (refs.length === 0) {
        return (
            <StatePanel
                summary="No controller-backed refs are available for the selected context."
                title="No artifact refs"
                tone="empty"
            />
        );
    }

    return (
        <section className="rounded-[16px] border border-outline-soft bg-surface-muted p-4">
            <p className="font-mono text-label font-medium text-muted">Evidence</p>
            <div className="mt-4 grid gap-3">
                {refs.map((ref) => (
                    <article
                        className="rounded-[16px] border border-outline-soft bg-surface px-4 py-3"
                        key={`${ref.kind}-${ref.label}-${ref.path ?? ""}`}
                    >
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                            <p className="break-all font-mono text-utility text-foreground">
                                {ref.label}
                            </p>
                            <span className="rounded-full bg-surface-muted px-2.5 py-0.5 font-mono text-label text-muted">
                                {ref.kind}
                            </span>
                        </div>
                        {ref.path === null ? null : (
                            <p className="mt-2 break-all text-utility text-muted">{ref.path}</p>
                        )}
                    </article>
                ))}
            </div>
        </section>
    );
}

function NodeStatusChip({
    context,
    view,
}: {
    readonly context: NonNullable<TaskDetailController["selectedContext"]>;
    readonly view: TaskDetailView;
}) {
    const status = context.node === null ? view.task.status : nodeStatusLabel(context.node.status);
    const tone = status === "green" ? "success" : status === "running" ? "active" : "neutral";

    return (
        <StatusChip className="rounded-full" tone={tone} withDot>
            {status}
        </StatusChip>
    );
}

function nodeStatusLabel(status: TaskGraphNode["status"]): string {
    switch (status) {
        case "active":
            return "running";
        case "done":
            return "green";
        case "quiet":
            return "idle";
        case "staged":
            return "staged";
    }
}

function preferRows(rows: readonly DetailRow[], labels: readonly string[]): readonly DetailRow[] {
    const labelSet = new Set(labels);
    const preferred = rows.filter((row) => labelSet.has(row.label));
    return preferred.length > 0 ? preferred : rows;
}

function shouldUseMono(row: DetailRow): boolean {
    const label = row.label.toLowerCase();
    return (
        label.includes("id") ||
        label.includes("key") ||
        label.includes("ref") ||
        label.includes("status") ||
        label.includes("kind") ||
        label.includes("node")
    );
}

function displayEventLabel(eventType: string): string {
    return titleCaseNodeLabel(eventType);
}
