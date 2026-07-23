from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    DispatchRequestModel,
    DispatchTurnModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.boundary import open_boundary_successor
from banksia.runtime.contracts import (
    CheckpointResponse,
    ReplanSuccess,
    StructuralReplanTrigger,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import (
    GetCurrentContextResponse,
    NodeOperationExecutor,
    NodeOperationScope,
)
from banksia.runtime.post_commit import BoundaryAccepted, CapturedRuntimeEffectPublisher
from banksia.runtime.replan.continuation import continue_committed_replan
from banksia.runtime.team.participation import read_accepted_green_participation
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
    seeded_task_root,
)


async def test_deep_replan_preserves_only_exact_unchanged_branch_participation(
    tmp_path: Path,
) -> None:
    suffix = "deep-participation"
    async with seeded_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        scenario = _DeepParticipationScenario(
            executor=executor,
            session_factory=session_factory,
            task_id=ids.task_id,
            initial_dispatch_id=ids.current_dispatch_id,
            task_root=seeded_task_root(tmp_path, suffix),
            dependencies=_opening_dependencies(),
        )
        await scenario.run()


@dataclass(frozen=True, slots=True)
class _ScenarioMembers:
    a: str
    b: str
    e: str
    c: str


@dataclass(frozen=True, slots=True)
class _CommittedReplan:
    source_dispatch_id: str
    result: ReplanSuccess
    previous_request: DispatchRequestModel
    current_selections: dict[str, TeamRevisionMemberModel]


@dataclass(frozen=True, slots=True)
class _DeepParticipationScenario:
    executor: NodeOperationExecutor
    session_factory: SessionFactory
    task_id: str
    initial_dispatch_id: str
    task_root: Path
    dependencies: DispatchOpeningDependencies

    async def run(self) -> None:
        members, root_dispatch = await self._create_team()
        root_dispatch = await self._establish_initial_participation(
            members,
            root_dispatch,
        )
        b_dispatch = await self._return_blocked_on_same_basis(
            members,
            root_dispatch,
        )
        replan = await self._commit_e_replan(members, b_dispatch)
        successor_dispatch = await self._verify_replan_readbacks(members, replan)
        await self._reintegrate_changed_e(members, replan, successor_dispatch)

    async def _create_team(self) -> tuple[_ScenarioMembers, str]:
        initial_replan = ReplanSuccess.model_validate(
            await self.executor.execute(
                scope=self._scope(self.initial_dispatch_id),
                operation_name="add_child",
                arguments={
                    "child": {
                        "title": "A",
                        "children": [
                            {
                                "title": "B",
                                "children": [
                                    {
                                        "title": "E",
                                        "instruction": "Inspect the original behavior.",
                                    }
                                ],
                            },
                            {"title": "C"},
                        ],
                    }
                },
            )
        )
        a_id, b_id, e_id, c_id = initial_replan.created_ids
        members = _ScenarioMembers(a=a_id, b=b_id, e=e_id, c=c_id)
        root_dispatch = await self._continue_replan(self.initial_dispatch_id)
        return members, root_dispatch

    async def _establish_initial_participation(
        self,
        members: _ScenarioMembers,
        root_dispatch: str,
    ) -> str:
        a_dispatch = await self._delegate(root_dispatch, members.a)
        c_dispatch = await self._delegate(a_dispatch, members.c)
        _assert_contributor_context(await self._context(c_dispatch))
        a_dispatch = await self._checkpoint_and_resume(c_dispatch, "green")

        b_dispatch = await self._delegate(a_dispatch, members.b)
        e_dispatch = await self._delegate(b_dispatch, members.e)
        _assert_contributor_context(await self._context(e_dispatch))
        b_dispatch = await self._checkpoint_and_resume(e_dispatch, "green")
        _assert_direct_participation(
            await self._context(b_dispatch),
            {members.e: "satisfied"},
        )

        a_dispatch = await self._checkpoint_and_resume(b_dispatch, "green")
        _assert_direct_participation(
            await self._context(a_dispatch),
            {members.b: "satisfied", members.c: "satisfied"},
        )
        return await self._checkpoint_and_resume(a_dispatch, "green")

    async def _return_blocked_on_same_basis(
        self,
        members: _ScenarioMembers,
        root_dispatch: str,
    ) -> str:
        a_dispatch = await self._delegate(root_dispatch, members.a)
        _assert_direct_participation(
            await self._context(a_dispatch),
            {members.b: "satisfied", members.c: "satisfied"},
        )
        b_dispatch = await self._delegate(a_dispatch, members.b)
        e_dispatch = await self._delegate(b_dispatch, members.e)
        b_dispatch = await self._checkpoint_and_resume(e_dispatch, "blocked")
        _assert_direct_participation(
            await self._context(b_dispatch),
            {members.e: "satisfied"},
        )

        with pytest.raises(RuntimeOperationError) as outside_subtree:
            await self.executor.execute(
                scope=self._scope(b_dispatch),
                operation_name="update_child",
                arguments={
                    "id": members.c,
                    "patch": {"instruction": "B cannot change C."},
                },
            )
        assert outside_subtree.value.code == OperationFailureCode.ILLEGAL_TARGET_RELATION
        return b_dispatch

    async def _commit_e_replan(
        self,
        members: _ScenarioMembers,
        b_dispatch: str,
    ) -> _CommittedReplan:
        previous_selections = await self._read_current_selections()
        previous_request = await self._read_dispatch_request(b_dispatch)
        assert _direct_member_instruction(previous_request.input, members.e) == (
            "Inspect the original behavior."
        )

        result = ReplanSuccess.model_validate(
            await self.executor.execute(
                scope=self._scope(b_dispatch),
                operation_name="update_child",
                arguments={
                    "id": members.e,
                    "patch": {"instruction": "Inspect the updated behavior."},
                },
            )
        )
        assert result.updated_ids == (members.e,)
        assert result.behavior == "manager"
        assert result.direct_team[0].description is None
        assert result.direct_team[0].participation == "required"
        assert {"assign_child", "update_child", "remove_child"}.issubset(result.available_actions)

        current_selections = await self._read_current_selections()
        for changed_member_id in ("root", members.a, members.b, members.e):
            assert (
                current_selections[changed_member_id].member_branch_basis_id
                != previous_selections[changed_member_id].member_branch_basis_id
            )
        assert (
            current_selections[members.c].member_branch_basis_id
            == previous_selections[members.c].member_branch_basis_id
        )
        assert (
            current_selections[members.c].member_configuration_id
            == previous_selections[members.c].member_configuration_id
        )
        assert await self._has_current_participation(current_selections[members.c])
        for invalidated_member_id in (members.a, members.b, members.e):
            assert not await self._has_current_participation(
                current_selections[invalidated_member_id]
            )

        return _CommittedReplan(
            source_dispatch_id=b_dispatch,
            result=result,
            previous_request=previous_request,
            current_selections=current_selections,
        )

    async def _verify_replan_readbacks(
        self,
        members: _ScenarioMembers,
        replan: _CommittedReplan,
    ) -> str:
        successor_dispatch = await self._continue_replan(replan.source_dispatch_id)
        current_context = await self._context(successor_dispatch)
        assert current_context.continuation is not None
        trigger = cast(
            StructuralReplanTrigger,
            current_context.continuation.trigger,
        )
        assert trigger.kind == "structural_replan"
        assert trigger.result.replan == replan.result
        assert current_context.current_member.behavior == "manager"
        assert current_context.current_member.description is None
        assert current_context.direct_team == replan.result.direct_team
        assert current_context.available_actions == replan.result.available_actions
        assert current_context.direct_team[0].description is None
        assert current_context.direct_team[0].instruction == ("Inspect the updated behavior.")
        assert current_context.direct_team[0].participation == "required"

        manifest = (self.task_root / "manifest.md").read_text(encoding="utf-8")
        assert all(
            f"`{member_id}`" in manifest
            for member_id in (members.a, members.b, members.e, members.c)
        )
        assert "Instruction: Inspect the updated behavior." in manifest
        current_request = await self._read_dispatch_request(replan.source_dispatch_id)
        assert current_request.input == replan.previous_request.input
        successor_request = await self._read_dispatch_request(successor_dispatch)
        successor_xml = ElementTree.fromstring(successor_request.input)
        assert successor_xml.find("current_member/description") is None

        with pytest.raises(RuntimeOperationError) as missing_e:
            await self.executor.execute(
                scope=self._scope(successor_dispatch),
                operation_name="checkpoint",
                arguments={
                    "summary": "The changed branch is not yet reintegrated.",
                    "outcome": "green",
                },
            )
        assert missing_e.value.code == OperationFailureCode.BOUNDARY_PRECONDITION_FAILED
        assert members.e in missing_e.value.summary
        return successor_dispatch

    async def _reintegrate_changed_e(
        self,
        members: _ScenarioMembers,
        replan: _CommittedReplan,
        successor_dispatch: str,
    ) -> None:
        e_dispatch = await self._delegate(successor_dispatch, members.e)
        _assert_contributor_context(await self._context(e_dispatch))
        b_dispatch = await self._checkpoint_and_resume(e_dispatch, "green")
        _assert_direct_participation(
            await self._context(b_dispatch),
            {members.e: "satisfied"},
        )
        completed = CheckpointResponse.model_validate(
            await self.executor.execute(
                scope=self._scope(b_dispatch),
                operation_name="checkpoint",
                arguments={
                    "summary": "The changed E branch is reintegrated.",
                    "outcome": "green",
                },
            )
        )
        assert completed.terminal is True
        assert await self._has_current_participation(replan.current_selections[members.b])

    async def _delegate(self, parent_dispatch_id: str, child_id: str) -> str:
        async with self.session_factory() as session:
            parent_dispatch = await session.get(
                DispatchTurnModel,
                parent_dispatch_id,
            )
        assert parent_dispatch is not None
        await self.executor.execute(
            scope=self._scope(parent_dispatch_id),
            operation_name="assign_child",
            arguments={
                "expected_structural_revision_id": parent_dispatch.flow_revision_id,
                "payload": {
                    "child_node_key": child_id,
                    "assignment": {"prompt": f"Complete the {child_id} contribution."},
                },
            },
        )
        await self.executor.execute(
            scope=self._scope(parent_dispatch_id),
            operation_name="return_boundary",
            arguments={"boundary": "yield"},
        )
        return await self._open_boundary_successor(parent_dispatch_id)

    async def _checkpoint_and_resume(self, dispatch_id: str, outcome: str) -> str:
        await self.executor.execute(
            scope=self._scope(dispatch_id),
            operation_name="checkpoint",
            arguments={
                "summary": f"The {dispatch_id} contribution returned {outcome}.",
                "outcome": outcome,
            },
        )
        return await self._open_boundary_successor(dispatch_id)

    async def _open_boundary_successor(self, source_dispatch_id: str) -> str:
        async with self.session_factory() as session:
            opened = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=BoundaryAccepted(source_dispatch_id),
                dependencies=self.dependencies,
            )
        assert opened.outcome == "opened"
        assert opened.dispatch_id is not None
        return opened.dispatch_id

    async def _continue_replan(self, source_dispatch_id: str) -> str:
        async with self.session_factory() as session:
            transition = await session.scalar(
                select(ReplanTransitionModel).where(
                    ReplanTransitionModel.source_dispatch_id == source_dispatch_id
                )
            )
            assert transition is not None
            opened = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=transition.replan_transition_id,
                dependencies=self.dependencies,
            )
        assert opened.outcome == "opened"
        assert opened.dispatch_id is not None
        return opened.dispatch_id

    async def _context(self, dispatch_id: str) -> GetCurrentContextResponse:
        return GetCurrentContextResponse.model_validate(
            await self.executor.execute(
                scope=self._scope(dispatch_id),
                operation_name="get_current_context",
                arguments={},
            )
        )

    async def _read_current_selections(self) -> dict[str, TeamRevisionMemberModel]:
        async with self.session_factory() as session:
            task = await session.get(TaskModel, self.task_id)
            assert task is not None
            selections = tuple(
                await session.scalars(
                    select(TeamRevisionMemberModel).where(
                        TeamRevisionMemberModel.task_id == self.task_id,
                        TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    )
                )
            )
        return {selection.member_id: selection for selection in selections}

    async def _read_dispatch_request(self, dispatch_id: str) -> DispatchRequestModel:
        async with self.session_factory() as session:
            request = cast(
                DispatchRequestModel | None,
                await session.get(DispatchRequestModel, dispatch_id),
            )
        assert request is not None
        return request

    async def _has_current_participation(
        self,
        selection: TeamRevisionMemberModel,
    ) -> bool:
        async with self.session_factory() as session:
            return await read_accepted_green_participation(
                cast(AsyncSession, session),
                task_id=self.task_id,
                member_id=selection.member_id,
                member_configuration_id=selection.member_configuration_id,
                member_branch_basis_id=selection.member_branch_basis_id,
            )

    def _scope(self, dispatch_id: str) -> NodeOperationScope:
        return NodeOperationScope(task_id=self.task_id, dispatch_id=dispatch_id)


def _assert_contributor_context(context: GetCurrentContextResponse) -> None:
    assert context.current_member.behavior == "contributor"
    assert context.direct_team == ()
    assert "add_child" in context.available_actions
    assert not {"assign_child", "update_child", "remove_child"}.intersection(
        context.available_actions
    )


def _assert_direct_participation(
    context: GetCurrentContextResponse,
    expected: dict[str, str],
) -> None:
    assert context.current_member.behavior == "manager"
    assert {member.id: member.participation for member in context.direct_team} == expected


def _direct_member_instruction(input_text: str, member_id: str) -> str | None:
    root = ElementTree.fromstring(input_text)
    for member in root.findall("direct_team/member"):
        if member.findtext("id") == member_id:
            return member.findtext("instruction")
    raise AssertionError(f"direct Member {member_id!r} is absent from Dispatch input")


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
