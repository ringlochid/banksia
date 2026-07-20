import type { ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export interface FocusedDetailShellProps {
    readonly actions?: ReactNode;
    readonly children: ReactNode;
    readonly className?: string;
    readonly label?: string;
    readonly title: string;
}

export function FocusedDetailShell({
    actions,
    children,
    className,
    label,
    title,
}: FocusedDetailShellProps) {
    return (
        <aside
            aria-label={title}
            className={classNames(
                "rounded-card border border-outline-soft bg-surface-low shadow-panel",
                className,
            )}
        >
            <header className="flex items-start justify-between gap-4 border-b border-outline-soft px-4 py-3">
                <div className="min-w-0">
                    {label === undefined ? null : (
                        <p className="font-mono text-label font-medium uppercase text-muted">
                            {label}
                        </p>
                    )}
                    <h2 className="mt-1 truncate font-display text-compact font-semibold text-foreground">
                        {title}
                    </h2>
                </div>
                {actions === undefined ? null : (
                    <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
                )}
            </header>
            <div className="px-4 py-4">{children}</div>
        </aside>
    );
}
