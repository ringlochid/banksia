from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from enum import StrEnum
from pathlib import Path
from typing import Protocol, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictStr,
    field_validator,
    model_validator,
)

from banksia.providers import (
    ManagedExtensionMode,
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
    ProviderNativeAccess,
)
from banksia.runtime.contracts.provider_resolution import ProviderRoute

MANAGED_NODE_MCP_SERVER_NAME = "banksia_node"
DEFAULT_PROVIDER_STOP_TIMEOUT_SECONDS = 5.0


class ManagedNodeMcpConnection(BaseModel):
    """Private invocation-scoped connection to the managed Node MCP projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    bearer_token: SecretStr = Field(repr=False)
    enabled_tools: tuple[str, ...]

    @field_validator("url")
    @classmethod
    def validate_loopback_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
            raise ValueError("managed Node MCP URL must use loopback HTTP")
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError("managed Node MCP URL must not contain credentials or a fragment")
        return value

    @field_validator("enabled_tools")
    @classmethod
    def validate_enabled_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("managed Node MCP requires at least one enabled tool")
        if any(not tool or tool.strip() != tool for tool in value):
            raise ValueError("managed Node MCP tool names must be non-blank and trimmed")
        if len(set(value)) != len(value):
            raise ValueError("managed Node MCP tool names must be unique")
        return value

    @property
    def authorization_header(self) -> str:
        return f"Bearer {self.bearer_token.get_secret_value()}"


class CompatibilityNodeMcpConnection(BaseModel):
    """User-managed compatibility connection selected for an OpenClaw dispatch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("compatibility Node MCP URL must be absolute HTTP(S)")
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError(
                "compatibility Node MCP URL must not contain credentials or a fragment"
            )
        return value


class DispatchStartRequest(BaseModel):
    """Exact committed request and policy supplied to one provider start attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    dispatch_id: str
    provider_start_revision: int = Field(ge=0)
    working_directory: Path
    instructions: StrictStr
    input: StrictStr
    provider_route: ProviderRoute
    provider_native_access: ProviderNativeAccess
    network_access: NetworkAccess
    sandbox_mode: ManagedSandboxMode | None = None
    extension_mode: ManagedExtensionMode | None = None
    managed_node_mcp: ManagedNodeMcpConnection | None = None
    compatibility_node_mcp: CompatibilityNodeMcpConnection | None = None

    @model_validator(mode="after")
    def validate_connection_projection(self) -> Self:
        if self.provider_route.kind in {ProviderKind.CODEX, ProviderKind.CLAUDE}:
            if self.managed_node_mcp is None or self.compatibility_node_mcp is not None:
                raise ValueError("managed providers require only a managed Node MCP connection")
            if self.sandbox_mode is None:
                raise ValueError("managed providers require an exact sandbox mode")
            if self.extension_mode is None:
                raise ValueError("managed providers require an exact extension mode")
        elif self.managed_node_mcp is not None or self.compatibility_node_mcp is None:
            raise ValueError("OpenClaw requires only a compatibility Node MCP connection")
        elif self.sandbox_mode is not None:
            raise ValueError("OpenClaw does not carry a controller-managed sandbox mode")
        elif self.extension_mode is not None:
            raise ValueError("OpenClaw does not carry a managed extension mode")
        return self


class ProviderMcpServerInventory(BaseModel):
    """Sanitized observed provider-home MCP surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: StrictStr = Field(min_length=1, max_length=255, pattern=r"\S")
    tools: tuple[StrictStr, ...] = ()

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("MCP inventory server names must be trimmed")
        return value

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or item.strip() != item or len(item) > 255 for item in value):
            raise ValueError("MCP inventory tool names must be trimmed and bounded")
        if tuple(sorted(set(value))) != value:
            raise ValueError("MCP inventory tool names must be unique and sorted")
        return value


class ProviderExtensionInventory(BaseModel):
    """Sanitized observed Skill and MCP names without content, paths, or secrets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    skills: tuple[StrictStr, ...] = ()
    mcp_servers: tuple[ProviderMcpServerInventory, ...] = ()

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or item.strip() != item or len(item) > 255 for item in value):
            raise ValueError("Skill inventory names must be trimmed and bounded")
        if tuple(sorted(set(value))) != value:
            raise ValueError("Skill inventory names must be unique and sorted")
        return value

    @field_validator("mcp_servers")
    @classmethod
    def validate_mcp_servers(
        cls,
        value: tuple[ProviderMcpServerInventory, ...],
    ) -> tuple[ProviderMcpServerInventory, ...]:
        names = tuple(server.name for server in value)
        if tuple(sorted(set(names))) != names:
            raise ValueError("MCP inventory servers must be unique and sorted")
        return value


class ProviderStartAccepted(BaseModel):
    """Positive provider submission acceptance plus sanitized startup observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    extension_inventory: ProviderExtensionInventory | None = None


class ProviderStartFailureKind(StrEnum):
    DEFINITE_FAILURE = "definite_failure"
    UNCERTAIN_ACCEPTANCE = "uncertain_acceptance"


class ProviderStartErrorCode(StrEnum):
    CONFIGURATION = "provider_configuration"
    AUTHENTICATION = "provider_authentication"
    CONNECTION = "provider_connection"
    UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "provider_timeout"
    REJECTED = "provider_rejected"
    UNSUPPORTED = "provider_unsupported"
    UNCERTAIN = "provider_uncertain"


class ProviderStartError(RuntimeError):
    """Sanitized provider start failure suitable for same-dispatch retry routing."""

    def __init__(
        self,
        *,
        kind: ProviderStartFailureKind,
        code: ProviderStartErrorCode,
    ) -> None:
        super().__init__(code.value)
        self.kind = kind
        self.code = code


class ProviderStopOutcome(StrEnum):
    STOPPED = "stopped"
    NOT_RUNNING = "not_running"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class ProviderCheckStatus(StrEnum):
    AVAILABLE = "available"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"


class ProviderCheckAxisStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    PASSED = "passed"
    FAILED = "failed"


class ProviderAuthenticationMethod(StrEnum):
    SUBSCRIPTION = "subscription"
    API_KEY = "api_key"
    TOKEN = "token"
    PASSWORD = "password"


class ProviderCheckResult(BaseModel):
    """Bounded non-secret result for an explicit non-agent provider check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ProviderKind
    status: ProviderCheckStatus
    code: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9_]+$")
    authentication: ProviderCheckAxisStatus = ProviderCheckAxisStatus.NOT_CHECKED
    authentication_method: ProviderAuthenticationMethod | None = None
    reachability: ProviderCheckAxisStatus = ProviderCheckAxisStatus.NOT_CHECKED


class ProviderAdapter(Protocol):
    kind: ProviderKind

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted: ...

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome: ...

    async def read_availability(self) -> ProviderCheckResult: ...

    def lifespan(self) -> AbstractAsyncContextManager[None]: ...


__all__ = [
    "DEFAULT_PROVIDER_STOP_TIMEOUT_SECONDS",
    "MANAGED_NODE_MCP_SERVER_NAME",
    "CompatibilityNodeMcpConnection",
    "DispatchStartRequest",
    "ManagedNodeMcpConnection",
    "ProviderAdapter",
    "ProviderAuthenticationMethod",
    "ProviderCheckAxisStatus",
    "ProviderCheckResult",
    "ProviderCheckStatus",
    "ProviderExtensionInventory",
    "ProviderMcpServerInventory",
    "ProviderStartAccepted",
    "ProviderStartError",
    "ProviderStartErrorCode",
    "ProviderStartFailureKind",
    "ProviderStopOutcome",
]
