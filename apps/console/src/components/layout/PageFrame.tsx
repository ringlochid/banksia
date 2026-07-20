import { useId, type ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export interface PageFrameProps {
    readonly actions?: ReactNode;
    readonly children: ReactNode;
    readonly className?: string;
    readonly description?: string;
    readonly eyebrow?: ReactNode;
    readonly headerContent?: ReactNode;
    readonly headerContentPlacement?: "after-description" | "title-inline";
    readonly headerClassName?: string;
    readonly contentClassName?: string;
    readonly title: string;
}

export function PageFrame({
    actions,
    children,
    className,
    description,
    eyebrow,
    headerContent,
    headerContentPlacement = "after-description",
    headerClassName,
    contentClassName,
    title,
}: PageFrameProps) {
    const headingId = useId();
    const hasHeaderContent = headerContent !== undefined;
    const hasInlineHeaderContent = hasHeaderContent && headerContentPlacement === "title-inline";

    return (
        <section
            aria-labelledby={headingId}
            className={classNames(
                "mx-auto w-full max-w-[1320px] overflow-hidden rounded-shell border border-outline-soft bg-surface shadow-shell",
                className,
            )}
        >
            <header
                className={classNames(
                    "flex flex-col gap-5 border-b border-outline-soft p-5 sm:p-6",
                    !hasHeaderContent && "lg:flex-row lg:items-start lg:justify-between",
                    headerClassName,
                )}
            >
                <div className="flex w-full flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                        {eyebrow === undefined ? null : (
                            <p className="font-mono text-label font-medium text-muted">{eyebrow}</p>
                        )}
                        <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
                            <h1
                                className="font-display text-[22px] font-semibold leading-6 text-foreground sm:text-display"
                                id={headingId}
                            >
                                {title}
                            </h1>
                            {hasInlineHeaderContent ? headerContent : null}
                        </div>
                        {description === undefined ? null : (
                            <p className="mt-2 max-w-3xl text-compact text-muted">{description}</p>
                        )}
                    </div>
                    {actions === undefined ? null : (
                        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
                    )}
                </div>
                {hasHeaderContent && !hasInlineHeaderContent ? headerContent : null}
            </header>
            <div className={classNames("px-4 py-4 sm:px-5 lg:px-6", contentClassName)}>
                {children}
            </div>
        </section>
    );
}
