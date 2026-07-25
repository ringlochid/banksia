from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import click
import httpx
from pydantic import ValidationError

from banksia.config import format_loopback_authority, get_settings
from banksia.interfaces.cli.support import coerce_path, command_env, print_json
from banksia.runtime.contracts import TaskStartRequest
from banksia.runtime.contracts.task import TaskStartReceipt
from banksia.runtime.product.paths import build_product_api_path
from banksia.workflows.authoring_contracts import WorkflowSearchItem, WorkflowSearchResponse


class TaskStartCliError(RuntimeError):
    def __init__(self, message: str, *, kind: str, hint: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.hint = hint


async def cmd_task_start(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    sources = tuple(args.json_sources)
    if len(sources) > 1:
        raise TaskStartCliError(
            "--json accepts exactly one inline object, @file, or '-' source",
            kind="task_start_json_source_invalid",
            hint="Use one: banksia task start --json @request.json",
        )

    with command_env(config_path=config_path):
        settings = get_settings()
        base_url = f"http://{format_loopback_authority(settings.api_host, settings.api_port)}"
        async with httpx.AsyncClient(base_url=base_url, trust_env=False, timeout=30.0) as client:
            request = (
                parse_task_start_json_request(sources[0], invocation_cwd=Path.cwd())
                if sources
                else await prompt_for_task_start_request(client, invocation_cwd=Path.cwd())
            )
            response = await _post_task_start(client, request)

    if sources:
        print_json(response.model_dump(mode="json"))
    else:
        click.echo(f"Task accepted: {response.task_id}")
        click.echo(f"Workflow: {response.workflow_id} revision {response.workflow_revision}")
        click.echo(f"Workspace: {response.workspace}")
        click.echo(f"Manifest: {response.manifest}")
    return 0


def parse_task_start_json_request(
    source: str,
    *,
    invocation_cwd: Path,
) -> TaskStartRequest:
    """Parse one strict machine-mode source into a Task start request."""

    try:
        raw = _read_json_source(source)
        payload = json.loads(
            raw,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_nonfinite_json_number,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise TaskStartCliError(
            f"Task-start JSON could not be read: {exc}",
            kind="task_start_json_invalid",
            hint="Provide one strict JSON object inline, as @file, or on stdin with '-'.",
        ) from exc
    if not isinstance(payload, dict):
        raise TaskStartCliError(
            "Task-start JSON must be one object",
            kind="task_start_json_invalid",
            hint="Provide one strict JSON object inline, as @file, or on stdin with '-'.",
        )
    if payload.get("workspace") is None:
        payload["workspace"] = str(invocation_cwd.resolve())
    try:
        return TaskStartRequest.model_validate(payload)
    except ValidationError as exc:
        raise TaskStartCliError(
            _validation_message(exc),
            kind="task_start_request_invalid",
            hint="Correct the named TaskStartRequest field and retry.",
        ) from exc


async def prompt_for_task_start_request(
    client: httpx.AsyncClient,
    *,
    invocation_cwd: Path,
) -> TaskStartRequest:
    """Collect one interactive Task start request."""

    if not sys.stdin.isatty():
        raise TaskStartCliError(
            "Interactive Task start requires a terminal",
            kind="task_start_non_interactive",
            hint="Use: banksia task start --json @request.json",
        )
    workflows = await _get_published_workflows(client)
    if not workflows:
        raise TaskStartCliError(
            "No published Workflow is available",
            kind="task_start_workflow_missing",
            hint="Import and publish a Workflow, then retry Task start.",
        )
    workflow_ids = tuple(workflow.workflow_id for workflow in workflows)
    workflow = click.prompt(
        "Workflow",
        type=click.Choice(workflow_ids, case_sensitive=True),
        show_choices=True,
    )
    click.echo("Write the complete request for the selected Banksia team, then save and close.")
    prompt = click.edit(
        "",
        require_save=True,
        extension=".md",
    )
    if prompt is None or not prompt.strip():
        raise click.Abort()
    return TaskStartRequest(
        workflow=workflow,
        prompt=prompt,
        workspace=invocation_cwd,
    )


async def _get_published_workflows(
    client: httpx.AsyncClient,
) -> tuple[WorkflowSearchItem, ...]:
    published: list[WorkflowSearchItem] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        request_options = {"params": {"cursor": cursor}} if cursor is not None else {}
        response = await _request(
            client,
            "GET",
            build_product_api_path("/workflows"),
            **request_options,
        )
        try:
            catalog = WorkflowSearchResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise TaskStartCliError(
                "Controller returned an invalid Workflow catalog",
                kind="controller_response_invalid",
                hint="Check the Banksia controller version and logs.",
            ) from exc
        published.extend(item for item in catalog.items if item.published_revision_no is not None)
        cursor = catalog.next_cursor
        if cursor is None:
            return tuple(published)
        if cursor in seen_cursors:
            raise TaskStartCliError(
                "Controller returned a repeating Workflow catalog cursor",
                kind="controller_response_invalid",
                hint="Check the Banksia controller version and logs.",
            )
        seen_cursors.add(cursor)


async def _post_task_start(
    client: httpx.AsyncClient,
    request: TaskStartRequest,
) -> TaskStartReceipt:
    response = await _request(
        client,
        "POST",
        build_product_api_path("/tasks"),
        json=request.model_dump(mode="json", exclude_none=True),
    )
    try:
        return TaskStartReceipt.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise TaskStartCliError(
            "Controller returned an invalid Task-start receipt",
            kind="controller_response_invalid",
            hint="Check the Banksia controller version and logs.",
        ) from exc


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.RequestError as exc:
        raise TaskStartCliError(
            "Banksia controller is not reachable",
            kind="controller_unreachable",
            hint="Start it with `banksia service start`, then retry.",
        ) from exc
    if response.is_success:
        return response
    try:
        failure = response.json()
    except ValueError:
        failure = {}
    summary: str = (
        str(failure.get("summary"))
        if isinstance(failure, dict) and isinstance(failure.get("summary"), str)
        else f"Controller rejected Task start with HTTP {response.status_code}"
    )
    suggested: str = (
        str(failure.get("suggested_next_step"))
        if isinstance(failure, dict) and isinstance(failure.get("suggested_next_step"), str)
        else "Correct the request or controller configuration, then retry."
    )
    code: str = (
        str(failure.get("code"))
        if isinstance(failure, dict) and isinstance(failure.get("code"), str)
        else "controller_rejected"
    )
    raise TaskStartCliError(summary, kind=code, hint=suggested)


def _read_json_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    if source.startswith("@"):
        path = Path(source[1:]).expanduser()
        if not source[1:]:
            raise ValueError("@file source requires a path")
        return path.read_text(encoding="utf-8")
    return source


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _reject_nonfinite_json_number(value: str) -> object:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _validation_message(exc: ValidationError) -> str:
    finding = exc.errors(include_input=False, include_url=False)[0]
    path = ".".join(str(part) for part in finding.get("loc", ()))
    prefix = f"{path}: " if path else ""
    return f"{prefix}{finding.get('msg', 'invalid TaskStartRequest')}"


__all__ = [
    "TaskStartCliError",
    "cmd_task_start",
    "parse_task_start_json_request",
    "prompt_for_task_start_request",
]
