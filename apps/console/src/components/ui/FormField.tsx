import { cloneElement, isValidElement, type ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export interface FormFieldProps {
    readonly children: ReactNode;
    readonly error?: ReactNode;
    readonly hint?: ReactNode;
    readonly id: string;
    readonly label: string;
    readonly labelClassName?: string;
}

export function FormField({ children, error, hint, id, label, labelClassName }: FormFieldProps) {
    const hintId = `${id}-hint`;
    const errorId = `${id}-error`;
    const describedBy = [hint === undefined ? null : hintId, error === undefined ? null : errorId]
        .filter((value): value is string => value !== null)
        .join(" ");
    const renderedChildren = isValidElement<FieldControlProps>(children)
        ? cloneElement(children, {
              "aria-describedby": describedBy.length > 0 ? describedBy : undefined,
              "aria-invalid": error === undefined ? undefined : true,
              id,
          })
        : children;

    return (
        <div>
            <label
                className={classNames(
                    "block font-mono text-label font-medium uppercase text-muted",
                    labelClassName,
                )}
                htmlFor={id}
            >
                {label}
            </label>
            <div className="mt-2">{renderedChildren}</div>
            {hint === undefined ? null : (
                <p className="mt-1 text-utility text-muted" id={hintId}>
                    {hint}
                </p>
            )}
            {error === undefined ? null : (
                <p className="mt-1 text-utility font-semibold text-danger" id={errorId}>
                    {error}
                </p>
            )}
        </div>
    );
}

interface FieldControlProps {
    readonly "aria-describedby"?: string;
    readonly "aria-invalid"?: boolean;
    readonly id?: string;
}
