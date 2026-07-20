import { useCallback, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { classNames } from "../../lib/classNames";
import { ShellTaskTitleContext, type ShellTaskTitleContextValue } from "./ShellTaskTitleContext";

interface ShellNavItem {
    readonly end?: boolean;
    readonly label: string;
    readonly to: string;
}

interface ShellBreadcrumb {
    readonly label: string;
    readonly to?: string;
}

interface ShellContext {
    readonly breadcrumbs: readonly ShellBreadcrumb[];
    readonly status: {
        readonly label: string;
        readonly tone: "active" | "neutral" | "success";
    } | null;
    readonly taskPath: string | null;
}

type PrimaryNavVariant = "mobile" | "rail";

export function AppShell() {
    const location = useLocation();
    const context = getShellContext(location.pathname);
    const [taskTitles, setTaskTitles] = useState<ReadonlyMap<string, string>>(() => new Map());
    const registerTaskTitle = useCallback((taskPath: string, title: string) => {
        setTaskTitles((current) => {
            if (current.get(taskPath) === title) {
                return current;
            }

            const next = new Map(current);
            next.set(taskPath, title);
            return next;
        });

        return () => {
            setTaskTitles((current) => {
                if (current.get(taskPath) !== title) {
                    return current;
                }

                const next = new Map(current);
                next.delete(taskPath);
                return next;
            });
        };
    }, []);
    const taskTitle = context.taskPath === null ? null : (taskTitles.get(context.taskPath) ?? null);
    const shellContext = taskTitle === null ? context : withTaskTitle(context, taskTitle);
    const shellTaskTitleContext = useMemo<ShellTaskTitleContextValue>(
        () => ({ registerTaskTitle }),
        [registerTaskTitle],
    );
    const navGroups = getPrimaryNavGroups(shellContext.taskPath);

    return (
        <ShellTaskTitleContext.Provider value={shellTaskTitleContext}>
            <a
                className="fixed left-4 top-3 z-50 -translate-y-24 rounded-control bg-primary px-4 py-2 font-semibold text-primary-contrast shadow-popover transition-transform focus:translate-y-0"
                href="#autoclaw-main-content"
            >
                Skip to main content
            </a>
            <div className="min-h-screen bg-background text-foreground lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]">
                <aside className="hidden border-r border-outline-soft bg-surface lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:overflow-y-auto lg:p-3">
                    <ShellBrand />
                    <nav
                        aria-label="Primary"
                        className="flex flex-1 flex-col gap-4 overflow-y-auto"
                    >
                        <PrimaryNavGroups groups={navGroups} variant="rail" />
                    </nav>
                </aside>
                <div className="min-w-0">
                    <nav
                        aria-label="Primary"
                        className="grid grid-cols-2 gap-1 border-b border-outline-soft bg-surface px-3 py-3 lg:hidden"
                    >
                        <div className="col-span-full">
                            <ShellBrand />
                        </div>
                        <PrimaryNavGroups groups={navGroups} variant="mobile" />
                    </nav>
                    <header className="sticky top-0 z-10 border-b border-outline-soft bg-surface">
                        <div className="flex min-h-11 flex-wrap items-center justify-between gap-3 px-4 py-3.5 sm:px-page-inline lg:py-0">
                            <div className="min-w-0">
                                <nav
                                    aria-label="Breadcrumb"
                                    className="flex min-w-0 items-center gap-2 font-mono text-utility text-muted"
                                >
                                    <ol className="flex min-w-0 flex-wrap items-center gap-1">
                                        {shellContext.breadcrumbs.map((breadcrumb, index) => {
                                            const isCurrent =
                                                index === shellContext.breadcrumbs.length - 1;

                                            return (
                                                <li
                                                    className="flex min-w-0 items-center gap-2"
                                                    key={`${breadcrumb.label}-${String(index)}`}
                                                >
                                                    {index === 0 ? null : (
                                                        <span
                                                            aria-hidden="true"
                                                            className="text-muted"
                                                        >
                                                            {"\u203a"}
                                                        </span>
                                                    )}
                                                    {!isCurrent && breadcrumb.to !== undefined ? (
                                                        <Link
                                                            className="min-w-0 truncate text-muted transition-colors hover:text-primary-foreground"
                                                            to={breadcrumb.to}
                                                        >
                                                            {breadcrumb.label}
                                                        </Link>
                                                    ) : (
                                                        <span
                                                            aria-current={
                                                                isCurrent ? "page" : undefined
                                                            }
                                                            className={classNames(
                                                                "min-w-0 truncate",
                                                                isCurrent &&
                                                                    "font-semibold text-primary-foreground",
                                                            )}
                                                        >
                                                            {breadcrumb.label}
                                                        </span>
                                                    )}
                                                </li>
                                            );
                                        })}
                                    </ol>
                                </nav>
                            </div>
                            {shellContext.status === null ? null : (
                                <div
                                    aria-label="Shell state"
                                    className={classNames(
                                        "inline-flex h-7 min-w-0 items-center gap-2 text-utility text-muted",
                                        shellContext.status.tone === "active" &&
                                            "text-primary-foreground",
                                        shellContext.status.tone === "success" && "text-success",
                                    )}
                                >
                                    <span
                                        aria-hidden="true"
                                        className="size-1.5 shrink-0 rounded-full bg-current"
                                    />
                                    <span className="truncate">{shellContext.status.label}</span>
                                </div>
                            )}
                        </div>
                    </header>
                    <main
                        aria-label="AutoClaw Console"
                        className="min-w-0 px-4 py-4 sm:px-page-inline sm:py-page-block"
                        id="autoclaw-main-content"
                        tabIndex={-1}
                    >
                        <Outlet />
                    </main>
                </div>
            </div>
        </ShellTaskTitleContext.Provider>
    );
}

function withTaskTitle(context: ShellContext, title: string): ShellContext {
    if (context.taskPath === null) {
        return context;
    }

    return {
        ...context,
        breadcrumbs: context.breadcrumbs.map((breadcrumb, index) => {
            const isTaskBreadcrumb =
                breadcrumb.to === context.taskPath ||
                (context.breadcrumbs.length === 2 && index === 1);

            return isTaskBreadcrumb ? { ...breadcrumb, label: title } : breadcrumb;
        }),
    };
}

function ShellBrand() {
    return (
        <div className="mb-2 flex min-h-[4.25rem] items-center gap-3 border-b border-outline-soft px-4 pb-5 pt-4 lg:mb-3">
            <img alt="" className="size-10 shrink-0 rounded-lg object-cover" src="/app-icon.png" />
            <div className="min-w-0">
                <p className="truncate font-display text-[20px] font-bold leading-6 text-foreground">
                    AutoClaw
                </p>
                <p className="text-[13px] leading-[18px] text-muted">Control Room</p>
            </div>
        </div>
    );
}

function PrimaryNavGroups({
    groups,
    variant,
}: {
    readonly groups: readonly {
        readonly items: readonly ShellNavItem[];
        readonly section: string;
    }[];
    readonly variant: PrimaryNavVariant;
}) {
    return groups.map((group) => (
        <div
            className={classNames(
                variant === "rail" && "space-y-0",
                variant === "mobile" && "contents",
            )}
            key={group.section}
        >
            <p
                className={classNames(
                    "font-mono text-label font-medium text-muted",
                    variant === "rail" && "px-4 py-2",
                    variant === "mobile" && "col-span-full px-3 py-[7px]",
                )}
            >
                {group.section}
            </p>
            <div
                className={classNames(
                    variant === "rail" && "space-y-1",
                    variant === "mobile" && "contents",
                )}
            >
                {group.items.map((item) => (
                    <PrimaryNavLink item={item} key={item.to} variant={variant} />
                ))}
            </div>
        </div>
    ));
}

function PrimaryNavLink({
    item,
    variant,
}: {
    readonly item: ShellNavItem;
    readonly variant: PrimaryNavVariant;
}) {
    return (
        <NavLink
            className={({ isActive }) =>
                classNames(
                    "flex h-control items-center gap-3 rounded-control border px-4 text-compact font-semibold transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:!outline-offset-[-2px] focus-visible:outline-primary",
                    variant === "rail" && "w-full",
                    variant === "mobile" &&
                        "!h-[38px] min-h-[38px] w-full border border-transparent px-3",
                    isActive
                        ? "border-primary/25 bg-active text-active-foreground"
                        : "border-transparent text-muted",
                )
            }
            end={item.end ?? true}
            to={item.to}
        >
            {({ isActive }) => (
                <>
                    <span
                        aria-hidden="true"
                        className={classNames(
                            "size-2 shrink-0 rounded-full",
                            isActive ? "bg-primary shadow-active-indicator" : "bg-outline-soft",
                        )}
                    />
                    <span className="truncate">{item.label}</span>
                </>
            )}
        </NavLink>
    );
}

function getPrimaryNavGroups(taskPath: string | null): readonly {
    readonly items: readonly ShellNavItem[];
    readonly section: string;
}[] {
    return [
        {
            section: "Runtime",
            items: [
                {
                    label: "Tasks",
                    to: "/tasks",
                },
            ],
        },
        ...(taskPath === null
            ? []
            : [
                  {
                      section: "Selected task",
                      items: [
                          {
                              label: "Task Detail",
                              to: taskPath,
                          },
                          {
                              label: "Human Requests",
                              to: `${taskPath}/human-requests`,
                          },
                          {
                              label: "Command Runs",
                              to: `${taskPath}/command-runs`,
                          },
                      ],
                  },
              ]),
        {
            section: "Authoring",
            items: [
                {
                    label: "Definitions",
                    to: "/definitions",
                },
                {
                    label: "Definition Editor",
                    to: "/definitions/editor",
                },
                {
                    label: "Task Start",
                    to: "/task-start",
                },
            ],
        },
    ];
}

function getShellContext(pathname: string): ShellContext {
    const segments = pathname.split("/").filter((segment) => segment.length > 0);
    const taskIdSegment = segments[0] === "tasks" ? segments[1] : undefined;
    const taskId = taskIdSegment === undefined ? "Selected task" : safeDecode(taskIdSegment);
    const taskPath = taskIdSegment === undefined ? null : `/tasks/${taskIdSegment}`;

    if (segments[0] === "tasks" && segments[2] === "human-requests") {
        return {
            breadcrumbs: [
                { label: "Tasks", to: "/tasks" },
                { label: taskId, to: taskPath ?? undefined },
                { label: "Human Requests" },
            ],
            status: null,
            taskPath,
        };
    }

    if (segments[0] === "tasks" && segments[2] === "command-runs") {
        return {
            breadcrumbs: [
                { label: "Tasks", to: "/tasks" },
                { label: taskId, to: taskPath ?? undefined },
                { label: "Command Runs" },
            ],
            status: null,
            taskPath,
        };
    }

    if (segments[0] === "tasks" && segments.length > 1) {
        return {
            breadcrumbs: [{ label: "Tasks", to: "/tasks" }, { label: taskId }],
            status: null,
            taskPath,
        };
    }

    if (segments[0] === "definitions" && segments[1] === "editor") {
        return {
            breadcrumbs: [
                { label: "Definitions", to: "/definitions" },
                { label: "Definition Editor" },
            ],
            status: { label: "Draft editing", tone: "active" },
            taskPath: null,
        };
    }

    if (segments[0] === "definitions") {
        return {
            breadcrumbs: [{ label: "Definitions" }],
            status: { label: "Stored registry", tone: "active" },
            taskPath: null,
        };
    }

    if (segments[0] === "task-start") {
        return {
            breadcrumbs: [{ label: "Definitions", to: "/definitions" }, { label: "Task Start" }],
            status: { label: "Workflow launch", tone: "neutral" },
            taskPath: null,
        };
    }

    if (import.meta.env.DEV && segments[0] === "fixtures") {
        return {
            breadcrumbs: [{ label: "Fixtures" }],
            status: { label: "Internal", tone: "success" },
            taskPath: null,
        };
    }

    return {
        breadcrumbs: [{ label: "Tasks" }],
        status: null,
        taskPath: null,
    };
}

function safeDecode(value: string): string {
    try {
        return decodeURIComponent(value);
    } catch {
        return value;
    }
}
