import { ArrowLeft, Download, RotateCcw, Settings2 } from "lucide-react";
import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
    type RefObject,
} from "react";
import { Link } from "react-router";

import type {
    NewMember,
    NormalizedMember,
    NormalizedWorkflow,
} from "../../api/types";
import { Button, Dialog, DialogFooter } from "../../components/ui";
import { ConflictNotice } from "./ConflictNotice";
import { MemberDetailsSurface } from "./MemberDetailsSurface";
import { SaveStatus } from "./SaveStatus";
import { WorkflowDetailsSurface } from "./WorkflowDetailsSurface";
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
import { downloadWorkflowYaml } from "./workflow-export";

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

interface PendingMemberDraft {
    readonly parentMemberId: string;
    readonly member: NewMember;
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
    const [pendingMember, setPendingMember] =
        useState<PendingMemberDraft | null>(null);
    const [workflowDetailsOpen, setWorkflowDetailsOpen] = useState(false);
    const [workflowDetailsFocusRequest, setWorkflowDetailsFocusRequest] =
        useState(0);
    const workflow = studio.snapshot.workingWorkflow;
    if (workflow === null) {
        return null;
    }
    return (
        <section className="studio">
            <StudioHeader
                localAddOpen={pendingMember !== null}
                onOpenDiscard={onOpenDiscard}
                onOpenWorkflowSettings={() => {
                    setWorkflowDetailsOpen(true);
                    setWorkflowDetailsFocusRequest((request) => request + 1);
                }}
                studio={studio}
                validationRef={validationRef}
                workflow={workflow}
            />
            <StudioBody
                options={options}
                onRetryOptions={onRetryOptions}
                pendingMember={pendingMember}
                setPendingMember={setPendingMember}
                studio={studio}
                validationRef={validationRef}
                workflowDetailsFocusRequest={workflowDetailsFocusRequest}
                workflowDetailsOpen={workflowDetailsOpen}
                setWorkflowDetailsOpen={setWorkflowDetailsOpen}
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
    readonly localAddOpen: boolean;
    readonly onOpenDiscard: () => void;
    readonly onOpenWorkflowSettings: () => void;
    readonly studio: StudioContextValue;
    readonly validationRef: RefObject<HTMLDivElement | null>;
    readonly workflow: NormalizedWorkflow;
}

function StudioHeader({
    localAddOpen,
    onOpenDiscard,
    onOpenWorkflowSettings,
    studio,
    validationRef,
    workflow,
}: StudioHeaderProps) {
    const { snapshot, actions } = studio;
    const isChecking = snapshot.validation.kind === "checking";
    const isExclusive = snapshot.exclusiveOperation !== null;
    const actionBlocked =
        isExclusive ||
        localAddOpen ||
        snapshot.recovery !== null ||
        snapshot.save.kind === "conflict";
    return (
        <header className="studio__header">
            <div className="studio__header-inner">
                <div className="studio__crumbs">
                    <Link className="studio__back" to="/workflows">
                        <ArrowLeft aria-hidden="true" size={15} />
                        Workflows
                    </Link>
                    <span aria-hidden="true" className="studio__crumb-sep">
                        /
                    </span>
                    <h1 className="studio__title">{workflow.id}</h1>
                </div>
                <div className="studio__actions">
                    <Button
                        disabled={actionBlocked}
                        onClick={onOpenWorkflowSettings}
                        tone="quiet"
                    >
                        <Settings2 aria-hidden="true" size={16} />
                        Workflow settings
                    </Button>
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
                        onClick={() => downloadWorkflowYaml(workflow)}
                        tone="quiet"
                    >
                        <Download aria-hidden="true" size={16} />
                        Export YAML
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
    readonly pendingMember: PendingMemberDraft | null;
    readonly setPendingMember: (pending: PendingMemberDraft | null) => void;
    readonly studio: StudioContextValue;
    readonly validationRef: RefObject<HTMLDivElement | null>;
    readonly workflowDetailsFocusRequest: number;
    readonly workflowDetailsOpen: boolean;
    readonly setWorkflowDetailsOpen: (open: boolean) => void;
}

function StudioBody({
    onRetryOptions,
    options,
    pendingMember,
    setPendingMember,
    studio,
    validationRef,
    workflowDetailsFocusRequest,
    workflowDetailsOpen,
    setWorkflowDetailsOpen,
}: StudioBodyProps) {
    const workflow = studio.snapshot.workingWorkflow;
    return workflow === null ? null : (
        <EditableStudioBody
            onRetryOptions={onRetryOptions}
            options={options}
            pendingMember={pendingMember}
            setPendingMember={setPendingMember}
            studio={studio}
            validationRef={validationRef}
            workflow={workflow}
            workflowDetailsFocusRequest={workflowDetailsFocusRequest}
            workflowDetailsOpen={workflowDetailsOpen}
            setWorkflowDetailsOpen={setWorkflowDetailsOpen}
        />
    );
}

interface EditableStudioBodyProps extends StudioBodyProps {
    readonly workflow: NormalizedWorkflow;
}

function EditableStudioBody({
    onRetryOptions,
    options,
    pendingMember,
    setPendingMember,
    studio,
    validationRef,
    workflow,
    workflowDetailsFocusRequest,
    workflowDetailsOpen,
    setWorkflowDetailsOpen,
}: EditableStudioBodyProps) {
    const { snapshot, actions } = studio;
    const issues = selectValidationIssues(snapshot);
    const summaryIssues = issues.filter(
        (issue) =>
            !(issue.source === "controller" && issue.target !== undefined),
    );
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

    useEffect(() => {
        if (!workflowDetailsOpen) {
            return;
        }
        const frame = requestAnimationFrame(() => {
            setDetailsOpen(false);
            setOutlineOpen(false);
        });
        return () => cancelAnimationFrame(frame);
    }, [workflowDetailsOpen]);

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
        setWorkflowDetailsOpen(false);
        actions.selectMember(memberId);
        if (openDetails) {
            setOutlineOpen(false);
            setDetailsOpen(true);
        }
    };

    const openMemberDetails = (memberId: string): void => {
        setWorkflowDetailsOpen(false);
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
        <div className="studio__body">
            <ConflictNotice {...studio} />
            <ValidationSummary
                issues={summaryIssues}
                validationRef={validationRef}
            />
            <div className="studio__workspace">
                <TeamCanvas
                    collapsedMemberIds={visibleCollapsedMemberIds}
                    detailsOpen={detailsOpen || workflowDetailsOpen}
                    disabled={editingDisabled}
                    focusRequest={memberFocusRequest}
                    issues={issues}
                    lead={workflow.lead}
                    localAddOpen={pendingMember !== null}
                    onAddChild={(memberId) => {
                        setWorkflowDetailsOpen(false);
                        setOutlineOpen(false);
                        actions.selectMember(memberId);
                        setPendingMember({
                            parentMemberId: memberId,
                            member: {},
                        });
                        setDetailsOpen(true);
                        setDetailsFocusRequest((request) => request + 1);
                    }}
                    onEdit={openMemberDetails}
                    onOutlineOpenChange={(open) => {
                        if (open) {
                            setWorkflowDetailsOpen(false);
                        }
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
                {workflowDetailsOpen ||
                (selectedMember === null && pendingMember === null) ? null : (
                    <MemberDetailsSurface
                        createState={
                            pendingMember === null
                                ? undefined
                                : {
                                      canSubmit: hasPendingMemberContent(
                                          pendingMember.member,
                                      ),
                                      error: addMemberError(snapshot),
                                      onSubmit: () => {
                                          void actions
                                              .addChild(
                                                  pendingMember.parentMemberId,
                                                  pendingMember.member,
                                              )
                                              .then((memberId) => {
                                                  if (memberId === null) {
                                                      return;
                                                  }
                                                  setPendingMember(null);
                                                  setDetailsFocusRequest(
                                                      (request) => request + 1,
                                                  );
                                              });
                                      },
                                      submitting:
                                          snapshot.exclusiveOperation ===
                                          "adding_child",
                                  }
                        }
                        disabled={
                            pendingMember === null
                                ? editingDisabled
                                : snapshot.exclusiveOperation === "adding_child"
                        }
                        focusRequest={detailsFocusRequest}
                        issues={issues}
                        member={
                            pendingMember === null
                                ? selectedMember!
                                : pendingMemberView(pendingMember)
                        }
                        onClose={() => {
                            const focusMemberId =
                                pendingMember?.parentMemberId ??
                                selectedMember?.id ??
                                workflow.lead.id;
                            setPendingMember(null);
                            setDetailsOpen(false);
                            requestMemberFocus(focusMemberId, "canvas");
                        }}
                        onEditMember={(patch) => {
                            if (pendingMember !== null) {
                                setPendingMember({
                                    ...pendingMember,
                                    member: {
                                        ...pendingMember.member,
                                        ...patch,
                                    },
                                });
                                return;
                            }
                            if (selectedMember !== null) {
                                actions.editMember(selectedMember.id, patch);
                            }
                        }}
                        onRemove={
                            // The lead owns the Workflow and has no parent to
                            // return to, so it is the one Member that stays.
                            pendingMember !== null ||
                            selectedMember === null ||
                            selectedMember.id === workflow.lead.id
                                ? undefined
                                : () => setRemovalMemberId(selectedMember.id)
                        }
                        onRetryOptions={onRetryOptions}
                        open={detailsOpen}
                        options={options}
                        workflow={workflow}
                    />
                )}
                <WorkflowDetailsSurface
                    disabled={editingDisabled}
                    focusRequest={workflowDetailsFocusRequest}
                    issues={issues}
                    onClose={() => {
                        setWorkflowDetailsOpen(false);
                        requestMemberFocus(selectedMemberId, "canvas");
                    }}
                    onEdit={actions.editWorkflow.bind(actions)}
                    open={workflowDetailsOpen}
                    workflow={workflow}
                />
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
            <DialogFooter>
                <Button disabled={isSaving} onClick={onClose} tone="secondary">
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
            </DialogFooter>
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
            <p>This also removes every Member below it.</p>
            <DialogFooter>
                <Button
                    disabled={isRemoving}
                    onClick={onClose}
                    tone="secondary"
                >
                    Cancel
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
                    {isRemoving ? "Removing…" : "Remove member"}
                </Button>
            </DialogFooter>
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

function pendingMemberView(pending: PendingMemberDraft): NormalizedMember {
    const { capabilities, description, instruction, provider, title } =
        pending.member;
    return {
        id: `pending-${pending.parentMemberId}`,
        children: [],
        ...(title === undefined ? {} : { title }),
        ...(description === undefined ? {} : { description }),
        ...(instruction === undefined ? {} : { instruction }),
        ...(provider === undefined || provider === null ? {} : { provider }),
        ...(capabilities === undefined || capabilities === null
            ? {}
            : { capabilities }),
    };
}

function hasPendingMemberContent(member: NewMember): boolean {
    return (member.title?.trim() ?? "") !== "";
}

function addMemberError(
    snapshot: StudioContextValue["snapshot"],
): string | null {
    if (snapshot.save.kind === "failed" || snapshot.save.kind === "offline") {
        return snapshot.save.message;
    }
    if (
        snapshot.recovery?.kind === "check_current" &&
        snapshot.recovery.operation === "adding_child"
    ) {
        return "Banksia could not confirm whether this member was added. Check the current Workflow before trying again.";
    }
    return null;
}
