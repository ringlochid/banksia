import type {
    MemberCapabilities,
    NormalizedMember,
    WorkflowAuthoringOptions,
} from "../../../api/types";
import { useId } from "react";
import type { MemberEdit } from "../state/contracts";

export interface MemberCapabilityFieldsProps {
    readonly disabled: boolean;
    readonly error: string | null;
    readonly member: NormalizedMember;
    readonly onEdit: (patch: MemberEdit) => void;
    readonly options: WorkflowAuthoringOptions | null;
}

export function MemberCapabilityFields({
    disabled,
    error,
    member,
    onEdit,
    options,
}: MemberCapabilityFieldsProps) {
    const errorId = useId();
    const capabilities = member.capabilities;
    const humanKinds = [
        ...new Set([
            ...(options?.human_request_kinds ?? []),
            ...(capabilities?.human_request ?? []),
        ]),
    ];
    const commandRunVisible =
        options?.command_run_values.includes("allow") === true ||
        capabilities?.command_run === "allow";

    return (
        <fieldset
            aria-describedby={error === null ? undefined : errorId}
            aria-invalid={error === null ? undefined : true}
            className="studio-capabilities"
            data-field-path={`$.members.${member.id}.capabilities`}
            disabled={disabled}
            tabIndex={error === null ? undefined : -1}
        >
            <legend>Allowed actions</legend>
            <p>
                Nothing is allowed by default. Choose only what this Member
                needs.
            </p>
            {humanKinds.map((kind) => (
                <label key={kind}>
                    <input
                        checked={
                            capabilities?.human_request?.includes(
                                kind as
                                    | "input"
                                    | "direction"
                                    | "approval"
                                    | "review",
                            ) ?? false
                        }
                        onChange={(event) => {
                            onEdit({
                                capabilities: toggleHumanRequest(
                                    capabilities,
                                    kind,
                                    event.target.checked,
                                ),
                            });
                        }}
                        type="checkbox"
                    />
                    Allow this teammate to ask you for {humanRequestLabel(kind)}
                </label>
            ))}
            {commandRunVisible ? (
                <label>
                    <input
                        checked={capabilities?.command_run === "allow"}
                        onChange={(event) => {
                            onEdit({
                                capabilities: toggleCommandRun(
                                    capabilities,
                                    event.target.checked,
                                ),
                            });
                        }}
                        type="checkbox"
                    />
                    Allow this teammate to run a managed command
                </label>
            ) : null}
            {error === null ? null : (
                <span className="ui-field__error" id={errorId}>
                    {error}
                </span>
            )}
        </fieldset>
    );
}

function toggleHumanRequest(
    current: MemberCapabilities | undefined,
    kind: string,
    enabled: boolean,
): MemberCapabilities | null {
    const selected = new Set(current?.human_request ?? []);
    const typedKind = kind as "input" | "direction" | "approval" | "review";
    if (enabled) {
        selected.add(typedKind);
    } else {
        selected.delete(typedKind);
    }
    const next = normalizedCapabilities(current);
    if (selected.size === 0) {
        delete next.human_request;
    } else {
        next.human_request = [...selected];
    }
    return compactCapabilities(next);
}

function toggleCommandRun(
    current: MemberCapabilities | undefined,
    enabled: boolean,
): MemberCapabilities | null {
    const next = normalizedCapabilities(current);
    if (enabled) {
        next.command_run = "allow";
    } else {
        delete next.command_run;
    }
    return compactCapabilities(next);
}

function compactCapabilities(
    value: MemberCapabilities,
): MemberCapabilities | null {
    return value.command_run === undefined &&
        (value.human_request === undefined || value.human_request.length === 0)
        ? null
        : value;
}

function normalizedCapabilities(
    value: MemberCapabilities | undefined,
): MemberCapabilities {
    const normalized: MemberCapabilities = {};
    if ((value?.human_request?.length ?? 0) > 0) {
        normalized.human_request = [...(value?.human_request ?? [])];
    }
    if (value?.command_run === "allow") {
        normalized.command_run = "allow";
    }
    return normalized;
}

function humanRequestLabel(kind: string): string {
    switch (kind) {
        case "input":
            return "input";
        case "direction":
            return "direction";
        case "approval":
            return "approval";
        case "review":
            return "a review";
        default:
            return kind;
    }
}
