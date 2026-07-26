import { ArrowRight, Plus, RefreshCw, Search } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { Button, Card, Notice } from "../../components/ui";
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
    const [query, setQuery] = useState("");
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

    function handleSearch(event: FormEvent<HTMLFormElement>): void {
        event.preventDefault();
        const nextQuery = draftQuery.trim();
        setLoading(true);
        setError(null);
        if (nextQuery === query) {
            setReloadKey((key) => key + 1);
        } else {
            setQuery(nextQuery);
        }
    }

    function retry(): void {
        setLoading(true);
        setError(null);
        setReloadKey((key) => key + 1);
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
        <section className="page-frame run-list">
            <header className="run-list__header">
                <div>
                    <p className="run-eyebrow">Commissioned work</p>
                    <h1>Runs</h1>
                    <p>
                        Follow what your teams are doing, respond when they need
                        you, and read the final result.
                    </p>
                </div>
                <Link className="ui-button ui-button--primary" to="/runs/new">
                    <Plus aria-hidden="true" size={18} />
                    Start run
                </Link>
            </header>

            <form className="run-search" onSubmit={handleSearch}>
                <Search aria-hidden="true" size={18} />
                <label className="sr-only" htmlFor="run-search">
                    Search Runs
                </label>
                <input
                    id="run-search"
                    onChange={(event) => setDraftQuery(event.target.value)}
                    placeholder="Search by prompt or Workflow"
                    type="search"
                    value={draftQuery}
                />
                <Button type="submit">Search</Button>
            </form>

            {loading ? (
                <div className="run-list__state" role="status">
                    Loading Runs…
                </div>
            ) : error !== null && items.length === 0 ? (
                <RunListError message={error} onRetry={retry} />
            ) : items.length === 0 ? (
                <EmptyRunList isSearching={query !== ""} />
            ) : (
                <>
                    {error === null ? null : (
                        <Notice tone="danger" urgent>
                            {error} Try showing more again.
                        </Notice>
                    )}
                    <div className="run-list__items">
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
                                {loadingMore
                                    ? "Loading more…"
                                    : "Show more Runs"}
                            </Button>
                        </div>
                    )}
                </>
            )}
        </section>
    );
}

function RunRow({ run }: { readonly run: RunItem }) {
    return (
        <Card as="article" className="run-row">
            <div className="run-row__status">
                <span
                    className={`run-status run-status--${run.status}`}
                    data-status={run.status}
                >
                    {runStatusLabel(run.status)}
                </span>
                <span>{formatRunDate(run.updated_at)}</span>
            </div>
            <div className="run-row__body">
                <div>
                    <h2>{run.prompt_excerpt}</h2>
                    <p>{run.workflow.description}</p>
                </div>
                <div className="run-row__meta">
                    <span>{run.workflow.id}</span>
                    {run.attention_count > 0 ? (
                        <strong>
                            {run.attention_count}{" "}
                            {run.attention_count === 1 ? "item" : "items"} need
                            you
                        </strong>
                    ) : (
                        <span>{run.status_message}</span>
                    )}
                </div>
            </div>
            <Link
                aria-label={`Open Run: ${run.prompt_excerpt}`}
                className="run-row__open"
                to={`/runs/${encodeURIComponent(run.id)}`}
            >
                Open Run
                <ArrowRight aria-hidden="true" size={17} />
            </Link>
        </Card>
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
        <Notice tone="danger" urgent>
            <p>{message}</p>
            <Button onClick={onRetry}>
                <RefreshCw aria-hidden="true" size={16} />
                Try again
            </Button>
        </Notice>
    );
}

function EmptyRunList({ isSearching }: { readonly isSearching: boolean }) {
    return (
        <div className="run-list__state">
            <h2>{isSearching ? "No matching Runs" : "No Runs yet"}</h2>
            <p>
                {isSearching
                    ? "Try a different prompt or Workflow name."
                    : "Start a Run when you have work for one of your published teams."}
            </p>
            {isSearching ? null : (
                <Link className="ui-button ui-button--primary" to="/runs/new">
                    Start your first Run
                </Link>
            )}
        </div>
    );
}
