import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { NormalizedMember } from "../../../api/types";
import { memberTitle, providerSummary } from "./member-presentation";

export type MemberCardNode = Node<MemberCardData, "member">;

export type MemberCardData = {
    readonly collapsed: boolean;
    readonly issueCount: number;
    readonly member: NormalizedMember;
    readonly onSelect: (memberId: string) => void;
    readonly onToggleCollapse: (memberId: string) => void;
    readonly pending: boolean;
    readonly selected: boolean;
} & Record<string, unknown>;

export function MemberCard({ data }: NodeProps<MemberCardNode>) {
    const title = memberTitle(data.member);
    const children = data.member.children ?? [];
    const purpose = data.member.description?.trim();
    const role = children.length > 0 ? "Manager" : "Contributor";

    return (
        <article
            aria-busy={data.pending || undefined}
            className={[
                "team-member-card",
                data.selected ? "team-member-card--selected" : "",
                data.pending ? "team-member-card--pending" : "",
                data.issueCount > 0 ? "team-member-card--invalid" : "",
            ]
                .filter(Boolean)
                .join(" ")}
            data-member-card={data.member.id}
        >
            <Handle
                aria-hidden="true"
                className="team-geometry-handle"
                isConnectable={false}
                position={Position.Left}
                type="target"
            />
            <button
                aria-pressed={data.selected}
                className="team-member-card__select nodrag nopan"
                data-focus-surface="canvas"
                data-member-focus={data.member.id}
                onClick={() => data.onSelect(data.member.id)}
                onPointerDown={(event) => {
                    event.preventDefault();
                }}
                type="button"
            >
                <span aria-hidden="true" className="team-member-card__avatar">
                    {memberInitial(title)}
                </span>
                <span className="team-member-card__content">
                    <span className="team-member-card__heading">
                        <strong>{title}</strong>
                        <span>{role}</span>
                    </span>
                    {purpose === undefined || purpose === "" ? null : (
                        <span className="team-member-card__purpose">
                            {purpose}
                        </span>
                    )}
                    <span className="team-member-card__footer">
                        <span>{providerSummary(data.member)}</span>
                        {data.issueCount === 0 ? null : (
                            <span className="team-member-card__issues">
                                {data.issueCount}{" "}
                                {data.issueCount === 1 ? "issue" : "issues"}
                            </span>
                        )}
                    </span>
                </span>
            </button>
            {children.length === 0 ? null : (
                <button
                    aria-expanded={!data.collapsed}
                    aria-label={`${data.collapsed ? "Expand" : "Collapse"} team under ${title}`}
                    className="team-member-card__collapse nodrag nopan"
                    onClick={(event) => {
                        event.stopPropagation();
                        data.onToggleCollapse(data.member.id);
                    }}
                    onPointerDown={(event) => {
                        event.stopPropagation();
                    }}
                    type="button"
                >
                    {data.collapsed ? (
                        <ChevronRight aria-hidden="true" size={16} />
                    ) : (
                        <ChevronDown aria-hidden="true" size={16} />
                    )}
                </button>
            )}
            <Handle
                aria-hidden="true"
                className="team-geometry-handle"
                isConnectable={false}
                position={Position.Right}
                type="source"
            />
        </article>
    );
}

function memberInitial(title: string): string {
    const first = [...title.trim()][0];
    return first?.toLocaleUpperCase() ?? "T";
}
