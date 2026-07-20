from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from autoclaw.definitions.contracts import DefinitionUploadRequest
from autoclaw.definitions.registry.definition_catalog import (
    get_definition_detail,
    upload_definition,
)
from autoclaw.definitions.registry.revisions.ids import canonical_content_hash
from autoclaw.interfaces.cli.support import coerce_path, command_env, print_json
from autoclaw.persistence.session_operations import read_session_operation
from autoclaw.platform.file_entrypoints import definition_upload_request_from_path
from autoclaw.runtime.errors import RuntimeOperationError


class DefinitionImportOverwriteMode(StrEnum):
    REJECT = "reject"
    ALLOW_NEW_REVISION = "allow_new_revision"


@dataclass(frozen=True)
class DefinitionImportResult:
    path: str
    kind: str | None
    key: str | None
    status: Literal["imported", "unchanged", "rejected"]
    revision_no: int | None = None
    reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "key": self.key,
            "status": self.status,
            "revision_no": self.revision_no,
            "reason": self.reason,
        }


async def cmd_definitions_import(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    overwrite = DefinitionImportOverwriteMode(args.overwrite)
    file_paths = _definition_files_for_import(args.file)
    if not file_paths:
        raise FileNotFoundError(
            "no top-level .yaml definition files found in the current directory"
        )

    results: list[DefinitionImportResult] = []
    with command_env(config_path=config_path):
        for path in file_paths:
            try:
                results.append(await _import_definition_file(path, overwrite=overwrite))
            except Exception as exc:
                results.append(
                    DefinitionImportResult(
                        path=str(path),
                        kind=None,
                        key=None,
                        status="rejected",
                        reason=_exception_summary(exc),
                    )
                )

    payload = _payload_for_results(
        mode="file" if args.file is not None else "scan",
        overwrite=overwrite,
        results=results,
    )
    if args.json:
        print_json(payload)
    else:
        _print_human_results(results)
    return 0 if payload["ok"] else 1


def _exception_summary(exc: Exception) -> str:
    if isinstance(exc, RuntimeOperationError):
        return exc.summary
    return str(exc)


def _definition_files_for_import(file_path: str | None) -> list[Path]:
    if file_path is not None:
        return [coerce_path(file_path)]
    return sorted(path.resolve() for path in Path.cwd().glob("*.yaml"))


async def _current_definition_hash(
    request: DefinitionUploadRequest,
) -> tuple[int | None, str | None]:
    try:
        current = await read_session_operation(
            lambda session: get_definition_detail(session, request.kind, request.content.id)
        )
    except FileNotFoundError:
        return None, None
    return current.revision_no, canonical_content_hash(current.content.model_dump(mode="json"))


async def _import_definition_file(
    path: Path,
    *,
    overwrite: DefinitionImportOverwriteMode,
) -> DefinitionImportResult:
    request = definition_upload_request_from_path(path)
    content_hash = canonical_content_hash(request.content.model_dump(mode="json"))
    current_revision_no, current_hash = await _current_definition_hash(request)
    if current_hash == content_hash:
        return DefinitionImportResult(
            path=str(path),
            kind=request.kind.value,
            key=request.content.id,
            status="unchanged",
            revision_no=current_revision_no,
        )
    if current_hash is not None and overwrite == DefinitionImportOverwriteMode.REJECT:
        return DefinitionImportResult(
            path=str(path),
            kind=request.kind.value,
            key=request.content.id,
            status="rejected",
            revision_no=current_revision_no,
            reason=(
                f"current {request.kind.value} '{request.content.id}' already exists "
                "with different content"
            ),
        )

    result = await upload_definition(request)
    return DefinitionImportResult(
        path=str(path),
        kind=request.kind.value,
        key=request.content.id,
        status="imported" if result.created else "unchanged",
        revision_no=result.detail.revision_no,
    )


def _payload_for_results(
    *,
    mode: str,
    overwrite: DefinitionImportOverwriteMode,
    results: list[DefinitionImportResult],
) -> dict[str, Any]:
    return {
        "ok": not any(result.status == "rejected" for result in results),
        "mode": mode,
        "overwrite": overwrite.value,
        "results": [result.to_payload() for result in results],
    }


def _print_human_results(results: list[DefinitionImportResult]) -> None:
    imported = [result for result in results if result.status == "imported"]
    unchanged = [result for result in results if result.status == "unchanged"]
    rejected = [result for result in results if result.status == "rejected"]
    print(
        f"definitions import: {len(imported)} imported, "
        f"{len(unchanged)} unchanged, {len(rejected)} rejected"
    )
    for result in results:
        label = result.kind or "unknown"
        key = result.key or "-"
        suffix = f" revision {result.revision_no}" if result.revision_no is not None else ""
        if result.reason:
            print(f"{result.status}: {label} {key} <- {result.path}")
            print(f"reason: {result.reason}")
            continue
        print(f"{result.status}: {label} {key}{suffix} <- {result.path}")


__all__ = ["cmd_definitions_import"]
