import { useId, useRef, useState, type FormEvent } from "react";

import type { WorkflowApi } from "../../api/client";
import {
    Button,
    Dialog,
    DialogFooter,
    FormField,
    Input,
    Notice,
    Prose,
    Textarea,
} from "../../components/ui";

export interface CreateWorkflowDialogProps {
    readonly api: WorkflowApi;
    readonly isOpen: boolean;
    readonly onClose: () => void;
    readonly onCreated: (workflowId: string) => void;
}

const WORKFLOW_ID = /^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$/;

export function CreateWorkflowDialog({
    api,
    isOpen,
    onClose,
    onCreated,
}: CreateWorkflowDialogProps) {
    const idPrefix = useId();
    const {
        description,
        descriptionError,
        error,
        idError,
        isCreating,
        setDescription,
        setWorkflowId,
        submit,
        workflowId,
        workflowIdRef,
    } = useWorkflowDraftCreation(api, onCreated);

    return (
        <Dialog
            closeDisabled={isCreating}
            initialFocusRef={workflowIdRef}
            isOpen={isOpen}
            onClose={onClose}
            title="Create a Workflow"
        >
            {error === null ? null : (
                <Notice tone="danger" urgent>
                    <Prose>{error}</Prose>
                </Notice>
            )}
            <form
                className="workflow-dialog__form"
                onSubmit={(event) => void submit(event)}
            >
                <FormField
                    error={idError}
                    hint="This stable name is used in links and commands. Reusing a removed ID continues its preserved revision history."
                    id={`${idPrefix}-workflow-id`}
                    label="Workflow ID"
                >
                    <Input
                        autoComplete="off"
                        disabled={isCreating}
                        maxLength={128}
                        onChange={(event) => setWorkflowId(event.target.value)}
                        placeholder="research-review"
                        ref={workflowIdRef}
                        required
                        value={workflowId}
                    />
                </FormField>
                <FormField
                    error={descriptionError}
                    id={`${idPrefix}-workflow-description`}
                    label="Purpose"
                >
                    <Textarea
                        disabled={isCreating}
                        maxLength={1024}
                        onChange={(event) => setDescription(event.target.value)}
                        required
                        value={description}
                    />
                </FormField>
                <CreateWorkflowActions
                    canCreate={
                        WORKFLOW_ID.test(workflowId) &&
                        description.trim() !== ""
                    }
                    isCreating={isCreating}
                    onClose={onClose}
                />
            </form>
        </Dialog>
    );
}

interface CreateWorkflowActionsProps {
    readonly canCreate: boolean;
    readonly isCreating: boolean;
    readonly onClose: () => void;
}

function CreateWorkflowActions({
    canCreate,
    isCreating,
    onClose,
}: CreateWorkflowActionsProps) {
    return (
        <DialogFooter>
            <Button disabled={isCreating} onClick={onClose} tone="secondary">
                Cancel
            </Button>
            <Button
                disabled={isCreating || !canCreate}
                tone="primary"
                type="submit"
            >
                {isCreating ? "Creating…" : "Create Workflow"}
            </Button>
        </DialogFooter>
    );
}

function useWorkflowDraftCreation(
    api: WorkflowApi,
    onCreated: (workflowId: string) => void,
) {
    const [workflowId, setWorkflowId] = useState("");
    const [description, setDescription] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [isCreating, setIsCreating] = useState(false);
    const workflowIdRef = useRef<HTMLInputElement>(null);
    const idError =
        workflowId !== "" && !WORKFLOW_ID.test(workflowId)
            ? "Use lowercase letters and numbers, joined by hyphens or underscores."
            : null;
    const descriptionError =
        description !== "" && description.trim() === ""
            ? "Describe when this team should be used."
            : null;

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (
            !WORKFLOW_ID.test(workflowId) ||
            description.trim() === "" ||
            isCreating
        ) {
            return;
        }
        setIsCreating(true);
        setError(null);
        try {
            const { body } = await api.createWorkflow({
                kind: "create",
                workflow_id: workflowId,
                description,
            });
            onCreated(body.draft.workflow_id);
        } catch (caught) {
            setError(
                caught instanceof Error
                    ? caught.message
                    : "The Workflow could not be created.",
            );
        } finally {
            setIsCreating(false);
        }
    };

    return {
        description,
        descriptionError,
        error,
        idError,
        isCreating,
        setDescription,
        setWorkflowId,
        submit,
        workflowId,
        workflowIdRef,
    };
}
