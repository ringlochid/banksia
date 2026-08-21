from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class _WorkspaceAdmissionLock:
    lock: asyncio.Lock
    users: int = 0


class TaskWorkspaceAdmissionCoordinator:
    """Serialize admission recovery and commit for each workspace in one controller."""

    def __init__(self) -> None:
        self._entries_lock = asyncio.Lock()
        self._entries: dict[Path, _WorkspaceAdmissionLock] = {}

    @asynccontextmanager
    async def hold(self, workspace: Path) -> AsyncIterator[None]:
        """Hold one workspace admission lane without blocking unrelated workspaces."""

        entry = await self._register(workspace)
        try:
            async with entry.lock:
                yield
        finally:
            await self._unregister(workspace, entry)

    async def _register(self, workspace: Path) -> _WorkspaceAdmissionLock:
        async with self._entries_lock:
            entry = self._entries.get(workspace)
            if entry is None:
                entry = _WorkspaceAdmissionLock(lock=asyncio.Lock())
                self._entries[workspace] = entry
            entry.users += 1
            return entry

    async def _unregister(
        self,
        workspace: Path,
        entry: _WorkspaceAdmissionLock,
    ) -> None:
        async with self._entries_lock:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(workspace) is entry:
                del self._entries[workspace]


__all__ = ["TaskWorkspaceAdmissionCoordinator"]
