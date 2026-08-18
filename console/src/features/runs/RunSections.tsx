import {
    CheckCircle2,
    Circle,
    CircleDot,
    Clock3,
    FileText,
} from "lucide-react";

import { Button, Prose } from "../../components/ui";
import { formatRunDate } from "./run-presentation";
import type {
    FileReference,
    TaskActivity,
    TaskMemberView,
    TaskPlanView,
    TaskResultView,
} from "./run-api";

export function RunResult({ result }: { readonly result: TaskResultView }) {
    return (
        <section
            aria-labelledby="run-result-title"
            className={`run-result run-result--${result.status}`}
        >
            <header className="run-section-heading">
                <div>
                    <span className="run-result__status">
                        {result.status === "completed"
                            ? "Completed"
                            : "Blocked"}
                    </span>
                    <h2 id="run-result-title">Result</h2>
                </div>
                <time dateTime={result.completed_at}>
                    {formatRunDate(result.completed_at)}
                </time>
            </header>
            <Prose className="run-result__summary">{result.summary}</Prose>
            {result.details === null || result.details === undefined ? null : (
                <Prose className="run-result__details">{result.details}</Prose>
            )}
            <FileReferences files={result.files} />
        </section>
    );
}

export function TeamSection({
    onSelect,
    selectedMemberId,
    team,
}: {
    readonly onSelect: (memberId: string) => void;
    readonly selectedMemberId: string;
    readonly team: TaskMemberView;
}) {
    return (
        <section aria-labelledby="run-team-title" className="run-side-section">
            <header>
                <h2 id="run-team-title">Team</h2>
            </header>
            <ul aria-label="Run team" className="run-team">
                <TeamMember
                    member={team}
                    onSelect={onSelect}
                    selectedMemberId={selectedMemberId}
                />
            </ul>
        </section>
    );
}

function TeamMember({
    member,
    onSelect,
    selectedMemberId,
}: {
    readonly member: TaskMemberView;
    readonly onSelect: (memberId: string) => void;
    readonly selectedMemberId: string;
}) {
    return (
        <li>
            <button
                aria-pressed={member.id === selectedMemberId}
                className="run-team__member"
                onClick={() => onSelect(member.id)}
                type="button"
            >
                <span
                    aria-hidden="true"
                    className={`run-team__state run-team__state--${member.state}`}
                />
                <span className="run-team__name">
                    <strong>{member.name}</strong>
                    <span>{memberStateLabel(member.state)}</span>
                </span>
            </button>
            {member.children.length === 0 ? null : (
                <ul>
                    {member.children.map((child) => (
                        <TeamMember
                            key={child.id}
                            member={child}
                            onSelect={onSelect}
                            selectedMemberId={selectedMemberId}
                        />
                    ))}
                </ul>
            )}
        </li>
    );
}

export function MemberContextSection({
    member,
    onSteer,
}: {
    readonly member: TaskMemberView;
    readonly onSteer: (member: TaskMemberView) => void;
}) {
    const update = member.latest_update;
    return (
        <section
            aria-labelledby="run-member-title"
            className="run-side-section run-member-context"
        >
            <header className="run-section-heading">
                <div>
                    <span className="run-member-context__eyebrow">Member</span>
                    <h2 id="run-member-title">{member.name}</h2>
                </div>
                <span>{memberStateLabel(member.state)}</span>
            </header>
            {member.purpose === null || member.purpose === undefined ? null : (
                <Prose className="run-team__purpose">{member.purpose}</Prose>
            )}
            {member.steer_action === null ||
            member.steer_action === undefined ? null : (
                <div className="run-member-context__action">
                    <Button
                        className="run-member-context__steer"
                        onClick={() => onSteer(member)}
                    >
                        Steer
                    </Button>
                </div>
            )}
            {update === null || update === undefined ? null : (
                <div className="run-member-update">
                    <div className="run-section-heading">
                        <strong>Latest update</strong>
                        <time dateTime={update.occurred_at}>
                            {formatRunDate(update.occurred_at)}
                        </time>
                    </div>
                    <Prose>{update.summary}</Prose>
                    <FileReferences compact files={update.files} />
                </div>
            )}
        </section>
    );
}

export function PlanSection({ plan }: { readonly plan: TaskPlanView }) {
    return (
        <section aria-labelledby="run-plan-title" className="run-side-section">
            <header className="run-section-heading">
                <h2 id="run-plan-title">Plan</h2>
                <time dateTime={plan.updated_at}>
                    {formatRunDate(plan.updated_at)}
                </time>
            </header>
            {plan.explanation === null ||
            plan.explanation === undefined ? null : (
                <Prose className="run-plan__explanation">
                    {plan.explanation}
                </Prose>
            )}
            <ol className="run-plan">
                {plan.steps.map((step, index) => (
                    <li key={`${step.text}-${String(index)}`}>
                        <PlanIcon status={step.status} />
                        <div>
                            <Prose>{step.text}</Prose>
                            <small>{planStepLabel(step.status)}</small>
                        </div>
                    </li>
                ))}
            </ol>
        </section>
    );
}

function PlanIcon({ status }: { readonly status: string }) {
    if (status === "completed") {
        return <CheckCircle2 aria-hidden="true" size={16} />;
    }
    if (status === "in_progress") {
        return <CircleDot aria-hidden="true" size={16} />;
    }
    return <Circle aria-hidden="true" size={16} />;
}

export function ActivitySection({
    activities,
    isTruncated,
}: {
    readonly activities: readonly TaskActivity[];
    readonly isTruncated: boolean;
}) {
    return (
        <section
            aria-labelledby="run-activity-title"
            className="run-activity-panel"
        >
            <header className="run-section-heading">
                <h2 id="run-activity-title">Activity</h2>
            </header>
            {activities.length === 0 ? (
                <p className="run-section__empty">No activity yet.</p>
            ) : (
                <ol className="run-activity">
                    {activities.map((activity) => (
                        <li key={activity.id}>
                            <span
                                aria-hidden="true"
                                className="run-activity__marker"
                            >
                                <Clock3 size={14} />
                            </span>
                            <div>
                                <div className="run-activity__heading">
                                    <strong>{activity.title}</strong>
                                    <time dateTime={activity.occurred_at}>
                                        {formatRunDate(activity.occurred_at)}
                                    </time>
                                </div>
                                {activity.member === null ||
                                activity.member === undefined ? null : (
                                    <span>{activity.member.name}</span>
                                )}
                                {activity.summary === null ||
                                activity.summary === undefined ? null : (
                                    <Prose className="run-activity__summary">
                                        {activity.summary}
                                    </Prose>
                                )}
                                <FileReferences
                                    compact
                                    files={activity.files}
                                />
                            </div>
                        </li>
                    ))}
                </ol>
            )}
            {isTruncated ? (
                <p className="run-bounded-note">
                    Showing the most recent activity.
                </p>
            ) : null}
        </section>
    );
}

export function FileReferences({
    compact = false,
    files,
}: {
    readonly compact?: boolean;
    readonly files: readonly FileReference[];
}) {
    if (files.length === 0) {
        return null;
    }
    return (
        <div className={compact ? "run-files is-compact" : "run-files"}>
            <h3>Files</h3>
            <ul>
                {files.map((file) => (
                    <li key={file.path}>
                        <FileText aria-hidden="true" size={15} />
                        <div>
                            <code>{file.path}</code>
                            {file.description === null ||
                            file.description === undefined ? null : (
                                <Prose>{file.description}</Prose>
                            )}
                        </div>
                    </li>
                ))}
            </ul>
        </div>
    );
}

function memberStateLabel(state: TaskMemberView["state"]): string {
    switch (state) {
        case "not_started":
            return "Not started";
        case "working":
            return "Working";
        case "waiting":
            return "Waiting";
        case "done":
            return "Done";
        case "blocked":
            return "Blocked";
    }
}

function planStepLabel(status: string): string {
    switch (status) {
        case "completed":
            return "Completed";
        case "in_progress":
            return "In progress";
        default:
            return "Not started";
    }
}
