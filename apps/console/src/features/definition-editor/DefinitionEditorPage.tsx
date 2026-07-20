import { Plus } from "lucide-react";

import { PageFrame } from "../../components/layout";
import { Button } from "../../components/ui";
import { DefinitionEditorPanels } from "./DefinitionEditorPanels";
import {
    DraftActionConfirmDialog,
    DraftActionResultDialog,
    DraftOperationNavigationDialog,
    NewDraftDialog,
    UnsavedDraftChangesDialog,
} from "./definition-editor-dialogs";
import { useDefinitionEditorController } from "./use-definition-editor-controller";

export function DefinitionEditorPage() {
    const controller = useDefinitionEditorController();

    return (
        <PageFrame
            actions={
                <Button onClick={controller.openNewDraftDialog} icon={<Plus className="size-4" />}>
                    New draft
                </Button>
            }
            className="lg:min-h-[calc(100vh-8rem)]"
            eyebrow="Authoring"
            title="Definition Editor"
        >
            <DefinitionEditorPanels controller={controller} />
            {controller.newDraftForm.isOpen ? (
                <NewDraftDialog
                    form={controller.newDraftForm}
                    onCancel={controller.closeNewDraftDialog}
                    onChange={controller.setNewDraftForm}
                    onCreate={controller.createNewDraft}
                />
            ) : null}
            {controller.draftActionDialog === null ? null : (
                <DraftActionResultDialog
                    dialog={controller.draftActionDialog}
                    onClose={controller.closeDraftActionDialog}
                />
            )}
            {controller.draftConfirmation === null || controller.currentDraft === null ? null : (
                <DraftActionConfirmDialog
                    action={controller.draftConfirmation}
                    draft={controller.currentDraft}
                    isBusy={controller.isBusy}
                    onCancel={controller.cancelDraftConfirmation}
                    onConfirm={controller.confirmDraftAction}
                    operation={controller.operation}
                    operationError={controller.operationError}
                />
            )}
            {controller.isOperationNavigationBlocked ? (
                <DraftOperationNavigationDialog onStay={controller.keepBlockedNavigation} />
            ) : null}
            {controller.isUnsavedNavigationBlocked ? (
                <UnsavedDraftChangesDialog
                    onDiscard={controller.discardBlockedNavigation}
                    onKeepEditing={controller.keepBlockedNavigation}
                />
            ) : null}
        </PageFrame>
    );
}
