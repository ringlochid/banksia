import { type KeyboardEvent, type ReactNode, useEffect, useRef } from "react";

import { X } from "lucide-react";
import { Link } from "react-router-dom";

import { taskOutcome } from "../../api/task-outcome";
import {
    CodeBlock,
    Disclosure,
    StatePanel,
    StatusChip,
    Tabs,
    TimestampText,
    type StatusTone,
} from "../../components/ui";
import type { TaskDetailController } from "./task-detail-controller";
import { titleCaseNodeLabel } from "./task-detail-format";
import {
    TASK_DETAIL_TABS,
    checkpointOutcomeTone,
    commandRunTone,
    humanRequestTone,
    type DetailRow,
    type TaskDetailRef,
    type TaskDetailTab,
    type TaskDetailView,
    type TaskGraphNode,
} from "./task-detail-model";

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
                        {tab === "summary" ? (
                            <SummaryTab context={context} taskId={taskId} view={view} />
                        ) : (
                            <EvidenceTab refs={context.evidenceRefs} />
                        )}
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

function SummaryTab({
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
                    <DetailProperty label="Milestone">
                        {context.event === null ? "No event selected yet" : context.event.label}
                    </DetailProperty>
                    <DetailProperty label="Time" mono>
                        <TimestampText
                            value={
                                context.event === null
                                    ? view.task.updatedAt
                                    : context.event.occurredAt
                            }
                        />
                    </DetailProperty>
                </div>
            </section>

            {context.checkpointSummary === null && context.checkpointOutcome === null ? null : (
                <section className="min-w-0 rounded-[16px] border border-outline-soft bg-surface p-4">
                    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                        <p className="font-mono text-label font-medium text-muted">Checkpoint</p>
                        {context.checkpointOutcome === null ? null : (
                            <StatusChip
                                className="rounded-full"
                                tone={checkpointOutcomeTone(context.checkpointOutcome)}
                                withDot
                            >
                                {context.checkpointOutcome}
                            </StatusChip>
                        )}
                    </div>
                    {context.checkpointSummary === null ? null : (
                        <p className="mt-2 text-compact text-foreground">
                            {context.checkpointSummary}
                        </p>
                    )}
                </section>
            )}

            <div className="grid min-w-0 gap-3">
                <HumanRequestHandoff taskId={taskId} view={view} />
                <CommandRunHandoff taskId={taskId} view={view} />
            </div>

            <Disclosure title="Technical details">
                <div className="min-w-0 space-y-3">
                    <TechnicalRows label="Assignment" rows={context.assignmentRows} />
                    <TechnicalRows label="Boundary" rows={context.boundaryRows} />
                    <TechnicalRows label="Checkpoint" rows={context.checkpointRows} />
                    <TechnicalRefs refs={context.technicalRefs} />
                    <CodeBlock title="Trace">
                        {context.traceJson === "{}"
                            ? `No selected task event for ${taskId}.`
                            : context.traceJson}
                    </CodeBlock>
                </div>
            </Disclosure>
        </div>
    );
}

function TechnicalRows({
    label,
    rows,
}: {
    readonly label: string;
    readonly rows: readonly DetailRow[];
}) {
    if (rows.length === 0) {
        return null;
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

function EvidenceTab({ refs }: { readonly refs: readonly TaskDetailRef[] }) {
    if (refs.length === 0) {
        return (
            <StatePanel
                summary="No produced artifacts are available for the selected context. Reference plumbing lives under Technical details on the Summary tab."
                title="No evidence yet"
                tone="empty"
            />
        );
    }

    return (
        <section className="rounded-[16px] border border-outline-soft bg-surface-muted p-4">
            <p className="font-mono text-label font-medium text-muted">Evidence</p>
            <div className="mt-4 grid gap-3">
                {refs.map((ref) => (
                    <RefCard key={`${ref.kind}-${ref.label}-${ref.path ?? ""}`} refItem={ref} />
                ))}
            </div>
        </section>
    );
}

function TechnicalRefs({ refs }: { readonly refs: readonly TaskDetailRef[] }) {
    if (refs.length === 0) {
        return null;
    }

    return (
        <section className="rounded-[16px] border border-outline-soft bg-surface-muted p-4">
            <p className="font-mono text-label font-medium text-muted">References</p>
            <div className="mt-4 grid gap-3">
                {refs.map((ref) => (
                    <RefCard key={`${ref.kind}-${ref.label}-${ref.path ?? ""}`} refItem={ref} />
                ))}
            </div>
        </section>
    );
}

function RefCard({ refItem }: { readonly refItem: TaskDetailRef }) {
    return (
        <article className="rounded-[16px] border border-outline-soft bg-surface px-4 py-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <p className="break-all font-mono text-utility text-foreground">{refItem.label}</p>
                <span className="rounded-full bg-surface-muted px-2.5 py-0.5 font-mono text-label text-muted">
                    {refItem.kind}
                </span>
            </div>
            {refItem.path === null ? null : (
                <p className="mt-2 break-all text-utility text-muted">{refItem.path}</p>
            )}
        </article>
    );
}

function NodeStatusChip({
    context,
    view,
}: {
    readonly context: NonNullable<TaskDetailController["selectedContext"]>;
    readonly view: TaskDetailView;
}) {
    if (context.node === null) {
        const outcome = taskOutcome(view.task.status, view.task.terminalOutcome);
        return (
            <StatusChip className="rounded-full" tone={outcome.tone} withDot>
                {outcome.label}
            </StatusChip>
        );
    }

    const presentation = nodeStatusPresentation(context.node.status);
    return (
        <StatusChip className="rounded-full" tone={presentation.tone} withDot>
            {presentation.label}
        </StatusChip>
    );
}

function nodeStatusPresentation(status: TaskGraphNode["status"]): {
    readonly label: string;
    readonly tone: StatusTone;
} {
    switch (status) {
        case "active":
            return { label: "running", tone: "active" };
        case "blocked":
            return { label: "blocked", tone: "danger" };
        case "done":
            return { label: "completed", tone: "success" };
        case "quiet":
            return { label: "idle", tone: "neutral" };
        case "staged":
            return { label: "staged", tone: "neutral" };
    }
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
