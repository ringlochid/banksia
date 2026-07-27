import { Button, Notice } from "../../components/ui";
import type { StudioContextValue } from "./state/contracts";
import { selectSaveMessage } from "./state/selectors";

export function SaveStatus({ snapshot, actions }: StudioContextValue) {
    if (snapshot.validation.kind === "checking") {
        return (
            <span className="studio-save-status" role="status">
                Checking this team before publishing…
            </span>
        );
    }
    const operationMessage = exclusiveOperationMessage(
        snapshot.exclusiveOperation,
    );
    if (operationMessage !== null) {
        return (
            <span className="studio-save-status" role="status">
                {operationMessage}
            </span>
        );
    }
    const message = selectSaveMessage(snapshot);
    if (snapshot.save.kind === "offline") {
        return (
            <Notice tone="warning" urgent>
                <p>{message}</p>
                <RecoveryButton {...{ actions, recovery: snapshot.recovery }} />
            </Notice>
        );
    }
    if (snapshot.save.kind === "failed") {
        if (hasTargetedControllerIssue(snapshot)) {
            return (
                <span className="studio-save-status" role="status">
                    Not saved
                </span>
            );
        }
        return (
            <Notice tone="danger" urgent>
                <p>{message}</p>
                <RecoveryButton {...{ actions, recovery: snapshot.recovery }} />
            </Notice>
        );
    }
    return (
        <span className="studio-save-status" role="status">
            {message}
        </span>
    );
}

function hasTargetedControllerIssue(
    snapshot: StudioContextValue["snapshot"],
): boolean {
    return (
        snapshot.validation.kind === "invalid" &&
        snapshot.validation.issues.some(
            (issue) =>
                issue.source === "controller" && issue.target !== undefined,
        )
    );
}

function RecoveryButton({
    actions,
    recovery,
}: {
    readonly actions: StudioContextValue["actions"];
    readonly recovery: StudioContextValue["snapshot"]["recovery"];
}) {
    if (recovery === null) {
        return null;
    }
    const label =
        recovery.kind === "retry_autosave"
            ? "Try saving again"
            : recovery.kind === "check_current"
              ? "Check current"
              : "Reload current";
    return <Button onClick={() => void actions.retrySave()}>{label}</Button>;
}

function exclusiveOperationMessage(
    operation: StudioContextValue["snapshot"]["exclusiveOperation"],
): string | null {
    switch (operation) {
        case "opening_draft":
            return "Opening an editable draft…";
        case "validating_publish":
            return "Checking this team before publishing…";
        case "undoing":
            return "Undoing the last change…";
        case "adding_child":
        case "removing_member":
            return "Updating the team…";
        case "discarding_draft":
            return "Discarding the draft…";
        case null:
            return null;
    }
}
