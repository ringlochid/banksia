import { ListChecks, Plus, RefreshCw, SearchX } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import {
    Badge,
    Button,
    Notice,
    PageState,
    Prose,
    SearchInput,
} from "../../components/ui";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import {
    errorMessage,
    formatRunDate,
    runStatusLabel,
} from "./run-presentation";
import type { RunApi, TaskSearchResponse } from "./run-api";

export interface RunListPageProps {
    readonly api: RunApi;
}

type RunItem = TaskSearchResponse["items"][number];

export function RunListPage({ api }: RunListPageProps) {
    const [draftQuery, setDraftQuery] = useState("");
    // Runs filter as you type, exactly like the workflow library. There is no
    // submit button: the Console has one search interaction, not two.
    const query = useDebouncedValue(draftQuery.trim(), 250);
    const [items, setItems] = useState<RunItem[]>([]);
    const [nextCursor, setNextCursor] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        void api
            .searchRuns(query, null, controller.signal)
            .then(({ body }) => {
                setItems(body.items);
                setNextCursor(body.next_cursor ?? null);
                setError(null);
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
    }, [api, query, reloadKey]);

    function retry(): void {
        setError(null);
        setLoading(true);
        setReloadKey((key) => key + 1);
    }

    function updateQuery(value: string): void {
        setDraftQuery(value);
        if (value.trim() !== query) {
            setLoading(true);
        }
    }

    async function handleLoadMore(): Promise<void> {
        if (nextCursor === null) {
            return;
        }
        setLoadingMore(true);
        setError(null);
        try {
            const response = await api.searchRuns(query, nextCursor);
            setItems((current) => [...current, ...response.body.items]);
            setNextCursor(response.body.next_cursor ?? null);
        } catch (reason) {
            setError(errorMessage(reason));
        } finally {
            setLoadingMore(false);
        }
    }

    return (
        <section className="page">
            <header className="page__header">
                <div className="page__heading">
                    <h1 className="page__title">Runs</h1>
                </div>
                <div className="page__actions">
                    <Link
                        className="ui-button ui-button--primary"
                        to="/runs/new"
                    >
                        <Plus aria-hidden="true" size={15} />
                        Start run
                    </Link>
                </div>
            </header>

            <div className="page__toolbar">
                <SearchInput
                    autoComplete="off"
                    id="run-search"
                    label="Search runs"
                    onChange={(event) => updateQuery(event.target.value)}
                    placeholder="Search runs"
                    value={draftQuery}
                />
            </div>

            <div className="page__body">
                {loading ? (
                    <PageState fill kind="loading" title="Loading Runs" />
                ) : error !== null && items.length === 0 ? (
                    <RunListError message={error} onRetry={retry} />
                ) : items.length === 0 ? (
                    <EmptyRunList isSearching={query !== ""} />
                ) : (
                    <>
                        {error === null ? null : (
                            <Notice tone="danger" urgent>
                                <Prose>{error}</Prose>
                            </Notice>
                        )}
                        <div className="run-list">
                            {items.map((run) => (
                                <RunRow key={run.id} run={run} />
                            ))}
                        </div>
                        {nextCursor === null ? null : (
                            <div className="run-list__more">
                                <Button
                                    disabled={loadingMore}
                                    onClick={() => void handleLoadMore()}
                                >
                                    {loadingMore ? "Loading…" : "Show more"}
                                </Button>
                            </div>
                        )}
                    </>
                )}
            </div>
        </section>
    );
}

/**
 * One row per Run. The status is shown once, as a dot plus a label; the
 * status sentence is not repeated beside it.
 */
function RunRow({ run }: { readonly run: RunItem }) {
    return (
        <Link
            aria-label={`Open Run: ${run.prompt_excerpt}`}
            className="run-row"
            to={`/runs/${encodeURIComponent(run.id)}`}
        >
            <span
                aria-hidden="true"
                className={`run-dot run-dot--${run.status}`}
            />
            <div className="run-row__main">
                <h2 className="run-row__prompt">{run.prompt_excerpt}</h2>
                <p className="run-row__workflow">{run.workflow.id}</p>
            </div>
            <div className="run-row__meta">
                {run.attention_count > 0 ? (
                    <Badge tone="accent">
                        {run.attention_count === 1
                            ? "1 needs you"
                            : `${String(run.attention_count)} need you`}
                    </Badge>
                ) : null}
                <span className="run-row__status">
                    {runStatusLabel(run.status)}
                </span>
                <span className="run-row__date">
                    {formatRunDate(run.updated_at)}
                </span>
            </div>
        </Link>
    );
}

function RunListError({
    message,
    onRetry,
}: {
    readonly message: string;
    readonly onRetry: () => void;
}) {
    return (
        <PageState
            actions={
                <Button onClick={onRetry}>
                    <RefreshCw aria-hidden="true" size={15} />
                    Try again
                </Button>
            }
            detail={message}
            fill
            kind="error"
            title="Runs could not be loaded"
        />
    );
}

function EmptyRunList({ isSearching }: { readonly isSearching: boolean }) {
    return (
        <PageState
            actions={
                isSearching ? undefined : (
                    <Link
                        className="ui-button ui-button--primary"
                        to="/runs/new"
                    >
                        Start Run
                    </Link>
                )
            }
            fill
            icon={isSearching ? SearchX : ListChecks}
            title={isSearching ? "No Runs match this search" : "No Runs yet"}
        />
    );
}
