import type { ReactNode } from "react";

import { ExternalLink, FileText, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { PageFrame, useShellTaskTitle } from "../../components/layout";
import {
    Button,
    CodeBlock,
    IdRefText,
    StatePanel,
    StatusChip,
    TimestampText,
} from "../../components/ui";
import { classNames } from "../../lib/classNames";
import {
    isAuthError,
    isStaleActionError,
    useCommandRunsController,
    type CommandRunLogState,
    type CommandRunsController,
} from "./command-run-controller";
import {
    isTerminalCommandRunState,
    type CommandRunState,
    type CommandRunDetailView,
    type CommandRunRowView,
} from "./command-run-model";

export function CommandRunsPage() {
    const { taskId } = useParams();

    return <CommandRunsTaskPage key={taskId ?? "missing-task"} taskId={taskId ?? null} />;
}

function CommandRunsTaskPage({ taskId }: { readonly taskId: string | null }) {
    const controller = useCommandRunsController(taskId);
    const pageTitle = controller.taskTitle ?? controller.taskId ?? "Selected task";
    useShellTaskTitle(controller.taskId, controller.taskTitle);

    return (
        <PageFrame
            actions={<OpenTaskDetailLink taskId={controller.taskId} />}
            eyebrow="Command Runs"
            title={pageTitle}
        >
            <CommandRunsState controller={controller} />
        </PageFrame>
    );
}

function CommandRunsState({ controller }: { readonly controller: CommandRunsController }) {
    if (controller.isLoading) {
        return (
            <StatePanel
                summary="Reading controller-managed command runs for this task."
                title="Loading Command Runs"
                tone="loading"
            />
        );
    }

    if (controller.error !== null) {
        return (
            <StatePanel
                action={<Button onClick={controller.refresh}>Retry</Button>}
                summary={controller.error.summary}
                title={
                    isAuthError(controller.error)
                        ? "Access to Command Runs failed"
                        : "Command Runs could not load"
                }
                tone={isAuthError(controller.error) ? "auth" : "error"}
            />
        );
    }

    if (controller.rows.length === 0) {
        return (
            <StatePanel
                summary="The controller did not return command-run records for this task."
                title="No command runs"
                tone="empty"
            />
        );
    }

    return (
        <div className="space-y-4">
            {controller.taskStatus === "paused" ? (
                <StatePanel
                    summary={
                        controller.taskWaitingCause === "command_run"
                            ? "The command run remains controller-owned while the task is paused. Terminal or abandoned readback is retained without opening a successor dispatch."
                            : "Command-run readback is retained while the task is paused. Continue remains a separate task action."
                    }
                    title={`Task paused${controller.taskPauseReason === null ? "" : ` · ${controller.taskPauseReason}`}`}
                    tone="stale"
                />
            ) : null}
            <ol aria-label="Command run rows" className="space-y-3">
                {controller.rows.map((row) => (
                    <li key={row.runId}>
                        <CommandRunRow controller={controller} row={row} />
                    </li>
                ))}
            </ol>
            <CommandRunsFooter controller={controller} />
        </div>
    );
}

function CommandRunRow({
    controller,
    row,
}: {
    readonly controller: CommandRunsController;
    readonly row: CommandRunRowView;
}) {
    const isExpanded = controller.expandedRunId === row.runId;
    const cancelError = controller.cancelErrorsByRunId[row.runId] ?? null;

    return (
        <article
            className={classNames(
                "min-w-0 overflow-hidden rounded-card border bg-surface-low transition-colors focus-within:border-primary/45",
                isExpanded
                    ? "border-primary/40 shadow-[inset_3px_0_0_var(--ac-primary)]"
                    : "border-outline-soft",
            )}
        >
            <div className="flex min-w-0 flex-col gap-3 p-4 sm:px-5 sm:py-4 lg:flex-row lg:items-start lg:justify-between">
                <button
                    aria-expanded={isExpanded}
                    className="min-w-0 flex-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                    onClick={() => {
                        controller.toggleExpandedRun(row.runId);
                    }}
                    type="button"
                >
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span
                            aria-hidden="true"
                            className={classNames(
                                "size-2.5 shrink-0 rounded-full",
                                commandRunStateDotClass(row.state),
                            )}
                        />
                        <h2 className="min-w-0 break-words font-display text-compact font-semibold text-foreground">
                            {row.description ?? row.command}
                        </h2>
                    </div>
                    {row.summary === null ? null : (
                        <p className="mt-2 max-w-4xl break-words text-compact text-muted line-clamp-2">
                            {row.summary}
                        </p>
                    )}
                </button>
                <div className="flex min-w-0 flex-wrap items-center gap-2 lg:justify-end">
                    <StatusChip tone={row.stateTone}>{row.stateLabel}</StatusChip>
                    {row.canCancel ? (
                        <Button
                            disabled={controller.isCancellingRunId !== null}
                            icon={<X />}
                            onClick={() => {
                                controller.cancelRun(row.runId);
                            }}
                            variant="danger"
                        >
                            {controller.isCancellingRunId === row.runId ? "Cancelling" : "Cancel"}
                        </Button>
                    ) : null}
                </div>
            </div>
            {cancelError === null ? null : (
                <CommandRunActionError error={cancelError} onRefresh={controller.refresh} />
            )}
            {isExpanded ? <CommandRunExpandedDetail controller={controller} row={row} /> : null}
        </article>
    );
}

function CommandRunExpandedDetail({
    controller,
    row,
}: {
    readonly controller: CommandRunsController;
    readonly row: CommandRunRowView;
}) {
    const detail = controller.detailViewsByRunId[row.runId] ?? null;
    const detailError = controller.detailErrorsByRunId[row.runId] ?? null;
    const isLoading = controller.isDetailLoadingRunId === row.runId && detail === null;

    if (isLoading) {
        return (
            <div className="border-t border-outline-soft p-4">
                <StatePanel
                    summary="Reading the full controller command-run record."
                    title="Loading run detail"
                    tone="loading"
                />
            </div>
        );
    }

    if (detailError !== null && detail === null) {
        return (
            <div className="border-t border-outline-soft p-4">
                <StatePanel
                    action={
                        <Button onClick={() => controller.retryDetail(row.runId)}>Retry</Button>
                    }
                    summary={detailError.summary}
                    title="Run detail could not load"
                    tone="error"
                />
            </div>
        );
    }

    if (detail === null) {
        return null;
    }

    return (
        <div className="space-y-4 border-t border-outline-soft bg-surface px-4 pb-4 pt-4 sm:px-5 sm:pb-5">
            <CommandRunCommandSection detail={detail} />
            <div className="grid min-w-0 gap-4 lg:grid-cols-2 xl:grid-cols-3">
                <CommandRunResultSection detail={detail} />
                <CommandRunTimingSection detail={detail} />
                <CommandRunProvenanceSection detail={detail} />
            </div>
            <CommandRunLogSection
                detail={detail}
                logState={controller.logStatesByRunId[detail.runId] ?? null}
                onToggleLogs={() => {
                    controller.toggleLogs(detail.runId);
                }}
            />
        </div>
    );
}

function CommandRunCommandSection({ detail }: { readonly detail: CommandRunDetailView }) {
    return (
        <section className="min-w-0 rounded-card border border-outline-soft bg-surface-low px-4 py-3">
            <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(12rem,18rem)]">
                <div className="min-w-0">
                    <p className="font-mono text-label font-medium uppercase text-muted">Command</p>
                    <p className="mt-2 break-words font-mono text-utility text-foreground">
                        {detail.command}
                    </p>
                    <p className="mt-3 break-words text-compact text-muted">{detail.description}</p>
                </div>
                <div className="min-w-0">
                    <p className="font-mono text-label font-medium uppercase text-muted">Workdir</p>
                    <IdRefText
                        className="mt-2 block rounded-control border border-outline bg-surface px-3 py-1.5"
                        value={detail.workdir ?? "Not reported"}
                    />
                </div>
            </div>
            {detail.expectedOutputs.length === 0 ? null : (
                <div className="mt-4 border-t border-outline-soft pt-3">
                    <p className="font-mono text-label font-medium uppercase text-muted">
                        Expected outputs
                    </p>
                    <ul className="mt-2 space-y-2">
                        {detail.expectedOutputs.map((output) => (
                            <li className="min-w-0 text-compact text-muted" key={output.path}>
                                <IdRefText value={output.path} /> · {output.description}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </section>
    );
}

function CommandRunResultSection({ detail }: { readonly detail: CommandRunDetailView }) {
    const terminalResult = detail.terminalResult;

    if (!isTerminalCommandRunState(detail.state) || terminalResult === null) {
        return null;
    }

    return (
        <CommandRunDetailPanel
            items={[
                {
                    label: "Summary",
                    value:
                        detail.state === "abandoned"
                            ? `${terminalResult.summary} AutoClaw lost exact process ownership; this does not prove the operating-system process exited.`
                            : terminalResult.summary,
                },
                { label: "Terminal state", value: terminalResult.state },
                ...(detail.failureCode === null
                    ? []
                    : [{ label: "Failure code", value: detail.failureCode }]),
                ...(terminalResult.exit_code === null || terminalResult.exit_code === undefined
                    ? []
                    : [
                          {
                              label: "Exit code",
                              value: <span className="font-mono">{terminalResult.exit_code}</span>,
                          },
                      ]),
            ]}
            label="Result"
        />
    );
}

function CommandRunTimingSection({ detail }: { readonly detail: CommandRunDetailView }) {
    return (
        <CommandRunDetailPanel
            items={[
                { label: "Created", value: <TimestampText value={detail.createdAt} /> },
                ...(detail.startedAt === null
                    ? []
                    : [{ label: "Started", value: <TimestampText value={detail.startedAt} /> }]),
                ...(detail.dueAt === null
                    ? []
                    : [{ label: "Due", value: <TimestampText value={detail.dueAt} /> }]),
                ...(detail.endedAt === null
                    ? []
                    : [{ label: "Ended", value: <TimestampText value={detail.endedAt} /> }]),
                ...(detail.timeoutSeconds === null
                    ? []
                    : [
                          {
                              label: "Timeout",
                              value: `${String(detail.timeoutSeconds)} seconds`,
                          },
                      ]),
                ...(detail.cancellationRequestedAt === null
                    ? []
                    : [
                          {
                              label: "Cancel requested",
                              value: <TimestampText value={detail.cancellationRequestedAt} />,
                          },
                      ]),
            ]}
            label="Timing"
        />
    );
}

function CommandRunProvenanceSection({ detail }: { readonly detail: CommandRunDetailView }) {
    return (
        <CommandRunDetailPanel
            items={[
                { label: "Run id", value: <IdRefText value={detail.runId} /> },
                { label: "Source dispatch", value: <IdRefText value={detail.sourceDispatchId} /> },
                { label: "Assignment", value: <IdRefText value={detail.assignmentId} /> },
                { label: "Attempt", value: <IdRefText value={detail.attemptId} /> },
                { label: "Flow", value: <IdRefText value={detail.flowId} /> },
                { label: "Ownership revision", value: String(detail.ownershipRevision) },
                ...(detail.successorDispatchId === null
                    ? []
                    : [
                          {
                              label: "Successor dispatch",
                              value: <IdRefText value={detail.successorDispatchId} />,
                          },
                      ]),
                ...(detail.terminalEventSource === null
                    ? []
                    : [
                          {
                              label: "Terminal source",
                              value: detail.terminalEventSource,
                          },
                      ]),
                ...(detail.terminalActorRef === null
                    ? []
                    : [
                          {
                              label: "Terminal actor",
                              value: <IdRefText value={detail.terminalActorRef} />,
                          },
                      ]),
                ...(detail.cancellationRequestedByActorRef === null
                    ? []
                    : [
                          {
                              label: "Cancel actor",
                              value: <IdRefText value={detail.cancellationRequestedByActorRef} />,
                          },
                      ]),
            ]}
            label="Provenance"
        />
    );
}

function CommandRunDetailPanel({
    items,
    label,
}: {
    readonly items: readonly {
        readonly label: string;
        readonly value: ReactNode;
    }[];
    readonly label: string;
}) {
    if (items.length === 0) {
        return null;
    }

    return (
        <section className="min-w-0 rounded-card border border-outline-soft bg-surface px-4 py-3">
            <p className="font-mono text-label font-medium uppercase text-muted">{label}</p>
            <dl className="mt-3 grid min-w-0 grid-cols-1 gap-3">
                {items.map((item) => (
                    <div className="min-w-0" key={item.label}>
                        <dt className="font-mono text-label font-medium uppercase text-muted">
                            {item.label}
                        </dt>
                        <dd className="mt-1 min-w-0 break-words text-utility text-foreground">
                            {item.value}
                        </dd>
                    </div>
                ))}
            </dl>
        </section>
    );
}

function CommandRunLogSection({
    detail,
    logState,
    onToggleLogs,
}: {
    readonly detail: CommandRunDetailView;
    readonly logState: CommandRunLogState | null;
    readonly onToggleLogs: () => void;
}) {
    const logRef = detail.preferredLogRef;

    return (
        <section className="min-w-0 rounded-card border border-outline-soft bg-surface px-4 py-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                    <p className="font-mono text-label font-medium uppercase text-muted">
                        Log access
                    </p>
                    {detail.stdoutLogRef === null && detail.stderrLogRef === null ? (
                        <p className="mt-1 text-compact text-muted">
                            This run does not expose a log ref.
                        </p>
                    ) : (
                        <dl className="mt-2 grid gap-2">
                            {detail.stdoutLogRef === null ? null : (
                                <div>
                                    <dt className="font-mono text-label text-muted">Stdout</dt>
                                    <dd>
                                        <IdRefText value={detail.stdoutLogRef} />
                                    </dd>
                                </div>
                            )}
                            {detail.stderrLogRef === null ? null : (
                                <div>
                                    <dt className="font-mono text-label text-muted">Stderr</dt>
                                    <dd>
                                        <IdRefText value={detail.stderrLogRef} />
                                    </dd>
                                </div>
                            )}
                        </dl>
                    )}
                </div>
                {logRef === null ? null : (
                    <Button icon={<FileText />} onClick={onToggleLogs}>
                        {logState?.isVisible === true ? "Hide logs" : "View logs"}
                    </Button>
                )}
            </div>
            {logState?.error === undefined || logState.error === null ? null : (
                <div className="mt-4">
                    <StatePanel
                        summary={logState.error.summary}
                        title="Logs could not load"
                        tone={logState.error.status === 404 ? "stale" : "error"}
                    />
                </div>
            )}
            {logState?.isVisible === true && logState.isLoading ? (
                <div className="mt-4">
                    <StatePanel
                        summary="Reading persisted command-run logs."
                        title="Loading logs"
                        tone="loading"
                    />
                </div>
            ) : null}
            {logState?.isVisible === true && logState.content !== null ? (
                <div className="mt-4">
                    <CodeBlock className="bg-[#151923] text-[#e5e7eb]" title="Logs">
                        {logState.content}
                    </CodeBlock>
                </div>
            ) : null}
        </section>
    );
}

function CommandRunActionError({
    error,
    onRefresh,
}: {
    readonly error: {
        readonly code: string;
        readonly suggestedNextStep: string | null;
        readonly summary: string;
    };
    readonly onRefresh: () => void;
}) {
    const isStale = isStaleActionError(error.code);
    return (
        <div className="border-t border-outline-soft px-4 pb-4">
            <StatePanel
                action={isStale ? <Button onClick={onRefresh}>Reread current truth</Button> : null}
                summary={
                    <span>
                        {error.summary}
                        {error.suggestedNextStep === null ? null : (
                            <span className="mt-1 block">{error.suggestedNextStep}</span>
                        )}
                    </span>
                }
                title={isStale ? "Cancel state changed" : "Cancel failed"}
                tone={isStale ? "stale" : "error"}
            />
        </div>
    );
}

function CommandRunsFooter({ controller }: { readonly controller: CommandRunsController }) {
    if (controller.nextCursor === null) {
        return null;
    }

    return (
        <footer className="flex flex-col gap-3 border-t border-outline-soft pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-compact text-muted">More command runs are available.</p>
            <Button
                disabled={
                    controller.isLoading || controller.isLoadingMore || controller.isRefreshing
                }
                onClick={controller.loadMore}
            >
                {controller.isLoadingMore ? "Loading" : "Load more"}
            </Button>
        </footer>
    );
}

function OpenTaskDetailLink({ taskId }: { readonly taskId: string | null }) {
    const to = taskId === null ? "/tasks" : `/tasks/${encodeURIComponent(taskId)}`;

    return (
        <Link
            className="inline-flex h-control items-center justify-center gap-2 rounded-control border border-outline bg-surface-low px-3 text-utility font-semibold text-foreground transition-colors hover:border-primary/45 hover:text-primary-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            to={to}
        >
            <ExternalLink aria-hidden="true" className="size-4 shrink-0" />
            <span>Open task detail</span>
        </Link>
    );
}

function commandRunStateDotClass(state: CommandRunState): string {
    switch (state) {
        case "running":
            return "bg-primary";
        case "succeeded":
            return "bg-success";
        case "failed":
        case "abandoned":
            return "bg-danger";
        case "cancellation_requested":
        case "timed_out":
            return "bg-warning";
        case "cancelled":
        case "pending_start":
            return "bg-outline";
    }
}
