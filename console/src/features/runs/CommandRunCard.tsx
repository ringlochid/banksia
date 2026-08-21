import { Copy, RefreshCw, Square, Terminal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
    Button,
    Dialog,
    Notice,
    PageState,
    Prose,
    SearchInput,
} from "../../components/ui";
import { errorMessage, formatRunDate } from "./run-presentation";
import type {
    CommandRunOutputPage,
    CommandRunView,
    ProductAction,
    RunApi,
} from "./run-api";

export interface CommandRunCardProps {
    readonly api: RunApi;
    readonly command: CommandRunView;
    readonly onCancel: (
        command: CommandRunView,
        action: ProductAction,
    ) => Promise<string>;
    readonly taskId: string;
}

export function CommandRunCard({
    api,
    command,
    onCancel,
    taskId,
}: CommandRunCardProps) {
    const [outputOpen, setOutputOpen] = useState(false);
    const [cancelPending, setCancelPending] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [receipt, setReceipt] = useState<string | null>(null);

    async function cancelCommand(): Promise<void> {
        if (
            command.cancel_action === null ||
            command.cancel_action === undefined
        ) {
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            setReceipt(await onCancel(command, command.cancel_action));
            setCancelPending(false);
        } catch (reason) {
            setError(errorMessage(reason));
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <article className="run-command">
            <div className="run-command__heading">
                <span className="run-command__icon" aria-hidden="true">
                    <Terminal size={18} />
                </span>
                <div>
                    <h3>{command.purpose}</h3>
                    <span>
                        {command.member?.name ?? "Team"} ·{" "}
                        {commandStateLabel(command.state)}
                    </span>
                </div>
            </div>
            {command.outcome_summary === null ||
            command.outcome_summary === undefined ? null : (
                <Prose>{command.outcome_summary}</Prose>
            )}
            <dl className="run-command__facts">
                <div>
                    <dt>Started</dt>
                    <dd>
                        {command.started_at === null ||
                        command.started_at === undefined
                            ? "Waiting to start"
                            : formatRunDate(command.started_at)}
                    </dd>
                </div>
                {command.elapsed_seconds === null ||
                command.elapsed_seconds === undefined ? null : (
                    <div>
                        <dt>Elapsed</dt>
                        <dd>{formatDuration(command.elapsed_seconds)}</dd>
                    </div>
                )}
            </dl>
            {error === null ? null : (
                <Notice tone="danger" urgent>
                    <Prose>{error}</Prose>
                </Notice>
            )}
            {receipt === null ? null : (
                <Notice tone="info">
                    <Prose>{receipt}</Prose>
                </Notice>
            )}
            <div className="run-command__actions">
                <Button onClick={() => setOutputOpen(true)}>View output</Button>
                {command.cancel_action === null ||
                command.cancel_action === undefined ? null : (
                    <Button
                        disabled={submitting}
                        onClick={() => setCancelPending(true)}
                        tone="quiet"
                    >
                        <Square aria-hidden="true" size={15} />
                        Cancel action
                    </Button>
                )}
            </div>
            {cancelPending &&
            command.cancel_action !== null &&
            command.cancel_action !== undefined ? (
                <div className="run-command__confirm">
                    <strong>{command.cancel_action.confirmation.title}</strong>
                    <Prose>
                        {command.cancel_action.confirmation.consequence}
                    </Prose>
                    <div>
                        <Button
                            disabled={submitting}
                            onClick={() => setCancelPending(false)}
                        >
                            Keep running
                        </Button>
                        <Button
                            disabled={submitting}
                            onClick={() => void cancelCommand()}
                            tone="danger"
                        >
                            {submitting ? "Cancelling…" : "Cancel action"}
                        </Button>
                    </div>
                </div>
            ) : null}
            <CommandOutputDialog
                api={api}
                command={command}
                isOpen={outputOpen}
                key={String(outputOpen)}
                onClose={() => setOutputOpen(false)}
                taskId={taskId}
            />
        </article>
    );
}

function CommandOutputDialog({
    api,
    command,
    isOpen,
    onClose,
    taskId,
}: {
    readonly api: RunApi;
    readonly command: CommandRunView;
    readonly isOpen: boolean;
    readonly onClose: () => void;
    readonly taskId: string;
}) {
    const [output, setOutput] = useState<CommandRunOutputPage | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState("");
    const [reloadKey, setReloadKey] = useState(0);
    const [copyMessage, setCopyMessage] = useState<string | null>(null);

    useEffect(() => {
        if (!isOpen) {
            return;
        }
        const controller = new AbortController();
        void api
            .getCommandOutput(taskId, command.id, controller.signal)
            .then(({ body }) => setOutput(body))
            .catch((reason: unknown) => {
                if (!controller.signal.aborted) {
                    setError(errorMessage(reason));
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) {
                    setLoading(false);
                }
            });
        return () => controller.abort();
    }, [api, command.id, isOpen, reloadKey, taskId]);

    const visibleOutput = useMemo(() => {
        if (output === null || query.trim() === "") {
            return output?.content ?? "";
        }
        const needle = query.trim().toLocaleLowerCase();
        return output.content
            .split("\n")
            .filter((line) => line.toLocaleLowerCase().includes(needle))
            .join("\n");
    }, [output, query]);

    async function copyOutput(): Promise<void> {
        try {
            await navigator.clipboard.writeText(visibleOutput);
            setCopyMessage("Visible output copied.");
        } catch {
            setCopyMessage(
                "Copy is unavailable here. Select the output text instead.",
            );
        }
    }

    return (
        <Dialog
            isOpen={isOpen}
            onClose={onClose}
            title={`Output: ${command.purpose}`}
        >
            <div className="run-output">
                <div className="run-output__tools">
                    <SearchInput
                        id="command-output-search"
                        label="Search visible output"
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Search visible output"
                        value={query}
                    />
                    <Button
                        disabled={output === null || visibleOutput === ""}
                        onClick={() => void copyOutput()}
                    >
                        <Copy aria-hidden="true" size={15} />
                        Copy
                    </Button>
                </div>
                {copyMessage === null ? null : (
                    <p role="status">{copyMessage}</p>
                )}
                {loading ? (
                    <PageState
                        className="run-output__state"
                        kind="loading"
                        title="Loading output"
                    />
                ) : error !== null ? (
                    <Notice tone="danger" urgent>
                        <Prose>{error}</Prose>
                        <Button
                            onClick={() => {
                                setLoading(true);
                                setError(null);
                                setReloadKey((key) => key + 1);
                            }}
                        >
                            <RefreshCw aria-hidden="true" size={16} />
                            Try again
                        </Button>
                    </Notice>
                ) : output === null ? null : (
                    <>
                        {output.is_missing ? (
                            <Notice tone="warning">
                                The output file is missing from the workspace.
                            </Notice>
                        ) : null}
                        {output.is_changed ? (
                            <Notice tone="warning">
                                The workspace output changed after Oh My
                                Subagents recorded this Action.
                            </Notice>
                        ) : null}
                        {output.is_bounded || !output.output_complete ? (
                            <Notice tone="info">
                                {output.output_complete
                                    ? "Only a bounded part of the output is shown."
                                    : "The output is incomplete. Only observed content is shown."}
                            </Notice>
                        ) : null}
                        <pre
                            aria-label="Command output"
                            className="run-output__content"
                            tabIndex={0}
                        >
                            {visibleOutput === ""
                                ? "No matching output."
                                : visibleOutput}
                        </pre>
                    </>
                )}
            </div>
        </Dialog>
    );
}

function commandStateLabel(state: CommandRunView["state"]): string {
    switch (state) {
        case "queued":
            return "Waiting to start";
        case "running":
            return "Running";
        case "cancelling":
            return "Cancelling";
        case "succeeded":
            return "Succeeded";
        case "failed":
            return "Failed";
        case "timed_out":
            return "Timed out";
        case "cancelled":
            return "Cancelled";
    }
}

function formatDuration(seconds: number): string {
    if (seconds < 60) {
        return `${Math.max(0, Math.round(seconds))} seconds`;
    }
    const minutes = Math.floor(seconds / 60);
    const remaining = Math.round(seconds % 60);
    return remaining === 0
        ? `${minutes} minutes`
        : `${minutes} minutes ${remaining} seconds`;
}
