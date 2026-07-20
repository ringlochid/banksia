import type { ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export interface ListRowProps {
    readonly action?: ReactNode;
    readonly className?: string;
    readonly description?: ReactNode;
    readonly meta?: ReactNode;
    readonly selected?: boolean;
    readonly status?: ReactNode;
    readonly title: ReactNode;
}

export function ListRow({
    action,
    className,
    description,
    meta,
    selected = false,
    status,
    title,
}: ListRowProps) {
    return (
        <article
            className={classNames(
                "flex min-w-0 flex-col gap-3 rounded-card border bg-surface-low p-4 shadow-hairline sm:flex-row sm:items-center sm:justify-between",
                selected
                    ? "border-primary/45 bg-primary-soft"
                    : "border-outline-soft hover:border-primary/25",
                className,
            )}
        >
            <div className="min-w-0">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <h3 className="min-w-0 truncate font-display text-compact font-semibold text-foreground">
                        {title}
                    </h3>
                    {status}
                </div>
                {description === undefined ? null : (
                    <div className="mt-1 min-w-0 text-compact text-muted">{description}</div>
                )}
                {meta === undefined ? null : (
                    <div className="mt-2 flex min-w-0 flex-wrap gap-2 font-mono text-label text-muted">
                        {meta}
                    </div>
                )}
            </div>
            {action === undefined ? null : (
                <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>
            )}
        </article>
    );
}
