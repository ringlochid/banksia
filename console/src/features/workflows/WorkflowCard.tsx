import { ArrowRight, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import type { WorkflowSearchItem } from "../../api/types";
import { Card } from "../../components/ui";

export interface WorkflowCardProps {
    readonly workflow: WorkflowSearchItem;
}

export function WorkflowCard({ workflow }: WorkflowCardProps) {
    return (
        <Card as="article" className="workflow-card">
            <div className="workflow-card__heading">
                <div>
                    <h2>{workflow.workflow_id}</h2>
                    <div className="workflow-card__badges">
                        <span
                            className={`workflow-state workflow-state--${workflow.state}`}
                        >
                            {stateLabel(workflow.state)}
                        </span>
                        {workflow.provenance === "starter_seed" ? (
                            <span className="workflow-starter">
                                <Sparkles aria-hidden="true" size={14} />
                                Starter
                            </span>
                        ) : null}
                    </div>
                </div>
                <span className="workflow-card__date">
                    Updated {formatDate(workflow.updated_at)}
                </span>
            </div>
            <p>{workflow.description}</p>
            <footer className="workflow-card__footer">
                <span>{stateSummary(workflow.state)}</span>
                <Link
                    aria-label={`Open ${workflow.workflow_id}`}
                    className="workflow-card__open"
                    to={`/workflows/${encodeURIComponent(workflow.workflow_id)}`}
                >
                    Open
                    <ArrowRight aria-hidden="true" size={17} />
                </Link>
            </footer>
        </Card>
    );
}

function stateLabel(state: WorkflowSearchItem["state"]): string {
    switch (state) {
        case "draft":
            return "Draft";
        case "published":
            return "Published";
        case "published_with_draft":
            return "Published · draft changes";
    }
}

function stateSummary(state: WorkflowSearchItem["state"]): string {
    switch (state) {
        case "draft":
            return "Draft in progress";
        case "published":
            return "Published team";
        case "published_with_draft":
            return "Published with draft changes";
    }
}

function formatDate(value: string): string {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) {
        return value;
    }
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
    }).format(parsed);
}
