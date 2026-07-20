import type { ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export interface PropertyGridItem {
    readonly label: string;
    readonly value: ReactNode;
}

export interface PropertyGridProps {
    readonly className?: string;
    readonly items: readonly PropertyGridItem[];
}

export function PropertyGrid({ className, items }: PropertyGridProps) {
    const isSingleItem = items.length === 1;

    return (
        <dl
            className={classNames(
                "grid overflow-hidden rounded-card border border-outline-soft bg-surface-low sm:grid-cols-2 lg:grid-cols-3",
                className,
            )}
        >
            {items.map((item) => (
                <div
                    className={classNames(
                        "min-w-0 border-b border-outline-soft px-4 py-3 last:border-b-0",
                        isSingleItem
                            ? "sm:col-span-2 lg:col-span-3"
                            : "sm:border-r sm:[&:nth-child(2n)]:border-r-0 lg:[&:nth-child(2n)]:border-r lg:[&:nth-child(3n)]:border-r-0",
                    )}
                    key={item.label}
                >
                    <dt className="font-mono text-label font-medium uppercase text-muted">
                        {item.label}
                    </dt>
                    <dd className="mt-1 min-w-0 text-compact text-foreground">{item.value}</dd>
                </div>
            ))}
        </dl>
    );
}
