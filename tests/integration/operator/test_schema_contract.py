from __future__ import annotations

from oh_my_subagents.persistence import RuntimeBase
from oh_my_subagents.persistence.models import operator as operator_models


def test_operator_core_has_exactly_two_durable_records() -> None:
    operator_tables = {
        table_name
        for table_name in RuntimeBase.metadata.tables
        if table_name.startswith("operator_")
    }

    assert operator_tables == {
        "operator_conversations",
        "operator_conversation_entries",
    }
    assert operator_models.__all__ == [
        "OperatorConversationEntryModel",
        "OperatorConversationModel",
    ]


def test_operator_core_columns_exclude_rejected_wrapper_concepts() -> None:
    assert set(RuntimeBase.metadata.tables["operator_conversations"].c.keys()) == {
        "conversation_id",
        "provider",
        "model",
        "effort",
        "provider_thread_id",
        "state",
        "active_turn_id",
        "create_idempotency_key",
        "created_at",
        "updated_at",
    }
    assert set(RuntimeBase.metadata.tables["operator_conversation_entries"].c.keys()) == {
        "entry_id",
        "conversation_id",
        "sequence",
        "kind",
        "body_json",
        "request_idempotency_key",
        "request_digest",
        "created_at",
    }

    serialized = repr(RuntimeBase.metadata.tables).casefold()
    for forbidden in (
        "operator_invocation",
        "operator_effect",
        "operator_proposal",
        "operator_confirmation",
        "operator_retry",
        "operator_queue",
        "operator_coordinator",
        "provider_call_id",
    ):
        assert forbidden not in serialized


def test_entry_order_uses_one_unique_constraint_without_redundant_index() -> None:
    entry_table = RuntimeBase.metadata.tables["operator_conversation_entries"]

    assert entry_table.indexes == set()
