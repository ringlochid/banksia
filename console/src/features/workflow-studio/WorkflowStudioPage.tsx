import { ArrowLeft } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useParams } from "react-router-dom";

import type { WorkflowApi } from "../../api/client";
import { Button, Dialog, Notice } from "../../components/ui";
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
        return <Notice tone="danger">The Workflow link is incomplete.</Notice>;
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

    if (snapshot.load.kind !== "ready") {
        return <WorkflowOpeningState load={snapshot.load} />;
    }
    if (snapshot.recoveryOutcome?.kind === "workflow_removed") {
        return (
            <div className="page-frame studio-state" role="status">
                Returning to Workflows…
            </div>
        );
    }
    if (snapshot.catalog === null) {
        return null;
    }
    if (snapshot.workingWorkflow === null) {
        return (
            <PublishedWorkflow
                canEdit={snapshot.catalog.available_actions.includes("edit")}
                description={snapshot.catalog.description}
                error={
                    snapshot.save.kind === "failed" ||
                    snapshot.save.kind === "offline"
                        ? snapshot.save.message
                        : null
                }
                isOpening={snapshot.save.kind === "saving"}
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
        return (
            <div className="page-frame studio-state" role="status">
                Opening Workflow…
            </div>
        );
    }
    if (load.kind === "failed") {
        return (
            <div className="page-frame studio-state">
                <Notice tone="danger" urgent>
                    {load.message}
                </Notice>
                <Link to="/workflows">Return to Workflows</Link>
            </div>
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
            title="Leave before changes are saved?"
        >
            <p>
                Some changes have not reached Banksia. Leaving now will discard
                the values that exist only in this tab.
            </p>
            <div className="workflow-dialog__actions">
                <Button onClick={onStay} tone="quiet">
                    Keep editing
                </Button>
                <Button onClick={onLeave} tone="danger">
                    Leave page
                </Button>
            </div>
        </Dialog>
    );
}

interface PublishedWorkflowProps {
    readonly canEdit: boolean;
    readonly description: string;
    readonly error: string | null;
    readonly isOpening: boolean;
    readonly onEdit: () => void;
    readonly onRecover: () => void;
    readonly recovery: StudioContextValue["snapshot"]["recovery"];
    readonly workflowId: string;
}

function PublishedWorkflow({
    canEdit,
    description,
    error,
    isOpening,
    onEdit,
    onRecover,
    recovery,
    workflowId,
}: PublishedWorkflowProps) {
    return (
        <section className="page-frame studio-published">
            <Link className="studio__back" to="/workflows">
                <ArrowLeft aria-hidden="true" size={16} />
                Workflows
            </Link>
            <p className="studio-form__eyebrow">Published Workflow</p>
            <h1>{workflowId}</h1>
            <p>{description}</p>
            <Notice tone="success">
                This is the current published team. Open a draft when you want
                to make changes.
            </Notice>
            {error === null ? null : (
                <Notice tone="danger" urgent>
                    <p>{error}</p>
                    {recovery === null ? null : (
                        <Button onClick={onRecover}>Check current</Button>
                    )}
                </Notice>
            )}
            {canEdit ? (
                <Button
                    disabled={isOpening || recovery !== null}
                    onClick={onEdit}
                    tone="primary"
                >
                    {isOpening ? "Opening draft…" : "Edit Workflow"}
                </Button>
            ) : null}
        </section>
    );
}
