import type { components } from "../../src/api/generated/openapi";

export const DEFINITION_EDITOR_SCREENSHOT_DIR =
    "/home/ubuntu/leo/projects/autoclaw/tmp/autoclaw-frontend/full-delivery-design-parity/07-definition-editor/screenshots";

export const DEFINITION_EDITOR_WORKFLOW_KEY = "definition-editor-page";
export const DEFINITION_EDITOR_ROLE_KEY = "definition-editor-review";
export const DEFINITION_EDITOR_NEW_DRAFT_KEY = "definition-editor-new-role";
export const DEFINITION_EDITOR_UPDATED_BODY = bodyForKind(
    "workflow",
    DEFINITION_EDITOR_WORKFLOW_KEY,
    "Saved clean draft body.",
);

const UPDATED_AT = "2026-06-29T20:15:00Z";

export function createDefinitionEditorDraftList(
    ...drafts: readonly components["schemas"]["DefinitionDraftDetail"][]
): components["schemas"]["DefinitionDraftListResponse"] {
    const listedDrafts = drafts.length === 0 ? [createDefinitionEditorDraftDetail()] : drafts;
    return {
        items: listedDrafts.map((draft) => draftSummaryFromDetail(draft)),
        next_cursor: null,
    };
}

export function createDefinitionEditorDraftResponse(
    draft: components["schemas"]["DefinitionDraftDetail"] = createDefinitionEditorDraftDetail(),
): components["schemas"]["DefinitionDraftDetailResponse"] {
    return { draft };
}

export function createDefinitionEditorDraftDetail(
    overrides: Partial<components["schemas"]["DefinitionDraftDetail"]> = {},
): components["schemas"]["DefinitionDraftDetail"] {
    const kind = overrides.kind ?? "workflow";
    const key = overrides.key ?? DEFINITION_EDITOR_WORKFLOW_KEY;
    const body = overrides.body ?? bodyForKind(kind, key);
    return {
        based_on: {
            content_hash: "sha256:stored-baseline",
            revision_no: 12,
            source_path: null,
        },
        baseline_body: storedBodyForKind(kind, key),
        baseline_normalized_content: null,
        body,
        body_format: "yaml",
        content_hash: `sha256:${kind}-${key}-${overrides.status ?? "modified"}`,
        draft_path: `drafts/definitions/${kind}s/${key}.yaml`,
        is_saved: true,
        key,
        kind,
        mode: "update",
        normalized_content: null,
        normalized_path: `drafts/definitions/_normalized/${kind}s/${key}.json`,
        status: "modified",
        updated_at: UPDATED_AT,
        ...overrides,
    };
}

export function createUnsavedCurrentDefinitionDraft(
    key = DEFINITION_EDITOR_WORKFLOW_KEY,
): components["schemas"]["DefinitionDraftDetail"] {
    return createDefinitionEditorDraftDetail({
        body: storedBodyForKind("workflow", key),
        is_saved: false,
        key,
        mode: "update",
        status: "clean",
    });
}

export function createCleanDefinitionEditorDraft(
    body = DEFINITION_EDITOR_UPDATED_BODY,
): components["schemas"]["DefinitionDraftDetail"] {
    return createDefinitionEditorDraftDetail({
        body,
        content_hash: "sha256:clean-workflow",
        status: "clean",
    });
}

export function createNewRoleDraft(
    body = bodyForKind("role", DEFINITION_EDITOR_NEW_DRAFT_KEY),
): components["schemas"]["DefinitionDraftDetail"] {
    return createDefinitionEditorDraftDetail({
        based_on: {
            content_hash: null,
            revision_no: null,
            source_path: null,
        },
        baseline_body: body,
        body,
        content_hash: "sha256:new-role",
        is_saved: true,
        key: DEFINITION_EDITOR_NEW_DRAFT_KEY,
        kind: "role",
        mode: "create",
        status: "new",
    });
}

export function createDefinitionEditorValidation(
    status: components["schemas"]["DefinitionDraftValidationResponse"]["status"] = "valid",
): components["schemas"]["DefinitionDraftValidationResponse"] {
    if (status === "invalid") {
        return {
            errors: [
                {
                    code: "missing_required_field",
                    kind: "schema",
                    message: "Workflow root.role is required.",
                    path: "root.role",
                },
            ],
            key: DEFINITION_EDITOR_WORKFLOW_KEY,
            kind: "workflow",
            status: "invalid",
            warnings: [],
        };
    }

    if (status === "stale") {
        return {
            errors: [
                {
                    code: "stale_baseline",
                    kind: "stale",
                    message: "Stored workflow revision moved after this draft was opened.",
                    path: "workflow.definition-editor-page",
                },
            ],
            key: DEFINITION_EDITOR_WORKFLOW_KEY,
            kind: "workflow",
            status: "stale",
            warnings: [],
        };
    }

    if (status === "name_collision") {
        return {
            errors: [
                {
                    code: "name_collision",
                    kind: "collision",
                    message: "A stored definition already owns this key.",
                    path: "id",
                },
            ],
            key: DEFINITION_EDITOR_WORKFLOW_KEY,
            kind: "workflow",
            status,
            warnings: [],
        };
    }

    return {
        errors: [],
        key: DEFINITION_EDITOR_WORKFLOW_KEY,
        kind: "workflow",
        status: "valid",
        warnings: [],
    };
}

export function createDefinitionEditorPublish(
    status: components["schemas"]["DefinitionDraftPublishResponse"]["status"] = "published",
): components["schemas"]["DefinitionDraftPublishResponse"] {
    return {
        key: DEFINITION_EDITOR_WORKFLOW_KEY,
        kind: "workflow",
        published_revision:
            status === "published"
                ? {
                      content_hash: "sha256:published-workflow",
                      key: DEFINITION_EDITOR_WORKFLOW_KEY,
                      kind: "workflow",
                      revision_no: 14,
                  }
                : null,
        status,
        validation:
            status === "published"
                ? createDefinitionEditorValidation("valid")
                : createDefinitionEditorValidation(status),
    };
}

export function bodyForKind(
    kind: components["schemas"]["DefinitionKind"],
    key: string,
    description = "Review the Definition Editor authoring scope.",
): string {
    if (kind === "policy") {
        return [
            "kind: policy",
            `id: ${key}`,
            `title: ${description}`,
            `description: ${description}`,
            "instruction: Guard launch from incomplete draft state.",
            "applies_to:",
            "    - worker",
            "capabilities:",
            "    provider_native_access: full",
            "    network_access: allow",
            "    command_run: deny",
            "    human_request:",
            "        mode: deny",
            "        allowed_kinds: []",
            "",
        ].join("\n");
    }

    if (kind === "workflow") {
        return [
            "kind: workflow",
            `id: ${key}`,
            `description: ${description}`,
            "root:",
            "    node_key: root",
            "    kind: root",
            "    role_id: root_planning_lead",
            "    policy_id: standard-root",
            "    provider:",
            "        kind: openclaw",
            "    description: Coordinate the authoring workbench.",
            "",
        ].join("\n");
    }

    return [
        "kind: role",
        `id: ${key}`,
        `title: ${description}`,
        `description: ${description}`,
        "instruction: Verify the selected definition draft.",
        "allowed_node_kinds:",
        "    - worker",
        "",
    ].join("\n");
}

function storedBodyForKind(kind: components["schemas"]["DefinitionKind"], key: string): string {
    return bodyForKind(
        kind,
        key,
        "Captured stored baseline for the Definition Editor authoring surface.",
    );
}

function draftSummaryFromDetail(
    detail: components["schemas"]["DefinitionDraftDetail"],
): components["schemas"]["DefinitionDraftSummary"] {
    return {
        based_on: detail.based_on,
        body_format: detail.body_format,
        content_hash: detail.content_hash,
        draft_path: detail.draft_path,
        key: detail.key,
        kind: detail.kind,
        mode: detail.mode,
        normalized_path: detail.normalized_path,
        status: detail.status,
        updated_at: detail.updated_at,
    };
}
