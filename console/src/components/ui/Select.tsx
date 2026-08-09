import * as RadixSelect from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";

export interface SelectOption {
    readonly value: string;
    readonly label: string;
    readonly disabled?: boolean;
    /**
     * Secondary line rendered under the label. Long descriptions belong here,
     * never appended to the label — a native select truncates the whole row
     * into one unreadable line, which is what this replaces.
     */
    readonly hint?: string;
}

export interface SelectProps {
    readonly "aria-describedby"?: string;
    readonly "aria-invalid"?: boolean;
    readonly id?: string;
    readonly value: string;
    readonly onValueChange: (value: string) => void;
    readonly options: readonly SelectOption[];
    readonly placeholder?: string;
    readonly disabled?: boolean;
    readonly ariaLabel?: string;
    readonly dataFieldPath?: string;
}

export function Select({
    "aria-describedby": ariaDescribedBy,
    "aria-invalid": ariaInvalid,
    ariaLabel,
    dataFieldPath,
    disabled = false,
    id,
    onValueChange,
    options,
    placeholder = "Choose…",
    value,
}: SelectProps) {
    return (
        <RadixSelect.Root
            disabled={disabled}
            onValueChange={onValueChange}
            {...(value === "" ? {} : { value })}
        >
            <RadixSelect.Trigger
                aria-describedby={ariaDescribedBy}
                aria-invalid={ariaInvalid}
                aria-label={ariaLabel}
                className="ui-select__trigger"
                data-field-path={dataFieldPath}
                id={id}
            >
                <RadixSelect.Value
                    className="ui-select__value"
                    placeholder={placeholder}
                />
                <RadixSelect.Icon className="ui-select__icon">
                    <ChevronDown size={15} />
                </RadixSelect.Icon>
            </RadixSelect.Trigger>
            <RadixSelect.Portal>
                <RadixSelect.Content
                    className="ui-select__content"
                    position="popper"
                    sideOffset={4}
                >
                    <RadixSelect.Viewport className="ui-select__viewport">
                        {options.map((option) => (
                            <RadixSelect.Item
                                className="ui-select__item"
                                {...(option.disabled === undefined
                                    ? {}
                                    : { disabled: option.disabled })}
                                key={option.value}
                                value={option.value}
                            >
                                <RadixSelect.ItemText>
                                    {option.label}
                                </RadixSelect.ItemText>
                                {option.hint === undefined ? null : (
                                    <span className="ui-select__item-hint">
                                        {option.hint}
                                    </span>
                                )}
                                <RadixSelect.ItemIndicator className="sr-only">
                                    <Check size={14} />
                                </RadixSelect.ItemIndicator>
                            </RadixSelect.Item>
                        ))}
                    </RadixSelect.Viewport>
                </RadixSelect.Content>
            </RadixSelect.Portal>
        </RadixSelect.Root>
    );
}
