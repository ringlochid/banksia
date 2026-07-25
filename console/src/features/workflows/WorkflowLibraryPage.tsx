import { Plus, Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { WorkflowApi } from "../../api/client";
import { Button } from "../../components/ui";
import { CreateWorkflowDialog } from "./CreateWorkflowDialog";
import { WorkflowLibraryResults } from "./WorkflowLibraryResults";
import { useWorkflowLibrarySearch } from "./useWorkflowLibrarySearch";

export interface WorkflowLibraryPageProps {
    readonly api: WorkflowApi;
}

export function WorkflowLibraryPage({ api }: WorkflowLibraryPageProps) {
    const navigate = useNavigate();
    const [createOpen, setCreateOpen] = useState(false);
    const librarySearch = useWorkflowLibrarySearch(api);

    return (
        <section className="page-frame workflow-library">
            <header className="workflow-library__header">
                <div>
                    <p className="workflow-library__eyebrow">AI teams</p>
                    <h1>Workflows</h1>
                    <p>
                        Build a reusable team of Members, each with a clear
                        responsibility. Connections show who owns whose work—not
                        the order work happens.
                    </p>
                </div>
                <Button onClick={() => setCreateOpen(true)} tone="primary">
                    <Plus aria-hidden="true" size={18} />
                    Create Workflow
                </Button>
            </header>

            <div className="workflow-search">
                <Search aria-hidden="true" size={18} />
                <label className="sr-only" htmlFor="workflow-search">
                    Search Workflows
                </label>
                <input
                    autoComplete="off"
                    id="workflow-search"
                    onChange={(event) =>
                        librarySearch.updateQuery(event.target.value)
                    }
                    placeholder="Search by name or purpose"
                    type="search"
                    value={librarySearch.query}
                />
            </div>

            <WorkflowLibraryResults
                onCreate={() => setCreateOpen(true)}
                search={librarySearch}
            />

            <CreateWorkflowDialog
                api={api}
                isOpen={createOpen}
                onClose={() => setCreateOpen(false)}
                onCreated={(workflowId) => {
                    setCreateOpen(false);
                    void navigate(
                        `/workflows/${encodeURIComponent(workflowId)}`,
                    );
                }}
            />
        </section>
    );
}
