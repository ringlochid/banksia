from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

_CREATE_NO_WINDOW = 0x08000000
_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_JOB_KILL_ON_CLOSE = 0x00002000
_TERMINATED_EXIT_CODE = 0xC000013A
_ctypes_windows: Any = ctypes


def main(arguments: Sequence[str] | None = None) -> int:
    """Own one Windows process family in a kill-on-close Job Object."""

    if os.name != "nt":
        raise RuntimeError("the Windows command guardian requires Windows")
    working_directory, command = _parse_arguments(
        tuple(sys.argv[1:] if arguments is None else arguments)
    )
    import win32api
    import win32con
    import win32event
    import win32file
    import win32job
    import win32process

    job: Any = win32job.CreateJobObject(None, "")  # type: ignore[func-returns-value]
    job_information = win32job.QueryInformationJobObject(
        job,
        win32job.JobObjectExtendedLimitInformation,
    )
    job_information["BasicLimitInformation"]["LimitFlags"] |= _JOB_KILL_ON_CLOSE
    win32job.SetInformationJobObject(
        job,
        win32job.JobObjectExtendedLimitInformation,
        job_information,
    )

    null_input: Any = win32file.CreateFile(
        "NUL",
        win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
        None,
        win32con.OPEN_EXISTING,
        0,
        None,
    )
    output_handle = _inheritable_standard_output()
    win32api.SetHandleInformation(int(null_input), win32con.HANDLE_FLAG_INHERIT, 1)
    startup = win32process.STARTUPINFO()
    startup.dwFlags |= win32process.STARTF_USESTDHANDLES
    startup.hStdInput = int(null_input)
    startup.hStdOutput = output_handle
    startup.hStdError = output_handle
    process_handle: Any | None = None
    thread_handle: Any | None = None
    try:
        try:
            process_handle, thread_handle, process_id, _thread_id = win32process.CreateProcess(
                None,
                subprocess.list2cmdline(command),
                None,
                None,
                True,
                _CREATE_SUSPENDED | _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT,
                dict(os.environ),
                working_directory,
                startup,
            )
            win32job.AssignProcessToJobObject(job, process_handle)
        except Exception as exc:
            print(f"ERR {_exception_error_number(exc)}", flush=True)
            return 127

        print(f"OK {process_id}", flush=True)
        win32process.ResumeThread(thread_handle)
        stop_event = threading.Event()
        control_thread = threading.Thread(
            target=_watch_controller,
            args=(job, stop_event),
            name="banksia-command-control",
            daemon=True,
        )
        control_thread.start()
        win32event.WaitForSingleObject(process_handle, win32event.INFINITE)
        exit_code = int(win32process.GetExitCodeProcess(process_handle))
        stop_event.set()
        win32job.TerminateJobObject(job, exit_code)
        return exit_code
    finally:
        for handle in (thread_handle, process_handle, null_input, job):
            if handle is not None:
                with suppress(OSError):
                    win32api.CloseHandle(int(handle))


def _parse_arguments(arguments: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    if len(arguments) < 3:
        raise ValueError("Windows guardian arguments are incomplete")
    working_directory, command_kind, *payload = arguments
    if command_kind == "argv":
        if not payload:
            raise ValueError("Windows guardian argv command is empty")
        return working_directory, tuple(payload)
    if command_kind == "shell":
        if len(payload) != 1:
            raise ValueError("Windows guardian shell command is invalid")
        command_processor = os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"
        return working_directory, (command_processor, "/d", "/s", "/c", payload[0])
    raise ValueError("Windows guardian command kind is invalid")


def _exception_error_number(exc: Exception) -> int:
    error_number = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    if error_number is None and exc.args and isinstance(exc.args[0], int):
        error_number = exc.args[0]
    return int(error_number or 1)


def _inheritable_standard_output() -> int:
    import msvcrt

    import win32api
    import win32con

    msvcrt_module: Any = msvcrt
    handle = int(msvcrt_module.get_osfhandle(sys.stdout.fileno()))
    win32api.SetHandleInformation(handle, win32con.HANDLE_FLAG_INHERIT, 1)
    return handle


def _watch_controller(job: Any, stop_event: threading.Event) -> None:
    import win32job

    while not stop_event.is_set():
        command = sys.stdin.buffer.read(1)
        if not command or command in {b"T", b"K"}:
            with suppress(OSError):
                win32job.TerminateJobObject(job, _TERMINATED_EXIT_CODE)
            return


def _exit_with_windows_code(code: int) -> None:
    kernel32 = _ctypes_windows.WinDLL("kernel32", use_last_error=True)
    kernel32.ExitProcess.argtypes = (ctypes.c_ulong,)
    kernel32.ExitProcess.restype = None
    kernel32.ExitProcess(code & 0xFFFF_FFFF)


if __name__ == "__main__":
    _exit_with_windows_code(main())
