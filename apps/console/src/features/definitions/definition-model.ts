import type { components } from "../../api/generated/openapi";
import { mapDefinitionSummary, type DefinitionSummary } from "../../api/view-models";

export type DefinitionKind = components["schemas"]["DefinitionKind"];
export type DefinitionListKind = "policies" | "roles" | "workflows";
export type DefinitionListSort = components["schemas"]["DefinitionListSort"];
export type NodeKind = components["schemas"]["NodeKind"];
export type ProviderKind = components["schemas"]["ProviderKind"];
export type DefinitionSummaryRead = components["schemas"]["DefinitionSummaryRead"];
export type DefinitionRevisionDetailResponse =
    components["schemas"]["DefinitionRevisionDetailResponse"];
export type DefinitionRevisionHistoryEntry =
    components["schemas"]["DefinitionRevisionHistoryEntry"];
export type BudgetSpec = components["schemas"]["BudgetSpec"];
export type WorkflowRootDefinition = components["schemas"]["RootNodeDefinition-Output"];
export type WorkflowNodeDefinition = components["schemas"]["NodeDefinitionInput-Output"];

type RoleContent = components["schemas"]["RoleDefinitionInput"];
type PolicyContent = components["schemas"]["PolicyDefinitionInput-Output"];
type WorkflowContent = components["schemas"]["WorkflowDefinitionInput-Output"];

export interface DefinitionKindOption {
    readonly label: string;
    readonly listKind: DefinitionListKind;
    readonly singularKind: DefinitionKind;
}

export interface DefinitionRow extends DefinitionSummary {
    readonly compatibilityLabels: readonly string[];
    readonly kind: DefinitionKind;
}

export interface DefinitionVersionRow {
    readonly recordedBy: string | null;
    readonly revisionNo: number;
    readonly updatedAt: string;
}

export interface WorkflowNodeSummary {
    readonly childCount: number;
    readonly description: string;
    readonly depth: number;
    readonly nodeKey: string;
    readonly policyId: string;
    readonly producedSlots: readonly string[];
    readonly providerKind: ProviderKind | null;
    readonly roleId: string;
    readonly title: string | null;
}

export interface WorkflowStats {
    readonly childCount: number;
    readonly leafRoleCount: number;
    readonly producedArtifactCount: number;
}

export interface DefinitionDetailBase {
    readonly description: string;
    readonly key: string;
    readonly kind: DefinitionKind;
    readonly recordedBy: string | null;
    readonly revisionNo: number;
    readonly updatedAt: string;
}

export interface RoleDefinitionDetail extends DefinitionDetailBase {
    readonly allowedNodeKinds: readonly NodeKind[];
    readonly instruction: string | null;
    readonly kind: "role";
}

export interface PolicyDefinitionDetail extends DefinitionDetailBase {
    readonly appliesTo: readonly NodeKind[];
    readonly budgetSpec: BudgetSpec | null;
    readonly capabilities: PolicyCapabilitySummary;
    readonly instruction: string | null;
    readonly kind: "policy";
}

export interface PolicyCapabilityValue<TValue extends string> {
    readonly basis: "authored" | "omitted_default" | null;
    readonly value: TValue;
}

export interface PolicyCapabilitySummary {
    readonly commandRun: PolicyCapabilityValue<components["schemas"]["CapabilityDecision"]>;
    readonly humanRequest: {
        readonly allowedKinds: readonly components["schemas"]["HumanRequestKind"][];
        readonly basis: "authored" | "omitted_default" | null;
        readonly mode: components["schemas"]["CapabilityDecision"];
    };
    readonly networkAccess: PolicyCapabilityValue<components["schemas"]["NetworkAccess"]>;
    readonly providerNativeAccess: PolicyCapabilityValue<
        components["schemas"]["ProviderNativeAccess"]
    >;
}

export interface WorkflowDefinitionDetail extends DefinitionDetailBase {
    readonly firstLevelNodes: readonly WorkflowNodeSummary[];
    readonly kind: "workflow";
    readonly nodeCount: number;
    readonly root: WorkflowNodeSummary;
    readonly visibleNodes: readonly WorkflowNodeSummary[];
    readonly workflowStats: WorkflowStats;
}

export type DefinitionDetailView =
    PolicyDefinitionDetail | RoleDefinitionDetail | WorkflowDefinitionDetail;

export const DEFINITION_KIND_OPTIONS: readonly DefinitionKindOption[] = [
    { label: "Roles", listKind: "roles", singularKind: "role" },
    { label: "Policies", listKind: "policies", singularKind: "policy" },
    { label: "Workflows", listKind: "workflows", singularKind: "workflow" },
];

export const DEFINITION_SORT_OPTIONS: readonly {
    readonly label: string;
    readonly value: DefinitionListSort;
}[] = [
    { label: "Sort by: Updated", value: "updated_at_desc" },
    { label: "Sort by: Oldest updated", value: "updated_at_asc" },
    { label: "Sort by: Key A-Z", value: "key_asc" },
    { label: "Sort by: Key Z-A", value: "key_desc" },
];

export const NODE_KIND_FILTERS: readonly { readonly label: string; readonly value: NodeKind }[] = [
    { label: "Root", value: "root" },
    { label: "Parent", value: "parent" },
    { label: "Worker", value: "worker" },
];

export function singularKindForListKind(kind: DefinitionListKind): DefinitionKind {
    switch (kind) {
        case "policies":
            return "policy";
        case "roles":
            return "role";
        case "workflows":
            return "workflow";
    }
}

export function listLabelForKind(kind: DefinitionListKind): string {
    switch (kind) {
        case "policies":
            return "policies";
        case "roles":
            return "roles";
        case "workflows":
            return "workflows";
    }
}

export function kindLabel(kind: DefinitionKind): string {
    switch (kind) {
        case "policy":
            return "Policy";
        case "role":
            return "Role";
        case "workflow":
            return "Workflow";
    }
}

export function formatNodeKind(kind: NodeKind): string {
    switch (kind) {
        case "parent":
            return "Parent";
        case "root":
            return "Root";
        case "worker":
            return "Worker";
    }
}

export function mapDefinitionRow(
    definition: DefinitionSummaryRead,
    kind: DefinitionKind,
): DefinitionRow {
    const summary = mapDefinitionSummary(definition);
    return {
        ...summary,
        compatibilityLabels: compatibilityLabelsForSummary(summary, kind),
        kind,
    };
}

export function mapDefinitionDetail(
    kind: DefinitionKind,
    detail: DefinitionRevisionDetailResponse,
): DefinitionDetailView {
    if (kind === "policy") {
        const content = detail.content as PolicyContent;
        return {
            appliesTo: content.applies_to,
            budgetSpec: content.budget_spec ?? null,
            capabilities: mapPolicyCapabilities(content.capabilities),
            description: content.description,
            instruction: content.instruction ?? null,
            key: detail.key,
            kind,
            recordedBy: detail.recorded_by ?? null,
            revisionNo: detail.revision_no,
            updatedAt: detail.updated_at,
        };
    }

    if (kind === "workflow") {
        const content = detail.content as WorkflowContent;
        const root = content.root;
        const visibleNodes = summarizeWorkflowNodes(root);
        return {
            description: content.description,
            firstLevelNodes: (root.children ?? []).map((node) => summarizeWorkflowNode(node, 1)),
            key: detail.key,
            kind,
            nodeCount: countWorkflowNodes(root),
            recordedBy: detail.recorded_by ?? null,
            revisionNo: detail.revision_no,
            root: visibleNodes[0] ?? summarizeWorkflowNode(root, 0),
            updatedAt: detail.updated_at,
            visibleNodes,
            workflowStats: countWorkflowStats(root),
        };
    }

    const content = detail.content as RoleContent;
    return {
        allowedNodeKinds: content.allowed_node_kinds,
        description: content.description,
        instruction: content.instruction ?? null,
        key: detail.key,
        kind,
        recordedBy: detail.recorded_by ?? null,
        revisionNo: detail.revision_no,
        updatedAt: detail.updated_at,
    };
}

export function mapDefinitionVersionRow(
    version: DefinitionRevisionHistoryEntry,
): DefinitionVersionRow {
    return {
        recordedBy: version.recorded_by ?? null,
        revisionNo: version.revision_no,
        updatedAt: version.updated_at,
    };
}

export function formatBudgetSpec(budgetSpec: BudgetSpec | null): string {
    if (budgetSpec === null) {
        return "No controller budget limit";
    }

    const budgetParts: string[] = [];
    if (
        budgetSpec.child_assignment_limit !== null &&
        budgetSpec.child_assignment_limit !== undefined
    ) {
        const assignmentLabel =
            budgetSpec.child_assignment_limit === 1 ? "child assignment" : "child assignments";
        budgetParts.push(`${String(budgetSpec.child_assignment_limit)} ${assignmentLabel}`);
    }
    if (budgetSpec.retry_limit !== null && budgetSpec.retry_limit !== undefined) {
        const retryLabel = budgetSpec.retry_limit === 1 ? "retry" : "retries";
        budgetParts.push(`${String(budgetSpec.retry_limit)} ${retryLabel}`);
    }

    if (budgetParts.length === 0) {
        return "No controller budget limit";
    }

    return budgetParts.join("; ");
}

export function formatOptionalInstruction(instruction: string | null): string {
    if (instruction === null || instruction.trim().length === 0) {
        return "No instruction reported by the current definition.";
    }

    return instruction;
}

function compatibilityLabelsForSummary(
    summary: DefinitionSummary,
    kind: DefinitionKind,
): readonly string[] {
    if (kind === "role") {
        return summary.allowedNodeKinds.map(formatNodeKind);
    }
    if (kind === "policy") {
        return summary.appliesTo.map(formatNodeKind);
    }
    return [];
}

function summarizeWorkflowNodes(root: WorkflowRootDefinition): readonly WorkflowNodeSummary[] {
    const nodes: WorkflowNodeSummary[] = [];
    visitWorkflowNode(root, 0, nodes);
    return nodes.slice(0, 6);
}

function visitWorkflowNode(
    node: WorkflowRootDefinition | WorkflowNodeDefinition,
    depth: number,
    nodes: WorkflowNodeSummary[],
): void {
    nodes.push(summarizeWorkflowNode(node, depth));
    for (const child of node.children ?? []) {
        visitWorkflowNode(child, depth + 1, nodes);
    }
}

function summarizeWorkflowNode(
    node: WorkflowRootDefinition | WorkflowNodeDefinition,
    depth: number,
): WorkflowNodeSummary {
    return {
        childCount: node.children?.length ?? 0,
        description: node.description,
        depth,
        nodeKey: node.node_key,
        policyId: node.policy_id,
        producedSlots: producedArtifactSlots(node),
        providerKind: node.provider?.kind ?? null,
        roleId: node.role_id,
        title: node.title ?? null,
    };
}

function mapPolicyCapabilities(
    capabilities: PolicyContent["capabilities"],
): PolicyCapabilitySummary {
    const humanRequest = capabilities?.human_request;
    return {
        commandRun: {
            basis: null,
            value: capabilities?.command_run ?? "deny",
        },
        humanRequest: {
            allowedKinds: humanRequest?.allowed_kinds ?? [],
            basis: null,
            mode: humanRequest?.mode ?? "deny",
        },
        networkAccess: {
            basis: capabilities?.network_access === undefined ? "omitted_default" : "authored",
            value: capabilities?.network_access ?? "allow",
        },
        providerNativeAccess: {
            basis:
                capabilities?.provider_native_access === undefined ? "omitted_default" : "authored",
            value: capabilities?.provider_native_access ?? "full",
        },
    };
}

function producedArtifactSlots(
    node: WorkflowRootDefinition | WorkflowNodeDefinition,
): readonly string[] {
    return (node.produces?.artifacts ?? []).map((artifact) => artifact.slot);
}

function countWorkflowNodes(root: WorkflowRootDefinition): number {
    return 1 + (root.children ?? []).reduce((count, child) => count + countWorkflowChild(child), 0);
}

function countWorkflowChild(node: WorkflowNodeDefinition): number {
    return 1 + (node.children ?? []).reduce((count, child) => count + countWorkflowChild(child), 0);
}

function countWorkflowStats(root: WorkflowRootDefinition): WorkflowStats {
    const stats: WorkflowStats = {
        childCount: Math.max(0, countWorkflowNodes(root) - 1),
        leafRoleCount: countWorkflowLeaves(root),
        producedArtifactCount: countWorkflowProducedArtifacts(root),
    };
    return stats;
}

function countWorkflowLeaves(node: WorkflowRootDefinition | WorkflowNodeDefinition): number {
    const children = node.children ?? [];
    if (children.length === 0) {
        return 1;
    }
    return children.reduce((count, child) => count + countWorkflowLeaves(child), 0);
}

function countWorkflowProducedArtifacts(
    node: WorkflowRootDefinition | WorkflowNodeDefinition,
): number {
    return (
        producedArtifactSlots(node).length +
        (node.children ?? []).reduce(
            (count, child) => count + countWorkflowProducedArtifacts(child),
            0,
        )
    );
}
