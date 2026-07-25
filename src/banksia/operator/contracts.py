from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from banksia.runtime.contracts.text import normalize_exact_text, normalize_optional_text

type OperatorAvailability = Literal[
    "available",
    "unconfigured",
    "unsupported",
    "unavailable",
]
type OperatorConversationState = Literal[
    "ready",
    "running",
    "awaiting_answer",
    "failed",
    "provider_thread_lost",
]
type OperatorInvocationState = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "provider_thread_lost",
]
type OperatorEffectState = Literal[
    "proposed",
    "executing",
    "succeeded",
    "failed",
    "indeterminate",
]
type OperatorProblemCode = Literal[
    "invalid_operator_request",
    "operator_conversation_not_found",
    "operator_question_set_not_found",
    "operator_confirmation_not_found",
    "operator_action_not_current",
    "idempotency_conflict",
    "effect_in_progress",
    "operator_provider_unavailable",
]

MAX_OPERATOR_TEXT_BYTES = 64 * 1024
MAX_OPERATOR_ANSWER_DEPTH = 16
MAX_OPERATOR_ANSWER_NODES = 1024


class OperatorModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


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


OperatorAnswerValue = Annotated[
    OperatorOptionAnswer | OperatorCustomAnswer | OperatorSkipAnswer,
    Field(discriminator="kind"),
]


class OperatorQuestionAnswer(OperatorModel):
    question_id: Annotated[str, Field(min_length=1, max_length=255)]
    answer: OperatorAnswerValue


class OperatorQuestionAnswersRequest(OperatorModel):
    answers: tuple[OperatorQuestionAnswer, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_serialized_bounds(self) -> OperatorQuestionAnswersRequest:
        payload = self.model_dump(mode="json")
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > (
            MAX_OPERATOR_TEXT_BYTES
        ):
            raise ValueError("question answers exceed the controller text limit")
        depth, nodes = _json_shape_size(payload)
        if depth > MAX_OPERATOR_ANSWER_DEPTH or nodes > MAX_OPERATOR_ANSWER_NODES:
            raise ValueError("question answers exceed the controller structure limit")
        return self


class OperatorFieldError(OperatorModel):
    path: str
    message: str


class OperatorProblem(OperatorModel):
    code: OperatorProblemCode
    message: str
    is_retryable: bool = Field(alias="retryable")
    field_errors: tuple[OperatorFieldError, ...] | None = None


class OperatorStatusResponse(OperatorModel):
    availability: OperatorAvailability
    configured_provider: str | None = None
    problem_code: str | None = None
    explanation: str
    setup_action: str | None = None


class OperatorQuestionOption(OperatorModel):
    id: str
    label: str
    consequence: str


class OperatorQuestion(OperatorModel):
    id: str
    header: str
    question: str
    is_skip_allowed: bool = Field(default=False, alias="allow_skip")
    options: tuple[OperatorQuestionOption, ...] = Field(min_length=2, max_length=3)


class OperatorResourceLink(OperatorModel):
    label: str
    href: str


class OperatorEmptyInput(OperatorModel):
    kind: Literal["empty"] = "empty"


class OperatorMessageTextInput(OperatorModel):
    kind: Literal["message_text"] = "message_text"
    field: Literal["text"] = "text"
    min_length: Literal[1] = 1
    max_length: Literal[65536] = 65536


class OperatorQuestionAnswersInput(OperatorModel):
    kind: Literal["question_answers"] = "question_answers"
    question_set_id: str


OperatorActionInput = Annotated[
    OperatorEmptyInput | OperatorMessageTextInput | OperatorQuestionAnswersInput,
    Field(discriminator="kind"),
]


class OperatorSendMessageAction(OperatorModel):
    kind: Literal["send_message"]
    label: str
    method: Literal["POST"] = "POST"
    href: str
    is_confirmation_required: Literal[False] = Field(
        default=False,
        alias="requires_confirmation",
    )
    input: OperatorMessageTextInput


class OperatorAnswerQuestionSetAction(OperatorModel):
    kind: Literal["answer_question_set"]
    label: str
    method: Literal["POST"] = "POST"
    href: str
    is_confirmation_required: Literal[False] = Field(
        default=False,
        alias="requires_confirmation",
    )
    input: OperatorQuestionAnswersInput
    question_set_id: str


class OperatorConfirmEffectAction(OperatorModel):
    kind: Literal["confirm_effect"]
    label: str
    method: Literal["POST"] = "POST"
    href: str
    is_confirmation_required: Literal[True] = Field(
        default=True,
        alias="requires_confirmation",
    )
    consequence: str
    input: OperatorEmptyInput
    confirmation_id: str
    scope: str


class OperatorRetryProviderInvocationAction(OperatorModel):
    kind: Literal["retry_provider_invocation"]
    label: str
    method: Literal["POST"] = "POST"
    href: str
    is_confirmation_required: Literal[False] = Field(
        default=False,
        alias="requires_confirmation",
    )
    input: OperatorEmptyInput


class OperatorCreateNewConversationAction(OperatorModel):
    kind: Literal["create_new_conversation"]
    label: str
    method: Literal["POST"] = "POST"
    href: str
    is_confirmation_required: Literal[False] = Field(
        default=False,
        alias="requires_confirmation",
    )
    input: OperatorEmptyInput


OperatorLegalAction = Annotated[
    OperatorSendMessageAction
    | OperatorAnswerQuestionSetAction
    | OperatorConfirmEffectAction
    | OperatorRetryProviderInvocationAction
    | OperatorCreateNewConversationAction,
    Field(discriminator="kind"),
]
OPERATOR_LEGAL_ACTION_ADAPTER: TypeAdapter[OperatorLegalAction] = TypeAdapter(OperatorLegalAction)


class OperatorUserMessageEntry(OperatorModel):
    id: str
    kind: Literal["user_message"]
    text: str
    created_at: datetime


class OperatorAssistantMessageEntry(OperatorModel):
    id: str
    kind: Literal["assistant_message"]
    text: str
    created_at: datetime


class OperatorQuestionSetEntry(OperatorModel):
    id: str
    kind: Literal["question_set"]
    explanation: str | None = None
    questions: tuple[OperatorQuestion, ...] = Field(min_length=1, max_length=3)
    created_at: datetime


class OperatorQuestionAnswerEntry(OperatorModel):
    id: str
    kind: Literal["question_answer"]
    question_set_id: str
    answers: tuple[OperatorQuestionAnswer, ...] = Field(min_length=1, max_length=3)
    created_at: datetime


class OperatorActionProposalEntry(OperatorModel):
    id: str
    kind: Literal["action_proposal"]
    confirmation_id: str
    label: str
    scope: str
    consequence: str
    created_at: datetime


class OperatorUndoProposal(OperatorModel):
    confirmation_id: str
    label: str
    scope: str
    consequence: str


class OperatorEffectReceiptEntry(OperatorModel):
    id: str
    kind: Literal["effect_receipt"]
    summary: str
    resource: OperatorResourceLink | None = None
    undo: OperatorUndoProposal | None = None
    created_at: datetime


class OperatorRecoveryAction(OperatorModel):
    kind: Literal["retry_provider_invocation", "create_new_conversation"]
    label: str
    href: str


class OperatorRecoverableErrorEntry(OperatorModel):
    id: str
    kind: Literal["recoverable_error"]
    problem: str
    explanation: str
    recovery_action: OperatorRecoveryAction
    created_at: datetime


OperatorConversationEntry = Annotated[
    OperatorUserMessageEntry
    | OperatorAssistantMessageEntry
    | OperatorQuestionSetEntry
    | OperatorQuestionAnswerEntry
    | OperatorActionProposalEntry
    | OperatorEffectReceiptEntry
    | OperatorRecoverableErrorEntry,
    Field(discriminator="kind"),
]
OPERATOR_ENTRY_ADAPTER: TypeAdapter[OperatorConversationEntry] = TypeAdapter(
    OperatorConversationEntry
)


class OperatorConversationSummary(OperatorModel):
    id: str
    state: OperatorConversationState
    preview: str | None = None
    configured_provider: str
    created_at: datetime
    updated_at: datetime


class OperatorConversationPage(OperatorModel):
    items: tuple[OperatorConversationSummary, ...]
    next_cursor: str | None = None


class OperatorConversationView(OperatorModel):
    id: str
    state: OperatorConversationState
    configured_provider: str
    entries: tuple[OperatorConversationEntry, ...]
    older_cursor: str | None = None
    legal_actions: tuple[OperatorLegalAction, ...]
    created_at: datetime
    updated_at: datetime


class OperatorProblemResponse(OperatorModel):
    problem: OperatorProblem
    current: OperatorConversationView | None = None


class OperatorProviderQuestionOption(OperatorModel):
    label: Annotated[str, Field(min_length=1, max_length=255)]
    consequence: Annotated[str, Field(min_length=1, max_length=1024)]

    @field_validator("label", "consequence", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="question option text",
            is_nonblank_required=True,
        )


class OperatorProviderQuestion(OperatorModel):
    header: Annotated[str, Field(min_length=1, max_length=64)]
    question: Annotated[str, Field(min_length=1, max_length=4096)]
    is_skip_allowed: bool = Field(default=False, alias="allow_skip")
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
            max_characters=2048,
        )

    @model_validator(mode="after")
    def validate_serialized_size(self) -> OperatorProviderAskUserResult:
        payload = self.model_dump(mode="json")
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > (
            MAX_OPERATOR_TEXT_BYTES
        ):
            raise ValueError("question set exceeds the controller text limit")
        return self


OperatorProviderResult = Annotated[
    OperatorProviderMessageResult | OperatorProviderAskUserResult,
    Field(discriminator="kind"),
]
OPERATOR_PROVIDER_RESULT_ADAPTER: TypeAdapter[OperatorProviderResult] = TypeAdapter(
    OperatorProviderResult
)


def _json_shape_size(value: object, *, depth: int = 1) -> tuple[int, int]:
    if isinstance(value, dict):
        child_sizes = [_json_shape_size(item, depth=depth + 1) for item in value.values()]
        return max((size[0] for size in child_sizes), default=depth), 1 + sum(
            size[1] for size in child_sizes
        )
    if isinstance(value, list):
        child_sizes = [_json_shape_size(item, depth=depth + 1) for item in value]
        return max((size[0] for size in child_sizes), default=depth), 1 + sum(
            size[1] for size in child_sizes
        )
    return depth, 1


__all__ = [
    "MAX_OPERATOR_TEXT_BYTES",
    "OPERATOR_ENTRY_ADAPTER",
    "OPERATOR_LEGAL_ACTION_ADAPTER",
    "OPERATOR_PROVIDER_RESULT_ADAPTER",
    "OperatorActionProposalEntry",
    "OperatorAnswerQuestionSetAction",
    "OperatorAnswerValue",
    "OperatorAvailability",
    "OperatorConfirmEffectAction",
    "OperatorConversationEntry",
    "OperatorConversationPage",
    "OperatorConversationState",
    "OperatorConversationSummary",
    "OperatorConversationView",
    "OperatorCreateNewConversationAction",
    "OperatorEffectReceiptEntry",
    "OperatorEffectState",
    "OperatorEmptyRequest",
    "OperatorInvocationState",
    "OperatorLegalAction",
    "OperatorMessageRequest",
    "OperatorProblem",
    "OperatorProblemCode",
    "OperatorProblemResponse",
    "OperatorProviderAskUserResult",
    "OperatorProviderMessageResult",
    "OperatorProviderResult",
    "OperatorQuestionAnswer",
    "OperatorQuestionAnswerEntry",
    "OperatorQuestionAnswersRequest",
    "OperatorQuestionSetEntry",
    "OperatorRecoverableErrorEntry",
    "OperatorRetryProviderInvocationAction",
    "OperatorSendMessageAction",
    "OperatorStatusResponse",
]
