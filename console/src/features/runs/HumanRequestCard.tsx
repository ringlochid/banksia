import { ChevronLeft, ChevronRight, Send, X } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { Button, Input, Notice, Prose } from "../../components/ui";
import { errorMessage } from "./run-presentation";
import { FileReferences } from "./RunSections";
import type {
    HumanRequestItemAnswer,
    HumanRequestResponseInput,
    HumanRequestView,
    ProductAction,
} from "./run-api";

interface AnswerDraft {
    readonly mode: "value" | "option" | "other" | "skipped";
    readonly text: string;
    readonly optionId: string;
}

export interface HumanRequestCardProps {
    readonly request: HumanRequestView;
    readonly onRespond: (
        requestId: string,
        action: ProductAction,
        input: HumanRequestResponseInput,
    ) => Promise<string>;
}

export function HumanRequestCard({
    onRespond,
    request,
}: HumanRequestCardProps) {
    const titleId = useId();
    const [currentIndex, setCurrentIndex] = useState(0);
    const [answers, setAnswers] = useState<Record<string, AnswerDraft>>({});
    const [submitting, setSubmitting] = useState(false);
    const [cancelPending, setCancelPending] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [receipt, setReceipt] = useState<string | null>(null);
    const item = request.items[currentIndex];
    const currentAnswer =
        item === undefined ? null : toAnswer(item, answers[item.id]);
    const isLast = currentIndex === request.items.length - 1;

    const completedAnswers = useMemo(() => {
        const entries: [string, HumanRequestItemAnswer][] = [];
        for (const question of request.items) {
            const answer = toAnswer(question, answers[question.id]);
            if (answer === null) {
                return null;
            }
            entries.push([question.id, answer]);
        }
        return Object.fromEntries(entries);
    }, [answers, request.items]);

    if (request.status !== "open") {
        return (
            <section className="run-request run-request--resolved">
                <h3>{request.summary}</h3>
                <Prose>
                    {request.resolution?.summary ??
                        "This request no longer needs a response."}
                </Prose>
            </section>
        );
    }

    async function submitAnswer(): Promise<void> {
        if (
            request.action === null ||
            request.action === undefined ||
            completedAnswers === null
        ) {
            return;
        }
        await respond(request.action, {
            kind: "answer",
            item_responses: completedAnswers,
        });
    }

    async function cancelRequest(): Promise<void> {
        if (
            request.cancel_action === null ||
            request.cancel_action === undefined
        ) {
            return;
        }
        await respond(request.cancel_action, {
            kind: "cancel",
            confirmed: true,
        });
    }

    async function respond(
        action: ProductAction,
        input: HumanRequestResponseInput,
    ): Promise<void> {
        setSubmitting(true);
        setError(null);
        try {
            const message = await onRespond(request.id, action, input);
            setReceipt(message);
            setCancelPending(false);
        } catch (reason) {
            setError(errorMessage(reason));
        } finally {
            setSubmitting(false);
        }
    }

    if (receipt !== null) {
        return (
            <section className="run-request run-request--receipt" role="status">
                <h3>{request.summary}</h3>
                <Prose>{receipt}</Prose>
            </section>
        );
    }

    return (
        <section aria-labelledby={titleId} className="run-request">
            <div className="run-request__heading">
                <div>
                    <h3 id={titleId}>{request.summary}</h3>
                </div>
                {request.member === null ||
                request.member === undefined ? null : (
                    <span>From {request.member.name}</span>
                )}
            </div>
            <FileReferences files={request.files} compact />
            {error === null ? null : (
                <Notice tone="danger" urgent>
                    <Prose>{error}</Prose>
                </Notice>
            )}
            {item === undefined ? (
                <Notice tone="danger">
                    This request has no question to answer. Refresh the Run.
                </Notice>
            ) : (
                <>
                    <div className="run-request__progress">
                        Question {currentIndex + 1} of {request.items.length}
                    </div>
                    <QuestionInput
                        answer={answers[item.id]}
                        disabled={submitting}
                        item={item}
                        onChange={(answer) =>
                            setAnswers((current) => ({
                                ...current,
                                [item.id]: answer,
                            }))
                        }
                    />
                    <div className="run-request__actions">
                        <Button
                            disabled={submitting || currentIndex === 0}
                            onClick={() =>
                                setCurrentIndex((index) => index - 1)
                            }
                            tone="quiet"
                        >
                            <ChevronLeft aria-hidden="true" size={16} />
                            Back
                        </Button>
                        {isLast ? (
                            <Button
                                disabled={
                                    submitting ||
                                    completedAnswers === null ||
                                    request.action === null ||
                                    request.action === undefined
                                }
                                onClick={() => void submitAnswer()}
                                tone="primary"
                            >
                                <Send aria-hidden="true" size={16} />
                                {submitting ? "Submitting…" : "Submit response"}
                            </Button>
                        ) : (
                            <Button
                                disabled={submitting || currentAnswer === null}
                                onClick={() =>
                                    setCurrentIndex((index) => index + 1)
                                }
                                tone="primary"
                            >
                                Next
                                <ChevronRight aria-hidden="true" size={16} />
                            </Button>
                        )}
                    </div>
                </>
            )}
            {request.cancel_action === null ||
            request.cancel_action === undefined ? null : cancelPending ? (
                <div className="run-request__cancel-confirm">
                    <strong>{request.cancel_action.confirmation.title}</strong>
                    <Prose>
                        {request.cancel_action.confirmation.consequence}
                    </Prose>
                    <div>
                        <Button
                            disabled={submitting}
                            onClick={() => setCancelPending(false)}
                        >
                            Keep request open
                        </Button>
                        <Button
                            disabled={submitting}
                            onClick={() => void cancelRequest()}
                            tone="danger"
                        >
                            {submitting ? "Cancelling…" : "Cancel request"}
                        </Button>
                    </div>
                </div>
            ) : (
                <Button
                    disabled={submitting}
                    onClick={() => setCancelPending(true)}
                    tone="quiet"
                >
                    <X aria-hidden="true" size={16} />
                    Cancel this request
                </Button>
            )}
        </section>
    );
}

function QuestionInput({
    answer,
    disabled,
    item,
    onChange,
}: {
    readonly answer: AnswerDraft | undefined;
    readonly disabled: boolean;
    readonly item: HumanRequestView["items"][number];
    readonly onChange: (answer: AnswerDraft) => void;
}) {
    const groupName = useId();
    if (item.options !== null && item.options !== undefined) {
        return (
            <fieldset className="run-question">
                <legend>{item.prompt}</legend>
                {item.options.map((option) => (
                    <label key={option.id}>
                        <input
                            checked={
                                answer?.mode === "option" &&
                                answer.optionId === option.id
                            }
                            disabled={disabled}
                            name={groupName}
                            onChange={() =>
                                onChange({
                                    mode: "option",
                                    optionId: option.id,
                                    text: "",
                                })
                            }
                            type="radio"
                        />
                        <span>
                            <strong>{option.title}</strong>
                            {option.description === null ||
                            option.description === undefined ? null : (
                                <small>{option.description}</small>
                            )}
                        </span>
                    </label>
                ))}
                {item.allow_other ? (
                    <label>
                        <input
                            checked={answer?.mode === "other"}
                            disabled={disabled}
                            name={groupName}
                            onChange={() =>
                                onChange({
                                    mode: "other",
                                    optionId: "",
                                    text: answer?.text ?? "",
                                })
                            }
                            type="radio"
                        />
                        <span>
                            <strong>Something else</strong>
                            {answer?.mode === "other" ? (
                                <Input
                                    aria-label="Your answer"
                                    autoFocus
                                    disabled={disabled}
                                    onChange={(event) =>
                                        onChange({
                                            mode: "other",
                                            optionId: "",
                                            text: event.target.value,
                                        })
                                    }
                                    type="text"
                                    value={answer.text}
                                />
                            ) : null}
                        </span>
                    </label>
                ) : null}
                {item.allow_skip ? (
                    <label>
                        <input
                            checked={answer?.mode === "skipped"}
                            disabled={disabled}
                            name={groupName}
                            onChange={() =>
                                onChange({
                                    mode: "skipped",
                                    optionId: "",
                                    text: "",
                                })
                            }
                            type="radio"
                        />
                        <span>
                            <strong>Continue without this preference</strong>
                        </span>
                    </label>
                ) : null}
            </fieldset>
        );
    }

    return (
        <label className="run-question run-question--value">
            <strong>{item.prompt}</strong>
            <Input
                disabled={disabled}
                onChange={(event) =>
                    onChange({
                        mode: "value",
                        optionId: "",
                        text: event.target.value,
                    })
                }
                required
                type={inputType(item.response_schema)}
                value={answer?.text ?? ""}
            />
        </label>
    );
}

function toAnswer(
    item: HumanRequestView["items"][number],
    draft?: AnswerDraft,
): HumanRequestItemAnswer | null {
    if (draft === undefined) {
        return null;
    }
    switch (draft.mode) {
        case "option":
            return draft.optionId === ""
                ? null
                : { kind: "option", option_id: draft.optionId };
        case "other":
            return draft.text.trim() === ""
                ? null
                : { kind: "other", text: draft.text.trim() };
        case "skipped":
            return item.allow_skip ? { kind: "skipped" } : null;
        case "value":
            return valueAnswer(draft.text, item.response_schema);
    }
}

function valueAnswer(
    text: string,
    schema: HumanRequestView["items"][number]["response_schema"],
): HumanRequestItemAnswer | null {
    if (text.trim() === "") {
        return null;
    }
    const type = schemaType(schema);
    if (type === "integer" || type === "number") {
        const number = Number(text);
        return Number.isFinite(number)
            ? { kind: "value", value: number }
            : null;
    }
    if (type === "boolean") {
        return { kind: "value", value: text === "true" };
    }
    return { kind: "value", value: text };
}

function inputType(
    schema: HumanRequestView["items"][number]["response_schema"],
): "date" | "number" | "text" {
    const type = schemaType(schema);
    if (type === "number" || type === "integer") {
        return "number";
    }
    return schemaProperty(schema, "format") === "date" ? "date" : "text";
}

function schemaType(
    schema: HumanRequestView["items"][number]["response_schema"],
): string | null {
    return schemaProperty(schema, "type");
}

function schemaProperty(
    schema: HumanRequestView["items"][number]["response_schema"],
    key: string,
): string | null {
    if (schema === null || schema === undefined) {
        return null;
    }
    const value = schema[key];
    return typeof value === "string" ? value : null;
}
