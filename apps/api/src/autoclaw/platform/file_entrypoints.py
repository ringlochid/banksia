from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from autoclaw.definitions.contracts import (
    DefinitionContent,
    DefinitionKind,
    DefinitionUploadRequest,
    PolicyDefinitionFile,
    PolicyDefinitionInput,
    RoleDefinitionFile,
    RoleDefinitionInput,
    WorkflowDefinitionFile,
    WorkflowDefinitionInput,
)
from autoclaw.runtime.contracts import TaskStartRequest


def definition_upload_request_from_path(path_value: str | Path) -> DefinitionUploadRequest:
    payload = load_yaml_mapping(path_value)
    kind = DefinitionKind(payload["kind"])
    content: DefinitionContent
    if kind == DefinitionKind.ROLE:
        content = RoleDefinitionInput.model_validate(
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
    return DefinitionUploadRequest(kind=kind, content=content)


def task_start_request_from_path(path_value: str | Path) -> TaskStartRequest:
    return TaskStartRequest.model_validate(load_yaml_mapping(path_value))


def load_yaml_mapping(path_value: str | Path) -> dict[str, Any]:
    path = resolved_input_path(path_value)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping content in '{path}'")
    return cast(dict[str, Any], payload)


def resolved_input_path(path_value: str | Path) -> Path:
    return Path(path_value).expanduser().resolve()


__all__ = [
    "definition_upload_request_from_path",
    "load_yaml_mapping",
    "resolved_input_path",
    "task_start_request_from_path",
]
