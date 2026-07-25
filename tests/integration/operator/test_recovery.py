from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from banksia.operator import OperatorProviderThreadUnavailableError
from banksia.operator.contracts import OperatorMessageRequest
from banksia.persistence import (
    OperatorConversationEntryModel,
    OperatorConversationModel,
)
from banksia.runtime.clock import utc_now
from tests.helpers.operator import RecordingTurnRunner, operator_service


async def test_provider_failure_is_visible_and_duplicate_never_replays(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner((RuntimeError("secret provider failure"),))

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        interrupted = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Try this."),
            idempotency_key="message-1",
        )
        duplicate = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Try this."),
            idempotency_key="message-1",
        )

    assert interrupted.state == "interrupted"
    assert interrupted.entries[-1].kind == "turn_interrupted"
    assert "secret" not in interrupted.entries[-1].explanation
    assert duplicate == interrupted
    assert len(runner.requests) == 1


async def test_provider_thread_loss_closes_without_reconstructed_continuity(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner((OperatorProviderThreadUnavailableError(),))

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        closed = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Continue."),
            idempotency_key="message-1",
        )

    assert closed.state == "closed"
    assert [action.kind for action in closed.actions] == ["create_new_conversation"]
    assert closed.entries[-1].kind == "turn_interrupted"


async def test_startup_repair_interrupts_each_stranded_turn_once_without_provider_work(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(())

    async with operator_service(tmp_path, runner=runner) as (service, session_factory):
        now = utc_now()
        async with session_factory() as session:
            session.add(
                OperatorConversationModel(
                    conversation_id="operator-conversation.stranded",
                    provider="claude",
                    model=None,
                    effort=None,
                    provider_thread_id=None,
                    state="running",
                    active_turn_id="operator-turn.stranded",
                    create_idempotency_key="create-stranded",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                OperatorConversationEntryModel(
                    entry_id="operator-entry.input",
                    conversation_id="operator-conversation.stranded",
                    sequence=1,
                    kind="user_message",
                    body_json={"text": "Started before the restart."},
                    request_idempotency_key="message-stranded",
                    request_digest="0" * 64,
                    created_at=now,
                )
            )
            await session.commit()

        first_count = await service.repair_stranded_turns()
        second_count = await service.repair_stranded_turns()
        repaired = await service.read_conversation("operator-conversation.stranded")

        async with session_factory() as session:
            entries = (
                await session.scalars(
                    select(OperatorConversationEntryModel).where(
                        OperatorConversationEntryModel.conversation_id
                        == "operator-conversation.stranded"
                    )
                )
            ).all()

    assert first_count == 1
    assert second_count == 0
    assert repaired.state == "interrupted"
    assert [entry.kind for entry in repaired.entries] == [
        "user_message",
        "turn_interrupted",
    ]
    assert len(entries) == 2
    assert runner.requests == []
