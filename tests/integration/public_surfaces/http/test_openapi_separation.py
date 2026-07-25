from __future__ import annotations

import json
from copy import deepcopy

import pytest

from banksia.interfaces.http.contracts.operation_failure import ProductFailureCode
from banksia.interfaces.http.openapi import (
    PRODUCT_PATHS,
    PRODUCT_ROUTE_METHODS,
    SUPPORT_PATHS,
    SUPPORT_ROUTE_METHODS,
    build_product_openapi_document,
    build_support_openapi_document,
    validate_openapi_separation,
)


def test_product_and_support_openapi_are_exact_and_graph_isolated() -> None:
    product = build_product_openapi_document()
    support = build_support_openapi_document()

    validate_openapi_separation(product, support)
    assert set(product["paths"]) == PRODUCT_PATHS
    assert all(path.startswith("/api/") for path in product["paths"])
    assert set(support["paths"]) == SUPPORT_PATHS
    assert not set(product["paths"]) & set(support["paths"])
    assert {
        path: frozenset(path_item) & frozenset({"get", "post", "patch", "delete"})
        for path, path_item in product["paths"].items()
    } == PRODUCT_ROUTE_METHODS
    assert {
        path: frozenset(path_item) & frozenset({"get", "post", "patch", "delete"})
        for path, path_item in support["paths"].items()
    } == SUPPORT_ROUTE_METHODS
    assert not any(
        name.startswith("Support") for name in product.get("components", {}).get("schemas", {})
    )

    product_schema = json.dumps(product, sort_keys=True).casefold()
    for forbidden in (
        "assignment_id",
        "attempt_id",
        "dispatch_id",
        "boundary",
        "control_revision",
        "team_revision",
        "event_hash",
        "event_payload",
        "provider_route",
        "raw_event",
        "trace",
        "watchdog",
        "wave_id",
    ):
        assert forbidden not in product_schema

    support_schema = json.dumps(support, sort_keys=True).casefold()
    assert "dispatch_id" in support_schema
    assert "event_hash" in support_schema

    product_failure_codes = product["components"]["schemas"]["ProductFailureCode"]["enum"]
    assert set(product_failure_codes) == {code.value for code in ProductFailureCode}


def test_product_openapi_guard_rejects_reachable_technical_model_mutation() -> None:
    product = build_product_openapi_document()
    support = build_support_openapi_document()
    mutated = deepcopy(product)
    mutated["components"]["schemas"]["TechnicalRuntimeRecord"] = {
        "type": "object",
        "properties": {"label": {"type": "string"}},
    }
    mutated["paths"]["/api/tasks"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] = {"$ref": "#/components/schemas/TechnicalRuntimeRecord"}

    with pytest.raises(ValueError, match="forbidden reachable product OpenAPI models"):
        validate_openapi_separation(mutated, support)


@pytest.mark.parametrize(
    "technical_property",
    ("source_dispatch_id", "internal_storage_locator"),
)
def test_product_openapi_guard_rejects_reachable_technical_property_mutation(
    technical_property: str,
) -> None:
    product = build_product_openapi_document()
    support = build_support_openapi_document()
    mutated = deepcopy(product)
    task_schema = mutated["components"]["schemas"]["TaskView"]
    task_schema["properties"][technical_property] = {"type": "string"}

    with pytest.raises(ValueError, match="forbidden reachable product OpenAPI properties"):
        validate_openapi_separation(mutated, support)
