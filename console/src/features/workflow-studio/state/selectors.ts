import type { NormalizedMember } from "../../../api/types";
import type { StudioSnapshot, StudioValidationIssue } from "./contracts";
import { findMember } from "./tree";
import { validateLocalWorkflow } from "./validation";

export function selectMember(
    snapshot: StudioSnapshot,
    memberId = snapshot.selectedMemberId,
): NormalizedMember | null {
    if (snapshot.workingWorkflow === null || memberId === null) {
        return null;
    }
    return findMember(snapshot.workingWorkflow.lead, memberId)?.member ?? null;
}

export function selectChildren(
    snapshot: StudioSnapshot,
    memberId: string,
): readonly NormalizedMember[] {
    return selectMember(snapshot, memberId)?.children ?? [];
}

export function selectValidationIssues(
    snapshot: StudioSnapshot,
): readonly StudioValidationIssue[] {
    if (snapshot.workingWorkflow === null) {
        return [];
    }
    const local = validateLocalWorkflow(snapshot.workingWorkflow);
    if (local.length > 0) {
        return local;
    }
    return snapshot.validation.kind === "invalid"
        ? snapshot.validation.issues
        : [];
}

export function selectCanRemoveMember(snapshot: StudioSnapshot): boolean {
    return (
        snapshot.workingWorkflow !== null &&
        snapshot.selectedMemberId !== null &&
        snapshot.selectedMemberId !== snapshot.workingWorkflow.lead.id
    );
}

export function selectHasPendingWork(snapshot: StudioSnapshot): boolean {
    return (
        snapshot.dirty.workflow.length > 0 ||
        snapshot.dirty.memberIds.length > 0 ||
        snapshot.validation.kind === "checking" ||
        snapshot.exclusiveOperation !== null ||
        snapshot.recovery !== null ||
        [
            "settling",
            "saving",
            "checking_current",
            "structural",
            "offline",
        ].includes(snapshot.save.kind)
    );
}

export function selectEditingDisabled(snapshot: StudioSnapshot): boolean {
    return (
        snapshot.exclusiveOperation !== null ||
        snapshot.conflict !== null ||
        snapshot.recovery?.kind === "check_current" ||
        snapshot.recovery?.kind === "reload_current"
    );
}

export function selectSaveMessage(snapshot: StudioSnapshot): string {
    switch (snapshot.save.kind) {
        case "idle":
            return snapshot.canUndo
                ? "Saved. Undo is available."
                : "All changes saved.";
        case "settling":
            return "Waiting for you to finish typing…";
        case "saving":
            return "Saving changes…";
        case "checking_current":
            return "Checking the latest Workflow…";
        case "structural":
            return "Updating the team…";
        case "offline":
            return "Changes are only in this tab until Banksia reconnects.";
        case "failed":
            return snapshot.save.message;
        case "conflict":
            return "This draft changed elsewhere.";
    }
}
