import type { NormalizedMember, NormalizedWorkflow } from "../../../api/types";
import { FormField, Input, Textarea } from "../../../components/ui";
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
    readonly titleRequired?: boolean;
    readonly workflow: NormalizedWorkflow;
}

export function MemberForm({
    disabled,
    issues,
    member,
    onEdit,
    onRetryOptions,
    options,
    titleRequired = false,
    workflow,
}: MemberFormProps) {
    const prefix = `member-${member.id}`;
    const memberIssues = memberFieldIssues(workflow, issues, member.id);

    return (
        <section aria-label="Member settings" className="studio-form">
            <MemberProseFields
                disabled={disabled}
                issues={memberIssues}
                member={member}
                onEdit={onEdit}
                prefix={prefix}
                titleRequired={titleRequired}
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
    readonly titleRequired: boolean;
}

function MemberProseFields({
    disabled,
    issues,
    member,
    onEdit,
    prefix,
    titleRequired,
}: MemberProseFieldsProps) {
    return (
        <>
            <FormField
                error={fieldIssue(issues, "title")}
                hint="Shown on the team canvas."
                id={`${prefix}-title`}
                label="Name"
                optional={!titleRequired}
            >
                <Input
                    data-field-path={`$.members.${member.id}.title`}
                    disabled={disabled}
                    maxLength={16_384}
                    onChange={(event) =>
                        onEdit({ title: optionalText(event.target.value) })
                    }
                    required={titleRequired}
                    value={member.title ?? ""}
                />
            </FormField>
            <FormField
                error={fieldIssue(issues, "description")}
                hint="The part of the work this member owns."
                id={`${prefix}-description`}
                label="Responsibility"
                optional
            >
                <Textarea
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
                hint="Directions used whenever this member works."
                id={`${prefix}-instruction`}
                label="Instruction"
                optional
            >
                <Textarea
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
