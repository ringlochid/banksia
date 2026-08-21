from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import Field

from banksia.operator.contracts import (
    OperatorAvailability,
    OperatorModel,
    OperatorProviderResult,
)


class OperatorMessageTurnInput(OperatorModel):
    kind: Literal["message"] = "message"
    text: str


class OperatorAcceptedOptionAnswer(OperatorModel):
    kind: Literal["option"] = "option"
    label: str


class OperatorAcceptedCustomAnswer(OperatorModel):
    kind: Literal["custom"] = "custom"
    text: str


class OperatorAcceptedSkipAnswer(OperatorModel):
    kind: Literal["skip"] = "skip"


type OperatorAcceptedAnswer = Annotated[
    OperatorAcceptedOptionAnswer | OperatorAcceptedCustomAnswer | OperatorAcceptedSkipAnswer,
    Field(discriminator="kind"),
]


class OperatorAnsweredQuestion(OperatorModel):
    question: str
    answer: OperatorAcceptedAnswer


class OperatorQuestionAnswersTurnInput(OperatorModel):
    kind: Literal["question_answers"] = "question_answers"
    answers: tuple[OperatorAnsweredQuestion, ...]


type OperatorTurnInput = OperatorMessageTurnInput | OperatorQuestionAnswersTurnInput


@dataclass(frozen=True, slots=True)
class OperatorRunnerStatus:
    availability: OperatorAvailability
    configured_provider: str | None
    explanation: str
    setup_action: str | None = None
    model: str | None = None
    effort: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorTurnRequest:
    provider: str
    model: str | None
    effort: str | None
    provider_thread_id: str | None
    input: OperatorTurnInput


@dataclass(frozen=True, slots=True)
class OperatorTurnOutcome:
    provider_thread_id: str
    result: OperatorProviderResult

    def __post_init__(self) -> None:
        if not self.provider_thread_id.strip():
            raise ValueError("provider thread ID must not be blank")


class OperatorTurnRunner(Protocol):
    @property
    def status(self) -> OperatorRunnerStatus: ...

    async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome: ...


class OperatorProviderUnavailableError(RuntimeError):
    """Raised when no configured Operator provider can run a turn."""


class OperatorProviderThreadUnavailableError(RuntimeError):
    """Raised when the provider can no longer resume the opaque thread."""

    def __init__(self) -> None:
        super().__init__("the Operator provider thread is unavailable")


class UnavailableOperatorTurnRunner:
    def __init__(self, status: OperatorRunnerStatus | None = None) -> None:
        self._status = status or OperatorRunnerStatus(
            availability="unconfigured",
            configured_provider=None,
            explanation="Operator is not configured with a provider.",
            setup_action="Run `oms operator setup`, then restart Oh My Subagents.",
        )

    @property
    def status(self) -> OperatorRunnerStatus:
        return self._status

    async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome:
        del request
        raise OperatorProviderUnavailableError("Operator provider is unavailable")


__all__ = [
    "OperatorAcceptedAnswer",
    "OperatorAcceptedCustomAnswer",
    "OperatorAcceptedOptionAnswer",
    "OperatorAcceptedSkipAnswer",
    "OperatorAnsweredQuestion",
    "OperatorMessageTurnInput",
    "OperatorProviderThreadUnavailableError",
    "OperatorProviderUnavailableError",
    "OperatorQuestionAnswersTurnInput",
    "OperatorRunnerStatus",
    "OperatorTurnInput",
    "OperatorTurnOutcome",
    "OperatorTurnRequest",
    "OperatorTurnRunner",
    "UnavailableOperatorTurnRunner",
]
