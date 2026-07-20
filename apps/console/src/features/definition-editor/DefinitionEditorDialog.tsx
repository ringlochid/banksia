import { useEffect, useId, useRef, type ReactNode, type SubmitEventHandler } from "react";

import { X } from "lucide-react";

interface DefinitionEditorDialogProps {
    readonly canClose?: boolean;
    readonly children: ReactNode;
    readonly closeLabel?: string;
    readonly eyebrow: string;
    readonly footer: ReactNode;
    readonly onClose: () => void;
    readonly onSubmit?: SubmitEventHandler<HTMLFormElement>;
    readonly title: string;
}

export function DefinitionEditorDialog({
    canClose = true,
    children,
    closeLabel = "Close dialog",
    eyebrow,
    footer,
    onClose,
    onSubmit,
    title,
}: DefinitionEditorDialogProps) {
    const dialogRef = useRef<HTMLFormElement | null>(null);
    const onCloseRef = useRef(onClose);
    const canCloseRef = useRef(canClose);
    const previousFocusRef = useRef<HTMLElement | null>(null);
    const titleId = useId();

    useEffect(() => {
        onCloseRef.current = onClose;
        canCloseRef.current = canClose;
    }, [canClose, onClose]);

    useEffect(() => {
        const activeElement = document.activeElement;
        previousFocusRef.current = activeElement instanceof HTMLElement ? activeElement : null;
        const dialog = dialogRef.current;
        if (dialog === null) {
            return;
        }
        const initialFocusTarget = dialog.querySelector<HTMLElement>("[data-dialog-initial-focus]");
        const focusableElements = getFocusableElements(dialog);
        const fallbackFocusTarget = focusableElements.length > 0 ? focusableElements[0] : dialog;
        (initialFocusTarget ?? fallbackFocusTarget).focus({ preventScroll: true });

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                if (!canCloseRef.current) {
                    return;
                }
                event.preventDefault();
                event.stopPropagation();
                onCloseRef.current();
                return;
            }
            if (event.key !== "Tab") {
                return;
            }

            trapDialogFocus(event, dialogRef.current);
        };

        document.body.classList.add("overflow-hidden");
        document.addEventListener("keydown", handleKeyDown, true);
        return () => {
            document.body.classList.remove("overflow-hidden");
            document.removeEventListener("keydown", handleKeyDown, true);
            const previousFocus = previousFocusRef.current;
            if (previousFocus?.isConnected === true) {
                previousFocus.focus({ preventScroll: true });
            }
        };
    }, []);

    return (
        <div
            className="fixed inset-0 z-50 grid place-items-center bg-foreground/35 p-4 backdrop-blur-[2px]"
            role="presentation"
        >
            <form
                aria-labelledby={titleId}
                aria-modal="true"
                className="max-h-[calc(100vh-4rem)] w-full max-w-xl overflow-hidden rounded-shell border border-outline-soft bg-surface shadow-popover"
                onSubmit={onSubmit}
                ref={dialogRef}
                role="dialog"
                tabIndex={-1}
            >
                <header className="flex items-start justify-between gap-4 border-b border-outline-soft px-5 py-4">
                    <div className="min-w-0">
                        <p className="font-mono text-label font-medium uppercase text-muted">
                            {eyebrow}
                        </p>
                        <h2
                            className="mt-1 font-display text-[20px] font-semibold leading-6 text-foreground"
                            id={titleId}
                        >
                            {title}
                        </h2>
                    </div>
                    <button
                        aria-label={closeLabel}
                        className="inline-flex size-icon-control shrink-0 items-center justify-center rounded-control border border-outline bg-surface-low text-muted transition-colors hover:border-primary/45 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-55"
                        disabled={!canClose}
                        onClick={onClose}
                        type="button"
                    >
                        <X aria-hidden="true" className="size-4" />
                    </button>
                </header>
                <div className="grid max-h-[calc(100vh-14rem)] gap-4 overflow-y-auto px-5 py-5">
                    {children}
                </div>
                <footer className="flex flex-col gap-2 border-t border-outline-soft px-5 py-4 sm:flex-row sm:justify-end">
                    {footer}
                </footer>
            </form>
        </div>
    );
}

function trapDialogFocus(event: KeyboardEvent, dialog: HTMLElement | null): void {
    if (dialog === null) {
        return;
    }

    const focusableElements = getFocusableElements(dialog);
    if (focusableElements.length === 0) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
    }

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    const activeElement = document.activeElement;
    const isFocusOutside =
        !(activeElement instanceof HTMLElement) || !dialog.contains(activeElement);

    if (event.shiftKey && (activeElement === firstElement || isFocusOutside)) {
        event.preventDefault();
        lastElement.focus({ preventScroll: true });
        return;
    }
    if (!event.shiftKey && (activeElement === lastElement || isFocusOutside)) {
        event.preventDefault();
        firstElement.focus({ preventScroll: true });
    }
}

function getFocusableElements(dialog: HTMLElement | null): HTMLElement[] {
    if (dialog === null) {
        return [];
    }

    return Array.from(
        dialog.querySelectorAll<HTMLElement>(
            [
                "a[href]",
                "button:not([disabled])",
                "input:not([disabled])",
                "select:not([disabled])",
                "textarea:not([disabled])",
                "[tabindex]:not([tabindex='-1'])",
            ].join(", "),
        ),
    ).filter(
        (element) =>
            element.tabIndex >= 0 &&
            !element.hasAttribute("hidden") &&
            element.getAttribute("aria-hidden") !== "true",
    );
}
