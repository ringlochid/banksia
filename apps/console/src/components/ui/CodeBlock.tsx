import type { ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export interface CodeBlockProps {
    readonly children: ReactNode;
    readonly className?: string;
    readonly title?: string;
}

export function CodeBlock({ children, className, title }: CodeBlockProps) {
    return (
        <figure
            className={classNames(
                "overflow-hidden rounded-card border border-outline-soft bg-code text-foreground",
                className,
            )}
        >
            {title === undefined ? null : (
                <figcaption className="border-b border-outline-soft px-4 py-2 font-mono text-label font-medium uppercase text-muted">
                    {title}
                </figcaption>
            )}
            <pre
                aria-label={title ?? "Code block"}
                className="overflow-x-auto p-4 font-mono text-utility"
                tabIndex={0}
            >
                <code>{children}</code>
            </pre>
        </figure>
    );
}
