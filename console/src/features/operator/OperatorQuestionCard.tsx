import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { Button, Input, Prose } from "../../components/ui";
import type {
    OperatorAssistantQuestionSetEntry,
    OperatorQuestionAnswer,
} from "./operator-api";

type AnswerDraft =
    | { readonly kind: "option"; readonly optionId: string }
    | { readonly kind: "custom"; readonly text: string }
    | { readonly kind: "skip" };

export interface OperatorQuestionCardProps {
    readonly disabled: boolean;
    readonly questionSet: OperatorAssistantQuestionSetEntry;
    readonly onSubmit: (answers: OperatorQuestionAnswer[]) => void;
}

export function OperatorQuestionCard({
    disabled,
    onSubmit,
    questionSet,
}: OperatorQuestionCardProps) {
    const groupName = useId();
    const fieldsetRef = useRef<HTMLFieldSetElement>(null);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [drafts, setDrafts] = useState<Record<string, AnswerDraft>>({});
    const question = questionSet.questions[currentIndex];
    const currentDraft =
        question === undefined ? undefined : drafts[question.id];
    const currentIsValid = isValidDraft(currentDraft);
    const answers = useMemo(
        () => serializeAnswers(questionSet.questions, drafts),
        [drafts, questionSet.questions],
    );

    useEffect(() => {
        fieldsetRef.current?.focus();
    }, [currentIndex]);

    if (question === undefined) {
        return null;
    }

    const activeQuestion = question;
    const isLast = currentIndex === questionSet.questions.length - 1;

    function setDraft(draft: AnswerDraft): void {
        setDrafts((current) => ({ ...current, [activeQuestion.id]: draft }));
    }

    function handleShortcut(event: React.KeyboardEvent): void {
        if (
            event.target instanceof HTMLInputElement ||
            event.target instanceof HTMLTextAreaElement
        ) {
            return;
        }
        const optionIndex = Number(event.key) - 1;
        const option = activeQuestion.options[optionIndex];
        if (option !== undefined) {
            event.preventDefault();
            setDraft({ kind: "option", optionId: option.id });
        }
    }

    return (
        <section className="operator-question-card">
            {questionSet.explanation ? (
                <Prose className="operator-question-card__explanation">
                    {questionSet.explanation}
                </Prose>
            ) : null}
            <p aria-live="polite" className="operator-question-card__progress">
                Question {currentIndex + 1} of {questionSet.questions.length}
            </p>
            <fieldset
                className="operator-question-card__fieldset"
                disabled={disabled}
                onKeyDown={handleShortcut}
                ref={fieldsetRef}
                tabIndex={-1}
            >
                <legend>
                    <span>{question.header}</span>
                    {question.question}
                </legend>
                <div className="operator-question-card__options">
                    {question.options.map((option, index) => (
                        <label key={option.id}>
                            <input
                                checked={
                                    currentDraft?.kind === "option" &&
                                    currentDraft.optionId === option.id
                                }
                                name={`${groupName}-${question.id}`}
                                onChange={() =>
                                    setDraft({
                                        kind: "option",
                                        optionId: option.id,
                                    })
                                }
                                type="radio"
                            />
                            <span aria-hidden="true">{index + 1}</span>
                            <strong>{option.label}</strong>
                            <small>{option.description}</small>
                        </label>
                    ))}
                    <label>
                        <input
                            checked={currentDraft?.kind === "custom"}
                            name={`${groupName}-${question.id}`}
                            onChange={() =>
                                setDraft({
                                    kind: "custom",
                                    text:
                                        currentDraft?.kind === "custom"
                                            ? currentDraft.text
                                            : "",
                                })
                            }
                            type="radio"
                        />
                        <strong>Something else</strong>
                        <Input
                            aria-label="Something else"
                            disabled={disabled}
                            onChange={(event) =>
                                setDraft({
                                    kind: "custom",
                                    text: event.target.value,
                                })
                            }
                            onFocus={() => {
                                if (currentDraft?.kind !== "custom") {
                                    setDraft({ kind: "custom", text: "" });
                                }
                            }}
                            type="text"
                            value={
                                currentDraft?.kind === "custom"
                                    ? currentDraft.text
                                    : ""
                            }
                        />
                    </label>
                    {question.allow_skip ? (
                        <label>
                            <input
                                checked={currentDraft?.kind === "skip"}
                                name={`${groupName}-${question.id}`}
                                onChange={() => setDraft({ kind: "skip" })}
                                type="radio"
                            />
                            <strong>Skip this question</strong>
                            <small>
                                Continue without setting this preference.
                            </small>
                        </label>
                    ) : null}
                </div>
            </fieldset>
            <div className="operator-question-card__actions">
                <Button
                    disabled={disabled || currentIndex === 0}
                    onClick={() => setCurrentIndex((index) => index - 1)}
                    tone="quiet"
                >
                    <ChevronLeft aria-hidden="true" size={16} />
                    Back
                </Button>
                {isLast ? (
                    <Button
                        disabled={disabled || answers === null}
                        onClick={() => {
                            if (answers !== null) {
                                onSubmit(answers);
                            }
                        }}
                        tone="primary"
                    >
                        Continue
                    </Button>
                ) : (
                    <Button
                        disabled={disabled || !currentIsValid}
                        onClick={() => setCurrentIndex((index) => index + 1)}
                        tone="primary"
                    >
                        Next
                        <ChevronRight aria-hidden="true" size={16} />
                    </Button>
                )}
            </div>
        </section>
    );
}

function isValidDraft(draft: AnswerDraft | undefined): boolean {
    return (
        draft?.kind === "option" ||
        draft?.kind === "skip" ||
        (draft?.kind === "custom" && draft.text.trim() !== "")
    );
}

function serializeAnswers(
    questions: OperatorAssistantQuestionSetEntry["questions"],
    drafts: Record<string, AnswerDraft>,
): OperatorQuestionAnswer[] | null {
    const answers: OperatorQuestionAnswer[] = [];
    for (const question of questions) {
        const draft = drafts[question.id];
        if (!isValidDraft(draft) || draft === undefined) {
            return null;
        }
        const answer =
            draft.kind === "option"
                ? { kind: "option" as const, option_id: draft.optionId }
                : draft.kind === "custom"
                  ? { kind: "custom" as const, text: draft.text.trim() }
                  : { kind: "skip" as const };
        answers.push({ question_id: question.id, answer });
    }
    return answers;
}
