import { useMemo, useState } from "react";

import { StatePanel, TimestampText } from "../../components/ui";
import { classNames } from "../../lib/classNames";
import { titleCaseNodeLabel } from "./task-detail-format";
import type { TaskEventRow } from "./task-detail-model";

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
    const [showTechnical, setShowTechnical] = useState(false);
    const milestoneEvents = useMemo(() => events.filter((event) => event.isMilestone), [events]);
    const technicalCount = events.length - milestoneEvents.length;
    const visibleEvents = showTechnical ? events : milestoneEvents;

    return (
        <section className="min-w-0 overflow-hidden rounded-[22px] border border-outline-soft bg-surface-low shadow-panel">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-outline-soft px-4 py-3 sm:px-5">
                <p className="font-mono text-label font-medium text-muted">Events</p>
                {technicalCount === 0 ? null : (
                    <button
                        aria-pressed={showTechnical}
                        className="font-mono text-label text-muted transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                        onClick={() => {
                            setShowTechnical((current) => !current);
                        }}
                        type="button"
                    >
                        {showTechnical
                            ? "Hide technical events"
                            : `Technical events (${String(technicalCount)})`}
                    </button>
                )}
            </header>
            {visibleEvents.length === 0 ? (
                <div className="px-4 py-4">
                    <StatePanel
                        summary="No persisted task-event history was returned for the current snapshot anchor."
                        title="No event history"
                        tone="empty"
                    />
                </div>
            ) : (
                <ol aria-label="Task events" className="grid min-w-0 gap-2.5 px-4 py-4">
                    {visibleEvents.map((event) => (
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
                            eventDotClass(event),
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
                                    {event.label}
                                </p>
                                {event.nodeKey === null ? null : (
                                    <p className="break-all font-mono text-utility text-muted">
                                        {titleCaseNodeLabel(event.nodeKey)}
                                    </p>
                                )}
                            </div>
                            <TimestampText
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

function eventDotClass(event: TaskEventRow): string {
    switch (event.tone) {
        case "danger":
            return "bg-danger";
        case "success":
            return "bg-success";
        case "warning":
            return "bg-warning";
        case "neutral":
            return "bg-outline";
        case "active":
            return "bg-primary";
    }
}

function eventInlineRows(
    event: TaskEventRow,
): readonly { readonly label: string; readonly value: string }[] {
    const payload = event.record.payload;
    const keysByType: Partial<Record<TaskEventRow["eventType"], readonly string[]>> = {
        boundary_accepted: ["outcome", "resulting_flow_status"],
        checkpoint_recorded: ["checkpoint_kind", "outcome", "summary"],
        dispatch_opened: ["status", "resolved_provider"],
        task_started: ["workflow_key"],
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
