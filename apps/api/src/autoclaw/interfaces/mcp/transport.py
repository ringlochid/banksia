from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings

from autoclaw.platform.file_entrypoints import load_yaml_mapping, resolved_input_path


@dataclass(frozen=True, slots=True)
class NodeMcpTransportPolicy:
    allowed_hosts: frozenset[str]
    allowed_origins: frozenset[str]

    def as_sdk_settings(self) -> TransportSecuritySettings:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=sorted(self.allowed_hosts),
            allowed_origins=sorted(self.allowed_origins),
        )


def local_mcp_transport_security(
    *,
    host: str,
    port: int,
    allowed_origins: Sequence[str] = (),
) -> TransportSecuritySettings:
    return node_mcp_transport_policy(
        host=host,
        port=port,
        allowed_origins=allowed_origins,
    ).as_sdk_settings()


def node_mcp_transport_policy(
    *,
    host: str,
    port: int,
    allowed_origins: Iterable[str] = (),
) -> NodeMcpTransportPolicy:
    _require_loopback_host(host)
    if not 1 <= port <= 65535:
        raise ValueError("Node MCP port must be between 1 and 65535")
    host_aliases = {"127.0.0.1", "localhost", "[::1]", _host_header_name(host)}
    host_values = {f"{host_alias}:{port}" for host_alias in host_aliases}
    api_origins = {f"http://{host_alias}:{port}" for host_alias in host_aliases}
    normalized_origins = {_require_loopback_origin(origin) for origin in allowed_origins}
    return NodeMcpTransportPolicy(
        allowed_hosts=frozenset(host_values),
        allowed_origins=frozenset((*api_origins, *normalized_origins)),
    )


def resolved_path(path_value: str) -> Path:
    return resolved_input_path(path_value)


def _require_loopback_host(host: str) -> None:
    normalized_host = host.removeprefix("[").removesuffix("]")
    if normalized_host.casefold() == "localhost":
        return
    try:
        parsed_host = ipaddress.ip_address(normalized_host)
    except ValueError as exc:
        raise ValueError("Node MCP host must be a loopback IP address or localhost") from exc
    if not parsed_host.is_loopback:
        raise ValueError("Node MCP host must be loopback-only")


def _host_header_name(host: str) -> str:
    normalized_host = host.removeprefix("[").removesuffix("]")
    try:
        parsed_host = ipaddress.ip_address(normalized_host)
    except ValueError:
        return normalized_host
    if parsed_host.version == 6:
        return f"[{parsed_host.compressed}]"
    return parsed_host.compressed


def _require_loopback_origin(origin: str) -> str:
    parsed_origin = urlsplit(origin)
    if parsed_origin.scheme not in {"http", "https"} or parsed_origin.hostname is None:
        raise ValueError(f"Node MCP origin '{origin}' must be an absolute HTTP origin")
    if parsed_origin.username is not None or parsed_origin.password is not None:
        raise ValueError(f"Node MCP origin '{origin}' must not contain user information")
    try:
        _parsed_port = parsed_origin.port
    except ValueError as exc:
        raise ValueError(f"Node MCP origin '{origin}' must contain a valid port") from exc
    if parsed_origin.path not in {"", "/"} or parsed_origin.query or parsed_origin.fragment:
        raise ValueError(f"Node MCP origin '{origin}' must not contain a path, query, or fragment")
    _require_loopback_host(parsed_origin.hostname)
    return origin.removesuffix("/")


__all__ = [
    "NodeMcpTransportPolicy",
    "load_yaml_mapping",
    "local_mcp_transport_security",
    "node_mcp_transport_policy",
    "resolved_path",
]
