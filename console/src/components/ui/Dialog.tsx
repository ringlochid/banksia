import {
    useEffect,
    useId,
    useRef,
    type KeyboardEvent as ReactKeyboardEvent,
    type ReactNode,
    type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { Button } from "./Button";

export interface DialogProps {
    readonly children: ReactNode;
    readonly closeDisabled?: boolean;
    readonly initialFocusRef?: RefObject<HTMLElement | null>;
    readonly isOpen: boolean;
    readonly onClose: () => void;
    readonly title: string;
}

const FOCUSABLE =
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Dialog({
    children,
    closeDisabled = false,
    initialFocusRef,
    isOpen,
    onClose,
    title,
}: DialogProps) {
    const titleId = useId();
    const panelRef = useRef<HTMLDivElement>(null);
    const invokerRef = useRef<HTMLElement | null>(null);

    useEffect(() => {
        if (!isOpen) {
            return;
        }
        invokerRef.current =
            document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null;
        const frame = requestAnimationFrame(() => {
            const first =
                panelRef.current?.querySelector<HTMLElement>(FOCUSABLE);
            (initialFocusRef?.current ?? first ?? panelRef.current)?.focus();
        });
        return () => {
            cancelAnimationFrame(frame);
            invokerRef.current?.focus();
        };
    }, [initialFocusRef, isOpen]);

    if (!isOpen) {
        return null;
    }

    return createPortal(
        <div className="ui-dialog__backdrop">
            <div
                aria-busy={closeDisabled || undefined}
                aria-labelledby={titleId}
                aria-modal="true"
                className="ui-dialog"
                onKeyDown={(event) =>
                    trapDialogFocus(
                        event,
                        panelRef.current,
                        closeDisabled,
                        onClose,
                    )
                }
                ref={panelRef}
                role="dialog"
                tabIndex={-1}
            >
                <header className="ui-dialog__header">
                    <h2 id={titleId}>{title}</h2>
                    <Button
                        aria-label={`Close ${title}`}
                        disabled={closeDisabled}
                        onClick={onClose}
                        tone="quiet"
                    >
                        Close
                    </Button>
                </header>
                {children}
            </div>
        </div>,
        document.body,
    );
}

function trapDialogFocus(
    event: ReactKeyboardEvent<HTMLDivElement>,
    panel: HTMLDivElement | null,
    closeDisabled: boolean,
    onClose: () => void,
): void {
    if (event.key === "Escape") {
        event.preventDefault();
        if (!closeDisabled) {
            onClose();
        }
        return;
    }
    if (event.key !== "Tab") {
        return;
    }
    const items = [...(panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    const first = items[0];
    const last = items.at(-1);
    if (first === undefined || last === undefined) {
        event.preventDefault();
        return;
    }
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}
