from __future__ import annotations

import re
import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, cast

from autoclaw.persistence import RuntimeBase
from autoclaw.persistence.session import install_sqlite_transaction_control
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


class SyncSessionAdapter:
    """Expose the async session methods used by domain code over real sync SQLite."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._session = factory()

    async def __aenter__(self) -> SyncSessionAdapter:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc, traceback
        if exc_type is not None:
            self._session.rollback()
        self._session.close()

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.get(*args, **kwargs)

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.scalar(*args, **kwargs)

    async def scalars(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.scalars(*args, **kwargs)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.execute(*args, **kwargs)

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        with self._session.begin_nested():
            yield

    async def flush(self, objects: tuple[object, ...] | None = None) -> None:
        self._session.flush(objects)

    async def delete(self, instance: object) -> None:
        self._session.delete(instance)

    def add(self, instance: object) -> None:
        self._session.add(instance)

    def add_all(self, instances: tuple[object, ...]) -> None:
        self._session.add_all(instances)

    def get_bind(self) -> Engine:
        return cast(Engine, self._session.get_bind())


def create_runtime_schema_engine(tmp_path: Path, *, name: str = "runtime.sqlite") -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    install_sqlite_transaction_control(engine)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(
        dbapi_connection: sqlite3.Connection,
        connection_record: object,
    ) -> None:
        del connection_record
        dbapi_connection.execute("PRAGMA foreign_keys = ON")
        dbapi_connection.execute("PRAGMA busy_timeout = 5000")
        dbapi_connection.execute("PRAGMA journal_mode = WAL")

    RuntimeBase.metadata.create_all(engine)
    return engine


@contextmanager
def sqlite_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
    finally:
        connection.close()


def rewrite_empty_sqlite_table(
    path: Path,
    *,
    table_name: str,
    transform: Callable[[str], str],
    omitted_indexes: frozenset[str] = frozenset(),
    index_transform: Callable[[str, str], str] | None = None,
) -> None:
    replacement_name = f"{table_name}__replacement"
    with sqlite_connection(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        table_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        assert table_row is not None and isinstance(table_row[0], str)
        index_rows = connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
            (table_name,),
        ).fetchall()
        replacement_ddl = re.sub(
            rf"^CREATE TABLE {re.escape(table_name)}",
            f"CREATE TABLE {replacement_name}",
            table_row[0],
            count=1,
        )
        replacement_ddl = transform(replacement_ddl)
        connection.execute(replacement_ddl)
        connection.execute(f'DROP TABLE "{table_name}"')
        connection.execute(f'ALTER TABLE "{replacement_name}" RENAME TO "{table_name}"')
        for index_name, index_sql in index_rows:
            if index_name not in omitted_indexes:
                if index_transform is not None:
                    index_sql = index_transform(index_name, index_sql)
                connection.execute(index_sql)
        connection.commit()


__all__ = [
    "SyncSessionAdapter",
    "create_runtime_schema_engine",
    "rewrite_empty_sqlite_table",
]
