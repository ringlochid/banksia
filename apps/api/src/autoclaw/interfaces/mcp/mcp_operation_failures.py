from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any, ClassVar

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.tools.tool_manager import ToolManager
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import CallToolResult, Icon, TextContent, ToolAnnotations
from pydantic import ValidationError as PydanticValidationError

from autoclaw.interfaces.http.contracts.operation_failure import OperationFailure
from autoclaw.interfaces.http.errors import operation_failure, runtime_exception_failure
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode

OPERATION_FAILURE_OUTPUT_SCHEMA = OperationFailure.model_json_schema()


class ContractFastMCP(FastMCP[Any]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tool_manager = _ContractToolManager(
            warn_on_duplicate_tools=self.settings.warn_on_duplicate_tools
        )


class _ContractToolManager(ToolManager):
    def _add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> Tool:
        tool = _ContractTool.from_function(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=icons,
            meta=meta,
            structured_output=structured_output,
        )
        output_schema = getattr(tool, "output_schema", None)
        if isinstance(output_schema, dict):
            tool_dict: dict[str, Any] = tool.__dict__  # pyright: ignore[reportAssignmentType]
            tool_dict["output_schema"] = success_or_failure_output_schema(output_schema)
        existing = self.get_tool(tool.name)
        if existing is not None:
            return existing
        self._tools[tool.name] = tool  # pyright: ignore[reportIndexIssue]
        return tool

    add_tool: ClassVar[Callable[..., Tool]] = _add_tool


class _ContractTool(Tool):
    async def _run(
        self,
        arguments: dict[str, Any],
        context: Any = None,
        convert_result: bool = False,
    ) -> Any:
        try:
            result = await self.fn_metadata.call_fn_with_arg_validation(
                self.fn,
                self.is_async,
                arguments,
                {self.context_kwarg: context} if self.context_kwarg is not None else None,
            )
            if convert_result:
                return _convert_mcp_result(self, result)
            return result
        except UrlElicitationRequiredError:
            raise
        except PydanticValidationError as exc:
            return operation_failure_tool_result(validation_operation_failure(exc))
        except Exception as exc:
            return operation_failure_tool_result(runtime_operation_failure(exc))

    run: ClassVar[Callable[..., Any]] = _run


def success_or_failure_output_schema(success_schema: dict[str, Any]) -> dict[str, Any]:
    success_variant = deepcopy(success_schema)
    failure_variant = deepcopy(OPERATION_FAILURE_OUTPUT_SCHEMA)
    merged_defs: dict[str, Any] = {}

    for variant in (success_variant, failure_variant):
        defs = variant.pop("$defs", None)
        if not isinstance(defs, dict):
            continue
        for key, value in defs.items():
            existing = merged_defs.get(key)
            if existing is not None and existing != value:
                raise ValueError(f"conflicting schema definition for '{key}'")
            merged_defs[key] = deepcopy(value)

    union_schema: dict[str, Any] = {
        "type": "object",
        "oneOf": [success_variant, failure_variant],
    }
    title = success_schema.get("title")
    if isinstance(title, str):
        union_schema["title"] = title
    if merged_defs:
        union_schema["$defs"] = merged_defs
    return union_schema


def operation_failure_tool_result(failure: OperationFailure) -> CallToolResult:
    payload = failure.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=failure.summary)],
        structuredContent=payload,
        isError=True,
    )


def runtime_operation_failure(exc: Exception) -> OperationFailure:
    _status_code, failure = runtime_exception_failure(exc)
    return failure


def validation_operation_failure(exc: PydanticValidationError) -> OperationFailure:
    first_error = exc.errors()[0] if exc.errors() else None
    loc = first_error.get("loc", ()) if first_error is not None else ()
    field_path = ".".join(str(part) for part in loc) or None
    return operation_failure(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary="request shape does not match the canonical runtime surface",
        is_retryable=False,
        field_path=field_path,
        suggested_next_step=(
            "Reread the canonical request shape and resend the request with only the live "
            "required fields."
        ),
    )


def _convert_mcp_result(tool: Tool, result: Any) -> Any:
    if isinstance(result, CallToolResult):
        return result
    return tool.fn_metadata.convert_result(result)


__all__ = [
    "OPERATION_FAILURE_OUTPUT_SCHEMA",
    "ContractFastMCP",
    "operation_failure_tool_result",
    "runtime_operation_failure",
    "success_or_failure_output_schema",
    "validation_operation_failure",
]
