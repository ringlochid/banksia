from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """UTC-normalizing datetime column.

    Controller datetimes are UTC by contract, but SQLite ignores
    ``timezone=True`` and round-trips naive values. This type re-attaches UTC
    on read and normalizes aware values to UTC on write without changing the
    stored representation, so every mapped datetime is timezone-aware on every
    backend.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return _coerce_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return _coerce_utc(value)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["UtcDateTime"]
