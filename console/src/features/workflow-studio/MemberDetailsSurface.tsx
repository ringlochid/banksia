import "./member-details.css";

import { Trash2 } from "lucide-react";

import type { NormalizedMember, NormalizedWorkflow } from "../../api/types";
import { Button, Notice } from "../../components/ui";
import { DetailsDrawer } from "./DetailsDrawer";
import { MemberForm } from "./forms/MemberForm";
import type {
    MemberEdit,
    StudioValidationIssue,
    WorkflowAuthoringOptionsState,
} from "./state/contracts";

export interface MemberDetailsSurfaceProps {
    readonly createState?:
        | {
              readonly canSubmit: boolean;
              readonly error: string | null;
              readonly onSubmit: () => void;
              readonly submitting: boolean;
          }
        | undefined;
    readonly disabled: boolean;
    readonly focusRequest: number;
    readonly issues: readonly StudioValidationIssue[];
    readonly member: NormalizedMember;
    readonly onClose: () => void;
    readonly onEditMember: (patch: MemberEdit) => void;
    readonly onRemove?: (() => void) | undefined;
    readonly onRetryOptions: () => void;
    readonly open: boolean;
    readonly options: WorkflowAuthoringOptionsState;
    readonly workflow: NormalizedWorkflow;
}

export function MemberDetailsSurface({
    createState,
    disabled,
    focusRequest,
    issues,
    member,
    onClose,
    onEditMember,
    onRemove,
    onRetryOptions,
    open,
    options,
    workflow,
}: MemberDetailsSurfaceProps) {
    const isCreating = createState !== undefined;
    const heading = isCreating
        ? "New member"
        : member.title?.trim() || "Untitled member";
    const footer =
        createState !== undefined ? (
            <>
                <Button
                    disabled={createState.submitting}
                    onClick={onClose}
                    tone="quiet"
                >
                    Cancel
                </Button>
                <Button
                    disabled={createState.submitting || !createState.canSubmit}
                    onClick={createState.onSubmit}
                    tone="primary"
                >
                    {createState.submitting ? "Adding…" : "Add member"}
                </Button>
            </>
        ) : onRemove === undefined ? undefined : (
            <Button disabled={disabled} onClick={onRemove} tone="danger">
                <Trash2 aria-hidden="true" size={15} />
                Remove member
            </Button>
        );

    return (
        <DetailsDrawer
            busy={disabled}
            closeLabel="Close member details"
            focusRequest={focusRequest}
            footer={footer}
            heading={heading}
            identity={member.id}
            onClose={onClose}
            open={open}
        >
            <MemberForm
                disabled={disabled}
                issues={issues}
                member={member}
                onEdit={onEditMember}
                onRetryOptions={onRetryOptions}
                options={options}
                titleRequired={isCreating}
                workflow={workflow}
            />
            {createState?.error === null ||
            createState?.error === undefined ? null : (
                <Notice tone="danger" urgent>
                    {createState.error}
                </Notice>
            )}
        </DetailsDrawer>
    );
}
