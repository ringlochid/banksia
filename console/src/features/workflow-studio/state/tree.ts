import type { MemberEdit, MemberLookup, StudioDirtyState } from "./contracts";
import type { NormalizedMember, NormalizedWorkflow } from "../../../api/types";

export function findMember(
    root: NormalizedMember,
    memberId: string,
    parentId: string | null = null,
): MemberLookup | null {
    if (root.id === memberId) {
        return { member: root, parentId };
    }
    for (const child of root.children ?? []) {
        const found = findMember(child, memberId, root.id);
        if (found !== null) {
            return found;
        }
    }
    return null;
}

export function updateWorkflowMember(
    workflow: NormalizedWorkflow,
    memberId: string,
    patch: MemberEdit,
): NormalizedWorkflow {
    return {
        ...workflow,
        lead: updateMember(workflow.lead, memberId, patch),
    };
}

export function updateMember(
    root: NormalizedMember,
    memberId: string,
    patch: MemberEdit,
): NormalizedMember {
    if (root.id === memberId) {
        return applyMemberEdit(root, patch);
    }
    const children = root.children?.map((child) =>
        updateMember(child, memberId, patch),
    );
    return children === undefined ? root : { ...root, children };
}

export function overlayDirtyValues(
    accepted: NormalizedWorkflow,
    local: NormalizedWorkflow,
    dirty: StudioDirtyState,
): NormalizedWorkflow {
    let result = accepted;
    for (const field of dirty.workflow) {
        result = { ...result, [field]: local[field] };
    }
    for (const memberId of dirty.memberIds) {
        const localMember = findMember(local.lead, memberId)?.member;
        if (localMember === undefined) {
            continue;
        }
        const patch: MemberEdit = {};
        for (const field of dirty.memberFields[memberId] ?? []) {
            Object.assign(patch, { [field]: localMember[field] ?? null });
        }
        result = updateWorkflowMember(result, memberId, patch);
    }
    return result;
}

export function memberIds(root: NormalizedMember): readonly string[] {
    return [
        root.id,
        ...(root.children ?? []).flatMap((child) => memberIds(child)),
    ];
}

function applyMemberEdit(
    member: NormalizedMember,
    patch: MemberEdit,
): NormalizedMember {
    const result: NormalizedMember = { ...member };
    applyOptionalText(result, patch, "title");
    applyOptionalText(result, patch, "description");
    applyOptionalText(result, patch, "instruction");
    if (patch.provider === null) {
        delete result.provider;
    } else if (patch.provider !== undefined) {
        result.provider = patch.provider;
    }
    if (patch.capabilities === null) {
        delete result.capabilities;
    } else if (patch.capabilities !== undefined) {
        result.capabilities = patch.capabilities;
    }
    return result;
}

function applyOptionalText(
    target: NormalizedMember,
    patch: MemberEdit,
    field: "title" | "description" | "instruction",
): void {
    const value = patch[field];
    if (value === null) {
        delete target[field];
    } else if (value !== undefined) {
        target[field] = value;
    }
}
