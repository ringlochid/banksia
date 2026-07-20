import type { HTMLAttributes, ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export type StatusTone = "active" | "danger" | "neutral" | "success" | "warning";

export interface StatusChipProps extends HTMLAttributes<HTMLSpanElement> {
    readonly children: ReactNode;
    readonly tone?: StatusTone;
    readonly withDot?: boolean;
}

const toneClasses: Record<StatusTone, string> = {
    active: "border-primary/20 bg-primary-soft text-primary-foreground",
    danger: "border-danger/20 bg-danger-soft text-danger",
    neutral: "border-outline-soft bg-surface-muted text-muted",
    success: "border-success/20 bg-success-soft text-success",
    warning: "border-warning/20 bg-warning-soft text-warning",
};

export function StatusChip({ children, className, tone = "neutral", ...props }: StatusChipProps) {
    const { withDot = false, ...spanProps } = props;

    return (
        <span
            className={classNames(
                "inline-flex h-7 items-center gap-2 rounded-control border px-2.5 font-mono text-label font-medium",
                toneClasses[tone],
                className,
            )}
            {...spanProps}
        >
            {withDot ? (
                <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
            ) : null}
            {children}
        </span>
    );
}
