from __future__ import annotations

import argparse
import socket
from pathlib import Path
from typing import Any

from autoclaw.interfaces.cli.commands.bootstrap import update_config_sections
from autoclaw.interfaces.cli.support import print_json
from autoclaw.interfaces.cli.terminal.theme import accent, heading, muted, rich_enabled, warn


def update_server_config_overrides(
    config_path: Path,
    *,
    host: str | None = None,
    port: int | None = None,
) -> None:
    section_updates: dict[str, dict[str, Any]] = {}
    if host is not None or port is not None:
        section_updates["server"] = {}
        if host is not None:
            section_updates["server"]["host"] = host
        if port is not None:
            section_updates["server"]["port"] = port
    if section_updates:
        update_config_sections(config_path, section_updates=section_updates)


def build_server_bind_check_payload(host: str, port: int) -> dict[str, Any]:
    try:
        candidates = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "reason": str(exc),
        }

    errors: list[str] = []
    for family, socktype, proto, _canonname, sockaddr in candidates:
        test_socket = socket.socket(family, socktype, proto)
        try:
            test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
                test_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            test_socket.bind(sockaddr)
            return {
                "ok": True,
                "host": host,
                "port": port,
                "address": sockaddr[0],
            }
        except OSError as exc:
            errors.append(str(exc))
        finally:
            test_socket.close()

    return {
        "ok": False,
        "host": host,
        "port": port,
        "reason": errors[-1] if errors else "bind failed",
    }


def emit_server_bind_check_failure(
    *,
    command_name: str,
    args: argparse.Namespace,
    server_payload: dict[str, Any],
    stopped_before: str,
    payload_extra: dict[str, Any] | None = None,
) -> int:
    payload = {"ok": False, **(payload_extra or {}), "server": server_payload}
    if getattr(args, "json", False):
        print_json(payload)
    else:
        is_rich = rich_enabled(args)
        server_target = f"{server_payload['host']}:{server_payload['port']}"
        print(heading(command_name, is_rich=is_rich))
        print(warn("Local API bind check failed", is_rich=is_rich))
        if server_payload.get("reason"):
            print(f"reason: {warn(str(server_payload['reason']), is_rich=is_rich)}")
        print(muted(stopped_before, is_rich=is_rich))
        print(f"service port: {accent(server_target, is_rich=is_rich)}")
    return 1


__all__ = [
    "build_server_bind_check_payload",
    "emit_server_bind_check_failure",
    "update_server_config_overrides",
]
