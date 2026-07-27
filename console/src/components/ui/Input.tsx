import { Search } from "lucide-react";
import type { InputHTMLAttributes, Ref, TextareaHTMLAttributes } from "react";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
    readonly ref?: Ref<HTMLInputElement>;
}

export function Input({ className = "", ...props }: InputProps) {
    return <input className={`ui-input ${className}`.trim()} {...props} />;
}

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
    readonly ref?: Ref<HTMLTextAreaElement>;
}

export function Textarea({ className = "", ...props }: TextareaProps) {
    return (
        <textarea className={`ui-textarea ${className}`.trim()} {...props} />
    );
}

export interface SearchInputProps extends InputProps {
    /** Visually hidden label. Search fields carry no visible label. */
    readonly label: string;
}

/**
 * Type-to-filter search. Deliberately has no submit button: every list in the
 * Console filters as you type, so there is one search interaction to learn.
 */
export function SearchInput({
    className = "",
    id,
    label,
    ...props
}: SearchInputProps) {
    return (
        <div className={`ui-search ${className}`.trim()}>
            <span aria-hidden="true" className="ui-search__icon">
                <Search size={15} />
            </span>
            <label className="sr-only" htmlFor={id}>
                {label}
            </label>
            <Input id={id} type="search" {...props} />
        </div>
    );
}
