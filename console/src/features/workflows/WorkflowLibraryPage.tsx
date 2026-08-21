import { Plus } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import type { WorkflowApi } from "../../api/client";
import type { WorkflowSearchItem } from "../../api/types";
import { Button, SearchInput } from "../../components/ui";
import { CreateWorkflowDialog } from "./CreateWorkflowDialog";
import { RemoveWorkflowDialog } from "./RemoveWorkflowDialog";
import { WorkflowLibraryResults } from "./WorkflowLibraryResults";
import { useWorkflowLibrarySearch } from "./useWorkflowLibrarySearch";

export interface WorkflowLibraryPageProps {
    readonly api: WorkflowApi;
}

export function WorkflowLibraryPage({ api }: WorkflowLibraryPageProps) {
    const navigate = useNavigate();
    const [searchParameters, setSearchParameters] = useSearchParams();
    const [createOpen, setCreateOpen] = useState(false);
    const createTriggerRef = useRef<HTMLButtonElement | null>(null);
    const [workflowToRemove, setWorkflowToRemove] =
        useState<WorkflowSearchItem | null>(null);
    const librarySearch = useWorkflowLibrarySearch(api);
    const createRequested = searchParameters.get("create") === "1";

    function closeCreate(): void {
        setCreateOpen(false);
        requestAnimationFrame(() => createTriggerRef.current?.focus());
        if (!createRequested) {
            return;
        }
        const nextParameters = new URLSearchParams(searchParameters);
        nextParameters.delete("create");
        setSearchParameters(nextParameters, { replace: true });
    }

    return (
        <section className="page">
            <header className="page__header">
                <div className="page__heading">
                    <h1 className="page__title">Workflows</h1>
                </div>
                <div className="page__actions">
                    <Button
                        onClick={(event) => {
                            createTriggerRef.current = event.currentTarget;
                            setCreateOpen(true);
                        }}
                        tone="primary"
                    >
                        <Plus aria-hidden="true" size={15} />
                        Create workflow
                    </Button>
                </div>
            </header>

            <div className="page__toolbar">
                <SearchInput
                    autoComplete="off"
                    id="workflow-search"
                    label="Search workflows"
                    onChange={(event) =>
                        librarySearch.updateQuery(event.target.value)
                    }
                    placeholder="Search workflows"
                    value={librarySearch.query}
                />
            </div>

            <div className="page__body">
                <WorkflowLibraryResults
                    onCreate={() => setCreateOpen(true)}
                    onRemove={setWorkflowToRemove}
                    search={librarySearch}
                />
            </div>

            <CreateWorkflowDialog
                api={api}
                isOpen={createOpen || createRequested}
                onClose={closeCreate}
                onCreated={(workflowId) => {
                    setCreateOpen(false);
                    void navigate(
                        `/workflows/${encodeURIComponent(workflowId)}`,
                    );
                }}
            />
            {workflowToRemove === null ? null : (
                <RemoveWorkflowDialog
                    api={api}
                    key={workflowToRemove.workflow_id}
                    onClose={() => setWorkflowToRemove(null)}
                    onRemoved={(workflowId) => {
                        librarySearch.removeItem(workflowId);
                        setWorkflowToRemove(null);
                    }}
                    workflow={workflowToRemove}
                />
            )}
        </section>
    );
}
