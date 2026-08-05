from __future__ import annotations

import ipaddress
import os
import re
import stat
import tomllib
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from banksia.paths import default_config_path, default_data_dir, default_database_url
from banksia.platform.environment import Environment
from banksia.platform.workspace_files import read_private_text
from banksia.providers import (
    ManagedExtensionMode,
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
)

CONFIG_ENV_VAR = "BANKSIA_CONFIG"
CONTROLLER_WORKSPACE_ENV_VAR = "BANKSIA_CONTROLLER_WORKSPACE"
SUPPORT_BEARER_TOKEN_ENV_VAR = "BANKSIA_SUPPORT_BEARER_TOKEN"
DEFAULT_LOG_LEVEL = "WARNING"
DEFAULT_API_PORT = 18125
ConfigText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OperatorConfigText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
ProviderConfigText = Annotated[str, StringConstraints(strip_whitespace=True)]
_POSTGRES_SCHEMA_PATTERN = re.compile(r"[a-z_][a-z0-9_$]{0,62}\Z")
_CONTROLLER_WORKSPACE_REQUIREMENT = (
    "controller workspace must be a non-blank absolute path to an existing directory"
)


class CodexSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    model: ProviderConfigText | None = None
    effort: ProviderConfigText | None = None
    extension_mode: ManagedExtensionMode = ManagedExtensionMode.INHERIT


class ClaudeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    model: ProviderConfigText | None = None
    effort: ProviderConfigText | None = None
    extension_mode: ManagedExtensionMode = ManagedExtensionMode.INHERIT


class OperatorProvider(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


class OperatorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: OperatorProvider | None = None
    model: OperatorConfigText | None = None
    effort: OperatorConfigText | None = None

    @model_validator(mode="after")
    def validate_provider_overrides(self) -> OperatorSettings:
        if self.provider is None and (self.model is not None or self.effort is not None):
            raise ValueError("Operator model and effort require an Operator provider")
        return self


class OpenClawGatewayAuthMode(StrEnum):
    TOKEN = "token"
    PASSWORD = "password"


class OpenClawSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    cli_path: ProviderConfigText = "openclaw"
    gateway_url: ProviderConfigText = "ws://127.0.0.1:18789"
    gateway_profile: ProviderConfigText = "default"
    gateway_auth_mode: OpenClawGatewayAuthMode = OpenClawGatewayAuthMode.TOKEN


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default_provider: ProviderKind | None = None
    max_child_assignments_per_assignment: int = Field(default=20, ge=0)
    max_retries_per_assignment: int = Field(default=1, ge=0)
    max_wave_members: int = Field(default=8, ge=1)
    managed_provider_sandbox_mode: ManagedSandboxMode = ManagedSandboxMode.FULL_ACCESS
    managed_provider_network_access: NetworkAccess = NetworkAccess.ALLOW
    dispatch_launch_retry_initial_backoff_seconds: float = Field(default=1.0, ge=0.0)
    dispatch_launch_retry_max_backoff_seconds: float = Field(default=30.0, ge=0.0)
    watchdog_inactivity_timeout_seconds: int = Field(default=2700, ge=1)
    watchdog_same_attempt_replacement_limit: int = Field(default=2, ge=0)

    @model_validator(mode="after")
    def validate_managed_provider_sandbox_pair(self) -> RuntimeSettings:
        if (
            self.managed_provider_sandbox_mode is ManagedSandboxMode.READ_ONLY
            and self.managed_provider_network_access is not NetworkAccess.DENY
        ) or (
            self.managed_provider_sandbox_mode is ManagedSandboxMode.FULL_ACCESS
            and self.managed_provider_network_access is not NetworkAccess.ALLOW
        ):
            raise ValueError(
                "managed provider sandbox mode and network access are not a legal pair"
            )
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BANKSIA_",
        env_nested_delimiter="__",
        extra="ignore",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    env: Environment = Environment.DEVELOPMENT
    is_debug_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("debug", "is_debug_enabled"),
        serialization_alias="debug",
    )
    database_url: str = Field(default_factory=default_database_url)
    postgres_schema: ConfigText = "banksia"
    should_echo_database: bool = Field(
        default=False,
        validation_alias=AliasChoices("database_echo", "should_echo_database"),
        serialization_alias="database_echo",
    )
    console_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        ]
    )
    api_host: ConfigText = "127.0.0.1"
    api_port: int = Field(default=DEFAULT_API_PORT, ge=1, le=65535)
    log_level: str = DEFAULT_LOG_LEVEL
    config_path: Path = Field(default_factory=default_config_path)
    data_dir: Path = Field(default_factory=default_data_dir)
    controller_workspace: Path | None = None
    support_bearer_token: SecretStr | None = Field(
        default=None,
        min_length=32,
        exclude=True,
        repr=False,
    )
    codex: CodexSettings = Field(default_factory=CodexSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    openclaw: OpenClawSettings = Field(default_factory=OpenClawSettings)
    operator: OperatorSettings = Field(default_factory=OperatorSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)

    @field_validator("postgres_schema")
    @classmethod
    def validate_postgres_schema(cls, value: str) -> str:
        if _POSTGRES_SCHEMA_PATTERN.fullmatch(value) is None:
            raise ValueError(
                "postgres_schema must be a lowercase unquoted PostgreSQL identifier "
                "of at most 63 ASCII characters"
            )
        if value == "public" or value == "information_schema" or value.startswith("pg_"):
            raise ValueError("postgres_schema must name a dedicated non-system schema")
        return value

    @field_validator("api_host")
    @classmethod
    def validate_api_host(cls, value: str) -> str:
        return normalize_loopback_host(value)

    @field_validator("console_origins")
    @classmethod
    def validate_console_origins(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(normalize_loopback_origin(value) for value in values))

    @field_validator("controller_workspace", mode="before")
    @classmethod
    def validate_controller_workspace(cls, value: Any) -> Path | None:
        if value is None:
            return None
        return normalize_controller_workspace(value)

    @property
    def debug(self) -> bool:
        return self.is_debug_enabled

    @property
    def database_echo(self) -> bool:
        return self.should_echo_database

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del dotenv_settings
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


class TomlConfigSettingsSource(PydanticBaseSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        data = self()
        return data.get(field_name), field_name, False

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: Any,
        value_is_complex: bool,
    ) -> Any:
        del value_is_complex
        return value

    def __call__(self) -> dict[str, Any]:
        return _load_toml_settings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def load_settings() -> Settings:
    settings = Settings()
    debug_override = _environment_boolean_override("BANKSIA_DEBUG")
    if debug_override is not None:
        settings.is_debug_enabled = debug_override
    database_echo_override = _environment_boolean_override("BANKSIA_DATABASE_ECHO")
    if database_echo_override is not None:
        settings.should_echo_database = database_echo_override
    settings.config_path = _coerce_path(settings.config_path)
    settings.data_dir = _coerce_path(settings.data_dir)
    if "database_url" not in settings.model_fields_set:
        settings.database_url = default_database_url(settings.data_dir)
    return settings


def format_loopback_authority(host: str, port: int) -> str:
    """Render a validated loopback host and port as an HTTP authority."""
    normalized_host = normalize_loopback_host(host)
    rendered_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    return f"{rendered_host}:{port}"


def normalize_loopback_origin(value: str) -> str:
    """Return one canonical absolute loopback HTTP origin or reject it."""
    normalized_value = value.strip()
    parsed_origin = urlsplit(normalized_value)
    if parsed_origin.scheme.casefold() not in {"http", "https"}:
        raise ValueError("console origins must use HTTP or HTTPS")
    if parsed_origin.hostname is None:
        raise ValueError("console origins must be absolute")
    if parsed_origin.username is not None or parsed_origin.password is not None:
        raise ValueError("console origins must not contain user information")
    if parsed_origin.path not in {"", "/"} or parsed_origin.query or parsed_origin.fragment:
        raise ValueError("console origins must not contain a path, query, or fragment")
    try:
        port = parsed_origin.port
    except ValueError as exc:
        raise ValueError("console origins must contain a valid port") from exc

    host = normalize_loopback_host(parsed_origin.hostname)
    rendered_host = f"[{host}]" if ":" in host else host
    netloc = rendered_host if port is None else f"{rendered_host}:{port}"
    return urlunsplit((parsed_origin.scheme.casefold(), netloc, "", "", ""))


def normalize_loopback_host(value: str) -> str:
    """Return one canonical loopback listener host or reject it."""
    normalized_host = value.strip()
    has_opening_bracket = normalized_host.startswith("[")
    has_closing_bracket = normalized_host.endswith("]")
    if has_opening_bracket != has_closing_bracket:
        raise ValueError("api_host has mismatched IPv6 brackets")
    if has_opening_bracket:
        normalized_host = normalized_host[1:-1]
    elif "[" in normalized_host or "]" in normalized_host:
        raise ValueError("api_host has invalid IPv6 brackets")
    if "%" in normalized_host:
        raise ValueError("api_host must not contain an IPv6 scope identifier")
    if normalized_host.casefold() == "localhost":
        return "localhost"
    try:
        parsed_host = ipaddress.ip_address(normalized_host)
    except ValueError as exc:
        raise ValueError("api_host must be a loopback IP address or localhost") from exc
    if not parsed_host.is_loopback:
        raise ValueError("api_host must be loopback-only")
    return parsed_host.compressed


def normalize_controller_workspace(
    value: str | os.PathLike[str] | Path,
) -> Path:
    """Return one existing absolute controller workspace directory."""

    try:
        raw_workspace = os.fspath(value)
        if not isinstance(raw_workspace, str) or not raw_workspace.strip():
            raise ValueError(_CONTROLLER_WORKSPACE_REQUIREMENT)
        expanded_workspace = Path(raw_workspace).expanduser()
        if not expanded_workspace.is_absolute():
            raise ValueError(_CONTROLLER_WORKSPACE_REQUIREMENT)
        workspace = _coerce_path(expanded_workspace)
        metadata = workspace.stat(follow_symlinks=False)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError(f"{_CONTROLLER_WORKSPACE_REQUIREMENT}: {value!s}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{_CONTROLLER_WORKSPACE_REQUIREMENT}: {workspace}")
    return workspace


def _coerce_path(value: str | os.PathLike[str] | Path) -> Path:
    return Path(os.path.abspath(Path(value).expanduser()))


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _environment_boolean_override(name: str) -> bool | None:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return None

    normalized_value = raw_value.strip().casefold()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a recognizable boolean value")


def _load_toml_settings() -> dict[str, Any]:
    config_path = _coerce_path(os.environ.get(CONFIG_ENV_VAR, default_config_path()))
    config_text = read_private_text(config_path)
    if config_text is None:
        return {"config_path": config_path, "data_dir": default_data_dir()}

    payload = tomllib.loads(config_text)
    loaded: dict[str, Any] = {
        "config_path": config_path,
        "data_dir": _coerce_path(_nested_get(payload, "paths", "data_dir") or default_data_dir()),
    }

    field_mapping = {
        "database_url": ("database", "url"),
        "postgres_schema": ("database", "postgres_schema"),
        "database_echo": ("database", "echo"),
        "console_origins": ("server", "console_origins"),
        "api_host": ("server", "host"),
        "api_port": ("server", "port"),
        "log_level": ("logging", "level"),
        "controller_workspace": ("paths", "workspace"),
    }
    for field_name, key_path in field_mapping.items():
        value = _nested_get(payload, *key_path)
        if value is not None:
            loaded[field_name] = value
    for provider in ("codex", "claude", "openclaw"):
        if provider in payload:
            loaded[provider] = payload[provider]
    if "operator" in payload:
        loaded["operator"] = payload["operator"]
    if "runtime" in payload:
        loaded["runtime"] = payload["runtime"]
    return loaded


__all__ = [
    "CONFIG_ENV_VAR",
    "CONTROLLER_WORKSPACE_ENV_VAR",
    "DEFAULT_API_PORT",
    "DEFAULT_LOG_LEVEL",
    "SUPPORT_BEARER_TOKEN_ENV_VAR",
    "ClaudeSettings",
    "CodexSettings",
    "Environment",
    "OpenClawGatewayAuthMode",
    "OpenClawSettings",
    "OperatorProvider",
    "OperatorSettings",
    "RuntimeSettings",
    "Settings",
    "TomlConfigSettingsSource",
    "format_loopback_authority",
    "get_settings",
    "load_settings",
    "normalize_controller_workspace",
    "normalize_loopback_host",
    "normalize_loopback_origin",
]
