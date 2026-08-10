from __future__ import annotations

import base64
import json
from datetime import datetime
from secrets import token_urlsafe
from typing import Literal, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import CommandRunModel
from banksia.runtime.clock import utc_now
from banksia.runtime.command_run.service import (
    cancel_command_run,
    list_command_runs,
    read_command_run_log,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.primitives import TaskEventSource
from banksia.runtime.contracts.task import (
    CommandRunCancelReceipt,
    CommandRunCancelRequest,
    CommandRunOutputPage,
    CommandRunPage,
    CommandRunProductState,
    CommandRunView,
    ProductAction,
    ProductActionConfirmation,
    TaskMemberReference,
)
from banksia.runtime.errors import RuntimeOperationError, missing_resource_error
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.product.action_ids import product_action_id
from banksia.runtime.product.paths import build_product_api_path
from banksia.runtime.product.presenters import (
    read_source_member_reference,
    read_source_member_references,
)

_OUTPUT_CURSOR_PREFIX = "output."
_PRODUCT_LIST_CURSOR_PREFIX = "command-history."
_MAX_PRODUCT_OUTPUT_BYTES = 65_536
type _SanitizerState = Literal[
    "normal",
    "escape",
    "escape_intermediate",
    "csi",
    "osc",
    "control_string",
    "osc_escape",
    "control_string_escape",
]

_ACTIONABLE_COMMAND_STATES = ("pending_start", "running", "cancellation_requested")
_BIDI_AND_SPOOFING_CONTROLS = frozenset(
    {
        "\u061c",
        "\u200e",
        "\u200f",
        "\ufeff",
        *map(chr, range(0x202A, 0x202F)),
        *map(chr, range(0x2066, 0x2070)),
    }
)


class ProductCommandRunCollection(NamedTuple):
    items: tuple[CommandRunView, ...]
    total_count: int
    is_truncated: bool


async def list_product_command_runs(
    session: AsyncSession,
    *,
    task_id: str,
    terminal_limit: int = 20,
    observed_at: datetime | None = None,
) -> ProductCommandRunCollection:
    if not 0 <= terminal_limit <= 100:
        raise ValueError("terminal managed-action limit must be between 0 and 100")
    actionable_ids = tuple(
        await session.scalars(
            select(CommandRunModel.run_id)
            .where(
                CommandRunModel.task_id == task_id,
                CommandRunModel.state.in_(_ACTIONABLE_COMMAND_STATES),
            )
            .order_by(CommandRunModel.created_at.desc(), CommandRunModel.run_id.desc())
        )
    )
    terminal_ids = tuple(
        await session.scalars(
            select(CommandRunModel.run_id)
            .where(
                CommandRunModel.task_id == task_id,
                CommandRunModel.state.not_in(_ACTIONABLE_COMMAND_STATES),
            )
            .order_by(CommandRunModel.ended_at.desc(), CommandRunModel.run_id.desc())
            .limit(terminal_limit + 1)
        )
    )
    total_count = int(
        await session.scalar(
            select(func.count())
            .select_from(CommandRunModel)
            .where(CommandRunModel.task_id == task_id)
        )
        or 0
    )
    selected_ids = (*actionable_ids, *terminal_ids[:terminal_limit])
    sources = tuple(
        await session.scalars(
            select(CommandRunModel).where(CommandRunModel.run_id.in_(selected_ids))
        )
    )
    sources_by_id = {source.run_id: source for source in sources}
    members = await read_source_member_references(
        session,
        task_id=task_id,
        source_dispatch_ids=(source.source_dispatch_id for source in sources),
    )
    effective_observed_at = observed_at or utc_now()
    return ProductCommandRunCollection(
        items=tuple(
            _present_command_run(
                source,
                member=members.get(source.source_dispatch_id),
                observed_at=effective_observed_at,
            )
            for command_id in selected_ids
            if (source := sources_by_id.get(command_id)) is not None
        ),
        total_count=total_count,
        is_truncated=len(terminal_ids) > terminal_limit,
    )


async def list_product_command_run_page(
    session: AsyncSession,
    *,
    task_id: str,
    cursor: str | None = None,
    limit: int = 50,
    observed_at: datetime | None = None,
) -> CommandRunPage:
    source_cursor = _decode_product_list_cursor(cursor, task_id=task_id)
    source_page = await list_command_runs(
        session,
        task_id=task_id,
        cursor=source_cursor,
        limit=limit,
    )
    selected_ids = tuple(item.run_id for item in source_page.items)
    sources = tuple(
        await session.scalars(
            select(CommandRunModel).where(CommandRunModel.run_id.in_(selected_ids))
        )
    )
    sources_by_id = {source.run_id: source for source in sources}
    members = await read_source_member_references(
        session,
        task_id=task_id,
        source_dispatch_ids=(source.source_dispatch_id for source in sources),
    )
    effective_observed_at = observed_at or utc_now()
    return CommandRunPage(
        items=tuple(
            _present_command_run(
                source,
                member=members.get(source.source_dispatch_id),
                observed_at=effective_observed_at,
            )
            for command_id in selected_ids
            if (source := sources_by_id.get(command_id)) is not None
        ),
        next_cursor=(
            _encode_product_list_cursor(source_page.next_cursor, task_id=task_id)
            if source_page.next_cursor is not None
            else None
        ),
    )


async def read_product_command_output(
    session: AsyncSession,
    *,
    task_id: str,
    command_id: str,
    cursor: str | None = None,
    limit: int = _MAX_PRODUCT_OUTPUT_BYTES,
) -> CommandRunOutputPage:
    if not 1 <= limit <= _MAX_PRODUCT_OUTPUT_BYTES:
        raise _invalid_output_request("Output limit must be between 1 and 65536 bytes.")
    offset, sanitizer_state = _decode_output_cursor(cursor)
    output = await read_command_run_log(
        session,
        task_id=task_id,
        run_id=command_id,
        offset=offset,
        byte_limit=limit,
        should_preserve_utf8_boundaries=True,
    )
    content, next_sanitizer_state = _sanitize_command_output_chunk(
        output.content,
        initial_state=sanitizer_state,
    )
    return CommandRunOutputPage(
        command_id=command_id,
        content=content,
        next_cursor=(
            _encode_output_cursor(
                output.next_offset,
                sanitizer_state=next_sanitizer_state,
            )
            if output.next_offset is not None
            else None
        ),
        is_output_complete=output.output_complete and output.next_offset is None,
        is_missing=output.is_missing,
        is_changed=output.is_changed,
        is_bounded=(
            offset > 0
            or output.next_offset is not None
            or (output.file_size is not None and output.file_size > output.bytes_read)
        ),
    )


async def cancel_product_command_run(
    session: AsyncSession,
    *,
    task_id: str,
    command_id: str,
    request: CommandRunCancelRequest,
    actor_ref: str | None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> CommandRunCancelReceipt:
    source = await session.scalar(
        select(CommandRunModel).where(
            CommandRunModel.task_id == task_id,
            CommandRunModel.run_id == command_id,
        )
    )
    if source is None:
        raise missing_resource_error("That managed action could not be found.")
    expected_action_id = _command_cancel_action_id(source)
    if source.state not in {"pending_start", "running"} or request.action_id != expected_action_id:
        raise _action_unavailable()
    await cancel_command_run(
        session,
        task_id=task_id,
        run_id=command_id,
        actor_ref=actor_ref,
        event_source=event_source,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    current = await read_product_command_run(
        session,
        task_id=task_id,
        command_id=command_id,
    )
    return CommandRunCancelReceipt(
        receipt_id=f"receipt.{token_urlsafe(24)}",
        status_message=("Cancellation was requested. The action may take a moment to stop."),
        command_run=current,
    )


async def read_product_command_run(
    session: AsyncSession,
    *,
    task_id: str,
    command_id: str,
    observed_at: datetime | None = None,
) -> CommandRunView:
    source = await session.scalar(
        select(CommandRunModel).where(
            CommandRunModel.task_id == task_id,
            CommandRunModel.run_id == command_id,
        )
    )
    if source is None:
        raise missing_resource_error("That managed action could not be found.")
    member = await read_source_member_reference(
        session,
        task_id=task_id,
        source_dispatch_id=source.source_dispatch_id,
    )
    return _present_command_run(
        source,
        member=member,
        observed_at=observed_at or utc_now(),
    )


def _present_command_run(
    source: CommandRunModel,
    *,
    member: TaskMemberReference | None,
    observed_at: datetime,
) -> CommandRunView:
    cancel_action = (
        _command_cancel_action(source) if source.state in {"pending_start", "running"} else None
    )
    return CommandRunView(
        id=source.run_id,
        purpose=source.summary,
        state=_product_command_state(source.state),
        member=member,
        created_at=source.created_at,
        started_at=source.started_at,
        ended_at=source.ended_at,
        elapsed_seconds=_elapsed_seconds(source, observed_at=observed_at),
        outcome_summary=source.terminal_summary,
        output_href=build_product_api_path(
            f"/tasks/{source.task_id}/command-runs/{source.run_id}/output"
        ),
        is_output_complete=source.output_complete,
        cancel_action=cancel_action,
    )


def _encode_output_cursor(
    offset: int,
    *,
    sanitizer_state: _SanitizerState,
) -> str:
    payload = json.dumps(
        {
            "offset": offset,
            "sanitizer_state": sanitizer_state,
            "version": 2,
        },
        separators=(",", ":"),
    )
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{_OUTPUT_CURSOR_PREFIX}{token}"


def _encode_product_list_cursor(run_id: str, *, task_id: str) -> str:
    payload = json.dumps(
        {"run_id": run_id, "task_id": task_id, "version": 1},
        separators=(",", ":"),
    )
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{_PRODUCT_LIST_CURSOR_PREFIX}{token}"


def _decode_product_list_cursor(cursor: str | None, *, task_id: str) -> str | None:
    if cursor is None:
        return None
    if not cursor.startswith(_PRODUCT_LIST_CURSOR_PREFIX):
        raise _invalid_command_history_request()
    try:
        token = cursor.removeprefix(_PRODUCT_LIST_CURSOR_PREFIX)
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        run_id = payload["run_id"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid_command_history_request() from exc
    if (
        payload.get("version") != 1
        or payload.get("task_id") != task_id
        or not isinstance(run_id, str)
        or not run_id
    ):
        raise _invalid_command_history_request()
    return run_id


def _decode_output_cursor(cursor: str | None) -> tuple[int, _SanitizerState]:
    if cursor is None:
        return 0, "normal"
    if not cursor.startswith(_OUTPUT_CURSOR_PREFIX):
        raise _invalid_output_request("The output cursor is no longer usable.")
    try:
        token = cursor.removeprefix(_OUTPUT_CURSOR_PREFIX)
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        offset = payload["offset"]
        sanitizer_state = payload["sanitizer_state"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid_output_request("The output cursor is no longer usable.") from exc
    allowed_states: tuple[_SanitizerState, ...] = (
        "normal",
        "escape",
        "escape_intermediate",
        "csi",
        "osc",
        "control_string",
        "osc_escape",
        "control_string_escape",
    )
    if (
        payload.get("version") != 2
        or not isinstance(offset, int)
        or offset < 0
        or sanitizer_state not in allowed_states
    ):
        raise _invalid_output_request("The output cursor is no longer usable.")
    return offset, sanitizer_state


def _sanitize_command_output_chunk(
    content: str,
    *,
    initial_state: _SanitizerState,
) -> tuple[str, _SanitizerState]:
    """Strip terminal controls while preserving ordinary Unicode and chunk state."""

    output: list[str] = []
    state = initial_state
    for character in content:
        codepoint = ord(character)
        if state == "normal":
            if character == "\x1b":
                state = "escape"
            elif character == "\x9b":
                state = "csi"
            elif character == "\x9d":
                state = "osc"
            elif character in {"\x90", "\x98", "\x9e", "\x9f"}:
                state = "control_string"
            elif character in _BIDI_AND_SPOOFING_CONTROLS:
                continue
            elif character in {"\n", "\r", "\t"}:
                output.append(character)
            elif codepoint < 0x20 or 0x7F <= codepoint <= 0x9F:
                continue
            else:
                output.append(character)
            continue

        if state == "escape":
            if character == "[":
                state = "csi"
            elif character == "]":
                state = "osc"
            elif character in {"P", "X", "^", "_"}:
                state = "control_string"
            elif 0x20 <= codepoint <= 0x2F:
                state = "escape_intermediate"
            elif character == "\x1b":
                state = "escape"
            else:
                state = "normal"
            continue

        if state == "escape_intermediate":
            if character == "\x1b":
                state = "escape"
            elif 0x30 <= codepoint <= 0x7E:
                state = "normal"
            continue

        if state == "csi":
            if character == "\x1b":
                state = "escape"
            elif 0x40 <= codepoint <= 0x7E:
                state = "normal"
            continue

        if state in {"osc", "control_string"}:
            if character == "\x07" and state == "osc":
                state = "normal"
            elif character in {"\x9c"}:
                state = "normal"
            elif character == "\x1b":
                state = "osc_escape" if state == "osc" else "control_string_escape"
            continue

        if state in {"osc_escape", "control_string_escape"}:
            if character == "\\":
                state = "normal"
            elif character == "\x1b":
                continue
            elif state == "osc_escape" and character == "\x07":
                state = "normal"
            else:
                state = "osc" if state == "osc_escape" else "control_string"
    return "".join(output), state


def _product_command_state(state: str) -> CommandRunProductState:
    if state == "pending_start":
        return "queued"
    if state == "running":
        return "running"
    if state == "cancellation_requested":
        return "cancelling"
    if state == "succeeded":
        return "succeeded"
    if state in {"failed", "abandoned"}:
        return "failed"
    if state == "timed_out":
        return "timed_out"
    if state == "cancelled":
        return "cancelled"
    raise RuntimeError("Command Run has an unsupported controller state")


def _command_cancel_action(source: CommandRunModel) -> ProductAction:
    return ProductAction(
        id=_command_cancel_action_id(source),
        kind="cancel",
        label="Cancel action",
        href=build_product_api_path(f"/tasks/{source.task_id}/command-runs/{source.run_id}/cancel"),
        confirmation=ProductActionConfirmation(
            is_required=True,
            title="Cancel this action?",
            consequence="Banksia will request that the managed process stop.",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "confirmed": {"const": True},
            },
            "required": ["action_id", "confirmed"],
            "additionalProperties": False,
        },
    )


def _command_cancel_action_id(source: CommandRunModel) -> str:
    return product_action_id(
        "command-run",
        source.task_id,
        source.run_id,
        source.state,
        source.ownership_revision,
        "cancel",
    )


def _elapsed_seconds(
    source: CommandRunModel,
    *,
    observed_at: datetime,
) -> float | None:
    if source.started_at is None:
        return None
    end = source.ended_at or observed_at
    return max(0.0, (end - source.started_at).total_seconds())


def _invalid_output_request(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reload the action output and continue from its current cursor.",
        status_code_override=400,
    )


def _invalid_command_history_request() -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary="The command-history cursor is no longer usable.",
        is_retryable=False,
        suggested_next_step="Reload the Run and read Command history from the beginning.",
        status_code_override=400,
    )


def _action_unavailable() -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary="That cancellation action is no longer available.",
        is_retryable=False,
        suggested_next_step="Reload the managed action and use its current controls.",
        status_code_override=409,
    )


__all__ = [
    "ProductCommandRunCollection",
    "cancel_product_command_run",
    "list_product_command_run_page",
    "list_product_command_runs",
    "read_product_command_output",
    "read_product_command_run",
]
