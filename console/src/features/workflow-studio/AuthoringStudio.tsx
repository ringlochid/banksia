import { ArrowLeft, RotateCcw } from "lucide-react";
import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
    type RefObject,
} from "react";
import { Link } from "react-router-dom";

import type { NormalizedWorkflow } from "../../api/types";
import { Button, Dialog } from "../../components/ui";
import { ConflictNotice } from "./ConflictNotice";
import { MemberDetailsSurface } from "./MemberDetailsSurface";
import { SaveStatus } from "./SaveStatus";
import { TeamCanvas, type TeamMemberFocusRequest } from "./canvas/TeamCanvas";
import type {
    StudioContextValue,
    WorkflowAuthoringOptionsState,
} from "./state/contracts";
import {
    selectEditingDisabled,
    selectMember,
    selectValidationIssues,
} from "./state/selectors";
import { findMember } from "./state/tree";

export interface AuthoringStudioProps {
    readonly isDiscardOpen: boolean;
    readonly onCloseDiscard: () => void;
    readonly onDiscardDraftOnly: () => void;
    readonly onOpenDiscard: () => void;
    readonly onRetryOptions: () => void;
    readonly options: WorkflowAuthoringOptionsState;
    readonly studio: StudioContextValue;
    readonly validationRef: RefObject<HTMLDivElement | null>;
}

export function AuthoringStudio({
    isDiscardOpen,
    onCloseDiscard,
    onDiscardDraftOnly,
    onOpenDiscard,
    onRetryOptions,
    options,
    studio,
    validationRef,
}: AuthoringStudioProps) {
    const workflow = studio.snapshot.workingWorkflow;
    if (workflow === null) {
        return null;
    }
    return (
        <section className="studio">
            <StudioHeader
                onOpenDiscard={onOpenDiscard}
                studio={studio}
                validationRef={validationRef}
                workflowId={workflow.id}
            />
            <StudioBody
                options={options}
                onRetryOptions={onRetryOptions}
                studio={studio}
                validationRef={validationRef}
            />
            <DiscardDraftDialog
                isOpen={isDiscardOpen}
                onClose={onCloseDiscard}
                onDiscardDraftOnly={onDiscardDraftOnly}
                studio={studio}
            />
        </section>
    );
}

interface StudioHeaderProps {
    readonly onOpenDiscard: () => void;
    readonly studio: StudioContextValue;
    readonly validationRef: RefObject<HTMLDivElement | null>;
    readonly workflowId: string;
}

function StudioHeader({
    onOpenDiscard,
    studio,
    validationRef,
    workflowId,
}: StudioHeaderProps) {
    const { snapshot, actions } = studio;
    const isChecking = snapshot.validation.kind === "checking";
    const isExclusive = snapshot.exclusiveOperation !== null;
    const actionBlocked =
        isExclusive ||
        snapshot.recovery !== null ||
        snapshot.save.kind === "conflict";
    return (
        <header className="studio__header">
            <div className="page-frame studio__header-inner">
                <div>
                    <Link className="studio__back" to="/workflows">
                        <ArrowLeft aria-hidden="true" size={16} />
                        Workflows
                    </Link>
                    <h1>{workflowId}</h1>
                </div>
                <div className="studio__actions">
                    <SaveStatus {...studio} />
                    <Button
                        disabled={!snapshot.canUndo || actionBlocked}
                        onClick={() => void actions.undo()}
                        tone="quiet"
                    >
                        <RotateCcw aria-hidden="true" size={16} />
                        Undo
                    </Button>
                    <Button
                        disabled={actionBlocked}
                        onClick={() => {
                            void actions
                                .validateAndPublish()
                                .then((published) => {
                                    if (!published) {
                                        requestAnimationFrame(() =>
                                            validationRef.current?.focus(),
                                        );
                                    }
                                });
                        }}
                        tone="primary"
                    >
                        {snapshot.exclusiveOperation === "validating_publish" ||
                        isChecking
                            ? "Publishing…"
                            : "Publish"}
                    </Button>
                    <Button
                        disabled={actionBlocked}
                        onClick={onOpenDiscard}
                        tone="quiet"
                    >
                        Discard draft
                    </Button>
                </div>
            </div>
        </header>
    );
}

interface StudioBodyProps {
    readonly onRetryOptions: () => void;
    readonly options: WorkflowAuthoringOptionsState;
    readonly studio: StudioContextValue;
    readonly validationRef: RefObject<HTMLDivElement | null>;
}

function StudioBody({
    onRetryOptions,
    options,
    studio,
    validationRef,
}: StudioBodyProps) {
    const workflow = studio.snapshot.workingWorkflow;
    return workflow === null ? null : (
        <EditableStudioBody
            onRetryOptions={onRetryOptions}
            options={options}
            studio={studio}
            validationRef={validationRef}
            workflow={workflow}
        />
    );
}

interface EditableStudioBodyProps extends StudioBodyProps {
    readonly workflow: NormalizedWorkflow;
}

function EditableStudioBody({
    onRetryOptions,
    options,
    studio,
    validationRef,
    workflow,
}: EditableStudioBodyProps) {
    const { snapshot, actions } = studio;
    const issues = selectValidationIssues(snapshot);
    const selectedMember = selectMember(snapshot);
    const editingDisabled = selectEditingDisabled(snapshot);
    const selectedMemberId = selectedMember?.id ?? workflow.lead.id;
    const [detailsOpen, setDetailsOpen] = useState(false);
    const [outlineOpen, setOutlineOpen] = useState(false);
    const [detailsFocusRequest, setDetailsFocusRequest] = useState(0);
    const [memberFocusRequest, setMemberFocusRequest] =
        useState<TeamMemberFocusRequest | null>(null);
    const [collapsedMemberIds, setCollapsedMemberIds] = useState<
        ReadonlySet<string>
    >(() => new Set());
    const [removalMemberId, setRemovalMemberId] = useState<string | null>(null);
    const previousPendingStructure = useRef(snapshot.pendingStructure);
    const previousCheckingCurrent = useRef(
        snapshot.save.kind === "checking_current",
    );
    const nextMemberFocusRevision = useRef(0);
    const visibleCollapsedMemberIds = useMemo(
        () =>
            new Set(
                [...collapsedMemberIds].filter(
                    (memberId) => findMember(workflow.lead, memberId) !== null,
                ),
            ),
        [collapsedMemberIds, workflow.lead],
    );

    const requestMemberFocus = useCallback(
        (
            memberId: string,
            surface: TeamMemberFocusRequest["surface"],
        ): void => {
            nextMemberFocusRevision.current += 1;
            setMemberFocusRequest({
                memberId,
                revision: nextMemberFocusRevision.current,
                surface,
            });
        },
        [],
    );

    useEffect(() => {
        const previous = previousPendingStructure.current;
        previousPendingStructure.current = snapshot.pendingStructure;
        if (
            previous?.kind !== "remove_member" ||
            snapshot.pendingStructure !== null ||
            findMember(workflow.lead, previous.memberId) !== null
        ) {
            return;
        }
        setRemovalMemberId(null);
        requestMemberFocus(
            selectedMemberId,
            outlineOpen ? "outline" : "canvas",
        );
    }, [
        outlineOpen,
        requestMemberFocus,
        selectedMemberId,
        snapshot.pendingStructure,
        workflow.lead,
    ]);

    useEffect(() => {
        const wasChecking = previousCheckingCurrent.current;
        const isChecking = snapshot.save.kind === "checking_current";
        previousCheckingCurrent.current = isChecking;
        if (
            !wasChecking ||
            isChecking ||
            snapshot.recovery !== null ||
            snapshot.conflict !== null
        ) {
            return;
        }
        const frame = requestAnimationFrame(() => {
            if (detailsOpen) {
                setDetailsFocusRequest((request) => request + 1);
                return;
            }
            requestMemberFocus(
                selectedMemberId,
                outlineOpen ? "outline" : "canvas",
            );
        });
        return () => cancelAnimationFrame(frame);
    }, [
        detailsOpen,
        outlineOpen,
        requestMemberFocus,
        selectedMemberId,
        snapshot.conflict,
        snapshot.recovery,
        snapshot.save.kind,
    ]);

    const selectMemberForCanvas = (
        memberId: string,
        openDetails: boolean,
    ): void => {
        actions.selectMember(memberId);
        if (openDetails) {
            setOutlineOpen(false);
            setDetailsOpen(true);
        }
    };

    const openMemberDetails = (memberId: string): void => {
        actions.selectMember(memberId);
        setOutlineOpen(false);
        setDetailsOpen(true);
        setDetailsFocusRequest((request) => request + 1);
    };

    const toggleCollapse = (memberId: string): void => {
        const isCollapsing = !visibleCollapsedMemberIds.has(memberId);
        const selectsCollapsedAncestor =
            isCollapsing &&
            memberId !== selectedMemberId &&
            isMemberDescendantOf(workflow.lead, selectedMemberId, memberId);
        if (selectsCollapsedAncestor) {
            actions.selectMember(memberId);
            requestMemberFocus(memberId, "canvas");
        }
        setCollapsedMemberIds((current) => {
            const next = new Set(current);
            if (next.has(memberId)) {
                next.delete(memberId);
            } else {
                next.add(memberId);
            }
            return next;
        });
    };

    return (
        <div className="page-frame studio__body">
            <ConflictNotice {...studio} />
            <ValidationSummary issues={issues} validationRef={validationRef} />
            <div className="studio__workspace">
                <TeamCanvas
                    collapsedMemberIds={visibleCollapsedMemberIds}
                    detailsOpen={detailsOpen}
                    disabled={editingDisabled}
                    focusRequest={memberFocusRequest}
                    issues={issues}
                    lead={workflow.lead}
                    onAddChild={(memberId) => {
                        setOutlineOpen(false);
                        actions.selectMember(memberId);
                        void actions.addChild(memberId);
                    }}
                    onEdit={openMemberDetails}
                    onOutlineOpenChange={(open) => {
                        setOutlineOpen(open);
                        if (open) {
                            setDetailsOpen(false);
                            requestMemberFocus(selectedMemberId, "outline");
                        }
                    }}
                    onRemove={(memberId) => {
                        actions.selectMember(memberId);
                        setRemovalMemberId(memberId);
                    }}
                    onSelect={selectMemberForCanvas}
                    onToggleCollapse={toggleCollapse}
                    outlineOpen={outlineOpen}
                    pendingStructure={snapshot.pendingStructure}
                    selectedMemberId={selectedMemberId}
                />
                {selectedMember === null ? null : (
                    <MemberDetailsSurface
                        disabled={editingDisabled}
                        focusRequest={detailsFocusRequest}
                        issues={issues}
                        member={selectedMember}
                        onClose={() => {
                            setDetailsOpen(false);
                            requestMemberFocus(selectedMember.id, "canvas");
                        }}
                        onEditMember={(patch) =>
                            actions.editMember(selectedMember.id, patch)
                        }
                        onEditWorkflow={actions.editWorkflow.bind(actions)}
                        onRetryOptions={onRetryOptions}
                        open={detailsOpen}
                        options={options}
                        workflow={workflow}
                    />
                )}
            </div>
            <RemoveBranchDialog
                isOpen={removalMemberId !== null}
                memberId={removalMemberId}
                onClose={() => setRemovalMemberId(null)}
                studio={studio}
            />
        </div>
    );
}

interface ValidationSummaryProps {
    readonly issues: ReturnType<typeof selectValidationIssues>;
    readonly validationRef: RefObject<HTMLDivElement | null>;
}

function ValidationSummary({ issues, validationRef }: ValidationSummaryProps) {
    if (issues.length === 0) {
        return null;
    }
    return (
        <div
            className="studio-validation"
            data-validation-summary
            ref={validationRef}
            role="alert"
            tabIndex={-1}
        >
            <h2>Check these fields</h2>
            <ul>
                {issues.map((issue) => (
                    <li key={`${issue.path}:${issue.message}`}>
                        {issue.message}
                    </li>
                ))}
            </ul>
            <Button
                onClick={() => {
                    document
                        .querySelector<HTMLElement>('[aria-invalid="true"]')
                        ?.focus();
                }}
                tone="quiet"
            >
                Go to first problem
            </Button>
        </div>
    );
}

interface DiscardDraftDialogProps {
    readonly isOpen: boolean;
    readonly onClose: () => void;
    readonly onDiscardDraftOnly: () => void;
    readonly studio: StudioContextValue;
}

function DiscardDraftDialog({
    isOpen,
    onClose,
    onDiscardDraftOnly,
    studio,
}: DiscardDraftDialogProps) {
    const { snapshot, actions } = studio;
    const isSaving = snapshot.exclusiveOperation === "discarding_draft";
    const isDraftOnly =
        snapshot.acceptedDraft?.base_revision_no === null ||
        snapshot.acceptedDraft?.base_revision_no === undefined;
    return (
        <Dialog
            closeDisabled={isSaving}
            isOpen={isOpen}
            onClose={onClose}
            title="Discard this draft?"
        >
            <p>
                {isDraftOnly
                    ? "This Workflow exists only as a draft. Discarding removes it from the library."
                    : "Discarding removes these draft changes and returns to the published Workflow."}
            </p>
            <div className="workflow-dialog__actions">
                <Button disabled={isSaving} onClick={onClose} tone="quiet">
                    Keep editing
                </Button>
                <Button
                    disabled={isSaving}
                    onClick={() => {
                        void actions.discardDraft().then((discarded) => {
                            if (discarded && isDraftOnly) {
                                onDiscardDraftOnly();
                                return;
                            }
                            onClose();
                        });
                    }}
                    tone="danger"
                >
                    {isSaving ? "Discarding…" : "Discard draft"}
                </Button>
            </div>
        </Dialog>
    );
}

interface RemoveBranchDialogProps {
    readonly isOpen: boolean;
    readonly memberId: string | null;
    readonly onClose: () => void;
    readonly studio: StudioContextValue;
}

function RemoveBranchDialog({
    isOpen,
    memberId,
    onClose,
    studio,
}: RemoveBranchDialogProps) {
    const workflow = studio.snapshot.workingWorkflow;
    const member =
        workflow === null || memberId === null
            ? null
            : (findMember(workflow.lead, memberId)?.member ?? null);
    const isRemoving =
        memberId !== null &&
        studio.snapshot.pendingStructure?.kind === "remove_member" &&
        studio.snapshot.pendingStructure.memberId === memberId;
    const title = member?.title?.trim() || "Untitled teammate";

    return (
        <Dialog
            closeDisabled={isRemoving}
            isOpen={isOpen && member !== null}
            onClose={onClose}
            title={`Remove ${title}?`}
        >
            <p>
                This removes the selected teammate and every teammate below it.
                The change is applied only after Banksia accepts the updated
                team.
            </p>
            <div className="workflow-dialog__actions">
                <Button disabled={isRemoving} onClick={onClose} tone="quiet">
                    Keep branch
                </Button>
                <Button
                    disabled={isRemoving || memberId === null}
                    onClick={() => {
                        if (memberId !== null) {
                            void studio.actions.removeMember(memberId);
                        }
                    }}
                    tone="danger"
                >
                    {isRemoving ? "Removing…" : "Remove branch"}
                </Button>
            </div>
        </Dialog>
    );
}

function isMemberDescendantOf(
    root: Parameters<typeof findMember>[0],
    candidateId: string,
    ancestorId: string,
): boolean {
    let parentId = findMember(root, candidateId)?.parentId ?? null;
    while (parentId !== null) {
        if (parentId === ancestorId) {
            return true;
        }
        parentId = findMember(root, parentId)?.parentId ?? null;
    }
    return false;
}
