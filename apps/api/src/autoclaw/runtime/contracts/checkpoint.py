import re
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from autoclaw.runtime.contracts.common import RuntimeSchemaText
from autoclaw.runtime.contracts.primitives import CheckpointKind, CheckpointOutcome
from autoclaw.runtime.contracts.refs import CheckpointFileRef

_CHECKPOINT_SUMMARY_MAX_LENGTH = 2_048
_CHECKPOINT_NEXT_STEP_MAX_LENGTH = 1_024
_CHECKPOINT_LIST_ENTRY_MAX_LENGTH = 1_024
_CHECKPOINT_LIST_MAX_LENGTH = 16
_VAGUE_TEXT_FINGERPRINTS = frozenset(("", "todo", "tbd"))
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_CHECKPOINT_SOURCE_ROOTS = frozenset(("workspace", "outputs", "tmp", "_runtime"))

_CheckpointSummaryText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=_CHECKPOINT_SUMMARY_MAX_LENGTH,
    ),
]
_CheckpointNextStepText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=_CHECKPOINT_NEXT_STEP_MAX_LENGTH,
    ),
]
_CheckpointListEntryText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=_CHECKPOINT_LIST_ENTRY_MAX_LENGTH,
    ),
]


class CheckpointHandoffRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: _CheckpointSummaryText
    next_step: _CheckpointNextStepText
    blockers: tuple[_CheckpointListEntryText, ...] = Field(
        default=(),
        max_length=_CHECKPOINT_LIST_MAX_LENGTH,
    )
    risks: tuple[_CheckpointListEntryText, ...] = Field(
        default=(),
        max_length=_CHECKPOINT_LIST_MAX_LENGTH,
    )

    @field_validator("summary", "next_step")
    @classmethod
    def reject_vague_scalar(cls, value: str) -> str:
        if _text_fingerprint(value) in _VAGUE_TEXT_FINGERPRINTS:
            raise ValueError("checkpoint handoff text must contain meaningful text")
        return value

    @field_validator("blockers", "risks")
    @classmethod
    def reject_vague_list_entries(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(_text_fingerprint(value) in _VAGUE_TEXT_FINGERPRINTS for value in values):
            raise ValueError("checkpoint handoff entries must contain meaningful text")
        return values


class ProducedArtifactClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["artifact"] = "artifact"
    slot: RuntimeSchemaText
    path: RuntimeSchemaText

    @field_validator("path")
    @classmethod
    def normalize_source_path(cls, value: str) -> str:
        return _normalize_source_path(value)


class TransientSurfaceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: RuntimeSchemaText
    description: RuntimeSchemaText

    @field_validator("path")
    @classmethod
    def normalize_source_path(cls, value: str) -> str:
        return _normalize_source_path(value)


class CheckpointWriteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint_kind: CheckpointKind
    outcome: CheckpointOutcome | None = None
    handoff: CheckpointHandoffRead
    produced_artifacts: tuple[ProducedArtifactClaim, ...] = ()
    transient_surfaces: tuple[TransientSurfaceWrite, ...] = ()

    @model_validator(mode="after")
    def validate_checkpoint_kind(self) -> Self:
        if self.checkpoint_kind == CheckpointKind.PROGRESS and self.outcome is not None:
            raise ValueError("progress checkpoints must not declare a terminal outcome")
        if self.checkpoint_kind == CheckpointKind.TERMINAL and self.outcome is None:
            raise ValueError("terminal checkpoints require an outcome")
        artifact_slots = [artifact.slot for artifact in self.produced_artifacts]
        if len(artifact_slots) != len(set(artifact_slots)):
            raise ValueError("produced_artifacts must not repeat the same slot in one checkpoint")
        return self


class CheckpointWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint: CheckpointWriteBody


class CheckpointRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: RuntimeSchemaText
    checkpoint_id: RuntimeSchemaText
    checkpoint_ref: CheckpointFileRef
    latest_checkpoint_ref: CheckpointFileRef


def _text_fingerprint(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _normalize_source_path(value: str) -> str:
    if "\x00" in value or "\\" in value:
        raise ValueError("checkpoint source path contains a forbidden character")
    if value.startswith(("/", "//")) or _WINDOWS_DRIVE.match(value):
        raise ValueError("checkpoint source path must be task-relative")
    parts = tuple(part for part in value.split("/") if part not in ("", "."))
    if not parts or ".." in parts:
        raise ValueError("checkpoint source path must not be empty or traverse upward")
    if parts[0] not in _CHECKPOINT_SOURCE_ROOTS:
        raise ValueError("checkpoint source path must use a logical task root")
    return "/".join(parts)


__all__ = [
    "CheckpointHandoffRead",
    "CheckpointRead",
    "CheckpointWrite",
    "CheckpointWriteBody",
    "ProducedArtifactClaim",
    "TransientSurfaceWrite",
]
