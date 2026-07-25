import { useId } from "react";

import { FormField } from "../../../components/ui";
import type { NormalizedWorkflow } from "../../../api/types";
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
        <section aria-labelledby={`${prefix}-heading`} className="studio-form">
            <header>
                <p className="studio-form__eyebrow">Workflow</p>
                <h2 id={`${prefix}-heading`}>Team purpose</h2>
                <p>
                    Help people recognize when this reusable team is the right
                    fit.
                </p>
            </header>
            <FormField
                error={descriptionError}
                hint="One plain-language sentence. This appears in the Workflow library."
                id={`${prefix}-description`}
                label="Use this team when…"
            >
                <textarea
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
            <details className="studio-disclosure">
                <summary>Shared note</summary>
                <div className="studio-disclosure__body">
                    <FormField
                        error={noteError}
                        hint="Optional shared context for this team, such as goals, preferences, or important background."
                        id={`${prefix}-note`}
                        label="Note"
                        optional
                    >
                        <textarea
                            data-field-path="$.note"
                            disabled={disabled}
                            maxLength={8192}
                            onChange={(event) => {
                                onEdit({ note: event.target.value || null });
                            }}
                            value={workflow.note ?? ""}
                        />
                    </FormField>
                </div>
            </details>
        </section>
    );
}
