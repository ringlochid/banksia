import { ArrowLeft, FilePlus2, Play, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button, FormField, Notice } from "../../components/ui";
import { errorMessage } from "./run-presentation";
import type { FileReference, RunApi, WorkflowSearchItem } from "./run-api";

export interface StartRunPageProps {
    readonly api: RunApi;
}

interface FileDraft {
    readonly key: number;
    readonly path: string;
    readonly description: string;
}

export function StartRunPage({ api }: StartRunPageProps) {
    const navigate = useNavigate();
    const [searchParameters] = useSearchParams();
    const preferredWorkflow = searchParameters.get("workflow") ?? "";
    const [workflows, setWorkflows] = useState<WorkflowSearchItem[]>([]);
    const [workflowId, setWorkflowId] = useState(preferredWorkflow);
    const [prompt, setPrompt] = useState("");
    const [workspace, setWorkspace] = useState("");
    const [files, setFiles] = useState<FileDraft[]>([]);
    const [nextFileKey, setNextFileKey] = useState(1);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        void api
            .searchWorkflows(controller.signal)
            .then(({ body }) => {
                const published = body.items.filter(
                    (workflow) => workflow.published_revision_no !== null,
                );
                setWorkflows(published);
                setWorkflowId((current) => {
                    if (
                        current !== "" &&
                        published.some(
                            (workflow) => workflow.workflow_id === current,
                        )
                    ) {
                        return current;
                    }
                    return published[0]?.workflow_id ?? "";
                });
            })
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
    }, [api, reloadKey]);

    async function handleSubmit(
        event: FormEvent<HTMLFormElement>,
    ): Promise<void> {
        event.preventDefault();
        const exactPrompt = prompt.trim();
        if (workflowId === "" || exactPrompt === "") {
            setError("Choose a published Workflow and describe the work.");
            return;
        }
        const referencedFiles = normalizedFiles(files);
        if (referencedFiles === null) {
            setError("Each referenced file needs a workspace-relative path.");
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            const response = await api.startRun({
                workflow: workflowId,
                prompt: exactPrompt,
                files: referencedFiles,
                ...(workspace.trim() === ""
                    ? {}
                    : { workspace: workspace.trim() }),
            });
            void navigate(
                `/runs/${encodeURIComponent(response.body.task_id)}`,
                {
                    state: {
                        startMessage: response.body.status_message,
                    },
                },
            );
        } catch (reason) {
            setError(errorMessage(reason));
        } finally {
            setSubmitting(false);
        }
    }

    function addFile(): void {
        setFiles((current) => [
            ...current,
            { key: nextFileKey, path: "", description: "" },
        ]);
        setNextFileKey((key) => key + 1);
    }

    function updateFile(
        key: number,
        patch: Partial<Pick<FileDraft, "path" | "description">>,
    ): void {
        setFiles((current) =>
            current.map((file) =>
                file.key === key ? { ...file, ...patch } : file,
            ),
        );
    }

    return (
        <section className="page-frame run-start">
            <Link className="run-back-link" to="/runs">
                <ArrowLeft aria-hidden="true" size={17} />
                Back to Runs
            </Link>
            <header>
                <p className="run-eyebrow">New work</p>
                <h1>Start a Run</h1>
                <p>
                    Choose a published team and give it one complete prompt.
                    Banksia will start the work asynchronously.
                </p>
            </header>

            {loading ? (
                <div className="run-start__state" role="status">
                    Loading published Workflows…
                </div>
            ) : error !== null && workflows.length === 0 ? (
                <Notice tone="danger" urgent>
                    <p>{error}</p>
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
            ) : workflows.length === 0 ? (
                <Notice title="Publish a Workflow first" tone="warning">
                    <p>
                        Runs use a published team. Finish and publish a
                        Workflow, then come back here.
                    </p>
                    <Link
                        className="ui-button ui-button--secondary"
                        to="/workflows"
                    >
                        Open Workflows
                    </Link>
                </Notice>
            ) : (
                <form
                    aria-busy={submitting}
                    className="run-start__form"
                    onSubmit={(event) => void handleSubmit(event)}
                >
                    {error === null ? null : (
                        <Notice tone="danger" urgent>
                            {error}
                        </Notice>
                    )}
                    <FormField id="run-workflow" label="Workflow">
                        <select
                            disabled={submitting}
                            onChange={(event) =>
                                setWorkflowId(event.target.value)
                            }
                            value={workflowId}
                        >
                            {workflows.map((workflow) => (
                                <option
                                    key={workflow.workflow_id}
                                    value={workflow.workflow_id}
                                >
                                    {workflow.workflow_id} —{" "}
                                    {workflow.description}
                                </option>
                            ))}
                        </select>
                    </FormField>
                    <FormField
                        hint="Include the outcome, important context, and any constraints the team must follow."
                        id="run-prompt"
                        label="What should the team accomplish?"
                    >
                        <textarea
                            disabled={submitting}
                            onChange={(event) => setPrompt(event.target.value)}
                            required
                            value={prompt}
                        />
                    </FormField>

                    <details className="run-start__advanced">
                        <summary>Advanced</summary>
                        <div className="run-start__advanced-body">
                            <FormField
                                hint="Leave blank to use the installation's configured default workspace."
                                id="run-workspace"
                                label="Workspace"
                                optional
                            >
                                <input
                                    disabled={submitting}
                                    onChange={(event) =>
                                        setWorkspace(event.target.value)
                                    }
                                    placeholder="/path/to/project"
                                    value={workspace}
                                />
                            </FormField>

                            <section
                                aria-labelledby="referenced-files-title"
                                className="run-files-editor"
                            >
                                <div className="run-files-editor__heading">
                                    <div>
                                        <h2 id="referenced-files-title">
                                            Referenced files
                                        </h2>
                                        <p>
                                            Add paths the team should inspect.
                                            Banksia records the path, not a copy
                                            of the file.
                                        </p>
                                    </div>
                                    <Button
                                        disabled={submitting}
                                        onClick={addFile}
                                    >
                                        <FilePlus2
                                            aria-hidden="true"
                                            size={16}
                                        />
                                        Add file
                                    </Button>
                                </div>
                                {files.map((file, index) => (
                                    <FileDraftRow
                                        disabled={submitting}
                                        file={file}
                                        index={index}
                                        key={file.key}
                                        onRemove={() =>
                                            setFiles((current) =>
                                                current.filter(
                                                    (candidate) =>
                                                        candidate.key !==
                                                        file.key,
                                                ),
                                            )
                                        }
                                        onUpdate={(patch) =>
                                            updateFile(file.key, patch)
                                        }
                                    />
                                ))}
                            </section>
                        </div>
                    </details>

                    <div className="run-start__actions">
                        <Link
                            aria-disabled={submitting || undefined}
                            className="ui-button ui-button--quiet"
                            to="/runs"
                        >
                            Cancel
                        </Link>
                        <Button
                            disabled={submitting}
                            tone="primary"
                            type="submit"
                        >
                            <Play aria-hidden="true" size={17} />
                            {submitting ? "Starting…" : "Start run"}
                        </Button>
                    </div>
                </form>
            )}
        </section>
    );
}

function FileDraftRow({
    disabled,
    file,
    index,
    onRemove,
    onUpdate,
}: {
    readonly disabled: boolean;
    readonly file: FileDraft;
    readonly index: number;
    readonly onRemove: () => void;
    readonly onUpdate: (
        patch: Partial<Pick<FileDraft, "path" | "description">>,
    ) => void;
}) {
    const baseId = useId();
    return (
        <div className="run-file-draft">
            <FormField id={`${baseId}-path`} label={`File ${index + 1} path`}>
                <input
                    disabled={disabled}
                    onChange={(event) => onUpdate({ path: event.target.value })}
                    placeholder="docs/research-brief.md"
                    required
                    value={file.path}
                />
            </FormField>
            <FormField
                id={`${baseId}-description`}
                label="Why should the team open it?"
                optional
            >
                <input
                    disabled={disabled}
                    onChange={(event) =>
                        onUpdate({ description: event.target.value })
                    }
                    value={file.description}
                />
            </FormField>
            <Button
                aria-label={`Remove referenced file ${index + 1}`}
                disabled={disabled}
                onClick={onRemove}
                tone="quiet"
            >
                <Trash2 aria-hidden="true" size={16} />
                Remove
            </Button>
        </div>
    );
}

function normalizedFiles(files: readonly FileDraft[]): FileReference[] | null {
    const normalized: FileReference[] = [];
    for (const file of files) {
        const path = file.path.trim();
        if (path === "") {
            return null;
        }
        const description = file.description.trim();
        normalized.push({
            path,
            ...(description === "" ? {} : { description }),
        });
    }
    return normalized;
}
