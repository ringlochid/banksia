from __future__ import annotations

import ipaddress
from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from autoclaw.config import (
    Settings,
    format_loopback_authority,
    normalize_loopback_origin,
)
from autoclaw.interfaces.http.errors import operation_failure
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode

_CORS_HEADERS = ("Content-Type", "Last-Event-ID")
_CORS_METHODS = ("DELETE", "GET", "PATCH", "POST", "PUT")
_LOOPBACK_HOST_ALIASES = ("127.0.0.1", "localhost", "::1")
_UNSAFE_HTTP_METHODS = frozenset({"DELETE", "PATCH", "POST", "PUT"})


class LocalHttpAdmission:
    """Reject requests outside the V2 loopback Host and Origin boundary."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_authorities: Sequence[str],
        allowed_origins: Sequence[str],
    ) -> None:
        self._app = app
        self._allowed_authorities = frozenset(allowed_authorities)
        self._allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if not _has_admitted_peer(scope):
            await _reject(
                summary="direct loopback access is required",
                suggested_next_step="Connect through the configured loopback listener.",
                status_code=403,
                scope=scope,
                receive=receive,
                send=send,
            )
            return

        headers = Headers(scope=scope)
        if not self._has_allowed_host(headers):
            await _reject(
                summary="Host must be an exact configured loopback authority",
                suggested_next_step="Use the configured loopback host and port.",
                status_code=400,
                scope=scope,
                receive=receive,
                send=send,
            )
            return
        if not self._has_allowed_origin(scope, headers):
            await _reject(
                summary="Origin is not allowed for this local request",
                suggested_next_step=(
                    "Use the API origin or an exact configured development console origin."
                ),
                status_code=400 if _is_cors_preflight(scope, headers) else 403,
                scope=scope,
                receive=receive,
                send=send,
            )
            return

        await self._app(scope, receive, send)

    def _has_allowed_host(self, headers: Headers) -> bool:
        host_headers = headers.getlist("host")
        if len(host_headers) != 1:
            return False
        try:
            authority = _normalize_loopback_authority(host_headers[0])
        except ValueError:
            return False
        return authority in self._allowed_authorities

    def _has_allowed_origin(self, scope: Scope, headers: Headers) -> bool:
        if not _requires_exact_origin(scope, headers):
            return True
        origin_headers = headers.getlist("origin")
        if not origin_headers:
            return True
        if len(origin_headers) != 1:
            return False
        try:
            origin = normalize_loopback_origin(origin_headers[0])
        except ValueError:
            return False
        return origin in self._allowed_origins


def add_local_control_plane_middleware(app: FastAPI, settings: Settings) -> None:
    """Install exact development CORS and outer local admission middleware."""
    allowed_authorities = _build_allowed_authorities(settings)
    allowed_origins = _build_allowed_origins(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.console_origins,
        allow_credentials=False,
        allow_methods=list(_CORS_METHODS),
        allow_headers=list(_CORS_HEADERS),
        allow_private_network=False,
    )
    app.add_middleware(
        LocalHttpAdmission,
        allowed_authorities=sorted(allowed_authorities),
        allowed_origins=sorted(allowed_origins),
    )


def _build_allowed_authorities(settings: Settings) -> frozenset[str]:
    hosts = {*_LOOPBACK_HOST_ALIASES, settings.api_host}
    return frozenset(format_loopback_authority(host, settings.api_port) for host in hosts)


def _build_allowed_origins(settings: Settings) -> frozenset[str]:
    api_origins = {
        f"http://{format_loopback_authority(host, settings.api_port)}"
        for host in (*_LOOPBACK_HOST_ALIASES, settings.api_host)
    }
    return frozenset((*api_origins, *settings.console_origins))


def _has_admitted_peer(scope: Scope) -> bool:
    client = scope.get("client")
    if client is None:
        return True
    if not isinstance(client, tuple) or not client or not isinstance(client[0], str):
        return False
    try:
        return ipaddress.ip_address(client[0]).is_loopback
    except ValueError:
        return False


def _requires_exact_origin(scope: Scope, headers: Headers) -> bool:
    method = str(scope.get("method", "")).upper()
    if method in _UNSAFE_HTTP_METHODS:
        return True
    return _is_cors_preflight(scope, headers)


def _is_cors_preflight(scope: Scope, headers: Headers) -> bool:
    if str(scope.get("method", "")).upper() != "OPTIONS":
        return False
    requested_method = headers.get("access-control-request-method", "").upper()
    return requested_method in _UNSAFE_HTTP_METHODS


def _normalize_loopback_authority(value: str) -> str:
    if value != value.strip() or "/" in value or "@" in value:
        raise ValueError("invalid authority")
    if value.startswith("["):
        close_bracket = value.find("]")
        if close_bracket < 0 or value[close_bracket + 1 : close_bracket + 2] != ":":
            raise ValueError("invalid IPv6 authority")
        host = value[1:close_bracket]
        raw_port = value[close_bracket + 2 :]
    else:
        host, separator, raw_port = value.rpartition(":")
        if separator == "" or ":" in host:
            raise ValueError("authority must contain an explicit port")
    if not raw_port.isascii() or not raw_port.isdecimal():
        raise ValueError("authority must contain a valid port")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("authority must contain a valid port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("authority must contain a valid port")
    return format_loopback_authority(host, port)


async def _reject(
    *,
    summary: str,
    suggested_next_step: str,
    status_code: int,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    failure = operation_failure(
        code=OperationFailureCode.LOCAL_ADMISSION_DENIED,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )
    await JSONResponse(
        status_code=status_code,
        content=failure.model_dump(mode="json"),
    )(scope, receive, send)


__all__ = ["LocalHttpAdmission", "add_local_control_plane_middleware"]
