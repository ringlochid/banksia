import type {
    NormalizedMember,
    ProviderSandbox,
    ProviderSelection,
    WorkflowAuthoringOptions,
} from "../../../api/types";
import { Button, FormField, Notice } from "../../../components/ui";
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
                    <p className="studio-form__explanation" role="status">
                        Loading provider and access choices…
                    </p>
                ) : options.kind === "error" ? (
                    <Notice tone="warning">
                        <p>{options.message}</p>
                        <Button onClick={onRetryOptions}>
                            Try loading choices again
                        </Button>
                    </Notice>
                ) : (
                    <p className="studio-form__explanation">
                        Leave these settings unchanged to use the installation
                        default. Asking you questions and running managed
                        commands are denied unless you explicitly allow them
                        here; each teammate needs its own access settings.
                    </p>
                )}
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
    const providerKinds = [
        ...new Set([
            ...(options?.provider_kinds ?? []),
            ...(provider === undefined || provider === null
                ? []
                : [provider.kind]),
        ]),
    ];

    return (
        <>
            <FormField
                error={fieldIssue(issues, "provider")}
                hint={defaultProviderHint(options, isOptionsLoading)}
                id={`${prefix}-provider`}
                label="Provider"
            >
                <select
                    data-field-path={`$.members.${member.id}.provider`}
                    disabled={disabled}
                    onChange={(event) => {
                        onEdit({
                            provider: providerForKind(event.target.value),
                        });
                    }}
                    value={providerKind}
                >
                    <option value="default">Installation default</option>
                    {providerKinds.map((kind) => (
                        <option key={kind} value={kind}>
                            {providerLabel(kind)}
                        </option>
                    ))}
                </select>
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
                <p className="studio-form__explanation">
                    OpenClaw owns its sandbox and workspace access outside
                    Banksia. Make the selected workspace available in
                    OpenClaw&apos;s configuration before using this team.
                </p>
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
            ...(provider.effort === undefined ? [] : [provider.effort]),
        ]),
    ];
    const sandboxes = uniqueSandboxes([
        ...(options?.managed_sandbox_options ?? []),
        ...(provider.sandbox === undefined ? [] : [provider.sandbox]),
    ]);

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
            <input
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
            <select
                data-field-path={`$.members.${memberId}.provider.effort`}
                disabled={disabled}
                onChange={(event) =>
                    onEdit({
                        provider: withProviderValue(
                            provider,
                            "effort",
                            optionalValue(event.target.value),
                        ),
                    })
                }
                value={provider.effort ?? ""}
            >
                <option value="">Provider default</option>
                {efforts.map((effort) => (
                    <option key={effort} value={effort}>
                        {providerLabel(effort)}
                    </option>
                ))}
            </select>
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
            <select
                data-field-path={`$.members.${memberId}.provider.sandbox`}
                disabled={disabled}
                onChange={(event) =>
                    onEdit({
                        provider: withProviderValue(
                            provider,
                            "sandbox",
                            sandboxFromValue(event.target.value),
                        ),
                    })
                }
                value={sandboxValue(provider.sandbox)}
            >
                <option value="">Full access · network allow (default)</option>
                {sandboxes.map((sandbox) => (
                    <option
                        key={`${sandbox.mode}:${sandbox.network}`}
                        value={`${sandbox.mode}:${sandbox.network}`}
                    >
                        {sandboxLabel(sandbox)}
                    </option>
                ))}
            </select>
        </FormField>
    );
}

function providerForKind(kind: string): ProviderSelection | null {
    switch (kind) {
        case "codex":
            return { kind: "codex" };
        case "claude":
            return { kind: "claude" };
        case "openclaw":
            return { kind: "openclaw" };
        default:
            return null;
    }
}

function withProviderValue(
    provider: Extract<ProviderSelection, { kind: "codex" | "claude" }>,
    field: "model" | "effort" | "sandbox",
    value: string | ProviderSandbox | undefined,
): ProviderSelection {
    const next: Record<string, unknown> = { ...provider };
    if (value === undefined) {
        delete next[field];
    } else {
        next[field] = value;
    }
    return next as ProviderSelection;
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
    const mode = sandbox.mode.replaceAll("_", " ");
    return `${providerLabel(mode)} · network ${sandbox.network}`;
}

function uniqueSandboxes(
    sandboxes: readonly ProviderSandbox[],
): readonly ProviderSandbox[] {
    return [
        ...new Map(
            sandboxes.map((sandbox) => [
                `${sandbox.mode}:${sandbox.network}`,
                sandbox,
            ]),
        ).values(),
    ];
}

function defaultProviderHint(
    options: WorkflowAuthoringOptions | null,
    isLoading: boolean,
): string {
    if (options === null) {
        return isLoading
            ? "Provider choices are loading. The current selection is preserved."
            : "Provider choices could not be loaded. The current selection is preserved.";
    }
    const provider = options.default_provider;
    if (provider === null || provider === undefined) {
        return "No installation default is currently reported. Configure a provider before running this team.";
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
    ].filter((detail): detail is string => detail !== null);
    return `Installation default: ${details.join(" · ")}.`;
}

function optionalValue(value: string): string | undefined {
    return value === "" ? undefined : value;
}

function providerLabel(value: string): string {
    if (value === "openclaw") {
        return "OpenClaw";
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
