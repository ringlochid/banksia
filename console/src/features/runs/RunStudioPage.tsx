import { ArrowLeft, Pause, Play, RefreshCw, Square } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { Button, Card, Dialog, Notice } from "../../components/ui";
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
    PlanSection,
    RunResult,
    TeamSection,
} from "./RunSections";
import type {
    CommandRunView,
    HumanRequestResponseInput,
    ProductAction,
    RunApi,
} from "./run-api";
import { useRunLive } from "./use-run-live";

export interface RunStudioPageProps {
    readonly api: RunApi;
}

interface RunLocationState {
    readonly startMessage?: string;
}

interface RunStudioTaskProps extends RunStudioPageProps {
    readonly startMessage: string | undefined;
    readonly taskId: string;
}

export function RunStudioPage({ api }: RunStudioPageProps) {
    const { taskId } = useParams();
    const location = useLocation();
    const startMessage = (location.state as RunLocationState | null)
        ?.startMessage;

    if (taskId === undefined) {
        return (
            <section className="page-frame run-studio">
                <Notice tone="danger">This Run link is incomplete.</Notice>
            </section>
        );
    }
    return (
        <RunStudioTask
            api={api}
            key={taskId}
            startMessage={startMessage}
            taskId={taskId}
        />
    );
}

function RunStudioTask({ api, startMessage, taskId }: RunStudioTaskProps) {
    const {
        activities,
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
    const [receipt, setReceipt] = useState<string | null>(startMessage ?? null);
    const [pendingControl, setPendingControl] = useState<ProductAction | null>(
        null,
    );
    const [controlSubmitting, setControlSubmitting] = useState(false);
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

    if (loading) {
        return (
            <section className="page-frame run-studio">
                <div className="run-studio__state" role="status">
                    Loading Run…
                </div>
            </section>
        );
    }
    if (task === null) {
        return (
            <section className="page-frame run-studio">
                <Link className="run-back-link" to="/runs">
                    <ArrowLeft aria-hidden="true" size={17} />
                    Back to Runs
                </Link>
                <Notice tone="danger" urgent>
                    <p>
                        {error ??
                            "Banksia could not find controller truth for this Run."}
                    </p>
                    <Button disabled={refreshing} onClick={() => refreshRun()}>
                        <RefreshCw aria-hidden="true" size={16} />
                        {refreshing ? "Trying again…" : "Try again"}
                    </Button>
                </Notice>
            </section>
        );
    }

    const openRequests = task.human_requests.filter(
        (request) => request.status === "open",
    );
    const otherAttention = task.attention.filter(
        (attention) => attention.kind !== "human_request",
    );

    return (
        <section className="page-frame run-studio">
            <Link className="run-back-link" to="/runs">
                <ArrowLeft aria-hidden="true" size={17} />
                Back to Runs
            </Link>
            <header className="run-studio__header">
                <div>
                    <div className="run-studio__status-line">
                        <span
                            className={`run-status run-status--${task.status}`}
                        >
                            {runStatusLabel(task.status)}
                        </span>
                        <span>{task.workflow.id}</span>
                    </div>
                    <h1>{task.prompt_excerpt}</h1>
                    <p>{task.status_message}</p>
                    <span className="run-studio__updated">
                        Updated {formatRunDate(task.updated_at)}
                    </span>
                </div>
                <div className="run-studio__header-actions">
                    <Button
                        aria-label="Refresh Run"
                        disabled={refreshing}
                        onClick={() => refreshRun()}
                    >
                        <RefreshCw
                            aria-hidden="true"
                            className={refreshing ? "is-spinning" : ""}
                            size={16}
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
            </header>

            {receipt === null ? null : <Notice tone="info">{receipt}</Notice>}
            {liveDelayed ? (
                <Notice tone="info">
                    <p>
                        Live updates are delayed. This Run may be slightly out
                        of date.
                    </p>
                    <Button onClick={retryLive}>
                        <RefreshCw aria-hidden="true" size={16} />
                        Retry
                    </Button>
                </Notice>
            ) : null}
            {error === null ? null : (
                <Notice tone="danger" urgent>
                    {error} Refresh to read current Run state.
                </Notice>
            )}

            {task.result === null || task.result === undefined ? null : (
                <RunResult result={task.result} />
            )}

            {openRequests.length === 0 && otherAttention.length === 0 ? null : (
                <section
                    aria-labelledby="run-attention-title"
                    className="run-attention"
                >
                    <div>
                        <p className="run-section-kicker">Action needed</p>
                        <h2 id="run-attention-title">Needs your attention</h2>
                    </div>
                    {openRequests.map((request) => (
                        <HumanRequestCard
                            key={request.id}
                            onRespond={handleHumanResponse}
                            request={request}
                        />
                    ))}
                    {otherAttention.map((attention) => (
                        <Card
                            as="article"
                            className="run-attention__item"
                            key={attention.id}
                        >
                            <h3>{attention.title}</h3>
                            <p>{attention.summary}</p>
                            {attention.member === null ||
                            attention.member === undefined ? null : (
                                <span>{attention.member.name}</span>
                            )}
                            <FileReferences compact files={attention.files} />
                            {attention.link === null ||
                            attention.link === undefined ? null : (
                                <a
                                    className="ui-button ui-button--secondary"
                                    href={attention.link.href}
                                >
                                    {attention.link.label}
                                </a>
                            )}
                        </Card>
                    ))}
                </section>
            )}

            <div className="run-studio__columns">
                <div>
                    <TeamSection team={task.team} />
                    {task.plan === null || task.plan === undefined ? null : (
                        <PlanSection plan={task.plan} />
                    )}
                </div>
                <div>
                    <ActivitySection
                        activities={activities}
                        isTruncated={task.activities_truncated}
                    />
                    {task.command_runs.length === 0 ? null : (
                        <Card
                            aria-labelledby="run-actions-title"
                            className="run-section"
                        >
                            <div className="run-section-heading">
                                <div>
                                    <p className="run-section-kicker">
                                        Work in the world
                                    </p>
                                    <h2 id="run-actions-title">Actions</h2>
                                </div>
                            </div>
                            <div className="run-commands">
                                {task.command_runs.map((command) => (
                                    <CommandRunCard
                                        api={api}
                                        command={command}
                                        key={command.id}
                                        onCancel={handleCommandCancel}
                                        taskId={task.id}
                                    />
                                ))}
                            </div>
                            {task.command_runs_truncated ? (
                                <p className="run-bounded-note">
                                    This view shows the most recent Actions.
                                </p>
                            ) : null}
                        </Card>
                    )}
                </div>
            </div>

            <Dialog
                closeDisabled={controlSubmitting}
                isOpen={pendingControl !== null}
                onClose={() => setPendingControl(null)}
                title={pendingControl?.confirmation.title ?? "Confirm action"}
            >
                <div className="run-control-dialog">
                    <p>{pendingControl?.confirmation.consequence}</p>
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
        </section>
    );
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
