import { useId } from "react";

import type { NormalizedMember, NormalizedWorkflow } from "../../../api/types";
import { FormField } from "../../../components/ui";
import type {
    MemberEdit,
    StudioValidationIssue,
    WorkflowAuthoringOptionsState,
} from "../state/contracts";
import { validationMessageForTarget } from "../state/validation";
import { ProviderAndAccessFields } from "./ProviderAndAccessFields";

export interface MemberFormProps {
    readonly disabled: boolean;
    readonly issues: readonly StudioValidationIssue[];
    readonly member: NormalizedMember;
    readonly onEdit: (patch: MemberEdit) => void;
    readonly onRetryOptions: () => void;
    readonly options: WorkflowAuthoringOptionsState;
    readonly workflow: NormalizedWorkflow;
}

export function MemberForm({
    disabled,
    issues,
    member,
    onEdit,
    onRetryOptions,
    options,
    workflow,
}: MemberFormProps) {
    const prefix = useId();
    const memberIssues = memberFieldIssues(workflow, issues, member.id);

    return (
        <section aria-labelledby={`${prefix}-heading`} className="studio-form">
            <header>
                <p className="studio-form__eyebrow">Member</p>
                <h2 id={`${prefix}-heading`}>
                    {member.title?.trim() === "" || member.title === undefined
                        ? "Unnamed teammate"
                        : member.title}
                </h2>
                <p>
                    A Member is one teammate. Its responsibility comes from the
                    instruction you give it.
                </p>
            </header>
            <MemberProseFields
                disabled={disabled}
                issues={memberIssues}
                member={member}
                onEdit={onEdit}
                prefix={prefix}
            />
            <ProviderAndAccessFields
                disabled={disabled}
                issues={memberIssues}
                member={member}
                onEdit={onEdit}
                onRetryOptions={onRetryOptions}
                options={options}
                prefix={prefix}
            />
        </section>
    );
}

interface MemberProseFieldsProps {
    readonly disabled: boolean;
    readonly issues: Readonly<Record<string, string>>;
    readonly member: NormalizedMember;
    readonly onEdit: (patch: MemberEdit) => void;
    readonly prefix: string;
}

function MemberProseFields({
    disabled,
    issues,
    member,
    onEdit,
    prefix,
}: MemberProseFieldsProps) {
    return (
        <>
            <FormField
                error={fieldIssue(issues, "title")}
                hint="A short name people can recognize."
                id={`${prefix}-title`}
                label="Name"
                optional
            >
                <input
                    data-field-path={`$.members.${member.id}.title`}
                    disabled={disabled}
                    maxLength={16_384}
                    onChange={(event) =>
                        onEdit({ title: optionalText(event.target.value) })
                    }
                    value={member.title ?? ""}
                />
            </FormField>
            <FormField
                error={fieldIssue(issues, "description")}
                hint="What responsibility does this teammate own?"
                id={`${prefix}-description`}
                label="Responsibility"
                optional
            >
                <textarea
                    data-field-path={`$.members.${member.id}.description`}
                    disabled={disabled}
                    maxLength={16_384}
                    onChange={(event) =>
                        onEdit({
                            description: optionalText(event.target.value),
                        })
                    }
                    value={member.description ?? ""}
                />
            </FormField>
            <FormField
                error={fieldIssue(issues, "instruction")}
                hint="Specific task guidance for this Member. Banksia adds shared teamwork guidance automatically."
                id={`${prefix}-instruction`}
                label="Instruction"
                optional
            >
                <textarea
                    data-field-path={`$.members.${member.id}.instruction`}
                    disabled={disabled}
                    maxLength={16_384}
                    onChange={(event) =>
                        onEdit({
                            instruction: optionalText(event.target.value),
                        })
                    }
                    value={member.instruction ?? ""}
                />
            </FormField>
        </>
    );
}

function optionalText(value: string): string | null {
    return value === "" ? null : value;
}

function memberFieldIssues(
    workflow: NormalizedWorkflow,
    issues: readonly StudioValidationIssue[],
    memberId: string,
): Readonly<Record<string, string>> {
    const fields = [
        "title",
        "description",
        "instruction",
        "provider",
        "provider.model",
        "provider.effort",
        "provider.sandbox",
        "capabilities",
    ] as const;
    return Object.fromEntries(
        fields.flatMap((field) => {
            const message = validationMessageForTarget(workflow, issues, {
                kind: "member",
                memberId,
                field,
            });
            return message === null ? [] : [[field, message]];
        }),
    );
}

function fieldIssue(
    issues: Readonly<Record<string, string>>,
    field: string,
): string | null {
    return issues[field] ?? null;
}
