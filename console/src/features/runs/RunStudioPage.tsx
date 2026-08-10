import { ArrowLeft, Pause, Play, RefreshCw, Square } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import {
    Button,
    Dialog,
    DialogFooter,
    FormField,
    Notice,
    PageState,
    Prose,
    TabPanel,
    Tabs,
    Textarea,
} from "../../components/ui";
import { CommandRunCard } from "./CommandRunCard";
import { HumanRequestCard } from "./HumanRequestCard";
import {
    errorMessage,
    formatRunDate,
    runStatusLabel,
} from "./run-presentation";
import {
    ActivitySection,
    FileReferences,
    MemberContextSection,
    PlanSection,
    RunResult,
    TeamSection,
} from "./RunSections";
import type {
    CommandRunView,
    HumanRequestResponseInput,
    ProductAction,
    RunApi,
    TaskMemberView,
} from "./run-api";
import { useRunLive } from "./use-run-live";

export interface RunStudioPageProps {
    readonly api: RunApi;
}

interface RunStudioTaskProps extends RunStudioPageProps {
    readonly taskId: string;
}

export function RunStudioPage({ api }: RunStudioPageProps) {
    const { taskId } = useParams();

    if (taskId === undefined) {
        return (
            <PageState
                detail="Open a Run from the Runs list."
                fill
                kind="error"
                title="This Run link is incomplete"
            />
        );
    }
    return <RunStudioTask api={api} key={taskId} taskId={taskId} />;
}

function RunStudioTask({ api, taskId }: RunStudioTaskProps) {
    const {
        activities,
        activityHistoryTruncated,
        commandHistoryTruncated,
        commandRuns,
        error: readError,
        liveDelayed,
        loading,
        refresh,
        refreshing,
        replaceTask,
        retryLive,
        task,
    } = useRunLive(api, taskId);
    const [operationError, setOperationError] = useState<string | null>(null);
    const [selectedMemberId, setSelectedMemberId] = useState<string | null>(
        null,
    );
    const [receipt, setReceipt] = useState<string | null>(null);
    const [pendingControl, setPendingControl] = useState<ProductAction | null>(
        null,
    );
    const [controlSubmitting, setControlSubmitting] = useState(false);
    const [steerMemberId, setSteerMemberId] = useState<string | null>(null);
    const [steerMessage, setSteerMessage] = useState("");
    const [steerError, setSteerError] = useState<string | null>(null);
    const [steerSubmitting, setSteerSubmitting] = useState(false);
    const [activeTab, setActiveTab] = useState("activity");
    const steerInputRef = useRef<HTMLTextAreaElement>(null);
    const error = operationError ?? readError;

    function refreshRun(message?: string): void {
        if (message !== undefined) {
            setReceipt(message);
        }
        setOperationError(null);
        refresh();
    }

    async function handleControl(action: ProductAction): Promise<void> {
        setControlSubmitting(true);
        setOperationError(null);
        try {
            const response = await api.controlRun(taskId, action.id, true);
            replaceTask(response.body.task);
            setReceipt(response.body.status_message);
            setPendingControl(null);
        } catch (reason) {
            setOperationError(errorMessage(reason));
        } finally {
            setControlSubmitting(false);
        }
    }

    async function handleHumanResponse(
        requestId: string,
        action: ProductAction,
        input: HumanRequestResponseInput,
    ): Promise<string> {
        const response = await api.respondToHumanRequest(
            taskId,
            requestId,
            action.id,
            input,
        );
        refreshRun();
        return response.body.status_message;
    }

    async function handleCommandCancel(
        command: CommandRunView,
        action: ProductAction,
    ): Promise<string> {
        const response = await api.cancelCommandRun(
            taskId,
            command.id,
            action.id,
        );
        refreshRun();
        return response.body.status_message;
    }

    function openSteer(member: TaskMemberView): void {
        setSteerMemberId(member.id);
        setSteerMessage("");
        setSteerError(null);
    }

    function closeSteer(): void {
        if (steerSubmitting) {
            return;
        }
        setSteerMemberId(null);
        setSteerMessage("");
        setSteerError(null);
    }

    async function handleSteer(): Promise<void> {
        const member = findTaskMember(task?.team ?? null, steerMemberId);
        const action = member?.steer_action;
        if (member === null || action === null || action === undefined) {
            setSteerError(
                "This Member is no longer available to steer. Reload the Run and try again.",
            );
            return;
        }
        setSteerSubmitting(true);
        setSteerError(null);
        try {
            const response = await api.steerMember(
                taskId,
                member.id,
                action.id,
                steerMessage,
            );
            replaceTask(response.body.task);
            setReceipt(response.body.status_message);
            setSteerMemberId(null);
            setSteerMessage("");
        } catch (reason) {
            setSteerError(errorMessage(reason));
        } finally {
            setSteerSubmitting(false);
        }
    }

    if (loading) {
        return <PageState fill kind="loading" title="Loading Run" />;
    }
    if (task === null) {
        return (
            <PageState
                actions={
                    <>
                        <Button
                            disabled={refreshing}
                            onClick={() => refreshRun()}
                        >
                            <RefreshCw aria-hidden="true" size={16} />
                            {refreshing ? "Trying again…" : "Try again"}
                        </Button>
                        <Link className="ui-button ui-button--quiet" to="/runs">
                            Back to Runs
                        </Link>
                    </>
                }
                detail={
                    error ??
                    "Banksia could not find controller truth for this Run."
                }
                fill
                kind="error"
                title="Run unavailable"
            />
        );
    }

    const openRequests = task.human_requests.filter(
        (request) => request.status === "open",
    );
    const otherAttention = task.attention.filter(
        (attention) => attention.kind !== "human_request",
    );
    const selectedMember =
        findTaskMember(task.team, selectedMemberId) ?? task.team;
    const steerMember = findTaskMember(task.team, steerMemberId);

    return (
        <section className="run-studio">
            <header className="run-studio__header">
                <div className="run-studio__toolbar">
                    <Link className="run-back-link" to="/runs">
                        <ArrowLeft aria-hidden="true" size={15} />
                        Runs
                    </Link>
                    <div className="run-studio__header-actions">
                        <Button
                            aria-label="Refresh Run"
                            disabled={refreshing}
                            onClick={() => refreshRun()}
                            tone="quiet"
                        >
                            <RefreshCw
                                aria-hidden="true"
                                className={refreshing ? "is-spinning" : ""}
                                size={15}
                            />
                            {refreshing ? "Refreshing…" : "Refresh"}
                        </Button>
                        {task.actions.map((action) => (
                            <Button
                                key={action.id}
                                onClick={() =>
                                    action.confirmation.required
                                        ? setPendingControl(action)
                                        : void handleControl(action)
                                }
                                tone={
                                    action.kind === "cancel"
                                        ? "danger"
                                        : action.kind === "resume"
                                          ? "primary"
                                          : "secondary"
                                }
                            >
                                <ActionIcon kind={action.kind} />
                                {action.label}
                            </Button>
                        ))}
                    </div>
                </div>
                <div className="run-studio__title-row">
                    <div>
                        <div className="run-studio__status-line">
                            <span
                                className={`run-status run-status--${task.status}`}
                            >
                                {runStatusLabel(task.status)}
                            </span>
                            <span>{task.workflow.id}</span>
                            <time dateTime={task.updated_at}>
                                Updated {formatRunDate(task.updated_at)}
                            </time>
                        </div>
                        <h1>{task.prompt_excerpt}</h1>
                    </div>
                </div>
            </header>

            <div className="run-studio__feedback">
                {receipt === null ? null : (
                    <Notice tone="info">
                        <Prose>{receipt}</Prose>
                    </Notice>
                )}
                {liveDelayed ? (
                    <Notice tone="info">
                        <p>Live updates are delayed.</p>
                        <Button onClick={retryLive}>
                            <RefreshCw aria-hidden="true" size={16} />
                            Retry
                        </Button>
                    </Notice>
                ) : null}
                {error === null ? null : (
                    <Notice tone="danger" urgent>
                        <Prose>{error}</Prose>
                        <Button onClick={() => refreshRun()}>Refresh</Button>
                    </Notice>
                )}
            </div>

            <div className="run-studio__workspace">
                <aside aria-label="Run context" className="run-studio__sidebar">
                    <TeamSection
                        onSelect={setSelectedMemberId}
                        selectedMemberId={selectedMember.id}
                        team={task.team}
                    />
                    <MemberContextSection
                        member={selectedMember}
                        onSteer={openSteer}
                    />
                    {selectedMember.plan === null ||
                    selectedMember.plan === undefined ? (
                        <section className="run-side-section">
                            <h2>Plan</h2>
                            <p className="run-section__empty">
                                No current plan.
                            </p>
                        </section>
                    ) : (
                        <PlanSection plan={selectedMember.plan} />
                    )}
                </aside>

                <div className="run-studio__main">
                    {openRequests.length === 0 &&
                    otherAttention.length === 0 ? null : (
                        <section
                            aria-labelledby="run-attention-title"
                            className="run-attention"
                        >
                            <header>
                                <h2 id="run-attention-title">
                                    Action required
                                </h2>
                            </header>
                            {openRequests.map((request) => (
                                <HumanRequestCard
                                    key={request.id}
                                    onRespond={handleHumanResponse}
                                    request={request}
                                />
                            ))}
                            {otherAttention.map((attention) => (
                                <article
                                    className="run-attention__item"
                                    key={attention.id}
                                >
                                    <h3>{attention.title}</h3>
                                    <Prose>{attention.summary}</Prose>
                                    {attention.member === null ||
                                    attention.member === undefined ? null : (
                                        <span>{attention.member.name}</span>
                                    )}
                                    <FileReferences
                                        compact
                                        files={attention.files}
                                    />
                                    {attention.link === null ||
                                    attention.link === undefined ? null : (
                                        <a
                                            className="ui-button ui-button--secondary"
                                            href={attention.link.href}
                                        >
                                            {attention.link.label}
                                        </a>
                                    )}
                                </article>
                            ))}
                        </section>
                    )}

                    {task.result === null ||
                    task.result === undefined ? null : (
                        <RunResult result={task.result} />
                    )}

                    <Tabs
                        ariaLabel="Run information"
                        items={[
                            {
                                label: `Activity (${String(activities.length)})`,
                                value: "activity",
                            },
                            {
                                label: `Commands (${String(task.command_run_count)})`,
                                value: "commands",
                            },
                        ]}
                        onValueChange={setActiveTab}
                        value={activeTab}
                    >
                        <TabPanel value="activity">
                            <ActivitySection
                                activities={activities}
                                isTruncated={activityHistoryTruncated}
                            />
                        </TabPanel>
                        <TabPanel value="commands">
                            <section
                                aria-labelledby="run-commands-title"
                                className="run-commands-panel"
                            >
                                <header className="run-section-heading">
                                    <h2 id="run-commands-title">Commands</h2>
                                </header>
                                {commandRuns.length === 0 ? (
                                    <p className="run-section__empty">
                                        No commands for this Run.
                                    </p>
                                ) : (
                                    <div className="run-commands">
                                        {commandRuns.map((command) => (
                                            <CommandRunCard
                                                api={api}
                                                command={command}
                                                key={command.id}
                                                onCancel={handleCommandCancel}
                                                taskId={task.id}
                                            />
                                        ))}
                                    </div>
                                )}
                                {commandHistoryTruncated ? (
                                    <p className="run-bounded-note">
                                        Showing the most recent commands.
                                    </p>
                                ) : null}
                            </section>
                        </TabPanel>
                    </Tabs>
                </div>
            </div>

            <Dialog
                closeDisabled={controlSubmitting}
                isOpen={pendingControl !== null}
                onClose={() => setPendingControl(null)}
                title={pendingControl?.confirmation.title ?? "Confirm action"}
            >
                <div className="run-control-dialog">
                    <Prose>{pendingControl?.confirmation.consequence}</Prose>
                    <div>
                        <Button
                            disabled={controlSubmitting}
                            onClick={() => setPendingControl(null)}
                        >
                            Go back
                        </Button>
                        <Button
                            disabled={controlSubmitting}
                            onClick={() =>
                                pendingControl === null
                                    ? undefined
                                    : void handleControl(pendingControl)
                            }
                            tone={
                                pendingControl?.kind === "cancel"
                                    ? "danger"
                                    : "primary"
                            }
                        >
                            {controlSubmitting
                                ? "Applying…"
                                : (pendingControl?.label ?? "Continue")}
                        </Button>
                    </div>
                </div>
            </Dialog>

            <Dialog
                closeDisabled={steerSubmitting}
                description="Add context or redirect this Member’s current work. Work already completed stays completed."
                initialFocusRef={steerInputRef}
                isOpen={steerMemberId !== null}
                onClose={closeSteer}
                title={`Steer ${steerMember?.name ?? "Member"}`}
            >
                <div className="run-steer-dialog">
                    <FormField
                        error={steerError}
                        hint="Banksia sends this message to the Member’s active session. Completed work and tool effects are not undone."
                        id="run-steer-message"
                        label="Message"
                    >
                        <Textarea
                            maxLength={4096}
                            onChange={(event) =>
                                setSteerMessage(event.target.value)
                            }
                            placeholder="What should this Member reconsider or do next?"
                            ref={steerInputRef}
                            rows={6}
                            value={steerMessage}
                        />
                    </FormField>
                    <DialogFooter>
                        <Button disabled={steerSubmitting} onClick={closeSteer}>
                            Cancel
                        </Button>
                        <Button
                            disabled={
                                steerSubmitting || steerMessage.trim() === ""
                            }
                            onClick={() => void handleSteer()}
                            tone="primary"
                        >
                            {steerSubmitting ? "Steering…" : "Steer"}
                        </Button>
                    </DialogFooter>
                </div>
            </Dialog>
        </section>
    );
}

function findTaskMember(
    team: TaskMemberView | null,
    memberId: string | null,
): TaskMemberView | null {
    if (team === null || memberId === null || team.id === memberId) {
        return memberId === null ? null : team;
    }
    for (const child of team.children) {
        const match = findTaskMember(child, memberId);
        if (match !== null) {
            return match;
        }
    }
    return null;
}

function ActionIcon({ kind }: { readonly kind: string }): ReactNode {
    switch (kind) {
        case "pause":
            return <Pause aria-hidden="true" size={16} />;
        case "resume":
            return <Play aria-hidden="true" size={16} />;
        case "cancel":
            return <Square aria-hidden="true" size={15} />;
        default:
            return null;
    }
}
