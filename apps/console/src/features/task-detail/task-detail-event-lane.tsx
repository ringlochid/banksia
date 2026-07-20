import { StatePanel } from "../../components/ui";
import { classNames } from "../../lib/classNames";
import { titleCaseNodeLabel } from "./task-detail-format";
import type { TaskEventRow } from "./task-detail-model";
import { TaskDetailTimestamp } from "./task-detail-summary";

export function TaskEventLane({
    events,
    onOpenDetail,
    onSelectEvent,
    selectedEventId,
}: {
    readonly events: readonly TaskEventRow[];
    readonly onOpenDetail: () => void;
    readonly onSelectEvent: (eventId: string) => void;
    readonly selectedEventId: string | null;
}) {
    return (
        <section className="min-w-0 overflow-hidden rounded-[22px] border border-outline-soft bg-surface-low shadow-panel">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-outline-soft px-4 py-3 sm:px-5">
                <p className="font-mono text-label font-medium text-muted">Events</p>
            </header>
            {events.length === 0 ? (
                <div className="px-4 py-4">
                    <StatePanel
                        summary="No persisted task-event history was returned for the current snapshot anchor."
                        title="No event history"
                        tone="empty"
                    />
                </div>
            ) : (
                <ol
                    aria-label="Task events"
                    className="grid max-h-[560px] min-w-0 gap-2.5 overflow-x-hidden overflow-y-auto px-4 py-4 sm:max-h-[630px] xl:max-h-[689px]"
                >
                    {events.map((event) => (
                        <TaskEventItem
                            event={event}
                            isSelected={event.eventId === selectedEventId}
                            key={event.eventId}
                            onOpenDetail={onOpenDetail}
                            onSelectEvent={onSelectEvent}
                        />
                    ))}
                </ol>
            )}
        </section>
    );
}

function TaskEventItem({
    event,
    isSelected,
    onOpenDetail,
    onSelectEvent,
}: {
    readonly event: TaskEventRow;
    readonly isSelected: boolean;
    readonly onOpenDetail: () => void;
    readonly onSelectEvent: (eventId: string) => void;
}) {
    const detailRows = isSelected ? eventInlineRows(event) : [];

    return (
        <li>
            <button
                aria-pressed={isSelected}
                className={classNames(
                    "min-h-[74px] w-full rounded-[16px] border px-4 py-3.5 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
                    isSelected
                        ? "border-primary/20 bg-active"
                        : "border-outline-soft bg-surface-low hover:border-primary/25",
                )}
                onClick={() => {
                    onSelectEvent(event.eventId);
                }}
                onDoubleClick={onOpenDetail}
                type="button"
            >
                <div className="flex min-w-0 items-start gap-3">
                    <span
                        aria-hidden="true"
                        className={classNames(
                            "mt-1 size-3.5 shrink-0 rounded-full border-4 border-surface",
                            eventDotClass(event.eventType),
                        )}
                    />
                    <div className="min-w-0 flex-1 space-y-2">
                        <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                                <p
                                    className={classNames(
                                        "break-words font-display text-utility font-semibold",
                                        isSelected ? "text-primary-foreground" : "text-foreground",
                                    )}
                                >
                                    {eventLabel(event.eventType)}
                                </p>
                                {event.nodeKey === null ? null : (
                                    <p className="break-all font-mono text-utility text-muted">
                                        {titleCaseNodeLabel(event.nodeKey)}
                                    </p>
                                )}
                            </div>
                            <TaskDetailTimestamp
                                className="shrink-0 font-mono text-utility text-muted"
                                value={event.occurredAt}
                                variant="time"
                            />
                        </div>
                        {detailRows.length === 0 ? null : (
                            <div className="grid gap-3 rounded-[16px] border border-outline-soft bg-surface px-4 py-3">
                                {detailRows.map((row) => (
                                    <div className="min-w-0" key={row.label}>
                                        <p className="font-mono text-label font-medium text-muted">
                                            {row.label}
                                        </p>
                                        <p className="mt-1 break-all font-mono text-utility text-foreground">
                                            {row.value}
                                        </p>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </button>
        </li>
    );
}

function eventDotClass(eventType: TaskEventRow["eventType"]): string {
    if (eventType.startsWith("command_run")) {
        return "bg-primary";
    }
    if (eventType.startsWith("human_request")) {
        return "bg-warning";
    }
    if (eventType === "checkpoint_recorded" || eventType === "boundary_accepted") {
        return "bg-success";
    }
    if (eventType.startsWith("child_assignment") || eventType === "structural_revision_adopted") {
        return "bg-[#8b5cf6]";
    }
    if (eventType === "task_cancelled") {
        return "bg-danger";
    }
    if (eventType === "task_started") {
        return "bg-outline";
    }
    return "bg-foreground";
}

function eventLabel(eventType: TaskEventRow["eventType"]): string {
    const labelByType: Partial<Record<TaskEventRow["eventType"], string>> = {
        boundary_accepted: "Boundary accepted",
        checkpoint_recorded: "Checkpoint recorded",
        child_assignment_committed: "Child assignment committed",
        child_assignment_staged: "Child assignment staged",
        dispatch_opened: "Dispatch opened",
        structural_revision_adopted: "Structural revision adopted",
        task_started: "Task started",
    };
    return labelByType[eventType] ?? titleCaseNodeLabel(eventType);
}

function eventInlineRows(
    event: TaskEventRow,
): readonly { readonly label: string; readonly value: string }[] {
    const payload = event.record.payload;
    const keysByType: Partial<Record<TaskEventRow["eventType"], readonly string[]>> = {
        boundary_accepted: ["outcome", "resulting_flow_status"],
        checkpoint_recorded: ["checkpoint_kind", "outcome"],
        dispatch_opened: ["status", "resolved_provider"],
        task_started: ["workflow_key", "manifest_ref"],
    };
    const keys = keysByType[event.eventType] ?? [];
    return keys.flatMap((key) => {
        const value = readDisplayString(payload, key);
        return value === null ? [] : [{ label: key.replaceAll("_", " "), value }];
    });
}

function readDisplayString(value: unknown, key: string): string | null {
    if (!isRecord(value)) {
        return null;
    }
    const item = value[key];
    if (typeof item === "string" && item.trim().length > 0) {
        return item;
    }
    if (typeof item === "number" || typeof item === "boolean") {
        return String(item);
    }
    return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
