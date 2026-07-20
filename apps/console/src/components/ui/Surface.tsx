import type { HTMLAttributes, ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export interface SurfaceProps extends HTMLAttributes<HTMLElement> {
    readonly actions?: ReactNode;
    readonly children: ReactNode;
    readonly label?: string;
    readonly title?: string;
    readonly variant?: "default" | "muted";
}

const variantClasses = {
    default: "bg-surface-low",
    muted: "bg-surface-muted",
};

export function Surface({
    actions,
    children,
    className,
    label,
    title,
    variant = "default",
    ...props
}: SurfaceProps) {
    const hasHeader = actions !== undefined || label !== undefined || title !== undefined;

    return (
        <section
            className={classNames(
                "rounded-card border border-outline-soft p-4 shadow-hairline",
                variantClasses[variant],
                className,
            )}
            {...props}
        >
            {hasHeader ? (
                <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                        {label === undefined ? null : (
                            <p className="font-mono text-label font-medium uppercase text-muted">
                                {label}
                            </p>
                        )}
                        {title === undefined ? null : (
                            <h2 className="mt-1 font-display text-compact font-semibold text-foreground">
                                {title}
                            </h2>
                        )}
                    </div>
                    {actions === undefined ? null : (
                        <div className="flex flex-wrap items-center gap-2 sm:shrink-0">
                            {actions}
                        </div>
                    )}
                </header>
            ) : null}
            {children}
        </section>
    );
}
