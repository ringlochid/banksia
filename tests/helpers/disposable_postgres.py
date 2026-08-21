from __future__ import annotations

import os

from sqlalchemy.engine import URL, make_url


def read_disposable_postgres_url() -> URL | None:
    raw_url = os.environ.get("OMS_TEST_POSTGRES_URL") or os.environ.get("OMS_DATABASE_URL")
    if raw_url is None:
        return None
    database_url = make_url(raw_url)
    database_name = database_url.database or ""
    if database_url.get_backend_name() != "postgresql" or "test" not in database_name.casefold():
        return None
    return database_url.set(drivername="postgresql+asyncpg")


__all__ = ["read_disposable_postgres_url"]
