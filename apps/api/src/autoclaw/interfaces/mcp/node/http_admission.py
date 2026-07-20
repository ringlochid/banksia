from __future__ import annotations

import ipaddress
from contextvars import ContextVar

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from autoclaw.runtime.node_mcp import DispatchMcpBinding, DispatchMcpBindingRegistry

_CURRENT_MANAGED_BINDING: ContextVar[DispatchMcpBinding | None] = ContextVar(
    "autoclaw_current_managed_node_mcp_binding",
    default=None,
)


class ManagedNodeMcpHttpAdmission:
    """Authenticate dispatch scope before managed MCP request handling."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        binding_registry: DispatchMcpBindingRegistry,
    ) -> None:
        self._app = app
        self._binding_registry = binding_registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if not _has_loopback_peer(scope):
            await PlainTextResponse(
                "Direct loopback access required",
                status_code=403,
            )(scope, receive, send)
            return

        binding = self._authenticate_managed_request(scope)
        if isinstance(binding, Response):
            await binding(scope, receive, send)
            return

        binding_token = _CURRENT_MANAGED_BINDING.set(binding)
        try:
            await self._app(scope, receive, send)
        finally:
            _CURRENT_MANAGED_BINDING.reset(binding_token)

    def _authenticate_managed_request(self, scope: Scope) -> DispatchMcpBinding | Response:
        authorization = Headers(scope=scope).get("authorization")
        credential = _bearer_credential(authorization)
        binding = self._binding_registry.authenticate(credential) if credential else None
        if binding is None:
            return PlainTextResponse(
                "Managed Node MCP authentication failed",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return binding


def current_managed_binding() -> DispatchMcpBinding:
    binding = _CURRENT_MANAGED_BINDING.get()
    if binding is None:
        raise RuntimeError("managed Node MCP binding is unavailable outside an admitted request")
    return binding


def _has_loopback_peer(scope: Scope) -> bool:
    client = scope.get("client")
    if not isinstance(client, tuple) or not client:
        return False
    client_host = client[0]
    if not isinstance(client_host, str):
        return False
    try:
        return ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        return False


def _bearer_credential(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, credential = authorization.partition(" ")
    if separator != " " or scheme.casefold() != "bearer":
        return None
    if (
        not credential
        or credential != credential.strip()
        or any(character.isspace() for character in credential)
    ):
        return None
    return credential


__all__ = ["ManagedNodeMcpHttpAdmission", "current_managed_binding"]
