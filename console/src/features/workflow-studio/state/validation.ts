import type {
    DraftOperation,
    NormalizedMember,
    NormalizedWorkflow,
} from "../../../api/types";
import type {
    StudioValidationIssue,
    StudioValidationTarget,
} from "./contracts";

export function validateLocalWorkflow(
    workflow: NormalizedWorkflow,
): readonly StudioValidationIssue[] {
    const issues: StudioValidationIssue[] = [];
    if (workflow.description.trim() === "") {
        issues.push(
            issue("$.description", "Describe when this team should be used."),
        );
    } else if (workflow.description.length > 1024) {
        issues.push(
            issue(
                "$.description",
                "Description must be 1,024 characters or fewer.",
            ),
        );
    }
    if ((workflow.note?.length ?? 0) > 8192) {
        issues.push(
            issue("$.note", "Shared note must be 8,192 characters or fewer."),
        );
    }
    validateMember(workflow.lead, issues);
    return issues;
}

export function resolveValidationTarget(
    workflow: NormalizedWorkflow,
    validationIssue: StudioValidationIssue,
): StudioValidationTarget | null {
    if (validationIssue.target !== undefined) {
        return validationIssue.target;
    }
    const tokens = parseValidationPath(validationIssue.path);
    if (tokens === null) {
        return null;
    }
    const workflowTarget = workflowFieldTarget(tokens);
    if (workflowTarget !== null) {
        return workflowTarget;
    }
    const memberPath = resolveMemberPath(workflow.lead, tokens);
    return memberPath === null
        ? null
        : memberFieldTarget(memberPath.member.id, memberPath.remaining);
}

export function operationValidationTarget(
    operation: DraftOperation,
    fieldPath: string,
): StudioValidationTarget | null {
    const tokens = parseValidationPath(fieldPath);
    if (tokens === null) {
        return null;
    }
    if (operation.kind === "update_workflow") {
        return workflowFieldTarget(tokens);
    }
    if (operation.kind !== "update_member") {
        return null;
    }
    const patchIndex = tokens.lastIndexOf("patch");
    return memberFieldTarget(
        operation.member_id,
        patchIndex === -1 ? tokens : tokens.slice(patchIndex + 1),
    );
}

export function validationMessageForTarget(
    workflow: NormalizedWorkflow,
    issues: readonly StudioValidationIssue[],
    target: StudioValidationTarget,
): string | null {
    return (
        issues.find((validationIssue) =>
            sameTarget(
                resolveValidationTarget(workflow, validationIssue),
                target,
            ),
        )?.message ?? null
    );
}

function validateMember(
    member: NormalizedMember,
    issues: StudioValidationIssue[],
): void {
    const path = `$.members.${member.id}`;
    for (const field of ["title", "description", "instruction"] as const) {
        if ((member[field]?.length ?? 0) > 16_384) {
            issues.push(
                issue(
                    `${path}.${field}`,
                    `${humanize(field)} must be 16,384 characters or fewer.`,
                ),
            );
        }
    }
    for (const child of member.children ?? []) {
        validateMember(child, issues);
    }
}

function issue(path: string, message: string): StudioValidationIssue {
    return { source: "console", path, message };
}

function workflowFieldTarget(
    tokens: readonly (string | number)[],
): StudioValidationTarget | null {
    if (tokens.includes("lead") || tokens.includes("members")) {
        return null;
    }
    const field = [...tokens]
        .reverse()
        .find((token) => token === "description" || token === "note");
    return typeof field === "string" ? { kind: "workflow", field } : null;
}

function sameTarget(
    left: StudioValidationTarget | null,
    right: StudioValidationTarget,
): boolean {
    if (left === null || left.kind !== right.kind) {
        return false;
    }
    return left.kind === "workflow" && right.kind === "workflow"
        ? left.field === right.field
        : left.kind === "member" &&
              right.kind === "member" &&
              left.memberId === right.memberId &&
              left.field === right.field;
}

function resolveMemberPath(
    lead: NormalizedMember,
    tokens: readonly (string | number)[],
): {
    readonly member: NormalizedMember;
    readonly remaining: readonly string[];
} | null {
    if (tokens[0] === "members" && typeof tokens[1] === "string") {
        const member = findMemberById(lead, tokens[1]);
        return member === null
            ? null
            : {
                  member,
                  remaining: stringTokens(tokens.slice(2)),
              };
    }
    if (tokens[0] !== "lead") {
        return null;
    }
    let member = lead;
    let index = 1;
    while (
        tokens[index] === "children" &&
        typeof tokens[index + 1] === "number"
    ) {
        const child = member.children?.[tokens[index + 1] as number];
        if (child === undefined) {
            return null;
        }
        member = child;
        index += 2;
    }
    return { member, remaining: stringTokens(tokens.slice(index)) };
}

function memberFieldTarget(
    memberId: string,
    tokens: readonly (string | number)[],
): StudioValidationTarget | null {
    const strings = stringTokens(tokens);
    const supportedIndex = strings.findIndex((token) =>
        [
            "title",
            "description",
            "instruction",
            "provider",
            "capabilities",
        ].includes(token),
    );
    const field = strings[supportedIndex];
    if (supportedIndex === -1 || field === undefined) {
        return null;
    }
    const providerDetail = strings[supportedIndex + 1];
    return {
        kind: "member",
        memberId,
        field:
            field === "provider" && providerDetail !== undefined
                ? `provider.${providerDetail}`
                : (field as
                      | "title"
                      | "description"
                      | "instruction"
                      | "provider"
                      | "capabilities"),
    };
}

function parseValidationPath(
    path: string,
): readonly (string | number)[] | null {
    const tokens: (string | number)[] = [];
    const source = path.startsWith("$") ? path.slice(1) : path;
    const pattern = /\.?([A-Za-z_][A-Za-z0-9_-]*)|\[(\d+)\]/gy;
    let offset = 0;
    while (offset < source.length) {
        pattern.lastIndex = offset;
        const match = pattern.exec(source);
        if (match === null || match.index !== offset) {
            return null;
        }
        const numeric = match[2];
        tokens.push(numeric === undefined ? (match[1] ?? "") : Number(numeric));
        offset = pattern.lastIndex;
    }
    return tokens;
}

function stringTokens(tokens: readonly (string | number)[]): readonly string[] {
    return tokens.filter((token): token is string => typeof token === "string");
}

function findMemberById(
    member: NormalizedMember,
    memberId: string,
): NormalizedMember | null {
    if (member.id === memberId) {
        return member;
    }
    for (const child of member.children ?? []) {
        const found = findMemberById(child, memberId);
        if (found !== null) {
            return found;
        }
    }
    return null;
}

function humanize(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1);
}
