from __future__ import annotations

import logging
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import PlatformDirs

from oh_my_subagents.product_identity import OMS_IDENTITY

SERVICE_LOG_MAX_BYTES = 5 * 1024 * 1024
SERVICE_LOG_BACKUP_COUNT = 3
SERVICE_LOG_LINE_LIMIT = 2_000
SERVICE_LOGGER_NAME = OMS_IDENTITY.service_logger_name


def default_service_log_path() -> Path:
    directories = PlatformDirs(appname=OMS_IDENTITY.application_name, appauthor=False)
    return Path(directories.user_log_path) / "controller.log"


def configure_service_logging(path: Path, *, level: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=SERVICE_LOG_MAX_BYTES,
        backupCount=SERVICE_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
    service_logger = logging.getLogger(SERVICE_LOGGER_NAME)
    service_logger.handlers.clear()
    service_logger.propagate = True
    service_logger.setLevel(logging.INFO)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True


def read_service_log_tail(path: Path, *, line_count: int) -> list[str]:
    if not 1 <= line_count <= SERVICE_LOG_LINE_LIMIT:
        raise ValueError(f"service log line count must be between 1 and {SERVICE_LOG_LINE_LIMIT}")
    if not path.is_file():
        return []
    return _tail_lines(path, line_count=line_count)


def follow_service_log(path: Path, *, start_offset: int | None = None) -> Iterator[str]:
    offset = path.stat().st_size if start_offset is None and path.exists() else start_offset or 0
    while True:
        if not path.exists():
            yield ""
            continue
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(offset)
            for line in stream:
                yield line.rstrip("\n")
            offset = stream.tell()
        yield ""


def _tail_lines(path: Path, *, line_count: int) -> list[str]:
    block_size = 8_192
    with path.open("rb") as stream:
        stream.seek(0, 2)
        position = stream.tell()
        chunks: list[bytes] = []
        newline_count = 0
        while position > 0 and newline_count <= line_count:
            read_size = min(block_size, position)
            position -= read_size
            stream.seek(position)
            chunk = stream.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
    text = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return text.splitlines()[-line_count:]


__all__ = [
    "SERVICE_LOGGER_NAME",
    "SERVICE_LOG_BACKUP_COUNT",
    "SERVICE_LOG_LINE_LIMIT",
    "SERVICE_LOG_MAX_BYTES",
    "configure_service_logging",
    "default_service_log_path",
    "follow_service_log",
    "read_service_log_tail",
]
