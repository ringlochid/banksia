import type { components } from "../../src/api/generated/openapi";

export const DEFINITIONS_SCREENSHOT_DIR =
    "/home/ubuntu/leo/projects/autoclaw/tmp/autoclaw-frontend/full-delivery-design-parity/05-definitions/screenshots";

export const ROLE_KEY = "planning_lead";
export const SECOND_ROLE_KEY = "planner";
export const POLICY_KEY = "standard-root-planning";
export const WORKFLOW_KEY = "staged-delivery-release";

type DefinitionSummaryRead = components["schemas"]["DefinitionSummaryRead"];
type DefinitionRevisionDetailResponse = components["schemas"]["DefinitionRevisionDetailResponse"];
type NodeKind = components["schemas"]["NodeKind"];

const ROLE_FIXTURES: readonly {
    readonly allowedNodeKinds: readonly NodeKind[];
    readonly description: string;
    readonly instruction: string;
    readonly key: string;
    readonly revisionNo: number;
    readonly title: string;
    readonly updatedAt: string;
}[] = [
    {
        allowedNodeKinds: ["root", "parent"],
        description: "Parent/root coordinator for one owned subtree.",
        instruction:
            "Coordinate only the current owned subtree.\nUse the current assignment, checkpoints, and surfaced criteria to decide the next step.\nUse control tools only during an open dispatch.",
        key: ROLE_KEY,
        revisionNo: 4,
        title: "Planning Lead",
        updatedAt: "2026-06-19T14:22:00+10:00",
    },
    {
        allowedNodeKinds: ["root"],
        description: "Root coordinator for whole-flow closure.",
        instruction:
            "Own whole-flow planning and final closure from current evidence.\nDispatch bounded parent subtrees only when criteria are explicit.",
        key: "root_planning_lead",
        revisionNo: 3,
        title: "Root Planning Lead",
        updatedAt: "2026-06-18T14:00:00+10:00",
    },
    {
        allowedNodeKinds: ["worker"],
        description: "Worker for one bounded planning assignment.",
        instruction:
            "Plan only the assigned scope.\nPublish the current delivery plan for surfaced criteria and blockers.",
        key: SECOND_ROLE_KEY,
        revisionNo: 3,
        title: "Planner",
        updatedAt: "2026-06-15T11:30:00+10:00",
    },
    {
        allowedNodeKinds: ["worker"],
        description: "Worker for one bounded research or discovery assignment.",
        instruction:
            "Research the assigned sources, record current evidence, and avoid implementation changes.",
        key: "researcher",
        revisionNo: 2,
        title: "Researcher",
        updatedAt: "2026-06-13T15:20:00+10:00",
    },
];

const POLICY_FIXTURES: readonly {
    readonly appliesTo: readonly NodeKind[];
    readonly childAssignmentLimit: number | null;
    readonly commandRun: components["schemas"]["CapabilityDecision"];
    readonly description: string;
    readonly humanRequestKinds: readonly components["schemas"]["HumanRequestKind"][];
    readonly humanRequestMode: components["schemas"]["CapabilityDecision"];
    readonly instruction: string;
    readonly key: string;
    readonly networkAccess?: components["schemas"]["NetworkAccess"];
    readonly providerNativeAccess?: components["schemas"]["ProviderNativeAccess"];
    readonly retryLimit: number | null;
    readonly revisionNo: number;
    readonly title: string;
    readonly updatedAt: string;
}[] = [
    {
        appliesTo: ["root"],
        childAssignmentLimit: null,
        commandRun: "deny",
        description: "Default root planning and closure behavior.",
        instruction:
            "Root owns final closure.\nCommit release_green only when current whole-flow evidence is sufficient.\nCommit release_blocked only when whole-flow terminal blocked state is explicit and current.",
        key: POLICY_KEY,
        humanRequestKinds: ["direction", "review"],
        humanRequestMode: "allow",
        networkAccess: "deny",
        providerNativeAccess: "restricted",
        retryLimit: null,
        revisionNo: 3,
        title: "Standard Root Planning",
        updatedAt: "2026-06-19T16:00:00+10:00",
    },
    {
        appliesTo: ["parent"],
        childAssignmentLimit: 4,
        commandRun: "deny",
        description: "Default parent planning behavior.",
        instruction:
            "Dispatch bounded child assignments from accepted criteria.\nDo not widen scope to hide unclear plan or contract debt.",
        key: "standard-parent-planning",
        humanRequestKinds: [],
        humanRequestMode: "deny",
        retryLimit: null,
        revisionNo: 4,
        title: "Standard Parent Planning",
        updatedAt: "2026-06-17T12:00:00+10:00",
    },
    {
        appliesTo: ["worker"],
        childAssignmentLimit: null,
        commandRun: "allow",
        description: "Default worker behavior for bounded assignments.",
        instruction:
            "Complete the assigned scope, record evidence, and return a precise boundary result.",
        key: "standard-worker",
        humanRequestKinds: [],
        humanRequestMode: "deny",
        networkAccess: "allow",
        providerNativeAccess: "full",
        retryLimit: 1,
        revisionNo: 2,
        title: "Standard Worker",
        updatedAt: "2026-06-13T09:00:00+10:00",
    },
    {
        appliesTo: ["worker"],
        childAssignmentLimit: null,
        commandRun: "deny",
        description: "Ordinary review worker behavior.",
        instruction:
            "Review the submitted scope strictly against the accepted criteria and current evidence.",
        key: "standard-review",
        humanRequestKinds: ["review"],
        humanRequestMode: "allow",
        networkAccess: "allow",
        providerNativeAccess: "restricted",
        retryLimit: null,
        revisionNo: 2,
        title: "Standard Review",
        updatedAt: "2026-06-11T09:00:00+10:00",
    },
];

const WORKFLOW_FIXTURES: readonly {
    readonly description: string;
    readonly key: string;
    readonly revisionNo: number;
    readonly title: string;
    readonly updatedAt: string;
}[] = [
    {
        description:
            "Execute staged discovery, planning, implementation, review, QA, and release work for the authentication overhaul.",
        key: WORKFLOW_KEY,
        revisionNo: 5,
        title: "Maximal Parent First Release",
        updatedAt: "2026-06-20T17:58:00+10:00",
    },
    {
        description: "Execute one bounded engineering change.",
        key: "bounded-change",
        revisionNo: 2,
        title: "Minimal Implement Change",
        updatedAt: "2026-06-18T13:10:00+10:00",
    },
    {
        description:
            "Execute one implementation subtree, review it, then release from current evidence.",
        key: "reviewed-change-release",
        revisionNo: 3,
        title: "Normal Parent First Release",
        updatedAt: "2026-06-17T10:40:00+10:00",
    },
];

export function createDefinitionSummaryList(
    kind: components["schemas"]["DefinitionKind"],
    items: readonly DefinitionSummaryRead[],
    nextCursor: string | null = null,
): components["schemas"]["DefinitionSummaryListResponse"] {
    return {
        items: [...items],
        kind,
        next_cursor: nextCursor,
    };
}

export function createRoleDefinitionRows(): readonly DefinitionSummaryRead[] {
    return ROLE_FIXTURES.map((role) => ({
        allowed_node_kinds: [...role.allowedNodeKinds],
        applies_to: null,
        budget_spec: null,
        current_revision_no: role.revisionNo,
        description: role.description,
        key: role.key,
        labels: ["authoring"],
        title: role.title,
        updated_at: role.updatedAt,
    }));
}

export function createPolicyDefinitionRows(): readonly DefinitionSummaryRead[] {
    return POLICY_FIXTURES.map((policy) => ({
        allowed_node_kinds: null,
        applies_to: [...policy.appliesTo],
        budget_spec: policyBudgetSpec(policy),
        current_revision_no: policy.revisionNo,
        description: policy.description,
        key: policy.key,
        labels: ["authoring"],
        title: policy.title,
        updated_at: policy.updatedAt,
    }));
}

export function createWorkflowDefinitionRows(): readonly DefinitionSummaryRead[] {
    return WORKFLOW_FIXTURES.map((workflow) => ({
        allowed_node_kinds: null,
        applies_to: null,
        budget_spec: null,
        current_revision_no: workflow.revisionNo,
        description: workflow.description,
        key: workflow.key,
        labels: ["authoring"],
        title: workflow.title,
        updated_at: workflow.updatedAt,
    }));
}

export function createRoleDefinitionDetail(key = ROLE_KEY): DefinitionRevisionDetailResponse {
    const role = ROLE_FIXTURES.find((candidate) => candidate.key === key) ?? ROLE_FIXTURES[0];
    return {
        content: {
            allowed_node_kinds: [...role.allowedNodeKinds],
            description: role.description,
            id: role.key,
            instruction: role.instruction,
            labels: ["authoring"],
            title: role.title,
        },
        key: role.key,
        recorded_by: null,
        revision_no: role.revisionNo,
        updated_at: role.updatedAt,
    };
}

export function createPolicyDefinitionDetail(key = POLICY_KEY): DefinitionRevisionDetailResponse {
    const policy = POLICY_FIXTURES.find((candidate) => candidate.key === key) ?? POLICY_FIXTURES[0];
    return {
        content: {
            applies_to: [...policy.appliesTo],
            budget_spec: policyBudgetSpec(policy),
            capabilities: {
                command_run: policy.commandRun,
                human_request: {
                    allowed_kinds: [...policy.humanRequestKinds],
                    mode: policy.humanRequestMode,
                },
                ...(policy.networkAccess === undefined
                    ? {}
                    : { network_access: policy.networkAccess }),
                ...(policy.providerNativeAccess === undefined
                    ? {}
                    : { provider_native_access: policy.providerNativeAccess }),
            },
            description: policy.description,
            id: policy.key,
            instruction: policy.instruction,
            labels: ["authoring"],
            title: policy.title,
        },
        key: policy.key,
        recorded_by: null,
        revision_no: policy.revisionNo,
        updated_at: policy.updatedAt,
    };
}

export function createWorkflowDefinitionDetail(
    key = WORKFLOW_KEY,
): DefinitionRevisionDetailResponse {
    const workflow =
        WORKFLOW_FIXTURES.find((candidate) => candidate.key === key) ?? WORKFLOW_FIXTURES[0];
    return {
        content: {
            description: workflow.description,
            id: workflow.key,
            root: workflowRootForKey(workflow.key, workflow.description),
        },
        key: workflow.key,
        recorded_by: null,
        revision_no: workflow.revisionNo,
        updated_at: workflow.updatedAt,
    };
}

export function createDefinitionVersions(
    kind: components["schemas"]["DefinitionKind"] = "role",
    key = ROLE_KEY,
    options: {
        readonly currentRevisionNo?: number;
        readonly nextCursor?: string | null;
        readonly revisions?: readonly number[];
    } = {},
): components["schemas"]["DefinitionRevisionHistoryResponse"] {
    const revisions = options.revisions ?? [options.currentRevisionNo ?? 4, 3, 2];
    return {
        current_revision_no: options.currentRevisionNo ?? revisions[0],
        items: revisions.map((revisionNo, index) => ({
            recorded_by: null,
            revision_no: revisionNo,
            updated_at: `2026-06-${String(29 - index).padStart(2, "0")}T14:00:00Z`,
        })),
        key,
        kind,
        next_cursor: options.nextCursor ?? null,
    };
}

export function createDefinitionDetailMap(): Record<string, DefinitionRevisionDetailResponse> {
    return {
        ...Object.fromEntries(
            POLICY_FIXTURES.map((policy) => [
                `policy:${policy.key}`,
                createPolicyDefinitionDetail(policy.key),
            ]),
        ),
        ...Object.fromEntries(
            ROLE_FIXTURES.map((role) => [`role:${role.key}`, createRoleDefinitionDetail(role.key)]),
        ),
        ...Object.fromEntries(
            WORKFLOW_FIXTURES.map((workflow) => [
                `workflow:${workflow.key}`,
                createWorkflowDefinitionDetail(workflow.key),
            ]),
        ),
    };
}

export function createDefinitionVersionsMap(): Record<
    string,
    components["schemas"]["DefinitionRevisionHistoryResponse"]
> {
    return {
        ...Object.fromEntries(
            POLICY_FIXTURES.map((policy) => [
                `policy:${policy.key}`,
                createDefinitionVersions("policy", policy.key, {
                    currentRevisionNo: policy.revisionNo,
                    revisions: [policy.revisionNo],
                }),
            ]),
        ),
        ...Object.fromEntries(
            ROLE_FIXTURES.map((role) => [
                `role:${role.key}`,
                createDefinitionVersions("role", role.key, {
                    currentRevisionNo: role.revisionNo,
                    revisions:
                        role.key === SECOND_ROLE_KEY
                            ? [role.revisionNo]
                            : [role.revisionNo, Math.max(1, role.revisionNo - 1)],
                }),
            ]),
        ),
        ...Object.fromEntries(
            WORKFLOW_FIXTURES.map((workflow) => [
                `workflow:${workflow.key}`,
                createDefinitionVersions("workflow", workflow.key, {
                    currentRevisionNo: workflow.revisionNo,
                    revisions: [workflow.revisionNo, Math.max(1, workflow.revisionNo - 1)],
                }),
            ]),
        ),
    };
}

function policyBudgetSpec(policy: {
    readonly childAssignmentLimit: number | null;
    readonly retryLimit: number | null;
}): components["schemas"]["BudgetSpec"] | null {
    const budgetSpec: components["schemas"]["BudgetSpec"] = {};
    if (policy.childAssignmentLimit !== null) {
        budgetSpec.child_assignment_limit = policy.childAssignmentLimit;
    }
    if (policy.retryLimit !== null) {
        budgetSpec.retry_limit = policy.retryLimit;
    }

    return Object.keys(budgetSpec).length === 0 ? null : budgetSpec;
}

function workflowRootForKey(
    key: string,
    description: string,
): components["schemas"]["RootNodeDefinition-Output"] {
    if (key === "bounded-change") {
        return {
            child_defaults: null,
            children: [
                workflowChild({
                    description: "Implement one bounded engineering change.",
                    id: "implement_change",
                    produces: ["change_patch", "verification_report"],
                    role: "planner",
                    provider: { kind: "codex" },
                }),
            ],
            criteria: null,
            description,
            instruction: "Coordinate the bounded change and close from current evidence.",
            kind: "root",
            node_key: "root",
            policy_id: "standard-root-planning",
            produces: null,
            provider: { kind: "openclaw" },
            role_id: ROLE_KEY,
            title: "Root",
        };
    }

    if (key === "reviewed-change-release") {
        return {
            child_defaults: null,
            children: [
                workflowChild({
                    description: "Implement one meaningful scope.",
                    id: "implementation",
                    produces: ["change_patch", "verification_report"],
                    role: "planner",
                    provider: { kind: "codex" },
                }),
                workflowChild({
                    description: "Review the completed scope.",
                    id: "review",
                    produces: ["review_report"],
                    role: "researcher",
                }),
            ],
            criteria: null,
            description,
            instruction: "Execute one implementation subtree, review it, then release.",
            kind: "root",
            node_key: "root",
            policy_id: "standard-root-planning",
            produces: null,
            provider: { kind: "openclaw" },
            role_id: ROLE_KEY,
            title: "Root",
        };
    }

    return {
        child_defaults: null,
        children: [
            workflowChild({
                children: [
                    workflowChild({
                        description:
                            "Gather source truth and publish discovery notes before downstream use.",
                        id: "source_research",
                        produces: [],
                        role: "researcher",
                    }),
                ],
                description:
                    "Coordinate discovery work and verify discovery outputs before downstream use.",
                id: "discovery",
                produces: ["findings_report", "discovery_notes"],
                role: ROLE_KEY,
            }),
            workflowChild({
                children: [
                    workflowChild({
                        description: "Implement one meaningful frontend scope.",
                        id: "implement_frontend_scope",
                        produces: [],
                        role: "planner",
                    }),
                    workflowChild({
                        description: "Review one frontend scope.",
                        id: "review_frontend_scope",
                        produces: [],
                        role: "researcher",
                    }),
                    workflowChild({
                        description: "Verify release-sensitive browser evidence.",
                        id: "qa_frontend_scope",
                        produces: [],
                        role: "researcher",
                    }),
                    workflowChild({
                        description: "Apply focused fixes from current review findings.",
                        id: "fix_frontend_scope",
                        produces: [],
                        role: "researcher",
                    }),
                ],
                description:
                    "Coordinate planning, implementation, review, and QA from current surfaced discovery outputs.",
                id: "implementation_loop",
                produces: [
                    "delivery_plan",
                    "change_patch",
                    "verification_report",
                    "review_report",
                    "qa_report",
                ],
                role: ROLE_KEY,
            }),
            workflowChild({
                description:
                    "Perform the final bounded release work from current surfaced evidence.",
                id: "release_closure",
                produces: ["closure_report"],
                role: "root_planning_lead",
            }),
        ],
        criteria: null,
        description,
        instruction:
            "Coordinate the whole authentication overhaul and decide final bounded closure from current evidence.",
        kind: "root",
        node_key: "root",
        policy_id: "standard-root-planning",
        produces: null,
        provider: null,
        role_id: "root_planning_lead",
        title: "Root",
    };
}

function workflowChild({
    children = null,
    description,
    id,
    policy = "standard-parent-planning",
    produces,
    provider = null,
    role,
}: {
    readonly children?: components["schemas"]["NodeDefinitionInput-Output"][] | null;
    readonly description: string;
    readonly id: string;
    readonly policy?: string;
    readonly produces: readonly string[];
    readonly provider?: components["schemas"]["ProviderSelection"] | null;
    readonly role: string;
}): components["schemas"]["NodeDefinitionInput-Output"] {
    return {
        child_defaults: null,
        children,
        consumes: null,
        criteria: null,
        description,
        instruction: description,
        kind: children === null ? "worker" : "parent",
        node_key: id,
        policy_id: policy,
        produces: {
            artifacts: produces.map((slot) => ({
                description: slot,
                file_hint: `${slot}.md`,
                slot,
            })),
        },
        provider,
        role_id: role,
        title: null,
    };
}
