import type { ControllerResponse, WorkflowApi } from "../../src/api/client";
import type {
    NormalizedWorkflow,
    WorkflowDraftReadback,
    WorkflowGetResponse,
    WorkflowSearchItem,
} from "../../src/api/types";

export const TEST_WORKFLOW_ID = "evidence-synthesis";

export function workflowFixture(
    description = "Research a question with independent evidence review.",
): NormalizedWorkflow {
    return {
        kind: "workflow",
        id: TEST_WORKFLOW_ID,
        description,
        lead: {
            id: "member-1",
            title: "Research lead",
            description: "Own the answer and delegate bounded evidence work.",
            children: [
                {
                    id: "member-2",
                    title: "Independent reviewer",
                    instruction: "Review the draft and rank findings.",
                },
            ],
        },
    };
}

export function draftFixture(
    etag = '"wd-one"',
    description?: string,
): WorkflowDraftReadback {
    return {
        draft_id: "workflow-draft.test",
        workflow_id: TEST_WORKFLOW_ID,
        base_revision_no: 1,
        etag,
        workflow: workflowFixture(description),
    };
}

export function nestedDraftFixture(): WorkflowDraftReadback {
    const draft = draftFixture();
    const manager = draft.workflow.lead.children?.[0];
    if (manager === undefined) {
        throw new Error("Expected reviewer fixture");
    }
    return {
        ...draft,
        workflow: {
            ...draft.workflow,
            lead: {
                ...draft.workflow.lead,
                children: [
                    {
                        ...manager,
                        children: [
                            { id: "member-3", title: "Source specialist" },
                        ],
                    },
                ],
            },
        },
    };
}

export function removeNestedMemberFixture(
    draft: WorkflowDraftReadback,
    etag: string,
): WorkflowDraftReadback {
    const manager = draft.workflow.lead.children?.[0];
    if (manager === undefined) {
        throw new Error("Expected reviewer fixture");
    }
    return {
        ...draft,
        etag,
        workflow: {
            ...draft.workflow,
            lead: {
                ...draft.workflow.lead,
                children: [{ ...manager, children: [] }],
            },
        },
    };
}

export function catalogFixture(
    options: {
        readonly draft?: WorkflowDraftReadback | null;
        readonly published?: boolean;
    } = {},
): WorkflowGetResponse {
    const draft = options.draft === undefined ? draftFixture() : options.draft;
    const published = options.published ?? true;
    return {
        workflow_id: TEST_WORKFLOW_ID,
        description:
            draft?.workflow.description ??
            "Research a question with independent evidence review.",
        state:
            draft === null
                ? "published"
                : published
                  ? "published_with_draft"
                  : "draft",
        updated_at: "2026-07-25T05:00:00Z",
        provenance: "starter_seed",
        published_revision_no: published ? 1 : null,
        available_actions: published ? ["edit", "start_run"] : ["edit"],
        published: published
            ? {
                  workflow_id: TEST_WORKFLOW_ID,
                  revision_no: 1,
                  workflow: workflowFixture(),
              }
            : null,
        revisions: published
            ? [
                  {
                      workflow_id: TEST_WORKFLOW_ID,
                      revision_no: 1,
                      provenance: "starter_seed",
                  },
              ]
            : [],
        active_draft: draft,
    };
}

export function searchItemFixture(
    overrides: Partial<WorkflowSearchItem> = {},
): WorkflowSearchItem {
    return {
        workflow_id: TEST_WORKFLOW_ID,
        description: "Research a question with independent evidence review.",
        state: "published",
        updated_at: "2026-07-25T05:00:00Z",
        provenance: "starter_seed",
        published_revision_no: 1,
        available_actions: ["edit", "start_run", "remove"],
        ...overrides,
    };
}

export function response<T>(body: T, status = 200): ControllerResponse<T> {
    return { body, etag: null, status };
}

export function workflowApiStub(overrides: Partial<WorkflowApi>): WorkflowApi {
    const unavailable = (): never => {
        throw new Error("Unexpected Workflow API call");
    };
    return {
        searchWorkflows: unavailable,
        getWorkflow: unavailable,
        removeWorkflow: unavailable,
        getAuthoringOptions: unavailable,
        createWorkflow: unavailable,
        openWorkflow: unavailable,
        mutateDraft: unavailable,
        validateDraft: unavailable,
        publishDraft: unavailable,
        discardDraft: unavailable,
        undoDraft: unavailable,
        ...overrides,
    };
}
