import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode, RefObject } from "react";

export interface DialogProps {
    readonly children: ReactNode;
    readonly closeDisabled?: boolean;
    readonly description?: string;
    /** Focus this element on open instead of the first focusable child. */
    readonly initialFocusRef?: RefObject<HTMLElement | null>;
    readonly isOpen: boolean;
    readonly onClose: () => void;
    readonly title: string;
}

/**
 * Radix owns focus trapping, restore, scroll lock, and Escape. The previous
 * hand-rolled implementation is gone along with its focus-order bugs.
 */
export function Dialog({
    children,
    closeDisabled = false,
    description,
    initialFocusRef,
    isOpen,
    onClose,
    title,
}: DialogProps) {
    return (
        <RadixDialog.Root
            onOpenChange={(open) => {
                if (!open && !closeDisabled) {
                    onClose();
                }
            }}
            open={isOpen}
        >
            <RadixDialog.Portal>
                <RadixDialog.Overlay className="ui-dialog__overlay" />
                <RadixDialog.Content
                    className="ui-dialog__content"
                    onEscapeKeyDown={(event) => {
                        if (closeDisabled) {
                            event.preventDefault();
                        }
                    }}
                    onInteractOutside={(event) => {
                        if (closeDisabled) {
                            event.preventDefault();
                        }
                    }}
                    onOpenAutoFocus={(event) => {
                        const target = initialFocusRef?.current;
                        if (target !== null && target !== undefined) {
                            event.preventDefault();
                            target.focus();
                        }
                    }}
                >
                    <RadixDialog.Title className="ui-dialog__title">
                        {title}
                    </RadixDialog.Title>
                    {description === undefined ? (
                        <RadixDialog.Description className="sr-only">
                            {title}
                        </RadixDialog.Description>
                    ) : (
                        <RadixDialog.Description className="ui-dialog__description">
                            {description}
                        </RadixDialog.Description>
                    )}
                    {children}
                </RadixDialog.Content>
            </RadixDialog.Portal>
        </RadixDialog.Root>
    );
}

export function DialogFooter({ children }: { readonly children: ReactNode }) {
    return <div className="ui-dialog__footer">{children}</div>;
}

export interface DialogCloseProps {
    readonly children: ReactNode;
    /** Render the child element itself as the close control. */
    readonly asChild?: boolean;
}

export function DialogClose({ asChild = false, children }: DialogCloseProps) {
    return <RadixDialog.Close asChild={asChild}>{children}</RadixDialog.Close>;
}
