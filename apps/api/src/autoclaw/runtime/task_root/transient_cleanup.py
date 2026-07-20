from __future__ import annotations

import asyncio
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import TransientLocalizationModel
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import TaskRootPaths
from autoclaw.runtime.post_commit import TransientCleanupRequested
from autoclaw.runtime.task_root.logical_paths import (
    normalize_logical_task_path,
    resolve_logical_task_path,
)
from autoclaw.runtime.task_root.reads import read_task_root_paths

_LOCALIZED_LOGICAL_PREFIX = "tmp/transfers/localized/"


async def cleanup_expired_transient(
    session: AsyncSession,
    signal: TransientCleanupRequested,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> bool:
    """Remove one exact inactive transient body and commit its removed state."""

    source = (
        await session.execute(
            select(
                TransientLocalizationModel.task_id,
                TransientLocalizationModel.localized_logical_path,
            ).where(
                TransientLocalizationModel.transient_localization_id
                == signal.transient_localization_id,
                TransientLocalizationModel.retention_status == "expired",
                TransientLocalizationModel.expires_at == signal.expires_at,
            )
        )
    ).one_or_none()
    if source is None:
        return False
    task_id, localized_logical_path = source
    active_reference_exists = await session.scalar(
        select(
            exists().where(
                TransientLocalizationModel.task_id == task_id,
                TransientLocalizationModel.localized_logical_path == localized_logical_path,
                TransientLocalizationModel.retention_status == "active",
            )
        )
    )
    if active_reference_exists:
        raise RuntimeError("expired transient body still has an active reference")

    paths = await read_task_root_paths(session, task_id)
    await asyncio.to_thread(
        _remove_localized_body,
        paths,
        localized_logical_path,
    )
    removed_id = await session.scalar(
        update(TransientLocalizationModel)
        .where(
            TransientLocalizationModel.transient_localization_id
            == signal.transient_localization_id,
            TransientLocalizationModel.retention_status == "expired",
            TransientLocalizationModel.expires_at == signal.expires_at,
        )
        .values(retention_status="removed", removed_at=clock())
        .returning(TransientLocalizationModel.transient_localization_id)
    )
    if removed_id is None:
        await session.rollback()
        return False
    await session.commit()
    return True


def _remove_localized_body(paths: TaskRootPaths, logical_path: str) -> None:
    normalized = normalize_logical_task_path(logical_path)
    if not normalized.startswith(_LOCALIZED_LOGICAL_PREFIX):
        raise ValueError("transient cleanup path is outside the localized transfer root")
    resolved = resolve_logical_task_path(paths, normalized)
    assert resolved is not None
    localized_root = paths.localized_path.resolve()
    if not resolved.physical_path.is_relative_to(localized_root):
        raise ValueError("transient cleanup path escapes the localized transfer root")

    candidate = paths.task_root.joinpath(*PurePosixPath(normalized).parts)
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISREG(mode):
        raise ValueError("transient cleanup target is not a regular file")
    candidate.unlink()


__all__ = ["cleanup_expired_transient"]
