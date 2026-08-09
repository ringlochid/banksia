import * as Popover from "@radix-ui/react-popover";
import { EllipsisVertical, Sparkles, Trash2 } from "lucide-react";
import { Link } from "react-router";

import type { WorkflowSearchItem } from "../../api/types";
import { Badge, Button } from "../../components/ui";

export interface WorkflowCardProps {
    readonly onRemove: (workflow: WorkflowSearchItem) => void;
    readonly workflow: WorkflowSearchItem;
}

/**
 * One row per Workflow. The whole row is the link, so there is no separate
 * "Open" affordance, and the publication state is stated once rather than
 * repeated as both a badge and a footer sentence.
 */
export function WorkflowCard({ onRemove, workflow }: WorkflowCardProps) {
    const canRemove = workflow.available_actions.includes("remove");
    return (
        <article className="workflow-row">
            <Link
                aria-label={`Open ${workflow.workflow_id}`}
                className="workflow-row__link"
                to={`/workflows/${encodeURIComponent(workflow.workflow_id)}`}
            >
                <div className="workflow-row__main">
                    <h2 className="workflow-row__name">
                        {workflow.workflow_id}
                    </h2>
                    {workflow.description === null ||
                    workflow.description === "" ? null : (
                        <p className="workflow-row__purpose">
                            {workflow.description}
                        </p>
                    )}
                </div>
                <div className="workflow-row__meta">
                    <span className="workflow-row__date">
                        Updated {formatDate(workflow.updated_at)}
                    </span>
                    <span className="workflow-row__badges">
                        {workflow.provenance === "starter_seed" ? (
                            <Badge tone="accent">
                                <Sparkles aria-hidden="true" size={11} />
                                Starter
                            </Badge>
                        ) : null}
                        {workflow.has_retired_provider_selection ? (
                            <Badge>Provider repair needed</Badge>
                        ) : null}
                        <Badge tone={badgeTone(workflow.state)}>
                            {stateLabel(workflow.state)}
                        </Badge>
                    </span>
                </div>
            </Link>
            {canRemove ? (
                <Popover.Root>
                    <Popover.Trigger asChild>
                        <Button
                            aria-label={`More actions for ${workflow.workflow_id}`}
                            className="workflow-row__actions-trigger"
                            icon
                            size="sm"
                            tone="quiet"
                        >
                            <EllipsisVertical aria-hidden="true" size={15} />
                        </Button>
                    </Popover.Trigger>
                    <Popover.Portal>
                        <Popover.Content
                            align="end"
                            className="workflow-row-menu"
                            role="menu"
                            sideOffset={4}
                        >
                            <Popover.Close asChild>
                                <button
                                    className="workflow-row-menu__item workflow-row-menu__item--danger"
                                    onClick={() => onRemove(workflow)}
                                    role="menuitem"
                                    type="button"
                                >
                                    <Trash2 aria-hidden="true" size={15} />
                                    Remove workflow
                                </button>
                            </Popover.Close>
                        </Popover.Content>
                    </Popover.Portal>
                </Popover.Root>
            ) : null}
        </article>
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

function badgeTone(state: WorkflowSearchItem["state"]): "neutral" | "brand" {
    return state === "draft" ? "neutral" : "brand";
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
