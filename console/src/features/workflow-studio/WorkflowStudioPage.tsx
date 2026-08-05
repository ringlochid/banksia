import { ArrowLeft, CircleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useParams } from "react-router-dom";

import type { WorkflowApi } from "../../api/client";
import {
    Button,
    Dialog,
    DialogFooter,
    Notice,
    PageState,
    Prose,
} from "../../components/ui";
import { AuthoringStudio } from "./AuthoringStudio";
import { StudioProvider, useStudio } from "./state/context";
import type { StudioContextValue, StudioLoadState } from "./state/contracts";
import { selectHasPendingWork } from "./state/selectors";
import { useWorkflowAuthoringOptions } from "./useWorkflowAuthoringOptions";

export interface WorkflowStudioPageProps {
    readonly api: WorkflowApi;
}

export function WorkflowStudioPage({ api }: WorkflowStudioPageProps) {
    const { workflowId } = useParams();
    if (workflowId === undefined) {
        return (
            <PageState
                actions={
                    <Link
                        className="ui-button ui-button--secondary"
                        to="/workflows"
                    >
                        Return to Workflows
                    </Link>
                }
                detail="The Workflow link is incomplete."
                fill
                icon={CircleAlert}
                kind="error"
                title="Workflow could not be opened"
            />
        );
    }
    return (
        <StudioProvider api={api} workflowId={workflowId}>
            <WorkflowStudioContent api={api} />
        </StudioProvider>
    );
}

function WorkflowStudioContent({ api }: WorkflowStudioPageProps) {
    const navigate = useNavigate();
    const studio = useStudio();
    const { snapshot, actions } = studio;
    const [discardOpen, setDiscardOpen] = useState(false);
    const validationRef = useRef<HTMLDivElement>(null);
    const allowNavigationRef = useRef(false);
    const isAuthoring = snapshot.workingWorkflow !== null;
    const options = useWorkflowAuthoringOptions(api, isAuthoring);
    const hasPendingWork = selectHasPendingWork(snapshot);
    const blocker = useBlocker(
        ({ currentLocation, nextLocation }) =>
            !allowNavigationRef.current &&
            hasPendingWork &&
            currentLocation.pathname !== nextLocation.pathname,
    );

    useEffect(() => {
        if (snapshot.recoveryOutcome?.kind !== "workflow_removed") {
            return;
        }
        allowNavigationRef.current = true;
        void navigate("/workflows", { replace: true });
    }, [navigate, snapshot.recoveryOutcome]);

    // Opening a published Workflow goes straight to the editor. The old
    // interstitial asked for a click without offering a decision. Attempted
    // once per page so a failure surfaces instead of retrying forever.
    const autoOpenedRef = useRef(false);
    useEffect(() => {
        if (snapshot.workingWorkflow !== null) {
            autoOpenedRef.current = false;
            return;
        }
        if (
            autoOpenedRef.current ||
            snapshot.load.kind !== "ready" ||
            snapshot.catalog === null ||
            snapshot.recovery !== null ||
            !snapshot.catalog.available_actions.includes("edit")
        ) {
            return;
        }
        autoOpenedRef.current = true;
        void actions.beginEditing();
    }, [actions, snapshot]);

    if (snapshot.load.kind !== "ready") {
        return <WorkflowOpeningState load={snapshot.load} />;
    }
    if (snapshot.recoveryOutcome?.kind === "workflow_removed") {
        return <PageState fill kind="loading" title="Returning to Workflows" />;
    }
    if (snapshot.catalog === null) {
        return null;
    }
    if (snapshot.workingWorkflow === null) {
        return (
            <PublishedWorkflow
                canEdit={snapshot.catalog.available_actions.includes("edit")}
                error={
                    snapshot.save.kind === "failed" ||
                    snapshot.save.kind === "offline"
                        ? snapshot.save.message
                        : null
                }
                onEdit={() => void actions.beginEditing()}
                onRecover={() => void actions.retrySave()}
                recovery={snapshot.recovery}
                workflowId={snapshot.catalog.workflow_id}
            />
        );
    }

    return (
        <>
            <AuthoringStudio
                isDiscardOpen={discardOpen}
                onCloseDiscard={() => setDiscardOpen(false)}
                onDiscardDraftOnly={() => {
                    allowNavigationRef.current = true;
                    void navigate("/workflows");
                }}
                onOpenDiscard={() => setDiscardOpen(true)}
                onRetryOptions={options.retry}
                options={options.state}
                studio={studio}
                validationRef={validationRef}
            />
            <NavigationWarningDialog
                isOpen={blocker.state === "blocked"}
                onLeave={() => {
                    if (blocker.state === "blocked") {
                        blocker.proceed();
                    }
                }}
                onStay={() => {
                    if (blocker.state === "blocked") {
                        blocker.reset();
                    }
                }}
            />
        </>
    );
}

function WorkflowOpeningState({ load }: { readonly load: StudioLoadState }) {
    if (load.kind === "loading") {
        return <PageState fill kind="loading" title="Opening Workflow" />;
    }
    if (load.kind === "failed") {
        return (
            <PageState
                actions={
                    <Link
                        className="ui-button ui-button--secondary"
                        to="/workflows"
                    >
                        Return to Workflows
                    </Link>
                }
                detail={load.message}
                fill
                icon={CircleAlert}
                kind="error"
                title="Workflow could not be opened"
            />
        );
    }
    return null;
}

interface NavigationWarningDialogProps {
    readonly isOpen: boolean;
    readonly onLeave: () => void;
    readonly onStay: () => void;
}

function NavigationWarningDialog({
    isOpen,
    onLeave,
    onStay,
}: NavigationWarningDialogProps) {
    return (
        <Dialog
            isOpen={isOpen}
            onClose={onStay}
            title="Discard unsaved changes?"
        >
            <p>
                Banksia is still saving the changes in this tab. If you leave
                now, those unsaved changes will be lost. Your last saved version
                will remain available.
            </p>
            <DialogFooter>
                <Button onClick={onStay} tone="secondary">
                    Continue editing
                </Button>
                <Button onClick={onLeave} tone="danger">
                    Discard changes and leave
                </Button>
            </DialogFooter>
        </Dialog>
    );
}

interface PublishedWorkflowProps {
    readonly canEdit: boolean;
    readonly error: string | null;
    readonly onEdit: () => void;
    readonly onRecover: () => void;
    readonly recovery: StudioContextValue["snapshot"]["recovery"];
    readonly workflowId: string;
}

/**
 * Shown only while the draft is opening, or when it cannot be opened. The
 * happy path never renders anything here for long — the editor takes over as
 * soon as the draft exists.
 */
function PublishedWorkflow({
    canEdit,
    error,
    onEdit,
    onRecover,
    recovery,
    workflowId,
}: PublishedWorkflowProps) {
    if (error === null && recovery === null && canEdit) {
        return (
            <PageState fill kind="loading" title={`Opening ${workflowId}`} />
        );
    }
    return (
        <section className="page">
            <header className="page__header">
                <div className="page__heading">
                    <Link className="page__back" to="/workflows">
                        <ArrowLeft aria-hidden="true" size={15} />
                        Workflows
                    </Link>
                    <h1 className="page__title">{workflowId}</h1>
                </div>
            </header>
            <div className="page__body">
                {error === null ? (
                    <Notice tone="info">
                        You do not have permission to edit this workflow.
                    </Notice>
                ) : (
                    <Notice tone="danger" urgent>
                        <Prose>{error}</Prose>
                        {recovery === null ? null : (
                            <Button onClick={onRecover}>Check current</Button>
                        )}
                    </Notice>
                )}
                {canEdit && error !== null ? (
                    <Button onClick={onEdit} tone="primary">
                        Try again
                    </Button>
                ) : null}
            </div>
        </section>
    );
}
