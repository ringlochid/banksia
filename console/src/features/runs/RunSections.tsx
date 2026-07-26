import {
    CheckCircle2,
    Circle,
    CircleDot,
    Clock3,
    FileText,
} from "lucide-react";

import { Card } from "../../components/ui";
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
        <Card
            aria-labelledby="run-result-title"
            className={`run-result run-result--${result.status}`}
        >
            <div className="run-section-heading">
                <div>
                    <p className="run-section-kicker">
                        {result.status === "completed"
                            ? "Completed"
                            : "Blocked"}
                    </p>
                    <h2 id="run-result-title">Result</h2>
                </div>
                <span>{formatRunDate(result.completed_at)}</span>
            </div>
            <p className="run-result__summary">{result.summary}</p>
            {result.details === null || result.details === undefined ? null : (
                <div className="run-result__details">{result.details}</div>
            )}
            <FileReferences files={result.files} />
        </Card>
    );
}

export function TeamSection({ team }: { readonly team: TaskMemberView }) {
    return (
        <Card aria-labelledby="run-team-title" className="run-section">
            <div className="run-section-heading">
                <div>
                    <p className="run-section-kicker">Who owns the work</p>
                    <h2 id="run-team-title">Team</h2>
                </div>
            </div>
            <ul aria-label="Run team" className="run-team">
                <TeamMember member={team} />
            </ul>
        </Card>
    );
}

function TeamMember({ member }: { readonly member: TaskMemberView }) {
    return (
        <li>
            <div className="run-team__member">
                <span
                    aria-hidden="true"
                    className={`run-team__state run-team__state--${member.state}`}
                />
                <div>
                    <div className="run-team__name">
                        <strong>{member.name}</strong>
                        <span>{memberStateLabel(member.state)}</span>
                    </div>
                    {member.purpose === null ||
                    member.purpose === undefined ? null : (
                        <p>{member.purpose}</p>
                    )}
                    {member.latest_update === null ||
                    member.latest_update === undefined ? null : (
                        <div className="run-team__update">
                            <span>
                                Updated{" "}
                                {formatRunDate(
                                    member.latest_update.occurred_at,
                                )}
                            </span>
                            <p>{member.latest_update.summary}</p>
                            <FileReferences
                                files={member.latest_update.files}
                                compact
                            />
                        </div>
                    )}
                </div>
            </div>
            {member.children.length === 0 ? null : (
                <ul>
                    {member.children.map((child) => (
                        <TeamMember key={child.id} member={child} />
                    ))}
                </ul>
            )}
        </li>
    );
}

export function PlanSection({ plan }: { readonly plan: TaskPlanView }) {
    return (
        <Card aria-labelledby="run-plan-title" className="run-section">
            <div className="run-section-heading">
                <div>
                    <p className="run-section-kicker">
                        How the team is working
                    </p>
                    <h2 id="run-plan-title">Current plan</h2>
                </div>
                <span>{formatRunDate(plan.updated_at)}</span>
            </div>
            {plan.explanation === null ||
            plan.explanation === undefined ? null : (
                <p>{plan.explanation}</p>
            )}
            <ol className="run-plan">
                {plan.steps.map((step, index) => (
                    <li key={`${step.text}-${String(index)}`}>
                        <PlanIcon status={step.status} />
                        <span>
                            {step.text}
                            <small>{planStepLabel(step.status)}</small>
                        </span>
                    </li>
                ))}
            </ol>
        </Card>
    );
}

function PlanIcon({ status }: { readonly status: string }) {
    if (status === "completed") {
        return <CheckCircle2 aria-hidden="true" size={18} />;
    }
    if (status === "in_progress") {
        return <CircleDot aria-hidden="true" size={18} />;
    }
    return <Circle aria-hidden="true" size={18} />;
}

export function ActivitySection({
    activities,
    isTruncated,
}: {
    readonly activities: readonly TaskActivity[];
    readonly isTruncated: boolean;
}) {
    return (
        <Card aria-labelledby="run-activity-title" className="run-section">
            <div className="run-section-heading">
                <div>
                    <p className="run-section-kicker">Meaningful updates</p>
                    <h2 id="run-activity-title">Activity</h2>
                </div>
            </div>
            {activities.length === 0 ? (
                <p className="run-section__empty">
                    No meaningful updates yet. Refresh to check again.
                </p>
            ) : (
                <ol className="run-activity">
                    {activities.map((activity) => (
                        <li key={activity.id}>
                            <Clock3 aria-hidden="true" size={17} />
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
                                    <p>{activity.summary}</p>
                                )}
                                <FileReferences
                                    files={activity.files}
                                    compact
                                />
                            </div>
                        </li>
                    ))}
                </ol>
            )}
            {isTruncated ? (
                <p className="run-bounded-note">
                    This view shows the most recent meaningful updates.
                </p>
            ) : null}
        </Card>
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
            <h3>Referenced files</h3>
            <ul>
                {files.map((file) => (
                    <li key={file.path}>
                        <FileText aria-hidden="true" size={16} />
                        <div>
                            <code>{file.path}</code>
                            {file.description === null ||
                            file.description === undefined ? null : (
                                <p>{file.description}</p>
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
