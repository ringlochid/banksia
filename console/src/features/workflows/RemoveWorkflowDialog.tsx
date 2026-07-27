import { useState } from "react";

import type { WorkflowApi } from "../../api/client";
import type { WorkflowSearchItem } from "../../api/types";
import {
    Button,
    Dialog,
    DialogFooter,
    Notice,
    Prose,
} from "../../components/ui";

export interface RemoveWorkflowDialogProps {
    readonly api: WorkflowApi;
    readonly onClose: () => void;
    readonly onRemoved: (workflowId: string) => void;
    readonly workflow: WorkflowSearchItem;
}

export function RemoveWorkflowDialog({
    api,
    onClose,
    onRemoved,
    workflow,
}: RemoveWorkflowDialogProps) {
    const [error, setError] = useState<string | null>(null);
    const [isRemoving, setIsRemoving] = useState(false);

    const remove = async () => {
        if (isRemoving) {
            return;
        }
        setError(null);
        setIsRemoving(true);
        try {
            const { body } = await api.removeWorkflow(workflow.workflow_id);
            onRemoved(body.workflow_id);
        } catch (caught) {
            setError(
                caught instanceof Error
                    ? caught.message
                    : "The Workflow could not be removed.",
            );
            setIsRemoving(false);
        }
    };

    const description =
        workflow.published_revision_no === null
            ? "This discards its unpublished draft. The unused ID can be created again."
            : "This removes it from Workflows and prevents new runs. Existing runs keep their recorded Workflow revision.";

    return (
        <Dialog
            closeDisabled={isRemoving}
            description={description}
            isOpen
            onClose={onClose}
            title={`Remove ${workflow.workflow_id}?`}
        >
            {error === null ? null : (
                <Notice tone="danger" urgent>
                    <Prose>{error}</Prose>
                </Notice>
            )}
            <DialogFooter>
                <Button disabled={isRemoving} onClick={onClose} tone="quiet">
                    Keep Workflow
                </Button>
                <Button
                    disabled={isRemoving}
                    onClick={() => void remove()}
                    tone="danger"
                >
                    {isRemoving ? "Removing…" : "Remove Workflow"}
                </Button>
            </DialogFooter>
        </Dialog>
    );
}
