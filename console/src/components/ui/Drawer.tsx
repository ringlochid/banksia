import * as RadixDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "./Button";

export interface DrawerProps {
    readonly children: ReactNode;
    readonly isOpen: boolean;
    readonly onClose: () => void;
    readonly title: string;
    readonly description?: string;
    /**
     * Overlay drawers dim and block the page. The canvas uses `false` so the
     * team stays visible and clickable while a Member is being edited.
     */
    readonly modal?: boolean;
    readonly footer?: ReactNode;
}

/**
 * Right-hand contextual panel. Radix has no drawer primitive, so this is its
 * Dialog positioned as a side sheet — which keeps the focus management,
 * Escape handling, and dismiss semantics.
 */
export function Drawer({
    children,
    description,
    footer,
    isOpen,
    modal = false,
    onClose,
    title,
}: DrawerProps) {
    return (
        <RadixDialog.Root
            modal={modal}
            onOpenChange={(open) => {
                if (!open) {
                    onClose();
                }
            }}
            open={isOpen}
        >
            <RadixDialog.Portal>
                {modal ? (
                    <RadixDialog.Overlay className="ui-dialog__overlay" />
                ) : null}
                <RadixDialog.Content
                    aria-describedby={undefined}
                    className="ui-drawer"
                    onInteractOutside={(event) => {
                        // A non-modal drawer must not close when the user
                        // interacts with the canvas behind it.
                        if (!modal) {
                            event.preventDefault();
                        }
                    }}
                >
                    <header className="ui-drawer__header">
                        <div className="ui-drawer__heading">
                            <RadixDialog.Title className="ui-drawer__title">
                                {title}
                            </RadixDialog.Title>
                            {description === undefined ? null : (
                                <RadixDialog.Description className="ui-drawer__description">
                                    {description}
                                </RadixDialog.Description>
                            )}
                        </div>
                        <RadixDialog.Close asChild>
                            <Button
                                aria-label={`Close ${title}`}
                                icon
                                size="sm"
                                tone="quiet"
                            >
                                <X aria-hidden="true" size={16} />
                            </Button>
                        </RadixDialog.Close>
                    </header>
                    <div className="ui-drawer__body">{children}</div>
                    {footer === undefined ? null : (
                        <footer className="ui-drawer__footer">{footer}</footer>
                    )}
                </RadixDialog.Content>
            </RadixDialog.Portal>
        </RadixDialog.Root>
    );
}
