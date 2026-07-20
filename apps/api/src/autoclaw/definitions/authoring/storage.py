from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, unquote

import yaml
from pydantic import BaseModel, ConfigDict, Field

from autoclaw.definitions.authoring.contracts import DefinitionDraftMode
from autoclaw.definitions.contracts import (
    DefinitionContent,
    DefinitionKind,
    PolicyDefinitionFile,
    PolicyDefinitionInput,
    RoleDefinitionFile,
    RoleDefinitionInput,
    WorkflowDefinitionFile,
    WorkflowDefinitionInput,
)
from autoclaw.runtime.errors import missing_resource_error

DEFINITION_DRAFT_DIRECTORY_NAMES: dict[DefinitionKind, str] = {
    DefinitionKind.ROLE: "roles",
    DefinitionKind.POLICY: "policies",
    DefinitionKind.WORKFLOW: "workflows",
}


class StoredDraftBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_no: int | None = Field(default=None, ge=1)
    content_hash: str | None = None
    source_path: str | None = None


class StoredDefinitionDraftMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DefinitionKind
    key: str
    mode: DefinitionDraftMode
    created_at: datetime
    updated_at: datetime
    draft_path: str
    normalized_path: str
    body_format: str = "yaml"
    content_hash: str
    based_on: StoredDraftBaseline = Field(default_factory=StoredDraftBaseline)
    baseline_body: str | None = None
    baseline_normalized_content: dict[str, Any] | None = None


class StoredDefinitionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: StoredDefinitionDraftMetadata
    body: str
    normalized_content: dict[str, Any] | None = None


def delete_stored_definition_draft(data_dir: Path, *, kind: DefinitionKind, key: str) -> None:
    if not has_stored_definition_draft(data_dir, kind=kind, key=key):
        raise missing_resource_error(f"unknown definition draft '{kind.value}:{key}'")
    root = _draft_root(data_dir)
    for relative_path in _definition_draft_relative_paths(kind, key):
        path = root / relative_path
        if path.is_file():
            path.unlink()
        _prune_empty_draft_directories(path.parent, stop_at=root)


def has_stored_definition_draft(data_dir: Path, *, kind: DefinitionKind, key: str) -> bool:
    return any(path.is_file() for path in _stored_definition_draft_paths(data_dir, kind, key))


def read_stored_definition_draft(
    data_dir: Path,
    *,
    kind: DefinitionKind,
    key: str,
) -> StoredDefinitionDraft:
    metadata_path = _existing_metadata_path(data_dir, kind, key)
    if metadata_path is None:
        body_path = _existing_body_path(data_dir, kind, key)
        if body_path is None:
            raise missing_resource_error(f"unknown definition draft '{kind.value}:{key}'")
        return _read_body_backed_definition_draft(data_dir, kind=kind, key=key, body_path=body_path)

    metadata = StoredDefinitionDraftMetadata.model_validate(
        json.loads(metadata_path.read_text(encoding="utf-8"))
    )
    body_path = _draft_root(data_dir) / metadata.draft_path
    if not body_path.is_file():
        raise missing_resource_error(f"unknown definition draft '{kind.value}:{key}'")
    return StoredDefinitionDraft(
        metadata=metadata,
        body=body_path.read_text(encoding="utf-8"),
        normalized_content=read_definition_draft_normalized_content(
            data_dir,
            kind=kind,
            key=key,
        ),
    )


def list_stored_definition_drafts(data_dir: Path) -> list[StoredDefinitionDraftMetadata]:
    metadata_root = _draft_root(data_dir) / "_metadata"
    metadata_by_identity: dict[tuple[DefinitionKind, str], StoredDefinitionDraftMetadata] = {}
    if metadata_root.is_dir():
        for metadata_path in sorted(metadata_root.glob("*/*.json")):
            metadata = StoredDefinitionDraftMetadata.model_validate(
                json.loads(metadata_path.read_text(encoding="utf-8"))
            )
            metadata_by_identity[(metadata.kind, metadata.key)] = metadata

    for kind, body_path in _iter_definition_draft_body_paths(data_dir):
        key = unquote(body_path.stem)
        identity = (kind, key)
        if identity in metadata_by_identity:
            continue
        metadata_by_identity[identity] = _build_body_backed_definition_draft_metadata(
            kind=kind,
            key=key,
            body_path=body_path,
            body=body_path.read_text(encoding="utf-8"),
        )

    return list(metadata_by_identity.values())


def write_stored_definition_draft(
    data_dir: Path,
    *,
    metadata: StoredDefinitionDraftMetadata,
    body: str,
    normalized_content: dict[str, Any] | None,
) -> None:
    root = _draft_root(data_dir)
    body_path = root / metadata.draft_path
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text(body, encoding="utf-8")

    normalized_path = root / metadata.normalized_path
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    if normalized_content is None:
        if normalized_path.exists():
            normalized_path.unlink()
    else:
        normalized_path.write_text(
            json.dumps(normalized_content, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    metadata_path = _metadata_path(data_dir, metadata.kind, metadata.key)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_definition_draft_normalized_content(
    data_dir: Path,
    *,
    kind: DefinitionKind,
    key: str,
) -> dict[str, Any] | None:
    for normalized_path in _normalized_paths(data_dir, kind, key):
        if normalized_path.is_file():
            return cast(dict[str, Any], json.loads(normalized_path.read_text(encoding="utf-8")))
    return None


def build_definition_draft_metadata(
    *,
    kind: DefinitionKind,
    key: str,
    mode: DefinitionDraftMode,
    body: str,
    based_on: StoredDraftBaseline,
    baseline_body: str | None,
    baseline_normalized_content: dict[str, Any] | None,
    created_at: datetime | None = None,
) -> StoredDefinitionDraftMetadata:
    now = utc_now()
    return StoredDefinitionDraftMetadata(
        kind=kind,
        key=key,
        mode=mode,
        created_at=created_at or now,
        updated_at=now,
        draft_path=definition_draft_relative_path(kind, key),
        normalized_path=definition_draft_normalized_relative_path(kind, key),
        body_format="yaml",
        content_hash=draft_body_content_hash(body),
        based_on=based_on,
        baseline_body=baseline_body,
        baseline_normalized_content=baseline_normalized_content,
    )


def definition_draft_relative_path(kind: DefinitionKind, key: str) -> str:
    return f"{_definition_draft_directory_name(kind)}/{_quoted_key_filename(key)}.yaml"


def definition_draft_normalized_relative_path(kind: DefinitionKind, key: str) -> str:
    return f"_normalized/{_definition_draft_directory_name(kind)}/{_quoted_key_filename(key)}.json"


def definition_draft_metadata_relative_path(kind: DefinitionKind, key: str) -> str:
    return f"_metadata/{_definition_draft_directory_name(kind)}/{_quoted_key_filename(key)}.json"


def draft_body_content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def serialize_definition_content(kind: DefinitionKind, content: DefinitionContent) -> str:
    payload = {"kind": kind.value, **content.model_dump(mode="json")}
    return yaml.safe_dump(payload, sort_keys=False)


def normalize_definition_content(content: DefinitionContent) -> dict[str, Any]:
    return content.model_dump(mode="json")


def parse_definition_body(kind: DefinitionKind, key: str, body: str) -> DefinitionContent:
    try:
        payload = yaml.safe_load(body)
    except yaml.YAMLError as exc:  # pragma: no cover - exercised through invalid YAML tests
        raise ValueError(f"invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("expected YAML mapping content")
    payload_kind = payload.get("kind")
    if payload_kind != kind.value:
        raise ValueError(
            f"draft body kind '{payload_kind}' does not match requested kind '{kind.value}'"
        )

    if kind == DefinitionKind.ROLE:
        content: DefinitionContent = RoleDefinitionInput.model_validate(
            RoleDefinitionFile.model_validate(payload).model_dump(exclude={"kind"})
        )
    elif kind == DefinitionKind.POLICY:
        content = PolicyDefinitionInput.model_validate(
            PolicyDefinitionFile.model_validate(payload).model_dump(exclude={"kind"})
        )
    else:
        content = WorkflowDefinitionInput.model_validate(
            WorkflowDefinitionFile.model_validate(payload).model_dump(exclude={"kind"})
        )
    if content.id != key:
        raise ValueError(f"draft body id '{content.id}' does not match requested key '{key}'")
    return content


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _metadata_path(data_dir: Path, kind: DefinitionKind, key: str) -> Path:
    return _draft_root(data_dir) / definition_draft_metadata_relative_path(kind, key)


def _draft_root(data_dir: Path) -> Path:
    return data_dir / "drafts" / "definitions"


def _quoted_key_filename(key: str) -> str:
    return quote(key, safe="._-")


def _read_body_backed_definition_draft(
    data_dir: Path,
    *,
    kind: DefinitionKind,
    key: str,
    body_path: Path,
) -> StoredDefinitionDraft:
    body = body_path.read_text(encoding="utf-8")
    return StoredDefinitionDraft(
        metadata=_build_body_backed_definition_draft_metadata(
            kind=kind,
            key=key,
            body_path=body_path,
            body=body,
        ),
        body=body,
        normalized_content=read_definition_draft_normalized_content(
            data_dir,
            kind=kind,
            key=key,
        )
        or _try_normalize_definition_body(kind=kind, key=key, body=body),
    )


def _build_body_backed_definition_draft_metadata(
    *,
    kind: DefinitionKind,
    key: str,
    body_path: Path,
    body: str,
) -> StoredDefinitionDraftMetadata:
    updated_at = datetime.fromtimestamp(body_path.stat().st_mtime, tz=UTC)
    normalized_content = _try_normalize_definition_body(kind=kind, key=key, body=body)
    return StoredDefinitionDraftMetadata(
        kind=kind,
        key=key,
        mode=DefinitionDraftMode.CREATE,
        created_at=updated_at,
        updated_at=updated_at,
        draft_path=definition_draft_relative_path(kind, key),
        normalized_path=definition_draft_normalized_relative_path(kind, key),
        body_format="yaml",
        content_hash=draft_body_content_hash(body),
        based_on=StoredDraftBaseline(),
        baseline_body=body,
        baseline_normalized_content=normalized_content,
    )


def _try_normalize_definition_body(
    *,
    kind: DefinitionKind,
    key: str,
    body: str,
) -> dict[str, Any] | None:
    try:
        content = parse_definition_body(kind, key, body)
    except ValueError:
        return None
    return normalize_definition_content(content)


def _definition_draft_directory_name(kind: DefinitionKind) -> str:
    return DEFINITION_DRAFT_DIRECTORY_NAMES[kind]


def _definition_draft_relative_paths(kind: DefinitionKind, key: str) -> tuple[str, ...]:
    quoted_key = _quoted_key_filename(key)
    legacy_directory = f"{kind.value}s"
    canonical_directory = _definition_draft_directory_name(kind)
    directories = _unique_strings((canonical_directory, legacy_directory))
    relative_paths: list[str] = []
    for directory in directories:
        relative_paths.append(f"{directory}/{quoted_key}.yaml")
        relative_paths.append(f"_normalized/{directory}/{quoted_key}.json")
        relative_paths.append(f"_metadata/{directory}/{quoted_key}.json")
    return tuple(relative_paths)


def _stored_definition_draft_paths(
    data_dir: Path, kind: DefinitionKind, key: str
) -> tuple[Path, ...]:
    root = _draft_root(data_dir)
    return tuple(
        root / relative_path for relative_path in _definition_draft_relative_paths(kind, key)
    )


def _body_paths(data_dir: Path, kind: DefinitionKind, key: str) -> tuple[Path, ...]:
    root = _draft_root(data_dir)
    quoted_key = _quoted_key_filename(key)
    directories = _unique_strings((_definition_draft_directory_name(kind), f"{kind.value}s"))
    return tuple(root / directory / f"{quoted_key}.yaml" for directory in directories)


def _metadata_paths(data_dir: Path, kind: DefinitionKind, key: str) -> tuple[Path, ...]:
    root = _draft_root(data_dir)
    quoted_key = _quoted_key_filename(key)
    directories = _unique_strings((_definition_draft_directory_name(kind), f"{kind.value}s"))
    return tuple(root / "_metadata" / directory / f"{quoted_key}.json" for directory in directories)


def _normalized_paths(data_dir: Path, kind: DefinitionKind, key: str) -> tuple[Path, ...]:
    root = _draft_root(data_dir)
    quoted_key = _quoted_key_filename(key)
    directories = _unique_strings((_definition_draft_directory_name(kind), f"{kind.value}s"))
    return tuple(
        root / "_normalized" / directory / f"{quoted_key}.json" for directory in directories
    )


def _existing_metadata_path(data_dir: Path, kind: DefinitionKind, key: str) -> Path | None:
    return _first_existing_path(_metadata_paths(data_dir, kind, key))


def _existing_body_path(data_dir: Path, kind: DefinitionKind, key: str) -> Path | None:
    return _first_existing_path(_body_paths(data_dir, kind, key))


def _first_existing_path(paths: tuple[Path, ...]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _iter_definition_draft_body_paths(data_dir: Path) -> list[tuple[DefinitionKind, Path]]:
    root = _draft_root(data_dir)
    paths: list[tuple[DefinitionKind, Path]] = []
    for kind in DefinitionKind:
        directories = _unique_strings((_definition_draft_directory_name(kind), f"{kind.value}s"))
        for directory in directories:
            draft_directory = root / directory
            if not draft_directory.is_dir():
                continue
            paths.extend((kind, path) for path in sorted(draft_directory.glob("*.yaml")))
    return paths


def _unique_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _prune_empty_draft_directories(path: Path, *, stop_at: Path) -> None:
    current = path
    while current != stop_at and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


__all__ = [
    "StoredDefinitionDraft",
    "StoredDefinitionDraftMetadata",
    "StoredDraftBaseline",
    "build_definition_draft_metadata",
    "definition_draft_metadata_relative_path",
    "definition_draft_normalized_relative_path",
    "definition_draft_relative_path",
    "delete_stored_definition_draft",
    "draft_body_content_hash",
    "has_stored_definition_draft",
    "list_stored_definition_drafts",
    "normalize_definition_content",
    "parse_definition_body",
    "read_definition_draft_normalized_content",
    "read_stored_definition_draft",
    "serialize_definition_content",
    "utc_now",
    "write_stored_definition_draft",
]
