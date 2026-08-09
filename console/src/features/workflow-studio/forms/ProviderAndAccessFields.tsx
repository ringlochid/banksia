import { LoaderCircle } from "lucide-react";

import type {
    AuthoredProviderSelection,
    NormalizedMember,
    ProviderSandbox,
    ProviderSelection,
    WorkflowAuthoringOptions,
} from "../../../api/types";
import {
    Button,
    FormField,
    Input,
    Notice,
    Prose,
    Select,
    type SelectOption,
} from "../../../components/ui";
import type {
    MemberEdit,
    WorkflowAuthoringOptionsState,
} from "../state/contracts";
import { MemberCapabilityFields } from "./MemberCapabilityFields";

export interface ProviderAndAccessFieldsProps {
    readonly disabled: boolean;
    readonly issues: Readonly<Record<string, string>>;
    readonly member: NormalizedMember;
    readonly onEdit: (patch: MemberEdit) => void;
    readonly onRetryOptions: () => void;
    readonly options: WorkflowAuthoringOptionsState;
    readonly prefix: string;
}

export function ProviderAndAccessFields({
    disabled,
    issues,
    member,
    onEdit,
    onRetryOptions,
    options,
    prefix,
}: ProviderAndAccessFieldsProps) {
    const availableOptions = options.kind === "ready" ? options.options : null;
    const controlsDisabled = disabled || options.kind !== "ready";

    return (
        <details className="studio-disclosure">
            <summary>Provider and access</summary>
            <div className="studio-disclosure__body">
                {options.kind === "loading" ? (
                    <div className="studio-form__status" role="status">
                        <LoaderCircle
                            aria-hidden="true"
                            className="ui-spin"
                            size={16}
                        />
                        Loading choices
                    </div>
                ) : options.kind === "error" ? (
                    <Notice tone="warning">
                        <Prose>{options.message}</Prose>
                        <Button onClick={onRetryOptions}>Try again</Button>
                    </Notice>
                ) : null}
                <ProviderFields
                    disabled={controlsDisabled}
                    issues={issues}
                    isOptionsLoading={options.kind === "loading"}
                    member={member}
                    onEdit={onEdit}
                    options={availableOptions}
                    prefix={prefix}
                />
                <MemberCapabilityFields
                    disabled={controlsDisabled}
                    error={fieldIssue(issues, "capabilities")}
                    member={member}
                    onEdit={onEdit}
                    options={availableOptions}
                />
            </div>
        </details>
    );
}

interface ProviderFieldsProps {
    readonly disabled: boolean;
    readonly issues: Readonly<Record<string, string>>;
    readonly isOptionsLoading: boolean;
    readonly member: NormalizedMember;
    readonly onEdit: (patch: MemberEdit) => void;
    readonly options: WorkflowAuthoringOptions | null;
    readonly prefix: string;
}

function ProviderFields({
    disabled,
    issues,
    isOptionsLoading,
    member,
    onEdit,
    options,
    prefix,
}: ProviderFieldsProps) {
    const provider = member.provider;
    const providerKind = provider?.kind ?? "default";
    const managedProvider =
        provider?.kind === "codex" || provider?.kind === "claude";
    const providerKinds = [...new Set(options?.provider_kinds ?? [])];

    return (
        <>
            <FormField
                error={fieldIssue(issues, "provider")}
                hint={defaultProviderHint(options, isOptionsLoading)}
                id={`${prefix}-provider`}
                label="Provider"
            >
                <Select
                    dataFieldPath={`$.members.${member.id}.provider`}
                    disabled={disabled}
                    onValueChange={(value) => {
                        onEdit({
                            provider: providerForKind(value),
                        });
                    }}
                    options={providerOptions(
                        providerKinds,
                        provider?.kind === "openclaw",
                    )}
                    value={providerKind}
                />
            </FormField>
            {managedProvider ? (
                <ManagedProviderFields
                    disabled={disabled}
                    issues={issues}
                    memberId={member.id}
                    onEdit={onEdit}
                    options={options}
                    prefix={prefix}
                    provider={provider}
                />
            ) : null}
            {provider?.kind === "openclaw" ? (
                <Notice tone="warning">
                    <Prose>
                        OpenClaw is retired. Choose Codex, Claude, or the
                        installation default before publishing or running this
                        Workflow.
                    </Prose>
                </Notice>
            ) : null}
        </>
    );
}

interface ManagedProviderFieldsProps {
    readonly disabled: boolean;
    readonly issues: Readonly<Record<string, string>>;
    readonly memberId: string;
    readonly onEdit: (patch: MemberEdit) => void;
    readonly options: WorkflowAuthoringOptions | null;
    readonly prefix: string;
    readonly provider: Extract<ProviderSelection, { kind: "codex" | "claude" }>;
}

function ManagedProviderFields({
    disabled,
    issues,
    memberId,
    onEdit,
    options,
    prefix,
    provider,
}: ManagedProviderFieldsProps) {
    const availableEfforts =
        provider.kind === "codex"
            ? options?.codex_efforts
            : options?.claude_efforts;
    const efforts = [
        ...new Set([
            ...(availableEfforts ?? []),
            ...(provider.effort === undefined || provider.effort === null
                ? []
                : [provider.effort]),
        ]),
    ];
    const sandboxes = uniqueSandboxes([
        ...(options?.managed_sandbox_options ?? []),
        ...(provider.sandbox === undefined || provider.sandbox === null
            ? []
            : [provider.sandbox]),
    ]);
    const extensionModes = [
        ...new Set([
            ...(options?.managed_extension_modes ?? []),
            ...(provider.extension_mode === undefined ||
            provider.extension_mode === null
                ? []
                : [provider.extension_mode]),
        ]),
    ];

    return (
        <>
            <ManagedModelField
                disabled={disabled}
                error={fieldIssue(issues, "provider.model")}
                memberId={memberId}
                onEdit={onEdit}
                prefix={prefix}
                provider={provider}
            />
            <ManagedEffortField
                disabled={disabled}
                efforts={efforts}
                error={fieldIssue(issues, "provider.effort")}
                memberId={memberId}
                onEdit={onEdit}
                prefix={prefix}
                provider={provider}
            />
            <ManagedSandboxField
                disabled={disabled}
                error={fieldIssue(issues, "provider.sandbox")}
                memberId={memberId}
                onEdit={onEdit}
                prefix={prefix}
                provider={provider}
                sandboxes={sandboxes}
            />
            <ManagedExtensionModeField
                disabled={disabled}
                error={fieldIssue(issues, "provider.extension_mode")}
                extensionModes={extensionModes}
                memberId={memberId}
                onEdit={onEdit}
                prefix={prefix}
                provider={provider}
            />
        </>
    );
}

interface ManagedFieldProps {
    readonly disabled: boolean;
    readonly error: string | null;
    readonly memberId: string;
    readonly onEdit: (patch: MemberEdit) => void;
    readonly prefix: string;
    readonly provider: Extract<ProviderSelection, { kind: "codex" | "claude" }>;
}

function ManagedModelField({
    disabled,
    error,
    memberId,
    onEdit,
    prefix,
    provider,
}: ManagedFieldProps) {
    return (
        <FormField
            error={error}
            hint="Leave blank to use the provider's configured model."
            id={`${prefix}-model`}
            label="Model"
            optional
        >
            <Input
                data-field-path={`$.members.${memberId}.provider.model`}
                disabled={disabled}
                onChange={(event) =>
                    onEdit({
                        provider: withProviderValue(
                            provider,
                            "model",
                            optionalValue(event.target.value),
                        ),
                    })
                }
                value={provider.model ?? ""}
            />
        </FormField>
    );
}

interface ManagedEffortFieldProps extends ManagedFieldProps {
    readonly efforts: readonly string[];
}

function ManagedEffortField({
    disabled,
    efforts,
    error,
    memberId,
    onEdit,
    prefix,
    provider,
}: ManagedEffortFieldProps) {
    return (
        <FormField
            error={error}
            hint="Leave unchanged to use the provider's configured reasoning effort."
            id={`${prefix}-effort`}
            label="Reasoning effort"
            optional
        >
            <Select
                dataFieldPath={`$.members.${memberId}.provider.effort`}
                disabled={disabled}
                onValueChange={(value) =>
                    onEdit({
                        provider: withProviderValue(
                            provider,
                            "effort",
                            value === "default" ? undefined : value,
                        ),
                    })
                }
                options={[
                    { value: "default", label: "Provider default" },
                    ...efforts.map((effort) => ({
                        value: effort,
                        label: providerLabel(effort),
                    })),
                ]}
                value={provider.effort ?? "default"}
            />
        </FormField>
    );
}

interface ManagedSandboxFieldProps extends ManagedFieldProps {
    readonly sandboxes: readonly ProviderSandbox[];
}

function ManagedSandboxField({
    disabled,
    error,
    memberId,
    onEdit,
    prefix,
    provider,
    sandboxes,
}: ManagedSandboxFieldProps) {
    return (
        <FormField
            error={error}
            hint="Workspace write permits file changes. Network access permits external connections."
            id={`${prefix}-sandbox`}
            label="Sandbox and network"
            optional
        >
            <Select
                dataFieldPath={`$.members.${memberId}.provider.sandbox`}
                disabled={disabled}
                onValueChange={(value) =>
                    onEdit({
                        provider: withProviderValue(
                            provider,
                            "sandbox",
                            sandboxFromValue(value === "default" ? "" : value),
                        ),
                    })
                }
                options={[
                    { value: "default", label: "Provider default" },
                    ...sandboxes.map((sandbox) => ({
                        value: `${sandbox.mode}:${sandbox.network}`,
                        label: sandboxLabel(sandbox),
                    })),
                ]}
                value={
                    provider.sandbox === undefined || provider.sandbox === null
                        ? "default"
                        : sandboxValue(provider.sandbox)
                }
            />
        </FormField>
    );
}

interface ManagedExtensionModeFieldProps extends ManagedFieldProps {
    readonly extensionModes: readonly string[];
}

function ManagedExtensionModeField({
    disabled,
    error,
    extensionModes,
    memberId,
    onEdit,
    prefix,
    provider,
}: ManagedExtensionModeFieldProps) {
    return (
        <FormField
            error={error}
            hint="Inherit uses enabled user and project Skills plus configured MCP servers for trusted full-access work. Restricted access is isolated automatically."
            id={`${prefix}-extension-mode`}
            label="Skills and MCP"
            optional
        >
            <Select
                dataFieldPath={`$.members.${memberId}.provider.extension_mode`}
                disabled={disabled}
                onValueChange={(value) =>
                    onEdit({
                        provider: withProviderValue(
                            provider,
                            "extension_mode",
                            value === "default" ? undefined : value,
                        ),
                    })
                }
                options={[
                    { value: "default", label: "Provider default" },
                    ...extensionModes.map((mode) => ({
                        value: mode,
                        label:
                            mode === "inherit"
                                ? "Use provider Skills and MCP"
                                : "Banksia only",
                    })),
                ]}
                value={provider.extension_mode ?? "default"}
            />
        </FormField>
    );
}

function providerForKind(kind: string): AuthoredProviderSelection | null {
    switch (kind) {
        case "codex":
            return { kind: "codex" };
        case "claude":
            return { kind: "claude" };
        default:
            return null;
    }
}

function providerOptions(
    kinds: readonly string[],
    includeRetiredSelection: boolean,
): readonly SelectOption[] {
    const descriptions: Readonly<Record<string, string>> = {
        codex: "Use the configured Codex provider.",
        claude: "Use the configured Claude provider.",
    };
    return [
        {
            value: "default",
            label: "Installation default",
            hint: "Use the provider configured for Banksia.",
        },
        ...(includeRetiredSelection
            ? [
                  {
                      value: "openclaw",
                      label: "OpenClaw (retired)",
                      hint: "Choose an active provider to repair this Member.",
                      disabled: true,
                  },
              ]
            : []),
        ...kinds.map((kind) => ({
            value: kind,
            label: providerLabel(kind),
            ...(descriptions[kind] === undefined
                ? {}
                : { hint: descriptions[kind] }),
        })),
    ];
}

function withProviderValue(
    provider: Extract<ProviderSelection, { kind: "codex" | "claude" }>,
    field: "model" | "effort" | "sandbox" | "extension_mode",
    value: string | ProviderSandbox | undefined,
): AuthoredProviderSelection {
    const next: Record<string, unknown> = { kind: provider.kind };
    for (const providerField of [
        "model",
        "effort",
        "sandbox",
        "extension_mode",
    ] as const) {
        const currentValue = provider[providerField];
        if (currentValue !== undefined && currentValue !== null) {
            next[providerField] = currentValue;
        }
    }
    if (value === undefined) {
        delete next[field];
    } else {
        next[field] = value;
    }
    return next as AuthoredProviderSelection;
}

function sandboxFromValue(value: string): ProviderSandbox | undefined {
    if (value === "") {
        return undefined;
    }
    const [mode, network] = value.split(":");
    return { mode, network } as ProviderSandbox;
}

function sandboxValue(sandbox: ProviderSandbox | undefined): string {
    return sandbox === undefined ? "" : `${sandbox.mode}:${sandbox.network}`;
}

function sandboxLabel(sandbox: ProviderSandbox): string {
    return `${providerLabel(sandbox.mode)} · Network ${sandbox.network}`;
}

function uniqueSandboxes(
    sandboxes: readonly (ProviderSandbox | null | undefined)[],
): readonly ProviderSandbox[] {
    return [
        ...new Map(
            sandboxes
                .filter(isProviderSandbox)
                .map(
                    (sandbox) =>
                        [
                            `${sandbox.mode}:${sandbox.network}`,
                            sandbox,
                        ] as const,
                ),
        ).values(),
    ];
}

function isProviderSandbox(
    sandbox: ProviderSandbox | null | undefined,
): sandbox is ProviderSandbox {
    return sandbox !== null && sandbox !== undefined;
}

function defaultProviderHint(
    options: WorkflowAuthoringOptions | null,
    isLoading: boolean,
): string {
    if (options === null) {
        return isLoading
            ? "Current selection is preserved."
            : "Choices unavailable. Current selection is preserved.";
    }
    const provider = options.default_provider;
    if (provider === null || provider === undefined) {
        return "No installation default configured.";
    }
    const details = [
        providerLabel(provider.kind),
        provider.model ?? null,
        provider.effort === null || provider.effort === undefined
            ? null
            : `${providerLabel(provider.effort)} effort`,
        provider.sandbox === null || provider.sandbox === undefined
            ? null
            : sandboxLabel(provider.sandbox),
        provider.extension_mode === null ||
        provider.extension_mode === undefined
            ? null
            : provider.extension_mode === "inherit"
              ? "Provider Skills and MCP"
              : "Banksia-only extensions",
    ].filter((detail): detail is string => detail !== null);
    return `Default: ${details.join(" · ")}`;
}

function optionalValue(value: string): string | undefined {
    return value === "" ? undefined : value;
}

function providerLabel(value: string): string {
    if (value === "openclaw") {
        return "OpenClaw (retired)";
    }
    return value
        .split(/[_-]/)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}

function fieldIssue(
    issues: Readonly<Record<string, string>>,
    field: string,
): string | null {
    return issues[field] ?? null;
}
