from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal, cast

import yaml

from oh_my_subagents.interfaces.cli.support import coerce_path, command_env, print_json
from oh_my_subagents.persistence.session_operations import (
    read_session_operation,
    write_session_operation,
)
from oh_my_subagents.workflows.authoring import import_workflow_draft
from oh_my_subagents.workflows.catalog import (
    read_current_published_workflow,
    read_published_workflow_revision,
)
from oh_my_subagents.workflows.ingest import parse_workflow

type WorkflowFileFormat = Literal["json", "yaml"]


async def cmd_workflow_import(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    raw, source_format, source_label = _read_import_input(args.file, args.format)
    workflow = parse_workflow(raw, source_format=source_format)
    with command_env(config_path=config_path):
        result = await write_session_operation(
            lambda session: import_workflow_draft(
                session,
                workflow=workflow,
                expected_etag=args.expected_etag,
            )
        )
    draft = result.draft
    payload = {
        "ok": True,
        "source": source_label,
        "draft": draft.model_dump(mode="json"),
        "is_created": result.is_created,
        "undo_receipt": result.undo_receipt,
    }
    if args.json:
        print_json(payload)
    else:
        undo_note = (
            f"; Undo receipt {result.undo_receipt}" if result.undo_receipt is not None else ""
        )
        print(
            f"Workflow {draft.workflow_id!r} imported into draft {draft.draft_id} "
            f"at ETag {draft.etag}{undo_note}"
        )
    return 0


async def cmd_workflow_export(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path):
        if args.revision is None:
            published = await read_session_operation(
                lambda session: read_current_published_workflow(
                    session,
                    workflow_id=args.workflow_id,
                )
            )
        else:
            published = await read_session_operation(
                lambda session: read_published_workflow_revision(
                    session,
                    workflow_id=args.workflow_id,
                    revision_no=args.revision,
                )
            )
    output_format = _export_format(args.output, args.format)
    payload = published.workflow.model_dump(mode="json", exclude_none=True)
    rendered = _render_workflow(payload, output_format=output_format)
    if args.output in {None, "-"}:
        print(rendered, end="")
        return 0
    output_path = coerce_path(args.output)
    if output_path.exists() and not args.should_force:
        raise FileExistsError(f"Refusing to overwrite existing file without --force: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(
        f"Exported Workflow {published.workflow_id!r} revision "
        f"{published.revision_no} to {output_path}"
    )
    return 0


def _read_import_input(
    file_value: str,
    requested_format: str | None,
) -> tuple[bytes, WorkflowFileFormat, str]:
    if file_value == "-":
        if requested_format not in {"json", "yaml"}:
            raise ValueError("stdin import requires --format json or --format yaml")
        return (
            cast(bytes, sys.stdin.buffer.read()),
            cast(WorkflowFileFormat, requested_format),
            "stdin",
        )
    path = coerce_path(file_value)
    inferred = _format_from_extension(path)
    if requested_format is not None and requested_format != inferred:
        raise ValueError(
            f"--format {requested_format} conflicts with the {path.suffix!r} file extension"
        )
    return path.read_bytes(), inferred, str(path)


def _export_format(output: str | None, requested_format: str | None) -> WorkflowFileFormat:
    if output is not None and output != "-":
        inferred = _format_from_extension(Path(output))
        if requested_format is not None and requested_format != inferred:
            raise ValueError(
                f"--format {requested_format} conflicts with the {Path(output).suffix!r} "
                "file extension"
            )
        return inferred
    if requested_format not in {"json", "yaml"}:
        raise ValueError("stdout export requires --format json or --format yaml")
    return cast(WorkflowFileFormat, requested_format)


def _format_from_extension(path: Path) -> WorkflowFileFormat:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    raise ValueError("Workflow files must use .json, .yaml, or .yml")


def _render_workflow(
    payload: dict[str, object],
    *,
    output_format: WorkflowFileFormat,
) -> str:
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


__all__ = ["cmd_workflow_export", "cmd_workflow_import"]
