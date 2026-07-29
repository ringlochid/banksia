from __future__ import annotations

from enum import StrEnum


class ProviderKind(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    OPENCLAW = "openclaw"


class ManagedSandboxMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


class ProviderNativeAccess(StrEnum):
    """Residual adapter projection; ManagedSandboxMode is authored authority."""

    FULL = "full"
    RESTRICTED = "restricted"
    DENIED = "denied"


class NetworkAccess(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class ManagedExtensionMode(StrEnum):
    """Requested or effective managed-provider Skill and MCP visibility."""

    INHERIT = "inherit"
    ISOLATED = "isolated"


__all__ = [
    "ManagedExtensionMode",
    "ManagedSandboxMode",
    "NetworkAccess",
    "ProviderKind",
    "ProviderNativeAccess",
]
