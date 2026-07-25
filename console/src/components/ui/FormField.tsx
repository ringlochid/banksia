import {
    cloneElement,
    isValidElement,
    type ReactElement,
    type ReactNode,
} from "react";

export interface FormFieldProps {
    readonly children: ReactElement<{
        "aria-describedby"?: string;
        "aria-invalid"?: boolean;
        id?: string;
    }>;
    readonly error?: string | null;
    readonly hint?: ReactNode;
    readonly id: string;
    readonly label: string;
    readonly optional?: boolean;
}

export function FormField({
    children,
    error,
    hint,
    id,
    label,
    optional = false,
}: FormFieldProps) {
    const hintId = hint === undefined ? null : `${id}-hint`;
    const errorId =
        error === undefined || error === null ? null : `${id}-error`;
    const describedBy =
        [hintId, errorId].filter(Boolean).join(" ") || undefined;
    const control = isValidElement(children)
        ? cloneElement(children, {
              id,
              ...(describedBy === undefined
                  ? {}
                  : { "aria-describedby": describedBy }),
              ...(errorId === null ? {} : { "aria-invalid": true }),
          })
        : children;

    return (
        <div className="ui-field">
            <label className="ui-field__label" htmlFor={id}>
                {label}
                {optional ? (
                    <span className="ui-field__optional">Optional</span>
                ) : null}
            </label>
            {control}
            {hint === undefined ? null : (
                <div className="ui-field__hint" id={hintId ?? undefined}>
                    {hint}
                </div>
            )}
            {error === undefined || error === null ? null : (
                <div className="ui-field__error" id={errorId ?? undefined}>
                    {error}
                </div>
            )}
        </div>
    );
}
