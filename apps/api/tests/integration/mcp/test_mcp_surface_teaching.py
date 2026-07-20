from __future__ import annotations

from autoclaw.runtime.node_operations import NODE_OPERATION_CATALOG


def test_node_operation_catalog_owns_provider_neutral_teaching_metadata() -> None:
    assert len(NODE_OPERATION_CATALOG) == 16
    for descriptor in NODE_OPERATION_CATALOG:
        assert descriptor.title.strip()
        assert descriptor.description.strip()
        assert "session_key" not in descriptor.description
        assert "callback" not in descriptor.description.casefold()
