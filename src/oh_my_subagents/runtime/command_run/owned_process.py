from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from oh_my_subagents.runtime.command_run.process_resources import (
    CommandOutputCapture,
    CommandTerminalCause,
)
from oh_my_subagents.runtime.command_run.transitions import CommandRunLaunchClaim


class ManagedCommandProcess(Protocol):
    """Host-neutral lifecycle and output surface for one owned command family."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None: ...

    async def read_output(self, byte_limit: int) -> bytes: ...

    async def wait(self) -> int: ...

    def request_termination(self) -> None: ...

    def request_kill(self) -> None: ...

    def close_controller_liveness(self) -> None: ...


@dataclass(slots=True)
class OwnedCommandProcess:
    claim: CommandRunLaunchClaim
    process: ManagedCommandProcess | None = None
    output_capture: CommandOutputCapture | None = None
    terminal_cause: CommandTerminalCause | None = None
    termination_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    launch_state_resolved: asyncio.Event = field(default_factory=asyncio.Event)


__all__ = ["ManagedCommandProcess", "OwnedCommandProcess"]
