from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from autoclaw.runtime.command_run.process_resources import CommandTerminalCause
from autoclaw.runtime.command_run.transitions import CommandRunLaunchClaim


@dataclass(slots=True)
class OwnedCommandProcess:
    claim: CommandRunLaunchClaim
    process: asyncio.subprocess.Process | None = None
    terminal_cause: CommandTerminalCause | None = None
    termination_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    launch_state_resolved: asyncio.Event = field(default_factory=asyncio.Event)


__all__ = ["OwnedCommandProcess"]
