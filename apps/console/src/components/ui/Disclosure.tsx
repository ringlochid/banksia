import type { DetailsHTMLAttributes, ReactNode } from "react";

import { ChevronDown } from "lucide-react";

import { classNames } from "../../lib/classNames";

export interface DisclosureProps extends DetailsHTMLAttributes<HTMLDetailsElement> {
    readonly children: ReactNode;
    readonly label?: string;
    readonly title: string;
}

export function Disclosure({ children, className, label, title, ...props }: DisclosureProps) {
    return (
        <details
            className={classNames(
                "group rounded-card border border-outline-soft bg-surface-low shadow-hairline",
                className,
            )}
            {...props}
        >
            <summary className="flex min-h-control cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
                <span className="min-w-0">
                    {label === undefined ? null : (
                        <span className="block font-mono text-label font-medium uppercase text-muted">
                            {label}
                        </span>
                    )}
                    <span className="block truncate font-display text-compact font-semibold text-foreground">
                        {title}
                    </span>
                </span>
                <ChevronDown
                    aria-hidden="true"
                    className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180"
                />
            </summary>
            <div className="border-t border-outline-soft px-4 py-4">{children}</div>
        </details>
    );
}
