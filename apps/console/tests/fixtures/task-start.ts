import type { components } from "../../src/api/generated/openapi";
import {
    WORKFLOW_KEY,
    createDefinitionVersions,
    createWorkflowDefinitionDetail,
    createWorkflowDefinitionRows,
} from "./definitions";

export const TASK_START_SCREENSHOT_DIR =
    "/home/ubuntu/leo/projects/autoclaw/tmp/autoclaw-frontend/full-delivery-design-parity/06-task-start/screenshots";

export const TASK_START_WORKFLOW_KEY = "reviewed-change-release";
export const SECOND_TASK_START_WORKFLOW_KEY = WORKFLOW_KEY;

export function createTaskStartPreview(
    status: components["schemas"]["TaskComposePreviewResponse"]["status"] = "ready",
): components["schemas"]["TaskComposePreviewResponse"] {
    if (status === "invalid") {
        return {
            errors: [
                {
                    code: "provider_route_unavailable",
                    kind: "provider",
                    message: "The selected provider route is not configured on this machine.",
                    path: "workflow.root.provider.kind",
                },
            ],
            nodes: [],
            status,
            warnings: [],
        };
    }

    return {
        errors: [],
        nodes: [
            {
                network_access: { effective: "deny", source: "policy_definition" },
                node_key: "root",
                provider_native_access: {
                    effective: "restricted",
                    source: "policy_definition",
                },
                provider_resolution: {
                    requested_provider: "openclaw",
                    resolved_provider: "openclaw",
                    selection_basis: "explicit",
                },
            },
            {
                network_access: { effective: "allow", source: "default" },
                node_key: "implementation",
                provider_native_access: { effective: "full", source: "default" },
                provider_resolution: {
                    requested_provider: "codex",
                    resolved_provider: "codex",
                    selection_basis: "default",
                },
            },
        ],
        status,
        warnings: [
            {
                code: "experimental_provider",
                kind: "provider",
                message: "OpenClaw remains an experimental provider lane.",
                path: "workflow.root.provider.kind",
            },
        ],
    };
}

const TASK_START_WORKFLOW_OVERRIDES = new Map<
    string,
    { readonly description: string; readonly updated_at: string }
>([
    [
        WORKFLOW_KEY,
        {
            description:
                "Execute staged discovery, planning, implementation, review, QA, and release work.",
            updated_at: "2026-06-20T07:58:00Z",
        },
    ],
    [
        "bounded-change",
        {
            description: "Execute one bounded engineering change under parent ownership.",
            updated_at: "2026-06-18T09:26:00Z",
        },
    ],
    [
        TASK_START_WORKFLOW_KEY,
        {
            description:
                "Execute one implementation subtree, review it, then release from current evidence.",
            updated_at: "2026-06-16T18:42:00Z",
        },
    ],
]);

export function createTaskStartWorkflowRows(): readonly components["schemas"]["DefinitionSummaryRead"][] {
    const rows = createWorkflowDefinitionRows().map(applyTaskStartWorkflowOverride);
    return [
        ...rows.filter((row) => row.key === TASK_START_WORKFLOW_KEY),
        ...rows.filter((row) => row.key !== TASK_START_WORKFLOW_KEY),
    ];
}

export function createTaskStartWorkflowDetail(
    key = TASK_START_WORKFLOW_KEY,
): components["schemas"]["DefinitionRevisionDetailResponse"] {
    const detail = createWorkflowDefinitionDetail(key);
    const override = TASK_START_WORKFLOW_OVERRIDES.get(detail.key);

    if (override === undefined) {
        return detail;
    }

    return {
        ...detail,
        content: {
            ...detail.content,
            description: override.description,
        },
        updated_at: override.updated_at,
    };
}

export function createTaskStartWorkflowVersions(
    key = TASK_START_WORKFLOW_KEY,
): components["schemas"]["DefinitionRevisionHistoryResponse"] {
    return createDefinitionVersions("workflow", key, {
        currentRevisionNo: key === TASK_START_WORKFLOW_KEY ? 3 : 5,
        revisions: key === TASK_START_WORKFLOW_KEY ? [3, 2] : [5, 4],
    });
}

function applyTaskStartWorkflowOverride(
    row: components["schemas"]["DefinitionSummaryRead"],
): components["schemas"]["DefinitionSummaryRead"] {
    const override = TASK_START_WORKFLOW_OVERRIDES.get(row.key);

    if (override === undefined) {
        return row;
    }

    return {
        ...row,
        description: override.description,
        updated_at: override.updated_at,
    };
}
