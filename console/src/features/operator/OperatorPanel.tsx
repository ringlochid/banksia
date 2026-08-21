import { Bot, LoaderCircle, Plus, RefreshCw, Send, X } from "lucide-react";
import {
    type FormEvent,
    type KeyboardEvent,
    useEffect,
    useRef,
    useState,
} from "react";
import { Link } from "react-router";

import {
    Button,
    Notice,
    PageState,
    Prose,
    Select,
    Textarea,
} from "../../components/ui";
import { OperatorQuestionCard } from "./OperatorQuestionCard";
import type {
    OperatorAnswerQuestionSetAction,
    OperatorApi,
    OperatorAssistantQuestionSetEntry,
    OperatorConversationEntry,
    OperatorConversationSummary,
    OperatorConversationView,
    OperatorQuestionAnswer,
    OperatorStatusResponse,
} from "./operator-api";

export interface OperatorPanelProps {
    readonly api: OperatorApi;
    readonly isOpen: boolean;
    readonly onClose: () => void;
}

interface PendingUserMessage {
    readonly entryIdsBeforeSend: ReadonlySet<string>;
    readonly idempotencyKey: string;
    readonly state: "sending" | "failed";
    readonly text: string;
}

export function OperatorPanel({ api, isOpen, onClose }: OperatorPanelProps) {
    const [status, setStatus] = useState<OperatorStatusResponse | null>(null);
    const [conversations, setConversations] = useState<
        OperatorConversationSummary[]
    >([]);
    const [conversation, setConversation] =
        useState<OperatorConversationView | null>(null);
    const [message, setMessage] = useState("");
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [pendingUserMessage, setPendingUserMessage] =
        useState<PendingUserMessage | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [reloadKey, setReloadKey] = useState(0);
    const transcriptRef = useRef<HTMLDivElement>(null);
    const closeButtonRef = useRef<HTMLButtonElement>(null);
    const createKeyRef = useRef<string | null>(null);

    useEffect(() => {
        if (!isOpen || status !== null) {
            return;
        }
        void loadOperator(api, setStatus, setConversations, setConversation)
            .catch((reason: unknown) => setError(errorMessage(reason)))
            .finally(() => setLoading(false));
    }, [api, isOpen, reloadKey, status]);

    useEffect(() => {
        if (isOpen) {
            closeButtonRef.current?.focus();
        }
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen) {
            return;
        }
        function closeOnEscape(event: globalThis.KeyboardEvent): void {
            if (event.key === "Escape") {
                event.preventDefault();
                onClose();
            }
        }
        document.addEventListener("keydown", closeOnEscape);
        return () => document.removeEventListener("keydown", closeOnEscape);
    }, [isOpen, onClose]);

    useEffect(() => {
        if (isOpen && transcriptRef.current !== null) {
            transcriptRef.current.scrollTop =
                transcriptRef.current.scrollHeight;
        }
    }, [conversation, isOpen, pendingUserMessage]);

    const sendAction = conversation?.actions.find(
        (action) => action.kind === "send_message",
    );
    const answerAction = conversation?.actions.find(
        (action): action is OperatorAnswerQuestionSetAction =>
            action.kind === "answer_question_set",
    );
    const createAction = conversation?.actions.find(
        (action) => action.kind === "create_new_conversation",
    );
    const questionSet =
        answerAction === undefined
            ? undefined
            : conversation?.entries.find(
                  (entry) =>
                      entry.kind === "assistant_question_set" &&
                      entry.id === answerAction.question_set_id,
              );
    const canSend =
        sendAction !== undefined &&
        (conversation?.state === "ready" ||
            conversation?.state === "interrupted");
    const stateMismatch =
        (conversation?.state === "awaiting_answer" &&
            (answerAction === undefined ||
                questionSet?.kind !== "assistant_question_set")) ||
        ((conversation?.state === "ready" ||
            conversation?.state === "interrupted") &&
            sendAction === undefined) ||
        (conversation?.state === "closed" && createAction === undefined);

    async function createConversation(): Promise<void> {
        const key = createKeyRef.current ?? idempotencyKey();
        createKeyRef.current = key;
        setSubmitting(true);
        setError(null);
        setMessage("");
        setPendingUserMessage(null);
        try {
            const next = (await api.createConversation(key)).body;
            createKeyRef.current = null;
            setConversation(next);
            await refreshConversationList(api, setConversations).catch(
                () => undefined,
            );
        } catch (reason) {
            // Reuse this key until this exact create returns committed readback.
            setError(errorMessage(reason));
        } finally {
            setSubmitting(false);
        }
    }

    async function chooseConversation(id: string): Promise<void> {
        if (id === "") {
            return;
        }
        setLoading(true);
        setError(null);
        setPendingUserMessage(null);
        try {
            setConversation((await api.getConversation(id)).body);
        } catch (reason) {
            setError(errorMessage(reason));
        } finally {
            setLoading(false);
        }
    }

    async function sendMessage(event?: FormEvent): Promise<void> {
        event?.preventDefault();
        const text = message.trim();
        if (!canSend || sendAction === undefined || text === "") {
            return;
        }
        setMessage("");
        await submitUserMessage({
            entryIdsBeforeSend: new Set(
                conversation?.entries.map((entry) => entry.id) ?? [],
            ),
            idempotencyKey: idempotencyKey(),
            state: "sending",
            text,
        });
    }

    async function submitUserMessage(
        pending: PendingUserMessage,
    ): Promise<void> {
        if (sendAction === undefined) {
            return;
        }
        setSubmitting(true);
        setError(null);
        setPendingUserMessage({ ...pending, state: "sending" });
        try {
            const next = (
                await api.sendMessage(
                    sendAction.href,
                    pending.text,
                    pending.idempotencyKey,
                )
            ).body;
            setConversation(next);
            setPendingUserMessage(null);
            await refreshConversationList(api, setConversations).catch(
                () => undefined,
            );
        } catch (reason) {
            let reconciled: OperatorConversationView | null = null;
            if (conversation !== null) {
                try {
                    reconciled = (await api.getConversation(conversation.id))
                        .body;
                    setConversation(reconciled);
                } catch {
                    // Preserve the original mutation failure below.
                }
            }
            const accepted =
                reconciled?.entries.some(
                    (entry) =>
                        !pending.entryIdsBeforeSend.has(entry.id) &&
                        entry.kind === "user_message" &&
                        entry.text === pending.text,
                ) ?? false;
            setPendingUserMessage(
                accepted ? null : { ...pending, state: "failed" },
            );
            setError(errorMessage(reason));
        } finally {
            setSubmitting(false);
        }
    }

    async function answerQuestions(
        answers: OperatorQuestionAnswer[],
    ): Promise<void> {
        if (answerAction === undefined) {
            return;
        }
        await mutate(
            () =>
                api.answerQuestions(
                    answerAction.href,
                    answers,
                    idempotencyKey(),
                ),
            true,
        );
    }

    async function mutate(
        operation: () => Promise<{ body: OperatorConversationView }>,
        reconcileOnFailure = false,
    ): Promise<void> {
        setSubmitting(true);
        setError(null);
        try {
            const next = (await operation()).body;
            setConversation(next);
            try {
                await refreshConversationList(api, setConversations);
            } catch {
                // The committed conversation remains the authoritative readback.
            }
        } catch (reason) {
            if (reconcileOnFailure && conversation !== null) {
                try {
                    setConversation(
                        (await api.getConversation(conversation.id)).body,
                    );
                } catch {
                    // Preserve the original, more useful mutation failure.
                }
            }
            setError(errorMessage(reason));
        } finally {
            setSubmitting(false);
        }
    }

    async function reloadConversation(): Promise<void> {
        if (conversation === null) {
            setStatus(null);
            setLoading(true);
            setError(null);
            setReloadKey((key) => key + 1);
            return;
        }
        await chooseConversation(conversation.id);
    }

    function handleComposerKeyDown(
        event: KeyboardEvent<HTMLTextAreaElement>,
    ): void {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void sendMessage();
        }
    }

    return (
        <aside
            aria-hidden={!isOpen}
            aria-label="Oh My Subagents Operator"
            className={`operator-panel ${isOpen ? "is-open" : ""}`}
            id="oms-operator"
            inert={!isOpen}
        >
            <header className="operator-panel__header">
                <span aria-hidden="true">
                    <Bot size={20} />
                </span>
                <div>
                    <strong>Operator</strong>
                </div>
                <button
                    aria-label="Close Operator"
                    className="ui-button ui-button--quiet"
                    onClick={onClose}
                    ref={closeButtonRef}
                    type="button"
                >
                    <X aria-hidden="true" size={18} />
                </button>
            </header>

            {loading ? (
                <PageState
                    className="operator-panel__loading"
                    fill
                    kind="loading"
                    title="Opening Operator"
                />
            ) : status?.availability !== "available" ? (
                <div className="operator-panel__empty">
                    <Notice title="Operator is not available" tone="warning">
                        <p>
                            {status?.explanation ??
                                error ??
                                "Oh My Subagents could not read Operator status."}
                        </p>
                        {status?.setup_action ? (
                            <p>{status.setup_action}</p>
                        ) : null}
                    </Notice>
                    <Button onClick={() => void reloadConversation()}>
                        <RefreshCw aria-hidden="true" size={16} />
                        Reload
                    </Button>
                </div>
            ) : (
                <>
                    <div className="operator-panel__conversation-bar">
                        {conversations.length === 0 ? (
                            <span>
                                {conversation === null
                                    ? "Start a conversation"
                                    : "Current conversation"}
                            </span>
                        ) : (
                            <Select
                                ariaLabel="Operator conversation"
                                onValueChange={(id) =>
                                    void chooseConversation(id)
                                }
                                options={conversations.map((item) => ({
                                    hint: conversationTime(item),
                                    label: conversationLabel(item),
                                    value: item.id,
                                }))}
                                value={conversation?.id ?? ""}
                            />
                        )}
                        <Button
                            aria-label="New Operator conversation"
                            disabled={submitting}
                            icon
                            onClick={() => void createConversation()}
                            tone="quiet"
                        >
                            <Plus aria-hidden="true" size={17} />
                        </Button>
                    </div>

                    <div
                        aria-live="polite"
                        className="operator-panel__transcript"
                        ref={transcriptRef}
                        role="log"
                    >
                        {conversation === null ? (
                            <div className="operator-panel__welcome">
                                <Bot aria-hidden="true" size={28} />
                                <h2>Start a conversation</h2>
                                <p>Describe the Workflow or work you need.</p>
                                <Button
                                    disabled={submitting}
                                    onClick={() => void createConversation()}
                                    tone="primary"
                                >
                                    Start conversation
                                </Button>
                            </div>
                        ) : (
                            conversation.entries.map((entry) => (
                                <ConversationEntry
                                    entry={entry}
                                    key={entry.id}
                                    questionSet={
                                        entry.kind === "user_question_answers"
                                            ? findQuestionSet(
                                                  conversation.entries,
                                                  entry.question_set_id,
                                              )
                                            : undefined
                                    }
                                />
                            ))
                        )}
                        {pendingUserMessage === null ? null : (
                            <article
                                className={`operator-entry operator-entry--user operator-entry--pending ${
                                    pendingUserMessage.state === "failed"
                                        ? "is-failed"
                                        : ""
                                }`}
                            >
                                <p>{pendingUserMessage.text}</p>
                                {pendingUserMessage.state === "failed" ? (
                                    <Button
                                        disabled={submitting}
                                        onClick={() =>
                                            void submitUserMessage(
                                                pendingUserMessage,
                                            )
                                        }
                                        tone="quiet"
                                    >
                                        Retry
                                    </Button>
                                ) : null}
                            </article>
                        )}
                        {conversation?.state === "running" ||
                        pendingUserMessage?.state === "sending" ? (
                            <div className="operator-panel__working">
                                <p role="status">
                                    <LoaderCircle
                                        aria-hidden="true"
                                        className="is-spinning"
                                        size={16}
                                    />
                                    Working…
                                </p>
                                {pendingUserMessage === null ? (
                                    <Button
                                        onClick={() =>
                                            void reloadConversation()
                                        }
                                        tone="quiet"
                                    >
                                        Refresh
                                    </Button>
                                ) : null}
                            </div>
                        ) : null}
                        {stateMismatch ? (
                            <Notice tone="danger" urgent>
                                <p>
                                    This conversation changed unexpectedly.
                                    Reload before continuing.
                                </p>
                                <Button
                                    onClick={() => void reloadConversation()}
                                >
                                    Reload
                                </Button>
                            </Notice>
                        ) : null}
                        {questionSet?.kind === "assistant_question_set" ? (
                            <OperatorQuestionCard
                                disabled={submitting}
                                onSubmit={(answers) =>
                                    void answerQuestions(answers)
                                }
                                questionSet={questionSet}
                            />
                        ) : null}
                        {error === null ? null : (
                            <Notice tone="danger" urgent>
                                <Prose>{error}</Prose>
                            </Notice>
                        )}
                    </div>

                    <footer className="operator-panel__footer">
                        {conversation?.state === "closed" &&
                        createAction !== undefined ? (
                            <Button
                                disabled={submitting}
                                onClick={() => void createConversation()}
                                tone="primary"
                            >
                                Start new conversation
                            </Button>
                        ) : (
                            <form onSubmit={(event) => void sendMessage(event)}>
                                <label htmlFor="operator-message">
                                    Message Operator
                                </label>
                                <Textarea
                                    disabled={!canSend || submitting}
                                    id="operator-message"
                                    onChange={(event) =>
                                        setMessage(event.target.value)
                                    }
                                    onKeyDown={handleComposerKeyDown}
                                    placeholder={
                                        conversation === null
                                            ? "Start a conversation first"
                                            : conversation.state ===
                                                "awaiting_answer"
                                              ? "Answer the question above"
                                              : conversation.state === "running"
                                                ? "Operator is working"
                                                : "Message Operator"
                                    }
                                    rows={2}
                                    value={message}
                                />
                                <Button
                                    aria-label="Send message"
                                    disabled={
                                        !canSend ||
                                        submitting ||
                                        message.trim() === ""
                                    }
                                    tone="primary"
                                    type="submit"
                                >
                                    <Send aria-hidden="true" size={17} />
                                </Button>
                            </form>
                        )}
                        <Link to="/workflows">Open Workflows</Link>
                    </footer>
                </>
            )}
        </aside>
    );
}

async function loadOperator(
    api: OperatorApi,
    setStatus: (status: OperatorStatusResponse) => void,
    setConversations: (items: OperatorConversationSummary[]) => void,
    setConversation: (conversation: OperatorConversationView | null) => void,
): Promise<void> {
    const status = (await api.getStatus()).body;
    setStatus(status);
    if (status.availability !== "available") {
        return;
    }
    const items = (await api.listConversations()).body.items;
    setConversations(items);
    if (items[0] !== undefined) {
        setConversation((await api.getConversation(items[0].id)).body);
    }
}

async function refreshConversationList(
    api: OperatorApi,
    setConversations: (items: OperatorConversationSummary[]) => void,
): Promise<void> {
    setConversations((await api.listConversations()).body.items);
}

function ConversationEntry({
    entry,
    questionSet,
}: {
    readonly entry: OperatorConversationEntry;
    readonly questionSet: OperatorAssistantQuestionSetEntry | undefined;
}) {
    switch (entry.kind) {
        case "assistant_message":
            return (
                <article className="operator-entry operator-entry--assistant">
                    <Prose>{entry.text}</Prose>
                </article>
            );
        case "user_message":
            return (
                <article className="operator-entry operator-entry--user">
                    <p>{entry.text}</p>
                </article>
            );
        case "turn_interrupted":
            return (
                <Notice title="Operator was interrupted" tone="warning">
                    <Prose>{entry.explanation}</Prose>
                    <Prose>{entry.next_step}</Prose>
                </Notice>
            );
        case "user_question_answers":
            return (
                <article className="operator-entry operator-entry--receipt">
                    <strong>Answers sent</strong>
                    <dl>
                        {entry.answers.map(({ answer, question_id }) => {
                            const question = questionSet?.questions.find(
                                (candidate) => candidate.id === question_id,
                            );
                            return (
                                <div key={question_id}>
                                    <dt>
                                        {question?.question ?? "Your answer"}
                                    </dt>
                                    <dd>{answerLabel(answer, question)}</dd>
                                </div>
                            );
                        })}
                    </dl>
                </article>
            );
        case "assistant_question_set":
            return null;
    }
}

function findQuestionSet(
    entries: OperatorConversationEntry[],
    id: string,
): OperatorAssistantQuestionSetEntry | undefined {
    return entries.find(
        (entry): entry is OperatorAssistantQuestionSetEntry =>
            entry.kind === "assistant_question_set" && entry.id === id,
    );
}

function answerLabel(
    answer:
        | { readonly kind: "option"; readonly option_id: string }
        | { readonly kind: "custom"; readonly text: string }
        | { readonly kind: "skip" },
    question:
        OperatorAssistantQuestionSetEntry["questions"][number] | undefined,
): string {
    if (answer.kind === "custom") {
        return answer.text;
    }
    if (answer.kind === "skip") {
        return "Skipped";
    }
    return (
        question?.options.find((option) => option.id === answer.option_id)
            ?.label ?? "Selected option"
    );
}

function conversationLabel(item: OperatorConversationSummary): string {
    if (item.preview?.trim()) {
        return item.preview;
    }
    return "New conversation";
}

function conversationTime(item: OperatorConversationSummary): string {
    const date = new Date(item.updated_at);
    if (Number.isNaN(date.valueOf())) {
        return "Updated earlier";
    }

    const elapsedSeconds = Math.max(
        0,
        Math.floor((Date.now() - date.valueOf()) / 1_000),
    );
    if (elapsedSeconds < 60) {
        return "Just now";
    }
    const elapsedMinutes = Math.floor(elapsedSeconds / 60);
    if (elapsedMinutes < 60) {
        return `${elapsedMinutes}m ago`;
    }
    const elapsedHours = Math.floor(elapsedMinutes / 60);
    if (elapsedHours < 24) {
        return `${elapsedHours}h ago`;
    }
    const elapsedDays = Math.floor(elapsedHours / 24);
    if (elapsedDays < 7) {
        return `${elapsedDays}d ago`;
    }
    return date.toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year:
            date.getFullYear() === new Date().getFullYear()
                ? undefined
                : "numeric",
    });
}

function idempotencyKey(): string {
    return globalThis.crypto.randomUUID();
}

function errorMessage(reason: unknown): string {
    return reason instanceof Error
        ? reason.message
        : "Oh My Subagents could not update Operator.";
}
