from __future__ import annotations

import errno
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

_CONTROL_POLL_SECONDS = 0.05
_CONTROLLER_LOSS_GRACE_SECONDS = 2.0


def main(arguments: Sequence[str] | None = None) -> int:
    """Run one command in an admitted directory and own its POSIX process group."""

    argv = tuple(sys.argv[1:] if arguments is None else arguments)
    cwd_descriptor, control_descriptor, status_descriptor, command = _parse_arguments(argv)
    try:
        os.fchdir(cwd_descriptor)
    finally:
        os.close(cwd_descriptor)

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        _write_launch_status(status_descriptor, f"ERR {exc.errno or errno.EIO}\n")
        return 127

    _write_launch_status(status_descriptor, f"OK {process.pid}\n")
    return _supervise_process_group(process, control_descriptor)


def _parse_arguments(arguments: tuple[str, ...]) -> tuple[int, int, int, tuple[str, ...]]:
    if len(arguments) < 5:
        raise ValueError("POSIX guardian arguments are incomplete")
    cwd_descriptor = int(arguments[0])
    control_descriptor = int(arguments[1])
    status_descriptor = int(arguments[2])
    command_kind = arguments[3]
    payload = arguments[4:]
    if command_kind == "argv":
        if not payload:
            raise ValueError("POSIX guardian argv command is empty")
        command = payload
    elif command_kind == "shell":
        if len(payload) != 1:
            raise ValueError("POSIX guardian shell command is invalid")
        command = ("/bin/sh", "-c", payload[0])
    else:
        raise ValueError("POSIX guardian command kind is invalid")
    return cwd_descriptor, control_descriptor, status_descriptor, command


def _write_launch_status(descriptor: int, status: str) -> None:
    try:
        os.write(descriptor, status.encode("ascii", errors="strict"))
    finally:
        os.close(descriptor)


def _supervise_process_group(
    process: subprocess.Popen[bytes],
    control_descriptor: int,
) -> int:
    termination_deadline: float | None = None
    should_force_kill = False
    is_control_open = True
    try:
        while process.poll() is None:
            readable, _, _ = (
                select.select(
                    (control_descriptor,),
                    (),
                    (),
                    _CONTROL_POLL_SECONDS,
                )
                if is_control_open
                else ((), (), ())
            )
            if not is_control_open:
                time.sleep(_CONTROL_POLL_SECONDS)
            if readable:
                command = os.read(control_descriptor, 64)
                if not command:
                    os.close(control_descriptor)
                    is_control_open = False
                    _signal_group(process.pid, signal.SIGTERM)
                    if termination_deadline is None:
                        termination_deadline = time.monotonic() + _CONTROLLER_LOSS_GRACE_SECONDS
                elif b"K" in command:
                    _signal_group(process.pid, signal.SIGKILL)
                    should_force_kill = True
                elif b"T" in command and termination_deadline is None:
                    _signal_group(process.pid, signal.SIGTERM)
            if termination_deadline is not None and time.monotonic() >= termination_deadline:
                _signal_group(process.pid, signal.SIGKILL)
                should_force_kill = True
                termination_deadline = None
        returncode = process.wait()
        _cleanup_remaining_group(
            process.pid,
            should_force_kill=should_force_kill,
        )
        return _portable_returncode(returncode)
    finally:
        if is_control_open:
            os.close(control_descriptor)


def _cleanup_remaining_group(process_group_id: int, *, should_force_kill: bool) -> None:
    if not _process_group_exists(process_group_id):
        return
    if not should_force_kill:
        _signal_group(process_group_id, signal.SIGTERM)
        deadline = time.monotonic() + _CONTROL_POLL_SECONDS
        while time.monotonic() < deadline:
            if not _process_group_exists(process_group_id):
                return
            time.sleep(0.01)
    _signal_group(process_group_id, signal.SIGKILL)


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_group(process_group_id: int, selected_signal: signal.Signals) -> None:
    try:
        os.killpg(process_group_id, selected_signal)
    except ProcessLookupError:
        return


def _portable_returncode(returncode: int) -> int:
    if returncode >= 0:
        return returncode
    return 128 + abs(returncode)


if __name__ == "__main__":
    raise SystemExit(main())
