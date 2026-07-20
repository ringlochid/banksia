import {
    useEffect,
    useRef,
    useState,
    type Dispatch,
    type ReactNode,
    type SetStateAction,
} from "react";

import { AlertTriangle, ArrowRight, ChevronDown, Inbox, Search, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { PageFrame } from "../../components/layout";
import { Button, StatusChip, TimestampText } from "../../components/ui";
import {
    getNextCursor,
    isApiAbortError,
    mapUnknownApiError,
    requestJson,
    type ConsoleErrorView,
} from "../../api/client";
import type { components } from "../../api/generated/openapi";
import { runtimeTasksRoute, type RuntimeTasksQuery } from "../../api/routes";
import { taskOutcome } from "../../api/task-outcome";
import { mapTaskRow, type TaskRow } from "../../api/view-models";
import { classNames } from "../../lib/classNames";

type TaskStatusFilter = NonNullable<RuntimeTasksQuery["status"]>;
type TaskSort = NonNullable<RuntimeTasksQuery["sort"]>;

interface TaskPageState {
    readonly criteriaKey: string;
    readonly error: ConsoleErrorView | null;
    readonly hasLoaded: boolean;
    readonly isLoading: boolean;
    readonly isLoadingMore: boolean;
    readonly isRefreshing: boolean;
    readonly listGeneration: number;
    readonly nextCursor: string | null;
    readonly rows: readonly TaskRow[];
}

interface TaskPageController {
    readonly clearListView: () => void;
    readonly hasActiveNarrowing: boolean;
    readonly hasModifiedListView: boolean;
    readonly loadMore: () => void;
    readonly pageState: TaskPageState;
    readonly query: string;
    readonly refresh: () => void;
    readonly setQuery: (value: string) => void;
    readonly setSort: (value: TaskSort) => void;
    readonly setStatus: (value: TaskStatusFilter) => void;
    readonly sort: TaskSort;
    readonly status: TaskStatusFilter;
}

type TaskPageStateSetter = Dispatch<SetStateAction<TaskPageState>>;

const TASK_PAGE_SIZE = 25;
const TASK_SKELETON_ROW_INDICES = [0, 1, 2, 3, 4] as const;
const INITIAL_TASK_CRITERIA_KEY = buildTaskListCriteriaKey({
    sort: "updated_at_desc",
    status: "any",
    trimmedQuery: "",
});

const STATUS_FILTERS: readonly { readonly label: string; readonly value: TaskStatusFilter }[] = [
    { label: "All statuses", value: "any" },
    { label: "Pending", value: "pending" },
    { label: "Running", value: "running" },
    { label: "Paused", value: "paused" },
    { label: "Completed", value: "completed" },
    { label: "Cancelled", value: "cancelled" },
];

const SORT_OPTIONS: readonly { readonly label: string; readonly value: TaskSort }[] = [
    { label: "Sort by: Updated", value: "updated_at_desc" },
    { label: "Sort by: Oldest updated", value: "updated_at_asc" },
    { label: "Sort by: Title A-Z", value: "task_title_asc" },
    { label: "Sort by: Title Z-A", value: "task_title_desc" },
];

const initialState: TaskPageState = {
    criteriaKey: INITIAL_TASK_CRITERIA_KEY,
    error: null,
    hasLoaded: false,
    isLoading: true,
    isLoadingMore: false,
    isRefreshing: false,
    listGeneration: 0,
    nextCursor: null,
    rows: [],
};

export function TasksPage() {
    const controller = useTaskPageController();

    return (
        <PageFrame
            eyebrow="Runtime"
            headerContent={<TaskControls controller={controller} />}
            contentClassName="!py-0"
            headerClassName="!gap-6 !px-5 !pb-6 !pt-5 sm:!px-6 sm:!pb-7 sm:!pt-6 lg:!px-6"
            title="Tasks"
        >
            <div className="-mx-4 sm:-mx-5 lg:-mx-6">
                <TaskListState
                    error={controller.pageState.error}
                    hasActiveNarrowing={controller.hasActiveNarrowing}
                    isLoading={controller.pageState.isLoading}
                    onClearNarrowing={controller.clearListView}
                    onRetry={controller.refresh}
                    rows={controller.pageState.rows}
                />
                <TaskListFooter controller={controller} />
            </div>
        </PageFrame>
    );
}

function useTaskPageController(): TaskPageController {
    const [query, setQuery] = useState("");
    const [status, setStatus] = useState<TaskStatusFilter>("any");
    const [sort, setSort] = useState<TaskSort>("updated_at_desc");
    const [refreshToken, setRefreshToken] = useState(0);
    const [pageState, setPageState] = useState<TaskPageState>(initialState);
    const listGenerationRef = useRef(0);
    const trimmedQuery = query.trim();
    const criteriaKey = buildTaskListCriteriaKey({ sort, status, trimmedQuery });
    const hasActiveNarrowing = trimmedQuery.length > 0 || status !== "any";
    const hasModifiedListView = hasActiveNarrowing || sort !== "updated_at_desc";

    useTaskListReadEffect({
        criteriaKey,
        listGenerationRef,
        refreshToken,
        setPageState,
        sort,
        status,
        trimmedQuery,
    });

    return {
        clearListView: () => {
            setQuery("");
            setStatus("any");
            setSort("updated_at_desc");
        },
        hasActiveNarrowing,
        hasModifiedListView,
        loadMore: () => {
            void loadMoreTaskPage({
                criteriaKey,
                pageState,
                setPageState,
                sort,
                status,
                trimmedQuery,
            });
        },
        pageState,
        query,
        refresh: () => {
            setRefreshToken((value) => value + 1);
        },
        setQuery,
        setSort,
        setStatus,
        sort,
        status,
    };
}

function useTaskListReadEffect({
    criteriaKey,
    listGenerationRef,
    refreshToken,
    setPageState,
    sort,
    status,
    trimmedQuery,
}: {
    readonly criteriaKey: string;
    readonly listGenerationRef: { current: number };
    readonly refreshToken: number;
    readonly setPageState: TaskPageStateSetter;
    readonly sort: TaskSort;
    readonly status: TaskStatusFilter;
    readonly trimmedQuery: string;
}) {
    useEffect(() => {
        const abortController = new AbortController();
        const listGeneration = listGenerationRef.current + 1;
        listGenerationRef.current = listGeneration;
        beginTaskListRead(setPageState, criteriaKey, listGeneration);
        void readTaskPage({
            cursor: null,
            signal: abortController.signal,
            sort,
            status,
            trimmedQuery,
        })
            .then((page) => {
                applyTaskListPage(setPageState, page, criteriaKey, listGeneration);
            })
            .catch((error: unknown) => {
                applyTaskListError(setPageState, error, criteriaKey, listGeneration);
            });

        return () => {
            abortController.abort();
        };
    }, [criteriaKey, listGenerationRef, refreshToken, setPageState, sort, status, trimmedQuery]);
}

function TaskControls({ controller }: { readonly controller: TaskPageController }) {
    return (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_220px_auto]">
            <label className="relative block" htmlFor="tasks-query">
                <span className="sr-only">Search</span>
                <Search
                    aria-hidden="true"
                    className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted"
                />
                <input
                    className={controlClassName("pl-10")}
                    id="tasks-query"
                    onChange={(event) => {
                        controller.setQuery(event.target.value);
                    }}
                    placeholder="Search title, summary, workflow, or node"
                    type="search"
                    value={controller.query}
                />
            </label>
            <TaskSelect
                id="tasks-status"
                label="Status"
                onChange={(value) => {
                    controller.setStatus(value as TaskStatusFilter);
                }}
                options={STATUS_FILTERS}
                value={controller.status}
            />
            <TaskSelect
                id="tasks-sort"
                label="Sort"
                onChange={(value) => {
                    controller.setSort(value as TaskSort);
                }}
                options={SORT_OPTIONS}
                value={controller.sort}
            />
            {controller.hasModifiedListView ? (
                <Button onClick={controller.clearListView}>Clear filters</Button>
            ) : null}
        </div>
    );
}

function TaskSelect({
    id,
    label,
    onChange,
    options,
    value,
}: {
    readonly id: string;
    readonly label: string;
    readonly onChange: (value: string) => void;
    readonly options: readonly { readonly label: string; readonly value: string }[];
    readonly value: string;
}) {
    return (
        <label className="relative block" htmlFor={id}>
            <span className="sr-only">{label}</span>
            <select
                className={controlClassName("appearance-none bg-none pr-10")}
                id={id}
                onChange={(event) => {
                    onChange(event.target.value);
                }}
                value={value}
            >
                {options.map((option) => (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                ))}
            </select>
            <ChevronDown
                aria-hidden="true"
                className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-foreground"
            />
        </label>
    );
}

function TaskListFooter({ controller }: { readonly controller: TaskPageController }) {
    const { pageState } = controller;
    if (pageState.rows.length === 0) {
        return null;
    }

    return (
        <footer className="flex flex-col gap-3 border-t border-outline-soft bg-surface-low px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <p className="text-compact text-muted">
                {pageState.nextCursor === null
                    ? "All matching tasks are shown."
                    : "More tasks are available."}
            </p>
            <Button
                disabled={
                    pageState.nextCursor === null ||
                    pageState.isLoading ||
                    pageState.isLoadingMore ||
                    pageState.isRefreshing
                }
                onClick={controller.loadMore}
            >
                {pageState.isLoadingMore ? "Loading" : "Load more"}
            </Button>
        </footer>
    );
}

function TaskListState({
    error,
    hasActiveNarrowing,
    isLoading,
    onClearNarrowing,
    onRetry,
    rows,
}: {
    readonly error: ConsoleErrorView | null;
    readonly hasActiveNarrowing: boolean;
    readonly isLoading: boolean;
    readonly onClearNarrowing: () => void;
    readonly onRetry: () => void;
    readonly rows: readonly TaskRow[];
}) {
    const role = error === null ? "status" : "alert";

    if (isLoading) {
        return <TaskListFrame body={<TaskListLoadingState />} />;
    }

    if (error !== null) {
        return (
            <TaskListFrame
                body={
                    <TaskListMessageState
                        action={<Button onClick={onRetry}>Retry</Button>}
                        icon={
                            isAuthError(error) ? (
                                <ShieldAlert aria-hidden="true" className="size-6" />
                            ) : (
                                <AlertTriangle aria-hidden="true" className="size-6" />
                            )
                        }
                        role={role}
                        summary={error.summary}
                        title={
                            isAuthError(error) ? "Access to tasks failed" : "Tasks could not load"
                        }
                    />
                }
            />
        );
    }

    if (rows.length === 0) {
        return (
            <TaskListFrame
                body={
                    <TaskListMessageState
                        action={
                            hasActiveNarrowing ? (
                                <Button onClick={onClearNarrowing}>Clear filters</Button>
                            ) : undefined
                        }
                        icon={
                            hasActiveNarrowing ? (
                                <Search aria-hidden="true" className="size-6" />
                            ) : (
                                <Inbox aria-hidden="true" className="size-6" />
                            )
                        }
                        role={role}
                        summary={
                            hasActiveNarrowing
                                ? "No task rows match the current search or status filter."
                                : "The runtime task list is empty."
                        }
                        title={hasActiveNarrowing ? "No matching tasks" : "No tasks available"}
                    />
                }
            />
        );
    }

    return (
        <TaskListFrame
            body={
                <ol aria-label="Task rows" className="grid gap-2 bg-surface p-3">
                    {rows.map((row) => (
                        <TaskRowItem key={row.taskId} row={row} />
                    ))}
                </ol>
            }
        />
    );
}

function TaskListFrame({ body }: { readonly body: ReactNode }) {
    return (
        <div>
            <TaskListHeader />
            {body}
        </div>
    );
}

function TaskListHeader() {
    return (
        <div className="hidden border-b border-outline-soft bg-surface-low px-4 py-3 font-mono text-label font-medium uppercase text-muted md:grid md:grid-cols-[minmax(0,1fr)_120px_120px_96px] md:items-center md:gap-4 sm:px-6">
            <span>Tasks</span>
            <span>Status</span>
            <span className="text-right">Updated</span>
            <span className="sr-only">Open</span>
        </div>
    );
}

function TaskListLoadingState() {
    return (
        <>
            <div
                aria-busy="true"
                aria-label="Loading task rows"
                className="grid gap-8 bg-surface px-4 py-8 sm:px-6"
                role="status"
            >
                {TASK_SKELETON_ROW_INDICES.map((rowIndex) => (
                    <div aria-hidden="true" className="space-y-3 py-1" key={rowIndex}>
                        <div className="h-6 w-2/5 max-w-md animate-pulse rounded-lg bg-gradient-to-r from-surface-muted via-outline-soft/70 to-surface-muted" />
                        <div className="h-4 w-4/5 max-w-4xl animate-pulse rounded-lg bg-gradient-to-r from-surface-muted via-outline-soft/70 to-surface-muted" />
                        <div className="flex gap-3">
                            <div className="h-4 w-32 animate-pulse rounded-full bg-gradient-to-r from-surface-muted via-outline-soft/70 to-surface-muted" />
                            <div className="h-4 w-36 animate-pulse rounded-full bg-gradient-to-r from-surface-muted via-outline-soft/70 to-surface-muted" />
                        </div>
                    </div>
                ))}
            </div>
            <footer className="border-t border-outline-soft bg-surface-low px-4 py-4 sm:px-6">
                <p className="font-mono text-utility text-muted">Loading tasks...</p>
            </footer>
        </>
    );
}

function TaskListMessageState({
    action,
    icon,
    role,
    summary,
    title,
}: {
    readonly action?: ReactNode;
    readonly icon: ReactNode;
    readonly role: "alert" | "status";
    readonly summary: ReactNode;
    readonly title: string;
}) {
    return (
        <>
            <div className="bg-surface px-4 py-12 sm:px-6">
                <section
                    aria-label={title}
                    className="rounded-card border border-dashed border-outline bg-surface-muted p-8 text-center shadow-hairline"
                    role={role}
                >
                    <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-card bg-surface-high text-muted">
                        {icon}
                    </div>
                    <h2 className="font-display text-[18px] font-semibold leading-6 text-foreground">
                        {title}
                    </h2>
                    <p className="mx-auto mt-2 max-w-xl text-compact text-muted">{summary}</p>
                    {action === undefined ? null : (
                        <div className="mt-6 flex justify-center">{action}</div>
                    )}
                </section>
            </div>
            <footer
                aria-hidden="true"
                className="h-8 border-t border-outline-soft bg-surface-low"
            />
        </>
    );
}

function TaskRowItem({ row }: { readonly row: TaskRow }) {
    return (
        <li>
            <Link
                aria-label={`Open ${row.title} in Task Detail`}
                className="task-row block overflow-hidden rounded-card border border-outline-soft bg-surface-low text-foreground transition-colors"
                to={taskDetailPath(row.taskId)}
            >
                <article className="min-w-0 space-y-4 px-4 py-4 sm:px-6 md:grid md:grid-cols-[minmax(0,1fr)_120px_120px_96px] md:items-center md:gap-4 md:space-y-0">
                    <div className="min-w-0">
                        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 md:flex-nowrap">
                            <h2 className="min-w-0 break-words font-display text-[18px] font-semibold leading-6 text-foreground md:shrink-0">
                                {row.title}
                            </h2>
                            <TaskRowMetadata row={row} />
                        </div>
                        <p className="mt-2 line-clamp-2 break-words text-compact text-muted">
                            {row.summary}
                        </p>
                    </div>
                    <div className="flex items-center justify-between gap-3 md:block">
                        <p className="font-mono text-label font-medium uppercase text-muted md:sr-only">
                            Status
                        </p>
                        <TaskStatusChip row={row} />
                    </div>
                    <div className="flex min-w-0 items-center justify-between gap-3 md:block md:text-right">
                        <p className="font-mono text-label font-medium uppercase text-muted md:sr-only">
                            Updated
                        </p>
                        <TaskUpdatedTime value={row.updatedAt} />
                    </div>
                    <div className="flex justify-end">
                        <span className="task-open-pill inline-flex h-control items-center justify-center gap-2 rounded-control border border-outline bg-surface-low px-3 text-utility font-semibold text-foreground transition-colors">
                            <span className="hidden lg:inline">Open</span>
                            <ArrowRight aria-hidden="true" className="size-4 shrink-0" />
                        </span>
                    </div>
                </article>
            </Link>
        </li>
    );
}

function TaskRowMetadata({ row }: { readonly row: TaskRow }) {
    const items = [row.workflowKey, row.currentNodeKey].filter(
        (item): item is string => item !== null,
    );

    return (
        <div
            className="flex min-w-0 flex-wrap gap-2 font-mono text-[11px] leading-4 md:flex-nowrap md:overflow-hidden"
            data-task-meta
        >
            {items.map((item, index) => (
                <span
                    className="inline-flex min-w-0 max-w-full items-center rounded-full border border-outline-soft bg-surface-muted px-2.5 py-1"
                    key={`${item}-${index.toString()}`}
                    title={item}
                >
                    <span className="block min-w-0 max-w-80 truncate text-muted">{item}</span>
                </span>
            ))}
        </div>
    );
}

function TaskUpdatedTime({ value }: { readonly value: string }) {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) {
        return <span className="font-mono text-utility text-foreground">{value}</span>;
    }

    return (
        <span className="block">
            <span className="block text-compact text-foreground">{formatRelativeTime(date)}</span>
            <TimestampText className="block text-label text-muted" value={date} />
        </span>
    );
}

function TaskStatusChip({ row }: { readonly row: TaskRow }) {
    const outcome = taskOutcome(row.status, row.terminalOutcome);
    return (
        <StatusChip className="rounded-full px-3" tone={outcome.tone}>
            {outcome.label}
        </StatusChip>
    );
}

function formatRelativeTime(date: Date): string {
    const diffSeconds = Math.round((date.getTime() - Date.now()) / 1000);
    const divisions: readonly {
        readonly amount: number;
        readonly unit: Intl.RelativeTimeFormatUnit;
    }[] = [
        { amount: 60, unit: "second" },
        { amount: 60, unit: "minute" },
        { amount: 24, unit: "hour" },
        { amount: 7, unit: "day" },
        { amount: 4.34524, unit: "week" },
        { amount: 12, unit: "month" },
        { amount: Number.POSITIVE_INFINITY, unit: "year" },
    ];
    const formatter = new Intl.RelativeTimeFormat(undefined, {
        numeric: "auto",
        style: "narrow",
    });
    let duration = diffSeconds;

    for (const division of divisions) {
        if (Math.abs(duration) < division.amount) {
            return formatter.format(Math.round(duration), division.unit);
        }
        duration /= division.amount;
    }

    return formatter.format(Math.round(duration), "year");
}

function beginTaskListRead(
    setPageState: TaskPageStateSetter,
    criteriaKey: string,
    listGeneration: number,
): void {
    setPageState((currentState) => ({
        ...currentState,
        criteriaKey,
        error: null,
        isLoading: !currentState.hasLoaded,
        isLoadingMore: false,
        isRefreshing: currentState.hasLoaded,
        listGeneration,
        nextCursor: null,
    }));
}

function applyTaskListPage(
    setPageState: TaskPageStateSetter,
    page: components["schemas"]["RuntimeFlowSummaryListResponse"],
    criteriaKey: string,
    listGeneration: number,
): void {
    setPageState((currentState) => {
        if (!isCurrentTaskListRead(currentState, criteriaKey, listGeneration)) {
            return currentState;
        }

        return {
            ...currentState,
            error: null,
            hasLoaded: true,
            isLoading: false,
            isLoadingMore: false,
            isRefreshing: false,
            nextCursor: getNextCursor(page),
            rows: page.items.map(mapTaskRow),
        };
    });
}

function applyTaskListError(
    setPageState: TaskPageStateSetter,
    error: unknown,
    criteriaKey: string,
    listGeneration: number,
): void {
    if (isAbortError(error)) {
        return;
    }

    setPageState((currentState) => {
        if (!isCurrentTaskListRead(currentState, criteriaKey, listGeneration)) {
            return currentState;
        }

        return {
            ...currentState,
            error: toErrorView(error),
            hasLoaded: true,
            isLoading: false,
            isLoadingMore: false,
            isRefreshing: false,
            rows: currentState.hasLoaded ? currentState.rows : [],
        };
    });
}

async function loadMoreTaskPage({
    criteriaKey,
    pageState,
    setPageState,
    sort,
    status,
    trimmedQuery,
}: {
    readonly criteriaKey: string;
    readonly pageState: TaskPageState;
    readonly setPageState: TaskPageStateSetter;
    readonly sort: TaskSort;
    readonly status: TaskStatusFilter;
    readonly trimmedQuery: string;
}): Promise<void> {
    if (
        pageState.nextCursor === null ||
        pageState.isLoading ||
        pageState.isLoadingMore ||
        pageState.isRefreshing ||
        pageState.criteriaKey !== criteriaKey
    ) {
        return;
    }

    const cursor = pageState.nextCursor;
    const listGeneration = pageState.listGeneration;
    setPageState((currentState) =>
        isCurrentTaskListRead(currentState, criteriaKey, listGeneration)
            ? { ...currentState, error: null, isLoadingMore: true }
            : currentState,
    );

    try {
        const page = await readTaskPage({ cursor, signal: undefined, sort, status, trimmedQuery });
        setPageState((currentState) => {
            if (
                !isCurrentTaskListRead(currentState, criteriaKey, listGeneration) ||
                currentState.isLoading ||
                currentState.isRefreshing
            ) {
                return currentState;
            }

            return {
                ...currentState,
                error: null,
                isLoadingMore: false,
                nextCursor: getNextCursor(page),
                rows: [...currentState.rows, ...page.items.map(mapTaskRow)],
            };
        });
    } catch (error) {
        setPageState((currentState) => {
            if (!isCurrentTaskListRead(currentState, criteriaKey, listGeneration)) {
                return currentState;
            }

            return {
                ...currentState,
                error: toErrorView(error),
                isLoadingMore: false,
            };
        });
    }
}

function isCurrentTaskListRead(
    pageState: TaskPageState,
    criteriaKey: string,
    listGeneration: number,
): boolean {
    return pageState.criteriaKey === criteriaKey && pageState.listGeneration === listGeneration;
}

function buildTaskListCriteriaKey({
    sort,
    status,
    trimmedQuery,
}: {
    readonly sort: TaskSort;
    readonly status: TaskStatusFilter;
    readonly trimmedQuery: string;
}): string {
    return JSON.stringify([trimmedQuery, status, sort]);
}

async function readTaskPage({
    cursor,
    signal,
    sort,
    status,
    trimmedQuery,
}: {
    readonly cursor: string | null;
    readonly signal: AbortSignal | undefined;
    readonly sort: TaskSort;
    readonly status: TaskStatusFilter;
    readonly trimmedQuery: string;
}): Promise<components["schemas"]["RuntimeFlowSummaryListResponse"]> {
    const route = runtimeTasksRoute({
        cursor,
        limit: TASK_PAGE_SIZE,
        q: trimmedQuery.length === 0 ? null : trimmedQuery,
        sort,
        status,
    });

    return requestJson<components["schemas"]["RuntimeFlowSummaryListResponse"]>({
        path: route.path,
        query: route.query,
        signal,
    });
}

function controlClassName(className?: string): string {
    return classNames(
        "h-[50px] w-full min-w-0 rounded-control border border-outline bg-surface-low px-4 text-compact text-foreground shadow-hairline transition-colors placeholder:text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15",
        className,
    );
}

function taskDetailPath(taskId: string): string {
    return `/tasks/${encodeURIComponent(taskId)}`;
}

function isAbortError(error: unknown): boolean {
    return isApiAbortError(error);
}

function toErrorView(error: unknown): ConsoleErrorView {
    return mapUnknownApiError(error);
}

function isAuthError(error: ConsoleErrorView): boolean {
    return (
        error.status === 401 ||
        error.status === 403 ||
        error.code === "illegal_caller" ||
        error.code === "capability_rejected" ||
        error.code === "auth_required" ||
        error.code === "permission_denied"
    );
}
