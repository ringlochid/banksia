import { SearchX, Workflow } from "lucide-react";

import type { WorkflowSearchItem } from "../../api/types";
import { Button, Notice, PageState, Prose } from "../../components/ui";
import { WorkflowCard } from "./WorkflowCard";
import type { WorkflowLibrarySearch } from "./useWorkflowLibrarySearch";

export interface WorkflowLibraryResultsProps {
    readonly onCreate: () => void;
    readonly onRemove: (workflow: WorkflowSearchItem) => void;
    readonly search: WorkflowLibrarySearch;
}

export function WorkflowLibraryResults({
    onCreate,
    onRemove,
    search,
}: WorkflowLibraryResultsProps) {
    if (search.isLoading) {
        return <PageState fill kind="loading" title="Loading Workflows" />;
    }
    if (search.error !== null) {
        return (
            <PageState
                actions={<Button onClick={search.retry}>Try again</Button>}
                detail={search.error}
                fill
                kind="error"
                title="Workflows could not be loaded"
            />
        );
    }
    if (search.items.length === 0) {
        return (
            <EmptyWorkflowLibrary onCreate={onCreate} query={search.search} />
        );
    }
    return (
        <>
            <div className="workflow-list">
                {search.items.map((workflow) => (
                    <WorkflowCard
                        key={workflow.workflow_id}
                        onRemove={onRemove}
                        workflow={workflow}
                    />
                ))}
            </div>
            {search.moreError === null ? null : (
                <Notice tone="danger" urgent>
                    <Prose>{search.moreError}</Prose>
                </Notice>
            )}
            {search.nextCursor === null ? null : (
                <div className="workflow-list__more">
                    <Button
                        aria-label="Show more Workflows"
                        disabled={search.isLoadingMore}
                        onClick={() => void search.loadMore()}
                    >
                        {search.isLoadingMore ? "Loading…" : "Show more"}
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
        <PageState
            actions={
                isSearching ? undefined : (
                    <Button onClick={onCreate} tone="primary">
                        Create Workflow
                    </Button>
                )
            }
            fill
            icon={isSearching ? SearchX : Workflow}
            title={
                isSearching
                    ? "No Workflows match this search"
                    : "No Workflows yet"
            }
        />
    );
}
