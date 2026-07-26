import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { OperatorPanel } from "../../src/features/operator/OperatorPanel";
import { OperatorQuestionCard } from "../../src/features/operator/OperatorQuestionCard";
import type {
    OperatorApi,
    OperatorAssistantQuestionSetEntry,
    OperatorConversationView,
} from "../../src/features/operator/operator-api";

describe("temporary Operator conversation flow", () => {
    it("preserves question drafts and submits stable answers once", async () => {
        const onSubmit = vi.fn();
        const user = userEvent.setup();

        render(
            <OperatorQuestionCard
                disabled={false}
                onSubmit={onSubmit}
                questionSet={questionSet()}
            />,
        );

        await user.click(screen.getByRole("radio", { name: /Reliability/ }));
        await user.click(screen.getByRole("button", { name: "Next" }));
        await user.click(screen.getByRole("radio", { name: "Something else" }));
        await user.type(
            screen.getByRole("textbox", { name: "Something else" }),
            "Twice a day",
        );
        await user.click(screen.getByRole("button", { name: "Back" }));
        expect(
            screen.getByRole("radio", { name: /Reliability/ }),
        ).toBeChecked();
        await user.click(screen.getByRole("button", { name: "Next" }));
        await user.click(screen.getByRole("button", { name: "Continue" }));

        expect(onSubmit).toHaveBeenCalledOnce();
        expect(onSubmit).toHaveBeenCalledWith([
            {
                question_id: "priority",
                answer: { kind: "option", option_id: "reliability" },
            },
            {
                question_id: "schedule",
                answer: { kind: "custom", text: "Twice a day" },
            },
        ]);
    });

    it("creates, messages, asks, and records the controller readback", async () => {
        const ready = conversation(
            "ready",
            [],
            [
                {
                    kind: "send_message",
                    label: "Send message",
                    method: "POST",
                    href: "/api/operator/conversations/op_1/messages",
                },
            ],
        );
        const awaiting = conversation(
            "awaiting_answer",
            [
                {
                    id: "message-1",
                    kind: "user_message",
                    text: "Draft a workflow for me",
                    created_at: "2026-07-26T01:00:00Z",
                },
                questionSet(),
            ],
            [
                {
                    kind: "answer_question_set",
                    label: "Continue",
                    method: "POST",
                    href: "/api/operator/conversations/op_1/question-sets/questions-1/answers",
                    question_set_id: "questions-1",
                },
            ],
        );
        const answered = conversation(
            "ready",
            [
                ...awaiting.entries,
                {
                    id: "answer-1",
                    kind: "user_question_answers",
                    question_set_id: "questions-1",
                    answers: [
                        {
                            question_id: "priority",
                            answer: {
                                kind: "option",
                                option_id: "reliability",
                            },
                        },
                        {
                            question_id: "schedule",
                            answer: { kind: "skip" },
                        },
                    ],
                    created_at: "2026-07-26T01:01:00Z",
                },
                {
                    id: "message-2",
                    kind: "assistant_message",
                    text: "The workflow draft is ready to review.",
                    created_at: "2026-07-26T01:02:00Z",
                },
            ],
            ready.actions,
        );
        const sendMessage = vi.fn(() => resolved(awaiting));
        const answerQuestions = vi.fn(() => resolved(answered));
        const api = operatorApiStub({
            createConversation: vi.fn(() => resolved(ready, 201)),
            sendMessage,
            answerQuestions,
        });
        const onClose = vi.fn();
        const user = userEvent.setup();

        render(
            <MemoryRouter>
                <OperatorPanel api={api} isOpen onClose={onClose} />
            </MemoryRouter>,
        );

        expect(
            await screen.findByRole("button", { name: "Close Operator" }),
        ).toHaveFocus();
        await user.click(
            await screen.findByRole("button", {
                name: "Start conversation",
            }),
        );
        await user.type(
            screen.getByLabelText("Message Operator"),
            "Draft a workflow for me",
        );
        await user.click(screen.getByRole("button", { name: "Send message" }));
        expect(
            await screen.findByText("Draft a workflow for me"),
        ).toBeVisible();
        await user.click(screen.getByRole("radio", { name: /Reliability/ }));
        await user.click(screen.getByRole("button", { name: "Next" }));
        await user.click(
            screen.getByRole("radio", { name: /^Skip this question/ }),
        );
        await user.click(screen.getByRole("button", { name: "Continue" }));

        expect(
            await screen.findByText("The workflow draft is ready to review."),
        ).toBeVisible();
        expect(screen.getByText("Answers sent")).toBeVisible();
        expect(screen.getByText("What matters most?")).toBeVisible();
        expect(screen.getByText("Reliability")).toBeVisible();
        expect(screen.queryByText("reliability")).toBeNull();
        expect(sendMessage).toHaveBeenCalledWith(
            "/api/operator/conversations/op_1/messages",
            "Draft a workflow for me",
            expect.any(String),
        );
        expect(answerQuestions).toHaveBeenCalledWith(
            "/api/operator/conversations/op_1/question-sets/questions-1/answers",
            [
                {
                    question_id: "priority",
                    answer: { kind: "option", option_id: "reliability" },
                },
                {
                    question_id: "schedule",
                    answer: { kind: "skip" },
                },
            ],
            expect.any(String),
        );
        expect(
            screen.getByRole("link", { name: "Open Workflows" }),
        ).toBeVisible();
        await user.keyboard("{Escape}");
        expect(onClose).toHaveBeenCalledOnce();
    });

    it("reloads after an initial status failure", async () => {
        const getStatus = vi
            .fn()
            .mockRejectedValueOnce(new Error("Status unavailable"))
            .mockImplementation(() =>
                resolved({
                    availability: "available",
                    configured_provider: "codex",
                    explanation: "Operator is ready.",
                    setup_action: null,
                }),
            );
        const api = operatorApiStub({ getStatus });
        const user = userEvent.setup();

        render(
            <MemoryRouter>
                <OperatorPanel api={api} isOpen onClose={vi.fn()} />
            </MemoryRouter>,
        );

        expect(await screen.findByText("Status unavailable")).toBeVisible();
        await user.click(screen.getByRole("button", { name: "Reload" }));
        expect(
            await screen.findByRole("button", {
                name: "Start conversation",
            }),
        ).toBeVisible();
        expect(getStatus).toHaveBeenCalledTimes(2);
    });

    it("reuses the create key and reconciles controller truth", async () => {
        const ready = conversation(
            "ready",
            [],
            [
                {
                    kind: "send_message",
                    label: "Send message",
                    method: "POST",
                    href: "/api/operator/conversations/op_1/messages",
                },
            ],
        );
        const listConversations = vi.fn(() =>
            resolved({ items: [], next_cursor: null }),
        );
        const createKeys: string[] = [];
        const createConversation = vi.fn((key: string) => {
            createKeys.push(key);
            return createKeys.length === 1
                ? Promise.reject(new Error("Connection interrupted"))
                : resolved(ready, 201);
        });
        const api = operatorApiStub({
            listConversations,
            createConversation,
            getConversation: () => resolved(ready),
        });
        const user = userEvent.setup();

        render(
            <MemoryRouter>
                <OperatorPanel api={api} isOpen onClose={vi.fn()} />
            </MemoryRouter>,
        );

        const start = await screen.findByRole("button", {
            name: "Start conversation",
        });
        await user.click(start);
        await screen.findByText(/Connection interrupted/);
        await user.click(start);
        expect(await screen.findByLabelText("Message Operator")).toBeEnabled();
        expect(createConversation).toHaveBeenCalledTimes(2);
        expect(createKeys[0]).toBe(createKeys[1]);
        expect(listConversations).toHaveBeenCalledTimes(2);
    });
});

function questionSet(): OperatorAssistantQuestionSetEntry {
    return {
        id: "questions-1",
        kind: "assistant_question_set",
        explanation: "Two choices will shape the draft.",
        created_at: "2026-07-26T01:00:00Z",
        questions: [
            {
                id: "priority",
                header: "Priority",
                question: "What matters most?",
                allow_skip: false,
                options: [
                    {
                        id: "reliability",
                        label: "Reliability",
                        description: "Prefer predictable execution.",
                    },
                    {
                        id: "speed",
                        label: "Speed",
                        description: "Prefer the fastest result.",
                    },
                ],
            },
            {
                id: "schedule",
                header: "Schedule",
                question: "How often should it run?",
                allow_skip: true,
                options: [
                    {
                        id: "daily",
                        label: "Daily",
                        description: "Run every day.",
                    },
                ],
            },
        ],
    };
}

function conversation(
    state: OperatorConversationView["state"],
    entries: OperatorConversationView["entries"],
    actions: OperatorConversationView["actions"],
): OperatorConversationView {
    return {
        id: "op_1",
        provider: "codex",
        state,
        entries,
        actions,
        created_at: "2026-07-26T01:00:00Z",
        updated_at: "2026-07-26T01:00:00Z",
        older_cursor: null,
    };
}

function resolved<T>(body: T, status = 200) {
    return Promise.resolve({ body, status, etag: null });
}

function operatorApiStub(overrides: Partial<OperatorApi>): OperatorApi {
    return {
        getStatus: () =>
            resolved({
                availability: "available",
                configured_provider: "codex",
                explanation: "Operator is ready.",
                setup_action: null,
            }),
        listConversations: () => resolved({ items: [], next_cursor: null }),
        createConversation: () => Promise.reject(new Error("not implemented")),
        getConversation: () => Promise.reject(new Error("not implemented")),
        sendMessage: () => Promise.reject(new Error("not implemented")),
        answerQuestions: () => Promise.reject(new Error("not implemented")),
        ...overrides,
    };
}
