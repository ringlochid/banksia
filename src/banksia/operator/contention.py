from __future__ import annotations

from sqlalchemy.exc import OperationalError

OPERATOR_PERSISTENCE_ATTEMPTS = 5
_POSTGRES_CONTENTION_CODES = frozenset({"40001", "40P01", "55P03"})


class OperatorPersistenceContentionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Operator persistence is temporarily contended")


def is_recognized_persistence_contention(exc: OperationalError) -> bool:
    original = exc.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate in _POSTGRES_CONTENTION_CODES:
        return True
    message = str(original).casefold()
    return "database is locked" in message or "database table is locked" in message


__all__ = [
    "OPERATOR_PERSISTENCE_ATTEMPTS",
    "OperatorPersistenceContentionError",
    "is_recognized_persistence_contention",
]
