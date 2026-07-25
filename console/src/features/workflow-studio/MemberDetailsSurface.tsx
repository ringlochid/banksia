import "./member-details.css";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import type { NormalizedMember, NormalizedWorkflow } from "../../api/types";
import { Button } from "../../components/ui";
import { MemberForm } from "./forms/MemberForm";
import { WorkflowForm } from "./forms/WorkflowForm";
import type {
    MemberEdit,
    StudioValidationIssue,
    WorkflowAuthoringOptionsState,
    WorkflowEdit,
} from "./state/contracts";

const NARROW_QUERY = "(max-width: 48rem)";
const FOCUSABLE =
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface MemberDetailsSurfaceProps {
    readonly disabled: boolean;
    readonly focusRequest: number;
    readonly issues: readonly StudioValidationIssue[];
    readonly member: NormalizedMember;
    readonly onClose: () => void;
    readonly onEditMember: (patch: MemberEdit) => void;
    readonly onEditWorkflow: (patch: WorkflowEdit) => void;
    readonly onRetryOptions: () => void;
    readonly open: boolean;
    readonly options: WorkflowAuthoringOptionsState;
    readonly workflow: NormalizedWorkflow;
}

export function MemberDetailsSurface({
    disabled,
    focusRequest,
    issues,
    member,
    onClose,
    onEditMember,
    onEditWorkflow,
    onRetryOptions,
    open,
    options,
    workflow,
}: MemberDetailsSurfaceProps) {
    const isNarrow = useNarrowViewport();
    const titleId = useId();
    const panelRef = useRef<HTMLElement>(null);
    const handledFocusRequest = useRef(0);

    useEffect(() => {
        const hasExplicitRequest = focusRequest > handledFocusRequest.current;
        if (!open || (!isNarrow && !hasExplicitRequest)) {
            return;
        }
        handledFocusRequest.current = focusRequest;
        const frame = requestAnimationFrame(() => {
            const panel = panelRef.current;
            const firstInvalid = panel?.querySelector<HTMLElement>(
                '[aria-invalid="true"]',
            );
            const firstField = panel?.querySelector<HTMLElement>(
                "input:not([disabled]), select:not([disabled]), textarea:not([disabled])",
            );
            (
                firstInvalid ??
                firstField ??
                panel?.querySelector<HTMLElement>("[data-details-heading]") ??
                panel
            )?.focus();
        });
        return () => cancelAnimationFrame(frame);
    }, [focusRequest, isNarrow, member.id, open]);

    useEffect(() => {
        if (!open || !isNarrow) {
            return;
        }
        const root = document.getElementById("root");
        const hadInert = root?.hasAttribute("inert") ?? false;
        const previousOverflow = document.body.style.overflow;
        root?.setAttribute("inert", "");
        document.body.style.overflow = "hidden";
        return () => {
            if (!hadInert) {
                root?.removeAttribute("inert");
            }
            document.body.style.overflow = previousOverflow;
        };
    }, [isNarrow, open]);

    if (!open) {
        return null;
    }

    const Surface = isNarrow ? "div" : "aside";
    const content = (
        <Surface
            aria-busy={disabled || undefined}
            aria-labelledby={titleId}
            aria-modal={isNarrow || undefined}
            className="studio-member-details"
            data-details-surface
            onKeyDown={(event) => {
                if (isNarrow) {
                    trapSheetFocus(event, panelRef.current, onClose);
                }
            }}
            ref={(element) => {
                panelRef.current = element;
            }}
            role={isNarrow ? "dialog" : undefined}
            tabIndex={-1}
        >
            <header className="studio-member-details__header">
                <div>
                    <p>Selected teammate</p>
                    <h2 data-details-heading id={titleId} tabIndex={-1}>
                        Details
                    </h2>
                </div>
                <Button
                    aria-label="Close teammate details"
                    className="studio-member-details__close"
                    onClick={onClose}
                    tone="quiet"
                >
                    <X aria-hidden="true" size={18} />
                    <span className="sr-only">Close</span>
                </Button>
            </header>
            <div className="studio-member-details__body">
                <MemberForm
                    disabled={disabled}
                    issues={issues}
                    member={member}
                    onEdit={onEditMember}
                    onRetryOptions={onRetryOptions}
                    options={options}
                    workflow={workflow}
                />
                <details className="studio-member-details__workflow">
                    <summary>Workflow purpose and shared note</summary>
                    <WorkflowForm
                        disabled={disabled}
                        issues={issues}
                        onEdit={onEditWorkflow}
                        workflow={workflow}
                    />
                </details>
            </div>
        </Surface>
    );

    return isNarrow
        ? createPortal(
              <div className="studio-member-details__backdrop">{content}</div>,
              document.body,
          )
        : content;
}

function useNarrowViewport(): boolean {
    const query = (): boolean =>
        typeof window.matchMedia === "function"
            ? window.matchMedia(NARROW_QUERY).matches
            : window.innerWidth <= 48 * 16;
    const [isNarrow, setIsNarrow] = useState(query);

    useEffect(() => {
        if (typeof window.matchMedia !== "function") {
            return;
        }
        const media = window.matchMedia(NARROW_QUERY);
        const update = () => setIsNarrow(media.matches);
        media.addEventListener("change", update);
        return () => media.removeEventListener("change", update);
    }, []);

    return isNarrow;
}

function trapSheetFocus(
    event: KeyboardEvent<HTMLElement>,
    panel: HTMLElement | null,
    onClose: () => void,
): void {
    if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
    }
    if (event.key !== "Tab") {
        return;
    }
    const focusable = [
        ...(panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []),
    ];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined || last === undefined) {
        event.preventDefault();
    } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}
