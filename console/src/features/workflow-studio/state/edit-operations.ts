import type {
    DraftOperation,
    MemberPatch,
    NormalizedMember,
    NormalizedWorkflow,
} from "../../../api/types";
import type {
    MemberEditableField,
    StudioDirtyState,
    StudioSnapshot,
    WorkflowEditableField,
} from "./contracts";
import { EMPTY_DIRTY } from "./reducer";
import { findMember } from "./tree";

export type SentDraftEdit =
    | {
          readonly kind: "workflow";
          readonly fields: readonly WorkflowEditableField[];
          readonly values: Readonly<Record<WorkflowEditableField, unknown>>;
      }
    | {
          readonly kind: "member";
          readonly memberId: string;
          readonly fields: readonly MemberEditableField[];
          readonly values: Readonly<Record<MemberEditableField, unknown>>;
      };

export interface BuiltDraftEdit {
    readonly operation: DraftOperation;
    readonly sent: SentDraftEdit;
}

export function buildDraftEditBatch(
    snapshot: StudioSnapshot,
): readonly BuiltDraftEdit[] {
    const workflow = snapshot.workingWorkflow;
    if (workflow === null) {
        return [];
    }
    const edits: BuiltDraftEdit[] = [];
    if (snapshot.dirty.workflow.length > 0) {
        edits.push(buildWorkflowOperation(workflow, snapshot.dirty.workflow));
    }
    for (const memberId of snapshot.dirty.memberIds) {
        const member = findMember(workflow.lead, memberId)?.member;
        const fields = snapshot.dirty.memberFields[memberId] ?? [];
        if (member !== undefined && fields.length > 0) {
            edits.push(buildMemberOperation(member, fields));
        }
    }
    return edits;
}

export function buildNextDraftEdit(
    snapshot: StudioSnapshot,
): BuiltDraftEdit | null {
    return buildDraftEditBatch(snapshot)[0] ?? null;
}

export function retainNewerDirtyFields(
    snapshot: StudioSnapshot,
    sent: SentDraftEdit,
): StudioDirtyState {
    const workflow = snapshot.workingWorkflow;
    if (workflow === null) {
        return EMPTY_DIRTY;
    }
    if (sent.kind === "workflow") {
        const fields = snapshot.dirty.workflow.filter(
            (field) =>
                !sent.fields.includes(field) ||
                !sameValue(
                    readWorkflowValue(workflow, field),
                    sent.values[field],
                ),
        );
        return { ...snapshot.dirty, workflow: fields };
    }
    const member = findMember(workflow.lead, sent.memberId)?.member;
    if (member === undefined) {
        return withoutMember(snapshot.dirty, sent.memberId);
    }
    const fields = (snapshot.dirty.memberFields[sent.memberId] ?? []).filter(
        (field) =>
            !sent.fields.includes(field) ||
            !sameValue(readMemberValue(member, field), sent.values[field]),
    );
    if (fields.length === 0) {
        return withoutMember(snapshot.dirty, sent.memberId);
    }
    return {
        ...snapshot.dirty,
        memberFields: {
            ...snapshot.dirty.memberFields,
            [sent.memberId]: fields,
        },
    };
}

export function hasDirtyFields(dirty: StudioDirtyState): boolean {
    return dirty.workflow.length > 0 || dirty.memberIds.length > 0;
}

export function buildUnsavedValues(
    snapshot: StudioSnapshot,
): Record<string, unknown> | null {
    const workflow = snapshot.workingWorkflow;
    if (workflow === null || !hasDirtyFields(snapshot.dirty)) {
        return null;
    }
    const result: Record<string, unknown> = { workflow_id: workflow.id };
    if (snapshot.dirty.workflow.length > 0) {
        result.workflow = Object.fromEntries(
            snapshot.dirty.workflow.map((field) => [
                field,
                readWorkflowValue(workflow, field),
            ]),
        );
    }
    result.members = snapshot.dirty.memberIds.map((memberId) => {
        const member = findMember(workflow.lead, memberId)?.member;
        return {
            id: memberId,
            ...Object.fromEntries(
                (snapshot.dirty.memberFields[memberId] ?? []).map((field) => [
                    field,
                    member === undefined
                        ? null
                        : readMemberValue(member, field),
                ]),
            ),
        };
    });
    return result;
}

function buildWorkflowOperation(
    workflow: NormalizedWorkflow,
    fields: readonly WorkflowEditableField[],
): { readonly operation: DraftOperation; readonly sent: SentDraftEdit } {
    const values = {
        description: workflow.description,
        note: workflow.note ?? null,
    };
    const patch = Object.fromEntries(
        fields.map((field) => [field, values[field]]),
    );
    return {
        operation: { kind: "update_workflow", patch },
        sent: { kind: "workflow", fields, values },
    };
}

function buildMemberOperation(
    member: NormalizedMember,
    fields: readonly MemberEditableField[],
): { readonly operation: DraftOperation; readonly sent: SentDraftEdit } {
    const values: Record<MemberEditableField, unknown> = {
        title: member.title ?? null,
        description: member.description ?? null,
        instruction: member.instruction ?? null,
        provider: member.provider ?? null,
        capabilities: member.capabilities ?? null,
    };
    const patch = Object.fromEntries(
        fields.map((field) => [field, values[field]]),
    ) as MemberPatch;
    return {
        operation: { kind: "update_member", member_id: member.id, patch },
        sent: { kind: "member", memberId: member.id, fields, values },
    };
}

function readWorkflowValue(
    workflow: NormalizedWorkflow,
    field: WorkflowEditableField,
): unknown {
    return field === "note" ? (workflow.note ?? null) : workflow.description;
}

function readMemberValue(
    member: NormalizedMember,
    field: MemberEditableField,
): unknown {
    return member[field] ?? null;
}

function withoutMember(
    dirty: StudioDirtyState,
    memberId: string,
): StudioDirtyState {
    const memberFields = { ...dirty.memberFields };
    delete memberFields[memberId];
    return {
        ...dirty,
        memberIds: dirty.memberIds.filter((id) => id !== memberId),
        memberFields,
    };
}

function sameValue(left: unknown, right: unknown): boolean {
    return JSON.stringify(left) === JSON.stringify(right);
}
