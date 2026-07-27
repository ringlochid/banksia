import { useId } from "react";

import type { NormalizedWorkflow } from "../../../api/types";
import { FormField, Textarea } from "../../../components/ui";
import type { StudioValidationIssue, WorkflowEdit } from "../state/contracts";
import { validationMessageForTarget } from "../state/validation";

export interface WorkflowFormProps {
    readonly disabled: boolean;
    readonly issues: readonly StudioValidationIssue[];
    readonly onEdit: (patch: WorkflowEdit) => void;
    readonly workflow: NormalizedWorkflow;
}

export function WorkflowForm({
    disabled,
    issues,
    onEdit,
    workflow,
}: WorkflowFormProps) {
    const prefix = useId();
    const descriptionError = validationMessageForTarget(workflow, issues, {
        kind: "workflow",
        field: "description",
    });
    const noteError = validationMessageForTarget(workflow, issues, {
        kind: "workflow",
        field: "note",
    });

    return (
        <section aria-label="Workflow settings" className="studio-form">
            <FormField
                error={descriptionError}
                id={`${prefix}-description`}
                label="Purpose"
            >
                <Textarea
                    data-field-path="$.description"
                    disabled={disabled}
                    maxLength={1024}
                    onChange={(event) => {
                        onEdit({ description: event.target.value });
                    }}
                    required
                    value={workflow.description}
                />
            </FormField>
            <FormField
                error={noteError}
                id={`${prefix}-note`}
                label="Shared note"
                optional
            >
                <Textarea
                    data-field-path="$.note"
                    disabled={disabled}
                    maxLength={8192}
                    onChange={(event) => {
                        onEdit({ note: event.target.value || null });
                    }}
                    value={workflow.note ?? ""}
                />
            </FormField>
        </section>
    );
}
