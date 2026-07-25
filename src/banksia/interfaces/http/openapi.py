from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import FastAPI

from banksia.interfaces.http.router import api_router
from banksia.interfaces.http.support import create_support_app
from banksia.runtime.product.paths import build_product_api_path

type OpenApiSurface = Literal["product", "support"]

PRODUCT_ROUTE_METHODS: dict[str, frozenset[str]] = {
    build_product_api_path(path): methods
    for path, methods in {
        "/workflows": frozenset({"get"}),
        "/workflows/authoring-options": frozenset({"get"}),
        "/workflows/{workflow_id}": frozenset({"get"}),
        "/workflow-drafts": frozenset({"post"}),
        "/workflow-drafts/{draft_id}": frozenset({"get", "patch", "delete"}),
        "/workflow-drafts/{draft_id}/validate": frozenset({"post"}),
        "/workflow-drafts/{draft_id}/undo": frozenset({"post"}),
        "/workflow-drafts/{draft_id}/publish": frozenset({"post"}),
        "/tasks": frozenset({"get", "post"}),
        "/tasks/{task_id}": frozenset({"get"}),
        "/tasks/{task_id}/controls/{action_id}": frozenset({"post"}),
        "/tasks/{task_id}/activities": frozenset({"get"}),
        "/tasks/{task_id}/activities/stream": frozenset({"get"}),
        "/tasks/{task_id}/human-requests/{request_id}": frozenset({"get"}),
        "/tasks/{task_id}/human-requests/{request_id}/responses": frozenset({"post"}),
        "/tasks/{task_id}/command-runs/{command_id}": frozenset({"get"}),
        "/tasks/{task_id}/command-runs/{command_id}/output": frozenset({"get"}),
        "/tasks/{task_id}/command-runs/{command_id}/cancel": frozenset({"post"}),
        "/operator/status": frozenset({"get"}),
        "/operator/conversations": frozenset({"get", "post"}),
        "/operator/conversations/{conversation_id}": frozenset({"get"}),
        "/operator/conversations/{conversation_id}/messages": frozenset({"post"}),
        (
            "/operator/conversations/{conversation_id}/question-sets/{question_set_id}/answers"
        ): frozenset({"post"}),
        ("/operator/conversations/{conversation_id}/confirmations/{confirmation_id}"): frozenset(
            {"post"}
        ),
        "/operator/conversations/{conversation_id}/retries": frozenset({"post"}),
    }.items()
}
PRODUCT_PATHS = frozenset(PRODUCT_ROUTE_METHODS)
SUPPORT_PATHS = frozenset(
    {
        "/support/openapi.json",
        "/support/tasks",
        "/support/tasks/{task_id}",
        "/support/tasks/{task_id}/trace",
        "/support/tasks/{task_id}/events",
        "/support/tasks/{task_id}/events/stream",
    }
)
SUPPORT_ROUTE_METHODS = {path: frozenset({"get"}) for path in SUPPORT_PATHS}
_HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put", "trace"})
FORBIDDEN_PRODUCT_SCHEMA_TERMS = (
    "assignment_id",
    "attempt_id",
    "boundary_id",
    "control_revision",
    "dispatch_id",
    "event_id",
    "event_seq",
    "event_source",
    "event_type",
    "event_hash",
    "payload",
    "prev_event_hash",
    "provider_route",
    "provider_start_revision",
    "team_revision_id",
    "current_team_revision_id",
    "member_configuration_id",
    "member_branch_basis_id",
    "result_boundary_id",
    "root_assignment_id",
    "source_dispatch_id",
    "successor_dispatch_id",
    "checkpoint_id",
    "wave_id",
    "delegation_wave_id",
    "ownership_revision",
    "process_metadata_json",
    "command_spec_json",
    "actor_ref",
    "task_root_path",
    "output_path",
    "argv",
    "cwd",
    "exit_code",
    "internal_storage_locator",
    "trace",
    "watchdog",
)
_FORBIDDEN_PRODUCT_MODEL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"support",
        r"controller",
        r"runtime",
        r"taskevent",
        r"dispatch",
        r"assignment",
        r"attempt",
        r"acceptedboundary",
        r"delegationwave",
        r"checkpoint",
        r"commandrunrecord",
    )
)


def build_openapi_document(surface: OpenApiSurface = "product") -> dict[str, Any]:
    product = build_product_openapi_document()
    support = build_support_openapi_document()
    validate_openapi_separation(product, support)
    return product if surface == "product" else support


def build_product_openapi_document() -> dict[str, Any]:
    app = FastAPI(title="Banksia Product API", version="0.0.0")
    app.include_router(api_router)
    document = app.openapi()
    _require_exact_routes(
        document,
        expected_paths=PRODUCT_PATHS,
        expected_methods=PRODUCT_ROUTE_METHODS,
        surface="product",
    )
    _require_product_schema_clean(document)
    return document


def build_support_openapi_document() -> dict[str, Any]:
    app = create_support_app(
        credential="openapi-generation-only-" + "x" * 48,
        version="0.0.0",
    )
    document = app.openapi()
    _require_exact_routes(
        document,
        expected_paths=SUPPORT_PATHS,
        expected_methods=SUPPORT_ROUTE_METHODS,
        surface="support",
    )
    return document


def validate_openapi_separation(
    product: dict[str, Any],
    support: dict[str, Any],
) -> None:
    product_paths = set(product.get("paths", {}))
    support_paths = set(support.get("paths", {}))
    overlap = product_paths & support_paths
    if overlap:
        raise ValueError(f"product and support OpenAPI paths overlap: {sorted(overlap)}")
    product_schemas = product.get("components", {}).get("schemas", {})
    leaked_support_models = sorted(name for name in product_schemas if name.startswith("Support"))
    if leaked_support_models:
        raise ValueError(
            f"support schemas are reachable from product OpenAPI: {leaked_support_models}"
        )
    _require_product_schema_clean(product)


def _require_exact_routes(
    document: dict[str, Any],
    *,
    expected_paths: frozenset[str],
    expected_methods: dict[str, frozenset[str]],
    surface: str,
) -> None:
    actual = frozenset(document.get("paths", {}))
    if actual != expected_paths:
        raise ValueError(
            f"{surface} OpenAPI route drift: "
            f"missing={sorted(expected_paths - actual)} "
            f"extra={sorted(actual - expected_paths)}"
        )
    for path, path_item in document["paths"].items():
        actual_methods = frozenset(path_item) & _HTTP_METHODS
        if actual_methods != expected_methods[path]:
            raise ValueError(
                f"{surface} OpenAPI method drift at {path}: "
                f"expected={sorted(expected_methods[path])} "
                f"actual={sorted(actual_methods)}"
            )


def _require_product_schema_clean(document: dict[str, Any]) -> None:
    reachable = _reachable_product_schemas(document)
    leaked_models = sorted(
        name
        for name in reachable
        if any(pattern.search(name) for pattern in _FORBIDDEN_PRODUCT_MODEL_PATTERNS)
    )
    if leaked_models:
        raise ValueError(f"forbidden reachable product OpenAPI models: {leaked_models}")
    forbidden_properties = set(FORBIDDEN_PRODUCT_SCHEMA_TERMS)
    leaked_properties: set[str] = set()
    schemas = document.get("components", {}).get("schemas", {})
    for name in reachable:
        schema = schemas.get(name)
        if isinstance(schema, dict):
            leaked_properties.update(
                property_name
                for property_name in _schema_property_names(schema)
                if property_name in forbidden_properties
            )
    if leaked_properties:
        raise ValueError(
            f"forbidden reachable product OpenAPI properties: {sorted(leaked_properties)}"
        )


def _reachable_product_schemas(document: dict[str, Any]) -> frozenset[str]:
    roots: list[object] = []
    for path_item in document.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        roots.extend(
            operation
            for method, operation in path_item.items()
            if method in _HTTP_METHODS and isinstance(operation, dict)
        )
    reachable: set[str] = set()
    visited_refs: set[str] = set()
    queue = roots
    while queue:
        value = queue.pop()
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/") and ref not in visited_refs:
                visited_refs.add(ref)
                target = _resolve_local_ref(document, ref)
                if target is not None:
                    queue.append(target)
                schema_prefix = "#/components/schemas/"
                if ref.startswith(schema_prefix):
                    reachable.add(_decode_json_pointer_token(ref.removeprefix(schema_prefix)))
            queue.extend(item for key, item in value.items() if key != "$ref")
        elif isinstance(value, list):
            queue.extend(value)
    return frozenset(reachable)


def _resolve_local_ref(document: dict[str, Any], ref: str) -> object | None:
    current: object = document
    for token in ref.removeprefix("#/").split("/"):
        if not isinstance(current, dict):
            return None
        current = current.get(_decode_json_pointer_token(token))
        if current is None:
            return None
    return current


def _decode_json_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _schema_property_names(schema: object) -> set[str]:
    names: set[str] = set()
    queue = [schema]
    while queue:
        value = queue.pop()
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                names.update(properties)
            queue.extend(value.values())
        elif isinstance(value, list):
            queue.extend(value)
    return names


__all__ = [
    "FORBIDDEN_PRODUCT_SCHEMA_TERMS",
    "PRODUCT_PATHS",
    "PRODUCT_ROUTE_METHODS",
    "SUPPORT_PATHS",
    "SUPPORT_ROUTE_METHODS",
    "build_openapi_document",
    "build_product_openapi_document",
    "build_support_openapi_document",
    "validate_openapi_separation",
]
