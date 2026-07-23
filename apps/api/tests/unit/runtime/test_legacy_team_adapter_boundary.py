from banksia.runtime.launch.legacy_team_adapter import (
    LEGACY_TEAM_ADAPTER_DELETE_AFTER,
    project_legacy_team_plan,
)
from banksia.runtime.team import plan_initial_task_team
from tests.helpers.launch_foundation import build_launch_foundation_workflow_revision


def test_private_legacy_team_adapter_has_wp09_deletion_marker() -> None:
    assert LEGACY_TEAM_ADAPTER_DELETE_AFTER == "WP-09"


def test_private_legacy_team_adapter_does_not_invent_optional_description() -> None:
    published = build_launch_foundation_workflow_revision()
    without_description = published.model_copy(
        update={
            "workflow": published.workflow.model_copy(
                update={"lead": published.workflow.lead.model_copy(update={"description": None})}
            )
        }
    )
    team = plan_initial_task_team(without_description, "task.blank-description")

    projected = project_legacy_team_plan(without_description, team)

    assert projected.nodes[0].description == ""
