import { http, HttpResponse } from "msw";
import { expect, vi } from "vitest";

import { WorkflowApiClient } from "../../src/api/client";
import type {
    DraftOperation,
    WorkflowDraftReadback,
} from "../../src/api/types";
import { WorkflowStudioController } from "../../src/features/workflow-studio/state/controller";
import type { catalogFixture } from "../fixtures/workflows";
import { TEST_WORKFLOW_ID } from "../fixtures/workflows";

export const API_ROOT = "http://oms.test/api";
export const DRAFT_PATH = `${API_ROOT}/workflow-drafts/workflow-draft.test`;
export const WORKFLOW_PATH = `${API_ROOT}/workflows/${TEST_WORKFLOW_ID}`;

export function workflowRead(factory: () => ReturnType<typeof catalogFixture>) {
    return http.get(WORKFLOW_PATH, () => HttpResponse.json(factory()));
}

export async function loadedController(): Promise<WorkflowStudioController> {
    const controller = new WorkflowStudioController(
        TEST_WORKFLOW_ID,
        new WorkflowApiClient(API_ROOT),
    );
    await controller.load();
    expect(controller.getSnapshot().load.kind).toBe("ready");
    return controller;
}

export function mutationResponse(
    draft: WorkflowDraftReadback,
    receipt: string,
) {
    return HttpResponse.json(
        { draft, undo_receipt: receipt },
        { headers: { ETag: draft.etag } },
    );
}

export function applyWorkflowOperation(
    draft: WorkflowDraftReadback,
    operation: DraftOperation,
    etag: string,
): WorkflowDraftReadback {
    if (operation.kind === "update_member") {
        const workflow = structuredClone(draft.workflow);
        applyMemberOperation(workflow.lead, operation);
        return { ...draft, etag, workflow };
    }
    if (operation.kind !== "update_workflow") {
        return { ...draft, etag };
    }
    const workflow = { ...draft.workflow };
    if (typeof operation.patch.description === "string") {
        workflow.description = operation.patch.description;
    }
    if ("note" in operation.patch) {
        if (operation.patch.note === null) {
            delete workflow.note;
        } else if (operation.patch.note !== undefined) {
            workflow.note = operation.patch.note;
        }
    }
    return { ...draft, etag, workflow };
}

export async function settleUntil(condition: () => boolean): Promise<void> {
    for (let attempt = 0; attempt < 100; attempt += 1) {
        if (condition()) {
            return;
        }
        await vi.advanceTimersByTimeAsync(0);
    }
    throw new Error("Controller did not settle within the bounded test loop");
}

function applyMemberOperation(
    member: WorkflowDraftReadback["workflow"]["lead"],
    operation: Extract<DraftOperation, { kind: "update_member" }>,
): boolean {
    if (member.id === operation.member_id) {
        applyMemberPatch(member, operation.patch);
        return true;
    }
    return (
        member.children?.some((child) =>
            applyMemberOperation(child, operation),
        ) ?? false
    );
}

function applyMemberPatch(
    member: WorkflowDraftReadback["workflow"]["lead"],
    patch: Extract<DraftOperation, { kind: "update_member" }>["patch"],
): void {
    for (const field of [
        "title",
        "description",
        "instruction",
        "provider",
        "capabilities",
    ] as const) {
        const value = patch[field];
        if (value === null) {
            delete member[field];
        } else if (value !== undefined) {
            Object.assign(member, { [field]: value });
        }
    }
}
