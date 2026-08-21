from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue, SkipJsonSchema
from pydantic_core import CoreSchema

_MAX_DIRECT_CHILDREN = 32
_MAX_MANAGED_PROVIDER_VALUE_LENGTH = 255

Identifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$",
    ),
]


BoundedProviderValue = Annotated[
    str,
    Field(min_length=1, pattern=r"\S"),
]
CodexEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]
ManagedExtensionModeValue = Literal["inherit", "isolated"]


class _WorkflowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderSandbox(_WorkflowModel):
    mode: Literal["read_only", "workspace_write", "full_access"]
    network: Literal["allow", "deny"]

    @model_validator(mode="after")
    def validate_portable_pair(self) -> ProviderSandbox:
        if (self.mode == "read_only" and self.network != "deny") or (
            self.mode == "full_access" and self.network != "allow"
        ):
            raise ValueError("sandbox mode and network combination is not supported")
        return self

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        handler(core_schema)
        return {
            "title": "ProviderSandbox",
            "oneOf": [
                _closed_object_schema(mode="read_only", networks=("deny",)),
                _closed_object_schema(
                    mode="workspace_write",
                    networks=("allow", "deny"),
                ),
                _closed_object_schema(mode="full_access", networks=("allow",)),
            ],
        }


class CodexProviderSelection(_WorkflowModel):
    kind: Literal["codex"]
    model: BoundedProviderValue | SkipJsonSchema[None] = None
    effort: CodexEffort | SkipJsonSchema[None] = None
    sandbox: ProviderSandbox | SkipJsonSchema[None] = None
    extension_mode: ManagedExtensionModeValue | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value: Any) -> Any:
        return _reject_explicit_nulls(
            value,
            fields=("model", "effort", "sandbox", "extension_mode"),
        )

    @field_validator("model")
    @classmethod
    def enforce_hidden_model_length(cls, value: str | None) -> str | None:
        return _validate_hidden_provider_value(value)

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return _without_null_defaults(
            handler(core_schema),
            fields=("model", "effort", "sandbox", "extension_mode"),
        )


class ClaudeProviderSelection(_WorkflowModel):
    kind: Literal["claude"]
    model: BoundedProviderValue | SkipJsonSchema[None] = None
    effort: ClaudeEffort | SkipJsonSchema[None] = None
    sandbox: ProviderSandbox | SkipJsonSchema[None] = None
    extension_mode: ManagedExtensionModeValue | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value: Any) -> Any:
        return _reject_explicit_nulls(
            value,
            fields=("model", "effort", "sandbox", "extension_mode"),
        )

    @field_validator("model")
    @classmethod
    def enforce_hidden_model_length(cls, value: str | None) -> str | None:
        return _validate_hidden_provider_value(value)

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return _without_null_defaults(
            handler(core_schema),
            fields=("model", "effort", "sandbox", "extension_mode"),
        )


class RetiredOpenClawProviderSelection(_WorkflowModel):
    """Readback-only provider selection retained for historical Workflows."""

    kind: Literal["openclaw"]


ProviderSelection = Annotated[
    CodexProviderSelection | ClaudeProviderSelection,
    Field(discriminator="kind"),
]

StoredProviderSelection = Annotated[
    CodexProviderSelection | ClaudeProviderSelection | RetiredOpenClawProviderSelection,
    Field(discriminator="kind"),
]


class MemberCapabilities(_WorkflowModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={"minProperties": 1},
    )

    human_request: (
        Annotated[
            tuple[Literal["input", "direction", "approval", "review"], ...],
            Field(
                min_length=1,
                max_length=4,
                json_schema_extra={"uniqueItems": True},
            ),
        ]
        | SkipJsonSchema[None]
    ) = None
    command_run: Literal["allow"] | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value: Any) -> Any:
        return _reject_explicit_nulls(value, fields=("human_request", "command_run"))

    @model_validator(mode="after")
    def require_one_capability(self) -> MemberCapabilities:
        if self.human_request is None and self.command_run is None:
            raise ValueError("capabilities must grant at least one operation")
        return self

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return _without_null_defaults(
            handler(core_schema),
            fields=("human_request", "command_run"),
        )


class NormalizedMember(_WorkflowModel):
    id: Identifier
    title: Annotated[str, Field(max_length=16384)] | None = None
    description: Annotated[str, Field(max_length=16384)] | None = None
    instruction: Annotated[str, Field(max_length=16384)] | None = None
    provider: StoredProviderSelection | SkipJsonSchema[None] = None
    capabilities: MemberCapabilities | SkipJsonSchema[None] = None
    children: tuple[NormalizedMember, ...] | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_structural_nulls(cls, value: Any) -> Any:
        return _reject_explicit_nulls(
            value,
            fields=("provider", "capabilities", "children"),
        )

    @field_validator("children")
    @classmethod
    def enforce_hidden_direct_child_limit(
        cls,
        value: tuple[NormalizedMember, ...] | None,
    ) -> tuple[NormalizedMember, ...] | None:
        if value is not None and len(value) > _MAX_DIRECT_CHILDREN:
            raise ValueError("Member exceeds the controller direct-child limit")
        return value

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return _without_null_defaults(
            handler(core_schema),
            fields=("provider", "capabilities", "children"),
        )


class NormalizedWorkflow(_WorkflowModel):
    kind: Literal["workflow"]
    id: Identifier
    description: Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")]
    note: Annotated[str, Field(max_length=8192)] | None = None
    lead: NormalizedMember


class AuthoredMember(_WorkflowModel):
    """Normalized authored Member whose provider must be active."""

    id: Identifier
    title: Annotated[str, Field(max_length=16384)] | None = None
    description: Annotated[str, Field(max_length=16384)] | None = None
    instruction: Annotated[str, Field(max_length=16384)] | None = None
    provider: ProviderSelection | SkipJsonSchema[None] = None
    capabilities: MemberCapabilities | SkipJsonSchema[None] = None
    children: tuple[AuthoredMember, ...] | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_structural_nulls(cls, value: Any) -> Any:
        return _reject_explicit_nulls(
            value,
            fields=("provider", "capabilities", "children"),
        )

    @field_validator("children")
    @classmethod
    def enforce_hidden_direct_child_limit(
        cls,
        value: tuple[AuthoredMember, ...] | None,
    ) -> tuple[AuthoredMember, ...] | None:
        if value is not None and len(value) > _MAX_DIRECT_CHILDREN:
            raise ValueError("Member exceeds the controller direct-child limit")
        return value

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return _without_null_defaults(
            handler(core_schema),
            fields=("provider", "capabilities", "children"),
        )


class AuthoredWorkflow(_WorkflowModel):
    """Normalized Workflow accepted at a complete authoring boundary."""

    kind: Literal["workflow"]
    id: Identifier
    description: Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")]
    note: Annotated[str, Field(max_length=8192)] | None = None
    lead: AuthoredMember


class WorkflowProvenance(StrEnum):
    STARTER_SEED = "starter_seed"
    USER = "user"


class PublishedWorkflowRevision(_WorkflowModel):
    workflow_id: Identifier
    revision_no: Annotated[int, Field(ge=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    workflow: NormalizedWorkflow


class WorkflowSummary(_WorkflowModel):
    workflow_id: Identifier
    description: str
    updated_at: datetime
    provenance: WorkflowProvenance
    published_revision_no: Annotated[int, Field(ge=1)] | None = None
    has_active_draft: bool
    has_retired_provider_selection: bool = False


class WorkflowRevisionSummary(_WorkflowModel):
    workflow_id: Identifier
    revision_no: Annotated[int, Field(ge=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    provenance: WorkflowProvenance


def _validate_hidden_provider_value(value: str | None) -> str | None:
    if value is not None and len(value) > _MAX_MANAGED_PROVIDER_VALUE_LENGTH:
        raise ValueError("value exceeds the controller text limit")
    return value


def _reject_explicit_nulls(value: Any, *, fields: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        for field_name in fields:
            if field_name in value and value[field_name] is None:
                raise ValueError(f"{field_name} cannot be null")
    return value


def _without_null_defaults(
    schema: JsonSchemaValue,
    *,
    fields: tuple[str, ...],
) -> JsonSchemaValue:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return schema
    for field_name in fields:
        field_schema = properties.get(field_name)
        if isinstance(field_schema, dict) and field_schema.get("default") is None:
            field_schema.pop("default", None)
    return schema


def _closed_object_schema(
    *,
    mode: str,
    networks: tuple[str, ...],
) -> JsonSchemaValue:
    network_schema: JsonSchemaValue = (
        {"const": networks[0], "type": "string"}
        if len(networks) == 1
        else {"enum": list(networks), "type": "string"}
    )
    return {
        "additionalProperties": False,
        "properties": {
            "mode": {"const": mode, "type": "string"},
            "network": network_schema,
        },
        "required": ["mode", "network"],
        "type": "object",
    }


__all__ = [
    "AuthoredMember",
    "AuthoredWorkflow",
    "ClaudeProviderSelection",
    "CodexProviderSelection",
    "Identifier",
    "MemberCapabilities",
    "NormalizedMember",
    "NormalizedWorkflow",
    "ProviderSandbox",
    "ProviderSelection",
    "PublishedWorkflowRevision",
    "RetiredOpenClawProviderSelection",
    "StoredProviderSelection",
    "WorkflowProvenance",
    "WorkflowRevisionSummary",
    "WorkflowSummary",
]
