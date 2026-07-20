import { classNames } from "../../lib/classNames";

export function controlClassName(extraClassName?: string): string {
    return classNames(
        "h-control w-full rounded-control border border-outline bg-surface px-3 text-compact text-foreground shadow-hairline transition-colors placeholder:text-muted/70 focus:border-primary/50 focus:outline-none focus:ring-2 focus:ring-primary/15",
        extraClassName,
    );
}

export function textAreaClassName(extraClassName?: string): string {
    return classNames(
        "w-full rounded-control border border-outline bg-surface px-3 py-3 text-compact text-foreground shadow-hairline transition-colors placeholder:text-muted/70 focus:border-primary/50 focus:outline-none focus:ring-2 focus:ring-primary/15",
        extraClassName,
    );
}
