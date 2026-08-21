from __future__ import annotations


class OperatorConversationError(ValueError):
    """Base class for product-safe Operator conversation failures."""


class OperatorConversationNotFoundError(OperatorConversationError):
    """Raised when the requested conversation does not exist."""


class OperatorQuestionSetNotFoundError(OperatorConversationError):
    """Raised when the requested question set is not the current set."""


class OperatorConversationConflictError(OperatorConversationError):
    """Raised when the current conversation state rejects a new turn."""


class OperatorIdempotencyConflictError(OperatorConversationError):
    """Raised when one request key is reused for a different normalized body."""


class OperatorTurnInProgressError(OperatorConversationConflictError):
    """Raised when a matching active turn did not reach durable readback in time."""


class OperatorAnswerValidationError(OperatorConversationError):
    """Raised when submitted answers do not exactly satisfy the current question set."""


class OperatorCursorValidationError(OperatorConversationError):
    """Raised when an opaque Operator read cursor is malformed."""


class OperatorIdempotencyKeyValidationError(OperatorConversationError):
    """Raised when an Operator request key is blank or exceeds its bound."""


class OperatorUnavailableError(OperatorConversationError):
    """Raised when no configured Operator runner is available."""


__all__ = [
    "OperatorAnswerValidationError",
    "OperatorConversationConflictError",
    "OperatorConversationError",
    "OperatorConversationNotFoundError",
    "OperatorCursorValidationError",
    "OperatorIdempotencyConflictError",
    "OperatorIdempotencyKeyValidationError",
    "OperatorQuestionSetNotFoundError",
    "OperatorTurnInProgressError",
    "OperatorUnavailableError",
]
