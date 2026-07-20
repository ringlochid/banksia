import { ExternalLink } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { PageFrame, useShellTaskTitle } from "../../components/layout";
import { Button, IdRefText, StatePanel } from "../../components/ui";
import type { components } from "../../api/generated/openapi";
import { classNames } from "../../lib/classNames";
import {
    isAuthError,
    useHumanRequestsController,
    type HumanRequestsController,
} from "./human-request-controller";
import { isRequestEditable, mapHumanRequestQueueItem } from "./human-request-model";
import { TerminalReadback } from "./human-request-terminal-readback";
import { FocusedRequestWorkbench } from "./human-request-workbench";

type HumanRequestRead = components["schemas"]["HumanRequestRead"];
type HumanRequestStatus = components["schemas"]["HumanRequestStatus"];

export function HumanRequestsPage() {
    const { taskId } = useParams();

    return <HumanRequestsTaskPage key={taskId ?? "missing-task"} taskId={taskId ?? null} />;
}

function HumanRequestsTaskPage({ taskId }: { readonly taskId: string | null }) {
    const controller = useHumanRequestsController(taskId);
    const pageTitle = controller.taskTitle ?? controller.taskId ?? "Selected task";
    const hasRequestReads = controller.requestReads.length > 0;
    useShellTaskTitle(controller.taskId, controller.taskTitle);

    return (
        <PageFrame
            actions={
                hasRequestReads ? (
                    <HumanRequestsHeaderActions controller={controller} />
                ) : (
                    <OpenTaskDetailLink taskId={controller.taskId} />
                )
            }
            contentClassName={hasRequestReads ? "!p-0" : undefined}
            eyebrow="Human Requests"
            headerClassName="!gap-4 !px-5 !py-5 sm:!px-6 sm:!pb-[27px] sm:!pt-6"
            title={pageTitle}
        >
            <HumanRequestsState controller={controller} />
        </PageFrame>
    );
}

function HumanRequestsHeaderActions({
    controller,
}: {
    readonly controller: HumanRequestsController;
}) {
    const { openCount, terminalCount } = useMemo(
        () => getRequestCounts(controller.requestReads),
        [controller.requestReads],
    );

    return (
        <>
            <HeaderCountPill>{String(openCount)} pending</HeaderCountPill>
            <HeaderCountPill className="max-sm:!hidden">
                {String(terminalCount)} terminal
            </HeaderCountPill>
        </>
    );
}

function HumanRequestsState({ controller }: { readonly controller: HumanRequestsController }) {
    if (controller.isLoading) {
        return (
            <StatePanel
                summary="Reading task-scoped pending and terminal human requests."
                title="Loading Human Requests"
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
                        ? "Access to Human Requests failed"
                        : "Human Requests could not load"
                }
                tone={isAuthError(controller.error) ? "auth" : "error"}
            />
        );
    }

    if (controller.requestReads.length === 0) {
        return (
            <StatePanel
                action={<OpenTaskDetailLink taskId={controller.taskId} />}
                summary="The controller did not return any human request records for this task."
                title="No human requests"
                tone="empty"
            />
        );
    }

    return (
        <div>
            {controller.taskStatus === "paused" ? (
                <div className="border-b border-outline-soft p-4 sm:px-5">
                    <StatePanel
                        summary={
                            controller.taskWaitingCause === "human_request"
                                ? "The request remains open while the task is paused. A terminal answer or timeout is retained without opening a successor dispatch."
                                : "This request result is retained while the task is paused. Continue remains a separate task action."
                        }
                        title={`Task paused${controller.taskPauseReason === null ? "" : ` · ${controller.taskPauseReason}`}`}
                        tone="stale"
                    />
                </div>
            ) : null}
            <div className="grid min-w-0 gap-0 lg:min-h-[720px] lg:grid-cols-[19rem_minmax(0,1fr)]">
                <HumanRequestQueue controller={controller} />
                <SelectedHumanRequest controller={controller} />
            </div>
        </div>
    );
}

function HumanRequestQueue({ controller }: { readonly controller: HumanRequestsController }) {
    const openReads = controller.requestReads.filter((read) => read.request.status === "open");
    const terminalReads = controller.requestReads.filter((read) => read.request.status !== "open");

    return (
        <aside
            className="hidden min-h-0 min-w-0 flex-col border-b border-outline-soft bg-surface px-4 py-4 sm:px-5 lg:flex lg:border-b-0 lg:border-r"
            aria-label="Human request queue"
        >
            <div className="mb-4 flex min-w-0 items-center justify-between gap-3">
                <h2 className="mt-1 font-display text-compact font-semibold text-foreground">
                    Requests
                </h2>
                <span className="rounded-full border border-outline-soft bg-surface px-2.5 py-1 font-mono text-utility text-muted">
                    {String(openReads.length)} open
                </span>
            </div>
            {openReads.length === 0 ? (
                <StatePanel
                    className="mb-3"
                    summary="Closed requests remain available as terminal readback."
                    title="No pending requests"
                    tone="empty"
                />
            ) : null}
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                <HumanRequestQueueSection controller={controller} reads={openReads} title="Open" />
                <HumanRequestQueueSection
                    controller={controller}
                    reads={terminalReads}
                    title="Closed"
                />
            </div>
        </aside>
    );
}

function HumanRequestQueueSection({
    controller,
    reads,
    title,
}: {
    readonly controller: HumanRequestsController;
    readonly reads: readonly HumanRequestRead[];
    readonly title: string;
}) {
    if (reads.length === 0) {
        return null;
    }

    return (
        <section className="space-y-2">
            <div className="flex items-center justify-between">
                <p className="font-mono text-label font-medium text-muted">{title}</p>
                <span className="font-mono text-utility text-muted">{String(reads.length)}</span>
            </div>
            <ol aria-label={`${title} human requests`} className="space-y-2">
                {reads.map((read) => (
                    <li key={read.request.request_id}>
                        <HumanRequestQueueButton controller={controller} read={read} />
                    </li>
                ))}
            </ol>
        </section>
    );
}

function HumanRequestQueueButton({
    controller,
    read,
}: {
    readonly controller: HumanRequestsController;
    readonly read: HumanRequestRead;
}) {
    const item = mapHumanRequestQueueItem(read);
    const isSelected = controller.selectedRequestId === item.requestId;

    return (
        <button
            aria-current={isSelected ? "true" : undefined}
            className={classNames(
                "w-full min-w-0 rounded-card border bg-surface px-3 py-2.5 text-left transition-colors hover:border-primary/35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
                isSelected
                    ? "border-[rgba(59,130,246,0.32)] bg-surface-low shadow-[inset_3px_0_0_#3b82f6]"
                    : "border-outline-soft shadow-hairline",
            )}
            onClick={() => {
                controller.selectRequest(item.requestId);
            }}
            type="button"
        >
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-3 gap-y-1">
                <RequestKindPill kind={item.kind} size="compact" />
                <span className="min-w-0 break-all font-mono text-label text-muted">
                    {queueStatusLabel(read)}
                </span>
            </div>
            <h2
                className={classNames(
                    "mt-1.5 min-w-0 font-display text-body font-semibold text-foreground",
                    isSelected && "text-primary-foreground",
                )}
            >
                {item.summary}
            </h2>
        </button>
    );
}

function SelectedHumanRequest({ controller }: { readonly controller: HumanRequestsController }) {
    const read = controller.selectedRead;
    const headingRef = useRef<HTMLHeadingElement>(null);
    const previousRequestIdRef = useRef<string | null>(null);

    useEffect(() => {
        const requestId = read?.request.request_id ?? null;
        if (previousRequestIdRef.current !== null && previousRequestIdRef.current !== requestId) {
            headingRef.current?.focus();
        }
        previousRequestIdRef.current = requestId;
    }, [read]);

    if (read === null) {
        return (
            <StatePanel
                summary="Select a request from the task queue."
                title="No selected request"
                tone="empty"
            />
        );
    }

    const editable = isRequestEditable(read);

    return (
        <section className="min-w-0 bg-surface">
            <div className="hidden border-b border-outline-soft pb-4 lg:block">
                <div className="space-y-4 px-5 pb-0 pt-8 sm:px-6 sm:pb-0 sm:pt-8 lg:px-5">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <RequestKindPill kind={read.request.kind} />
                        <RequestStatusPill status={read.request.status} />
                        <span className="rounded-full bg-surface-muted px-2.5 py-1 font-mono text-utility text-foreground">
                            {String(read.request.items.length)} item
                            {read.request.items.length === 1 ? "" : "s"}
                        </span>
                    </div>
                    <div className="flex min-w-0 flex-col gap-3 lg:items-stretch">
                        <div className="min-w-0 max-w-4xl">
                            <h2
                                className="font-display text-display font-semibold text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                                ref={headingRef}
                                tabIndex={-1}
                            >
                                {read.request.summary}
                            </h2>
                        </div>
                        <SelectedRequestActions
                            className="hidden shrink-0 flex-nowrap items-center justify-end gap-2 lg:flex"
                            controller={controller}
                            editable={editable}
                        />
                    </div>
                    <RequestMetadata read={read} />
                </div>
            </div>

            <div className="space-y-6 px-5 py-5 sm:px-6 sm:py-6 lg:space-y-0 lg:px-5 lg:pb-5 lg:pt-4">
                <MobileSelectedRequestSummary controller={controller} read={read} />
                {read.resolution !== null || read.request.status !== "open" ? (
                    <TerminalReadback read={read} />
                ) : (
                    <FocusedRequestWorkbench controller={controller} />
                )}
                <SelectedRequestActions
                    className="flex flex-col gap-3 sm:flex-row lg:hidden"
                    controlClassName="w-full sm:w-auto"
                    controller={controller}
                    editable={editable}
                />
                <MobileRequestQueueSummary controller={controller} />
            </div>
        </section>
    );
}

function MobileSelectedRequestSummary({
    controller,
    read,
}: {
    readonly controller: HumanRequestsController;
    readonly read: HumanRequestRead;
}) {
    const openCount = controller.requestReads.filter(
        (entry) => entry.request.status === "open",
    ).length;
    const itemCount = read.request.items.length;

    return (
        <section className="space-y-2 rounded-card border border-outline-soft bg-surface-muted p-3 lg:hidden">
            <div className="rounded-card border border-outline-soft bg-surface-low px-3 py-2.5">
                <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                            <RequestKindPill kind={read.request.kind} />
                            <span className="rounded-full bg-surface-muted px-2.5 py-1 font-mono text-utility text-foreground">
                                {String(controller.selectedItemIndex + 1)}/{String(itemCount)}
                            </span>
                        </div>
                        <h2 className="mt-1.5 font-display text-compact font-semibold text-foreground">
                            {read.request.summary}
                        </h2>
                    </div>
                    <div className="shrink-0 text-left sm:text-right">
                        <p className="font-mono text-utility text-muted">
                            {String(openCount)} open
                        </p>
                        <p className="mt-1 whitespace-nowrap font-mono text-utility text-muted">
                            {read.request.timeout?.due_at === undefined ||
                            read.request.timeout.due_at === null
                                ? "No due time"
                                : formatAestTime(read.request.timeout.due_at)}
                        </p>
                    </div>
                </div>
            </div>
        </section>
    );
}

function SelectedRequestActions({
    className,
    controlClassName,
    controller,
    editable,
}: {
    readonly className?: string;
    readonly controlClassName?: string;
    readonly controller: HumanRequestsController;
    readonly editable: boolean;
}) {
    return (
        <div className={className}>
            <OpenTaskDetailLink className={controlClassName} taskId={controller.taskId} />
            <Button
                className={classNames(
                    "!border-[#2563eb] !bg-[#2563eb] !shadow-none hover:!bg-[#1d4ed8] lg:min-w-[86px]",
                    controlClassName,
                )}
                disabled={!editable || controller.isResolving}
                onClick={controller.resolveSelectedRequest}
                variant="primary"
            >
                {controller.isResolving ? "Resolving" : "Resolve"}
            </Button>
        </div>
    );
}

function MobileRequestQueueSummary({
    controller,
}: {
    readonly controller: HumanRequestsController;
}) {
    const [isOpen, setIsOpen] = useState(false);
    const otherReads = controller.requestReads.filter(
        (read) => read.request.request_id !== controller.selectedRequestId,
    );
    const otherOpenCount = otherReads.filter((read) => read.request.status === "open").length;
    const otherTerminalCount = otherReads.length - otherOpenCount;

    return (
        <details
            className="rounded-card border border-outline-soft bg-surface-low px-3 py-2 shadow-hairline lg:hidden"
            onToggle={(event) => {
                setIsOpen(event.currentTarget.open);
            }}
        >
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-display text-compact font-semibold text-foreground marker:hidden">
                <span>Other requests</span>
                <span className="font-mono text-label font-medium text-muted">
                    {String(otherOpenCount)} open / {String(otherTerminalCount)} closed
                </span>
            </summary>
            {!isOpen ? null : otherReads.length === 0 ? (
                <p className="mt-3 text-compact text-muted">No other request records.</p>
            ) : (
                <ol aria-label="Other human requests" className="mt-3 space-y-2">
                    {otherReads.map((read) => (
                        <li key={read.request.request_id}>
                            <HumanRequestQueueButton controller={controller} read={read} />
                        </li>
                    ))}
                </ol>
            )}
        </details>
    );
}

function RequestMetadata({ read }: { readonly read: HumanRequestRead }) {
    return (
        <dl className="grid min-w-0 overflow-hidden rounded-card border border-outline-soft bg-surface-low md:grid-cols-2 xl:grid-cols-5">
            <RequestMetadataItem label="Source dispatch">
                <IdRefText value={read.request.source_dispatch_id} />
            </RequestMetadataItem>
            <RequestMetadataItem label="Assignment">
                <IdRefText value={read.request.assignment_id} />
            </RequestMetadataItem>
            <RequestMetadataItem label="Attempt">
                <IdRefText value={read.request.attempt_id} />
            </RequestMetadataItem>
            <RequestMetadataItem label="Opened">
                <time dateTime={new Date(read.request.opened_at).toISOString()}>
                    {formatAestTime(read.request.opened_at)}
                </time>
            </RequestMetadataItem>
            <RequestMetadataItem label="Due">
                {read.request.timeout?.due_at === undefined ||
                read.request.timeout.due_at === null ? (
                    "No due time"
                ) : (
                    <time dateTime={new Date(read.request.timeout.due_at).toISOString()}>
                        {formatAestTime(read.request.timeout.due_at)}
                    </time>
                )}
            </RequestMetadataItem>
        </dl>
    );
}

function RequestMetadataItem({
    children,
    label,
}: {
    readonly children: ReactNode;
    readonly label: string;
}) {
    return (
        <div className="min-w-0 border-b border-outline-soft px-4 py-3 last:border-b-0 md:border-b-0 md:border-r md:last:border-r-0">
            <dt className="font-mono text-label font-medium text-muted">{label}</dt>
            <dd className="mt-2 min-w-0 text-compact text-foreground">{children}</dd>
        </div>
    );
}

function OpenTaskDetailLink({
    className,
    taskId,
}: {
    readonly className?: string;
    readonly taskId: string | null;
}) {
    return (
        <Link
            className={classNames(
                "inline-flex h-control min-w-[167px] items-center justify-center gap-2 rounded-control border border-outline bg-surface-low px-4 text-utility font-semibold text-foreground transition-colors hover:border-primary/45 hover:text-primary-foreground",
                className,
                taskId === null && "pointer-events-none opacity-55",
            )}
            to={taskId === null ? "/tasks" : `/tasks/${encodeURIComponent(taskId)}`}
        >
            <span>Open task detail</span>
            <ExternalLink aria-hidden="true" className="size-4 shrink-0" />
        </Link>
    );
}

function HeaderCountPill({
    children,
    className,
}: {
    readonly children: ReactNode;
    readonly className?: string;
}) {
    return (
        <span
            className={classNames(
                "inline-flex h-[30px] items-center rounded-full bg-surface-muted px-3 font-mono text-utility text-foreground",
                className,
            )}
        >
            {children}
        </span>
    );
}

function RequestKindPill({
    kind,
    size = "default",
}: {
    readonly kind: components["schemas"]["HumanRequestKind"];
    readonly size?: "compact" | "default";
}) {
    return (
        <span
            className={classNames(
                "rounded-full font-mono",
                size === "compact" ? "px-2 py-0.5 text-label" : "px-2.5 py-1 text-utility",
                kindClassName(kind),
            )}
        >
            {kind}
        </span>
    );
}

function RequestStatusPill({ status }: { readonly status: HumanRequestStatus }) {
    return (
        <span
            className={classNames(
                "rounded-full px-2.5 py-1 font-mono text-utility",
                statusClassName(status),
            )}
        >
            {status === "resolved" ? "answered" : status}
        </span>
    );
}

function kindClassName(kind: components["schemas"]["HumanRequestKind"]): string {
    switch (kind) {
        case "direction":
            return "bg-primary-soft text-primary-foreground";
        case "approval":
            return "bg-amber-50 text-amber-700";
        case "input":
            return "bg-surface-muted text-foreground";
        case "review":
            return "bg-emerald-50 text-emerald-700";
    }
}

function getRequestCounts(reads: readonly HumanRequestRead[]): {
    readonly openCount: number;
    readonly terminalCount: number;
} {
    const openCount = reads.filter((read) => read.request.status === "open").length;
    return {
        openCount,
        terminalCount: reads.length - openCount,
    };
}

function queueStatusLabel(read: HumanRequestRead): string {
    if (read.request.status === "open") {
        if (read.request.timeout?.due_at === undefined || read.request.timeout.due_at === null) {
            return "No due time";
        }

        return `Due ${formatAestTime(read.request.timeout.due_at)}`;
    }

    if (read.resolution?.resolved_at !== undefined) {
        return formatAestTime(read.resolution.resolved_at);
    }

    return read.request.status;
}

function formatAestTime(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) {
        return value;
    }

    return new Intl.DateTimeFormat("en-AU", {
        hour: "numeric",
        minute: "2-digit",
        timeZone: "Australia/Sydney",
        timeZoneName: "short",
    }).format(date);
}

function statusClassName(status: HumanRequestStatus): string {
    switch (status) {
        case "open":
            return "bg-surface-muted text-foreground";
        case "resolved":
            return "bg-emerald-50 text-emerald-700";
        case "cancelled":
        case "timed_out":
            return "bg-red-50 text-red-700";
    }
}
