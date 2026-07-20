import { classNames } from "../../lib/classNames";

export interface IdRefTextProps {
    readonly className?: string;
    readonly value: string;
}

export interface TimestampTextProps {
    readonly className?: string;
    readonly value: Date | string;
}

export function IdRefText({ className, value }: IdRefTextProps) {
    return (
        <span className={classNames("break-all font-mono text-utility text-muted", className)}>
            {value}
        </span>
    );
}

export function TimestampText({ className, value }: TimestampTextProps) {
    const date = value instanceof Date ? value : new Date(value);
    const label = Number.isNaN(date.valueOf())
        ? String(value)
        : new Intl.DateTimeFormat(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
          }).format(date);

    return (
        <time
            className={classNames("font-mono text-utility", className)}
            dateTime={Number.isNaN(date.valueOf()) ? undefined : date.toISOString()}
        >
            {label}
        </time>
    );
}
