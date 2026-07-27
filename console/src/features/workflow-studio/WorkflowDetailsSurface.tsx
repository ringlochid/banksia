import type { NormalizedWorkflow } from "../../api/types";
import { DetailsDrawer } from "./DetailsDrawer";
import { WorkflowForm } from "./forms/WorkflowForm";
import type { StudioValidationIssue, WorkflowEdit } from "./state/contracts";

export interface WorkflowDetailsSurfaceProps {
    readonly disabled: boolean;
    readonly focusRequest: number;
    readonly issues: readonly StudioValidationIssue[];
    readonly onClose: () => void;
    readonly onEdit: (patch: WorkflowEdit) => void;
    readonly open: boolean;
    readonly workflow: NormalizedWorkflow;
}

export function WorkflowDetailsSurface({
    disabled,
    focusRequest,
    issues,
    onClose,
    onEdit,
    open,
    workflow,
}: WorkflowDetailsSurfaceProps) {
    return (
        <DetailsDrawer
            busy={disabled}
            closeLabel="Close Workflow settings"
            focusRequest={focusRequest}
            heading="Workflow settings"
            identity={workflow.id}
            initialFocusSelector='[data-field-path="$.description"]'
            onClose={onClose}
            open={open}
        >
            <WorkflowForm
                disabled={disabled}
                issues={issues}
                onEdit={onEdit}
                workflow={workflow}
            />
        </DetailsDrawer>
    );
}
