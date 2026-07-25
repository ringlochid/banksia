import { Button, Notice } from "../../components/ui";
import { WorkflowCard } from "./WorkflowCard";
import type { WorkflowLibrarySearch } from "./useWorkflowLibrarySearch";

export interface WorkflowLibraryResultsProps {
    readonly onCreate: () => void;
    readonly search: WorkflowLibrarySearch;
}

export function WorkflowLibraryResults({
    onCreate,
    search,
}: WorkflowLibraryResultsProps) {
    if (search.isLoading) {
        return (
            <div className="workflow-library__state" role="status">
                Loading Workflows…
            </div>
        );
    }
    if (search.error !== null) {
        return (
            <Notice tone="danger" urgent>
                {search.error} Try refreshing this page.
            </Notice>
        );
    }
    if (search.items.length === 0) {
        return (
            <EmptyWorkflowLibrary onCreate={onCreate} query={search.search} />
        );
    }
    return (
        <>
            <div className="workflow-library__grid">
                {search.items.map((workflow) => (
                    <WorkflowCard
                        key={workflow.workflow_id}
                        workflow={workflow}
                    />
                ))}
            </div>
            {search.moreError === null ? null : (
                <Notice tone="danger" urgent>
                    {search.moreError} Try showing more again.
                </Notice>
            )}
            {search.nextCursor === null ? null : (
                <div className="workflow-library__more">
                    <Button
                        disabled={search.isLoadingMore}
                        onClick={() => void search.loadMore()}
                    >
                        {search.isLoadingMore
                            ? "Loading more…"
                            : "Show more Workflows"}
                    </Button>
                </div>
            )}
        </>
    );
}

interface EmptyWorkflowLibraryProps {
    readonly onCreate: () => void;
    readonly query: string;
}

function EmptyWorkflowLibrary({ onCreate, query }: EmptyWorkflowLibraryProps) {
    const isSearching = query !== "";
    return (
        <div className="workflow-library__state">
            <h2>{isSearching ? "No matches" : "No Workflows yet"}</h2>
            <p>
                {isSearching
                    ? "Try another name or purpose."
                    : "Create a reusable team for work you do more than once."}
            </p>
            {isSearching ? null : (
                <Button onClick={onCreate} tone="primary">
                    Create your first Workflow
                </Button>
            )}
        </div>
    );
}
