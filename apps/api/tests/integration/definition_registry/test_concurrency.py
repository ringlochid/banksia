from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers.definition_registry_runtime import initialized_registry
from tests.integration.definition_registry.concurrency_support import (
    build_concurrency_fixture,
    run_two_writer_race,
)


@pytest.mark.parametrize("definition_kind", ["role", "policy", "workflow"])
async def test_concurrent_new_key_upserts_create_ordered_revisions(
    tmp_path: Path,
    definition_kind: str,
) -> None:
    async with initialized_registry(tmp_path) as session_factory:
        definition_key = f"concurrent-{definition_kind}-definition"
        async with session_factory() as session:
            fixture = await build_concurrency_fixture(
                session,
                definition_kind=definition_kind,
                definition_key=definition_key,
                same_key_update=False,
            )

        first_revision_no, second_revision_no = await run_two_writer_race(
            session_factory,
            definition_kind=definition_kind,
            fixture=fixture,
        )

        assert (first_revision_no, second_revision_no) == (1, 2)

        async with session_factory() as session:
            current_revision_no, current_description = await fixture.load_current_definition(
                session,
                fixture.definition_key,
            )
            revision_history = await fixture.load_revision_history(session, fixture.definition_key)

        assert current_revision_no == 2
        assert current_description == fixture.second_definition.description
        assert revision_history == [
            (1, fixture.first_definition.description),
            (2, fixture.second_definition.description),
        ]


@pytest.mark.parametrize("definition_kind", ["role", "policy", "workflow"])
async def test_concurrent_same_key_identical_definition_updates_reuse_one_new_revision(
    tmp_path: Path,
    definition_kind: str,
) -> None:
    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            fixture = await build_concurrency_fixture(
                session,
                definition_kind=definition_kind,
                same_key_update=True,
            )

        first_revision_no, second_revision_no = await run_two_writer_race(
            session_factory,
            definition_kind=definition_kind,
            fixture=fixture,
        )

        assert (first_revision_no, second_revision_no) == (2, 2)

        async with session_factory() as session:
            current_revision_no, current_description = await fixture.load_current_definition(
                session,
                fixture.definition_key,
            )
            revision_history = await fixture.load_revision_history(session, fixture.definition_key)

        assert current_revision_no == 2
        assert current_description == fixture.second_definition.description
        assert revision_history == [
            (1, fixture.original_description),
            (2, fixture.second_definition.description),
        ]
