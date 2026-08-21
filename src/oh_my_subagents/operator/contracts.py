from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from oh_my_subagents.runtime.contracts.text import normalize_exact_text, normalize_optional_text

MAX_OPERATOR_TEXT_BYTES = 64 * 1024
MAX_OPERATOR_EXPLANATION_CHARACTERS = 2_048
MAX_OPERATOR_QUESTION_HEADER_CHARACTERS = 64
MAX_OPERATOR_QUESTION_CHARACTERS = 4_096
MAX_OPERATOR_OPTION_LABEL_CHARACTERS = 255
MAX_OPERATOR_OPTION_DESCRIPTION_CHARACTERS = 1_024

type OperatorAvailability = Literal["available", "unconfigured", "unavailable"]
type OperatorConversationState = Literal[
    "ready",
    "running",
    "awaiting_answer",
    "interrupted",
    "closed",
]


class OperatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OperatorEmptyRequest(OperatorModel):
    pass


class OperatorMessageRequest(OperatorModel):
    text: str

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="Operator message",
            max_utf8_bytes=MAX_OPERATOR_TEXT_BYTES,
            is_nonblank_required=True,
        )


class OperatorOptionAnswer(OperatorModel):
    kind: Literal["option"]
    option_id: Annotated[str, Field(min_length=1, max_length=255)]


class OperatorCustomAnswer(OperatorModel):
    kind: Literal["custom"]
    text: str

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="custom answer",
            max_utf8_bytes=MAX_OPERATOR_TEXT_BYTES,
            is_nonblank_required=True,
        )


class OperatorSkipAnswer(OperatorModel):
    kind: Literal["skip"]


type OperatorAnswerValue = Annotated[
    OperatorOptionAnswer | OperatorCustomAnswer | OperatorSkipAnswer,
    Field(discriminator="kind"),
]


class OperatorQuestionAnswer(OperatorModel):
    question_id: Annotated[str, Field(min_length=1, max_length=255)]
    answer: OperatorAnswerValue


class OperatorQuestionAnswersRequest(OperatorModel):
    answers: tuple[OperatorQuestionAnswer, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_serialized_size(self) -> OperatorQuestionAnswersRequest:
        payload = self.model_dump(mode="json")
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(serialized) > MAX_OPERATOR_TEXT_BYTES:
            raise ValueError("question answers exceed the controller text limit")
        return self


class OperatorStatusResponse(OperatorModel):
    availability: OperatorAvailability
    configured_provider: str | None = None
    explanation: str
    setup_action: str | None = None


class OperatorQuestionOption(OperatorModel):
    id: str
    label: str
    description: str


class OperatorQuestion(OperatorModel):
    id: str
    header: str
    question: str
    allow_skip: bool = False
    options: tuple[OperatorQuestionOption, ...] = Field(min_length=2, max_length=3)


class OperatorUserMessageEntry(OperatorModel):
    id: str
    kind: Literal["user_message"]
    text: str
    created_at: datetime


class OperatorUserQuestionAnswersEntry(OperatorModel):
    id: str
    kind: Literal["user_question_answers"]
    question_set_id: str
    answers: tuple[OperatorQuestionAnswer, ...] = Field(min_length=1, max_length=3)
    created_at: datetime


class OperatorAssistantMessageEntry(OperatorModel):
    id: str
    kind: Literal["assistant_message"]
    text: str
    created_at: datetime


class OperatorAssistantQuestionSetEntry(OperatorModel):
    id: str
    kind: Literal["assistant_question_set"]
    explanation: str | None = None
    questions: tuple[OperatorQuestion, ...] = Field(min_length=1, max_length=3)
    created_at: datetime


class OperatorTurnInterruptedEntry(OperatorModel):
    id: str
    kind: Literal["turn_interrupted"]
    explanation: str
    next_step: str
    created_at: datetime


type OperatorConversationEntry = Annotated[
    OperatorUserMessageEntry
    | OperatorUserQuestionAnswersEntry
    | OperatorAssistantMessageEntry
    | OperatorAssistantQuestionSetEntry
    | OperatorTurnInterruptedEntry,
    Field(discriminator="kind"),
]


class OperatorSendMessageAction(OperatorModel):
    kind: Literal["send_message"] = "send_message"
    label: Literal["Send message"] = "Send message"
    method: Literal["POST"] = "POST"
    href: str


class OperatorAnswerQuestionSetAction(OperatorModel):
    kind: Literal["answer_question_set"] = "answer_question_set"
    label: Literal["Continue"] = "Continue"
    method: Literal["POST"] = "POST"
    href: str
    question_set_id: str


class OperatorCreateNewConversationAction(OperatorModel):
    kind: Literal["create_new_conversation"] = "create_new_conversation"
    label: Literal["Start new conversation"] = "Start new conversation"
    method: Literal["POST"] = "POST"
    href: str


type OperatorConversationAction = Annotated[
    OperatorSendMessageAction
    | OperatorAnswerQuestionSetAction
    | OperatorCreateNewConversationAction,
    Field(discriminator="kind"),
]


class OperatorConversationSummary(OperatorModel):
    id: str
    state: OperatorConversationState
    provider: str
    preview: str | None = None
    created_at: datetime
    updated_at: datetime


class OperatorConversationPage(OperatorModel):
    items: tuple[OperatorConversationSummary, ...]
    next_cursor: str | None = None


class OperatorConversationView(OperatorModel):
    id: str
    state: OperatorConversationState
    provider: str
    model: str | None = None
    effort: str | None = None
    entries: tuple[OperatorConversationEntry, ...]
    older_cursor: str | None = None
    actions: tuple[OperatorConversationAction, ...]
    created_at: datetime
    updated_at: datetime


class OperatorProviderQuestionOption(OperatorModel):
    label: Annotated[
        str,
        Field(min_length=1, max_length=MAX_OPERATOR_OPTION_LABEL_CHARACTERS),
    ]
    description: Annotated[
        str,
        Field(min_length=1, max_length=MAX_OPERATOR_OPTION_DESCRIPTION_CHARACTERS),
    ]

    @field_validator("label", "description", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="question option text",
            is_nonblank_required=True,
        )


class OperatorProviderQuestion(OperatorModel):
    header: Annotated[
        str,
        Field(min_length=1, max_length=MAX_OPERATOR_QUESTION_HEADER_CHARACTERS),
    ]
    question: Annotated[
        str,
        Field(min_length=1, max_length=MAX_OPERATOR_QUESTION_CHARACTERS),
    ]
    allow_skip: bool = False
    options: tuple[OperatorProviderQuestionOption, ...] = Field(min_length=2, max_length=3)

    @field_validator("header", "question", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="question text",
            is_nonblank_required=True,
        )

    @model_validator(mode="after")
    def reject_browser_owned_options(self) -> OperatorProviderQuestion:
        browser_owned_labels = {"other", "something else"}
        if any(option.label.strip().casefold() in browser_owned_labels for option in self.options):
            raise ValueError("the browser owns the Something else answer option")
        return self


class OperatorProviderMessageResult(OperatorModel):
    kind: Literal["message"]
    text: str

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="Operator response",
            max_utf8_bytes=MAX_OPERATOR_TEXT_BYTES,
            is_nonblank_required=True,
        )


class OperatorProviderAskUserResult(OperatorModel):
    kind: Literal["ask_user"]
    explanation: str | None = None
    questions: tuple[OperatorProviderQuestion, ...] = Field(min_length=1, max_length=3)

    @field_validator("explanation", mode="before")
    @classmethod
    def normalize_explanation(cls, value: object | None) -> str | None:
        return normalize_optional_text(
            value,
            label="question explanation",
            max_characters=MAX_OPERATOR_EXPLANATION_CHARACTERS,
        )

    @model_validator(mode="after")
    def validate_serialized_size(self) -> OperatorProviderAskUserResult:
        payload = self.model_dump(mode="json")
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(serialized) > MAX_OPERATOR_TEXT_BYTES:
            raise ValueError("question set exceeds the controller text limit")
        return self


type OperatorProviderResult = Annotated[
    OperatorProviderMessageResult | OperatorProviderAskUserResult,
    Field(discriminator="kind"),
]
OPERATOR_PROVIDER_RESULT_ADAPTER: TypeAdapter[OperatorProviderResult] = TypeAdapter(
    OperatorProviderResult
)


__all__ = [
    "MAX_OPERATOR_TEXT_BYTES",
    "OPERATOR_PROVIDER_RESULT_ADAPTER",
    "OperatorAnswerValue",
    "OperatorAssistantMessageEntry",
    "OperatorAssistantQuestionSetEntry",
    "OperatorAvailability",
    "OperatorConversationAction",
    "OperatorConversationEntry",
    "OperatorConversationPage",
    "OperatorConversationState",
    "OperatorConversationSummary",
    "OperatorConversationView",
    "OperatorCreateNewConversationAction",
    "OperatorCustomAnswer",
    "OperatorEmptyRequest",
    "OperatorMessageRequest",
    "OperatorOptionAnswer",
    "OperatorProviderAskUserResult",
    "OperatorProviderMessageResult",
    "OperatorProviderQuestion",
    "OperatorProviderQuestionOption",
    "OperatorProviderResult",
    "OperatorQuestion",
    "OperatorQuestionAnswer",
    "OperatorQuestionAnswersRequest",
    "OperatorQuestionOption",
    "OperatorSendMessageAction",
    "OperatorSkipAnswer",
    "OperatorStatusResponse",
    "OperatorTurnInterruptedEntry",
    "OperatorUserMessageEntry",
    "OperatorUserQuestionAnswersEntry",
]
